"""Stage 6 create/read-only production-domain API skeleton.

No endpoint in this module imports the scheduler, creates queue items, or
communicates with a printer.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.library import LibraryFile
from backend.app.models.material_type import MaterialType
from backend.app.models.operation_log import OperationLog
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.product_master import MaterialTypeSpoolMapping, ProductComponent, ProductionBOMItem
from backend.app.models.production import PlateJob, ProductionOrder, ProductionRequirement
from backend.app.models.production_recipe import ProductionRecipe, production_recipe_profiles
from backend.app.models.slicer_pipeline import SlicerPipeline
from backend.app.models.spool import Spool
from backend.app.models.user import User
from backend.app.schemas.production import (
    MaterialTypeCreate,
    MaterialTypeResponse,
    OperationLogResponse,
    PlateJobConfirmRequest,
    PlateJobConfirmResponse,
    PlateJobPreviewResponse,
    PlateJobResponse,
    PrinterProfileCreate,
    PrinterProfileResponse,
    ProductionOrderCreate,
    ProductionOrderDetail,
    ProductionOrderResponse,
    ProductionOrderStatusAction,
    ProductionOrderUpdate,
    ProductionRecipeCreate,
    ProductionRecipeResponse,
    ProductionRequirementResponse,
)
from backend.app.services.production_order_service import (
    ProductionOrderError,
    change_order_status,
    confirm_plate_jobs,
    create_order as create_production_order,
    order_detail,
    preview_plate_jobs,
    update_order as update_production_order,
)

router = APIRouter(prefix="/production", tags=["production"])


async def _commit_unique(db: AsyncSession, instance, conflict_detail: str):
    db.add(instance)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=conflict_detail)
    await db.refresh(instance)
    return instance


async def _require_row(db: AsyncSession, model, row_id: int | None, detail: str):
    if row_id is None:
        return None
    row = await db.get(model, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail=detail)
    return row


@router.get("/material-types", response_model=list[MaterialTypeResponse])
async def list_material_types(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.MATERIAL_TYPES_READ),
):
    return list((await db.execute(select(MaterialType).order_by(MaterialType.id))).scalars().all())


@router.post("/material-types", response_model=MaterialTypeResponse, status_code=status.HTTP_201_CREATED)
async def create_material_type(
    payload: MaterialTypeCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.MATERIAL_TYPES_WRITE),
):
    return await _commit_unique(db, MaterialType(**payload.model_dump()), "Material type code already exists")


@router.put("/material-types/{item_id}", response_model=MaterialTypeResponse)
async def update_material_type(
    item_id: int,
    payload: MaterialTypeCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.MATERIAL_TYPES_WRITE),
):
    item = await _require_row(db, MaterialType, item_id, "Material type not found")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Material type code already exists")
    await db.refresh(item)
    return item


@router.delete("/material-types/{item_id}", status_code=204)
async def delete_material_type(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.MATERIAL_TYPES_WRITE),
):
    item = await _require_row(db, MaterialType, item_id, "Material type not found")
    recipe_ref = (
        await db.execute(select(ProductionRecipe.id).where(ProductionRecipe.material_type_id == item_id).limit(1))
    ).scalar_one_or_none()
    spool_ref = (
        await db.execute(
            select(MaterialTypeSpoolMapping.spool_id)
            .where(MaterialTypeSpoolMapping.material_type_id == item_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if recipe_ref or spool_ref:
        raise HTTPException(409, "Material type is referenced by a recipe or spool")
    await db.delete(item)
    await db.commit()


@router.put("/material-types/{item_id}/spools/{spool_id}", status_code=204)
async def map_spool(
    item_id: int,
    spool_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.MATERIAL_TYPES_WRITE),
):
    await _require_row(db, MaterialType, item_id, "Material type not found")
    await _require_row(db, Spool, spool_id, "Spool not found")
    existing = await db.get(MaterialTypeSpoolMapping, (item_id, spool_id))
    if not existing:
        db.add(MaterialTypeSpoolMapping(material_type_id=item_id, spool_id=spool_id))
        await db.commit()


@router.delete("/material-types/{item_id}/spools/{spool_id}", status_code=204)
async def unmap_spool(
    item_id: int,
    spool_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.MATERIAL_TYPES_WRITE),
):
    await _require_row(db, Spool, spool_id, "Spool not found")
    mapping = await db.get(MaterialTypeSpoolMapping, (item_id, spool_id))
    if mapping:
        await db.delete(mapping)
        await db.commit()


@router.get("/printer-profiles", response_model=list[PrinterProfileResponse])
async def list_printer_profiles(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTER_PROFILES_READ),
):
    return list((await db.execute(select(PrinterProfile).order_by(PrinterProfile.id))).scalars().all())


@router.post("/printer-profiles", response_model=PrinterProfileResponse, status_code=status.HTTP_201_CREATED)
async def create_printer_profile(
    payload: PrinterProfileCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTER_PROFILES_WRITE),
):
    return await _commit_unique(db, PrinterProfile(**payload.model_dump()), "Printer profile code already exists")


@router.put("/printer-profiles/{item_id}", response_model=PrinterProfileResponse)
async def update_printer_profile(
    item_id: int,
    payload: PrinterProfileCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTER_PROFILES_WRITE),
):
    item = await _require_row(db, PrinterProfile, item_id, "Printer profile not found")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Printer profile code already exists")
    await db.refresh(item)
    return item


@router.delete("/printer-profiles/{item_id}", status_code=204)
async def delete_printer_profile(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRINTER_PROFILES_WRITE),
):
    item = await _require_row(db, PrinterProfile, item_id, "Printer profile not found")
    recipe_ref = (
        await db.execute(select(ProductionRecipe.id).where(ProductionRecipe.printer_profile_id == item_id).limit(1))
    ).scalar_one_or_none()
    job_ref = (
        await db.execute(select(PlateJob.id).where(PlateJob.printer_profile_id == item_id).limit(1))
    ).scalar_one_or_none()
    compatible_ref = (
        await db.execute(
            select(production_recipe_profiles.c.recipe_id)
            .where(production_recipe_profiles.c.printer_profile_id == item_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if recipe_ref or job_ref or compatible_ref:
        raise HTTPException(409, "Printer profile is referenced by a recipe or plate job")
    await db.delete(item)
    await db.commit()


@router.get("/recipes", response_model=list[ProductionRecipeResponse])
async def list_recipes(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.RECIPES_READ),
):
    return list(
        (
            await db.execute(
                select(ProductionRecipe)
                .options(selectinload(ProductionRecipe.compatible_profiles))
                .order_by(ProductionRecipe.id)
            )
        )
        .scalars()
        .all()
    )


@router.post("/recipes", response_model=ProductionRecipeResponse, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    payload: ProductionRecipeCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.RECIPES_WRITE),
):
    await _require_row(db, Product, payload.product_id, "Product not found")
    component = await _require_row(db, ProductComponent, payload.component_id, "Product component not found")
    if component and not (
        await db.execute(
            select(ProductComponent.id)
            .join(ProductionBOMItem, ProductionBOMItem.component_id == ProductComponent.id)
            .where(ProductComponent.id == component.id, ProductionBOMItem.product_id == payload.product_id)
        )
    ).scalar_one_or_none():
        raise HTTPException(422, "该零件不在这个产品的零件清单中")
    await _require_row(db, MaterialType, payload.material_type_id, "Material type not found")
    await _require_row(db, PrinterProfile, payload.printer_profile_id, "Printer profile not found")
    await _require_row(db, LibraryFile, payload.library_file_id, "Library file not found")
    await _require_row(db, SlicerPipeline, payload.slicer_pipeline_id, "Slicer pipeline not found")
    values = payload.model_dump(exclude={"compatible_profile_ids"})
    recipe = ProductionRecipe(**values)
    for profile_id in payload.compatible_profile_ids:
        recipe.compatible_profiles.append(
            await _require_row(db, PrinterProfile, profile_id, "Compatible printer profile not found")
        )
    recipe = await _commit_unique(db, recipe, "Recipe code and version already exist")
    return (
        await db.execute(
            select(ProductionRecipe)
            .where(ProductionRecipe.id == recipe.id)
            .options(selectinload(ProductionRecipe.compatible_profiles))
        )
    ).scalar_one()


@router.put("/recipes/{item_id}", response_model=ProductionRecipeResponse)
async def update_recipe(
    item_id: int,
    payload: ProductionRecipeCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.RECIPES_WRITE),
):
    recipe = (
        await db.execute(
            select(ProductionRecipe)
            .where(ProductionRecipe.id == item_id)
            .options(selectinload(ProductionRecipe.compatible_profiles))
        )
    ).scalar_one_or_none()
    if not recipe:
        raise HTTPException(404, "Recipe not found")
    await _require_row(db, Product, payload.product_id, "Product not found")
    component = await _require_row(db, ProductComponent, payload.component_id, "Product component not found")
    if component and not (
        await db.execute(
            select(ProductComponent.id)
            .join(ProductionBOMItem, ProductionBOMItem.component_id == ProductComponent.id)
            .where(ProductComponent.id == component.id, ProductionBOMItem.product_id == payload.product_id)
        )
    ).scalar_one_or_none():
        raise HTTPException(422, "该零件不在这个产品的零件清单中")
    await _require_row(db, MaterialType, payload.material_type_id, "Material type not found")
    await _require_row(db, PrinterProfile, payload.printer_profile_id, "Printer profile not found")
    await _require_row(db, LibraryFile, payload.library_file_id, "Library file not found")
    await _require_row(db, SlicerPipeline, payload.slicer_pipeline_id, "Slicer pipeline not found")
    for key, value in payload.model_dump(exclude={"compatible_profile_ids"}).items():
        setattr(recipe, key, value)
    recipe.compatible_profiles = [
        await _require_row(db, PrinterProfile, pid, "Compatible printer profile not found")
        for pid in payload.compatible_profile_ids
    ]
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Recipe code and version already exists")
    return (
        await db.execute(
            select(ProductionRecipe)
            .where(ProductionRecipe.id == recipe.id)
            .options(selectinload(ProductionRecipe.compatible_profiles))
        )
    ).scalar_one()


@router.delete("/recipes/{item_id}", status_code=204)
async def delete_recipe(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.RECIPES_WRITE),
):
    item = await _require_row(db, ProductionRecipe, item_id, "Recipe not found")
    ref = (
        await db.execute(select(ProductionRequirement.id).where(ProductionRequirement.recipe_id == item_id).limit(1))
    ).scalar_one_or_none()
    if ref:
        raise HTTPException(409, "Recipe is referenced by a production requirement")
    await db.delete(item)
    await db.commit()


@router.get("/orders", response_model=list[ProductionOrderResponse])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_READ),
):
    return list((await db.execute(select(ProductionOrder).order_by(ProductionOrder.id))).scalars().all())


@router.post("/orders", response_model=ProductionOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: ProductionOrderCreate,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_CREATE),
):
    try:
        order, replayed = await create_production_order(
            db,
            **payload.model_dump(),
            actor_user_id=current_user.id if current_user else None,
        )
    except ProductionOrderError as exc:
        raise HTTPException(422, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "生产订单编号已经存在") from exc
    if replayed:
        response.status_code = status.HTTP_200_OK
    return order


@router.get("/orders/{order_id}", response_model=ProductionOrderDetail)
async def get_order_detail(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_READ),
):
    try:
        return await order_detail(db, order_id)
    except ProductionOrderError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.patch("/orders/{order_id}", response_model=ProductionOrderResponse)
async def update_order(
    order_id: int,
    payload: ProductionOrderUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_UPDATE),
):
    try:
        return await update_production_order(
            db,
            order_id,
            **payload.model_dump(),
            provided_fields=payload.model_fields_set,
        )
    except ProductionOrderError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/orders/{order_id}/status", response_model=ProductionOrderResponse)
async def update_order_status(
    order_id: int,
    payload: ProductionOrderStatusAction,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_UPDATE),
):
    if payload.action == "cancel":
        # Authentication-disabled development instances return ``None`` and are
        # already trusted by the dependency.  Permission enforcement remains in
        # the dependency layer for authenticated deployments.
        pass
    try:
        order, _ = await change_order_status(
            db,
            order_id=order_id,
            operation_id=payload.operation_id,
            action=payload.action,
            actor_user_id=current_user.id if current_user else None,
        )
        return order
    except ProductionOrderError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/orders/{order_id}/plate-jobs/preview", response_model=PlateJobPreviewResponse)
async def preview_order_plate_jobs(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PLATE_JOBS_READ),
):
    try:
        order, items = await preview_plate_jobs(db, order_id)
        return {"order_id": order.id, "items": items}
    except ProductionOrderError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post(
    "/orders/{order_id}/plate-jobs/confirm",
    response_model=PlateJobConfirmResponse,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_order_plate_jobs(
    order_id: int,
    payload: PlateJobConfirmRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.PLATE_JOBS_CREATE),
):
    try:
        jobs, replayed = await confirm_plate_jobs(
            db,
            order_id=order_id,
            operation_id=payload.operation_id,
            items=payload.items,
            actor_user_id=current_user.id if current_user else None,
        )
    except ProductionOrderError as exc:
        raise HTTPException(409, str(exc)) from exc
    if replayed:
        response.status_code = status.HTTP_200_OK
    return {"order_id": order_id, "items": jobs}


@router.get("/requirements", response_model=list[ProductionRequirementResponse])
async def list_requirements(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_READ),
):
    return list((await db.execute(select(ProductionRequirement).order_by(ProductionRequirement.id))).scalars().all())


@router.get("/plate-jobs", response_model=list[PlateJobResponse])
async def list_plate_jobs(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PLATE_JOBS_READ),
):
    return list((await db.execute(select(PlateJob).order_by(PlateJob.id))).scalars().all())


@router.get("/operations", response_model=list[OperationLogResponse])
async def list_operations(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PLATE_JOBS_READ),
):
    return list((await db.execute(select(OperationLog).order_by(OperationLog.id))).scalars().all())
