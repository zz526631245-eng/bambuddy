"""Stage 11 virtual production, quality accounting and cleanup workflow."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.library import LibraryFile
from backend.app.models.production import PlateJob
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.services.production_allocator import allocate_plate_jobs


async def _assigned_virtual_job(
    client: AsyncClient,
    db: AsyncSession,
    suffix: str,
    *,
    quantity: int = 3,
    create_virtual: bool = True,
    expect_assigned: bool = True,
) -> tuple[int, int, int]:
    library = LibraryFile(
        filename=f"stage11-{suffix}.3mf",
        file_path=f"library/stage11-{suffix}.3mf",
        file_type="3mf",
        file_size=128,
        file_hash=(suffix.lower() * 64)[:64],
    )
    db.add(library)
    if create_virtual:
        virtual = VirtualPrinter(
            name=f"阶段11虚拟打印机-{suffix}",
            enabled=True,
            model="N2S",
            units_per_plate_capacity=20,
            supported_materials=["PLA"],
            supported_colors=["FF0000"],
            loaded_filaments=[{"slot": 0, "material": "PLA", "color": "FF0000"}],
        )
        db.add(virtual)
    else:
        virtual = (await db.execute(select(VirtualPrinter).order_by(VirtualPrinter.id))).scalars().first()
        assert virtual is not None
    await db.commit()
    await db.refresh(library)
    await db.refresh(virtual)

    product = (
        await client.post(
            "/api/v1/products",
            json={"sku": f"STAGE11-{suffix}", "name": f"阶段11产品{suffix}"},
        )
    ).json()
    profile_response = await client.post(
        "/api/v1/production/printer-profiles",
        json={
            "code": f"STAGE11-A1-{suffix}",
            "name": f"阶段11 A1 配置{suffix}",
            "printer_model": "A1",
            "nozzle_diameter": 0.4,
            "auto_production_enabled": True,
            "supported_materials": ["PLA"],
            "supported_colors": ["FF0000"],
        },
    )
    assert profile_response.status_code == 201, profile_response.text
    profile = profile_response.json()
    recipe_response = await client.post(
        "/api/v1/production/recipes",
        json={
            "code": f"STAGE11-PLAN-{suffix}",
            "name": f"阶段11打印方案{suffix}",
            "product_id": product["id"],
            "printer_profile_id": profile["id"],
            "compatible_profile_ids": [profile["id"]],
            "library_file_id": library.id,
        },
    )
    assert recipe_response.status_code == 201, recipe_response.text
    source_response = await client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": (f"stage11-{suffix}.3mf", b"PK\\x03\\x04stage11", "application/octet-stream")},
        data={
            "strategy": "fixed_plate",
            "units_per_plate": "1",
            "compatible_printer_models": '["A1"]',
            "filament_requirements": '[{"slot":0,"material":"PLA","color":"FF0000"}]',
        },
    )
    assert source_response.status_code == 201, source_response.text
    order_response = await client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": f"stage11-create-{suffix}",
            "product_id": product["id"],
            "quantity": quantity,
        },
    )
    assert order_response.status_code == 201, order_response.text
    order_id = order_response.json()["id"]
    preview = await client.get(f"/api/v1/production/orders/{order_id}/plate-jobs/preview")
    confirmed = await client.post(
        f"/api/v1/production/orders/{order_id}/plate-jobs/confirm",
        json={"operation_id": f"stage11-confirm-{suffix}", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    job = confirmed.json()["items"][0]
    assert job["status"] == ("assigned" if expect_assigned else "draft")
    assert job["workflow_status"] == ("assigned" if expect_assigned else "draft")
    assert job["virtual_printer_id"] == (virtual.id if expect_assigned else None)
    return order_id, job["id"], virtual.id


async def _action(client: AsyncClient, job_id: int, action: str, operation_id: str, **extra):
    return await client.post(
        f"/api/v1/production/plate-jobs/{job_id}/workflow/{action}",
        json={"operation_id": operation_id, **extra},
    )


async def test_virtual_job_walks_through_quality_and_cleanup(async_client: AsyncClient, db_session: AsyncSession):
    order_id, job_id, _ = await _assigned_virtual_job(async_client, db_session, "FLOW", quantity=3)

    prepared = await _action(async_client, job_id, "prepare", "stage11-flow-prepare")
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["workflow_status"] == "ready"

    started = await _action(async_client, job_id, "start", "stage11-flow-start")
    assert started.status_code == 200, started.text
    assert started.json()["workflow_status"] == "printing"

    finished = await _action(
        async_client,
        job_id,
        "finish",
        "stage11-flow-finish",
        machine_result="completed",
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["workflow_status"] == "awaiting_quality"

    quality = await _action(
        async_client,
        job_id,
        "quality",
        "stage11-flow-quality",
        good_quantity=2,
    )
    assert quality.status_code == 200, quality.text
    assert quality.json()["workflow_status"] == "waiting_cleanup"
    assert quality.json()["quality_good_quantity"] == 2
    assert quality.json()["quality_scrap_quantity"] == 1

    detail = (await async_client.get(f"/api/v1/production/orders/{order_id}")).json()
    ledger = detail["requirements"][0]["ledger"]
    assert ledger == {"planned": 3, "reserved": 0, "good": 2, "scrap": 1, "remaining": 1}

    cleaned = await _action(async_client, job_id, "cleanup", "stage11-flow-cleanup")
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["workflow_status"] == "completed"
    assert cleaned.json()["cleanup_confirmed_at"] is not None


async def test_quality_is_idempotent_and_rejects_impossible_quantity(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    _, job_id, _ = await _assigned_virtual_job(async_client, db_session, "SAFE", quantity=2)
    await _action(async_client, job_id, "prepare", "stage11-safe-prepare")
    await _action(async_client, job_id, "start", "stage11-safe-start")
    await _action(async_client, job_id, "finish", "stage11-safe-finish", machine_result="failed")

    invalid = await _action(
        async_client,
        job_id,
        "quality",
        "stage11-safe-invalid",
        good_quantity=3,
    )
    assert invalid.status_code == 409

    first = await _action(
        async_client,
        job_id,
        "quality",
        "stage11-safe-quality",
        good_quantity=0,
    )
    replay = await _action(
        async_client,
        job_id,
        "quality",
        "stage11-safe-quality",
        good_quantity=0,
    )
    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.headers["x-idempotent-replay"] == "true"
    assert replay.json()["quality_scrap_quantity"] == 2

    changed = await _action(
        async_client,
        job_id,
        "quality",
        "stage11-safe-quality-changed",
        good_quantity=1,
    )
    assert changed.status_code == 409


async def test_full_quality_and_cleanup_complete_the_order(async_client: AsyncClient, db_session: AsyncSession):
    order_id, job_id, _ = await _assigned_virtual_job(async_client, db_session, "COMPLETE", quantity=2)
    await _action(async_client, job_id, "prepare", "stage11-complete-prepare")
    await _action(async_client, job_id, "start", "stage11-complete-start")
    await _action(async_client, job_id, "finish", "stage11-complete-finish", machine_result="completed")
    await _action(async_client, job_id, "quality", "stage11-complete-quality", good_quantity=2)

    before_cleanup = (await async_client.get(f"/api/v1/production/orders/{order_id}")).json()
    assert before_cleanup["status"] == "planned"
    assert before_cleanup["requirements"][0]["ledger"]["good"] == 2

    await _action(async_client, job_id, "cleanup", "stage11-complete-cleanup")
    completed = (await async_client.get(f"/api/v1/production/orders/{order_id}")).json()
    assert completed["status"] == "completed"
    assert completed["requirements"][0]["status"] == "completed"


async def test_started_work_is_protected_from_cancel_and_delete(async_client: AsyncClient, db_session: AsyncSession):
    order_id, job_id, _ = await _assigned_virtual_job(async_client, db_session, "HISTORY", quantity=1)
    await _action(async_client, job_id, "prepare", "stage11-history-prepare")
    await _action(async_client, job_id, "start", "stage11-history-start")
    await _action(async_client, job_id, "finish", "stage11-history-finish", machine_result="failed")

    cancel_job = await async_client.post(f"/api/v1/production/plate-jobs/{job_id}/cancel")
    delete_job = await async_client.delete(f"/api/v1/production/plate-jobs/{job_id}")
    cancel_order = await async_client.post(
        f"/api/v1/production/orders/{order_id}/cancel",
        json={"operation_id": "stage11-history-cancel-order"},
    )
    delete_order = await async_client.delete(f"/api/v1/production/orders/{order_id}")

    assert cancel_job.status_code == 409
    assert delete_job.status_code == 409
    assert cancel_order.status_code == 409
    assert delete_order.status_code == 409


async def test_virtual_printer_stays_busy_until_cleanup(async_client: AsyncClient, db_session: AsyncSession):
    _, first_job_id, virtual_id = await _assigned_virtual_job(async_client, db_session, "BUSY1", quantity=1)

    _, second_job_id, second_virtual_id = await _assigned_virtual_job(
        async_client,
        db_session,
        "BUSY2",
        quantity=1,
        create_virtual=False,
        expect_assigned=False,
    )
    assert second_virtual_id == virtual_id

    await _action(async_client, first_job_id, "prepare", "stage11-busy-prepare")
    await _action(async_client, first_job_id, "start", "stage11-busy-start")
    await _action(async_client, first_job_id, "finish", "stage11-busy-finish", machine_result="completed")
    await _action(async_client, first_job_id, "quality", "stage11-busy-quality", good_quantity=1)
    assert await allocate_plate_jobs(db_session, plate_job_ids=[second_job_id]) == []

    await _action(async_client, first_job_id, "cleanup", "stage11-busy-cleanup")
    allocated = await allocate_plate_jobs(db_session, plate_job_ids=[second_job_id])
    assert [row.id for row in allocated] == [second_job_id]
    second_job = await db_session.get(PlateJob, second_job_id)
    assert second_job is not None
    assert second_job.virtual_printer_id == virtual_id


async def test_multi_plate_set_is_accounted_only_after_every_source_plate_is_reviewed(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    order_id, first_job_id, virtual_id = await _assigned_virtual_job(
        async_client,
        db_session,
        "MULTI",
        quantity=1,
    )
    first = await db_session.get(PlateJob, first_job_id)
    assert first is not None
    await db_session.refresh(first, ["requirement"])
    snapshot = dict(first.requirement.recipe_snapshot or {})
    file_snapshot = dict(snapshot.get("product_file_snapshot") or {})
    file_snapshot.update({"production_mode": "multi_plate", "source_plate_count": 2})
    snapshot["product_file_snapshot"] = file_snapshot
    first.requirement.recipe_snapshot = snapshot
    first.product_set_index = 1
    first.source_plate_index = 0
    second = PlateJob(
        requirement_id=first.requirement_id,
        printer_profile_id=first.printer_profile_id,
        virtual_printer_id=virtual_id,
        planned_quantity=1,
        status="assigned",
        product_set_index=1,
        source_plate_index=1,
    )
    db_session.add(second)
    await db_session.commit()
    await db_session.refresh(second)

    await _action(async_client, first_job_id, "prepare", "stage11-multi-first-prepare")
    await _action(async_client, first_job_id, "start", "stage11-multi-first-start")
    await _action(async_client, first_job_id, "finish", "stage11-multi-first-finish", machine_result="completed")
    await _action(async_client, first_job_id, "quality", "stage11-multi-first-quality", good_quantity=1)
    await _action(async_client, first_job_id, "cleanup", "stage11-multi-first-cleanup")
    midway = (await async_client.get(f"/api/v1/production/orders/{order_id}")).json()["requirements"][0]["ledger"]
    assert midway == {"planned": 1, "reserved": 1, "good": 0, "scrap": 0, "remaining": 0}

    await _action(async_client, second.id, "prepare", "stage11-multi-second-prepare")
    await _action(async_client, second.id, "start", "stage11-multi-second-start")
    await _action(async_client, second.id, "finish", "stage11-multi-second-finish", machine_result="failed")
    await _action(async_client, second.id, "quality", "stage11-multi-second-quality", good_quantity=0)
    final = (await async_client.get(f"/api/v1/production/orders/{order_id}")).json()["requirements"][0]["ledger"]
    assert final == {"planned": 1, "reserved": 0, "good": 0, "scrap": 1, "remaining": 1}

    retry_preview = await async_client.get(f"/api/v1/production/orders/{order_id}/plate-jobs/preview")
    retry_confirm = await async_client.post(
        f"/api/v1/production/orders/{order_id}/plate-jobs/confirm",
        json={"operation_id": "stage11-multi-retry-confirm", "items": retry_preview.json()["items"]},
    )
    assert retry_confirm.status_code == 201, retry_confirm.text
    assert {row["product_set_index"] for row in retry_confirm.json()["items"]} == {2}
