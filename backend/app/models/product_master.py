"""Stage 7 product images, reusable components and production BOM."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (CheckConstraint("file_size >= 0", name="ck_product_images_file_size_nonnegative"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    file_size: Mapped[int] = mapped_column(Integer)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    product = relationship("Product", back_populates="images")


class ProductComponent(Base):
    __tablename__ = "product_components"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(30), default="pcs", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    bom_items = relationship("ProductionBOMItem", back_populates="component")


class ProductionBOMItem(Base):
    __tablename__ = "production_bom_items"
    __table_args__ = (
        UniqueConstraint("product_id", "component_id", name="uq_production_bom_product_component"),
        CheckConstraint("quantity > 0", name="ck_production_bom_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("product_components.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)

    product = relationship("Product", back_populates="bom_items")
    component = relationship("ProductComponent", back_populates="bom_items")


class MaterialTypeSpoolMapping(Base):
    """Optional non-invasive link from existing inventory spools to normalized material types."""

    __tablename__ = "material_type_spool_mappings"
    material_type_id: Mapped[int] = mapped_column(ForeignKey("material_types.id", ondelete="CASCADE"), primary_key=True)
    spool_id: Mapped[int] = mapped_column(ForeignKey("spool.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
