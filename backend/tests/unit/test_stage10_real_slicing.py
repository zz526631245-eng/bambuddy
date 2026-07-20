import json
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from backend.app.services.production_slicer import (
    PrinterBuildVolume,
    SlicePlanningError,
    _format_real_slice_error,
    apply_build_item_layout,
    duplicate_build_items,
    inspect_projected_footprint,
    inspect_slice_output,
    make_direct_sendable_sliced_output,
    normalize_build_item_positions,
    patch_embedded_printer_preset,
    patch_sliced_output_printer_metadata,
    slice_output_filename,
    slice_settings_fingerprint,
)


def _source_3mf() -> bytes:
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "Metadata/project_settings.config",
            json.dumps(
                {
                    "printer_settings_id": "Bambu Lab A1 0.4 nozzle",
                    "printer_model": "A1",
                    "print_compatible_printers": ["Bambu Lab A1 0.4 nozzle"],
                    "print_settings_id": "0.20mm Standard",
                    "rotate_model": [12, 34, 56],
                    "sparse_infill_density": "15%",
                    "support_filament": "2",
                }
            ),
        )
        archive.writestr("Metadata/model_settings.config", b"keep-model-settings")
        archive.writestr("3D/3dmodel.model", b"keep-model")
    return out.getvalue()


def _build_source_3mf() -> bytes:
    out = BytesIO()
    model = b'''<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="2" type="model"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/><vertex x="0" y="10" z="0"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources><build><item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></build></model>'''
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Metadata/project_settings.config", json.dumps({"printer_model": "A1"}))
        archive.writestr("3D/3dmodel.model", model)
    return out.getvalue()


def test_switching_printer_changes_only_embedded_printer_fields():
    patched = patch_embedded_printer_preset(
        _source_3mf(),
        printer_preset="Bambu Lab A2L 0.4 nozzle",
        printer_model="A2L",
    )

    with ZipFile(BytesIO(patched)) as archive:
        settings = json.loads(archive.read("Metadata/project_settings.config"))
        assert settings["printer_settings_id"] == "Bambu Lab A2L 0.4 nozzle"
        assert settings["printer_model"] == "A2L"
        assert settings["print_compatible_printers"] == ["Bambu Lab A1 0.4 nozzle", "Bambu Lab A2L 0.4 nozzle"]
        assert settings["print_settings_id"] == "0.20mm Standard"
        assert settings["rotate_model"] == [12, 34, 56]
        assert settings["sparse_infill_density"] == "15%"
        assert settings["support_filament"] == "2"
        assert archive.read("Metadata/model_settings.config") == b"keep-model-settings"
        assert archive.read("3D/3dmodel.model") == b"keep-model"


def test_switching_without_target_keeps_source_bytes_unchanged():
    source = _source_3mf()
    assert patch_embedded_printer_preset(source) == source


def test_slice_cache_key_changes_when_source_or_printer_changes():
    base = {
        "source_sha256": "a" * 64,
        "source_version": 1,
        "strategy": "auto_pack",
        "preferred_slicer": "bambu_studio",
        "target_printer_preset": "A1",
        "target_printer_model": "A1",
    }
    assert slice_settings_fingerprint(**base) == slice_settings_fingerprint(**base)
    assert slice_settings_fingerprint(**{**base, "source_version": 2}) != slice_settings_fingerprint(**base)
    assert slice_settings_fingerprint(**{**base, "target_printer_model": "A2L"}) != slice_settings_fingerprint(**base)


def test_auto_pack_duplicates_one_product_for_the_requested_plate_quantity():
    source = _build_source_3mf()
    expanded = duplicate_build_items(source, 3)
    with ZipFile(BytesIO(expanded)) as archive:
        assert json.loads(archive.read("Metadata/project_settings.config"))["printer_model"] == "A1"
        model = archive.read("3D/3dmodel.model").decode()
        assert model.count("objectid=\"2\"") == 3


def test_geometry_failure_explains_that_the_source_layout_is_outside_the_bed():
    message = _format_real_slice_error(RuntimeError("Found G-code outside of the printable area; ZFiller"))
    assert "自动摆盘失败" in message
    assert "源 3MF" in message
    assert "原始原因" in message


def test_auto_pack_normalizes_xy_translation_and_keeps_rotation_and_z_height():
    source_model = b'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources/><build><item objectid="2" transform="1 0 0 0 0 -1 0 1 0 125 -40 12"/></build></model>'
    source_io = BytesIO()
    with ZipFile(source_io, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Metadata/project_settings.config", b"{}")
        archive.writestr("3D/3dmodel.model", source_model)
    source = source_io.getvalue()
    normalized = normalize_build_item_positions(source)
    with ZipFile(BytesIO(normalized)) as archive:
        model = archive.read("3D/3dmodel.model").decode()
    assert "transform=\"1 0 0 0 0 -1 0 1 0 0 0 12\"" in model


def test_real_slice_filename_marks_plate_index_and_quantity():
    assert slice_output_filename("111.3mf", plate_index=0, plate_quantity=3) == "111.plate-1.qty-3.gcode.3mf"
    assert slice_output_filename("111.3mf", plate_index=1, plate_quantity=4) == "111.plate-2.qty-4.gcode.3mf"


def test_explicit_layout_preserves_z_and_applies_z_rotation():
    source = _build_source_3mf()
    placed = apply_build_item_layout(
        source,
        [{"x_mm": 42, "y_mm": 42, "rotation_deg": 90}],
    )
    with ZipFile(BytesIO(placed)) as archive:
        model = archive.read("3D/3dmodel.model").decode()
    assert "transform=" in model
    assert "42 42 0" in model
    assert "6.123234e-17 -1 0 1 6.123234e-17 0 0 0 1" in model


def test_real_output_rejects_hidden_multi_plate_result():
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Metadata/plate_1.gcode", b"G1 X10 Y10")
        archive.writestr("Metadata/plate_2.gcode", b"G1 X20 Y20")
    inspection = inspect_slice_output(output.getvalue(), PrinterBuildVolume(256, 256, 250))
    assert inspection.plate_count == 2
    assert inspection.plate_names == ("Metadata/plate_1.gcode", "Metadata/plate_2.gcode")


def test_real_output_rejects_toolpath_outside_bed():
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("Metadata/plate_1.gcode", b"; layer num/total_layer_count: 1/1\nG1 X300 Y10 E1\n; EXECUTABLE_BLOCK_END")
    try:
        inspect_slice_output(output.getvalue(), PrinterBuildVolume(256, 256, 250))
    except SlicePlanningError as exc:
        assert "超出打印板" in str(exc)
    else:
        raise AssertionError("out-of-bed toolpath should fail validation")


def test_sliced_output_metadata_binds_target_printer_without_touching_gcode():
    source = _source_3mf()
    output = BytesIO()
    with ZipFile(BytesIO(source), "r") as original, ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for item in original.infolist():
            archive.writestr(item, original.read(item.filename))
        archive.writestr(
            "Metadata/slice_info.config",
            b'<?xml version="1.0"?><config><plate><metadata key="printer_model_id" value=""/></plate></config>',
        )
        archive.writestr("Metadata/plate_1.gcode", b"; real gcode")
    patched = patch_sliced_output_printer_metadata(output.getvalue(), printer_model="Bambu Lab A1 mini")
    with ZipFile(BytesIO(patched)) as archive:
        metadata = archive.read("Metadata/slice_info.config").decode()
        assert 'key="printer_model_id" value="N1"' in metadata
        assert archive.read("Metadata/plate_1.gcode") == b"; real gcode"


def test_sliced_output_removes_editable_model_payload_for_direct_send():
    output = BytesIO()
    model = b'''<?xml version="1.0"?><model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="2" type="model"/></resources><build><item objectid="2"/></build></model>'''
    settings = b'''<?xml version="1.0"?><config><object id="2"/><plate><metadata key="gcode_file" value="Metadata/plate_1.gcode"/></plate><assemble><assemble_item object_id="2"/></assemble></config>'''
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", model)
        archive.writestr("3D/Objects/object_1.model", b"editable mesh")
        archive.writestr("3D/_rels/3dmodel.model.rels", b"editable relation")
        archive.writestr("Metadata/model_settings.config", settings)
        archive.writestr("Metadata/plate_1.gcode", b"; complete gcode")
        archive.writestr("Metadata/slice_info.config", b"<config/>")

    patched = make_direct_sendable_sliced_output(output.getvalue())
    with ZipFile(BytesIO(patched)) as archive:
        names = set(archive.namelist())
        assert "3D/Objects/object_1.model" not in names
        assert "3D/_rels/3dmodel.model.rels" not in names
        model_root = ElementTree.fromstring(archive.read("3D/3dmodel.model"))
        assert not any(list(node) for node in model_root.iter() if node.tag.rsplit("}", 1)[-1] in {"resources", "build"})
        settings_root = ElementTree.fromstring(archive.read("Metadata/model_settings.config"))
        assert [node.tag.rsplit("}", 1)[-1] for node in settings_root] == ["plate"]
        assert archive.read("Metadata/plate_1.gcode") == b"; complete gcode"
