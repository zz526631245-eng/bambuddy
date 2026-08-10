"""Production consumable-unit inventory and QR scan lifecycle."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.material_type import MaterialType
from backend.app.models.operation_log import OperationLog
from backend.app.models.printer import Printer
from backend.app.models.production_consumable_unit import (
    CONSUMABLE_BOUND,
    CONSUMABLE_DEPLETED,
    CONSUMABLE_GENERATED,
    CONSUMABLE_IN_STOCK,
    CONSUMABLE_SCRAPPED,
    ProductionConsumableUnit,
)
from backend.app.models.production_printer_consumable import ProductionPrinterConsumable
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.schemas.production import ConsumableBatchCreate, ConsumableLibraryScan


async def _serialize(unit: ProductionConsumableUnit, db: AsyncSession, *, replayed: bool = False) -> dict:
    material = await db.get(MaterialType, unit.material_type_id)
    return {
        "id": unit.id,
        "material_type_id": unit.material_type_id,
        "material_type_code": material.code,
        "material": material.material,
        "brand": material.brand,
        "color_name": material.color_name,
        "color_hex": material.color_hex,
        "unit_code": unit.unit_code,
        "status": unit.status,
        "label_batch_id": unit.label_batch_id,
        "remaining_weight_g": unit.remaining_weight_g,
        "storage_location": unit.storage_location,
        "generated_at": unit.generated_at,
        "received_at": unit.received_at,
        "depleted_at": unit.depleted_at,
        "scrapped_at": unit.scrapped_at,
        "replayed": replayed,
    }


async def list_units(db: AsyncSession, *, status: str | None = None) -> list[dict]:
    query = select(ProductionConsumableUnit).order_by(ProductionConsumableUnit.id.desc())
    if status:
        query = query.where(ProductionConsumableUnit.status == status)
    rows = list((await db.execute(query)).scalars().all())
    return [await _serialize(row, db) for row in rows]


async def create_batch(db: AsyncSession, payload: ConsumableBatchCreate) -> dict:
    existing = (
        await db.execute(
            select(OperationLog).where(OperationLog.operation_id == payload.operation_id)
        )
    ).scalar_one_or_none()
    if existing and existing.payload and existing.payload.get("unit_ids"):
        rows = list(
            (
                await db.execute(
                    select(ProductionConsumableUnit).where(
                        ProductionConsumableUnit.id.in_(existing.payload["unit_ids"])
                    ).order_by(ProductionConsumableUnit.id)
                )
            ).scalars()
        )
        return {"batch_id": existing.payload.get("batch_id", ""), "items": [await _serialize(row, db, replayed=True) for row in rows]}

    material = await db.get(MaterialType, payload.material_type_id)
    if material is None:
        raise LookupError("材料类型不存在")
    batch_id = uuid4().hex
    rows = []
    for _index in range(payload.quantity):
        rows.append(
            ProductionConsumableUnit(
                material_type_id=material.id,
                unit_code=f"CU-{material.code}-{uuid4().hex[:12].upper()}",
                status=CONSUMABLE_GENERATED,
                label_batch_id=batch_id,
                remaining_weight_g=payload.remaining_weight_g,
            )
        )
    db.add_all(rows)
    await db.flush()
    db.add(
        OperationLog(
            operation_id=payload.operation_id,
            operation_type="production_consumable_batch_generated",
            entity_type="production_consumable_unit",
            entity_id=rows[0].id,
            payload={"batch_id": batch_id, "unit_ids": [row.id for row in rows]},
        )
    )
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return {"batch_id": batch_id, "items": [await _serialize(row, db) for row in rows]}


async def _clear_binding(binding: ProductionPrinterConsumable, db: AsyncSession) -> None:
    binding.is_active = False
    binding.replaced_at = datetime.now()
    if binding.virtual_printer_id:
        printer = await db.get(VirtualPrinter, binding.virtual_printer_id)
        if printer:
            printer.loaded_filaments = []
    if binding.printer_id:
        printer = await db.get(Printer, binding.printer_id)
        if printer:
            printer.loaded_filaments = []


async def scan_unit(db: AsyncSession, payload: ConsumableLibraryScan) -> dict:
    existing_log = (
        await db.execute(select(OperationLog).where(OperationLog.operation_id == payload.operation_id))
    ).scalar_one_or_none()
    if existing_log and existing_log.entity_id:
        row = await db.get(ProductionConsumableUnit, existing_log.entity_id)
        if row:
            return await _serialize(row, db, replayed=True)

    row = (
        await db.execute(
            select(ProductionConsumableUnit).where(ProductionConsumableUnit.unit_code == payload.unit_code)
        )
    ).scalar_one_or_none()
    if row is None:
        raise LookupError("耗材二维码不存在")
    now = datetime.now()
    if payload.action == "receive":
        if row.status not in (CONSUMABLE_GENERATED, CONSUMABLE_IN_STOCK):
            raise ValueError("该耗材当前不能入库")
        row.status = CONSUMABLE_IN_STOCK
        row.received_at = row.received_at or now
        if payload.storage_location is not None:
            row.storage_location = payload.storage_location
    elif payload.action == "deplete":
        if row.status not in (CONSUMABLE_IN_STOCK, CONSUMABLE_BOUND):
            raise ValueError("该耗材当前不能标记耗尽")
        binding = (
            await db.execute(
                select(ProductionPrinterConsumable).where(
                    ProductionPrinterConsumable.consumable_unit_id == row.id,
                    ProductionPrinterConsumable.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if binding:
            await _clear_binding(binding, db)
        row.status = CONSUMABLE_DEPLETED
        row.depleted_at = now
        row.remaining_weight_g = payload.remaining_weight_g if payload.remaining_weight_g is not None else 0
    else:
        if row.status in (CONSUMABLE_DEPLETED, CONSUMABLE_SCRAPPED):
            raise ValueError("该耗材已经结束，不能重复报废")
        binding = (
            await db.execute(
                select(ProductionPrinterConsumable).where(
                    ProductionPrinterConsumable.consumable_unit_id == row.id,
                    ProductionPrinterConsumable.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if binding:
            await _clear_binding(binding, db)
        row.status = CONSUMABLE_SCRAPPED
        row.scrapped_at = now

    db.add(
        OperationLog(
            operation_id=payload.operation_id,
            operation_type=f"production_consumable_{payload.action}",
            entity_type="production_consumable_unit",
            entity_id=row.id,
            payload={"unit_code": row.unit_code, "action": payload.action},
        )
    )
    await db.commit()
    await db.refresh(row)
    return await _serialize(row, db)


async def summary(db: AsyncSession) -> dict:
    rows = list((await db.execute(select(ProductionConsumableUnit.status))).scalars())
    counts = Counter(rows)
    return {
        "generated": counts[CONSUMABLE_GENERATED],
        "in_stock": counts[CONSUMABLE_IN_STOCK],
        "bound": counts[CONSUMABLE_BOUND],
        "depleted": counts[CONSUMABLE_DEPLETED],
        "scrapped": counts[CONSUMABLE_SCRAPPED],
        "total": len(rows),
    }
