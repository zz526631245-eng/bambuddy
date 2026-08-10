"""Stage 12 direct-feed consumable scan and replacement service."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.operation_log import OperationLog
from backend.app.models.printer import Printer
from backend.app.models.production_consumable_unit import (
    CONSUMABLE_BOUND,
    CONSUMABLE_IN_STOCK,
    ProductionConsumableUnit,
)
from backend.app.models.production_printer_consumable import ProductionPrinterConsumable
from backend.app.models.spool import Spool
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.schemas.production import PrinterConsumableScan


def _target_filter(payload: PrinterConsumableScan):
    if (payload.printer_id is None) == (payload.virtual_printer_id is None):
        raise ValueError("必须且只能选择一台真实打印机或虚拟打印机")
    if payload.printer_id is not None:
        return ProductionPrinterConsumable.printer_id == payload.printer_id
    return ProductionPrinterConsumable.virtual_printer_id == payload.virtual_printer_id


def _target_loaded_filament(material: str, color_hex: str, color_name: str | None, scan_code: str, binding_id: int) -> list[dict]:
    # 254 is the Bambu external/direct-feed tray id.  AMS slots remain untouched.
    return [
        {
            "slot": 254,
            "material": material,
            "color": color_hex,
            "color_name": color_name,
            "scan_code": scan_code,
            "binding_id": binding_id,
            "source": "direct_scan",
        }
    ]


async def _serialize(binding: ProductionPrinterConsumable, db: AsyncSession, **extra) -> dict:
    printer_name = None
    virtual_printer_name = None
    if binding.printer_id:
        printer_name = (await db.get(Printer, binding.printer_id)).name
    if binding.virtual_printer_id:
        virtual_printer_name = (await db.get(VirtualPrinter, binding.virtual_printer_id)).name
    result = {
        "id": binding.id,
        "printer_id": binding.printer_id,
        "virtual_printer_id": binding.virtual_printer_id,
        "printer_name": printer_name,
        "virtual_printer_name": virtual_printer_name,
        "spool_id": binding.spool_id,
        "consumable_unit_id": binding.consumable_unit_id,
        "scan_code": binding.scan_code,
        "material": binding.material,
        "color_hex": binding.color_hex,
        "color_name": binding.color_name,
        "source": binding.source,
        "operation_id": binding.operation_id,
        "is_active": binding.is_active,
        "scanned_at": binding.scanned_at,
        "replaced_at": binding.replaced_at,
    }
    result.update(extra)
    return result


async def list_bindings(db: AsyncSession, *, active_only: bool = True) -> list[dict]:
    query = select(ProductionPrinterConsumable).order_by(ProductionPrinterConsumable.id.desc())
    if active_only:
        query = query.where(ProductionPrinterConsumable.is_active.is_(True))
    rows = list((await db.execute(query)).scalars().all())
    return [await _serialize(row, db) for row in rows]


async def scan_direct_consumable(db: AsyncSession, payload: PrinterConsumableScan) -> dict:
    """Replace the current direct-feed spool for exactly one printer.

    Replaying an operation id returns the original binding.  Scanning a new
    code deactivates the previous binding, updates the target's persisted
    loaded-filament snapshot, and leaves the old row for audit/history.
    """

    if (payload.printer_id is None) == (payload.virtual_printer_id is None):
        raise ValueError("必须且只能选择一台真实打印机或虚拟打印机")
    if payload.printer_id is not None:
        target = await db.get(Printer, payload.printer_id)
        if target is None:
            raise LookupError("真实打印机不存在")
    else:
        target = await db.get(VirtualPrinter, payload.virtual_printer_id)
        if target is None:
            raise LookupError("虚拟打印机不存在")

    replay = (
        await db.execute(
            select(ProductionPrinterConsumable).where(
                ProductionPrinterConsumable.operation_id == payload.operation_id
            )
        )
    ).scalar_one_or_none()
    if replay is not None:
        return await _serialize(replay, db, replayed=True, replaced_id=None)

    spool = await db.get(Spool, payload.spool_id) if payload.spool_id is not None else None
    if payload.spool_id is not None and spool is None:
        raise LookupError("耗材卷不存在")
    unit = (
        await db.get(ProductionConsumableUnit, payload.consumable_unit_id)
        if payload.consumable_unit_id is not None
        else None
    )
    if payload.consumable_unit_id is not None and unit is None:
        raise LookupError("生产耗材卷不存在")
    if unit is not None:
        if unit.unit_code != payload.scan_code:
            raise ValueError("扫码编码与耗材卷不一致")
        if unit.status not in (CONSUMABLE_IN_STOCK, CONSUMABLE_BOUND):
            raise ValueError("该耗材卷当前不能绑定打印机")

    current = (
        await db.execute(
            select(ProductionPrinterConsumable).where(
                _target_filter(payload),
                ProductionPrinterConsumable.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    replaced_id = current.id if current else None
    now = datetime.now()
    if current:
        current.is_active = False
        current.replaced_at = now
        if current.consumable_unit_id:
            previous_unit = await db.get(ProductionConsumableUnit, current.consumable_unit_id)
            if previous_unit and previous_unit.status == CONSUMABLE_BOUND:
                previous_unit.status = CONSUMABLE_IN_STOCK

    binding = ProductionPrinterConsumable(
        printer_id=payload.printer_id,
        virtual_printer_id=payload.virtual_printer_id,
        spool_id=payload.spool_id,
        consumable_unit_id=payload.consumable_unit_id,
        scan_code=payload.scan_code,
        material=payload.material,
        color_hex=payload.color_hex,
        color_name=payload.color_name,
        source="scanner",
        operation_id=payload.operation_id,
        is_active=True,
        scanned_at=now,
    )
    db.add(binding)
    await db.flush()
    if unit is not None:
        unit.status = CONSUMABLE_BOUND
    target.loaded_filaments = _target_loaded_filament(
        payload.material, payload.color_hex, payload.color_name, payload.scan_code, binding.id
    )
    db.add(
        OperationLog(
            operation_id=payload.operation_id,
            operation_type="production_direct_consumable_scanned",
            entity_type="production_printer_consumable",
            entity_id=binding.id,
            payload={
                "printer_id": payload.printer_id,
                "virtual_printer_id": payload.virtual_printer_id,
                "scan_code": payload.scan_code,
                "material": payload.material,
                "color_hex": payload.color_hex,
                "replaced_id": replaced_id,
            },
        )
    )
    await db.commit()
    await db.refresh(binding)
    return await _serialize(binding, db, replayed=False, replaced_id=replaced_id)
