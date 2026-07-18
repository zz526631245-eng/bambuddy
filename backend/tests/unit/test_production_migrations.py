"""SQLite migration and upgrade-safety tests for the Stage 6 schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import MetaData, event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

import backend.app.models  # noqa: F401
from backend.app.core.database import Base, ensure_production_schema, ensure_stage7_columns, ensure_stage8_columns
from backend.app.models.production import PRODUCTION_TABLE_NAMES


def _legacy_metadata() -> MetaData:
    """Copy the current pre-production schema, excluding Stage 6 tables."""
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        if table.name not in PRODUCTION_TABLE_NAMES:
            table.to_metadata(metadata)
    return metadata


async def _table_names(conn) -> set[str]:
    return set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))


async def test_sqlite_fresh_schema_creation_is_complete_and_idempotent(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    async with engine.begin() as conn:
        await ensure_production_schema(conn)
        await ensure_production_schema(conn)
        tables = await _table_names(conn)

    assert tables >= PRODUCTION_TABLE_NAMES
    await engine.dispose()


async def test_sqlite_legacy_upgrade_preserves_old_rows_and_is_idempotent(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'legacy.db'}")
    legacy = _legacy_metadata()
    async with engine.begin() as conn:
        await conn.run_sync(legacy.create_all)
        await conn.execute(text("INSERT INTO settings (key, value) VALUES ('stage6_sentinel', 'preserve-me')"))

    async with engine.begin() as conn:
        await ensure_production_schema(conn)
        await ensure_production_schema(conn)

    async with engine.connect() as conn:
        tables = await _table_names(conn)
        sentinel = (await conn.execute(text("SELECT value FROM settings WHERE key = 'stage6_sentinel'"))).scalar_one()

    assert tables >= PRODUCTION_TABLE_NAMES
    assert sentinel == "preserve-me"
    await engine.dispose()


async def test_sqlite_schema_failure_does_not_damage_legacy_tables(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'failed-upgrade.db'}")
    legacy = _legacy_metadata()
    async with engine.begin() as conn:
        await conn.run_sync(legacy.create_all)
        await conn.execute(text("INSERT INTO settings (key, value) VALUES ('stage6_sentinel', 'still-here')"))

    def fail_during_production_create(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "CREATE TABLE production_recipes" in statement:
            raise RuntimeError("simulated production schema failure")

    event.listen(engine.sync_engine, "before_cursor_execute", fail_during_production_create)
    try:
        with pytest.raises(RuntimeError, match="simulated production schema failure"):
            async with engine.begin() as conn:
                await ensure_production_schema(conn)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", fail_during_production_create)

    async with engine.connect() as conn:
        sentinel = (await conn.execute(text("SELECT value FROM settings WHERE key = 'stage6_sentinel'"))).scalar_one()
        integrity = (await conn.execute(text("PRAGMA integrity_check"))).scalar_one()

    assert sentinel == "still-here"
    assert integrity == "ok"
    await engine.dispose()


async def test_sqlite_stage6_to_stage7_columns_preserve_rows_and_repeat(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stage6-to-7.db'}")
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE printer_profiles (id INTEGER PRIMARY KEY, code VARCHAR(100), name VARCHAR(255), printer_model VARCHAR(50), nozzle_diameter REAL, version INTEGER, is_active BOOLEAN)"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE production_recipes (id INTEGER PRIMARY KEY, code VARCHAR(100), name VARCHAR(255), version INTEGER, is_active BOOLEAN)"
            )
        )
        await conn.execute(text("INSERT INTO printer_profiles VALUES (1, 'X1', 'X1', 'X1C', 0.4, 1, 1)"))
        await conn.execute(text("INSERT INTO production_recipes VALUES (1, 'R1', 'Recipe', 1, 1)"))
        await ensure_stage7_columns(conn)
        await ensure_stage7_columns(conn)
        profile = (await conn.execute(text("SELECT code, auto_production_enabled FROM printer_profiles"))).one()
        recipe = (await conn.execute(text("SELECT code, slicer_preset FROM production_recipes"))).one()
    assert profile == ("X1", 0)
    assert recipe == ("R1", None)
    await engine.dispose()


async def test_sqlite_stage7_to_stage8_columns_preserve_rows_and_repeat(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'stage7-to-8.db'}")
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE production_recipes (id INTEGER PRIMARY KEY, code VARCHAR(100), name VARCHAR(255))")
        )
        await conn.execute(
            text(
                "CREATE TABLE production_orders (id INTEGER PRIMARY KEY, order_number VARCHAR(100), product_id INTEGER, quantity INTEGER, priority INTEGER, status VARCHAR(30))"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE production_requirements (id INTEGER PRIMARY KEY, order_id INTEGER, recipe_id INTEGER, required_quantity INTEGER, reserved_quantity INTEGER, good_quantity INTEGER, scrap_quantity INTEGER, status VARCHAR(30))"
            )
        )
        await conn.execute(text("INSERT INTO production_orders VALUES (1, 'KEEP-8', 1, 2, 0, 'planned')"))
        await ensure_stage8_columns(conn)
        await ensure_stage8_columns(conn)
        order = (await conn.execute(text("SELECT order_number, product_snapshot FROM production_orders"))).one()
        requirement_columns = {
            column[1] for column in (await conn.execute(text("PRAGMA table_info(production_requirements)"))).all()
        }

    assert order == ("KEEP-8", None)
    assert {"component_id", "unit_quantity", "component_snapshot", "recipe_snapshot"} <= requirement_columns
    await engine.dispose()
