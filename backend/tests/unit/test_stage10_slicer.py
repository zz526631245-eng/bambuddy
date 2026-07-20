import pytest

from backend.app.services.production_slicer import (
    PrinterBuildVolume,
    SlicePlanningError,
    SourceDimensions,
    plan_slice,
)


def test_auto_pack_capacity_changes_with_virtual_printer_size():
    source = SourceDimensions(width_mm=80, depth_mm=80, height_mm=20)
    a1 = plan_slice(
        strategy="auto_pack",
        requested_quantity=10,
        configured_units_per_plate=1,
        source=source,
        printer=PrinterBuildVolume(width_mm=200, depth_mm=200, height_mm=250),
    )
    a2l = plan_slice(
        strategy="auto_pack",
        requested_quantity=10,
        configured_units_per_plate=1,
        source=source,
        printer=PrinterBuildVolume(width_mm=300, depth_mm=300, height_mm=300),
    )

    assert a1.actual_units_per_plate == 4
    assert a1.plate_count == 3
    assert a2l.actual_units_per_plate == 9
    assert a2l.plate_count == 2
    assert a1.actual_units_per_plate != a2l.actual_units_per_plate
    assert a1.rearranged is True
    assert len(a1.placements) == 4


def test_fixed_plate_keeps_layout_and_splits_large_product_into_multiple_plates():
    result = plan_slice(
        strategy="fixed_plate",
        requested_quantity=5,
        configured_units_per_plate=1,
        source=SourceDimensions(width_mm=180, depth_mm=180, height_mm=220),
        printer=PrinterBuildVolume(width_mm=200, depth_mm=200, height_mm=250),
        source_plate_count=1,
    )

    assert result.actual_units_per_plate == 1
    assert result.plate_count == 5
    assert result.rearranged is False
    assert result.placements == []


def test_slice_fails_with_clear_reason_when_model_does_not_fit_height():
    with pytest.raises(SlicePlanningError, match="高度"):
        plan_slice(
            strategy="auto_pack",
            requested_quantity=1,
            configured_units_per_plate=1,
            source=SourceDimensions(width_mm=40, depth_mm=40, height_mm=300),
            printer=PrinterBuildVolume(width_mm=200, depth_mm=200, height_mm=250),
        )


def test_fixed_plate_rejects_invalid_capacity():
    with pytest.raises(SlicePlanningError, match="每盘套数"):
        plan_slice(
            strategy="fixed_plate",
            requested_quantity=1,
            configured_units_per_plate=0,
            source=SourceDimensions(width_mm=10, depth_mm=10, height_mm=10),
            printer=PrinterBuildVolume(width_mm=200, depth_mm=200, height_mm=250),
        )


def test_multi_plate_fixed_is_one_product_per_source_plate_without_rearranging():
    result = plan_slice(
        strategy="multi_plate_fixed",
        requested_quantity=4,
        configured_units_per_plate=1,
        source=SourceDimensions(width_mm=500, depth_mm=500, height_mm=500),
        printer=PrinterBuildVolume(width_mm=200, depth_mm=200, height_mm=200),
        source_plate_count=3,
    )
    assert result.actual_units_per_plate == 1
    assert result.plate_count == 4
    assert result.rearranged is False
    assert result.placements == []
