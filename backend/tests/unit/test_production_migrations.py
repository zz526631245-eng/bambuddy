"""SQLite migration and upgrade-safety tests for the Stage 6 schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import MetaData, event, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

import backend.app.models  # noqa: F401
from backend.app.core.database import Base, ensure_production_schema
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
