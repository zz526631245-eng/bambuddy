"""Versioned production eligibility profile for a class of printers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class PrinterProfile(Base):
    __tablename__ = "printer_profiles"
    __table_args__ = (
        CheckConstraint("nozzle_diameter > 0", name="ck_printer_profiles_nozzle_diameter_positive"),
        CheckConstraint("version >= 1", name="ck_printer_profiles_version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    printer_model: Mapped[str] = mapped_column(String(50), index=True)
    nozzle_diameter: Mapped[float] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255))
    profile_group: Mapped[str | None] = mapped_column(String(100))
    auto_production_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    recipes: Mapped[list[ProductionRecipe]] = relationship(back_populates="printer_profile")
    compatible_recipes = relationship(
        "ProductionRecipe", secondary="production_recipe_profiles", back_populates="compatible_profiles"
    )
    plate_jobs: Mapped[list[PlateJob]] = relationship(back_populates="printer_profile")


if TYPE_CHECKING:
    from backend.app.models.production import PlateJob
    from backend.app.models.production_recipe import ProductionRecipe
