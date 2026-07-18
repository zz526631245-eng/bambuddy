"""Stage 6 API shell tests: create/read only, with no print dispatch."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_create_and_read_product(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/products",
        json={"sku": "SKU-001", "name": "Stage 6 Product", "description": "Skeleton only"},
    )
    assert response.status_code == 201
    product = response.json()
    assert product["sku"] == "SKU-001"
    assert product["is_active"] is True

    detail = await async_client.get(f"/api/v1/products/{product['id']}")
    assert detail.status_code == 200
    assert detail.json()["name"] == "Stage 6 Product"


async def test_product_sku_conflict_is_409(async_client: AsyncClient):
    payload = {"sku": "SKU-DUP", "name": "First"}
    assert (await async_client.post("/api/v1/products", json=payload)).status_code == 201
    duplicate = await async_client.post("/api/v1/products", json={**payload, "name": "Second"})
    assert duplicate.status_code == 409


async def test_create_minimal_master_data_and_recipe(async_client: AsyncClient):
    product = (await async_client.post("/api/v1/products", json={"sku": "SKU-R", "name": "Recipe Product"})).json()
    material = (
        await async_client.post(
            "/api/v1/production/material-types",
            json={"code": "PLA-WHITE", "material": "PLA", "brand": "Test", "color_name": "White"},
        )
    ).json()
    profile = (
        await async_client.post(
            "/api/v1/production/printer-profiles",
            json={"code": "X1C-04", "name": "X1C 0.4", "printer_model": "X1C", "nozzle_diameter": 0.4},
        )
    ).json()
    recipe_response = await async_client.post(
        "/api/v1/production/recipes",
        json={
            "code": "RECIPE-001",
            "name": "Stage 6 Recipe",
            "product_id": product["id"],
            "material_type_id": material["id"],
            "printer_profile_id": profile["id"],
            "version": 1,
        },
    )
    assert recipe_response.status_code == 201
    assert recipe_response.json()["product_id"] == product["id"]


async def test_create_order_requires_stage8_operation_id_and_complete_master_data(
    async_client: AsyncClient,
    db_session: AsyncSession,
):
    product = (await async_client.post("/api/v1/products", json={"sku": "SKU-O", "name": "Order Product"})).json()
    missing_operation = await async_client.post(
        "/api/v1/production/orders",
        json={"order_number": "ORDER-001", "product_id": product["id"], "quantity": 25},
    )
    assert missing_operation.status_code == 422

    response = await async_client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": "stage6-incomplete-master",
            "order_number": "ORDER-001",
            "product_id": product["id"],
            "quantity": 25,
        },
    )
    assert response.status_code == 422
    assert "零件清单" in response.json()["detail"]

    requirements = await async_client.get("/api/v1/production/requirements")
    plate_jobs = await async_client.get("/api/v1/production/plate-jobs")
    assert requirements.status_code == 200
    assert requirements.json() == []
    assert plate_jobs.status_code == 200
    assert plate_jobs.json() == []

    queue_count = (await db_session.execute(text("SELECT COUNT(*) FROM print_queue"))).scalar_one()
    assert queue_count == 0


async def test_negative_quantities_are_rejected_before_database(async_client: AsyncClient):
    product = (await async_client.post("/api/v1/products", json={"sku": "SKU-N", "name": "Negative Test"})).json()
    response = await async_client.post(
        "/api/v1/production/orders",
        json={"order_number": "ORDER-NEG", "product_id": product["id"], "quantity": -1},
    )
    assert response.status_code == 422


async def test_missing_foreign_keys_return_404(async_client: AsyncClient):
    response = await async_client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": "missing-product",
            "order_number": "ORDER-MISSING",
            "product_id": 999999,
            "quantity": 1,
        },
    )
    assert response.status_code == 422


async def test_operation_logs_are_read_only_in_stage_6(async_client: AsyncClient):
    response = await async_client.get("/api/v1/production/operations")
    assert response.status_code == 200
    assert response.json() == []

    post_response = await async_client.post(
        "/api/v1/production/operations",
        json={"operation_id": "must-not-be-public"},
    )
    assert post_response.status_code == 405
