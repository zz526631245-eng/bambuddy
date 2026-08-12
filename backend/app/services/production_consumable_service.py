"""Stage 12 direct-feed consumable scan and replacement service."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.material_type import MaterialType
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
from backend.app.services.printer_manager import printer_manager


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


def _normalise_material(value: object) -> str | None:
    """Return a comparable material type without accepting empty telemetry."""

    if value is None:
        return None
    material = str(value).strip().upper()
    return material or None


def _real_printer_external_material(printer_id: int) -> str:
    """Read the already-connected printer's external-tray material for validation.

    This intentionally does not open a new MQTT connection and it never writes
    back to the printer.  The production direct-feed record remains the display
    source; the device value is only a safety check before changing that record.
    """

    state = printer_manager.get_status(printer_id)
    if state is None or not bool(getattr(state, "connected", False)):
        raise ValueError("无法读取打印机当前外部耗材类型，请确认打印机已在线后重新扫码")

    raw_data = getattr(state, "raw_data", None) or {}
    trays = raw_data.get("vt_tray") if isinstance(raw_data, dict) else None
    if isinstance(trays, dict):
        trays = [trays]
    if not isinstance(trays, list):
        trays = []

    tray_rows = [tray for tray in trays if isinstance(tray, dict)]
    # Stage 12 direct feed uses Bambu's primary external-tray identifier 254.
    external_tray = next((tray for tray in tray_rows if str(tray.get("id", "")) == "254"), None)
    if external_tray is None and len(tray_rows) == 1:
        external_tray = tray_rows[0]
    material = _normalise_material(external_tray.get("tray_type") if external_tray else None)
    if material is None:
        raise ValueError(
            "无法读取打印机当前外部耗材类型，请先在打印机或 Bambu Studio 中设置外部耗材类型后重新扫码"
        )
    return material


def _validate_real_printer_material(printer_id: int, scanned_material: str) -> None:
    printer_material = _real_printer_external_material(printer_id)
    if printer_material == scanned_material:
        return
    raise ValueError(
        f"耗材类型不匹配：打印机当前外部料槽为 {printer_material}，本次扫码为 {scanned_material}。"
        f"请先在打印机或 Bambu Studio 中把外部耗材类型调整为 {scanned_material}，再重新扫码。"
    )


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
        else (
            await db.execute(
                select(ProductionConsumableUnit).where(
                    ProductionConsumableUnit.unit_code == payload.scan_code
                )
            )
        ).scalar_one_or_none()
    )
    if payload.consumable_unit_id is not None and unit is None:
        raise LookupError("生产耗材卷不存在")
    effective_material = payload.material
    effective_color_hex = payload.color_hex
    effective_color_name = payload.color_name
    if unit is not None:
        material_type = await db.get(MaterialType, unit.material_type_id)
        if material_type is None or not material_type.color_hex:
            raise ValueError("consumable unit material type is missing material or color")
        if effective_material is not None and effective_material.upper() != material_type.material.upper():
            raise ValueError("scanned material does not match consumable unit")
        if effective_color_hex is not None and effective_color_hex.upper().lstrip("#") != material_type.color_hex.upper().lstrip("#"):
            raise ValueError("scanned color does not match consumable unit")
        effective_material = material_type.material.upper()
        effective_color_hex = material_type.color_hex.lstrip("#").upper()
        effective_color_name = material_type.color_name
        payload.consumable_unit_id = unit.id
        if unit.unit_code != payload.scan_code:
            raise ValueError("扫码编码与耗材卷不一致")
        if unit.status not in (CONSUMABLE_IN_STOCK, CONSUMABLE_BOUND):
            raise ValueError("该耗材未入库，无法绑定打印机")

    if effective_material is None or effective_color_hex is None:
        raise ValueError("material and color are required unless a consumable unit is scanned")

    if payload.printer_id is not None:
        _validate_real_printer_material(payload.printer_id, effective_material)

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
        material=effective_material,
        color_hex=effective_color_hex,
        color_name=effective_color_name,
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
        effective_material, effective_color_hex, effective_color_name, payload.scan_code, binding.id
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
                "material": effective_material,
                "color_hex": effective_color_hex,
                "replaced_id": replaced_id,
            },
        )
    )
    await db.commit()
    await db.refresh(binding)
    return await _serialize(binding, db, replayed=False, replaced_id=replaced_id)
