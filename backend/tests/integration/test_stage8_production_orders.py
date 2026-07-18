"""Stage 8 production-order workflow tests.

These tests intentionally assert that no queue item or printer communication is
created.  Stage 8 ends at manually confirmed *draft* plate jobs.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _master_data(client: AsyncClient, suffix: str = "A") -> dict:
    product = (
        await client.post(
            "/api/v1/products",
            json={"sku": f"STAGE8-{suffix}", "name": f"阶段8产品{suffix}"},
        )
    ).json()
    component = (
        await client.post(
            "/api/v1/products/components",
            json={"code": f"PART-{suffix}", "name": f"打印零件{suffix}", "unit": "个"},
        )
    ).json()
    bom_response = await client.post(
        f"/api/v1/products/{product['id']}/bom",
        json={"component_id": component["id"], "quantity": 2},
    )
    assert bom_response.status_code == 201
    profile = (
        await client.post(
            "/api/v1/production/printer-profiles",
            json={
                "code": f"X1C-{suffix}",
                "name": f"X1C测试配置{suffix}",
                "printer_model": "X1C",
                "nozzle_diameter": 0.4,
            },
        )
    ).json()
    recipe_response = await client.post(
        "/api/v1/production/recipes",
        json={
            "code": f"PLAN-{suffix}",
            "name": f"打印方案{suffix}",
            "product_id": product["id"],
            "component_id": component["id"],
            "printer_profile_id": profile["id"],
            "version": 1,
        },
    )
    assert recipe_response.status_code == 201
    return {
        "product": product,
        "component": component,
        "profile": profile,
        "recipe": recipe_response.json(),
    }


async def _create_order(client: AsyncClient, master: dict, suffix: str = "A", quantity: int = 5):
    return await client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": f"create-order-{suffix}",
            "order_number": f"ORDER-{suffix}",
            "product_id": master["product"]["id"],
            "quantity": quantity,
            "priority": 3,
        },
    )


async def test_order_creation_splits_bom_and_freezes_snapshots(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    master = await _master_data(async_client, "SNAP")
    response = await _create_order(async_client, master, "SNAP", quantity=5)
    assert response.status_code == 201, response.text
    order = response.json()
    assert order["status"] == "planned"
    assert order["product_snapshot"]["sku"] == "STAGE8-SNAP"
    assert order["bom_snapshot"][0]["quantity"] == 2
    assert order["recipe_snapshot"][0]["code"] == "PLAN-SNAP"

    detail = (await async_client.get(f"/api/v1/production/orders/{order['id']}")).json()
    assert len(detail["requirements"]) == 1
    requirement = detail["requirements"][0]
    assert requirement["required_quantity"] == 10
    assert requirement["ledger"] == {
        "planned": 10,
        "reserved": 0,
        "good": 0,
        "scrap": 0,
        "remaining": 10,
    }

    await db_session.execute(
        text("UPDATE products SET name = '后来修改的名称' WHERE id = :id"),
        {"id": master["product"]["id"]},
    )
    await db_session.execute(
        text("UPDATE production_bom_items SET quantity = 99 WHERE product_id = :id"),
        {"id": master["product"]["id"]},
    )
    await db_session.execute(
        text("UPDATE production_recipes SET name = '后来修改的方案' WHERE id = :id"),
        {"id": master["recipe"]["id"]},
    )
    await db_session.commit()

    unchanged = (await async_client.get(f"/api/v1/production/orders/{order['id']}")).json()
    assert unchanged["product_snapshot"]["name"] == "阶段8产品SNAP"
    assert unchanged["bom_snapshot"][0]["quantity"] == 2
    assert unchanged["recipe_snapshot"][0]["name"] == "打印方案SNAP"


async def test_create_order_operation_id_replay_returns_same_order(async_client: AsyncClient):
    master = await _master_data(async_client, "REPLAY")
    first = await _create_order(async_client, master, "REPLAY")
    second = await _create_order(async_client, master, "REPLAY")
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len((await async_client.get("/api/v1/production/orders")).json()) == 1


async def test_plate_job_preview_is_read_only_and_confirm_is_idempotent(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    master = await _master_data(async_client, "JOBS")
    order = (await _create_order(async_client, master, "JOBS", quantity=4)).json()

    preview = await async_client.get(f"/api/v1/production/orders/{order['id']}/plate-jobs/preview")
    assert preview.status_code == 200
    assert preview.json()["items"][0]["planned_quantity"] == 8
    assert (await async_client.get("/api/v1/production/plate-jobs")).json() == []

    payload = {"operation_id": "confirm-jobs-1", "items": preview.json()["items"]}
    first = await async_client.post(
        f"/api/v1/production/orders/{order['id']}/plate-jobs/confirm",
        json=payload,
    )
    second = await async_client.post(
        f"/api/v1/production/orders/{order['id']}/plate-jobs/confirm",
        json=payload,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 200
    assert [item["id"] for item in second.json()["items"]] == [item["id"] for item in first.json()["items"]]

    detail = (await async_client.get(f"/api/v1/production/orders/{order['id']}")).json()
    assert detail["requirements"][0]["ledger"]["reserved"] == 8
    assert detail["requirements"][0]["ledger"]["remaining"] == 0
    queue_count = (await db_session.execute(text("SELECT COUNT(*) FROM print_queue"))).scalar_one()
    assert queue_count == 0


async def test_pause_resume_cancel_and_audit_timeline(async_client: AsyncClient):
    master = await _master_data(async_client, "STATE")
    order = (await _create_order(async_client, master, "STATE")).json()
    order_id = order["id"]

    paused = await async_client.post(
        f"/api/v1/production/orders/{order_id}/status",
        json={"operation_id": "pause-state", "action": "pause"},
    )
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = await async_client.post(
        f"/api/v1/production/orders/{order_id}/status",
        json={"operation_id": "resume-state", "action": "resume"},
    )
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "planned"

    cancelled = await async_client.post(
        f"/api/v1/production/orders/{order_id}/cancel",
        json={"operation_id": "cancel-state"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    detail = (await async_client.get(f"/api/v1/production/orders/{order_id}")).json()
    assert detail["requirements"][0]["status"] == "cancelled"
    assert [item["operation_type"] for item in detail["operations"]] == [
        "production_order_created",
        "production_order_paused",
        "production_order_resumed",
        "production_order_cancelled",
    ]


async def test_order_quantity_must_be_positive(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": "zero-quantity",
            "order_number": "ORDER-ZERO",
            "product_id": 1,
            "quantity": 0,
        },
    )
    assert response.status_code == 422


async def test_order_requires_complete_product_parts_and_print_plans(async_client: AsyncClient):
    product = (
        await async_client.post(
            "/api/v1/products",
            json={"sku": "NO-PARTS", "name": "没有零件清单"},
        )
    ).json()
    response = await async_client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": "missing-master-data",
            "order_number": "ORDER-MISSING-MASTER",
            "product_id": product["id"],
            "quantity": 1,
        },
    )
    assert response.status_code == 422
    assert "零件清单" in response.json()["detail"]
