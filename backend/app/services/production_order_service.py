"""Stage 8 production-order orchestration without printer dispatch."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete as sql_delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.operation_log import OperationLog
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.product_file import ProductFile
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
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.services.production_accounting import calculate_ledger, transition_order_status


class ProductionOrderError(ValueError):
    pass


async def _next_order_number(db: AsyncSession) -> str:
    """Allocate the next human-readable order number for today's date.

    The database remains the authority for the sequence.  The unique order
    number constraint still protects against an accidental concurrent clash.
    """
    prefix = f"PO-{datetime.utcnow():%Y%m%d}-"
    existing = (
        await db.execute(
            select(ProductionOrder.order_number).where(ProductionOrder.order_number.like(f"{prefix}%"))
        )
    ).scalars().all()
    numbers = [
        int(match.group(1))
        for value in existing
        if (match := re.fullmatch(rf"{re.escape(prefix)}(\d+)", value))
    ]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _recipe_snapshot(recipe: ProductionRecipe) -> dict:
    compatible_profiles = recipe.__dict__.get("compatible_profiles") or []
    return {
        "id": recipe.id,
        "code": recipe.code,
        "name": recipe.name,
        "version": recipe.version,
        "component_id": recipe.component_id,
        "material_type_id": recipe.material_type_id,
        "printer_profile_id": recipe.printer_profile_id,
        "compatible_profile_ids": [profile.id for profile in compatible_profiles],
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


def _product_file_snapshot(
    product_file: ProductFile,
    *,
    product: Product,
    source_files: list[ProductFile] | None = None,
) -> dict:
    source_files = source_files or [product_file]
    return {
        "id": product_file.id,
        "version": product_file.version,
        "name": product_file.name,
        "product_color": product_file.product_color,
        "library_file_id": product_file.library_file_id,
        "strategy": product_file.strategy,
        "units_per_plate": product_file.units_per_plate,
        "source_plate_count": product_file.source_plate_count,
        "production_mode": product.production_mode,
        "source_set_id": product_file.source_set_id,
        "source_file_ids": [item.id for item in sorted(source_files, key=lambda item: item.source_plate_index)],
        "source_files": [
            {
                "id": item.id,
                "version": item.version,
                "name": item.name,
                "library_file_id": item.library_file_id,
                "source_plate_index": item.source_plate_index,
            }
            for item in sorted(source_files, key=lambda item: item.source_plate_index)
        ],
        "component_ids": product_file.component_ids or [],
        "compatible_printer_models": product_file.compatible_printer_models or [],
        "filament_requirements": product_file.filament_requirements or [],
        "product_size_class": product.size_class,
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


async def product_order_summaries(db: AsyncSession) -> list[dict[str, int]]:
    """Return product-level demand totals for the production overview.

    The aggregation stays in the backend so the UI only renders authoritative
    quantities. Cancelled orders are excluded; multi-component orders count a
    product as complete only when every requirement can supply that product.
    """

    orders = list(
        (
            await db.execute(
                select(ProductionOrder)
                .where(ProductionOrder.status != OrderStatus.CANCELLED.value)
                .options(selectinload(ProductionOrder.requirements))
                .order_by(ProductionOrder.product_id, ProductionOrder.id)
            )
        )
        .scalars()
        .all()
    )
    totals: dict[int, dict[str, int]] = {}
    for order in orders:
        summary = totals.setdefault(
            order.product_id,
            {"product_id": order.product_id, "total_quantity": 0, "completed_quantity": 0},
        )
        summary["total_quantity"] += max(0, int(order.quantity))
        if not order.requirements:
            continue
        completed_by_requirement = [
            int(requirement.good_quantity / requirement.unit_quantity)
            for requirement in order.requirements
            if requirement.unit_quantity > 0
        ]
        if completed_by_requirement:
            summary["completed_quantity"] += min(order.quantity, min(completed_by_requirement))
    return [
        {
            **summary,
            "pending_quantity": max(0, summary["total_quantity"] - summary["completed_quantity"]),
        }
        for summary in totals.values()
    ]


async def _create_product_file_order(
    db: AsyncSession,
    product: Product,
    product_file: ProductFile,
    operation_id: str,
    order_number: str,
    quantity: int,
    priority: int,
    due_at: datetime | None,
    notes: str | None,
    actor_user_id: int | None,
) -> tuple[ProductionOrder, bool]:
    """Create an order from a product-owned source file, without legacy BOM UI."""
    code = f"PRODUCT-FILE-{product_file.id}-V{product_file.version}"
    recipe = next((item for item in product.recipes if item.code == code), None)
    if recipe is None:
        recipe = ProductionRecipe(
            code=code,
            name=product_file.name,
            product_id=product.id,
            library_file_id=product_file.library_file_id,
            version=product_file.version,
            is_active=True,
        )
        db.add(recipe)
        await db.flush()
    source_files = [
        item
        for item in product.product_files
        if item.is_active and item.source_set_id == product_file.source_set_id
    ] if product.production_mode == "multi_plate" and product_file.source_set_id else [product_file]
    if product.production_mode == "multi_plate":
        expected = product.source_plate_count
        actual = {item.source_plate_index for item in source_files}
        if len(source_files) != expected or actual != set(range(expected)):
            raise ProductionOrderError(f"多盘产品需要完整上传 {expected} 个源文件，当前只有 {len(source_files)} 个")
    file_snapshot = _product_file_snapshot(product_file, product=product, source_files=source_files)
    recipe_snapshot = _recipe_snapshot(recipe)
    order = ProductionOrder(
        order_number=order_number,
        product_id=product.id,
        quantity=quantity,
        priority=priority,
        status=OrderStatus.PLANNED.value,
        due_at=due_at,
        notes=notes,
        created_by_id=actor_user_id,
        product_snapshot={"id": product.id, "sku": product.sku, "name": product.name, "description": product.description, "size_class": product.size_class, "captured_at": datetime.utcnow().isoformat()},
        bom_snapshot=[],
        recipe_snapshot=[recipe_snapshot],
        product_file_snapshot=file_snapshot,
    )
    db.add(order)
    await db.flush()
    db.add(ProductionRequirement(
        order_id=order.id,
        recipe_id=recipe.id,
        product_file_id=product_file.id,
        component_id=None,
        unit_quantity=1 if product.production_mode == "multi_plate" else product_file.units_per_plate,
        required_quantity=quantity,
        component_snapshot={"id": None, "name": product.name, "unit": "套"},
        recipe_snapshot={**recipe_snapshot, "product_file_snapshot": file_snapshot},
    ))
    db.add(OperationLog(operation_id=operation_id, operation_type="production_order_created", entity_type="production_order", entity_id=order.id, actor_user_id=actor_user_id, payload={"order_id": order.id, "order_number": order_number, "product_file_id": product_file.id}))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _operation(db, operation_id)
        if replay:
            existing = await _load_order(db, int((replay.payload or {})["order_id"]))
            if existing:
                return existing, True
        raise
    loaded = await _load_order(db, order.id)
    assert loaded is not None
    return loaded, False


async def create_order(
    db: AsyncSession,
    *,
    operation_id: str,
    order_number: str | None,
    product_id: int,
    product_file_id: int | None = None,
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
                selectinload(Product.recipes).selectinload(ProductionRecipe.compatible_profiles),
                selectinload(Product.product_files),
            )
        )
    ).scalar_one_or_none()
    if not product:
        raise ProductionOrderError("产品不存在")
    if not order_number:
        order_number = await _next_order_number(db)
    active_files = [item for item in product.product_files if item.is_active]
    selected_file = next((item for item in active_files if item.id == product_file_id), None) if product_file_id else (max(active_files, key=lambda item: (item.version, item.id)) if active_files else None)
    if product_file_id and selected_file is None:
        raise ProductionOrderError("指定的产品源文件不存在或已停用")
    if selected_file is None:
        raise ProductionOrderError("请先上传产品源文件，产品尚未配置可生产的源文件")
    return await _create_product_file_order(db, product, selected_file, operation_id, order_number, quantity, priority, due_at, notes, actor_user_id)

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
        if any(
            job.status in {PlateJobStatus.PRINTING.value, PlateJobStatus.WAITING_CLEANUP.value}
            for requirement in order.requirements
            for job in requirement.plate_jobs
        ):
            raise ProductionOrderError("订单中有正在打印或等待质检/清板的任务，不能直接取消")
        queue_item_ids: list[int] = []
        for requirement in order.requirements:
            requirement.status = RequirementStatus.CANCELLED.value
            requirement.reserved_quantity = 0
            for job in requirement.plate_jobs:
                if job.status not in {PlateJobStatus.COMPLETED.value, PlateJobStatus.CANCELLED.value}:
                    job.status = PlateJobStatus.CANCELLED.value
                if job.queue_item_id is not None:
                    queue_item_ids.append(job.queue_item_id)
        if queue_item_ids:
            await db.execute(
                update(PrintQueueItem)
                .where(
                    PrintQueueItem.id.in_(queue_item_ids),
                    PrintQueueItem.status == "pending",
                )
                .values(status="cancelled", completed_at=datetime.utcnow())
            )
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


async def cancel_plate_job(db: AsyncSession, plate_job_id: int) -> PlateJob:
    """Cancel one production plate job without dispatching printer commands."""
    job = (
        await db.execute(
            select(PlateJob)
            .where(PlateJob.id == plate_job_id)
            .options(selectinload(PlateJob.requirement))
        )
    ).scalar_one_or_none()
    if job is None:
        raise ProductionOrderError("打印任务不存在")
    if job.status == PlateJobStatus.COMPLETED.value:
        raise ProductionOrderError("已完成的打印任务不能取消")
    if job.status in {PlateJobStatus.PRINTING.value, PlateJobStatus.WAITING_CLEANUP.value}:
        raise ProductionOrderError("打印中或等待质检/清板的任务不能取消")
    if job.status == PlateJobStatus.CANCELLED.value:
        return job
    if job.queue_item_id is not None:
        queue_item = await db.get(PrintQueueItem, job.queue_item_id)
        if queue_item is not None:
            if queue_item.status == "printing":
                raise ProductionOrderError("打印机正在执行此任务，请先在打印机侧停止后再处理")
            if queue_item.status == "pending":
                queue_item.status = "cancelled"
                queue_item.completed_at = datetime.utcnow()
    job.status = PlateJobStatus.CANCELLED.value
    requirement = job.requirement
    requirement.reserved_quantity = max(0, requirement.reserved_quantity - job.planned_quantity)
    if requirement.reserved_quantity == 0 and requirement.good_quantity == 0 and requirement.scrap_quantity == 0:
        requirement.status = RequirementStatus.CANCELLED.value
    db.add(
        OperationLog(
            operation_id=f"cancel-plate-job-{job.id}-{datetime.utcnow().timestamp()}",
            operation_type="production_plate_job_cancelled",
            entity_type="production_order",
            entity_id=requirement.order_id,
            payload={"plate_job_id": job.id},
        )
    )
    await db.commit()
    await db.refresh(job)
    return job


async def delete_plate_job(db: AsyncSession, plate_job_id: int) -> None:
    """Remove a production task row after it is no longer printing."""
    job = (
        await db.execute(
            select(PlateJob)
            .where(PlateJob.id == plate_job_id)
            .options(selectinload(PlateJob.requirement))
        )
    ).scalar_one_or_none()
    if job is None:
        raise ProductionOrderError("打印任务不存在")
    queue_item = await db.get(PrintQueueItem, job.queue_item_id) if job.queue_item_id is not None else None
    if job.status in {
        PlateJobStatus.PRINTING.value,
        PlateJobStatus.WAITING_CLEANUP.value,
        PlateJobStatus.COMPLETED.value,
    } or (queue_item and queue_item.status == "printing"):
        raise ProductionOrderError("已开始执行或已完成的任务必须保留，不能删除")
    if queue_item and queue_item.status == "pending":
        queue_item.status = "cancelled"
        queue_item.completed_at = datetime.utcnow()
    if job.status not in {PlateJobStatus.CANCELLED.value, PlateJobStatus.COMPLETED.value}:
        job.requirement.reserved_quantity = max(0, job.requirement.reserved_quantity - job.planned_quantity)
    await db.delete(job)
    await db.commit()


async def delete_order(db: AsyncSession, order_id: int) -> None:
    """Delete one production order and its production-only task history."""
    order = await _load_order(db, order_id)
    if order is None:
        raise ProductionOrderError("生产订单不存在")
    if any(
        job.print_started_at is not None or job.status == PlateJobStatus.COMPLETED.value
        for requirement in order.requirements
        for job in requirement.plate_jobs
    ):
        raise ProductionOrderError("订单已有执行记录，必须保留审计历史，不能删除")
    queue_ids = [job.queue_item_id for req in order.requirements for job in req.plate_jobs if job.queue_item_id]
    if queue_ids:
        queue_rows = list((await db.execute(select(PrintQueueItem).where(PrintQueueItem.id.in_(queue_ids)))).scalars())
        if any(row.status == "printing" for row in queue_rows):
            raise ProductionOrderError("订单中仍有打印机正在执行的任务，请先取消打印")
        for row in queue_rows:
            if row.status == "pending":
                row.status = "cancelled"
                row.completed_at = datetime.utcnow()
    await db.execute(
        sql_delete(OperationLog).where(
            OperationLog.entity_type == "production_order",
            OperationLog.entity_id == order_id,
        )
    )
    await db.delete(order)
    await db.commit()


_WORKFLOW_LOG = {
    "prepare": "production_plate_job_prepared",
    "start": "production_plate_job_started",
    "finish": "production_plate_job_print_finished",
    "quality": "production_plate_job_quality_confirmed",
    "cleanup": "production_plate_job_cleanup_confirmed",
}


async def _refresh_order_completion(db: AsyncSession, order_id: int) -> None:
    order = await _load_order(db, order_id)
    if order is None or order.status in {OrderStatus.CANCELLED.value, OrderStatus.COMPLETED.value}:
        return
    if not order.requirements or any(
        requirement.good_quantity < requirement.required_quantity
        for requirement in order.requirements
    ):
        return
    active = await db.scalar(
        select(
            exists().where(
                ProductionRequirement.order_id == order_id,
                PlateJob.requirement_id == ProductionRequirement.id,
                PlateJob.status.not_in(
                    (PlateJobStatus.COMPLETED.value, PlateJobStatus.CANCELLED.value)
                ),
            )
        )
    )
    if not active:
        order.status = OrderStatus.COMPLETED.value


async def advance_virtual_plate_job(
    db: AsyncSession,
    *,
    plate_job_id: int,
    operation_id: str,
    action: str,
    actor_user_id: int | None,
    machine_result: str | None = None,
    good_quantity: int | None = None,
) -> tuple[PlateJob, bool]:
    """Advance one Stage 11 virtual job without contacting printer services."""

    operation_type = _WORKFLOW_LOG.get(action)
    if operation_type is None:
        raise ProductionOrderError("不支持的虚拟打印操作")
    replay = await _operation(db, operation_id)
    if replay:
        payload = replay.payload or {}
        if replay.operation_type != operation_type or payload.get("plate_job_id") != plate_job_id:
            raise ProductionOrderError("该操作编号已经用于其他操作")
        existing = await db.get(PlateJob, plate_job_id)
        if existing is None:
            raise ProductionOrderError("打印任务不存在")
        return existing, True

    job = (
        await db.execute(
            select(PlateJob)
            .where(PlateJob.id == plate_job_id)
            .options(
                selectinload(PlateJob.requirement).selectinload(ProductionRequirement.order),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise ProductionOrderError("打印任务不存在")
    if job.virtual_printer_id is None:
        raise ProductionOrderError("阶段11只允许操作虚拟打印机任务")

    now = datetime.utcnow()
    payload: dict = {"plate_job_id": job.id, "action": action, "simulation_only": True}
    if action == "prepare":
        if job.status != PlateJobStatus.ASSIGNED.value:
            raise ProductionOrderError("只有已分配任务可以进入待打印")
        job.status = PlateJobStatus.READY.value
    elif action == "start":
        if job.status != PlateJobStatus.READY.value:
            raise ProductionOrderError("只有待打印任务可以开始虚拟打印")
        job.status = PlateJobStatus.PRINTING.value
        job.print_started_at = now
    elif action == "finish":
        if job.status != PlateJobStatus.PRINTING.value:
            raise ProductionOrderError("只有打印中的任务可以结束虚拟打印")
        if machine_result not in {"completed", "failed"}:
            raise ProductionOrderError("必须说明虚拟打印机报告成功还是失败")
        job.status = PlateJobStatus.WAITING_CLEANUP.value
        job.machine_result = machine_result
        job.print_finished_at = now
        payload["machine_result"] = machine_result
    elif action == "quality":
        if job.status != PlateJobStatus.WAITING_CLEANUP.value or job.quality_confirmed_at is not None:
            raise ProductionOrderError("当前任务不在等待质检状态")
        if good_quantity is None or good_quantity < 0 or good_quantity > job.planned_quantity:
            raise ProductionOrderError("合格数量必须在零到本盘计划数量之间")
        scrap_quantity = job.planned_quantity - good_quantity
        job.quality_good_quantity = good_quantity
        job.quality_scrap_quantity = scrap_quantity
        job.quality_confirmed_at = now
        requirement = job.requirement
        file_snapshot = (requirement.recipe_snapshot or {}).get("product_file_snapshot") or {}
        is_multi_plate = (
            file_snapshot.get("production_mode") == "multi_plate"
            and int(file_snapshot.get("source_plate_count", 1) or 1) > 1
            and job.product_set_index > 0
        )
        if is_multi_plate:
            siblings = list(
                (
                    await db.execute(
                        select(PlateJob).where(
                            PlateJob.requirement_id == requirement.id,
                            PlateJob.product_set_index == job.product_set_index,
                            PlateJob.status != PlateJobStatus.CANCELLED.value,
                        )
                    )
                ).scalars()
            )
            if all(row.quality_confirmed_at is not None for row in siblings):
                requirement.reserved_quantity = max(0, requirement.reserved_quantity - 1)
                if all((row.quality_good_quantity or 0) >= row.planned_quantity for row in siblings):
                    requirement.good_quantity += 1
                else:
                    requirement.scrap_quantity += 1
        else:
            requirement.reserved_quantity = max(0, requirement.reserved_quantity - job.planned_quantity)
            requirement.good_quantity += good_quantity
            requirement.scrap_quantity += scrap_quantity
        requirement.status = (
            RequirementStatus.COMPLETED.value
            if requirement.good_quantity >= requirement.required_quantity
            else RequirementStatus.IN_PROGRESS.value
            if requirement.reserved_quantity > 0
            else RequirementStatus.PENDING.value
        )
        payload.update({"good_quantity": good_quantity, "scrap_quantity": scrap_quantity})
    elif action == "cleanup":
        if job.status != PlateJobStatus.WAITING_CLEANUP.value or job.quality_confirmed_at is None:
            raise ProductionOrderError("必须先完成质检才能确认清板")
        job.status = PlateJobStatus.COMPLETED.value
        job.cleanup_confirmed_at = now

    db.add(
        OperationLog(
            operation_id=operation_id,
            operation_type=operation_type,
            entity_type="production_order",
            entity_id=job.requirement.order_id,
            actor_user_id=actor_user_id,
            payload=payload,
        )
    )
    if action == "cleanup":
        await db.flush()
        await _refresh_order_completion(db, job.requirement.order_id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await _operation(db, operation_id)
        if replay:
            existing = await db.get(PlateJob, plate_job_id)
            if existing:
                return existing, True
        raise
    await db.refresh(job)
    return job, False


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
        file_snapshot = recipe.get("product_file_snapshot") or {}
        items.append(
            {
                "requirement_id": requirement.id,
                "printer_profile_id": recipe.get("printer_profile_id"),
                "planned_quantity": ledger.remaining,
                "component_name": component.get("name", f"需求 {requirement.id}"),
                "print_plan_name": recipe.get("name", f"打印方案 {requirement.recipe_id}"),
                "strategy": "multi_plate_fixed" if file_snapshot.get("production_mode") == "multi_plate" else file_snapshot.get("strategy", "fixed_plate"),
                "source_plate_count": int(
                    file_snapshot.get("source_plate_count", 1) or 1
                ),
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
        file_snapshot = (requirement.recipe_snapshot or {}).get("product_file_snapshot") or {}
        strategy = "multi_plate_fixed" if file_snapshot.get("production_mode") == "multi_plate" else file_snapshot.get("strategy", "fixed_plate")
        source_plate_count = int(file_snapshot.get("source_plate_count", 1) or 1)
        if strategy == "multi_plate_fixed":
            if source_plate_count < 2:
                raise ProductionOrderError("多盘固定源文件缺少有效的源盘数量")
            max_set_index = (
                await db.execute(
                    select(func.max(PlateJob.product_set_index)).where(
                        PlateJob.requirement_id == requirement.id
                    )
                )
            ).scalar_one_or_none()
            next_set_index = int(max_set_index or 0) + 1
            # One product set is one copy of every source plate.  Expand the
            # physical work items while reserving the product quantity only
            # once in the requirement ledger.
            for offset in range(item.planned_quantity):
                product_set_index = next_set_index + offset
                for source_plate_index in range(source_plate_count):
                    job = PlateJob(
                        requirement_id=requirement.id,
                        printer_profile_id=item.printer_profile_id,
                        planned_quantity=1,
                        status=PlateJobStatus.DRAFT.value,
                        queue_item_id=None,
                        source_plate_index=source_plate_index,
                        product_set_index=product_set_index,
                    )
                    db.add(job)
                    jobs.append(job)
        else:
            job = PlateJob(
                requirement_id=requirement.id,
                printer_profile_id=item.printer_profile_id,
                planned_quantity=item.planned_quantity,
                status=PlateJobStatus.DRAFT.value,
                queue_item_id=None,
            )
            db.add(job)
            jobs.append(job)
        requirement.reserved_quantity += item.planned_quantity
        requirement.status = RequirementStatus.IN_PROGRESS.value
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
    all_jobs = [job for requirement in order.requirements for job in requirement.plate_jobs]
    profile_ids = {job.printer_profile_id for job in all_jobs if job.printer_profile_id is not None}
    virtual_ids = {job.virtual_printer_id for job in all_jobs if job.virtual_printer_id is not None}
    queue_ids = {job.queue_item_id for job in all_jobs if job.queue_item_id is not None}
    profiles = {
        profile.id: profile
        for profile in list((await db.execute(select(PrinterProfile).where(PrinterProfile.id.in_(profile_ids)))).scalars())
    } if profile_ids else {}
    virtual_printers = {
        printer.id: printer
        for printer in list((await db.execute(select(VirtualPrinter).where(VirtualPrinter.id.in_(virtual_ids)))).scalars())
    } if virtual_ids else {}
    queue_items = {
        item.id: item
        for item in list((await db.execute(select(PrintQueueItem).where(PrintQueueItem.id.in_(queue_ids)))).scalars())
    } if queue_ids else {}
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
                "product_file_id": requirement.product_file_id,
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
                "plate_jobs": [
                    {
                        **{
                            key: value
                            for key, value in job.__dict__.items()
                            if not key.startswith("_")
                        },
                        "workflow_status": job.workflow_status,
                        "printer_profile_name": profiles[job.printer_profile_id].name
                        if job.printer_profile_id in profiles
                        else None,
                        "printer_model": profiles[job.printer_profile_id].printer_model
                        if job.printer_profile_id in profiles
                        else None,
                        "virtual_printer_name": virtual_printers[job.virtual_printer_id].name
                        if job.virtual_printer_id in virtual_printers
                        else None,
                        "queue_status": queue_items[job.queue_item_id].status
                        if job.queue_item_id in queue_items
                        else None,
                    }
                    for job in requirement.plate_jobs
                ],
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
        "recalculation_required": order.recalculation_required,
        "product_snapshot": order.product_snapshot,
        "bom_snapshot": order.bom_snapshot,
        "recipe_snapshot": order.recipe_snapshot,
        "product_file_snapshot": order.product_file_snapshot,
        "created_by_id": order.created_by_id,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "requirements": requirements,
        "operations": operations,
    }
