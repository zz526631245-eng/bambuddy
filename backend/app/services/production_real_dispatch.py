"""Stage 14 controlled dispatch to one real Bambu printer.

The production domain never talks to MQTT or FTP directly.  This service
performs the audited hand-off into Bambuddy's existing print queue; the normal
queue scheduler remains responsible for FTP upload and MQTT start.  Manual
dispatch remains available from the slice library, while eligible production
jobs use the same hand-off automatically.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.models.library import LibraryFile
from backend.app.models.operation_log import OperationLog
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.production import PlateJob, PlateJobStatus
from backend.app.models.slice_artifact import SliceArtifact
from backend.app.schemas.production import RealPrinterDispatchRequest
from backend.app.services.printer_manager import printer_manager
from backend.app.services.production_printer_status import availability

REAL_ACTIVE_JOB_STATUSES = frozenset(
    {
        PlateJobStatus.ASSIGNED.value,
        PlateJobStatus.READY.value,
        PlateJobStatus.PRINTING.value,
        PlateJobStatus.WAITING_CLEANUP.value,
    }
)


async def auto_dispatch_real_slice_job(db: AsyncSession, job: PlateJob) -> dict[str, Any] | None:
    """Automatically hand one complete real slice to the existing queue.

    Allocation and slicing happen in the production service, while this
    helper performs the same audited queue replacement as the explicit Stage
    14 endpoint.  A job with several output plates is left held because the
    current ``PlateJob`` relation represents one queue item; auto-dispatching
    only the first artifact would silently under-produce the order.
    """

    if job.virtual_printer_id is not None or job.status != PlateJobStatus.ASSIGNED.value:
        return None
    if job.slice_time_review_status == "pending":
        # A plate estimated above the configured limit is held until the
        # operator approves it or rejects it for a smaller re-pack.
        return None
    if job.slice_status != "succeeded" or job.queue_item_id is None:
        return None
    result = job.slice_result if isinstance(job.slice_result, dict) else {}
    plates = [item for item in result.get("plates") or [] if isinstance(item, dict)]
    if len(plates) > 1:
        return None
    artifact_id = result.get("slice_artifact_id")
    if not isinstance(artifact_id, int) and plates:
        artifact_id = plates[0].get("slice_artifact_id")
    if not isinstance(artifact_id, int):
        return None
    held_queue = await db.get(PrintQueueItem, job.queue_item_id)
    if held_queue is None or held_queue.status != "pending" or not held_queue.manual_start:
        return None
    payload = RealPrinterDispatchRequest(
        operation_id=f"stage14-auto-dispatch-job-{job.id}-artifact-{artifact_id}",
        printer_id=held_queue.printer_id,
        plate_job_id=job.id,
        confirm=True,
    )
    return await dispatch_real_slice_artifact(db, artifact_id, payload, manual_confirmation=False)


def _artifact_ids(slice_result: dict | None) -> set[int]:
    """Return all artifact ids represented by a plate-job slice result."""

    if not isinstance(slice_result, dict):
        return set()
    ids: set[int] = set()
    for key in ("slice_artifact_id",):
        value = slice_result.get(key)
        if isinstance(value, int):
            ids.add(value)
    for plate in slice_result.get("plates") or []:
        if isinstance(plate, dict) and isinstance(plate.get("slice_artifact_id"), int):
            ids.add(plate["slice_artifact_id"])
    return ids


def _local_file_path(file_row: LibraryFile) -> Path:
    path = Path(file_row.file_path)
    return path if path.is_absolute() else settings.base_dir / path


async def _response_from_operation(
    db: AsyncSession,
    operation: OperationLog,
    *,
    replayed: bool = True,
) -> dict:
    payload = operation.payload or {}
    queue_item_id = payload.get("queue_item_id")
    queue_item = await db.get(PrintQueueItem, queue_item_id) if queue_item_id else None
    if queue_item is None:
        raise ValueError("该受控发送操作的队列记录不存在，不能重放")
    printer = await db.get(Printer, queue_item.printer_id)
    if printer is None:
        raise ValueError("该受控发送操作的打印机不存在")
    return {
        "operation_id": operation.operation_id,
        "artifact_id": int(payload.get("artifact_id")),
        "plate_job_id": payload.get("plate_job_id"),
        "queue_item_id": queue_item.id,
        "printer_id": printer.id,
        "printer_name": printer.name,
        "printer_model": printer.model,
        "queue_status": queue_item.status,
        "manual_confirmation": bool(payload.get("manual_confirmation", True)),
        "transport": "existing_bambuddy_queue",
        "replayed": replayed,
    }


async def _resolve_plate_job(
    db: AsyncSession,
    *,
    artifact_id: int,
    requested_plate_job_id: int | None,
) -> PlateJob:
    """Resolve the production job that owns a real-slice artifact."""

    if requested_plate_job_id is not None:
        job = (
            await db.execute(
                select(PlateJob)
                .where(PlateJob.id == requested_plate_job_id)
                .options(selectinload(PlateJob.requirement))
            )
        ).scalar_one_or_none()
        if job is None:
            raise LookupError("生产盘任务不存在")
        if artifact_id not in _artifact_ids(job.slice_result):
            raise ValueError("切片结果与生产盘任务不匹配")
        return job

    jobs = list(
        (
            await db.execute(
                select(PlateJob).options(selectinload(PlateJob.requirement)).order_by(PlateJob.id)
            )
        ).scalars()
    )
    matches = [job for job in jobs if artifact_id in _artifact_ids(job.slice_result)]
    if not matches:
        raise ValueError("该切片结果未关联生产盘任务，不能进入第14阶段受控发送")
    if len(matches) > 1:
        raise ValueError("该切片结果关联了多个生产盘任务，请指定 plate_job_id")
    return matches[0]


async def dispatch_real_slice_artifact(
    db: AsyncSession,
    artifact_id: int,
    payload: RealPrinterDispatchRequest,
    *,
    actor_user_id: int | None = None,
    manual_confirmation: bool = True,
) -> dict:
    """Queue one real-printer print after an explicit or automatic hand-off.

    This is deliberately a single-printer operation.  It does not select a
    printer, connect to a device, upload a file, or call ``start_print``.  The
    existing scheduler performs the transport after this audited hand-off.
    """

    if not payload.confirm:
        raise ValueError("必须明确确认后才能发送到真实打印机")

    existing_operation = await db.scalar(
        select(OperationLog).where(OperationLog.operation_id == payload.operation_id)
    )
    if existing_operation is not None:
        existing_payload = existing_operation.payload or {}
        if (
            existing_operation.operation_type != "stage14_real_printer_dispatch"
            or existing_payload.get("artifact_id") != artifact_id
            or existing_payload.get("printer_id") != payload.printer_id
        ):
            raise ValueError("该操作编号已经用于其他第14阶段发送操作")
        return await _response_from_operation(db, existing_operation)

    artifact = await db.get(SliceArtifact, artifact_id)
    if artifact is None:
        raise LookupError("切片结果不存在")
    output_file = await db.scalar(
        LibraryFile.active().where(LibraryFile.id == artifact.output_library_file_id)
    )
    if output_file is None or not _local_file_path(output_file).exists():
        raise ValueError("切片文件不存在或已移入回收站，不能发送")

    printer = await db.get(Printer, payload.printer_id)
    if printer is None or not printer.is_active:
        raise LookupError("真实打印机不存在或已停用")
    if printer.awaiting_plate_clear or printer_manager.is_awaiting_plate_clear(printer.id):
        raise ValueError("打印机上一盘尚未确认清理料盘，不能接收新的打印任务")
    if not printer_manager.is_connected(printer.id):
        raise ValueError("真实打印机当前未连接，无法进入第14阶段受控发送")
    if not await availability(db, "printer", printer.id):
        raise ValueError("真实打印机当前不可用，无法发送")

    job = await _resolve_plate_job(
        db,
        artifact_id=artifact_id,
        requested_plate_job_id=payload.plate_job_id,
    )
    if job.virtual_printer_id is not None:
        raise ValueError("虚拟打印机任务不能发送到真实打印机")
    if job.status in {PlateJobStatus.PRINTING.value, PlateJobStatus.WAITING_CLEANUP.value}:
        raise ValueError("该生产盘任务已经开始执行，不能重复发送")
    if job.status in {PlateJobStatus.COMPLETED.value, PlateJobStatus.CANCELLED.value}:
        raise ValueError("已完成或已取消的生产盘任务不能发送")
    if job.queue_item_id is not None:
        old_queue = await db.get(PrintQueueItem, job.queue_item_id)
        if old_queue is not None and old_queue.status == "printing":
            raise ValueError("该生产盘任务已经存在正在打印的队列记录")
        if old_queue is not None and old_queue.status == "pending":
            # Stage 9 created a held source-file queue row.  Preserve it for
            # audit but replace it with the verified real-slice artifact.
            old_queue.status = "cancelled"
            old_queue.error_message = "第14阶段：已由确认后的真实切片文件替换"
        job.queue_item_id = None

    # Stage 14 is intentionally single-machine.  A second active production
    # job on this printer must be cleared or finished before another dispatch.
    active_query = (
        select(PlateJob)
        .join(PrintQueueItem, PlateJob.queue_item_id == PrintQueueItem.id)
        .where(PrintQueueItem.printer_id == printer.id)
        .where(PrintQueueItem.status.in_(("pending", "printing")))
        .where(PlateJob.status.in_(REAL_ACTIVE_JOB_STATUSES))
    )
    active_jobs = list((await db.execute(active_query)).scalars().all())
    active_jobs = [row for row in active_jobs if row.id != job.id]
    if active_jobs:
        raise ValueError("第14阶段一次只允许一台真实打印机执行一个生产盘任务")

    max_position = await db.scalar(
        select(func.max(PrintQueueItem.position)).where(
            PrintQueueItem.printer_id == printer.id,
            PrintQueueItem.status == "pending",
        )
    )
    queue_item = PrintQueueItem(
        printer_id=printer.id,
        library_file_id=output_file.id,
        position=int(max_position or 0) + 1,
        status="pending",
        # The endpoint itself is the human confirmation.  Once accepted the
        # existing scheduler may upload/start it when the printer is idle.
        manual_start=False,
        print_time_seconds=artifact.print_time_seconds,
        created_by_id=actor_user_id,
    )
    db.add(queue_item)
    await db.flush()

    job.queue_item_id = queue_item.id
    job.virtual_printer_id = None
    job.status = PlateJobStatus.READY.value
    job.machine_result = None
    job.print_started_at = None
    job.print_finished_at = None

    db.add(
        OperationLog(
            operation_id=payload.operation_id,
            operation_type="stage14_real_printer_dispatch",
            entity_type="slice_artifact",
            entity_id=artifact.id,
            actor_user_id=actor_user_id,
            payload={
                "artifact_id": artifact.id,
                "plate_job_id": job.id,
                "queue_item_id": queue_item.id,
                "printer_id": printer.id,
                "manual_confirmation": manual_confirmation,
                "transport": "existing_bambuddy_queue",
            },
        )
    )
    await db.commit()
    return {
        "operation_id": payload.operation_id,
        "artifact_id": artifact.id,
        "plate_job_id": job.id,
        "queue_item_id": queue_item.id,
        "printer_id": printer.id,
        "printer_name": printer.name,
        "printer_model": printer.model,
        "queue_status": queue_item.status,
        "manual_confirmation": manual_confirmation,
        "transport": "existing_bambuddy_queue",
        "replayed": False,
    }


async def mark_real_job_started(db: AsyncSession, printer_id: int) -> int | None:
    """Mirror a confirmed production queue start into its plate-job workflow."""

    job = await db.scalar(
        select(PlateJob)
        .join(PrintQueueItem, PlateJob.queue_item_id == PrintQueueItem.id)
        .options(selectinload(PlateJob.requirement))
        .where(
            PrintQueueItem.printer_id == printer_id,
            PrintQueueItem.status == "printing",
            PlateJob.virtual_printer_id.is_(None),
        )
        .order_by(PrintQueueItem.started_at.desc(), PrintQueueItem.id.desc())
        .limit(1)
    )
    if job is None or job.status not in {PlateJobStatus.ASSIGNED.value, PlateJobStatus.READY.value}:
        return None
    job.status = PlateJobStatus.PRINTING.value
    job.print_started_at = job.print_started_at or datetime.utcnow()
    db.add(
        OperationLog(
            operation_id=f"stage14-real-start-queue-{job.queue_item_id}",
            operation_type="stage14_real_printer_started",
            entity_type="production_order",
            entity_id=job.requirement.order_id,
            payload={"plate_job_id": job.id, "queue_item_id": job.queue_item_id, "printer_id": printer_id},
        )
    )
    await db.commit()
    return job.id


async def mark_real_job_finished(db: AsyncSession, queue_item_id: int, queue_status: str) -> int | None:
    """Move a real production job to quality review after an MQTT completion."""

    job = await db.scalar(
        select(PlateJob)
        .where(PlateJob.queue_item_id == queue_item_id, PlateJob.virtual_printer_id.is_(None))
        .options(selectinload(PlateJob.requirement))
    )
    if job is None or job.status not in {PlateJobStatus.PRINTING.value, PlateJobStatus.READY.value}:
        return None
    machine_result = "completed" if queue_status == "completed" else "failed"
    job.status = PlateJobStatus.WAITING_CLEANUP.value
    job.machine_result = machine_result
    job.print_finished_at = datetime.utcnow()
    db.add(
        OperationLog(
            operation_id=f"stage14-real-finish-queue-{queue_item_id}",
            operation_type="stage14_real_printer_finished",
            entity_type="production_order",
            entity_id=job.requirement.order_id,
            payload={
                "plate_job_id": job.id,
                "queue_item_id": queue_item_id,
                "machine_result": machine_result,
            },
        )
    )
    await db.commit()
    return job.id
