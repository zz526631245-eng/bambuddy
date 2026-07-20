"""Real PostgreSQL Stage 6 schema tests.

These tests are skipped outside the dedicated GitHub Actions PostgreSQL job.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import MetaData, func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.app.models  # noqa: F401
from backend.app.core.database import Base, ensure_production_schema, ensure_stage7_columns, ensure_stage8_columns
from backend.app.models.library import LibraryFile
from backend.app.models.operation_log import OperationLog
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.product_master import ProductComponent, ProductionBOMItem
from backend.app.models.production import PRODUCTION_TABLE_NAMES, PlateJob, ProductionOrder, ProductionRequirement
from backend.app.models.production_recipe import ProductionRecipe
from backend.app.services import production_order_service
from backend.app.services.production_allocator import allocate_plate_jobs
from backend.app.services.production_order_service import create_order

POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")
pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is only set in the PostgreSQL CI job"),
]


def _legacy_metadata() -> MetaData:
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name not in PRODUCTION_TABLE_NAMES:
            table.to_metadata(metadata)
    return metadata


@pytest.fixture
async def postgres_engine():
    schema = f"stage6_{uuid.uuid4().hex}"
    admin = create_async_engine(POSTGRES_URL, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        POSTGRES_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        yield engine
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


async def test_postgres_fresh_and_repeated_schema_creation(postgres_engine):
    async with postgres_engine.begin() as conn:
        await ensure_production_schema(conn)
        await ensure_production_schema(conn)
        names = set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))
    assert names >= PRODUCTION_TABLE_NAMES


async def test_postgres_legacy_upgrade_preserves_existing_rows(postgres_engine):
    async with postgres_engine.begin() as conn:
        await conn.run_sync(_legacy_metadata().create_all)
        await conn.execute(text("INSERT INTO settings (key, value) VALUES ('stage6_pg_sentinel', 'preserve-me')"))

    async with postgres_engine.begin() as conn:
        await ensure_production_schema(conn)
        await ensure_production_schema(conn)

    async with postgres_engine.connect() as conn:
        names = set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))
        sentinel = (
            await conn.execute(text("SELECT value FROM settings WHERE key = 'stage6_pg_sentinel'"))
        ).scalar_one()
    assert names >= PRODUCTION_TABLE_NAMES
    assert sentinel == "preserve-me"


async def test_postgres_constraints_match_sqlite_contract(postgres_engine):
    async with postgres_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with sessions() as session:
        product = Product(sku="PG-SKU", name="PostgreSQL Product")
        session.add(product)
        await session.flush()

        session.add(ProductionOrder(order_number="PG-NEG", product_id=product.id, quantity=-1))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        session.add(
            OperationLog(
                operation_id="pg-operation-1",
                operation_type="stage6_test",
                entity_type="product",
                entity_id=product.id,
            )
        )
        await session.commit()
        session.add(
            OperationLog(
                operation_id="pg-operation-1",
                operation_type="stage6_duplicate",
                entity_type="product",
                entity_id=product.id,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_postgres_operation_id_is_safe_under_concurrent_inserts(postgres_engine):
    async with postgres_engine.begin() as conn:
        await ensure_production_schema(conn)

    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)

    async def insert_once(operation_type: str) -> str:
        async with sessions() as session:
            session.add(
                OperationLog(
                    operation_id="pg-concurrent-operation",
                    operation_type=operation_type,
                    entity_type="production_order",
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return "duplicate"
            return "created"

    results = await asyncio.gather(insert_once("worker-a"), insert_once("worker-b"))
    assert sorted(results) == ["created", "duplicate"]


async def test_postgres_stage6_to_stage7_columns_preserve_rows(postgres_engine):
    async with postgres_engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE printer_profiles (id SERIAL PRIMARY KEY, code VARCHAR(100), name VARCHAR(255), printer_model VARCHAR(50), nozzle_diameter DOUBLE PRECISION, version INTEGER, is_active BOOLEAN)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE production_recipes (id SERIAL PRIMARY KEY, code VARCHAR(100), name VARCHAR(255), version INTEGER, is_active BOOLEAN)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO printer_profiles (code, name, printer_model, nozzle_diameter, version, is_active) VALUES ('X1', 'X1', 'X1C', 0.4, 1, TRUE)"
            )
        )
        await conn.execute(
            text("INSERT INTO production_recipes (code, name, version, is_active) VALUES ('R1', 'Recipe', 1, TRUE)")
        )
        await ensure_stage7_columns(conn)
        await ensure_stage7_columns(conn)
        profile = (await conn.execute(text("SELECT code, auto_production_enabled FROM printer_profiles"))).one()
        recipe = (await conn.execute(text("SELECT code, slicer_preset FROM production_recipes"))).one()
    assert profile == ("X1", False)
    assert recipe == ("R1", None)


async def test_postgres_stage7_to_stage8_columns_preserve_rows(postgres_engine):
    async with postgres_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE product_components (id SERIAL PRIMARY KEY)"))
        await conn.execute(
            text("CREATE TABLE production_recipes (id SERIAL PRIMARY KEY, code VARCHAR(100), name VARCHAR(255))")
        )
        await conn.execute(
            text(
                "CREATE TABLE production_orders (id SERIAL PRIMARY KEY, order_number VARCHAR(100), product_id INTEGER, quantity INTEGER, priority INTEGER, status VARCHAR(30))"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE production_requirements (id SERIAL PRIMARY KEY, order_id INTEGER, recipe_id INTEGER, required_quantity INTEGER, reserved_quantity INTEGER, good_quantity INTEGER, scrap_quantity INTEGER, status VARCHAR(30))"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO production_orders (order_number, product_id, quantity, priority, status) VALUES ('KEEP-PG-8', 1, 2, 0, 'planned')"
            )
        )
        await ensure_stage8_columns(conn)
        await ensure_stage8_columns(conn)
        row = (await conn.execute(text("SELECT order_number, product_snapshot FROM production_orders"))).one()
    assert row == ("KEEP-PG-8", None)


async def test_postgres_concurrent_order_creation_replays_one_result(postgres_engine):
    async with postgres_engine.begin() as conn:
        await ensure_production_schema(conn)
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with sessions() as session:
        product = Product(sku="PG-STAGE8", name="PG Stage 8")
        component = ProductComponent(code="PG-PART", name="PG Part", unit="pcs")
        session.add_all([product, component])
        await session.flush()
        session.add(ProductionBOMItem(product_id=product.id, component_id=component.id, quantity=1))
        recipe = ProductionRecipe(
            code="PG-PLAN",
            name="PG Plan",
            product_id=product.id,
            component_id=component.id,
            version=1,
        )
        session.add(recipe)
        await session.commit()
        product_id = product.id

    async def create_once():
        async with sessions() as session:
            order, replayed = await create_order(
                session,
                operation_id="pg-concurrent-stage8-order",
                order_number="PG-CONCURRENT-ORDER",
                product_id=product_id,
                quantity=3,
                priority=0,
                due_at=None,
                notes=None,
                actor_user_id=None,
            )
            return order.id, replayed

    results = await asyncio.gather(create_once(), create_once())
    assert results[0][0] == results[1][0]
    assert sorted(replayed for _, replayed in results) == [False, True]


async def test_postgres_concurrent_plate_job_confirmation_never_overallocates(
    postgres_engine,
):
    async with postgres_engine.begin() as conn:
        await ensure_production_schema(conn)
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)
    async with sessions() as session:
        product = Product(sku="PG-CONFIRM", name="PG Confirm")
        component = ProductComponent(code="PG-CONFIRM-PART", name="PG Confirm Part", unit="pcs")
        session.add_all([product, component])
        await session.flush()
        session.add(ProductionBOMItem(product_id=product.id, component_id=component.id, quantity=1))
        session.add(
            ProductionRecipe(
                code="PG-CONFIRM-PLAN",
                name="PG Confirm Plan",
                product_id=product.id,
                component_id=component.id,
                version=1,
            )
        )
        await session.commit()
        product_id = product.id

    async with sessions() as session:
        order, _ = await create_order(
            session,
            operation_id="pg-confirm-create-order",
            order_number="PG-CONFIRM-ORDER",
            product_id=product_id,
            quantity=3,
            priority=0,
            due_at=None,
            notes=None,
            actor_user_id=None,
        )
        order_id = order.id
        requirement_id = order.requirements[0].id

    start = asyncio.Event()
    ready = 0

    async def confirm_once(operation_id: str):
        nonlocal ready
        ready += 1
        if ready == 2:
            start.set()
        await asyncio.wait_for(start.wait(), timeout=5)
        async with sessions() as session:
            try:
                return await production_order_service.confirm_plate_jobs(
                    session,
                    order_id=order_id,
                    operation_id=operation_id,
                    items=[
                        type(
                            "PreviewItem",
                            (),
                            {
                                "requirement_id": requirement_id,
                                "printer_profile_id": None,
                                "planned_quantity": 3,
                            },
                        )()
                    ],
                    actor_user_id=None,
                )
            except production_order_service.ProductionOrderError:
                return [], False

    await asyncio.gather(confirm_once("pg-confirm-a"), confirm_once("pg-confirm-b"))

    async with sessions() as session:
        requirement = await session.get(ProductionRequirement, requirement_id)
        jobs = list(
            (await session.execute(select(PlateJob).where(PlateJob.requirement_id == requirement_id))).scalars()
        )
    total_planned = sum(job.planned_quantity for job in jobs)
    assert requirement is not None
    assert total_planned <= requirement.required_quantity
    assert requirement.reserved_quantity == total_planned


async def test_postgres_concurrent_stage9_allocators_create_one_queue_item(postgres_engine):
    async with postgres_engine.begin() as conn:
        await ensure_production_schema(conn)
    sessions = async_sessionmaker(postgres_engine, expire_on_commit=False)

    async with sessions() as session:
        product = Product(sku="PG-ALLOC", name="PG Allocator")
        component = ProductComponent(code="PG-ALLOC-PART", name="PG Allocator Part", unit="pcs")
        library_file = LibraryFile(
            filename="pg-stage9.3mf",
            file_path="library/pg-stage9.3mf",
            file_type="3mf",
            file_size=64,
        )
        profile = PrinterProfile(
            code="PG-AUTO-X1C",
            name="PG Auto X1C",
            printer_model="X1C",
            nozzle_diameter=0.4,
            location="PG-LAB",
            auto_production_enabled=True,
        )
        printer = Printer(
            name="PG simulated X1C",
            serial_number="PGSTAGE9000001",
            ip_address="192.0.2.90",
            access_code="00000000",
            model="X1C",
            location="PG-LAB",
            is_active=True,
        )
        session.add_all([product, component, library_file, profile, printer])
        await session.flush()
        session.add(ProductionBOMItem(product_id=product.id, component_id=component.id, quantity=1))
        session.add(
            ProductionRecipe(
                code="PG-ALLOC-PLAN",
                name="PG Allocator Plan",
                product_id=product.id,
                component_id=component.id,
                printer_profile_id=profile.id,
                library_file_id=library_file.id,
                version=1,
            )
        )
        await session.commit()
        product_id = product.id
        profile_id = profile.id

    async with sessions() as session:
        order, _ = await create_order(
            session,
            operation_id="pg-stage9-create",
            order_number="PG-STAGE9-ORDER",
            product_id=product_id,
            quantity=1,
            priority=0,
            due_at=None,
            notes=None,
            actor_user_id=None,
        )
        requirement_id = order.requirements[0].id
        jobs, _ = await production_order_service.confirm_plate_jobs(
            session,
            order_id=order.id,
            operation_id="pg-stage9-confirm",
            items=[
                type(
                    "PreviewItem",
                    (),
                    {
                        "requirement_id": requirement_id,
                        "printer_profile_id": profile_id,
                        "planned_quantity": 1,
                    },
                )()
            ],
            actor_user_id=None,
        )
        job_id = jobs[0].id

    start = asyncio.Event()
    ready = 0

    async def allocate_once():
        nonlocal ready
        ready += 1
        if ready == 2:
            start.set()
        await asyncio.wait_for(start.wait(), timeout=5)
        async with sessions() as session:
            return await allocate_plate_jobs(session, plate_job_ids=[job_id])

    await asyncio.gather(allocate_once(), allocate_once())

    async with sessions() as session:
        job = await session.get(PlateJob, job_id)
        queue_count = (await session.execute(select(func.count(PrintQueueItem.id)))).scalar_one()
    assert job is not None
    assert job.status == "assigned"
    assert job.queue_item_id is not None
    assert queue_count == 1
