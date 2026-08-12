"""Production consumable rolls with individually printable QR identities."""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base

CONSUMABLE_GENERATED = "generated"
CONSUMABLE_IN_STOCK = "in_stock"
CONSUMABLE_BOUND = "bound"
CONSUMABLE_DEPLETED = "depleted"
CONSUMABLE_SCRAPPED = "scrapped"
CONSUMABLE_STATUSES = (
    CONSUMABLE_GENERATED,
    CONSUMABLE_IN_STOCK,
    CONSUMABLE_BOUND,
    CONSUMABLE_DEPLETED,
    CONSUMABLE_SCRAPPED,
)


class ProductionConsumableUnit(Base):
    __tablename__ = "production_consumable_units"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("material_types.id", ondelete="RESTRICT"), index=True
    )
    unit_code: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default=CONSUMABLE_GENERATED, index=True)
    label_batch_id: Mapped[str] = mapped_column(String(64), index=True)
    # Per-roll cost basis captured when labels are generated.  These remain
    # nullable for legacy QR units created before cost tracking was enabled.
    initial_weight_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    remaining_weight_g: Mapped[float | None] = mapped_column(nullable=True)
    storage_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    depleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scrapped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    material_type = relationship("MaterialType")
    direct_bindings = relationship("ProductionPrinterConsumable", back_populates="consumable_unit")
    usage_events = relationship("ProductionConsumableUsage", back_populates="consumable_unit")
