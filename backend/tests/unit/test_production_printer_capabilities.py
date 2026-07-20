"""Material/colour matching contract for production allocation.

These tests deliberately describe the shared capability contract used by both
virtual printers and future real-printer adapters.  They must pass without a
printer connection or MQTT state.
"""

from backend.app.services.production_printer_capabilities import (
    PrinterCapabilities,
    match_filament_requirements,
)


def test_matching_requires_material_and_colour_from_the_loaded_printer_state():
    requirements = [{"slot": 0, "material": "PLA", "color": "#FF0000"}]
    capabilities = PrinterCapabilities(
        supported_materials=("PLA",),
        supported_colors=("#FF0000",),
        loaded_filaments=({"slot": 0, "material": "PLA", "color": "#FF0000"},),
    )

    result = match_filament_requirements(requirements, capabilities)

    assert result.matched is True
    assert result.reason is None


def test_matching_rejects_wrong_loaded_colour_even_when_material_matches():
    requirements = [{"slot": 0, "material": "PLA", "color": "#FF0000"}]
    capabilities = PrinterCapabilities(
        supported_materials=("PLA",),
        supported_colors=("#FF0000", "#0000FF"),
        loaded_filaments=({"slot": 0, "material": "PLA", "color": "#0000FF"},),
    )

    result = match_filament_requirements(requirements, capabilities)

    assert result.matched is False
    assert result.reason == "filament_color_mismatch"


def test_empty_loaded_state_is_not_treated_as_a_match_for_required_filament():
    result = match_filament_requirements(
        [{"slot": 0, "material": "PETG", "color": "#FFFFFF"}],
        PrinterCapabilities(
            supported_materials=("PETG",),
            supported_colors=("#FFFFFF",),
            loaded_filaments=(),
        ),
    )

    assert result.matched is False
    assert result.reason == "filament_not_loaded"
