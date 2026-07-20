"""Product-owned source 3MF files and their production strategy."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class ProductFile(Base):
    __tablename__ = "product_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    library_file_id: Mapped[int] = mapped_column(ForeignKey("library_files.id", ondelete="RESTRICT"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    # Product-level colour variant represented by this source file. This is
    # distinct from per-slot filament requirements: one product may have
    # separate red/white files, each with its own material mapping.
    product_color: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategy: Mapped[str] = mapped_column(String(30), default="fixed_plate")
    component_ids: Mapped[list] = mapped_column(JSON, default=list)
    units_per_plate: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    # For multi-plate fixed projects, one product set is one copy of every
    # source plate.  This is detected from the uploaded 3MF and is never
    # treated as an auto-pack capacity.
    source_plate_count: Mapped[int] = mapped_column(default=1, nullable=False)
    # Separate source files uploaded for one multi-plate product share this
    # group id and carry their zero-based source plate position.
    source_set_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_plate_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    compatible_printer_models: Mapped[list] = mapped_column(JSON, default=list)
    # Per-slot material/colour requirements extracted from or confirmed for
    # the source 3MF, e.g. [{"slot": 0, "material": "PLA", "color": "#FFFFFF"}].
    filament_requirements: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    product = relationship("Product", back_populates="product_files")
    library_file = relationship("LibraryFile")
