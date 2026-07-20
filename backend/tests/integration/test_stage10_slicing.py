from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest


def _box_3mf(width: int = 80, depth: int = 80, height: int = 20) -> bytes:
    model = f'''<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" unit="millimeter">
  <resources><object id="1" type="model"><mesh><vertices>
    <vertex x="0" y="0" z="0"/><vertex x="{width}" y="0" z="0"/>
    <vertex x="0" y="{depth}" z="0"/><vertex x="0" y="0" z="{height}"/>
  </vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources>
  <build><item objectid="1"/></build>
</model>'''.encode()
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("Metadata/plate_1.png", b"not-an-image")
        archive.writestr(
            "Metadata/slice_info.config",
            b'<?xml version="1.0"?><config><plate><metadata key="printer_model_id" value=""/></plate></config>',
        )
    return output.getvalue()


@pytest.mark.asyncio
async def test_auto_slice_persists_source_association_and_capacity(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE10-AUTO", "name": "Stage 10 auto"})).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("auto.3mf", _box_3mf(), "application/octet-stream")},
        data={
            "strategy": "auto_pack",
            "units_per_plate": "1",
            "compatible_printer_models": '["A1"]',
            "filament_requirements": '[{"slot":0,"material":"PETG","color":"#000000"}]',
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "STAGE10-AUTO-A1", "name": "Stage 10 A1", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    assert profile.status_code == 201, profile.text
    virtual = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Stage 10 virtual A1", "model": "N2S", "mode": "archive", "build_width_mm": 200, "build_depth_mm": 200, "build_height_mm": 250, "units_per_plate_capacity": 99, "supported_materials": ["PETG"], "supported_colors": ["#000000"], "loaded_filaments": [{"slot": 0, "material": "PETG", "color": "#000000"}]},
    )
    assert virtual.status_code == 200, virtual.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage10-auto-order", "order_number": "STAGE10-AUTO-ORDER", "product_id": product["id"], "quantity": 10},
    )
    assert order.status_code == 201, order.text
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "stage10-auto-confirm", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    job = confirmed.json()["items"][0]
    assert job["slice_status"] == "succeeded"
    assert job["slice_result"]["actual_units_per_plate"] == 4
    assert job["slice_result"]["plate_count"] == 3
    assert job["slice_result"]["source_product_file_id"] == uploaded.json()["id"]
    assert job["slice_result"]["simulation_only"] is True


@pytest.mark.asyncio
async def test_slice_failure_is_visible_and_retryable(async_client):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE10-FAIL", "name": "Stage 10 failure"})).json()
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("broken.3mf", b"not-a-zip", "application/octet-stream")},
        data={"strategy": "auto_pack", "units_per_plate": "1", "compatible_printer_models": "[]", "filament_requirements": "[]"},
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "STAGE10-FAIL-A1", "name": "Stage 10 fail A1", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    assert profile.status_code == 201, profile.text
    virtual = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Stage 10 fail virtual", "model": "N2S", "mode": "archive", "supported_materials": [], "supported_colors": [], "loaded_filaments": []},
    )
    assert virtual.status_code == 200, virtual.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage10-fail-order", "order_number": "STAGE10-FAIL-ORDER", "product_id": product["id"], "quantity": 1},
    )
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "stage10-fail-confirm", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    job = confirmed.json()["items"][0]
    assert job["slice_status"] == "failed"
    assert "无法读取 3MF" in job["slice_error"]
    retried = await async_client.post(f"/api/v1/production/plate-jobs/{job['id']}/slice")
    assert retried.status_code == 200, retried.text
    assert retried.json()["slice_status"] == "failed"
    assert retried.json()["slice_attempts"] == 2


@pytest.mark.asyncio
async def test_real_slice_uses_embedded_settings_and_persists_gcode_artifact(async_client, monkeypatch):
    """The production endpoint must call the real slicer adapter, not the
    deterministic planner, while keeping the source file immutable."""

    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE10-REAL", "name": "Stage 10 real"})).json()
    source = _box_3mf()
    # Keep the test archive valid and provide the embedded settings document.
    rebuilt = BytesIO()
    with ZipFile(BytesIO(source), "r") as original, ZipFile(rebuilt, "w", ZIP_DEFLATED) as archive:
        for item in original.infolist():
            archive.writestr(item, original.read(item.filename))
        archive.writestr(
            "Metadata/project_settings.config",
            b'{"printer_settings_id":"Bambu Lab A1 0.4 nozzle","printer_model":"A1","sparse_infill_density":"15%"}',
        )
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("real.3mf", rebuilt.getvalue(), "application/octet-stream")},
        data={
            "strategy": "auto_pack",
            "units_per_plate": "1",
            "compatible_printer_models": "[\"A1\"]",
            "filament_requirements": "[]",
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "STAGE10-REAL-A1", "name": "Stage 10 real A1", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    assert profile.status_code == 201, profile.text
    virtual = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Stage 10 real virtual", "model": "N2S", "mode": "archive", "supported_materials": [], "supported_colors": [], "loaded_filaments": []},
    )
    assert virtual.status_code == 200, virtual.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage10-real-order", "order_number": "STAGE10-REAL-ORDER", "product_id": product["id"], "quantity": 1},
    )
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "stage10-real-confirm", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    job_id = confirmed.json()["items"][0]["id"]

    calls: list[dict] = []

    class FakeSlicer:
        def __init__(self, base_url: str):
            calls.append({"base_url": base_url})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def slice_without_profiles(self, **kwargs):
            calls.append(kwargs)
            from backend.app.services.slicer_api import SliceResult

            return SliceResult(content=rebuilt.getvalue(), print_time_seconds=42, filament_used_g=3.5, filament_used_mm=120.0)

    monkeypatch.setattr("backend.app.services.slicer_api.SlicerApiService", FakeSlicer)
    result = await async_client.post(f"/api/v1/production/plate-jobs/{job_id}/real-slice")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["slice_status"] == "succeeded"
    assert body["slice_result"]["real_slice"] is True
    assert body["slice_result"]["simulation_only"] is False
    assert body["slice_result"]["embedded_settings_preserved"] is True
    assert body["slice_result"]["output_library_file_id"] > 0
    assert calls[-1]["plate"] == 0
    assert calls[-1]["export_3mf"] is True
    assert calls[-1]["arrange"] is False

    # Re-running the exact source/settings pair must reuse the persisted
    # artifact instead of calling the sidecar a second time.
    call_count = len(calls)
    reused = await async_client.post(f"/api/v1/production/plate-jobs/{job_id}/real-slice")
    assert reused.status_code == 200, reused.text
    assert reused.json()["slice_result"]["reused"] is True
    assert reused.json()["slice_result"]["slice_artifact_id"] == body["slice_result"]["slice_artifact_id"]
    assert len(calls) == call_count
    artifacts = await async_client.get("/api/v1/production/slice-artifacts")
    assert artifacts.status_code == 200
    assert len(artifacts.json()) == 1
    download = await async_client.get(
        f"/api/v1/production/slice-artifacts/{artifacts.json()[0]['id']}/download"
    )
    assert download.status_code == 200
    assert download.content != rebuilt.getvalue()
    with ZipFile(BytesIO(download.content)) as archive:
        assert 'key="printer_model_id" value="N2S"' in archive.read("Metadata/slice_info.config").decode()
        assert not any(name.startswith("3D/Objects/") for name in archive.namelist())
        assert '<build' in archive.read("3D/3dmodel.model").decode()
        assert 'objectid=' not in archive.read("3D/3dmodel.model").decode()
        assert '<object' not in archive.read("Metadata/model_settings.config").decode()
    dispatch = await async_client.post(
        f"/api/v1/production/slice-artifacts/{artifacts.json()[0]['id']}/dispatch"
    )
    assert dispatch.status_code == 409


@pytest.mark.asyncio
async def test_real_auto_pack_slices_each_plate_quantity_and_caches_separately(async_client, monkeypatch):
    product = (await async_client.post("/api/v1/products", json={"sku": "STAGE10-QTY", "name": "Stage 10 quantity"})).json()
    source = _box_3mf(width=100, depth=100)
    rebuilt = BytesIO()
    with ZipFile(BytesIO(source), "r") as original, ZipFile(rebuilt, "w", ZIP_DEFLATED) as archive:
        for item in original.infolist():
            archive.writestr(item, original.read(item.filename))
        archive.writestr("Metadata/project_settings.config", b'{"printer_model":"A1"}')
    uploaded = await async_client.post(
        f"/api/v1/products/{product['id']}/files",
        files={"file": ("quantity.3mf", rebuilt.getvalue(), "application/octet-stream")},
        data={"strategy": "auto_pack", "units_per_plate": "1", "compatible_printer_models": "[\"A1\"]", "filament_requirements": "[]"},
    )
    assert uploaded.status_code == 201, uploaded.text
    profile = await async_client.post(
        "/api/v1/production/printer-profiles",
        json={"code": "STAGE10-QTY-A1", "name": "Stage 10 quantity A1", "printer_model": "A1", "nozzle_diameter": 0.4, "auto_production_enabled": True},
    )
    assert profile.status_code == 201, profile.text
    virtual = await async_client.post(
        "/api/v1/virtual-printers",
        json={"name": "Stage 10 quantity virtual", "model": "N2S", "mode": "archive", "build_width_mm": 200, "build_depth_mm": 200, "build_height_mm": 250, "supported_materials": [], "supported_colors": [], "loaded_filaments": []},
    )
    assert virtual.status_code == 200, virtual.text
    order = await async_client.post(
        "/api/v1/production/orders",
        json={"operation_id": "stage10-qty-order", "order_number": "STAGE10-QTY-ORDER", "product_id": product["id"], "quantity": 6},
    )
    preview = await async_client.get(f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/preview")
    confirmed = await async_client.post(
        f"/api/v1/production/orders/{order.json()['id']}/plate-jobs/confirm",
        json={"operation_id": "stage10-qty-confirm", "items": preview.json()["items"]},
    )
    assert confirmed.status_code == 201, confirmed.text
    job_id = confirmed.json()["items"][0]["id"]
    calls: list[bytes] = []

    class FakeSlicer:
        def __init__(self, base_url: str):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def slice_without_profiles(self, **kwargs):
            calls.append(kwargs["model_bytes"])
            from backend.app.services.slicer_api import SliceResult

            return SliceResult(content=rebuilt.getvalue(), print_time_seconds=1, filament_used_g=1, filament_used_mm=1)

    monkeypatch.setattr("backend.app.services.slicer_api.SlicerApiService", FakeSlicer)
    result = await async_client.post(f"/api/v1/production/plate-jobs/{job_id}/real-slice")
    assert result.status_code == 200, result.text
    body = result.json()["slice_result"]
    assert body["plate_quantities"] == [1, 1, 1, 1, 1, 1]
    assert [plate["plate_quantity"] for plate in body["plates"]] == [1, 1, 1, 1, 1, 1]
    assert len({plate["slice_artifact_id"] for plate in body["plates"]}) == 6
    from xml.etree import ElementTree

    def build_item_count(data: bytes) -> int:
        with ZipFile(BytesIO(data)) as archive:
            root = ElementTree.fromstring(archive.read("3D/3dmodel.model"))
        return sum(node.tag.rsplit("}", 1)[-1] == "item" for node in root.iter())

    assert [build_item_count(data) for data in calls] == [1, 1, 1, 1, 1, 1]
    call_count = len(calls)
    reused = await async_client.post(f"/api/v1/production/plate-jobs/{job_id}/real-slice")
    assert reused.status_code == 200, reused.text
    assert reused.json()["slice_result"]["reused"] is True
    assert len(calls) == call_count
