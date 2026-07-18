"""Production product master data.

This is intentionally separate from ``Project``: projects group work and
archives, while products are stable production master data identified by SKU.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    recipes: Mapped[list[ProductionRecipe]] = relationship(back_populates="product")
    orders: Mapped[list[ProductionOrder]] = relationship(back_populates="product")


if TYPE_CHECKING:
    from backend.app.models.production import ProductionOrder
    from backend.app.models.production_recipe import ProductionRecipe
