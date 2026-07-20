"""Controls for reviewing, cancelling and removing production work."""

from httpx import AsyncClient


async def _order_with_job(client: AsyncClient, suffix: str) -> tuple[int, int]:
    product = (await client.post("/api/v1/products", json={"sku": f"CONTROL-{suffix}", "name": "Control product"})).json()
    uploaded = await client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": (f"control-{suffix}.3mf", b"PK\\x03\\x04control", "application/octet-stream")},
        data={"strategy": "fixed_plate", "units_per_plate": "1", "compatible_printer_models": "[]", "filament_requirements": "[]"},
    )
    assert uploaded.status_code == 201, uploaded.text
    order = await client.post(
        "/api/v1/production/orders",
        json={"operation_id": f"control-order-{suffix}", "product_id": product["id"], "quantity": 1},
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    preview = await client.get(f"/api/v1/production/orders/{order_id}/plate-jobs/preview")
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(
        f"/api/v1/production/orders/{order_id}/plate-jobs/confirm",
        json={"operation_id": f"control-confirm-{suffix}", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    return order_id, confirmed.json()["items"][0]["id"]


async def test_plate_job_can_be_cancelled_then_deleted(async_client: AsyncClient):
    order_id, job_id = await _order_with_job(async_client, "JOB")

    cancelled = await async_client.post(f"/api/v1/production/plate-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    deleted = await async_client.delete(f"/api/v1/production/plate-jobs/{job_id}")
    assert deleted.status_code == 204, deleted.text

    detail = await async_client.get(f"/api/v1/production/orders/{order_id}")
    assert detail.status_code == 200
    assert detail.json()["requirements"][0]["plate_jobs"] == []


async def test_production_order_can_be_deleted_with_its_work(async_client: AsyncClient):
    order_id, _ = await _order_with_job(async_client, "ORDER")

    deleted = await async_client.delete(f"/api/v1/production/orders/{order_id}")
    assert deleted.status_code == 204, deleted.text
    missing = await async_client.get(f"/api/v1/production/orders/{order_id}")
    assert missing.status_code == 404
