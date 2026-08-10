"""Stage 6 create/read schemas for production-domain skeleton APIs."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


class _FromAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MaterialTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    material: str = Field(min_length=1, max_length=50)
    subtype: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=100)
    color_name: str | None = Field(default=None, max_length=100)
    color_hex: str | None = Field(default=None, pattern=r"^#?[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
    is_active: bool = True

    _strip_code = field_validator("code", "material")(_strip_required)

    @field_validator("code", "material")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("subtype", "brand", "color_name")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("color_hex")
    @classmethod
    def normalize_hex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return "#" + value.lstrip("#").upper()


class MaterialTypeResponse(_FromAttributes):
    id: int
    code: str
    material: str
    subtype: str | None
    brand: str | None
    color_name: str | None
    color_hex: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PrinterProfileCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    printer_model: str = Field(min_length=1, max_length=50)
    nozzle_diameter: float = Field(gt=0)
    version: int = Field(default=1, ge=1)
    location: str | None = Field(default=None, max_length=255)
    profile_group: str | None = Field(default=None, max_length=100)
    auto_production_enabled: bool = False
    is_active: bool = True
    supported_materials: list[str] = []
    supported_colors: list[str] = []

    _strip_fields = field_validator("code", "name", "printer_model")(_strip_required)


class PrinterProfileResponse(_FromAttributes):
    id: int
    code: str
    name: str
    printer_model: str
    nozzle_diameter: float
    version: int
    location: str | None
    profile_group: str | None
    auto_production_enabled: bool
    is_active: bool
    supported_materials: list[str]
    supported_colors: list[str]
    created_at: datetime
    updated_at: datetime


class ProductionRecipeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    product_id: int
    component_id: int | None = None
    material_type_id: int | None = None
    printer_profile_id: int | None = None
    library_file_id: int | None = None
    slicer_pipeline_id: int | None = None
    slicer_preset: str | None = Field(default=None, max_length=255)
    compatible_profile_ids: list[int] = []
    version: int = Field(default=1, ge=1)
    is_active: bool = True

    _strip_fields = field_validator("code", "name")(_strip_required)


class ProductionRecipeResponse(_FromAttributes):
    id: int
    code: str
    name: str
    product_id: int
    component_id: int | None
    material_type_id: int | None
    printer_profile_id: int | None
    library_file_id: int | None
    slicer_pipeline_id: int | None
    slicer_preset: str | None
    compatible_profile_ids: list[int] = []
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductionOrderCreate(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    order_number: str | None = Field(default=None, max_length=100)
    product_id: int
    product_file_id: int | None = None
    quantity: int = Field(ge=1)
    priority: int = Field(default=0, ge=0)
    due_at: datetime | None = None
    notes: str | None = None

    _strip_operation_id = field_validator("operation_id")(_strip_required)

    @field_validator("order_number")
    @classmethod
    def normalize_order_number(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ProductionOrderResponse(_FromAttributes):
    id: int
    order_number: str
    product_id: int
    quantity: int
    priority: int
    status: str
    due_at: datetime | None
    notes: str | None
    recalculation_required: bool = False
    product_snapshot: dict | None
    bom_snapshot: list | None
    recipe_snapshot: list | None
    product_file_snapshot: dict | None = None
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


class ProductionRequirementResponse(_FromAttributes):
    id: int
    order_id: int
    recipe_id: int | None
    product_file_id: int | None = None
    component_id: int | None
    unit_quantity: float
    required_quantity: int
    reserved_quantity: int
    good_quantity: int
    scrap_quantity: int
    component_snapshot: dict | None
    recipe_snapshot: dict | None
    status: str
    created_at: datetime
    updated_at: datetime


class PlateJobResponse(_FromAttributes):
    id: int
    requirement_id: int
    printer_profile_id: int | None
    queue_item_id: int | None
    virtual_printer_id: int | None = None
    printer_profile_name: str | None = None
    printer_model: str | None = None
    virtual_printer_name: str | None = None
    queue_status: str | None = None
    planned_quantity: int
    status: str
    workflow_status: str
    machine_result: str | None = None
    quality_good_quantity: int | None = None
    quality_scrap_quantity: int | None = None
    print_started_at: datetime | None = None
    print_finished_at: datetime | None = None
    quality_confirmed_at: datetime | None = None
    cleanup_confirmed_at: datetime | None = None
    slice_status: str
    slice_attempts: int
    slice_error: str | None
    slice_result: dict | None
    source_plate_index: int = 0
    product_set_index: int = 0
    sliced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OperationLogResponse(_FromAttributes):
    id: int
    operation_id: str
    operation_type: str
    entity_type: str
    entity_id: int | None
    actor_user_id: int | None
    payload: dict | None
    created_at: datetime


class QuantityLedgerResponse(BaseModel):
    planned: int
    reserved: int
    good: int
    scrap: int
    remaining: int


class ProductionOrderUpdate(BaseModel):
    priority: int | None = Field(default=None, ge=0)
    due_at: datetime | None = None
    notes: str | None = None


class ProductionOrderStatusAction(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    action: Literal["pause", "resume"]

    _strip_operation = field_validator("operation_id", "action")(_strip_required)


class ProductionOrderCancelAction(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)

    _strip_operation = field_validator("operation_id")(_strip_required)


class PlateJobPreviewItem(BaseModel):
    requirement_id: int
    printer_profile_id: int | None
    planned_quantity: int = Field(gt=0)
    component_name: str
    print_plan_name: str
    strategy: str = "fixed_plate"
    source_plate_count: int = 1


class PlateJobPreviewResponse(BaseModel):
    order_id: int
    items: list[PlateJobPreviewItem]


class RealSliceRequest(BaseModel):
    """Optional printer identity override for an embedded-settings slice."""

    target_printer_preset: str | None = Field(default=None, min_length=1, max_length=255)
    target_printer_model: str | None = Field(default=None, min_length=1, max_length=100)


class SliceArtifactResponse(BaseModel):
    id: int
    source_product_file_id: int
    source_library_file_id: int
    output_library_file_id: int
    output_file_name: str | None = None
    source_sha256: str
    source_version: int
    strategy: str
    target_printer_preset: str | None
    target_printer_model: str | None
    settings_fingerprint: str
    arranged_by_slicer: bool
    print_time_seconds: int | None
    filament_used_g: float | None
    filament_used_mm: float | None
    output_sha256: str
    created_at: datetime
    updated_at: datetime


class ProductOrderSummaryResponse(BaseModel):
    product_id: int
    total_quantity: int
    completed_quantity: int
    pending_quantity: int


class PlateJobConfirmRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    items: list[PlateJobPreviewItem] = Field(min_length=1)

    _strip_operation = field_validator("operation_id")(_strip_required)


class PlateJobConfirmResponse(BaseModel):
    order_id: int
    items: list[PlateJobResponse]


class PlateJobWorkflowAction(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    machine_result: Literal["completed", "failed"] | None = None
    good_quantity: int | None = Field(default=None, ge=0)

    _strip_operation = field_validator("operation_id")(_strip_required)


class ProductionRequirementDetail(ProductionRequirementResponse):
    ledger: QuantityLedgerResponse
    plate_jobs: list[PlateJobResponse]


class ProductionOrderDetail(ProductionOrderResponse):
    requirements: list[ProductionRequirementDetail]
    operations: list[OperationLogResponse]
