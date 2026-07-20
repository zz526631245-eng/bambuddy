import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


def _source_3mf() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Metadata/project_settings.config", '{"printer_model":"A1"}')
        archive.writestr("3D/3dmodel.model", "model")
    return output.getvalue()


async def _create_file(async_client, product_id: int, *, name: str):
    response = await async_client.post(
        f"/api/v1/products/{product_id}/files",
        files={"file": (name, _source_3mf(), "application/octet-stream")},
        data={
            "strategy": "auto_pack",
            "units_per_plate": "1",
            "compatible_printer_models": "[]",
            "filament_requirements": '[{"slot":0,"material":"PETG","color":"#000000"}]',
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_product_size_class_routes_large_models_away_from_a1(async_client):
    a1_profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "SIZE-A1", "name": "Size A1", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    a2l_profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "SIZE-A2L", "name": "Size A2L", "printer_model": "A2L", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    assert a1_profile.status_code == 201, a1_profile.text
    assert a2l_profile.status_code == 201, a2l_profile.text
    a1 = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Size virtual A1", "model": "N2S", "mode": "archive", "supported_materials": ["PETG"], "supported_colors": ["#000000"], "loaded_filaments": [{"slot": 0, "material": "PETG", "color": "#000000"}]},
    )
    a2l = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Size virtual A2L", "model": "N9", "mode": "archive", "supported_materials": ["PETG"], "supported_colors": ["#000000"], "loaded_filaments": [{"slot": 0, "material": "PETG", "color": "#000000"}]},
    )
    assert a1.status_code == 200, a1.text
    assert a2l.status_code == 200, a2l.text

    standard = (await async_client.post("/api/v1/products", json={"name": "Standard size", "size_class": "standard"})).json()
    large = (await async_client.post("/api/v1/products", json={"name": "Large size", "size_class": "large"})).json()
    standard_file = await _create_file(async_client, standard["id"], name="standard.3mf")
    large_file = await _create_file(async_client, large["id"], name="large.3mf")

    standard_order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "size-standard-order", "order_number": "SIZE-STANDARD", "product_id": standard["id"], "product_file_id": standard_file["id"], "quantity": 1},
    )
    large_order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "size-large-order", "order_number": "SIZE-LARGE", "product_id": large["id"], "product_file_id": large_file["id"], "quantity": 1},
    )
    assert standard_order.status_code == 201, standard_order.text
    assert large_order.status_code == 201, large_order.text
    assert standard_order.json()["product_snapshot"]["size_class"] == "standard"
    assert large_order.json()["product_snapshot"]["size_class"] == "large"

    async def confirm(order_id: int, operation_id: str):
        preview = await async_client.get(f"/api/v1/production/orders/{order_id}/plate-jobs/preview")
        confirmed = await async_client.post(
            f"/api/v1/production/orders/{order_id}/plate-jobs/confirm",
            json={"operation_id": operation_id, "items": preview.json()["items"]},
        )
        assert confirmed.status_code == 201, confirmed.text
        return confirmed.json()["items"][0]

    standard_job = await confirm(standard_order.json()["id"], "size-standard-confirm")
    large_job = await confirm(large_order.json()["id"], "size-large-confirm")
    assert standard_job["virtual_printer_id"] == a1.json()["id"]
    assert large_job["virtual_printer_id"] == a2l.json()["id"]


@pytest.mark.asyncio
async def test_real_slice_uses_assigned_virtual_printer_model(async_client, monkeypatch):
    product = (await async_client.post("/api/v1/products", json={"name": "Auto target"})).json()
    uploaded = await _create_file(async_client, product["id"], name="target.3mf")
    await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "TARGET-A2L", "name": "Target A2L", "printer_model": "A2L", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    virtual = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Target A2L", "model": "N9", "mode": "archive", "supported_materials": ["PETG"], "supported_colors": ["#000000"], "loaded_filaments": [{"slot": 0, "material": "PETG", "color": "#000000"}]},
    )
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "size-target-order", "order_number": "SIZE-TARGET", "product_id": product["id"], "product_file_id": uploaded["id"], "quantity": 1},
    )
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "size-target-confirm", "items": preview.json()["items"]},
    )
    job_id = confirmed.json()["items"][0]["id"]
    assert confirmed.json()["items"][0]["virtual_printer_id"] == virtual.json()["id"]

    calls = []

    class FakeSlicer:
        def __init__(self, _url):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def slice_without_profiles(self, **kwargs):
            calls.append(kwargs)
            from backend.app.services.slicer_api import SliceResult

            return SliceResult(content=_source_3mf(), print_time_seconds=1, filament_used_g=1, filament_used_mm=1)

    monkeypatch.setattr("backend.app.services.slicer_api.SlicerApiService", FakeSlicer)
    result = await async_client.post(f"/api/v1/production/plate-jobs/{job_id}/real-slice")
    assert result.status_code == 200, result.text
    with ZipFile(BytesIO(calls[-1]["model_bytes"]), "r") as archive:
        settings = json.loads(archive.read("Metadata/project_settings.config"))
    assert settings["printer_model"] == "Bambu Lab A2L"
    assert settings["printer_settings_id"] == "Bambu Lab A2L 0.4 nozzle"
