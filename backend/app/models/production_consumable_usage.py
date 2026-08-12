"""Auditable filament consumption events for production prints."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class ProductionConsumableUsage(Base):
    """One measured/estimated gram deduction from one labelled consumable roll.

    ``operation_id`` makes the completion callback idempotent: MQTT may report
    a terminal state more than once, but a print must only deduct material once.
    """

    __tablename__ = "production_consumable_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    consumable_unit_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("production_consumable_units.id", ondelete="SET NULL"), nullable=True, index=True
    )
    queue_item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("print_queue.id", ondelete="SET NULL"), nullable=True, index=True
    )
    plate_job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("plate_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    printer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("printers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    operation_id: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    consumed_g: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="slicer_estimate")
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    consumable_unit = relationship("ProductionConsumableUnit", back_populates="usage_events")
