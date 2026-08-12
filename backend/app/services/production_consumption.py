"""Automatic filament usage accounting and date-ranged cost summaries."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.archive import PrintArchive
from backend.app.models.library import LibraryFile
from backend.app.models.material_type import MaterialType
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.production import PlateJob
from backend.app.models.production_consumable_unit import (
    CONSUMABLE_DEPLETED,
    ProductionConsumableUnit,
)
from backend.app.models.production_consumable_usage import ProductionConsumableUsage
from backend.app.models.production_printer_consumable import ProductionPrinterConsumable
from backend.app.models.slice_artifact import SliceArtifact
from backend.app.services.production_consumable_library import _clear_binding

PERIOD_DAYS = {
    "1d": 1,
    "3d": 3,
    "7d": 7,
    "30d": 30,
    "3m": 90,
    "6m": 180,
    "1y": 365,
}


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _artifact_ids(slice_result: dict | None) -> set[int]:
    if not isinstance(slice_result, dict):
        return set()
    result: set[int] = set()
    for value in (slice_result.get("slice_artifact_id"),):
        if isinstance(value, int):
            result.add(value)
    for plate in slice_result.get("plates") or []:
        if isinstance(plate, dict) and isinstance(plate.get("slice_artifact_id"), int):
            result.add(plate["slice_artifact_id"])
    return result


async def estimate_queue_item_consumption(db: AsyncSession, queue_item: PrintQueueItem) -> float | None:
    """Resolve the best available measured/estimated grams for a completed print."""

    if queue_item.archive_id:
        archive = await db.get(PrintArchive, queue_item.archive_id)
        grams = _positive_float(archive.filament_used_grams) if archive else None
        if grams is not None:
            return grams

    if queue_item.library_file_id:
        library = await db.get(LibraryFile, queue_item.library_file_id)
        metadata = library.file_metadata if library else None
        if isinstance(metadata, dict):
            for key in ("filament_used_grams", "filament_used_g", "filament_used_gross"):
                grams = _positive_float(metadata.get(key))
                if grams is not None:
                    return grams

    job = await db.scalar(select(PlateJob).where(PlateJob.queue_item_id == queue_item.id))
    result = job.slice_result if job else None
    artifact_ids = _artifact_ids(result)
    if artifact_ids:
        artifacts = list(
            (
                await db.execute(select(SliceArtifact).where(SliceArtifact.id.in_(artifact_ids)))
            ).scalars()
        )
        total = sum((artifact.filament_used_g or 0) for artifact in artifacts)
        if total > 0:
            return float(total)
    return None


async def record_usage_for_queue_item(
    db: AsyncSession,
    queue_item_id: int,
    *,
    queue_status: str,
) -> dict | None:
    """Deduct one direct-feed unit after a successful real print, idempotently."""

    if queue_status != "completed":
        return None
    queue_item = await db.get(PrintQueueItem, queue_item_id)
    if queue_item is None or queue_item.printer_id is None:
        return None
    grams = await estimate_queue_item_consumption(db, queue_item)
    if grams is None:
        return None

    binding = await db.scalar(
        select(ProductionPrinterConsumable)
        .where(
            ProductionPrinterConsumable.printer_id == queue_item.printer_id,
            ProductionPrinterConsumable.is_active.is_(True),
        )
        .order_by(ProductionPrinterConsumable.scanned_at.desc(), ProductionPrinterConsumable.id.desc())
    )
    if binding is None or binding.consumable_unit_id is None:
        return None
    unit = await db.get(ProductionConsumableUnit, binding.consumable_unit_id)
    if unit is None:
        return None
    operation_id = f"production-consumable-usage-queue-{queue_item_id}-unit-{unit.id}"
    existing = await db.scalar(
        select(ProductionConsumableUsage).where(ProductionConsumableUsage.operation_id == operation_id)
    )
    if existing is not None:
        return _usage_dict(existing, unit)

    cost = 0.0
    if unit.initial_weight_g and unit.initial_weight_g > 0 and unit.unit_price is not None:
        cost = grams / unit.initial_weight_g * unit.unit_price
    usage = ProductionConsumableUsage(
        consumable_unit_id=unit.id,
        queue_item_id=queue_item.id,
        plate_job_id=(await db.scalar(select(PlateJob.id).where(PlateJob.queue_item_id == queue_item.id))),
        printer_id=queue_item.printer_id,
        operation_id=operation_id,
        consumed_g=grams,
        cost=cost,
        source="slicer_estimate",
    )
    db.add(usage)
    if unit.remaining_weight_g is not None:
        unit.remaining_weight_g = max(0.0, unit.remaining_weight_g - grams)
        if unit.remaining_weight_g <= 0:
            unit.status = CONSUMABLE_DEPLETED
            unit.depleted_at = datetime.now()
            await _clear_binding(binding, db)
    await db.commit()
    await db.refresh(usage)
    return _usage_dict(usage, unit)


def _usage_dict(usage: ProductionConsumableUsage, unit: ProductionConsumableUnit | None) -> dict:
    return {
        "id": usage.id,
        "consumable_unit_id": usage.consumable_unit_id,
        "unit_code": unit.unit_code if unit else None,
        "consumed_g": float(usage.consumed_g or 0),
        "cost": float(usage.cost or 0),
        "source": usage.source,
        "queue_item_id": usage.queue_item_id,
        "plate_job_id": usage.plate_job_id,
        "printer_id": usage.printer_id,
        "recorded_at": usage.recorded_at,
    }


def resolve_period(
    period: str = "30d",
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[str, datetime, datetime]:
    now = datetime.now()
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None or start_date > end_date:
            raise ValueError("开始日期和结束日期必须同时填写，且开始日期不能晚于结束日期")
        return (
            "custom",
            datetime.combine(start_date, datetime.min.time()),
            datetime.combine(end_date + timedelta(days=1), datetime.min.time()),
        )
    if period not in PERIOD_DAYS:
        raise ValueError("不支持的耗材统计周期")
    return period, now - timedelta(days=PERIOD_DAYS[period]), now


async def consumption_summary(
    db: AsyncSession,
    *,
    period: str = "30d",
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    period_name, start, end = resolve_period(period, start_date=start_date, end_date=end_date)
    where = (ProductionConsumableUsage.recorded_at >= start, ProductionConsumableUsage.recorded_at < end)

    totals = await db.execute(
        select(
            func.coalesce(func.sum(ProductionConsumableUsage.consumed_g), 0),
            func.coalesce(func.sum(ProductionConsumableUsage.cost), 0),
            func.count(ProductionConsumableUsage.id),
        ).where(*where)
    )
    consumed_g, cost, event_count = totals.one()

    group_rows = await db.execute(
        select(
            MaterialType.brand,
            MaterialType.material,
            MaterialType.subtype,
            MaterialType.color_name,
            MaterialType.color_hex,
            func.coalesce(func.sum(ProductionConsumableUsage.consumed_g), 0).label("consumed_g"),
            func.coalesce(func.sum(ProductionConsumableUsage.cost), 0).label("cost"),
            func.count(ProductionConsumableUsage.id).label("event_count"),
        )
        .select_from(ProductionConsumableUsage)
        .join(ProductionConsumableUnit, ProductionConsumableUnit.id == ProductionConsumableUsage.consumable_unit_id)
        .join(MaterialType, MaterialType.id == ProductionConsumableUnit.material_type_id)
        .where(*where)
        .group_by(
            MaterialType.brand,
            MaterialType.material,
            MaterialType.subtype,
            MaterialType.color_name,
            MaterialType.color_hex,
        )
        .order_by(MaterialType.brand, MaterialType.material, MaterialType.color_name)
    )
    groups = [
        {
            "brand": row.brand,
            "material": row.material,
            "subtype": row.subtype,
            "color_name": row.color_name,
            "color_hex": row.color_hex,
            "consumed_g": float(row.consumed_g or 0),
            "cost": float(row.cost or 0),
            "event_count": int(row.event_count or 0),
        }
        for row in group_rows
    ]

    event_rows = await db.execute(
        select(ProductionConsumableUsage, ProductionConsumableUnit, MaterialType)
        .select_from(ProductionConsumableUsage)
        .outerjoin(ProductionConsumableUnit, ProductionConsumableUnit.id == ProductionConsumableUsage.consumable_unit_id)
        .outerjoin(MaterialType, MaterialType.id == ProductionConsumableUnit.material_type_id)
        .where(*where)
        .order_by(ProductionConsumableUsage.recorded_at.desc(), ProductionConsumableUsage.id.desc())
        .limit(200)
    )
    events = []
    for usage, unit, material in event_rows:
        events.append(
            {
                **_usage_dict(usage, unit),
                "material_type_code": material.code if material else None,
                "brand": material.brand if material else None,
                "material": material.material if material else None,
                "subtype": material.subtype if material else None,
                "color_name": material.color_name if material else None,
                "color_hex": material.color_hex if material else None,
            }
        )
    return {
        "period": period_name,
        "start_date": start,
        "end_date": end,
        "consumed_g": float(consumed_g or 0),
        "cost": float(cost or 0),
        "event_count": int(event_count or 0),
        "groups": groups,
        "events": events,
    }
