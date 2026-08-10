"""Stage 13 normalized printer status and heartbeat tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.production_printer_status import ProductionPrinterStatus
from backend.app.models.virtual_printer import VirtualPrinter


async def test_status_list_and_idempotent_heartbeat_for_virtual_printer(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    virtual = VirtualPrinter(name="阶段13状态测试机", enabled=True, model="N2S")
    db_session.add(virtual)
    await db_session.commit()
    await db_session.refresh(virtual)

    initial = await async_client.get("/api/v1/production/printer-status")
    assert initial.status_code == 200, initial.text
    before = next(item for item in initial.json() if item["target_key"] == f"virtual_printer:{virtual.id}")
    assert before["effective_state"] == "unknown"
    assert before["available_for_allocation"] is True
    assert before["transport_enabled"] is False

    heartbeat = await async_client.post(
        "/api/v1/production/printer-status/heartbeat",
        json={
            "operation_id": "stage13-heartbeat-online",
            "target_type": "virtual_printer",
            "target_id": virtual.id,
            "state": "printing",
            "current_job_id": 42,
            "current_job_state": "printing",
            "loaded_filaments": [{"slot": 254, "material": "PLA", "color_hex": "FFFFFF"}],
            "telemetry": {"progress": 37},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["effective_state"] == "printing"
    assert heartbeat.json()["available_for_allocation"] is True
    assert heartbeat.json()["current_job_id"] == 42

    replay = await async_client.post(
        "/api/v1/production/printer-status/heartbeat",
        json={
            "operation_id": "stage13-heartbeat-online",
            "target_type": "virtual_printer",
            "target_id": virtual.id,
            "state": "idle",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["effective_state"] == "printing"

    offline = await async_client.post(
        "/api/v1/production/printer-status/heartbeat",
        json={
            "operation_id": "stage13-heartbeat-offline",
            "target_type": "virtual_printer",
            "target_id": virtual.id,
            "state": "maintenance",
            "fault_code": "MAINT-001",
            "fault_message": "需要清洁喷嘴",
        },
    )
    assert offline.status_code == 200, offline.text
    assert offline.json()["effective_state"] == "maintenance"
    assert offline.json()["available_for_allocation"] is False
    assert offline.json()["fault_code"] == "MAINT-001"


async def test_stale_heartbeat_is_reported_offline(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    virtual = VirtualPrinter(name="阶段13过期心跳测试机", enabled=True, model="N2S")
    db_session.add(virtual)
    await db_session.commit()
    row = ProductionPrinterStatus(
        target_key=f"virtual_printer:{virtual.id}",
        target_type="virtual_printer",
        target_id=virtual.id,
        state="idle",
        last_heartbeat_at=datetime.utcnow() - timedelta(seconds=90),
        observed_at=datetime.utcnow() - timedelta(seconds=90),
    )
    db_session.add(row)
    await db_session.commit()

    response = await async_client.get("/api/v1/production/printer-status")
    assert response.status_code == 200, response.text
    status = next(item for item in response.json() if item["target_key"] == f"virtual_printer:{virtual.id}")
    assert status["state"] == "idle"
    assert status["effective_state"] == "offline"
    assert status["stale"] is True
    assert status["available_for_allocation"] is False
