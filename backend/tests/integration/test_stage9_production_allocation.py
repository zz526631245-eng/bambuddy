"""Stage 9 automatic production allocation safety tests.

Stage 9 may create and assign existing queue rows, but every production queue
item remains held for software-only validation.  No route or scheduler path may
send a print command before the later real-printer acceptance stage.
"""

from __future__ import annotations

import re
from unittest.mock import patch

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.library import LibraryFile
from backend.app.models.operation_log import OperationLog
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.production import PlateJob, ProductionRequirement
from backend.app.services.print_scheduler import scheduler
from backend.app.services.production_allocator import allocate_plate_jobs


async def _library_file(db: AsyncSession, suffix: str) -> LibraryFile:
    row = LibraryFile(
        filename=f"stage9-{suffix}.3mf",
        file_path=f"library/stage9-{suffix}.3mf",
        file_type="3mf",
        file_size=128,
        file_hash=(suffix.lower() * 64)[:64],
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _master_data(client: AsyncClient, db: AsyncSession, suffix: str, *, location: str = "A") -> dict:
    library_file = await _library_file(db, suffix)
    product = (
        await client.post(
            "/api/v1/products",
            json={"sku": f"STAGE9-{suffix}", "name": f"阶段9产品{suffix}"},
        )
    ).json()
    component = (
        await client.post(
            "/api/v1/products/components",
            json={"code": f"PART9-{suffix}", "name": f"自动分配零件{suffix}", "unit": "个"},
        )
    ).json()
    bom = await client.post(
        f"/api/v1/products/{product['id']}/bom",
        json={"component_id": component["id"], "quantity": 1},
    )
    assert bom.status_code == 201, bom.text
    profile = (
        await client.post(
            "/api/v1/production/printer-profiles",
            json={
                "code": f"AUTO9-{suffix}",
                "name": f"自动生产配置{suffix}",
                "printer_model": "X1C",
                "nozzle_diameter": 0.4,
                "location": location,
                "auto_production_enabled": True,
            },
        )
    ).json()
    recipe_response = await client.post(
        "/api/v1/production/recipes",
        json={
            "code": f"AUTO-PLAN9-{suffix}",
            "name": f"自动分配方案{suffix}",
            "product_id": product["id"],
            "component_id": component["id"],
            "printer_profile_id": profile["id"],
            "compatible_profile_ids": [profile["id"]],
            "library_file_id": library_file.id,
            "version": 1,
        },
    )
    assert recipe_response.status_code == 201, recipe_response.text
    source_response = await client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": (f"stage9-{suffix}.3mf", b"PK\\x03\\x04stage9-source", "application/octet-stream")},
        data={"strategy": "fixed_plate", "units_per_plate": "1", "component_ids": "[]", "compatible_printer_models": "[\"X1C\"]", "filament_requirements": "[]"},
    )
    assert source_response.status_code == 201, source_response.text
    return {
        "product": product,
        "component": component,
        "profile": profile,
        "recipe": recipe_response.json(),
        "library_file": library_file,
        "source_file": source_response.json(),
    }


async def _confirm_one_job(client: AsyncClient, master: dict, suffix: str) -> dict:
    if not master.get("source_file"):
        source_response = await client.post(
            f"/api/v1/products/{master['product']['id']}/files",
            files={"file": (f"stage9-{suffix}.3mf", b"PK\\x03\\x04stage9-source", "application/octet-stream")},
            data={"strategy": "fixed_plate", "units_per_plate": "1", "component_ids": "[]", "compatible_printer_models": "[\"P1S\",\"X1C\"]", "filament_requirements": "[]"},
        )
        assert source_response.status_code == 201, source_response.text
    order_response = await client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": f"stage9-create-{suffix}",
            "order_number": f"STAGE9-ORDER-{suffix}",
            "product_id": master["product"]["id"],
            "quantity": 1,
        },
    )
    assert order_response.status_code == 201, order_response.text
    order = order_response.json()
    preview = await client.get(f"/api/v1/production/orders/{order['id']}/plate-jobs/preview")
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(
        f"/api/v1/production/orders/{order['id']}/plate-jobs/confirm",
        json={"operation_id": f"stage9-confirm-{suffix}", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()["items"][0]


async def test_confirmed_job_is_automatically_assigned_to_existing_queue_but_never_dispatched(
    async_client: AsyncClient,
    db_session: AsyncSession,
    printer_factory,
):
    printer = await printer_factory(name="模拟 X1C A", model="X1C", location="A")
    printer_id = printer.id
    master = await _master_data(async_client, db_session, "AUTO", location="A")
    library_file_id = master["source_file"]["library_file_id"]

    with patch("backend.app.services.printer_manager.PrinterManager.start_print") as start_print:
        job_payload = await _confirm_one_job(async_client, master, "AUTO")

    db_session.expire_all()
    job = await db_session.get(PlateJob, job_payload["id"])
    assert job is not None
    assert job.status == "assigned"
    assert job.queue_item_id is not None

    queue_item = (
        await db_session.execute(
            select(PrintQueueItem)
            .where(PrintQueueItem.id == job.queue_item_id)
            .options(selectinload(PrintQueueItem.production_plate_job))
        )
    ).scalar_one()
    assert queue_item is not None
    assert queue_item.printer_id == printer_id
    assert queue_item.library_file_id == library_file_id
    assert queue_item.status == "pending"
    assert queue_item.manual_start is True
    assert queue_item.production_plate_job.id == job.id
    start_print.assert_not_called()

    queue_response = await async_client.get(f"/api/v1/queue/{queue_item.id}")
    assert queue_response.status_code == 200
    assert queue_response.json()["source_type"] == "production"
    assert queue_response.json()["production_plate_job_id"] == job.id
    allocation_log = (
        await db_session.execute(
            select(OperationLog).where(OperationLog.operation_type == "production_plate_job_allocated")
        )
    ).scalar_one()
    assert allocation_log.payload["queue_item_id"] == queue_item.id
    assert allocation_log.payload["printer_id"] == printer_id

    blocked = await async_client.post(f"/api/v1/queue/{queue_item.id}/start")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "production_dispatch_blocked"
    for mutation in (
        async_client.patch(f"/api/v1/queue/{queue_item.id}", json={"manual_start": False}),
        async_client.post(f"/api/v1/queue/{queue_item.id}/cancel"),
        async_client.delete(f"/api/v1/queue/{queue_item.id}"),
    ):
        response = await mutation
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "production_queue_managed_by_order"

    with patch("backend.app.services.print_scheduler.printer_manager.start_print") as scheduler_start:
        await scheduler._start_print(db_session, queue_item)
    scheduler_start.assert_not_called()
    await db_session.refresh(queue_item)
    assert queue_item.manual_start is True


async def test_allocator_never_double_assigns_one_printer(
    async_client: AsyncClient,
    db_session: AsyncSession,
    printer_factory,
):
    printer = await printer_factory(name="唯一模拟 X1C", model="X1C", location="LOCK")
    printer_id = printer.id
    first_master = await _master_data(async_client, db_session, "LOCK1", location="LOCK")
    second_master = await _master_data(async_client, db_session, "LOCK2", location="LOCK")

    first = await _confirm_one_job(async_client, first_master, "LOCK1")
    second = await _confirm_one_job(async_client, second_master, "LOCK2")

    db_session.expire_all()
    first_job = await db_session.get(PlateJob, first["id"])
    second_job = await db_session.get(PlateJob, second["id"])
    assert first_job is not None and first_job.status == "assigned"
    assert second_job is not None and second_job.status == "draft"
    assert second_job.queue_item_id is None

    queue_count = (
        await db_session.execute(
            select(func.count(PrintQueueItem.id)).where(
                PrintQueueItem.printer_id == printer_id,
                PrintQueueItem.status.in_(("pending", "printing")),
            )
        )
    ).scalar_one()
    assert queue_count == 1


async def test_cancelled_assignment_releases_queue_and_recovery_allocates_waiting_job(
    async_client: AsyncClient,
    db_session: AsyncSession,
    printer_factory,
):
    await printer_factory(name="恢复测试 X1C", model="X1C", location="RECOVER")
    first_master = await _master_data(async_client, db_session, "RECOVER1", location="RECOVER")
    second_master = await _master_data(async_client, db_session, "RECOVER2", location="RECOVER")
    first = await _confirm_one_job(async_client, first_master, "RECOVER1")
    second = await _confirm_one_job(async_client, second_master, "RECOVER2")

    first_order_id = (
        await db_session.execute(
            select(ProductionRequirement.order_id)
            .join(PlateJob, PlateJob.requirement_id == ProductionRequirement.id)
            .where(PlateJob.id == first["id"])
        )
    ).scalar_one()
    cancelled = await async_client.post(
        f"/api/v1/production/orders/{first_order_id}/cancel",
        json={"operation_id": "stage9-cancel-recover1"},
    )
    assert cancelled.status_code == 200, cancelled.text

    first_job = await db_session.get(PlateJob, first["id"])
    assert first_job is not None and first_job.queue_item_id is not None
    first_queue = await db_session.get(PrintQueueItem, first_job.queue_item_id)
    assert first_queue is not None and first_queue.status == "cancelled"

    allocated = await allocate_plate_jobs(db_session, plate_job_ids=[second["id"]])
    assert [job.id for job in allocated] == [second["id"]]
    second_job = await db_session.get(PlateJob, second["id"])
    assert second_job is not None and second_job.status == "assigned"
    assert second_job.queue_item_id is not None


async def test_unmatched_draft_is_recovered_when_a_compatible_printer_appears(
    async_client: AsyncClient,
    db_session: AsyncSession,
    printer_factory,
):
    master = await _master_data(async_client, db_session, "RESTART", location="LATER")
    payload = await _confirm_one_job(async_client, master, "RESTART")
    draft = await db_session.get(PlateJob, payload["id"])
    assert draft is not None and draft.status == "draft"
    assert draft.queue_item_id is None

    await printer_factory(name="后加入的模拟 X1C", model="X1C", location="LATER")
    allocated = await allocate_plate_jobs(db_session, plate_job_ids=[draft.id])
    assert [job.id for job in allocated] == [draft.id]
    await db_session.refresh(draft)
    assert draft.status == "assigned"
    assert draft.queue_item_id is not None


async def test_allocator_falls_back_to_another_frozen_compatible_profile(
    async_client: AsyncClient,
    db_session: AsyncSession,
    printer_factory,
):
    library_file = await _library_file(db_session, "FALLBACK")
    product = (
        await async_client.post(
            "/api/v1/products",
            json={"sku": "STAGE9-FALLBACK", "name": "兼容配置产品"},
        )
    ).json()
    component = (
        await async_client.post(
            "/api/v1/products/components",
            json={"code": "PART9-FALLBACK", "name": "兼容配置零件", "unit": "个"},
        )
    ).json()
    assert (
        await async_client.post(
            f"/api/v1/products/{product['id']}/bom",
            json={"component_id": component["id"], "quantity": 1},
        )
    ).status_code == 201

    primary = (
        await async_client.post(
            "/api/v1/production/printer-profiles",
            json={
                "code": "AUTO9-PRIMARY",
                "name": "无可用机器的首选配置",
                "printer_model": "X1C",
                "nozzle_diameter": 0.4,
                "auto_production_enabled": True,
            },
        )
    ).json()
    fallback = (
        await async_client.post(
            "/api/v1/production/printer-profiles",
            json={
                "code": "AUTO9-FALLBACK",
                "name": "有可用机器的兼容配置",
                "printer_model": "P1S",
                "nozzle_diameter": 0.4,
                "location": "FALLBACK",
                "auto_production_enabled": True,
            },
        )
    ).json()
    printer = await printer_factory(name="模拟 P1S", model="P1S", location="FALLBACK")
    recipe = await async_client.post(
        "/api/v1/production/recipes",
        json={
            "code": "AUTO-PLAN9-FALLBACK",
            "name": "多配置方案",
            "product_id": product["id"],
            "component_id": component["id"],
            "printer_profile_id": primary["id"],
            "compatible_profile_ids": [fallback["id"]],
            "library_file_id": library_file.id,
            "version": 1,
        },
    )
    assert recipe.status_code == 201, recipe.text

    master = {"product": product}
    payload = await _confirm_one_job(async_client, master, "FALLBACK")
    job = await db_session.get(PlateJob, payload["id"])
    assert job is not None
    assert job.status == "assigned"
    assert job.printer_profile_id == fallback["id"]
    queue_item = await db_session.get(PrintQueueItem, job.queue_item_id)
    assert queue_item is not None and queue_item.printer_id == printer.id


async def test_product_summary_keeps_completed_and_pending_quantities_separate(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    master = await _master_data(async_client, db_session, "SUMMARY")
    product_id = master["product"]["id"]
    first = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-summary-first", "order_number": "STAGE9-SUMMARY-FIRST", "product_id": product_id, "quantity": 3},
    )
    second = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-summary-second", "order_number": "STAGE9-SUMMARY-SECOND", "product_id": product_id, "quantity": 5},
    )
    assert first.status_code == 201 and second.status_code == 201
    requirement = (
        await db_session.execute(
            select(ProductionRequirement).where(ProductionRequirement.order_id == first.json()["id"])
        )
    ).scalar_one()
    requirement.good_quantity = 3
    await db_session.commit()

    response = await async_client.get("/api/v1/production/product-summaries")
    assert response.status_code == 200, response.text
    summary = next(item for item in response.json() if item["product_id"] == product_id)
    assert summary == {"product_id": product_id, "total_quantity": 8, "completed_quantity": 3, "pending_quantity": 5}


async def test_order_number_is_generated_when_not_supplied(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    master = await _master_data(async_client, db_session, "AUTO-NUMBER")
    response = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-auto-number", "product_id": master["product"]["id"], "quantity": 2},
    )
    assert response.status_code == 201, response.text
    assert re.fullmatch(r"PO-\d{8}-\d{3}", response.json()["order_number"])
