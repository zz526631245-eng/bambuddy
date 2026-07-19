"""Stage 7 product master-data API. No queue or printer imports are allowed here."""

import io
import json
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.config import settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.material_type import MaterialType
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.product_master import ProductComponent, ProductImage, ProductionBOMItem
from backend.app.models.production import ProductionOrder
from backend.app.models.production_recipe import ProductionRecipe
from backend.app.models.user import User
from backend.app.schemas.products import (
    BOMItemCreate,
    BOMItemResponse,
    ProductComponentCreate,
    ProductComponentResponse,
    ProductCreate,
    ProductDetailResponse,
    ProductImageResponse,
    ProductResponse,
    ProductUpdate,
)
from backend.app.utils.safe_path import safe_join_under

router = APIRouter(prefix="/products", tags=["production-products"])
IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


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
                selectinload(Product.images), selectinload(Product.bom_items).selectinload(ProductionBOMItem.component)
            )
        )
        product = row.scalar_one_or_none()
    else:
        product = await db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Product not found")
    return product


@router.get("", response_model=list[ProductResponse])
@router.get("/", response_model=list[ProductResponse])
async def list_products(
    db: AsyncSession = Depends(get_db), _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_READ)
):
    return list((await db.execute(select(Product).order_by(Product.sku))).scalars().all())


@router.post("", response_model=ProductResponse, status_code=201)
@router.post("/", response_model=ProductResponse, status_code=201, include_in_schema=False)
async def create_product(
    payload: ProductCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTS_WRITE),
):
    product = Product(**payload.model_dump())
    product.sku = product.sku.upper()
    db.add(product)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Product SKU already exists")
    await db.refresh(product)
    return product


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
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(product, key, value.upper() if key == "sku" and value else value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Product SKU already exists")
    await db.refresh(product)
    return product


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
    return product
