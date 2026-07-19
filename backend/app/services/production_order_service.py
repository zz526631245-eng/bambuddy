"""Stage 8 production-order orchestration without printer dispatch."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.operation_log import OperationLog
from backend.app.models.product import Product
from backend.app.models.product_master import ProductionBOMItem
from backend.app.models.production import (
    OrderStatus,
    PlateJob,
    PlateJobStatus,
    ProductionOrder,
    ProductionRequirement,
    RequirementStatus,
)
from backend.app.models.production_recipe import ProductionRecipe
from backend.app.services.production_accounting import calculate_ledger, transition_order_status


class ProductionOrderError(ValueError):
    pass


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _recipe_snapshot(recipe: ProductionRecipe) -> dict:
    return {
        "id": recipe.id,
        "code": recipe.code,
        "name": recipe.name,
        "version": recipe.version,
        "component_id": recipe.component_id,
        "material_type_id": recipe.material_type_id,
        "printer_profile_id": recipe.printer_profile_id,
        "library_file_id": recipe.library_file_id,
        "slicer_pipeline_id": recipe.slicer_pipeline_id,
        "slicer_preset": recipe.slicer_preset,
    }


def _component_snapshot(item: ProductionBOMItem) -> dict:
    return {
        "id": item.component.id,
        "code": item.component.code,
        "name": item.component.name,
        "unit": item.component.unit,
        "description": item.component.description,
    }


async def _operation(db: AsyncSession, operation_id: str) -> OperationLog | None:
    return (
        await db.execute(select(OperationLog).where(OperationLog.operation_id == operation_id))
    ).scalar_one_or_none()


async def _load_order(db: AsyncSession, order_id: int) -> ProductionOrder | None:
    return (
        await db.execute(
            select(ProductionOrder)
            .where(ProductionOrder.id == order_id)
            .options(
                selectinload(ProductionOrder.requirements).selectinload(ProductionRequirement.plate_jobs),
            )
        )
    ).scalar_one_or_none()


async def _load_order_for_update(db: AsyncSession, order_id: int) -> ProductionOrder | None:
    """Lock an order while mutating its requirement reservations.

    PostgreSQL serializes concurrent confirmations on the order row. SQLite
    ignores ``FOR UPDATE`` and continues to rely on its single-writer lock.
    """
    return (
        await db.execute(
            select(ProductionOrder)
            .where(ProductionOrder.id == order_id)
            .with_for_update()
            .options(
                selectinload(ProductionOrder.requirements).selectinload(ProductionRequirement.plate_jobs),
            )
        )
    ).scalar_one_or_none()


async def create_order(
    db: AsyncSession,
    *,
    operation_id: str,
    order_number: str,
    product_id: int,
    quantity: int,
    priority: int,
    due_at: datetime | None,
    notes: str | None,
    actor_user_id: int | None,
) -> tuple[ProductionOrder, bool]:
    replay = await _operation(db, operation_id)
    if replay:
        if replay.operation_type != "production_order_created":
            raise ProductionOrderError("该操作编号已经用于其他操作")
        order = await _load_order(db, int((replay.payload or {})["order_id"]))
        if not order:
            raise ProductionOrderError("重复操作记录指向的订单不存在")
        return order, True

    product = (
        await db.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.bom_items).selectinload(ProductionBOMItem.component),
                selectinload(Product.recipes),
            )
        )
    ).scalar_one_or_none()
    if not product:
        raise ProductionOrderError("产品不存在")
    if not product.bom_items:
        raise ProductionOrderError("产品还没有产品零件清单，不能创建生产订单")

    recipes_by_component: dict[int, ProductionRecipe] = {}
    for recipe in product.recipes:
        if recipe.is_active and recipe.component_id is not None:
            previous = recipes_by_component.get(recipe.component_id)
            if previous is None or recipe.version > previous.version:
                recipes_by_component[recipe.component_id] = recipe

    prepared: list[tuple[ProductionBOMItem, ProductionRecipe, int]] = []
    missing: list[str] = []
    for item in product.bom_items:
        recipe = recipes_by_component.get(item.component_id)
        if not recipe:
            missing.append(item.component.name)
            continue
        exact_required = quantity * item.quantity
        required = round(exact_required)
        if abs(exact_required - required) > 1e-9:
            raise ProductionOrderError(f"零件“{item.component.name}”计算结果不是整数，请检查每套需要数量")
        prepared.append((item, recipe, required))
    if missing:
        raise ProductionOrderError("以下零件还没有打印方案：" + "、".join(missing))

    product_snapshot = {
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "description": product.description,
        "captured_at": datetime.utcnow().isoformat(),
    }
    bom_snapshot = [
        {
            "bom_item_id": item.id,
            "component": _component_snapshot(item),
            "quantity": item.quantity,
            "notes": item.notes,
        }
        for item, _, _ in prepared
    ]
    recipe_snapshot = [_recipe_snapshot(recipe) for _, recipe, _ in prepared]
    order = ProductionOrder(
        order_number=order_number,
        product_id=product_id,
        quantity=quantity,
        priority=priority,
        status=OrderStatus.PLANNED.value,
        due_at=due_at,
        notes=notes,
        created_by_id=actor_user_id,
        product_snapshot=product_snapshot,
        bom_snapshot=bom_snapshot,
        recipe_snapshot=recipe_snapshot,
    )
    db.add(order)
    try:
        await db.flush()
        for item, recipe, required in prepared:
            db.add(
                ProductionRequirement(
                    order_id=order.id,
                    recipe_id=recipe.id,
                    component_id=item.component_id,
                    unit_quantity=item.quantity,
                    required_quantity=required,
                    component_snapshot=_component_snapshot(item),
                    recipe_snapshot=_recipe_snapshot(recipe),
                )
            )
        db.add(
            OperationLog(
                operation_id=operation_id,
                operation_type="production_order_created",
                entity_type="production_order",
                entity_id=order.id,
                actor_user_id=actor_user_id,
                payload={"order_id": order.id, "order_number": order_number},
            )
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _operation(db, operation_id)
        if replay and replay.operation_type == "production_order_created":
            existing = await _load_order(db, int((replay.payload or {})["order_id"]))
            if existing:
                return existing, True
        raise
    loaded = await _load_order(db, order.id)
    assert loaded is not None
    return loaded, False


async def update_order(
    db: AsyncSession,
    order_id: int,
    *,
    priority: int | None,
    due_at: datetime | None,
    notes: str | None,
    provided_fields: Iterable[str],
) -> ProductionOrder:
    order = await db.get(ProductionOrder, order_id)
    if not order:
        raise ProductionOrderError("生产订单不存在")
    fields = set(provided_fields)
    if "priority" in fields:
        order.priority = priority  # type: ignore[assignment]
    if "due_at" in fields:
        order.due_at = due_at
    if "notes" in fields:
        order.notes = notes
    await db.commit()
    await db.refresh(order)
    return order


_ACTION_TARGET = {"pause": "paused", "resume": "planned", "cancel": "cancelled"}
_ACTION_LOG = {
    "pause": "production_order_paused",
    "resume": "production_order_resumed",
    "cancel": "production_order_cancelled",
}


async def change_order_status(
    db: AsyncSession,
    *,
    order_id: int,
    operation_id: str,
    action: str,
    actor_user_id: int | None,
) -> tuple[ProductionOrder, bool]:
    replay = await _operation(db, operation_id)
    if replay:
        if replay.entity_id != order_id or replay.operation_type != _ACTION_LOG.get(action):
            raise ProductionOrderError("该操作编号已经用于其他操作")
        order = await _load_order(db, order_id)
        if not order:
            raise ProductionOrderError("生产订单不存在")
        return order, True
    target = _ACTION_TARGET.get(action)
    if not target:
        raise ProductionOrderError("不支持的订单操作")
    order = await _load_order(db, order_id)
    if not order:
        raise ProductionOrderError("生产订单不存在")
    try:
        order.status = transition_order_status(order.status, target)
    except ValueError as exc:
        raise ProductionOrderError("当前订单状态不允许执行这个操作") from exc
    if action == "cancel":
        for requirement in order.requirements:
            requirement.status = RequirementStatus.CANCELLED.value
            requirement.reserved_quantity = 0
            for job in requirement.plate_jobs:
                if job.status not in {PlateJobStatus.COMPLETED.value, PlateJobStatus.CANCELLED.value}:
                    job.status = PlateJobStatus.CANCELLED.value
    db.add(
        OperationLog(
            operation_id=operation_id,
            operation_type=_ACTION_LOG[action],
            entity_type="production_order",
            entity_id=order.id,
            actor_user_id=actor_user_id,
            payload={"order_id": order.id, "action": action, "status": order.status},
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _operation(db, operation_id)
        if replay:
            existing = await _load_order(db, order_id)
            if existing:
                return existing, True
        raise
    loaded = await _load_order(db, order.id)
    assert loaded is not None
    return loaded, False


async def preview_plate_jobs(db: AsyncSession, order_id: int) -> tuple[ProductionOrder, list[dict]]:
    order = await _load_order(db, order_id)
    if not order:
        raise ProductionOrderError("生产订单不存在")
    if order.status != OrderStatus.PLANNED.value:
        raise ProductionOrderError("只有进行中的订单可以生成打印任务草稿")
    items: list[dict] = []
    for requirement in order.requirements:
        ledger = calculate_ledger(
            required=requirement.required_quantity,
            reserved=requirement.reserved_quantity,
            good=requirement.good_quantity,
            scrap=requirement.scrap_quantity,
        )
        if ledger.remaining <= 0:
            continue
        component = requirement.component_snapshot or {}
        recipe = requirement.recipe_snapshot or {}
        items.append(
            {
                "requirement_id": requirement.id,
                "printer_profile_id": recipe.get("printer_profile_id"),
                "planned_quantity": ledger.remaining,
                "component_name": component.get("name", f"需求 {requirement.id}"),
                "print_plan_name": recipe.get("name", f"打印方案 {requirement.recipe_id}"),
            }
        )
    return order, items


async def confirm_plate_jobs(
    db: AsyncSession,
    *,
    order_id: int,
    operation_id: str,
    items: list,
    actor_user_id: int | None,
) -> tuple[list[PlateJob], bool]:
    replay = await _operation(db, operation_id)
    if replay:
        if replay.operation_type != "plate_jobs_confirmed" or replay.entity_id != order_id:
            raise ProductionOrderError("该操作编号已经用于其他操作")
        ids = list((replay.payload or {}).get("plate_job_ids", []))
        jobs = list((await db.execute(select(PlateJob).where(PlateJob.id.in_(ids)).order_by(PlateJob.id))).scalars())
        return jobs, True
    order = await _load_order_for_update(db, order_id)
    if not order:
        raise ProductionOrderError("生产订单不存在")
    if order.status != OrderStatus.PLANNED.value:
        raise ProductionOrderError("只有进行中的订单可以确认打印任务草稿")
    requirements = {requirement.id: requirement for requirement in order.requirements}
    jobs: list[PlateJob] = []
    for item in items:
        requirement = requirements.get(item.requirement_id)
        if not requirement:
            raise ProductionOrderError("打印任务草稿包含不属于该订单的需求")
        ledger = calculate_ledger(
            required=requirement.required_quantity,
            reserved=requirement.reserved_quantity,
            good=requirement.good_quantity,
            scrap=requirement.scrap_quantity,
        )
        if item.planned_quantity > ledger.remaining:
            raise ProductionOrderError("打印任务草稿数量超过剩余需要数量")
        job = PlateJob(
            requirement_id=requirement.id,
            printer_profile_id=item.printer_profile_id,
            planned_quantity=item.planned_quantity,
            status=PlateJobStatus.DRAFT.value,
            queue_item_id=None,
        )
        db.add(job)
        requirement.reserved_quantity += item.planned_quantity
        requirement.status = RequirementStatus.IN_PROGRESS.value
        jobs.append(job)
    await db.flush()
    db.add(
        OperationLog(
            operation_id=operation_id,
            operation_type="plate_jobs_confirmed",
            entity_type="production_order",
            entity_id=order_id,
            actor_user_id=actor_user_id,
            payload={"order_id": order_id, "plate_job_ids": [job.id for job in jobs]},
        )
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _operation(db, operation_id)
        if replay:
            ids = list((replay.payload or {}).get("plate_job_ids", []))
            existing = list(
                (await db.execute(select(PlateJob).where(PlateJob.id.in_(ids)).order_by(PlateJob.id))).scalars()
            )
            return existing, True
        raise
    for job in jobs:
        await db.refresh(job)
    return jobs, False


async def order_detail(db: AsyncSession, order_id: int) -> dict:
    order = await _load_order(db, order_id)
    if not order:
        raise ProductionOrderError("生产订单不存在")
    operations = list(
        (
            await db.execute(
                select(OperationLog)
                .where(OperationLog.entity_type == "production_order", OperationLog.entity_id == order_id)
                .order_by(OperationLog.id)
            )
        ).scalars()
    )
    requirements = []
    for requirement in order.requirements:
        ledger = calculate_ledger(
            required=requirement.required_quantity,
            reserved=requirement.reserved_quantity,
            good=requirement.good_quantity,
            scrap=requirement.scrap_quantity,
        )
        requirements.append(
            {
                "id": requirement.id,
                "order_id": requirement.order_id,
                "recipe_id": requirement.recipe_id,
                "component_id": requirement.component_id,
                "unit_quantity": requirement.unit_quantity,
                "required_quantity": requirement.required_quantity,
                "reserved_quantity": requirement.reserved_quantity,
                "good_quantity": requirement.good_quantity,
                "scrap_quantity": requirement.scrap_quantity,
                "component_snapshot": requirement.component_snapshot,
                "recipe_snapshot": requirement.recipe_snapshot,
                "status": requirement.status,
                "created_at": requirement.created_at,
                "updated_at": requirement.updated_at,
                "ledger": ledger.as_dict(),
                "plate_jobs": requirement.plate_jobs,
            }
        )
    return {
        "id": order.id,
        "order_number": order.order_number,
        "product_id": order.product_id,
        "quantity": order.quantity,
        "priority": order.priority,
        "status": order.status,
        "due_at": order.due_at,
        "notes": order.notes,
        "product_snapshot": order.product_snapshot,
        "bom_snapshot": order.bom_snapshot,
        "recipe_snapshot": order.recipe_snapshot,
        "created_by_id": order.created_by_id,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "requirements": requirements,
        "operations": operations,
    }
