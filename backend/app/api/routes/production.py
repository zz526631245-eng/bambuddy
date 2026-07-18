"""Stage 6 create/read-only production-domain API skeleton.

No endpoint in this module imports the scheduler, creates queue items, or
communicates with a printer.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.library import LibraryFile
from backend.app.models.material_type import MaterialType
from backend.app.models.operation_log import OperationLog
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.production import PlateJob, ProductionOrder, ProductionRequirement
from backend.app.models.production_recipe import ProductionRecipe
from backend.app.models.slicer_pipeline import SlicerPipeline
from backend.app.models.user import User
from backend.app.schemas.production import (
    MaterialTypeCreate,
    MaterialTypeResponse,
    OperationLogResponse,
    PlateJobResponse,
    PrinterProfileCreate,
    PrinterProfileResponse,
    ProductionOrderCreate,
    ProductionOrderResponse,
    ProductionRecipeCreate,
    ProductionRecipeResponse,
    ProductionRequirementResponse,
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


@router.get("/recipes", response_model=list[ProductionRecipeResponse])
async def list_recipes(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.RECIPES_READ),
):
    return list((await db.execute(select(ProductionRecipe).order_by(ProductionRecipe.id))).scalars().all())


@router.post("/recipes", response_model=ProductionRecipeResponse, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    payload: ProductionRecipeCreate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.RECIPES_WRITE),
):
    await _require_row(db, Product, payload.product_id, "Product not found")
    await _require_row(db, MaterialType, payload.material_type_id, "Material type not found")
    await _require_row(db, PrinterProfile, payload.printer_profile_id, "Printer profile not found")
    await _require_row(db, LibraryFile, payload.library_file_id, "Library file not found")
    await _require_row(db, SlicerPipeline, payload.slicer_pipeline_id, "Slicer pipeline not found")
    return await _commit_unique(
        db,
        ProductionRecipe(**payload.model_dump()),
        "Recipe code and version already exist",
    )


@router.get("/orders", response_model=list[ProductionOrderResponse])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_READ),
):
    return list((await db.execute(select(ProductionOrder).order_by(ProductionOrder.id))).scalars().all())


@router.post("/orders", response_model=ProductionOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: ProductionOrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.PRODUCTION_ORDERS_CREATE),
):
    await _require_row(db, Product, payload.product_id, "Product not found")
    values = payload.model_dump()
    values["created_by_id"] = current_user.id if current_user else None
    return await _commit_unique(db, ProductionOrder(**values), "Production order number already exists")


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
