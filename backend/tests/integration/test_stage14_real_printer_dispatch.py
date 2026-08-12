"""Stage 14 controlled real-printer hand-off tests.

The tests replace the live connection predicate; they never open MQTT/FTP or
send anything to a physical printer.
"""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.library import LibraryFile
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product import Product
from backend.app.models.product_file import ProductFile
from backend.app.models.production import PlateJob, ProductionOrder, ProductionRequirement
from backend.app.models.slice_artifact import SliceArtifact
from backend.app.models.virtual_printer import VirtualPrinter


async def _real_slice_fixture(db: AsyncSession, tmp_path: Path):
    output_path = tmp_path / "stage14-output.gcode.3mf"
    output_path.write_bytes(b"stage14-output")
    source = LibraryFile(
        filename="stage14-source.3mf",
        file_path=str(tmp_path / "stage14-source.3mf"),
        file_type="3mf",
        file_size=1,
        file_hash="a" * 64,
    )
    output = LibraryFile(
        filename=output_path.name,
        file_path=str(output_path),
        file_type="gcode.3mf",
        file_size=output_path.stat().st_size,
        file_hash="b" * 64,
    )
    product = Product(sku="STAGE14-REAL", name="Stage 14 real printer")
    printer = Printer(
        name="Stage 14 controlled printer",
        serial_number="STAGE14SERIAL",
        ip_address="192.168.1.99",
        access_code="12345678",
        model="A1",
    )
    db.add_all([source, output, product, printer])
    await db.commit()
    product_file = ProductFile(product_id=product.id, library_file_id=source.id, name="stage14-source.3mf")
    order = ProductionOrder(order_number="STAGE14-ORDER", product_id=product.id, quantity=1, status="planned")
    db.add_all([product_file, order])
    await db.commit()
    requirement = ProductionRequirement(order_id=order.id, required_quantity=1, unit_quantity=1)
    db.add(requirement)
    await db.commit()
    old_queue = PrintQueueItem(printer_id=printer.id, library_file_id=source.id, status="pending", manual_start=True)
    db.add(old_queue)
    await db.commit()
    job = PlateJob(requirement_id=requirement.id, queue_item_id=old_queue.id, planned_quantity=1, status="assigned")
    db.add(job)
    await db.commit()
    artifact = SliceArtifact(
        source_product_file_id=product_file.id,
        source_library_file_id=source.id,
        output_library_file_id=output.id,
        source_sha256="c" * 64,
        source_version=1,
        strategy="fixed_plate",
        settings_fingerprint="d" * 64,
        arranged_by_slicer=False,
        output_sha256="b" * 64,
    )
    db.add(artifact)
    await db.commit()
    job.slice_result = {"real_slice": True, "slice_artifact_id": artifact.id}
    await db.commit()
    return printer, artifact, job, old_queue


async def test_real_dispatch_requires_confirmation_and_replaces_stage9_hold(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch,
):
    printer, artifact, job, old_queue = await _real_slice_fixture(db_session, tmp_path)

    monkeypatch.setattr(
        "backend.app.services.production_real_dispatch.printer_manager.is_connected",
        lambda printer_id: printer_id == printer.id,
    )

    async def available(_db, target_type, target_id):
        return target_type == "printer" and target_id == printer.id

    monkeypatch.setattr("backend.app.services.production_real_dispatch.availability", available)

    rejected = await async_client.post(
        f"/api/v1/production/slice-artifacts/{artifact.id}/dispatch",
        json={"operation_id": "stage14-no-confirm", "printer_id": printer.id, "confirm": False},
    )
    assert rejected.status_code == 409, rejected.text

    sent = await async_client.post(
        f"/api/v1/production/slice-artifacts/{artifact.id}/dispatch",
        json={"operation_id": "stage14-confirmed", "printer_id": printer.id, "confirm": True},
    )
    assert sent.status_code == 200, sent.text
    body = sent.json()
    assert body["printer_id"] == printer.id
    assert body["plate_job_id"] == job.id
    assert body["manual_confirmation"] is True
    assert body["transport"] == "existing_bambuddy_queue"

    await db_session.refresh(old_queue)
    await db_session.refresh(job)
    new_queue = await db_session.get(PrintQueueItem, body["queue_item_id"])
    assert old_queue.status == "cancelled"
    assert new_queue is not None
    assert new_queue.library_file_id == artifact.output_library_file_id
    assert new_queue.manual_start is False
    assert job.queue_item_id == new_queue.id
    assert job.status == "ready"

    replay = await async_client.post(
        f"/api/v1/production/slice-artifacts/{artifact.id}/dispatch",
        json={"operation_id": "stage14-confirmed", "printer_id": printer.id, "confirm": True},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["queue_item_id"] == new_queue.id


async def test_real_completion_enters_quality_then_allows_manual_accounting(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
):
    from backend.app.services.production_real_dispatch import mark_real_job_finished, mark_real_job_started

    printer, _artifact, job, _old_queue = await _real_slice_fixture(db_session, tmp_path)
    queue = await db_session.get(PrintQueueItem, job.queue_item_id)
    assert queue is not None
    queue.status = "printing"
    job.status = "ready"
    await db_session.commit()

    assert await mark_real_job_started(db_session, printer.id) == job.id
    await db_session.refresh(job)
    assert job.status == "printing"

    queue.status = "completed"
    await db_session.commit()
    assert await mark_real_job_finished(db_session, queue.id, "completed") == job.id
    await db_session.refresh(job)
    assert job.status == "waiting_cleanup"
    assert job.machine_result == "completed"

    quality = await async_client.post(
        f"/api/v1/production/plate-jobs/{job.id}/workflow/quality",
        json={"operation_id": "stage14-quality", "good_quantity": 1},
    )
    assert quality.status_code == 200, quality.text
    cleanup = await async_client.post(
        f"/api/v1/production/plate-jobs/{job.id}/workflow/cleanup",
        json={"operation_id": "stage14-cleanup"},
    )
    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["status"] == "completed"


async def test_real_printer_is_preferred_over_matching_virtual_test_printer(
    db_session: AsyncSession,
    tmp_path: Path,
):
    """A Stage 11 virtual printer must only be a fallback once real hardware exists."""

    from backend.app.services.production_eligibility import find_assignment

    printer, _artifact, job, held_queue = await _real_slice_fixture(db_session, tmp_path)
    profile = PrinterProfile(
        code="STAGE14-A1",
        name="Stage 14 A1 profile",
        printer_model="A1",
        nozzle_diameter=0.4,
        auto_production_enabled=True,
    )
    virtual = VirtualPrinter(
        name="Stage 11 virtual fallback",
        enabled=True,
        model="N2S",
        units_per_plate_capacity=1,
    )
    db_session.add_all([profile, virtual])
    held_queue.status = "cancelled"
    await db_session.commit()

    requirement = await db_session.get(ProductionRequirement, job.requirement_id)
    assert requirement is not None
    job.printer_profile_id = profile.id
    job.status = "draft"
    requirement.recipe_snapshot = {
        "printer_profile_id": profile.id,
        "product_file_snapshot": {
            "compatible_printer_models": ["A1"],
            "filament_requirements": [],
            "units_per_plate": 1,
        },
    }
    await db_session.commit()

    assignment = await find_assignment(db_session, job)

    assert assignment is not None
    assert assignment.printer is not None
    assert assignment.printer.id == printer.id
    assert assignment.virtual_printer is None
