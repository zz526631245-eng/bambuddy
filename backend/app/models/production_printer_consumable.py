"""Current direct-feed consumable bindings for production printers.

This is deliberately separate from AMS slot assignments.  A direct-feed scan
replaces the current binding for one printer and keeps the replaced row as an
audit record.  The same contract can be populated by a real scanner later;
Stage 12 only exposes the software/API path and never connects to hardware.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class ProductionPrinterConsumable(Base):
    __tablename__ = "production_printer_consumables"
    __table_args__ = (
        CheckConstraint(
            "(printer_id IS NOT NULL AND virtual_printer_id IS NULL) "
            "OR (printer_id IS NULL AND virtual_printer_id IS NOT NULL)",
            name="ck_production_consumable_one_printer",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    printer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("printers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    virtual_printer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("virtual_printers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    spool_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("spool.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scan_code: Mapped[str] = mapped_column(String(128), index=True)
    material: Mapped[str] = mapped_column(String(50))
    color_hex: Mapped[str] = mapped_column(String(8))
    color_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="scanner")
    operation_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    replaced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    spool = relationship("Spool")
    printer = relationship("Printer")
    virtual_printer = relationship("VirtualPrinter")
