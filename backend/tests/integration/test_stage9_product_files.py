from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.app.models.product_file import ProductFile


def _tiny_3mf():
    return b"PK\x03\x04stage9-source"


def _multi_plate_3mf():
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", b"<model/>")
        archive.writestr("Metadata/plate_1.png", b"plate-1")
        archive.writestr("Metadata/plate_2.png", b"plate-2")
        archive.writestr("Metadata/plate_3.png", b"plate-3")
    return output.getvalue()


def test_product_file_model_supports_fixed_and_auto_strategies():
    row = ProductFile(
        product_id=1,
        library_file_id=1,
        name="small-product.3mf",
        strategy="auto_pack",
        component_ids=[1, 2],
        units_per_plate=6,
        compatible_printer_models=["A1", "A2L"],
        product_color="RED-COVER",
        filament_requirements=[{"slot": 0, "material": "PLA", "color": "#FF0000"}],
    )
    assert row.strategy == "auto_pack"
    assert row.component_ids == [1, 2]
    assert row.units_per_plate == 6
    assert row.filament_requirements[0]["material"] == "PLA"
    assert row.product_color == "RED-COVER"


def test_stage9_strategy_values_are_explicit():
    assert {"fixed_plate", "auto_pack", "multi_plate_fixed"} == {"fixed_plate", "auto_pack", "multi_plate_fixed"}


@pytest.mark.asyncio
async def test_product_source_file_upload_is_product_owned(async_client):
    created = await async_client.post("/api/v1/products", json={"sku": "STAGE9-FILE", "name": "Stage 9 file"})
    assert created.status_code == 201
    product_id = created.json()["id"]
    response = await async_client.post(
        f"/api/v1/products/{product_id}/files",
        files={"file": ("small.3mf", _tiny_3mf(), "application/octet-stream")},
        data={"strategy": "auto_pack", "units_per_plate": "6", "component_ids": "[]", "compatible_printer_models": "[]", "filament_requirements": '[{"slot":0,"material":"PLA","color":"#FF0000"}]'},
    )
    assert response.status_code == 201, response.text
    assert response.json()["strategy"] == "auto_pack"
    assert response.json()["filament_requirements"] == [{"slot": 0, "material": "PLA", "color": "#FF0000"}]
    detail = await async_client.get(f"/api/v1/products/{product_id}")
    assert detail.status_code == 200
    assert detail.json()["product_files"][0]["name"] == "small.3mf"
    assert detail.json()["product_files"][0]["filament_requirements"][0]["color"] == "#FF0000"


@pytest.mark.asyncio
async def test_multi_plate_fixed_file_records_source_plate_count_and_one_unit_per_plate(async_client):
    created = await async_client.post("/api/v1/products", json={"sku": "STAGE9-MULTI", "name": "Multi plate file"})
    product_id = created.json()["id"]
    response = await async_client.post(
        f"/api/v1/products/{product_id}/files",
        files={"file": ("multi.3mf", _multi_plate_3mf(), "application/octet-stream")},
        data={"strategy": "multi_plate_fixed", "units_per_plate": "9", "filament_requirements": "[]"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["strategy"] == "multi_plate_fixed"
    assert response.json()["source_plate_count"] == 3
    assert response.json()["units_per_plate"] == 1


@pytest.mark.asyncio
async def test_product_level_multi_plate_requires_one_source_file_per_plate(async_client):
    product_response = await async_client.post(
        "/api/v1/products",
        json={"sku": "STAGE9-PRODUCT-MULTI", "name": "Product level multi", "production_mode": "multi_plate", "source_plate_count": 3},
    )
    assert product_response.status_code == 201, product_response.text
    product = product_response.json()
    assert product["production_mode"] == "multi_plate"
    assert product["source_plate_count"] == 3
    source_set_id = "stage9-source-set-1"
    for index in range(3):
        uploaded = await async_client.post(
            f"/api/v1/products/{product['id']}/files",
            files={"file": (f"plate-{index + 1}.3mf", _tiny_3mf(), "application/octet-stream")},
            data={
                "source_set_id": source_set_id,
                "source_plate_index": str(index),
                "filament_requirements": "[]",
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.json()["source_plate_index"] == index
        assert uploaded.json()["source_plate_count"] == 3
    detail = (await async_client.get(f"/api/v1/products/{product['id']}")).json()
    assert {item["source_plate_index"] for item in detail["product_files"] if item["is_active"]} == {0, 1, 2}
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-product-level-order", "product_id": product["id"], "quantity": 2},
    )
    assert order.status_code == 201, order.text
    snapshot = order.json()["product_file_snapshot"]
    assert snapshot["production_mode"] == "multi_plate"
    assert snapshot["source_plate_count"] == 3
    assert len(snapshot["source_file_ids"]) == 3


@pytest.mark.asyncio
async def test_product_level_multi_plate_rejects_incomplete_source_set(async_client):
    product = (
        await async_client.post(
            "/api/v1/products",
            json={"sku": "STAGE9-PRODUCT-MULTI-INCOMPLETE", "name": "Incomplete multi", "production_mode": "multi_plate", "source_plate_count": 2},
        )
    ).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("only-plate.3mf", _tiny_3mf(), "application/octet-stream")},
        data={"source_set_id": "stage9-incomplete-set", "source_plate_index": "0", "filament_requirements": "[]"},
    )
    assert uploaded.status_code == 201
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-product-level-incomplete-order", "product_id": product["id"], "quantity": 1},
    )
    assert order.status_code == 422
    assert "完整上传" in order.json()["detail"]


@pytest.mark.asyncio
async def test_multi_plate_order_expands_one_physical_job_per_source_plate_and_set(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE9-MULTI-ORDER", "name": "Multi plate order"})).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("multi-order.3mf", _multi_plate_3mf(), "application/octet-stream")},
        data={"strategy": "multi_plate_fixed", "filament_requirements": "[]"},
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "STAGE9-MULTI-A1", "name": "Multi A1", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    assert profile.status_code == 201, profile.text
    virtual = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Multi virtual A1", "model": "N2S", "mode": "archive", "units_per_plate_capacity": 1},
    )
    assert virtual.status_code == 200, virtual.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-multi-order", "order_number": "STAGE9-MULTI-ORDER", "product_id": product["id"], "quantity": 2},
    )
    assert order.status_code == 201, order.text
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    assert preview.status_code == 200
    assert preview.json()["items"][0]["source_plate_count"] == 3
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "stage9-multi-confirm", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    jobs = confirmed.json()["items"]
    assert len(jobs) == 6
    assert {(job["product_set_index"], job["source_plate_index"]) for job in jobs} == {
        (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)
    }
    assert {job["planned_quantity"] for job in jobs} == {1}


@pytest.mark.asyncio
async def test_order_uses_product_file_without_legacy_bom_or_recipe(async_client):
    created = await async_client.post("/api/v1/products", json={"sku": "STAGE9-ORDER", "name": "File order"})
    product_id = created.json()["id"]
    uploaded = await async_client.post(
        f"/api/v1/products/{product_id}/files",
        files={"file": ("order.3mf", _tiny_3mf(), "application/octet-stream")},
        data={"strategy": "fixed_plate", "units_per_plate": "2", "component_ids": "[]", "compatible_printer_models": "[\"A1\"]"},
    )
    assert uploaded.status_code == 201
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-file-order-1", "order_number": "STAGE9-FILE-ORDER", "product_id": product_id, "quantity": 4},
    )
    assert order.status_code == 201, order.text
    body = order.json()
    assert body["product_file_snapshot"]["version"] == 1
    assert body["product_file_snapshot"]["strategy"] == "fixed_plate"
    assert body["product_file_snapshot"]["units_per_plate"] == 2
    assert body["product_file_snapshot"]["library_file_id"] == uploaded.json()["library_file_id"]
    protected_delete = await async_client.delete(f"/api/v1/products/{product_id}/files/{uploaded.json()['id']}")
    assert protected_delete.status_code == 409


@pytest.mark.asyncio
async def test_virtual_printer_assignment_uses_dimensions_and_capacity(async_client):
    vp = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "A1 simulation", "model": "N2S", "enabled": False, "mode": "archive", "build_width_mm": 256, "build_depth_mm": 256, "build_height_mm": 256, "units_per_plate_capacity": 4},
    )
    assert vp.status_code == 200, vp.text
    assert vp.json()["units_per_plate_capacity"] == 4


@pytest.mark.asyncio
async def test_product_file_order_allocates_to_virtual_printer_without_queue(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE9-VP", "name": "Virtual order"})).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("vp.3mf", _tiny_3mf(), "application/octet-stream")},
        data={"strategy": "auto_pack", "units_per_plate": "2", "component_ids": "[]", "compatible_printer_models": "[\"A1\"]"},
    )
    assert uploaded.status_code == 201
    profile = await async_client.post("/api/v1/production/printer-profiles", json={"code": "STAGE9-VP-A1", "name": "Virtual A1", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True})
    assert profile.status_code == 201
    vp = await async_client.post("/api/v1/virtual-printers", json={"name": "Virtual A1", "model": "N2S", "enabled": False, "mode": "archive", "units_per_plate_capacity": 4})
    assert vp.status_code == 200
    order = await async_client.post("/api/v1/production/orders", json={"operation_id": "stage9-vp-order-1", "order_number": "STAGE9-VP-ORDER", "product_id": product["id"], "quantity": 2})
    assert order.status_code == 201, order.text
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm", json={"operation_id": "stage9-vp-confirm-1", "items": preview.json()["items"]})
    assert confirmed.status_code == 201, confirmed.text
    item = confirmed.json()["items"][0]
    assert item["virtual_printer_id"] == vp.json()["id"]
    assert item["queue_item_id"] is None


@pytest.mark.asyncio
async def test_product_file_material_colour_snapshot_selects_matching_virtual_printer(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE9-FILAMENT", "name": "Material order"})).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("material.3mf", _tiny_3mf(), "application/octet-stream")},
        data={
            "strategy": "auto_pack",
            "units_per_plate": "2",
            "component_ids": "[]",
            "compatible_printer_models": '["A1"]',
            "filament_requirements": '[{"slot":0,"material":"PLA","color":"#FF0000"}]',
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={
            "code": "STAGE9-FILAMENT-A1",
            "name": "A1 PLA red",
            "printer_model": "A1",
            "nozzle_diameter": 0.4,
            "auto_production_enabled": True,
            "supported_materials": ["PLA"],
            "supported_colors": ["#FF0000"],
        },
    )
    assert profile.status_code == 201, profile.text
    vp = await async_client.post(
        "/api/v1/virtual-printers",
        json={
            "name": "Virtual A1 red",
            "model": "N2S",
            "enabled": False,
            "mode": "archive",
            "units_per_plate_capacity": 2,
            "supported_materials": ["PLA"],
            "supported_colors": ["#FF0000"],
            "loaded_filaments": [{"slot": 0, "material": "PLA", "color": "#FF0000"}],
        },
    )
    assert vp.status_code == 200, vp.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-filament-order", "order_number": "STAGE9-FILAMENT-ORDER", "product_id": product["id"], "quantity": 2},
    )
    assert order.status_code == 201, order.text
    assert order.json()["product_file_snapshot"]["filament_requirements"][0]["color"] == "#FF0000"
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "stage9-filament-confirm", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["items"][0]["virtual_printer_id"] == vp.json()["id"]


@pytest.mark.asyncio
async def test_same_product_colour_upload_replaces_active_version_and_old_file_can_be_removed(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE9-VARIANT", "name": "Colour variants"})).json()
    first = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("red-v1.3mf", _tiny_3mf(), "application/octet-stream")},
        data={"product_color": "RED", "filament_requirements": '[{"slot":0,"material":"PLA","color":"#FF0000"}]'},
    )
    assert first.status_code == 201, first.text
    second = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("red-v2.3mf", _tiny_3mf() + b"v2", "application/octet-stream")},
        data={"product_color": "RED", "filament_requirements": '[{"slot":0,"material":"PLA","color":"#FF0000"}]'},
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2
    assert second.json()["is_active"] is True
    detail = await async_client.get(f"/api/v1/products/{product['id']}")
    files = {item["id"]: item for item in detail.json()["product_files"]}
    assert files[first.json()["id"]]["is_active"] is False
    assert files[second.json()["id"]]["is_active"] is True
    assert files[second.json()["id"]]["product_color"] == "RED"
    deactivated = await async_client.post(f"/api/v1/products/{product['id']}/files/{second.json()['id']}/deactivate")
    assert deactivated.status_code == 204, deactivated.text
    detail = await async_client.get(f"/api/v1/products/{product['id']}")
    assert all(not item["is_active"] for item in detail.json()["product_files"])
    deleted = await async_client.delete(f"/api/v1/products/{product['id']}/files/{second.json()['id']}")
    assert deleted.status_code == 204, deleted.text
    deleted_old = await async_client.delete(f"/api/v1/products/{product['id']}/files/{first.json()['id']}")
    assert deleted_old.status_code == 204, deleted_old.text
    detail = await async_client.get(f"/api/v1/products/{product['id']}")
    assert detail.json()["product_files"] == []


@pytest.mark.asyncio
async def test_product_colour_variant_is_used_when_file_has_no_slot_metadata(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE9-COLOR-ONLY", "name": "Color only variant"})).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("red-variant.3mf", _tiny_3mf(), "application/octet-stream")},
        data={"product_color": "红色", "filament_requirements": "[]"},
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "STAGE9-COLOR-ONLY-A1", "name": "A1 red", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True, "supported_colors": ["#FF0000"]},
    )
    assert profile.status_code == 201, profile.text
    vp = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "A1 red loaded", "model": "N2S", "mode": "archive", "loaded_filaments": [{"slot": 0, "material": "PLA", "color": "#FF0000"}], "supported_colors": ["#FF0000"], "units_per_plate_capacity": 1},
    )
    assert vp.status_code == 200, vp.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-color-only-order", "order_number": "STAGE9-COLOR-ONLY-ORDER", "product_id": product["id"], "quantity": 1},
    )
    assert order.status_code == 201, order.text
    assert order.json()["product_file_snapshot"]["product_color"] == "红色"
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "stage9-color-only-confirm", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    assert confirmed.json()["items"][0]["virtual_printer_id"] == vp.json()["id"]


@pytest.mark.asyncio
async def test_inactive_referenced_file_can_be_deleted_without_losing_order_snapshot(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE9-DELETE", "name": "Delete inactive file"})).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("old.3mf", _tiny_3mf(), "application/octet-stream")},
        data={"filament_requirements": '[{"slot":0,"material":"PETG","color":"黑色"}]'},
    )
    assert uploaded.status_code == 201, uploaded.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage9-delete-order", "order_number": "STAGE9-DELETE-ORDER", "product_id": product["id"], "quantity": 1},
    )
    assert order.status_code == 201, order.text
    stopped = await async_client.post(f"/api/v1/products/{product['id']}/files/{uploaded.json()['id']}/deactivate")
    assert stopped.status_code == 204, stopped.text
    deleted = await async_client.delete(f"/api/v1/products/{product['id']}/files/{uploaded.json()['id']}")
    assert deleted.status_code == 204, deleted.text
    history = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}")
    assert history.status_code == 200
    assert history.json()["product_file_snapshot"]["version"] == 1
