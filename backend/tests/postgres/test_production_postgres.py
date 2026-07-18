"""Real PostgreSQL Stage 6 schema tests.

These tests are skipped outside the dedicated GitHub Actions PostgreSQL job.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import MetaData, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.app.models  # noqa: F401
from backend.app.core.database import Base, ensure_production_schema
from backend.app.models.operation_log import OperationLog
from backend.app.models.product import Product
from backend.app.models.production import PRODUCTION_TABLE_NAMES, ProductionOrder

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
