"""Minimal production order, requirement and plate-job skeleton."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
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

from backend.app.core.compat import StrEnum
from backend.app.core.database import Base


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RequirementStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PlateJobStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ASSIGNED = "assigned"
    PRINTING = "printing"
    WAITING_CLEANUP = "waiting_cleanup"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


PRODUCTION_TABLE_NAMES = {
    "products",
    "material_types",
    "printer_profiles",
    "production_recipes",
    "production_orders",
    "production_requirements",
    "plate_jobs",
    "operation_logs",
    "product_images",
    "product_components",
    "production_bom_items",
    "production_recipe_profiles",
    "material_type_spool_mappings",
    "slice_artifacts",
    "production_printer_status",
}


class ProductionOrder(Base):
    __tablename__ = "production_orders"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_production_orders_quantity_non_negative"),
        CheckConstraint("priority >= 0", name="ck_production_orders_priority_non_negative"),
        CheckConstraint(
            "status IN ('draft', 'planned', 'paused', 'completed', 'cancelled')",
            name="ck_production_orders_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_number: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=OrderStatus.DRAFT.value, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    recalculation_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    product_snapshot: Mapped[dict | None] = mapped_column(JSON)
    bom_snapshot: Mapped[list | None] = mapped_column(JSON)
    recipe_snapshot: Mapped[list | None] = mapped_column(JSON)
    product_file_snapshot: Mapped[dict | None] = mapped_column(JSON)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    product: Mapped[Product] = relationship(back_populates="orders")
    requirements: Mapped[list[ProductionRequirement]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class ProductionRequirement(Base):
    __tablename__ = "production_requirements"
    __table_args__ = (
        UniqueConstraint("order_id", "recipe_id", name="uq_production_requirements_order_recipe"),
        CheckConstraint(
            "required_quantity >= 0",
            name="ck_production_requirements_required_quantity_non_negative",
        ),
        CheckConstraint("unit_quantity > 0", name="ck_production_requirements_unit_quantity_positive"),
        CheckConstraint(
            "reserved_quantity >= 0",
            name="ck_production_requirements_reserved_quantity_non_negative",
        ),
        CheckConstraint("good_quantity >= 0", name="ck_production_requirements_good_quantity_non_negative"),
        CheckConstraint("scrap_quantity >= 0", name="ck_production_requirements_scrap_quantity_non_negative"),
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'cancelled')",
            name="ck_production_requirements_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("production_orders.id", ondelete="CASCADE"), index=True)
    recipe_id: Mapped[int | None] = mapped_column(ForeignKey("production_recipes.id", ondelete="RESTRICT"), nullable=True, index=True)
    product_file_id: Mapped[int | None] = mapped_column(ForeignKey("product_files.id", ondelete="RESTRICT"), nullable=True, index=True)
    component_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_components.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    unit_quantity: Mapped[float] = mapped_column(Float, default=1, nullable=False)
    required_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    good_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    scrap_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    component_snapshot: Mapped[dict | None] = mapped_column(JSON)
    recipe_snapshot: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default=RequirementStatus.PENDING.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    order: Mapped[ProductionOrder] = relationship(back_populates="requirements")
    recipe: Mapped[ProductionRecipe] = relationship(back_populates="requirements")
    component = relationship("ProductComponent")
    plate_jobs: Mapped[list[PlateJob]] = relationship(back_populates="requirement", cascade="all, delete-orphan")


class PlateJob(Base):
    __tablename__ = "plate_jobs"
    __table_args__ = (
        CheckConstraint("planned_quantity >= 0", name="ck_plate_jobs_planned_quantity_non_negative"),
        CheckConstraint(
            "status IN ('draft', 'ready', 'assigned', 'printing', 'waiting_cleanup', "
            "'completed', 'failed', 'cancelled')",
            name="ck_plate_jobs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(
        ForeignKey("production_requirements.id", ondelete="CASCADE"), index=True
    )
    printer_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("printer_profiles.id", ondelete="SET NULL"), nullable=True
    )
    queue_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("print_queue.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    planned_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default=PlateJobStatus.DRAFT.value, nullable=False)
    # Stage 10 simulated slicing state. These fields store the deterministic
    # plan and its source association; they never imply that a print was sent.
    slice_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    slice_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    slice_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    slice_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sliced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Stage 11 virtual workflow facts.  ``waiting_cleanup`` is intentionally
    # reused for both review phases to keep old SQLite status constraints
    # compatible: a missing quality timestamp means "awaiting quality" and a
    # present timestamp means "waiting for plate cleanup".
    machine_result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    quality_good_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_scrap_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    print_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    print_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quality_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cleanup_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    requirement: Mapped[ProductionRequirement] = relationship(back_populates="plate_jobs")
    printer_profile: Mapped[PrinterProfile | None] = relationship(back_populates="plate_jobs")
    queue_item: Mapped[PrintQueueItem | None] = relationship(
        back_populates="production_plate_job",
        foreign_keys=[queue_item_id],
        uselist=False,
    )
    virtual_printer_id: Mapped[int | None] = mapped_column(
        ForeignKey("virtual_printers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Multi-plate fixed source files expand into one physical job per product
    # set and source-plate role.  Single-plate jobs keep the default values.
    source_plate_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    product_set_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @property
    def workflow_status(self) -> str:
        if self.status == PlateJobStatus.WAITING_CLEANUP.value:
            return "waiting_cleanup" if self.quality_confirmed_at else "awaiting_quality"
        return self.status


if TYPE_CHECKING:
    from backend.app.models.print_queue import PrintQueueItem
    from backend.app.models.printer_profile import PrinterProfile
    from backend.app.models.product import Product
    from backend.app.models.production_recipe import ProductionRecipe
