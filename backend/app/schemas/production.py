"""Stage 6 create/read schemas for production-domain skeleton APIs."""

from datetime import datetime
from typing import Any, Literal

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
    consumable_stats: dict[str, Any] = Field(default_factory=dict)


class PrinterConsumableScan(BaseModel):
    """Payload emitted by a direct-feed barcode/NFC scanner."""

    operation_id: str = Field(min_length=1, max_length=100)
    scan_code: str = Field(min_length=1, max_length=128)
    # Material and colour can be omitted when a generated consumable unit is
    # scanned: the backend derives them from the unit's material master.
    material: str | None = Field(default=None, min_length=1, max_length=50)
    color_hex: str | None = Field(default=None, min_length=6, max_length=8)
    color_name: str | None = Field(default=None, max_length=100)
    spool_id: int | None = None
    consumable_unit_id: int | None = None
    printer_id: int | None = None
    virtual_printer_id: int | None = None

    _strip_fields = field_validator("operation_id", "scan_code")(_strip_required)

    @field_validator("material")
    @classmethod
    def normalize_material(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("color_hex")
    @classmethod
    def normalize_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lstrip("#").upper()
        if len(value) not in (6, 8) or any(char not in "0123456789ABCDEF" for char in value):
            raise ValueError("color_hex must be a 6 or 8 digit hexadecimal color")
        return value


class PrinterConsumableResponse(_FromAttributes):
    id: int
    printer_id: int | None
    virtual_printer_id: int | None
    printer_name: str | None
    virtual_printer_name: str | None
    spool_id: int | None
    consumable_unit_id: int | None
    scan_code: str
    material: str
    color_hex: str
    color_name: str | None
    source: str
    operation_id: str
    is_active: bool
    scanned_at: datetime
    replaced_at: datetime | None


class PrinterConsumableScanResponse(PrinterConsumableResponse):
    replayed: bool = False
    replaced_id: int | None = None


class PrinterConsumableTarget(_FromAttributes):
    id: int
    name: str
    kind: Literal["printer", "virtual_printer"]
    model: str | None
    loaded_filaments: list[dict]
    # Shared Bambuddy-side state used by every plate-clear confirmation entry
    # point (printer page, production order and QR scanner).
    awaiting_plate_clear: bool = False


class ConsumableBatchCreate(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    material_type_id: int
    quantity: int = Field(ge=1, le=1000)
    initial_weight_g: float | None = Field(default=None, gt=0)
    unit_price: float | None = Field(default=None, ge=0)
    # Kept for clients from the earlier inventory-only API.
    remaining_weight_g: float | None = Field(default=None, gt=0)


class ConsumableLibraryScan(BaseModel):
    operation_id: str = Field(min_length=1, max_length=100)
    unit_code: str = Field(min_length=1, max_length=100)
    action: Literal["receive", "deplete", "scrap"]
    remaining_weight_g: float | None = Field(default=None, ge=0)
    storage_location: str | None = Field(default=None, max_length=255)


class ConsumableUnitResponse(_FromAttributes):
    id: int
    material_type_id: int
    material_type_code: str
    material: str
    brand: str | None
    color_name: str | None
    color_hex: str | None
    unit_code: str
    status: str
    label_batch_id: str
    initial_weight_g: float | None = None
    unit_price: float | None = None
    remaining_weight_g: float | None
    storage_location: str | None
    generated_at: datetime
    received_at: datetime | None
    depleted_at: datetime | None
    scrapped_at: datetime | None
    replayed: bool = False


class ConsumableBatchResponse(BaseModel):
    batch_id: str
    items: list[ConsumableUnitResponse]


class ConsumableLibrarySummary(BaseModel):
    generated: int
    in_stock: int
    bound: int
    depleted: int
    scrapped: int
    total: int


class ConsumableInventoryGroup(BaseModel):
    """Server-calculated inventory totals for one brand/material/colour."""

    brand: str | None
    material: str
    subtype: str | None
    color_name: str | None
    color_hex: str | None
    generated: int
    in_stock: int
    bound: int
    depleted: int
    scrapped: int
    total: int


class ConsumableConsumptionGroup(BaseModel):
    brand: str | None
    material: str
    subtype: str | None
    color_name: str | None
    color_hex: str | None
    consumed_g: float
    cost: float
    event_count: int


class ConsumableUsageEventResponse(BaseModel):
    id: int
    consumable_unit_id: int | None
    unit_code: str | None
    material_type_code: str | None
    brand: str | None
    material: str | None
    subtype: str | None
    color_name: str | None
    color_hex: str | None
    queue_item_id: int | None
    plate_job_id: int | None
    printer_id: int | None
    consumed_g: float
    cost: float
    source: str
    recorded_at: datetime


class ConsumableConsumptionSummary(BaseModel):
    period: str
    start_date: datetime
    end_date: datetime
    consumed_g: float
    cost: float
    event_count: int
    groups: list[ConsumableConsumptionGroup]
    events: list[ConsumableUsageEventResponse]


PRINTER_STATUS_STATES = Literal["unknown", "idle", "printing", "paused", "finished", "offline", "error", "maintenance"]


class PrinterStatusHeartbeat(BaseModel):
    """Normalized telemetry accepted by the Stage 13 status adapter seam."""

    operation_id: str = Field(min_length=1, max_length=100)
    target_type: Literal["printer", "virtual_printer"]
    target_id: int = Field(gt=0)
    state: PRINTER_STATUS_STATES = "idle"
    source: Literal["stage13_simulation", "adapter"] = "stage13_simulation"
    current_job_id: int | None = Field(default=None, gt=0)
    current_job_state: str | None = Field(default=None, max_length=30)
    fault_code: str | None = Field(default=None, max_length=100)
    fault_message: str | None = Field(default=None, max_length=500)
    loaded_filaments: list[dict] = Field(default_factory=list)
    telemetry: dict = Field(default_factory=dict)

    _strip_operation = field_validator("operation_id")(_strip_required)


class ProductionPrinterStatusResponse(_FromAttributes):
    id: int | None = None
    target_key: str
    target_type: Literal["printer", "virtual_printer"]
    target_id: int
    name: str
    model: str | None = None
    state: str
    effective_state: str
    available_for_allocation: bool
    stale: bool
    source: str
    last_heartbeat_at: datetime | None = None
    observed_at: datetime | None = None
    seconds_since_heartbeat: int | None = None
    current_job_id: int | None = None
    current_job_state: str | None = None
    fault_code: str | None = None
    fault_message: str | None = None
    loaded_filaments: list[dict] = Field(default_factory=list)
    telemetry: dict = Field(default_factory=dict)
    heartbeat_timeout_seconds: int
    transport_enabled: bool = False
    replayed: bool = False


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
    build_width_mm: float = Field(default=0, ge=0)
    build_depth_mm: float = Field(default=0, ge=0)
    build_height_mm: float = Field(default=0, ge=0)

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
    build_width_mm: float
    build_depth_mm: float
    build_height_mm: float
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
    priority: int = Field(default=0, ge=0, le=4)
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
    deleted_at: datetime | None = None
    completed_at: datetime | None = None
    priority_label: str = "极低"
    overdue: bool = False
    delivery_status: str = "on_track"
    completed_quantity: int = 0
    printing_quantity: int = 0
    assigned_quantity: int = 0
    quality_quantity: int = 0
    cleanup_quantity: int = 0
    scrap_quantity: int = 0
    remaining_quantity: int = 0
    assigned_printer_names: list[str] = []
    compatible_printer_count: int = 0
    matching_consumable_printer_count: int = 0


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
    assigned_printer_id: int | None = None
    assigned_printer_name: str | None = None
    assigned_printer_model: str | None = None
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
    slice_time_review_status: str = "not_required"
    slice_time_limit_seconds: int = 108000
    max_units_per_plate: int | None = None
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
    priority: int | None = Field(default=None, ge=0, le=4)
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


class PlateJobSliceTimeReview(BaseModel):
    """Operator decision for a plate whose estimate exceeds 30 hours."""

    operation_id: str = Field(min_length=1, max_length=100)
    approve: bool

    _strip_operation = field_validator("operation_id")(_strip_required)


class ProductionOrderQuantityAppend(BaseModel):
    """Append a quantity to the selected active batch, without creating a new order."""

    operation_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0)

    _strip_operation = field_validator("operation_id")(_strip_required)


class ProductionOrderReplan(BaseModel):
    """Change the deadline/priority while preserving a planning audit entry."""

    operation_id: str = Field(min_length=1, max_length=100)
    due_at: datetime | None = None
    priority: int | None = Field(default=None, ge=0, le=4)

    _strip_operation = field_validator("operation_id")(_strip_required)


class ProductionOrderAvailabilityResponse(BaseModel):
    product_id: int
    product_file_id: int
    compatible_printer_count: int = 0
    matching_consumable_printer_count: int = 0
    available_printer_names: list[str] = []
    required_materials: list[str] = []
    required_colors: list[str] = []


class RealPrinterDispatchRequest(BaseModel):
    """Explicit Stage 14 confirmation for one real-printer dispatch."""

    operation_id: str = Field(min_length=1, max_length=100)
    printer_id: int = Field(gt=0)
    plate_job_id: int | None = Field(default=None, gt=0)
    confirm: bool = False

    _strip_operation = field_validator("operation_id")(_strip_required)


class RealPrinterDispatchResponse(BaseModel):
    operation_id: str
    artifact_id: int
    plate_job_id: int | None
    queue_item_id: int
    printer_id: int
    printer_name: str
    printer_model: str | None
    queue_status: str
    manual_confirmation: bool
    transport: str
    replayed: bool = False


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


class ProductWorkbenchSummaryResponse(BaseModel):
    """Current production progress aggregated by product, not by batch."""

    product_id: int
    product_name: str | None = None
    product_sku: str | None = None
    total_quantity: int
    completed_quantity: int
    remaining_quantity: int
    printing_quantity: int
    assigned_quantity: int
    quality_quantity: int
    cleanup_quantity: int
    scrap_quantity: int
    order_count: int
    overdue_order_count: int
    overdue: bool
    highest_priority: int
    priority_label: str
    due_at: datetime | None = None
    assigned_printer_names: list[str] = Field(default_factory=list)


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
