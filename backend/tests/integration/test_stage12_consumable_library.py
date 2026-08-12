"""Stage 12 consumable-unit library, inbound scan and depletion tests."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.production_consumable_unit import ProductionConsumableUnit
from backend.app.models.production_printer_consumable import ProductionPrinterConsumable
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.services import production_consumption


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
        json={
            "operation_id": "stage12-library-generate-a",
            "material_type_id": material["id"],
            "quantity": 3,
            "initial_weight_g": 1000,
            "unit_price": 80,
        },
    )
    assert generated.status_code == 201, generated.text
    units = generated.json()["items"]
    assert len(units) == 3
    assert len({unit["unit_code"] for unit in units}) == 3
    assert {unit["status"] for unit in units} == {"generated"}
    assert {unit["initial_weight_g"] for unit in units} == {1000}
    assert {unit["unit_price"] for unit in units} == {80}

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

    materials = await async_client.get("/api/v1/production/material-types")
    assert materials.status_code == 200, materials.text
    material_stats = next(item["consumable_stats"] for item in materials.json() if item["id"] == material["id"])
    assert material_stats["generated"] == 2
    assert material_stats["in_stock"] == 1
    assert material_stats["received"] == 1
    assert [unit["unit_code"] for unit in material_stats["units"]] == [units[2]["unit_code"], units[1]["unit_code"], units[0]["unit_code"]]

    inventory = await async_client.get("/api/v1/production/consumable-library/inventory-summary")
    assert inventory.status_code == 200, inventory.text
    grouped = next(item for item in inventory.json() if item["material"] == "PLA" and item["brand"] == "3DR")
    assert grouped["in_stock"] == 1
    assert grouped["generated"] == 2
    assert grouped["total"] == 3


async def test_qr_batch_history_is_one_downloadable_40mm_pdf(
    async_client: AsyncClient,
):
    material = await _material_type(async_client, "PDF")
    generated = await async_client.post(
        "/api/v1/production/consumable-library/batches",
        json={
            "operation_id": "stage12-library-pdf-batch",
            "material_type_id": material["id"],
            "quantity": 2,
        },
    )
    assert generated.status_code == 201, generated.text
    batch_id = generated.json()["batch_id"]

    history = await async_client.get("/api/v1/production/consumable-library/batches")
    assert history.status_code == 200, history.text
    batch = next(item for item in history.json() if item["batch_id"] == batch_id)
    assert batch["quantity"] == 2
    assert batch["received_count"] == 0

    # The inventory-facing endpoints intentionally omit labels that have not
    # been scanned into storage; only the batch download history retains them.
    visible_units = await async_client.get("/api/v1/production/consumable-library")
    assert visible_units.status_code == 200
    assert all(item["unit_code"] not in {unit["unit_code"] for unit in generated.json()["items"]} for item in visible_units.json())
    visible_summary = await async_client.get(
        "/api/v1/production/consumable-library/summary?include_pending=false"
    )
    assert visible_summary.status_code == 200
    assert visible_summary.json()["generated"] == 0

    pdf_response = await async_client.get(
        f"/api/v1/production/consumable-library/batches/{batch_id}/pdf"
    )
    assert pdf_response.status_code == 200, pdf_response.text
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert "attachment" in pdf_response.headers["content-disposition"]
    assert b"/MediaBox [ 0 0 113.3858 113.3858 ]" in pdf_response.content


async def test_consumption_is_recorded_once_and_can_be_filtered(
    async_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch,
):
    material = await _material_type(async_client, "C")
    batch = await async_client.post(
        "/api/v1/production/consumable-library/batches",
        json={
            "operation_id": "stage15-library-generate-c",
            "material_type_id": material["id"],
            "quantity": 1,
            "initial_weight_g": 1000,
            "unit_price": 80,
        },
    )
    unit = batch.json()["items"][0]
    unit_row = await db_session.get(ProductionConsumableUnit, unit["id"])
    unit_row.status = "bound"
    printer = Printer(name="Stage 15 printer", serial_number="STAGE15-C", ip_address="127.0.0.1", access_code="x")
    db_session.add(printer)
    await db_session.flush()
    queue = PrintQueueItem(printer_id=printer.id, status="completed")
    db_session.add(queue)
    await db_session.flush()
    db_session.add(
        ProductionPrinterConsumable(
            printer_id=printer.id,
            consumable_unit_id=unit_row.id,
            scan_code=unit_row.unit_code,
            material="PLA",
            color_hex="FFFFFF",
            color_name="白色",
            operation_id="stage15-library-bind-c",
            is_active=True,
        )
    )
    await db_session.commit()
    monkeypatch.setattr(production_consumption, "estimate_queue_item_consumption", lambda *_args, **_kwargs: __import__("asyncio").sleep(0, result=125.0))

    first = await production_consumption.record_usage_for_queue_item(db_session, queue.id, queue_status="completed")
    replay = await production_consumption.record_usage_for_queue_item(db_session, queue.id, queue_status="completed")
    assert first is not None
    assert first["consumed_g"] == 125
    assert first["cost"] == 10
    assert replay["id"] == first["id"]
    await db_session.refresh(unit_row)
    assert unit_row.remaining_weight_g == 875

    summary = await async_client.get("/api/v1/production/consumable-library/consumption-summary?period=1y")
    assert summary.status_code == 200, summary.text
    assert summary.json()["consumed_g"] == 125
    assert summary.json()["cost"] == 10
    assert summary.json()["event_count"] == 1


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
