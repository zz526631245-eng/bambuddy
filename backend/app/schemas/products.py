"""Pydantic schemas for production products."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProductCreate(BaseModel):
    sku: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    size_class: Literal["standard", "large"] = "standard"
    production_mode: Literal["single_plate", "multi_plate"] = "single_plate"
    source_plate_count: int = Field(default=1, ge=1)
    is_active: bool = True

    @field_validator("sku", "name")
    @classmethod
    def strip_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    size_class: Literal["standard", "large"] | None = None
    production_mode: Literal["single_plate", "multi_plate"] | None = None
    source_plate_count: int | None = Field(default=None, ge=1)
    is_active: bool | None = None

    @field_validator("sku", "name")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


class ProductImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    original_name: str
    content_type: str
    file_size: int
    is_primary: bool
    sort_order: int
    created_at: datetime


class ProductFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int
    library_file_id: int
    name: str
    product_color: str | None = None
    strategy: str
    component_ids: list[int]
    units_per_plate: float
    source_plate_count: int = 1
    source_set_id: str | None = None
    source_plate_index: int = 0
    compatible_printer_models: list[str]
    filament_requirements: list[dict] = []
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ProductComponentCreate(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    unit: str = Field(default="pcs", min_length=1, max_length=30)
    is_active: bool = True


class ProductComponentResponse(ProductComponentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    updated_at: datetime


class BOMItemCreate(BaseModel):
    component_id: int
    quantity: float = Field(gt=0)
    notes: str | None = None


class BOMItemResponse(BOMItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    product_id: int


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    description: str | None
    size_class: Literal["standard", "large"]
    production_mode: Literal["single_plate", "multi_plate"]
    source_plate_count: int
    is_active: bool
    images: list[ProductImageResponse] = []
    product_files: list[ProductFileResponse] = []
    created_at: datetime
    updated_at: datetime


class ProductDetailResponse(ProductResponse):
    images: list[ProductImageResponse] = []
    bom_items: list[BOMItemResponse] = []
    product_files: list[ProductFileResponse] = []
