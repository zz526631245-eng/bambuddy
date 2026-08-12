"""Stage 14 controlled real-printer hand-off tests.

The tests replace the live connection predicate; they never open MQTT/FTP or
send anything to a physical printer.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


async def test_long_slice_rejection_reduces_complete_sets_per_plate(
    db_session: AsyncSession,
    tmp_path: Path,
):
    """Rejecting a long plate requests a smaller complete-set repack."""

    _printer, _artifact, job, _queue = await _real_slice_fixture(db_session, tmp_path)
    job.slice_status = "succeeded"
    job.slice_time_review_status = "pending"
    job.slice_result = {"plate_quantities": [4, 2], "time_review_required": True}
    await db_session.commit()

    from backend.app.services.production_order_service import review_slice_time

    reviewed, replayed = await review_slice_time(
        db_session,
        plate_job_id=job.id,
        operation_id="stage14-time-reject",
        approve=False,
        actor_user_id=None,
    )

    assert replayed is False
    assert reviewed.max_units_per_plate == 3
    assert reviewed.slice_status == "pending"
    assert reviewed.slice_time_review_status == "not_required"
    assert reviewed.slice_result is None


async def test_real_assignment_uses_scanned_direct_feed_over_stale_virtual_profile(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch,
):
    """A legacy virtual profile must not block a matching real direct-feed spool."""

    from backend.app.services.production_eligibility import find_assignment

    printer, _artifact, job, held_queue = await _real_slice_fixture(db_session, tmp_path)
    printer.loaded_filaments = [{"slot": 254, "material": "PETG", "color": "#FFFFFF"}]
    held_queue.status = "cancelled"
    job.queue_item_id = None
    job.status = "draft"
    profile = PrinterProfile(
        code="STALE-VIRTUAL-A1",
        name="阶段11虚拟 A1 配置",
        printer_model="A1",
        nozzle_diameter=0.4,
        location="虚拟测试区",
        auto_production_enabled=True,
        supported_materials=["PLA"],
        supported_colors=["#FF0000"],
    )
    db_session.add(profile)
    await db_session.flush()
    job.printer_profile_id = profile.id
    requirement = await db_session.get(ProductionRequirement, job.requirement_id)
    assert requirement is not None
    requirement.recipe_snapshot = {
        "printer_profile_id": profile.id,
        "library_file_id": 1,
        "product_file_snapshot": {
            "compatible_printer_models": [],
            "filament_requirements": [{"slot": 0, "material": "PETG", "color": "白色"}],
        },
    }
    await db_session.commit()

    monkeypatch.setattr(
        "backend.app.services.production_printer_status.printer_manager.get_status",
        lambda _printer_id: SimpleNamespace(
            connected=True,
            state="IDLE",
            progress=0,
            remaining_time=0,
            layer_num=0,
            total_layers=0,
            gcode_file="",
            subtask_name="",
        ),
    )

    assignment = await find_assignment(db_session, job)

    assert assignment is not None
    assert assignment.printer is not None
    assert assignment.printer.id == printer.id
    assert assignment.virtual_printer is None


async def test_real_assignment_skips_printer_waiting_for_plate_clear(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch,
):
    """Automatic allocation must not bind a new plate before cleanup."""

    from backend.app.services.production_eligibility import find_assignment

    printer, _artifact, job, held_queue = await _real_slice_fixture(db_session, tmp_path)
    printer.loaded_filaments = [{"slot": 254, "material": "PETG", "color": "#FFFFFF"}]
    printer.awaiting_plate_clear = True
    held_queue.status = "cancelled"
    job.queue_item_id = None
    job.status = "draft"
    profile = PrinterProfile(
        code="WAITING-CLEAR-A1",
        name="Waiting clear A1",
        printer_model="A1",
        nozzle_diameter=0.4,
        auto_production_enabled=True,
    )
    db_session.add(profile)
    await db_session.flush()
    requirement = await db_session.get(ProductionRequirement, job.requirement_id)
    assert requirement is not None
    job.printer_profile_id = profile.id
    requirement.recipe_snapshot = {
        "printer_profile_id": profile.id,
        "library_file_id": 1,
        "product_file_snapshot": {
            "compatible_printer_models": [],
            "filament_requirements": [{"slot": 0, "material": "PETG", "color": "白色"}],
        },
    }
    await db_session.commit()

    monkeypatch.setattr(
        "backend.app.services.production_printer_status.printer_manager.get_status",
        lambda _printer_id: SimpleNamespace(
            connected=True,
            state="IDLE",
            progress=0,
            remaining_time=0,
            layer_num=0,
            total_layers=0,
            gcode_file="",
            subtask_name="",
        ),
    )

    assignment = await find_assignment(db_session, job)

    assert assignment is None


async def test_confirmed_real_job_runs_real_slice_instead_of_virtual_slice(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch,
):
    """Confirmation must select the real-slice adapter for a real assignment."""

    printer, _artifact, old_job, held_queue = await _real_slice_fixture(db_session, tmp_path)
    printer.loaded_filaments = [{"slot": 254, "material": "PETG", "color": "#FFFFFF"}]
    held_queue.status = "cancelled"
    profile = PrinterProfile(
        code="REAL-CONFIRM-A1",
        name="真实生产 A1",
        printer_model="A1",
        nozzle_diameter=0.4,
        location="虚拟测试区",
        auto_production_enabled=True,
        supported_materials=["PLA"],
        supported_colors=["#FF0000"],
    )
    db_session.add(profile)
    await db_session.flush()
    requirement = await db_session.get(ProductionRequirement, old_job.requirement_id)
    assert requirement is not None
    requirement.recipe_snapshot = {
        "printer_profile_id": profile.id,
        "library_file_id": 1,
        "product_file_snapshot": {
            "library_file_id": 1,
            "strategy": "fixed_plate",
            "units_per_plate": 1,
            "compatible_printer_models": [],
            "filament_requirements": [{"slot": 0, "material": "PETG", "color": "白色"}],
        },
    }
    await db_session.commit()
    old_job.status = "completed"
    await db_session.commit()

    sliced_ids: list[int] = []

    async def fake_real_slice(db: AsyncSession, plate_job_id: int, **_kwargs):
        job = await db.get(PlateJob, plate_job_id)
        assert job is not None
        sliced_ids.append(plate_job_id)
        job.slice_status = "succeeded"
        job.slice_result = {"real_slice": True, "simulation_only": False}
        await db.commit()
        await db.refresh(job)
        return job

    monkeypatch.setattr("backend.app.api.routes.production.slice_plate_job_real", fake_real_slice)

    preview = await async_client.get(f"/api/v1/production/orders/{requirement.order_id}/plate-jobs/preview")
    assert preview.status_code == 200, preview.text
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{requirement.order_id}/plate-jobs/confirm",
        json={"operation_id": "real-confirmation-flow", "items": preview.json()["items"]},
    )

    assert confirmed.status_code == 201, confirmed.text
    job = confirmed.json()["items"][0]
    assert job["virtual_printer_id"] is None
    assert job["queue_item_id"] is not None
    assert job["slice_status"] == "succeeded"
    assert job["slice_result"]["real_slice"] is True
    assert sliced_ids == [job["id"]]


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


async def test_real_dispatch_rejects_printer_waiting_for_plate_clear(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch,
):
    """A completed printer cannot accept a new real dispatch before cleanup."""

    printer, artifact, _job, old_queue = await _real_slice_fixture(db_session, tmp_path)
    printer.awaiting_plate_clear = True
    await db_session.commit()

    monkeypatch.setattr(
        "backend.app.services.production_real_dispatch.printer_manager.is_connected",
        lambda printer_id: printer_id == printer.id,
    )
    monkeypatch.setattr(
        "backend.app.services.production_real_dispatch.printer_manager.is_awaiting_plate_clear",
        lambda printer_id: printer_id == printer.id,
    )

    async def available(_db, target_type, target_id):
        return target_type == "printer" and target_id == printer.id

    monkeypatch.setattr("backend.app.services.production_real_dispatch.availability", available)

    rejected = await async_client.post(
        f"/api/v1/production/slice-artifacts/{artifact.id}/dispatch",
        json={"operation_id": "stage14-awaiting-clear", "printer_id": printer.id, "confirm": True},
    )
    assert rejected.status_code == 409, rejected.text
    assert "plate" in rejected.text.lower() or "清理" in rejected.text

    await db_session.refresh(old_queue)
    assert old_queue.status == "pending"


async def test_auto_dispatch_replaces_held_queue_after_real_slice(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch,
):
    from backend.app.services.production_real_dispatch import auto_dispatch_real_slice_job

    printer, artifact, job, old_queue = await _real_slice_fixture(db_session, tmp_path)
    monkeypatch.setattr(
        "backend.app.services.production_real_dispatch.printer_manager.is_connected",
        lambda printer_id: printer_id == printer.id,
    )

    async def available(_db, target_type, target_id):
        return target_type == "printer" and target_id == printer.id

    monkeypatch.setattr("backend.app.services.production_real_dispatch.availability", available)
    job.slice_status = "succeeded"
    job.slice_result = {"real_slice": True, "slice_artifact_id": artifact.id, "plates": [{"slice_artifact_id": artifact.id}]}
    await db_session.commit()

    result = await auto_dispatch_real_slice_job(db_session, job)

    assert result is not None
    new_queue = await db_session.get(PrintQueueItem, result["queue_item_id"])
    await db_session.refresh(old_queue)
    await db_session.refresh(job)
    assert old_queue.status == "cancelled"
    assert new_queue is not None
    assert new_queue.library_file_id == artifact.output_library_file_id
    assert new_queue.manual_start is False
    assert job.status == "ready"
    assert result["manual_confirmation"] is False


async def test_real_completion_enters_quality_then_allows_manual_accounting(
    async_client: AsyncClient,
    db_session: AsyncSession,
    tmp_path: Path,
):
    from backend.app.services.printer_manager import printer_manager
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
    # The production-order confirmation must release the same shared gate
    # used by the printer page and the QR scanner.
    printer_manager.set_awaiting_plate_clear(printer.id, True)
    assert printer_manager.is_awaiting_plate_clear(printer.id)
    pending_targets = await async_client.get("/api/v1/production/printer-consumables/targets")
    assert pending_targets.status_code == 200, pending_targets.text
    pending_target = next(item for item in pending_targets.json() if item["id"] == printer.id and item["kind"] == "printer")
    assert pending_target["awaiting_plate_clear"] is True
    cleanup = await async_client.post(
        f"/api/v1/production/plate-jobs/{job.id}/workflow/cleanup",
        json={"operation_id": "stage14-cleanup"},
    )
    assert cleanup.status_code == 200, cleanup.text
    assert cleanup.json()["status"] == "completed"
    assert not printer_manager.is_awaiting_plate_clear(printer.id)

    targets = await async_client.get("/api/v1/production/printer-consumables/targets")
    assert targets.status_code == 200, targets.text
    target = next(item for item in targets.json() if item["id"] == printer.id and item["kind"] == "printer")
    assert target["awaiting_plate_clear"] is False


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
