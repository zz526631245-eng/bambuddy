"""Persistent outputs of real slicer runs that can be reused safely."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class SliceArtifact(Base):
    """A cached sliced file keyed by the exact source and slicer inputs.

    The source hash/version and settings fingerprint make reuse explicit: a
    changed product source, strategy, or target printer creates a new artifact
    rather than silently reusing an old G-code file.
    """

    __tablename__ = "slice_artifacts"
    __table_args__ = (UniqueConstraint("settings_fingerprint", name="uq_slice_artifacts_fingerprint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_product_file_id: Mapped[int] = mapped_column(
        ForeignKey("product_files.id", ondelete="RESTRICT"), index=True
    )
    source_library_file_id: Mapped[int] = mapped_column(
        ForeignKey("library_files.id", ondelete="RESTRICT"), index=True
    )
    output_library_file_id: Mapped[int] = mapped_column(
        ForeignKey("library_files.id", ondelete="RESTRICT"), unique=True, index=True
    )
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    strategy: Mapped[str] = mapped_column(String(30), nullable=False)
    target_printer_preset: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_printer_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    settings_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    arranged_by_slicer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    print_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filament_used_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    filament_used_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
