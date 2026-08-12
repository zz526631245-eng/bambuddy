"""Stage 13 printer heartbeat and availability service.

This is the production-facing status contract.  It intentionally contains no
MQTT/FTP/device code: the current implementation accepts simulated heartbeats
so the workflow can be verified before Stage 14 enables a real adapter.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.operation_log import OperationLog
from backend.app.models.printer import Printer
from backend.app.models.production_printer_status import ProductionPrinterStatus
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.schemas.production import PrinterStatusHeartbeat
from backend.app.services.printer_manager import printer_manager

HEARTBEAT_TIMEOUT_SECONDS = 30
UNAVAILABLE_STATES = frozenset({"offline", "error", "maintenance"})
KNOWN_STATES = frozenset({"unknown", "idle", "printing", "paused", "finished", *UNAVAILABLE_STATES})


def _normalise_real_state(raw_state: str | None, *, connected: bool) -> str:
    """Map Bambuddy's MQTT state names to the production status contract."""

    if not connected:
        return "offline"
    state = str(raw_state or "").upper()
    if state in {"RUNNING", "PREPARE", "SLICING"}:
        return "printing"
    if state == "PAUSE":
        return "paused"
    if state in {"FINISH", "COMPLETED"}:
        return "finished"
    if state in {"FAILED", "ERROR"}:
        return "error"
    if state in {"IDLE", ""}:
        return "idle"
    return "unknown"


def target_key(target_type: str, target_id: int) -> str:
    return f"{target_type}:{target_id}"


def _now() -> datetime:
    return datetime.utcnow()


def _seconds_since(value: datetime | None, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    current = now or _now()
    return max(0, int((current - value).total_seconds()))


def _effective_state(row: ProductionPrinterStatus | None, now: datetime | None = None) -> tuple[str, bool, bool, int | None]:
    if row is None:
        # No Stage 13 snapshot means the target is still governed by the
        # Stage 9 persisted configuration.  This keeps existing installs and
        # virtual-printer tests compatible until a heartbeat is supplied.
        return "unknown", True, False, None
    seconds = _seconds_since(row.last_heartbeat_at, now)
    stale = seconds is None or seconds > HEARTBEAT_TIMEOUT_SECONDS
    if stale:
        return "offline", False, True, seconds
    state = row.state if row.state in KNOWN_STATES else "unknown"
    return state, state not in UNAVAILABLE_STATES and state != "unknown", False, seconds


async def _target(db: AsyncSession, target_type: str, target_id: int):
    model = Printer if target_type == "printer" else VirtualPrinter
    row = await db.get(model, target_id)
    if row is None or (target_type == "printer" and not row.is_active):
        raise LookupError("目标打印机不存在或已停用")
    return row


async def _serialize(
    db: AsyncSession,
    row: ProductionPrinterStatus | None,
    *,
    target_type: str,
    target_id: int,
    replayed: bool = False,
) -> dict:
    target = await _target(db, target_type, target_id)
    effective_state, available, stale, seconds = _effective_state(row)
    return {
        "id": row.id if row else None,
        "target_key": target_key(target_type, target_id),
        "target_type": target_type,
        "target_id": target_id,
        "name": target.name,
        "model": target.model,
        "state": row.state if row else "unknown",
        "effective_state": effective_state,
        "available_for_allocation": available,
        "stale": stale,
        "source": row.source if row else "stage13_not_started",
        "last_heartbeat_at": row.last_heartbeat_at if row else None,
        "observed_at": row.observed_at if row else None,
        "seconds_since_heartbeat": seconds,
        "current_job_id": row.current_job_id if row else None,
        "current_job_state": row.current_job_state if row else None,
        "fault_code": row.fault_code if row else None,
        "fault_message": row.fault_message if row else None,
        "loaded_filaments": (row.loaded_filaments if row else target.loaded_filaments) or [],
        "telemetry": (row.telemetry if row else {}) or {},
        "heartbeat_timeout_seconds": HEARTBEAT_TIMEOUT_SECONDS,
        "transport_enabled": bool(row and row.source == "stage14_real_adapter"),
        "replayed": replayed,
    }


async def _sync_real_printer_status(db: AsyncSession, printer: Printer) -> bool:
    """Persist the current MQTT snapshot for a connected real printer.

    The core printer manager owns connections.  This production adapter only
    translates its already-received state and never opens a second connection.
    """

    state = printer_manager.get_status(printer.id)
    if state is None:
        return False
    connected = bool(getattr(state, "connected", False))
    key = target_key("printer", printer.id)
    row = await db.scalar(select(ProductionPrinterStatus).where(ProductionPrinterStatus.target_key == key))
    now = _now()
    if row is None:
        row = ProductionPrinterStatus(target_key=key, target_type="printer", target_id=printer.id)
        db.add(row)
    row.state = _normalise_real_state(getattr(state, "state", None), connected=connected)
    row.source = "stage14_real_adapter"
    row.last_heartbeat_at = now
    row.observed_at = now
    row.current_job_state = getattr(state, "state", None)
    row.fault_code = None
    row.fault_message = None
    row.loaded_filaments = printer.loaded_filaments or []
    row.telemetry = {
        "progress": getattr(state, "progress", None),
        "remaining_time": getattr(state, "remaining_time", None),
        "layer_num": getattr(state, "layer_num", None),
        "total_layers": getattr(state, "total_layers", None),
        "gcode_file": getattr(state, "gcode_file", None),
        "subtask_name": getattr(state, "subtask_name", None),
        "connected": connected,
    }
    return True


async def list_statuses(db: AsyncSession) -> list[dict]:
    printers = list((await db.execute(select(Printer).where(Printer.is_active.is_(True)).order_by(Printer.id))).scalars())
    virtuals = list((await db.execute(select(VirtualPrinter).order_by(VirtualPrinter.position, VirtualPrinter.id))).scalars())
    updated = False
    for printer in printers:
        updated = await _sync_real_printer_status(db, printer) or updated
    if updated:
        await db.commit()
    rows = list((await db.execute(select(ProductionPrinterStatus))).scalars())
    by_key = {row.target_key: row for row in rows}
    result: list[dict] = []
    for target_type, targets in (("printer", printers), ("virtual_printer", virtuals)):
        for target in targets:
            result.append(
                await _serialize(
                    db,
                    by_key.get(target_key(target_type, target.id)),
                    target_type=target_type,
                    target_id=target.id,
                )
            )
    return result


async def heartbeat(db: AsyncSession, payload: PrinterStatusHeartbeat) -> dict:
    """Apply one idempotent normalized heartbeat and return its status view."""

    existing_operation = await db.scalar(
        select(OperationLog).where(OperationLog.operation_id == payload.operation_id)
    )
    if existing_operation:
        target_type = str((existing_operation.payload or {}).get("target_type", payload.target_type))
        target_id = int((existing_operation.payload or {}).get("target_id", payload.target_id))
        row = await db.scalar(
            select(ProductionPrinterStatus).where(
                ProductionPrinterStatus.target_key == target_key(target_type, target_id)
            )
        )
        return await _serialize(db, row, target_type=target_type, target_id=target_id, replayed=True)

    await _target(db, payload.target_type, payload.target_id)
    key = target_key(payload.target_type, payload.target_id)
    row = await db.scalar(select(ProductionPrinterStatus).where(ProductionPrinterStatus.target_key == key))
    now = _now()
    if row is None:
        row = ProductionPrinterStatus(target_key=key, target_type=payload.target_type, target_id=payload.target_id)
        db.add(row)
    row.state = payload.state
    row.source = payload.source
    row.last_heartbeat_at = now
    row.observed_at = now
    row.current_job_id = payload.current_job_id
    row.current_job_state = payload.current_job_state
    row.fault_code = payload.fault_code
    row.fault_message = payload.fault_message
    row.loaded_filaments = payload.loaded_filaments
    row.telemetry = payload.telemetry
    await db.flush()
    db.add(
        OperationLog(
            operation_id=payload.operation_id,
            operation_type="stage13_printer_heartbeat",
            entity_type="printer_status",
            entity_id=row.id,
            payload={
                "target_type": payload.target_type,
                "target_id": payload.target_id,
                "state": payload.state,
                "source": payload.source,
            },
        )
    )
    await db.commit()
    await db.refresh(row)
    return await _serialize(db, row, target_type=payload.target_type, target_id=payload.target_id)


async def availability(db: AsyncSession, target_type: str, target_id: int) -> bool:
    if target_type == "printer":
        # The MQTT adapter is owned by PrinterManager.  Refresh the persisted
        # production snapshot at the point where allocation/dispatch asks for
        # availability, so a healthy connected printer is not rejected merely
        # because the status page has not been opened in the last 30 seconds.
        printer = await db.get(Printer, target_id)
        if printer is not None:
            # A printer with a finished plate is reserved until the operator
            # confirms physical cleanup. This check is kept at the shared
            # availability boundary as a second line of defence for any
            # allocator/dispatch caller.
            if printer.awaiting_plate_clear or printer_manager.is_awaiting_plate_clear(printer.id):
                return False
            if await _sync_real_printer_status(db, printer):
                await db.flush()
    row = await db.scalar(
        select(ProductionPrinterStatus).where(
            ProductionPrinterStatus.target_key == target_key(target_type, target_id)
        )
    )
    _, available, _, _ = _effective_state(row)
    return available
