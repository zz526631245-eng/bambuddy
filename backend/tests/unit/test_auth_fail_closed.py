"""Regression tests for the GHSA-6mf4-q26m-47pv fail-open auth bypass.

The previous version of ``is_auth_enabled`` caught every exception and
returned False (auth disabled). An attacker could trigger a DB-side
exception — the documented PoC exhausts file descriptors via a flood on
``/api/v1/auth/login`` until the next SQLite ``connect`` raises — and then
hit any protected endpoint during that fail-open window with no token at
all. Severity CVSS 9.8.

These tests pin the fail-closed contract:

1. ``is_auth_enabled`` propagates any DB exception (instead of swallowing
   it and returning False).
2. The "no settings row" path still returns False (auth was legitimately
   never configured).
3. ``setting.value == "true"`` still returns True.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError

from backend.app.core.auth import is_auth_enabled


def _make_locked_error() -> OperationalError:
    return OperationalError(
        statement="SELECT value FROM settings",
        params=(),
        orig=Exception("database is locked"),
    )


@pytest.mark.asyncio
async def test_is_auth_enabled_propagates_db_exception_instead_of_failing_open():
    """The core regression for GHSA-6mf4-q26m-47pv. A DB error during the
    auth-enabled probe must propagate — fail closed — instead of returning
    False and treating the system as auth-disabled."""

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=OSError("simulated file-descriptor exhaustion"))

    with pytest.raises(OSError, match="simulated file-descriptor exhaustion"):
        await is_auth_enabled(db)


@pytest.mark.asyncio
async def test_is_auth_enabled_returns_false_when_settings_row_absent():
    """Legitimate 'auth was never configured' path: the settings row simply
    does not exist. ``scalar_one_or_none`` returns None, no exception, and
    the function returns False — system is auth-disabled by configuration,
    not because the DB blew up."""

    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    assert await is_auth_enabled(db) is False


@pytest.mark.asyncio
async def test_is_auth_enabled_returns_true_when_setting_value_is_true():
    """Happy path: the settings row exists and its value is "true" → auth
    is enabled and the caller must require credentials."""

    setting = MagicMock()
    setting.value = "true"
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=setting)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    assert await is_auth_enabled(db) is True


@pytest.mark.asyncio
async def test_is_auth_enabled_returns_false_when_setting_value_is_false():
    """Happy path: the settings row exists and its value is "false" → auth
    is disabled by configuration (legitimate, not exception)."""

    setting = MagicMock()
    setting.value = "false"
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=setting)
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    assert await is_auth_enabled(db) is False


@pytest.mark.asyncio
async def test_is_auth_enabled_retries_transient_sqlite_lock():
    """A short SQLite writer lock must not turn a healthy auth-disabled
    instance into a user-visible 503."""

    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=None)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_make_locked_error(), result])

    with patch("backend.app.core.auth.asyncio.sleep", new_callable=AsyncMock) as sleep:
        assert await is_auth_enabled(db) is False

    db.rollback.assert_awaited_once()
    sleep.assert_awaited_once_with(0.1)


@pytest.mark.asyncio
async def test_is_auth_enabled_still_fails_closed_after_persistent_lock():
    """Retrying must not weaken the fail-closed security contract."""

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=_make_locked_error())

    with (
        patch("backend.app.core.auth.asyncio.sleep", new_callable=AsyncMock) as sleep,
        pytest.raises(OperationalError, match="database is locked"),
    ):
        await is_auth_enabled(db)

    assert db.rollback.await_count == 2
    assert sleep.await_count == 2
