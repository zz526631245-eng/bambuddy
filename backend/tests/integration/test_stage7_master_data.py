"""Stage 7 production master data, safety and no-dispatch acceptance tests."""

import base64
import io
import zipfile

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_product_crud_sku_normalization_and_unique(async_client: AsyncClient):
    created = await async_client.post("/api/v1/products", json={"sku": " sku-7 ", "name": "Product 7"})
    assert created.status_code == 201 and created.json()["sku"] == "SKU-7"
    product_id = created.json()["id"]
    updated = await async_client.put(f"/api/v1/products/{product_id}", json={"name": "Updated"})
    assert updated.status_code == 200 and updated.json()["name"] == "Updated"
    duplicate = await async_client.post("/api/v1/products", json={"sku": "SKU-7", "name": "Duplicate"})
    assert duplicate.status_code == 409


async def test_bom_requires_positive_quantity_and_protects_component(async_client: AsyncClient):
    product = (await async_client.post("/api/v1/products", json={"sku": "BOM-7", "name": "BOM Product"})).json()
    component = (
        await async_client.post("/api/v1/products/components", json={"code": "PART-A", "name": "Part A", "unit": "pcs"})
    ).json()
    invalid = await async_client.post(
        f"/api/v1/products/{product['id']}/bom", json={"component_id": component["id"], "quantity": 0}
    )
    assert invalid.status_code == 422
    created = await async_client.post(
        f"/api/v1/products/{product['id']}/bom", json={"component_id": component["id"], "quantity": 2.5}
    )
    assert created.status_code == 201
    assert (await async_client.delete(f"/api/v1/products/components/{component['id']}")).status_code == 409


async def test_image_allowlist_safe_name_and_round_trip_export(async_client: AsyncClient, tmp_path, monkeypatch):
    from backend.app.api.routes import products as products_route

    monkeypatch.setattr(products_route.settings, "base_dir", tmp_path)
    product = (await async_client.post("/api/v1/products", json={"sku": "IMG-7", "name": "Image Product"})).json()
    rejected = await async_client.post(
        f"/api/v1/products/{product['id']}/images", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}
    )
    assert rejected.status_code == 415
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/images", files={"file": ("../../photo.png", png, "image/png")}
    )
    assert uploaded.status_code == 201 and uploaded.json()["original_name"] == "photo.png"
    exported = await async_client.get(f"/api/v1/products/{product['id']}/export")
    assert exported.status_code == 200
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert "manifest.json" in archive.namelist()
    assert (await async_client.delete(f"/api/v1/products/{product['id']}")).status_code == 204
    imported = await async_client.post(
        "/api/v1/products/import/archive",
        files={"file": ("product.zip", exported.content, "application/zip")},
    )
    assert imported.status_code == 201 and imported.json()["sku"] == "IMG-7"
    detail = await async_client.get(f"/api/v1/products/{imported.json()['id']}")
    assert len(detail.json()["images"]) == 1


async def test_product_archive_round_trip_preserves_recipe_component_link(async_client: AsyncClient):
    product = (
        await async_client.post(
            "/api/v1/products",
            json={"sku": "ROUNDTRIP-7", "name": "Round-trip Product"},
        )
    ).json()
    component = (
        await async_client.post(
            "/api/v1/products/components",
            json={"code": "ROUNDTRIP-PART-7", "name": "Round-trip Part", "unit": "个"},
        )
    ).json()
    await async_client.post(
        f"/api/v1/products/{product['id']}/bom",
        json={"component_id": component["id"], "quantity": 2},
    )
    recipe = (
        await async_client.post(
            "/api/v1/production/recipes",
            json={
                "code": "ROUNDTRIP-PLAN-7",
                "name": "Round-trip Plan",
                "product_id": product["id"],
                "component_id": component["id"],
                "version": 1,
            },
        )
    ).json()

    exported = await async_client.get(f"/api/v1/products/{product['id']}/export")
    assert exported.status_code == 200
    assert (await async_client.delete(f"/api/v1/production/recipes/{recipe['id']}")).status_code == 204
    assert (await async_client.delete(f"/api/v1/products/{product['id']}")).status_code == 204

    imported = await async_client.post(
        "/api/v1/products/import/archive",
        files={"file": ("product.zip", exported.content, "application/zip")},
    )
    assert imported.status_code == 201
    imported_product_id = imported.json()["id"]
    imported_detail = (await async_client.get(f"/api/v1/products/{imported_product_id}")).json()
    imported_recipes = [
        item
        for item in (await async_client.get("/api/v1/production/recipes")).json()
        if item["product_id"] == imported_product_id
    ]

    assert len(imported_recipes) == 1
    assert imported_recipes[0]["component_id"] == imported_detail["bom_items"][0]["component_id"]


async def test_material_normalization_profile_fields_recipe_compatibility_and_no_queue(
    async_client: AsyncClient, db_session: AsyncSession
):
    product = (await async_client.post("/api/v1/products", json={"sku": "REC-7", "name": "Recipe Product"})).json()
    material = (
        await async_client.post(
            "/api/v1/production/material-types",
            json={"code": " pla-red ", "material": "pla", "brand": " ACME ", "color_hex": "ff0000"},
        )
    ).json()
    assert material["code"] == "PLA-RED" and material["material"] == "PLA" and material["color_hex"] == "#FF0000"
    profile = (
        await async_client.post(
            "/api/v1/production/printer-profiles",
            json={
                "code": "X1-04",
                "name": "X1",
                "printer_model": "X1C",
                "nozzle_diameter": 0.4,
                "location": "A区",
                "profile_group": "高速组",
                "auto_production_enabled": True,
            },
        )
    ).json()
    recipe = await async_client.post(
        "/api/v1/production/recipes",
        json={
            "code": "R-7",
            "name": "Recipe",
            "product_id": product["id"],
            "material_type_id": material["id"],
            "printer_profile_id": profile["id"],
            "slicer_preset": "0.20 Standard",
            "compatible_profile_ids": [profile["id"]],
        },
    )
    assert recipe.status_code == 201 and recipe.json()["compatible_profile_ids"] == [profile["id"]]
    assert (await db_session.execute(text("SELECT COUNT(*) FROM print_queue"))).scalar_one() == 0


async def test_product_delete_reference_protection(async_client: AsyncClient):
    product = (await async_client.post("/api/v1/products", json={"sku": "REF-7", "name": "Referenced"})).json()
    component = (
        await async_client.post(
            "/api/v1/products/components",
            json={"code": "REF-PART-7", "name": "Referenced part", "unit": "个"},
        )
    ).json()
    await async_client.post(
        f"/api/v1/products/{product['id']}/bom",
        json={"component_id": component["id"], "quantity": 1},
    )
    recipe = await async_client.post(
        "/api/v1/production/recipes",
        json={
            "code": "REF-PLAN-7",
            "name": "Referenced plan",
            "product_id": product["id"],
            "component_id": component["id"],
            "version": 1,
        },
    )
    assert recipe.status_code == 201
    await async_client.post(
        "/api/v1/production/orders",
        json={
            "operation_id": "ref-order-7",
            "order_number": "REF-ORDER",
            "product_id": product["id"],
            "quantity": 1,
        },
    )
    assert (await async_client.delete(f"/api/v1/products/{product['id']}")).status_code == 409
