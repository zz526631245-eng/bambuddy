"""Versioned links between products and reusable Bambuddy production inputs."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class ProductionRecipe(Base):
    __tablename__ = "production_recipes"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_production_recipes_code_version"),
        CheckConstraint("version >= 1", name="ck_production_recipes_version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(255))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    material_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_types.id", ondelete="SET NULL"), nullable=True
    )
    printer_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("printer_profiles.id", ondelete="SET NULL"), nullable=True
    )
    library_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_files.id", ondelete="SET NULL"), nullable=True
    )
    slicer_pipeline_id: Mapped[int | None] = mapped_column(
        ForeignKey("slicer_pipelines.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    product: Mapped[Product] = relationship(back_populates="recipes")
    material_type: Mapped[MaterialType | None] = relationship(back_populates="recipes")
    printer_profile: Mapped[PrinterProfile | None] = relationship(back_populates="recipes")
    requirements: Mapped[list[ProductionRequirement]] = relationship(back_populates="recipe")


if TYPE_CHECKING:
    from backend.app.models.material_type import MaterialType
    from backend.app.models.printer_profile import PrinterProfile
    from backend.app.models.product import Product
    from backend.app.models.production import ProductionRequirement
