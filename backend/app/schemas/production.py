"""Stage 6 create/read schemas for production-domain skeleton APIs."""

from datetime import datetime

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
    is_active: bool = True

    _strip_fields = field_validator("code", "name", "printer_model")(_strip_required)


class PrinterProfileResponse(_FromAttributes):
    id: int
    code: str
    name: str
    printer_model: str
    nozzle_diameter: float
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductionRecipeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    product_id: int
    material_type_id: int | None = None
    printer_profile_id: int | None = None
    library_file_id: int | None = None
    slicer_pipeline_id: int | None = None
    version: int = Field(default=1, ge=1)
    is_active: bool = True

    _strip_fields = field_validator("code", "name")(_strip_required)


class ProductionRecipeResponse(_FromAttributes):
    id: int
    code: str
    name: str
    product_id: int
    material_type_id: int | None
    printer_profile_id: int | None
    library_file_id: int | None
    slicer_pipeline_id: int | None
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductionOrderCreate(BaseModel):
    order_number: str = Field(min_length=1, max_length=100)
    product_id: int
    quantity: int = Field(ge=0)
    priority: int = Field(default=0, ge=0)
    due_at: datetime | None = None
    notes: str | None = None

    _strip_order_number = field_validator("order_number")(_strip_required)


class ProductionOrderResponse(_FromAttributes):
    id: int
    order_number: str
    product_id: int
    quantity: int
    priority: int
    status: str
    due_at: datetime | None
    notes: str | None
    created_by_id: int | None
    created_at: datetime
    updated_at: datetime


class ProductionRequirementResponse(_FromAttributes):
    id: int
    order_id: int
    recipe_id: int
    required_quantity: int
    reserved_quantity: int
    good_quantity: int
    scrap_quantity: int
    status: str
    created_at: datetime
    updated_at: datetime


class PlateJobResponse(_FromAttributes):
    id: int
    requirement_id: int
    printer_profile_id: int | None
    queue_item_id: int | None
    planned_quantity: int
    status: str
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
