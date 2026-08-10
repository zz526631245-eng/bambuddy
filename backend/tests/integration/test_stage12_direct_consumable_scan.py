"""Stage 12 direct-feed consumable scan and automatic replacement tests."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.printer import Printer
from backend.app.models.production_printer_consumable import ProductionPrinterConsumable
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.services.production_printer_capabilities import capabilities_from_rows, match_filament_requirements


async def _virtual(db: AsyncSession, suffix: str = "A") -> VirtualPrinter:
    row = VirtualPrinter(
        name=f"Stage 12 test virtual {suffix}",
        enabled=True,
        model="N2S",
        supported_materials=["PLA"],
        supported_colors=["FF0000", "0000FF"],
        loaded_filaments=[],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def test_scan_registers_direct_feed_and_updates_loaded_snapshot(
    async_client: AsyncClient, db_session: AsyncSession
):
    virtual = await _virtual(db_session)
    targets = await async_client.get("/api/v1/production/printer-consumables/targets")
    assert targets.status_code == 200
    assert any(item["id"] == virtual.id and item["kind"] == "virtual_printer" for item in targets.json())
    response = await async_client.post(
        "/api/v1/production/printer-consumables/scan",
        json={
            "operation_id": "stage12-scan-first",
            "scan_code": "TAG-RED-001",
            "material": "pla",
            "color_hex": "#ff0000",
            "color_name": "红色",
            "virtual_printer_id": virtual.id,
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["replayed"] is False
    assert payload["replaced_id"] is None
    assert payload["color_hex"] == "FF0000"

    await db_session.refresh(virtual)
    assert virtual.loaded_filaments[0]["slot"] == 254
    assert virtual.loaded_filaments[0]["scan_code"] == "TAG-RED-001"

    match = match_filament_requirements(
        [{"slot": 254, "material": "PLA", "color": "FF0000"}],
        capabilities_from_rows(
            supported_materials=virtual.supported_materials,
            supported_colors=virtual.supported_colors,
            loaded_filaments=virtual.loaded_filaments,
        ),
    )
    assert match.matched is True


async def test_rescan_replaces_old_binding_and_replay_is_idempotent(
    async_client: AsyncClient, db_session: AsyncSession
):
    virtual = await _virtual(db_session, "B")
    first = await async_client.post(
        "/api/v1/production/printer-consumables/scan",
        json={
            "operation_id": "stage12-scan-old",
            "scan_code": "TAG-BLUE-001",
            "material": "PLA",
            "color_hex": "0000FF",
            "virtual_printer_id": virtual.id,
        },
    )
    old_id = first.json()["id"]
    second = await async_client.post(
        "/api/v1/production/printer-consumables/scan",
        json={
            "operation_id": "stage12-scan-new",
            "scan_code": "TAG-RED-002",
            "material": "PLA",
            "color_hex": "FF0000",
            "virtual_printer_id": virtual.id,
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["replaced_id"] == old_id
    rows = list((await db_session.execute(select(ProductionPrinterConsumable).order_by(ProductionPrinterConsumable.id))).scalars())
    assert [(row.id, row.is_active) for row in rows] == [(old_id, False), (second.json()["id"], True)]

    replay = await async_client.post(
        "/api/v1/production/printer-consumables/scan",
        json={
            "operation_id": "stage12-scan-new",
            "scan_code": "TAG-RED-002",
            "material": "PLA",
            "color_hex": "FF0000",
            "virtual_printer_id": virtual.id,
        },
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == second.json()["id"]
    assert replay.json()["replayed"] is True
    assert len((await async_client.get("/api/v1/production/printer-consumables")).json()) == 1


async def test_wrong_direct_feed_colour_does_not_match_required_colour(
    async_client: AsyncClient, db_session: AsyncSession
):
    virtual = await _virtual(db_session, "C")
    response = await async_client.post(
        "/api/v1/production/printer-consumables/scan",
        json={
            "operation_id": "stage12-scan-blue",
            "scan_code": "TAG-BLUE-003",
            "material": "PLA",
            "color_hex": "0000FF",
            "virtual_printer_id": virtual.id,
        },
    )
    assert response.status_code == 201, response.text
    await db_session.refresh(virtual)
    match = match_filament_requirements(
        [{"slot": 254, "material": "PLA", "color": "FF0000"}],
        capabilities_from_rows(
            supported_materials=virtual.supported_materials,
            supported_colors=virtual.supported_colors,
            loaded_filaments=virtual.loaded_filaments,
        ),
    )
    assert match.matched is False
    assert match.reason == "filament_color_mismatch"


async def test_real_printer_binding_uses_same_direct_feed_contract(
    async_client: AsyncClient, db_session: AsyncSession
):
    printer = Printer(name="Stage 12 real placeholder", serial_number="ST12-REAL-001", ip_address="127.0.0.2", access_code="12345678", model="A1")
    db_session.add(printer)
    await db_session.commit()
    await db_session.refresh(printer)
    response = await async_client.post(
        "/api/v1/production/printer-consumables/scan",
        json={
            "operation_id": "stage12-scan-real-placeholder",
            "scan_code": "TAG-REAL-001",
            "material": "PETG",
            "color_hex": "FFFFFF",
            "printer_id": printer.id,
        },
    )
    assert response.status_code == 201, response.text
    await db_session.refresh(printer)
    assert printer.loaded_filaments[0]["slot"] == 254
    assert response.json()["printer_name"] == "Stage 12 real placeholder"
