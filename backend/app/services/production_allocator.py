"""Stage 9 transactional allocator for production plate jobs.

It creates rows in Bambuddy's existing print queue but intentionally leaves
them on a production safety hold.  Stage 9 never dispatches a print.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.database import async_session
from backend.app.models.operation_log import OperationLog
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.production import OrderStatus, PlateJob, PlateJobStatus, ProductionRequirement
from backend.app.services.production_eligibility import find_assignment

logger = logging.getLogger(__name__)

_sqlite_allocator_lock = asyncio.Lock()
_sqlite_limit_logged = False


async def _allocate(db: AsyncSession, plate_job_ids: Sequence[int] | None, limit: int) -> list[PlateJob]:
    query = (
        select(PlateJob)
        .join(PlateJob.requirement)
        .join(ProductionRequirement.order)
        .where(
            PlateJob.status == PlateJobStatus.DRAFT.value,
            PlateJob.queue_item_id.is_(None),
            ProductionRequirement.order.has(status=OrderStatus.PLANNED.value),
            ProductionRequirement.order.has(recalculation_required=False),
        )
        .options(selectinload(PlateJob.requirement))
        .order_by(PlateJob.id)
        .limit(limit)
    )
    if plate_job_ids is not None:
        query = query.where(PlateJob.id.in_(list(plate_job_ids)))
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True, of=PlateJob)

    jobs = list((await db.execute(query)).scalars().unique())
    allocated: list[PlateJob] = []
    for job in jobs:
        snapshot = job.requirement.recipe_snapshot or {}
        library_file_id = snapshot.get("library_file_id")
        if not library_file_id:
            logger.info("Plate job %s remains draft: print plan has no library file", job.id)
            continue

        assignment = await find_assignment(db, job)
        if assignment is None:
            continue

        job.printer_profile_id = assignment.profile.id
        if assignment.virtual_printer is not None:
            job.virtual_printer_id = assignment.virtual_printer.id
            job.status = PlateJobStatus.ASSIGNED.value
            db.add(
                OperationLog(
                    operation_id=f"stage9-allocate-virtual-plate-job-{job.id}",
                    operation_type="production_plate_job_allocated",
                    entity_type="production_order",
                    entity_id=job.requirement.order_id,
                    payload={
                        "plate_job_id": job.id,
                        "virtual_printer_id": assignment.virtual_printer.id,
                        "printer_profile_id": assignment.profile.id,
                        "simulation_only": True,
                    },
                )
            )
            allocated.append(job)
            continue

        max_position = (
            await db.execute(
                select(func.max(PrintQueueItem.position)).where(
                    PrintQueueItem.printer_id == assignment.printer.id,
                    PrintQueueItem.status == "pending",
                )
            )
        ).scalar_one_or_none()
        queue_item = PrintQueueItem(
            printer_id=assignment.printer.id,
            target_model=None,
            target_location=None,
            library_file_id=int(library_file_id),
            required_filament_types=assignment.required_filament_types,
            position=int(max_position or 0) + 1,
            status="pending",
            manual_start=True,
        )
        db.add(queue_item)
        await db.flush()
        job.queue_item_id = queue_item.id
        job.status = PlateJobStatus.ASSIGNED.value
        db.add(
            OperationLog(
                operation_id=f"stage9-allocate-plate-job-{job.id}",
                operation_type="production_plate_job_allocated",
                entity_type="production_order",
                entity_id=job.requirement.order_id,
                payload={
                    "plate_job_id": job.id,
                    "queue_item_id": queue_item.id,
                    "printer_id": assignment.printer.id,
                    "printer_profile_id": assignment.profile.id,
                    "simulation_only": True,
                },
            )
        )
        allocated.append(job)

    await db.commit()
    for job in allocated:
        await db.refresh(job)
    return allocated


async def allocate_plate_jobs(
    db: AsyncSession,
    *,
    plate_job_ids: Sequence[int] | None = None,
    limit: int = 50,
) -> list[PlateJob]:
    """Allocate draft jobs once, serializing SQLite within this process."""

    global _sqlite_limit_logged
    if db.get_bind().dialect.name != "sqlite":
        return await _allocate(db, plate_job_ids, limit)

    if not _sqlite_limit_logged:
        logger.warning("SQLite production allocation is limited to one Bambuddy process")
        _sqlite_limit_logged = True
    async with _sqlite_allocator_lock:
        return await _allocate(db, plate_job_ids, limit)


class ProductionAllocator:
    """Small recovery loop; assignment remains software-only and held."""

    def __init__(self, interval_seconds: float = 5.0):
        self.interval_seconds = interval_seconds
        self._running = False

    async def run(self) -> None:
        self._running = True
        logger.info("Production allocator started in stage 9 simulation-only mode")
        while self._running:
            try:
                async with async_session() as db:
                    await allocate_plate_jobs(db)
            except Exception:
                logger.exception("Production allocator pass failed")
            await asyncio.sleep(self.interval_seconds)

    def stop(self) -> None:
        self._running = False


production_allocator = ProductionAllocator()
