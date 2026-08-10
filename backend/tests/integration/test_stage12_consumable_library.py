"""Stage 12 consumable-unit library, inbound scan and depletion tests."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.virtual_printer import VirtualPrinter


async def _material_type(client: AsyncClient, suffix: str) -> dict:
    response = await client.post(
        "/api/v1/production/material-types",
        json={
            "code": f"3DR-WHITE-{suffix}",
            "material": "PLA",
            "brand": "3DR",
            "color_name": "白色",
            "color_hex": "#FFFFFF",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_generate_unique_units_and_receive_is_idempotent(
    async_client: AsyncClient,
):
    material = await _material_type(async_client, "A")
    generated = await async_client.post(
        "/api/v1/production/consumable-library/batches",
        json={"operation_id": "stage12-library-generate-a", "material_type_id": material["id"], "quantity": 3},
    )
    assert generated.status_code == 201, generated.text
    units = generated.json()["items"]
    assert len(units) == 3
    assert len({unit["unit_code"] for unit in units}) == 3
    assert {unit["status"] for unit in units} == {"generated"}

    received = await async_client.post(
        "/api/v1/production/consumable-library/scan",
        json={
            "operation_id": "stage12-library-receive-a",
            "unit_code": units[0]["unit_code"],
            "action": "receive",
        },
    )
    assert received.status_code == 200, received.text
    assert received.json()["status"] == "in_stock"

    replay = await async_client.post(
        "/api/v1/production/consumable-library/scan",
        json={
            "operation_id": "stage12-library-receive-a",
            "unit_code": units[0]["unit_code"],
            "action": "receive",
        },
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True

    summary = await async_client.get("/api/v1/production/consumable-library/summary")
    assert summary.status_code == 200
    assert summary.json()["generated"] == 2
    assert summary.json()["in_stock"] == 1


async def test_bound_unit_depletion_releases_direct_printer_binding(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    material = await _material_type(async_client, "B")
    batch = await async_client.post(
        "/api/v1/production/consumable-library/batches",
        json={"operation_id": "stage12-library-generate-b", "material_type_id": material["id"], "quantity": 1},
    )
    unit = batch.json()["items"][0]
    received = await async_client.post(
        "/api/v1/production/consumable-library/scan",
        json={"operation_id": "stage12-library-receive-b", "unit_code": unit["unit_code"], "action": "receive"},
    )
    assert received.json()["status"] == "in_stock"

    virtual = VirtualPrinter(
        name="阶段12耗材库测试机",
        enabled=True,
        model="N2S",
        supported_materials=["PLA"],
        supported_colors=["FFFFFF"],
        loaded_filaments=[],
    )
    db_session.add(virtual)
    await db_session.commit()
    await db_session.refresh(virtual)
    bound = await async_client.post(
        "/api/v1/production/printer-consumables/scan",
        json={
            "operation_id": "stage12-library-bind-b",
            "scan_code": unit["unit_code"],
            "material": "PLA",
            "color_hex": "FFFFFF",
            "color_name": "白色",
            "virtual_printer_id": virtual.id,
            "consumable_unit_id": unit["id"],
        },
    )
    assert bound.status_code == 201, bound.text
    depleted = await async_client.post(
        "/api/v1/production/consumable-library/scan",
        json={
            "operation_id": "stage12-library-deplete-b",
            "unit_code": unit["unit_code"],
            "action": "deplete",
        },
    )
    assert depleted.status_code == 200, depleted.text
    assert depleted.json()["status"] == "depleted"
    active = await async_client.get("/api/v1/production/printer-consumables")
    assert all(item["virtual_printer_id"] != virtual.id for item in active.json())
