"""Stage 13 production printer health snapshots.

The production layer stores a normalized status snapshot for both physical
and virtual targets.  Stage 13 only accepts simulated/adapter heartbeats; it
does not open a printer connection or send a print command.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class ProductionPrinterStatus(Base):
    __tablename__ = "production_printer_status"
    __table_args__ = (UniqueConstraint("target_key", name="uq_production_printer_status_target"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="stage13_simulation")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    current_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_job_state: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fault_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fault_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    loaded_filaments: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    telemetry: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
