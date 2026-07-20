"""Shared material/colour capability matching for production allocation.

The matcher is intentionally independent from MQTT and from the virtual
printer implementation.  A real-printer adapter can feed its current AMS
state into the same ``PrinterCapabilities`` value later without changing
production-order semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def normalize_material(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_color(value: Any) -> str:
    """Normalise RGB/RGBA hex values to a comparable six-digit form."""

    raw = str(value or "").strip().lstrip("#").upper()
    named = {
        "RED": "FF0000",
        "红": "FF0000",
        "红色": "FF0000",
        "WHITE": "FFFFFF",
        "白": "FFFFFF",
        "白色": "FFFFFF",
        "BLACK": "000000",
        "黑": "000000",
        "黑色": "000000",
        "BLUE": "0000FF",
        "蓝": "0000FF",
        "蓝色": "0000FF",
        "GREEN": "00FF00",
        "绿": "00FF00",
        "绿色": "00FF00",
        "YELLOW": "FFFF00",
        "黄": "FFFF00",
        "黄色": "FFFF00",
    }
    raw = named.get(raw, raw)
    if len(raw) == 8:
        raw = raw[:6]
    return raw


@dataclass(frozen=True)
class PrinterCapabilities:
    """Capabilities and currently loaded filament state of any printer."""

    supported_materials: tuple[str, ...] = ()
    supported_colors: tuple[str, ...] = ()
    loaded_filaments: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class FilamentMatchResult:
    matched: bool
    reason: str | None = None
    slot: int | None = None


def _requirement_slot(requirement: dict[str, Any], fallback: int) -> int:
    raw = requirement.get("slot", fallback)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback


def match_filament_requirements(
    requirements: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    capabilities: PrinterCapabilities,
) -> FilamentMatchResult:
    """Check source-file filament requirements against one printer.

    ``loaded_filaments`` is authoritative for the current job: a printer that
    merely supports PLA but has no PLA loaded must not be selected.  Empty
    requirements preserve the legacy Stage 9 behaviour and always match.
    """

    if not requirements:
        return FilamentMatchResult(matched=True)

    supported_materials = {normalize_material(item) for item in capabilities.supported_materials if item}
    supported_colors = {normalize_color(item) for item in capabilities.supported_colors if item}
    loaded_by_slot = {
        _requirement_slot(item, index): item
        for index, item in enumerate(capabilities.loaded_filaments)
        if isinstance(item, dict)
    }

    for index, requirement in enumerate(requirements):
        if not isinstance(requirement, dict):
            continue
        slot = _requirement_slot(requirement, index)
        expected_material = normalize_material(requirement.get("material"))
        expected_color = normalize_color(requirement.get("color") or requirement.get("color_hex"))

        if expected_material and supported_materials and expected_material not in supported_materials:
            return FilamentMatchResult(False, "material_not_supported", slot)
        if expected_color and supported_colors and expected_color not in supported_colors:
            return FilamentMatchResult(False, "color_not_supported", slot)

        loaded = loaded_by_slot.get(slot)
        if loaded is None:
            return FilamentMatchResult(False, "filament_not_loaded", slot)
        actual_material = normalize_material(loaded.get("material") or loaded.get("tray_type"))
        actual_color = normalize_color(loaded.get("color") or loaded.get("tray_color"))
        if expected_material and actual_material != expected_material:
            return FilamentMatchResult(False, "filament_material_mismatch", slot)
        if expected_color and actual_color != expected_color:
            return FilamentMatchResult(False, "filament_color_mismatch", slot)

    return FilamentMatchResult(matched=True)


def capabilities_from_rows(
    *,
    supported_materials: list[str] | tuple[str, ...] | None,
    supported_colors: list[str] | tuple[str, ...] | None,
    loaded_filaments: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
) -> PrinterCapabilities:
    """Build a capability object from persisted JSON columns safely."""

    return PrinterCapabilities(
        supported_materials=tuple(str(value) for value in (supported_materials or []) if value),
        supported_colors=tuple(str(value) for value in (supported_colors or []) if value),
        loaded_filaments=tuple(value for value in (loaded_filaments or []) if isinstance(value, dict)),
    )
