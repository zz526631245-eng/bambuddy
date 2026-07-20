"""Stage 7 product master-data API. No queue or printer imports are allowed here."""

import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.api.routes.library import save_3mf_bytes_to_library
from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.material_type import MaterialType
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.product_file import ProductFile
from backend.app.models.product_master import ProductComponent, ProductImage, ProductionBOMItem
from backend.app.models.production import ProductionOrder, ProductionRequirement
from backend.app.models.production_recipe import ProductionRecipe
from backend.app.models.user import User
from backend.app.schemas.products import (
    BOMItemCreate,
    BOMItemResponse,
    ProductComponentCreate,
    ProductComponentResponse,
    ProductCreate,
    ProductDetailResponse,
    ProductFileResponse,
    ProductImageResponse,
    ProductResponse,
    ProductUpdate,
)
from backend.app.utils.safe_path import safe_join_under

router = APIRouter(prefix="/products", tags=["production-products"])
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _source_plate_count(content: bytes) -> int:
    """Read the number of source plates without changing the uploaded 3MF."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            count = max(
                [int(match.group(1)) for name in archive.namelist() if (match := re.fullmatch(r"Metadata/plate_(\d+)\.png", name))]
                or [1]
            )
            config_name = "Metadata/slice_info.config"
            if config_name in archive.namelist():
                root = ElementTree.fromstring(archive.read(config_name))
                count = max(count, sum(1 for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "plate"))
            return max(1, count)
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError):
        return 1


def _image_root() -> Path:
    root = settings.base_dir / "product_images"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validate_image_content(content: bytes, expected_type: str) -> None:
    expected_formats = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}
    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            if image.format != expected_formats[expected_type]:
                raise HTTPException(415, "Image content does not match its declared type")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(415, "Invalid or corrupt image")


async def _product_or_404(db: AsyncSession, product_id: int, detailed: bool = False) -> Product:
    if detailed:
        row = await db.execute(
            select(Product)
            .where(Product.id == product_id)
            .options(
                selectinload(Product.images),
                selectinload(Product.bom_items).selectinload(ProductionBOMItem.component),
                selectinload(Product.product_files),
            )
        )
        product = row.scalar_one_or_none()
    else:
        row = await db.execute(select(Product).where(Product.id == product_id).options(selectinload(Product.product_files)))
        product = row.scalar_one_or_none()
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


@router.get("", response_model=list[ProductResponse])
@router.get("/", response_model=list[ProductResponse])
async def list_products(
    db: AsyncSession = Depends(get_db), _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_READ)
):
    return list(
        (
            await db.execute(
                select(Product)
                .options(selectinload(Product.images), selectinload(Product.product_files))
                .order_by(Product.created_at.desc(), Product.id.desc())
            )
        )
        .scalars()
        .all()
    )


@router.post("", response_model=ProductResponse, status_code=201)
@router.post("/", response_model=ProductResponse, status_code=201, include_in_schema=False)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    values = payload.model_dump()
    if values["production_mode"] == "multi_plate" and values["source_plate_count"] < 2:
        raise HTTPException(422, "多盘产品至少需要 2 个源盘")
    if values["production_mode"] == "single_plate":
        values["source_plate_count"] = 1
    if not values.get("sku"):
        values["sku"] = await _next_product_sku(db)
    product = Product(**values)
    product.sku = product.sku.upper()
    db.add(product)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Product SKU already exists")
    await db.refresh(product)
    return await _product_or_404(db, product.id, True)


async def _next_product_sku(db: AsyncSession) -> str:
    """Generate a stable human-readable SKU without requiring user input."""
    rows = (await db.execute(select(Product.sku).where(Product.sku.like("PRD-%")))).scalars().all()
    used = {str(value).upper() for value in rows}
    number = 1
    while f"PRD-{number:04d}" in used:
        number += 1
    return f"PRD-{number:04d}"


@router.post("/with-image", response_model=ProductDetailResponse, status_code=201)
async def create_product_with_image(
    name: str = Form(...),
    description: str | None = Form(None),
    size_class: str = Form("standard"),
    production_mode: str = Form("single_plate"),
    source_plate_count: int = Form(1),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    """Create a product and its first image in one user-facing operation."""
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(422, "Product name is required")
    if size_class not in {"standard", "large"}:
        raise HTTPException(422, "size_class must be standard or large")
    if production_mode not in {"single_plate", "multi_plate"}:
        raise HTTPException(422, "production_mode must be single_plate or multi_plate")
    if production_mode == "multi_plate" and source_plate_count < 2:
        raise HTTPException(422, "多盘产品至少需要 2 个源盘")
    if production_mode == "single_plate":
        source_plate_count = 1
    content_type = (file.content_type or "").lower()
    if content_type not in IMAGE_TYPES:
        raise HTTPException(415, "Only JPEG, PNG and WebP images are allowed")
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds 10 MB")
    _validate_image_content(content, content_type)
    product = Product(
        sku=(await _next_product_sku(db)),
        name=clean_name,
        description=description.strip() if description else None,
        size_class=size_class,
        production_mode=production_mode,
        source_plate_count=source_plate_count,
    )
    db.add(product)
    await db.flush()
    filename = f"{uuid.uuid4().hex}{IMAGE_TYPES[content_type]}"
    folder = safe_join_under(_image_root(), str(product.id))
    folder.mkdir(parents=True, exist_ok=True)
    path = safe_join_under(folder, filename)
    path.write_bytes(content)
    db.add(ProductImage(product_id=product.id, filename=filename, original_name=Path(file.filename or "image").name, content_type=content_type, file_size=len(content), is_primary=True))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        path.unlink(missing_ok=True)
        raise HTTPException(409, "Product code generation conflict; please retry")
    return await _product_or_404(db, product.id, True)


@router.get("/components", response_model=list[ProductComponentResponse])
async def list_components(
    db: AsyncSession = Depends(get_db), _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_READ)
):
    return list((await db.execute(select(ProductComponent).order_by(ProductComponent.code))).scalars().all())


@router.post("/components", response_model=ProductComponentResponse, status_code=201)
async def create_component(
    payload: ProductComponentCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    values = payload.model_dump()
    values["code"] = values["code"].strip().upper()
    item = ProductComponent(**values)
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Component code already exists")
    await db.refresh(item)
    return item


@router.delete("/components/{component_id}", status_code=204)
async def delete_component(
    component_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    component = await db.get(ProductComponent, component_id)
    if not component:
        raise HTTPException(404, "Component not found")
    if (
        await db.execute(select(ProductionBOMItem.id).where(ProductionBOMItem.component_id == component_id).limit(1))
    ).scalar_one_or_none():
        raise HTTPException(409, "Component is referenced by a production BOM")
    await db.delete(component)
    await db.commit()


@router.get("/{product_id}", response_model=ProductDetailResponse)
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_READ),
):
    return await _product_or_404(db, product_id, True)


@router.put("/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    product = await _product_or_404(db, product_id)
    values = payload.model_dump(exclude_unset=True)
    next_mode = values.get("production_mode", product.production_mode)
    next_count = values.get("source_plate_count", product.source_plate_count)
    if next_mode == "multi_plate" and next_count < 2:
        raise HTTPException(422, "多盘产品至少需要 2 个源盘")
    if next_mode == "single_plate":
        values["source_plate_count"] = 1
    structure_changed = next_mode != product.production_mode or next_count != product.source_plate_count
    for key, value in values.items():
        setattr(product, key, value.upper() if key == "sku" and value else value)
    if structure_changed:
        await db.execute(
            update(ProductionOrder)
            .where(ProductionOrder.product_id == product_id, ProductionOrder.recalculation_required.is_(False))
            .values(recalculation_required=True)
        )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Product SKU already exists")
    await db.refresh(product)
    return await _product_or_404(db, product.id, True)


@router.delete("/{product_id}", status_code=204)
async def delete_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    product = await _product_or_404(db, product_id, True)
    recipe_ref = (
        await db.execute(select(ProductionRecipe.id).where(ProductionRecipe.product_id == product_id).limit(1))
    ).scalar_one_or_none()
    order_ref = (
        await db.execute(select(ProductionOrder.id).where(ProductionOrder.product_id == product_id).limit(1))
    ).scalar_one_or_none()
    if recipe_ref or order_ref:
        raise HTTPException(409, "Product is referenced by recipes or production orders")
    paths = [safe_join_under(_image_root(), str(product_id), image.filename) for image in product.images]
    await db.delete(product)
    await db.commit()
    for path in paths:
        path.unlink(missing_ok=True)


@router.post("/{product_id}/images", response_model=ProductImageResponse, status_code=201)
async def upload_image(
    product_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    await _product_or_404(db, product_id)
    content_type = (file.content_type or "").lower()
    if content_type not in IMAGE_TYPES:
        raise HTTPException(415, "Only JPEG, PNG and WebP images are allowed")
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds 10 MB")
    _validate_image_content(content, content_type)
    filename = f"{uuid.uuid4().hex}{IMAGE_TYPES[content_type]}"
    folder = safe_join_under(_image_root(), str(product_id))
    folder.mkdir(parents=True, exist_ok=True)
    path = safe_join_under(folder, filename)
    path.write_bytes(content)
    image = ProductImage(
        product_id=product_id,
        filename=filename,
        original_name=Path(file.filename or "image").name,
        content_type=content_type,
        file_size=len(content),
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    return image


@router.post("/{product_id}/files", response_model=ProductFileResponse, status_code=201)
async def upload_product_file(
    product_id: int,
    file: UploadFile = File(...),
    strategy: str = Form("fixed_plate"),
    units_per_plate: float = Form(1),
    component_ids: str = Form("[]"),
    compatible_printer_models: str = Form("[]"),
    filament_requirements: str = Form("[]"),
    product_color: str = Form(""),
    source_set_id: str | None = Form(None),
    source_plate_index: int = Form(0),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    """Upload a source 3MF owned by a product and invalidate pending work."""
    product = await _product_or_404(db, product_id)
    if strategy not in {"fixed_plate", "auto_pack", "multi_plate_fixed"}:
        raise HTTPException(422, "strategy must be fixed_plate, auto_pack or multi_plate_fixed")
    if product.production_mode == "multi_plate":
        if product.source_plate_count < 2:
            raise HTTPException(422, "多盘产品的源盘数量无效")
        if source_plate_index < 0 or source_plate_index >= product.source_plate_count:
            raise HTTPException(422, "源盘编号超出产品设置的源盘数量")
        source_set_id = (source_set_id or "").strip() or None
        if not source_set_id:
            raise HTTPException(422, "多盘产品上传必须提供同一组源文件编号")
        strategy = "fixed_plate"
        units_per_plate = 1
    elif strategy == "multi_plate_fixed":
        # Keep accepting old API clients during migration. New UI uploads use
        # the product-level multi_plate mode and separate source files.
        pass
    if units_per_plate <= 0:
        raise HTTPException(422, "units_per_plate must be positive")
    if not (file.filename or "").lower().endswith(".3mf"):
        raise HTTPException(415, "Product source files must be .3mf")
    try:
        parsed_components = json.loads(component_ids)
        parsed_models = json.loads(compatible_printer_models)
        parsed_filaments = json.loads(filament_requirements)
        if not isinstance(parsed_components, list) or not isinstance(parsed_models, list) or not isinstance(parsed_filaments, list):
            raise ValueError
    except (TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(422, "component_ids, compatible_printer_models and filament_requirements must be JSON arrays")
    normalized_filaments = []
    normalized_product_color = product_color.strip().upper() or None
    for index, requirement in enumerate(parsed_filaments):
        if not isinstance(requirement, dict):
            raise HTTPException(422, "filament_requirements must contain objects")
        material = str(requirement.get("material") or "").strip().upper()
        color = str(requirement.get("color") or requirement.get("color_hex") or "").strip().upper()
        if not material or not color:
            raise HTTPException(422, "Each filament requirement needs material and color")
        slot = requirement.get("slot", index)
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            raise HTTPException(422, "Filament slot must be an integer")
        if slot < 0:
            raise HTTPException(422, "Filament slot must not be negative")
        normalized_filaments.append({"slot": slot, "material": material, "color": color})
    content = await file.read()
    if not content:
        raise HTTPException(422, "Product source file is empty")
    source_plate_count = product.source_plate_count if product.production_mode == "multi_plate" else _source_plate_count(content)
    if strategy == "multi_plate_fixed":
        if source_plate_count < 2:
            raise HTTPException(422, "多盘源文件至少需要 2 个源盘")
        units_per_plate = 1
    if product.production_mode == "multi_plate":
        source_plate_count = product.source_plate_count
    library_file, _ = await save_3mf_bytes_to_library(
        db, file_bytes=content, filename=Path(file.filename or "source.3mf").name, source_type="product_source"
    )
    # Reuse the metadata parsed by Bambuddy's existing 3MF library pipeline
    # when the caller did not explicitly override the material/colour slots.
    if not normalized_filaments:
        metadata = library_file.file_metadata or {}
        raw_types = metadata.get("filament_type") or metadata.get("filament_types") or []
        raw_colors = metadata.get("filament_color") or metadata.get("filament_colour") or []
        if isinstance(raw_types, str):
            raw_types = [raw_types]
        if isinstance(raw_colors, str):
            raw_colors = [raw_colors]
        for index, raw_material in enumerate(raw_types):
            material = str(raw_material or "").strip().upper()
            color = str(raw_colors[index] if index < len(raw_colors) else "").strip().upper()
            if material and color:
                normalized_filaments.append({"slot": index, "material": material, "color": color})
    same_variant = [
        item
        for item in product.product_files
        if (item.product_color or None) == normalized_product_color
    ]
    grouped_variant = [item for item in same_variant if item.source_set_id == source_set_id] if source_set_id else []
    latest = max((f.version for f in same_variant), default=0)
    version = max((f.version for f in grouped_variant), default=latest + 1)
    # Uploading the same product colour is a replacement, not a second active
    # choice. Keep the old row for order/history snapshots but hide it from
    # new order selection and prevent the allocator from using it.
    # Older rows used an empty string for the unlabelled variant. Treat it the
    # same as NULL so replacing an unlabelled file also deactivates those rows.
    variant_filter = (ProductFile.product_color.is_(None) | (ProductFile.product_color == "")) if normalized_product_color is None else ProductFile.product_color == normalized_product_color
    if not grouped_variant:
        await db.execute(
            update(ProductFile)
            .where(ProductFile.product_id == product_id, ProductFile.is_active.is_(True), variant_filter)
            .values(is_active=False)
        )
    item = ProductFile(
        product_id=product_id,
        library_file_id=library_file.id,
        name=Path(file.filename or "source.3mf").name,
        product_color=normalized_product_color,
        strategy=strategy,
        component_ids=[int(x) for x in parsed_components],
        units_per_plate=units_per_plate,
        source_plate_count=source_plate_count,
        source_set_id=source_set_id,
        source_plate_index=source_plate_index,
        compatible_printer_models=[str(x) for x in parsed_models],
        filament_requirements=normalized_filaments,
        version=version,
    )
    db.add(item)
    await db.flush()
    await db.execute(
        update(ProductionOrder)
        .where(ProductionOrder.product_id == product_id, ProductionOrder.recalculation_required.is_(False))
        .values(recalculation_required=True)
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/{product_id}/files/{file_id}", status_code=204)
async def delete_product_file(
    product_id: int,
    file_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    """Physically delete a stopped source file while retaining order snapshots.

    Active files must be stopped first. If an old order references the file,
    its immutable snapshot remains on the order and the live requirement
    foreign key is cleared before deleting the product-file row.
    """

    product_file = await db.get(ProductFile, file_id)
    if product_file is None or product_file.product_id != product_id:
        raise HTTPException(404, "Product source file not found")
    if product_file.is_active:
        raise HTTPException(409, "请先停用产品源文件，再彻底删除")
    referenced = (
        await db.execute(
            select(ProductionRequirement.id)
            .where(ProductionRequirement.product_file_id == file_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if referenced is not None:
        await db.execute(
            update(ProductionRequirement)
            .where(ProductionRequirement.product_file_id == file_id)
            .values(product_file_id=None)
        )
    if referenced is not None and product_file.is_active:
        raise HTTPException(409, "该文件已被历史订单引用，请使用停用以保留历史快照")
    await db.delete(product_file)
    await db.commit()


@router.post("/{product_id}/files/{file_id}/deactivate", status_code=204)
async def deactivate_product_file(
    product_id: int,
    file_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    """Deactivate a file while retaining it for history and inspection."""

    product_file = await db.get(ProductFile, file_id)
    if product_file is None or product_file.product_id != product_id:
        raise HTTPException(404, "Product source file not found")
    if product_file.is_active:
        product_file.is_active = False
        await db.execute(
            update(ProductionOrder)
            .where(ProductionOrder.product_id == product_id, ProductionOrder.recalculation_required.is_(False))
            .values(recalculation_required=True)
        )
    await db.commit()


@router.get("/{product_id}/images/{image_id}/file")
async def get_image(
    product_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_READ),
):
    image = await db.get(ProductImage, image_id)
    if not image or image.product_id != product_id:
        raise HTTPException(404, "Product image not found")
    path = safe_join_under(_image_root(), str(product_id), image.filename)
    if not path.is_file():
        raise HTTPException(404, "Product image file not found")
    return FileResponse(path, media_type=image.content_type, filename=image.original_name)


@router.delete("/{product_id}/images/{image_id}", status_code=204)
async def delete_image(
    product_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    image = await db.get(ProductImage, image_id)
    if not image or image.product_id != product_id:
        raise HTTPException(404, "Product image not found")
    path = safe_join_under(_image_root(), str(product_id), image.filename)
    await db.delete(image)
    await db.commit()
    path.unlink(missing_ok=True)


@router.post("/{product_id}/bom", response_model=BOMItemResponse, status_code=201)
async def add_bom_item(
    product_id: int,
    payload: BOMItemCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    await _product_or_404(db, product_id)
    if not await db.get(ProductComponent, payload.component_id):
        raise HTTPException(404, "Component not found")
    item = ProductionBOMItem(product_id=product_id, **payload.model_dump())
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Component already exists in this BOM")
    await db.refresh(item)
    return item


@router.delete("/{product_id}/bom/{item_id}", status_code=204)
async def delete_bom_item(
    product_id: int,
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    item = await db.get(ProductionBOMItem, item_id)
    if not item or item.product_id != product_id:
        raise HTTPException(404, "BOM item not found")
    await db.delete(item)
    await db.commit()


@router.get("/{product_id}/export")
async def export_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_READ),
):
    product = await _product_or_404(db, product_id, True)
    recipes = list(
        (
            await db.execute(
                select(ProductionRecipe)
                .where(ProductionRecipe.product_id == product_id)
                .options(
                    selectinload(ProductionRecipe.compatible_profiles),
                    selectinload(ProductionRecipe.material_type),
                    selectinload(ProductionRecipe.printer_profile),
                )
            )
        )
        .scalars()
        .all()
    )
    component_codes = {item.component_id: item.component.code for item in product.bom_items}
    manifest = {
        "format": "bambuddy-product-v1",
        "product": {
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "size_class": product.size_class,
            "production_mode": product.production_mode,
            "source_plate_count": product.source_plate_count,
            "is_active": product.is_active,
        },
        "bom": [
            {
                "component_code": i.component.code,
                "component_name": i.component.name,
                "unit": i.component.unit,
                "quantity": i.quantity,
                "notes": i.notes,
            }
            for i in product.bom_items
        ],
        "images": [
            {"filename": i.filename, "original_name": i.original_name, "content_type": i.content_type}
            for i in product.images
        ],
        "recipes": [
            {
                "code": r.code,
                "name": r.name,
                "version": r.version,
                "component_code": component_codes.get(r.component_id),
                "material_code": r.material_type.code if r.material_type else None,
                "printer_profile_code": r.printer_profile.code if r.printer_profile else None,
                "library_file_id": r.library_file_id,
                "slicer_pipeline_id": r.slicer_pipeline_id,
                "slicer_preset": r.slicer_preset,
                "compatible_profile_codes": [p.code for p in r.compatible_profiles],
                "is_active": r.is_active,
            }
            for r in recipes
        ],
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for image in product.images:
            path = safe_join_under(_image_root(), str(product_id), image.filename)
            if path.is_file():
                archive.write(path, f"images/{image.filename}")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{product.sku}.bambuddy-product.zip"'},
    )


@router.post("/import/archive", response_model=ProductResponse, status_code=201)
async def import_product(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    raw = await file.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "Import archive exceeds 25 MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
        manifest = json.loads(archive.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise HTTPException(400, "Invalid Bambuddy product archive")
    if manifest.get("format") != "bambuddy-product-v1":
        raise HTTPException(400, "Unsupported product archive format")
    data = ProductCreate(**manifest["product"])
    product = Product(**data.model_dump())
    db.add(product)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Product SKU already exists")
    components_by_code: dict[str, ProductComponent] = {}
    for row in manifest.get("bom", []):
        code = str(row["component_code"]).strip().upper()
        component = (
            await db.execute(select(ProductComponent).where(ProductComponent.code == code))
        ).scalar_one_or_none()
        if not component:
            component = ProductComponent(code=code, name=row["component_name"], unit=row.get("unit", "pcs"))
            db.add(component)
            await db.flush()
        components_by_code[code] = component
        db.add(
            ProductionBOMItem(
                product_id=product.id, component_id=component.id, quantity=row["quantity"], notes=row.get("notes")
            )
        )
    folder = safe_join_under(_image_root(), str(product.id))
    folder.mkdir(parents=True, exist_ok=True)
    for row in manifest.get("images", []):
        source_name = Path(str(row["filename"])).name
        member = f"images/{source_name}"
        content_type = str(row.get("content_type", "")).lower()
        if content_type not in IMAGE_TYPES:
            raise HTTPException(400, "Product archive contains an unsupported image type")
        try:
            content = archive.read(member)
        except KeyError:
            raise HTTPException(400, "Product archive is missing an image")
        if len(content) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Product archive contains an image over 10 MB")
        _validate_image_content(content, content_type)
        filename = f"{uuid.uuid4().hex}{IMAGE_TYPES[content_type]}"
        safe_join_under(folder, filename).write_bytes(content)
        db.add(
            ProductImage(
                product_id=product.id,
                filename=filename,
                original_name=Path(str(row["original_name"])).name,
                content_type=content_type,
                file_size=len(content),
            )
        )
    for row in manifest.get("recipes", []):
        component_code = str(row.get("component_code") or "").strip().upper()
        component = components_by_code.get(component_code)
        material = (
            (
                await db.execute(select(MaterialType).where(MaterialType.code == row.get("material_code")))
            ).scalar_one_or_none()
            if row.get("material_code")
            else None
        )
        profile = (
            (
                await db.execute(select(PrinterProfile).where(PrinterProfile.code == row.get("printer_profile_code")))
            ).scalar_one_or_none()
            if row.get("printer_profile_code")
            else None
        )
        recipe = ProductionRecipe(
            code=row["code"],
            name=row["name"],
            product_id=product.id,
            component_id=component.id if component else None,
            material_type_id=material.id if material else None,
            printer_profile_id=profile.id if profile else None,
            library_file_id=None,
            slicer_pipeline_id=None,
            slicer_preset=row.get("slicer_preset"),
            version=row.get("version", 1),
            is_active=row.get("is_active", True),
        )
        for code in row.get("compatible_profile_codes", []):
            compatible = (
                await db.execute(select(PrinterProfile).where(PrinterProfile.code == code))
            ).scalar_one_or_none()
            if compatible:
                recipe.compatible_profiles.append(compatible)
        db.add(recipe)
    await db.commit()
    await db.refresh(product)
    return await _product_or_404(db, product.id, True)
