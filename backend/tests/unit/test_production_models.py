"""Stage 6 contracts for the production-domain model skeleton."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.core.database import Base
from backend.app.core.permissions import ALL_PERMISSIONS, DEFAULT_GROUPS, PERMISSION_CATEGORIES, Permission
from backend.app.models.material_type import MaterialType
from backend.app.models.operation_log import OperationLog
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.production import (
    OrderStatus,
    PlateJob,
    PlateJobStatus,
    ProductionOrder,
    ProductionRequirement,
    RequirementStatus,
)
from backend.app.models.production_recipe import ProductionRecipe

PRODUCTION_TABLES = {
    "products",
    "material_types",
    "printer_profiles",
    "production_recipes",
    "production_orders",
    "production_requirements",
    "plate_jobs",
    "operation_logs",
}


def test_production_tables_are_registered_with_metadata():
    assert set(Base.metadata.tables) >= PRODUCTION_TABLES


def test_status_enums_are_string_stable():
    assert OrderStatus.DRAFT.value == "draft"
    assert OrderStatus.PLANNED.value == "planned"
    assert RequirementStatus.PENDING.value == "pending"
    assert PlateJobStatus.WAITING_CLEANUP.value == "waiting_cleanup"


def test_production_permissions_are_classified_and_added_to_default_roles():
    production_permissions = {permission.value for permission in PERMISSION_CATEGORIES["Production"]}
    operator_permissions = set(DEFAULT_GROUPS["Operators"]["permissions"])
    viewer_permissions = set(DEFAULT_GROUPS["Viewers"]["permissions"])
    read_permissions = {
        Permission.PRODUCTS_READ.value,
        Permission.MATERIAL_TYPES_READ.value,
        Permission.PRINTER_PROFILES_READ.value,
        Permission.RECIPES_READ.value,
        Permission.PRODUCTION_ORDERS_READ.value,
        Permission.PLATE_JOBS_READ.value,
    }

    assert set(ALL_PERMISSIONS) >= production_permissions
    assert operator_permissions >= production_permissions
    assert viewer_permissions >= read_permissions
    assert not (viewer_permissions & (production_permissions - read_permissions))


@pytest.mark.parametrize(
    ("model", "constraint_name"),
    [
        (ProductionOrder, "ck_production_orders_quantity_non_negative"),
        (ProductionOrder, "ck_production_orders_priority_non_negative"),
        (ProductionRequirement, "ck_production_requirements_required_quantity_non_negative"),
        (ProductionRequirement, "ck_production_requirements_reserved_quantity_non_negative"),
        (ProductionRequirement, "ck_production_requirements_good_quantity_non_negative"),
        (ProductionRequirement, "ck_production_requirements_scrap_quantity_non_negative"),
        (PlateJob, "ck_plate_jobs_planned_quantity_non_negative"),
    ],
)
def test_quantity_columns_have_named_non_negative_constraints(model, constraint_name):
    names = {constraint.name for constraint in model.__table__.constraints}
    assert constraint_name in names


def test_operation_id_is_uniquely_constrained():
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in OperationLog.__table__.constraints
        if getattr(constraint, "unique", False) or constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("operation_id",) in unique_columns


async def test_sqlite_enforces_non_negative_quantity_and_unique_operation_id():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        product = Product(sku="TEST-SKU", name="Test Product")
        session.add(product)
        await session.flush()

        session.add(ProductionOrder(order_number="ORDER-NEG", product_id=product.id, quantity=-1))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        first = OperationLog(
            operation_id="op-stage6-1",
            operation_type="stage6_test",
            entity_type="product",
            entity_id=product.id,
        )
        session.add(first)
        await session.commit()

        duplicate = OperationLog(
            operation_id="op-stage6-1",
            operation_type="stage6_test_duplicate",
            entity_type="product",
            entity_id=product.id,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        rows = (await session.execute(select(OperationLog))).scalars().all()
        assert len(rows) == 1

    await engine.dispose()


async def test_models_can_be_created_together_without_queue_side_effects():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        product = Product(sku="P-001", name="Widget")
        material = MaterialType(code="PLA-WHITE", material="PLA", color_name="White")
        profile = PrinterProfile(code="X1C-04", name="X1C 0.4", printer_model="X1C", nozzle_diameter=0.4)
        session.add_all([product, material, profile])
        await session.flush()

        recipe = ProductionRecipe(
            code="R-001",
            name="Widget recipe",
            product_id=product.id,
            material_type_id=material.id,
            printer_profile_id=profile.id,
            version=1,
        )
        session.add(recipe)
        await session.flush()

        order = ProductionOrder(order_number="O-001", product_id=product.id, quantity=10)
        session.add(order)
        await session.flush()
        requirement = ProductionRequirement(order_id=order.id, recipe_id=recipe.id, required_quantity=10)
        session.add(requirement)
        await session.flush()
        job = PlateJob(requirement_id=requirement.id, planned_quantity=2)
        session.add(job)
        await session.commit()

        assert job.queue_item_id is None

    async with engine.connect() as conn:
        queue_count = (await conn.exec_driver_sql("SELECT COUNT(*) FROM print_queue")).scalar_one()
        assert queue_count == 0

    await engine.dispose()
