"""Keep bound real printers visible to the production allocator.

Real printers and production printer profiles are intentionally separate
concepts: a profile describes the capabilities of a printer model, while a
``Printer`` row describes one connected device.  This module supplies the
small compatibility bridge between them.  It is safe to call repeatedly and
also repairs older installations that already have printers but no profiles.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.printer import Printer
from backend.app.models.printer_profile import PrinterProfile
from backend.app.services.production_slicer import _printer_build_volume


def _model_token(model: str) -> str:
    token = re.sub(r"[^A-Z0-9]+", "-", model.upper()).strip("-")
    return token or "UNKNOWN"


async def _existing_generic_profile(db: AsyncSession, model: str) -> PrinterProfile | None:
    """Find an active, automatic profile that is not location-restricted."""

    return await db.scalar(
        select(PrinterProfile)
        .where(
            PrinterProfile.printer_model == model,
            PrinterProfile.is_active.is_(True),
            PrinterProfile.auto_production_enabled.is_(True),
            PrinterProfile.location.is_(None),
        )
        .order_by(PrinterProfile.id)
    )


async def ensure_generic_profile_for_model(
    db: AsyncSession,
    model: str | None,
) -> PrinterProfile | None:
    """Ensure one enabled, model-wide profile exists for a bound printer.

    Existing location-specific profiles are preserved.  A model-wide profile
    is added only when needed, so a newly bound device at another location is
    not accidentally excluded by an older location-specific configuration.
    """

    normalized_model = str(model or "").strip()
    if not normalized_model:
        return None

    profile = await _existing_generic_profile(db, normalized_model)
    if profile is not None:
        return profile

    token = _model_token(normalized_model)
    base_code = f"AUTO-{token}"
    code = base_code
    suffix = 2
    while await db.scalar(select(PrinterProfile.id).where(PrinterProfile.code == code)) is not None:
        code = f"{base_code}-{suffix}"
        suffix += 1

    volume = _printer_build_volume(normalized_model)
    profile = PrinterProfile(
        code=code,
        name=f"自动生产 {normalized_model}",
        printer_model=normalized_model,
        nozzle_diameter=0.4,
        version=1,
        location=None,
        profile_group="auto-bound-printer",
        auto_production_enabled=True,
        is_active=True,
        supported_materials=[],
        supported_colors=[],
        build_width_mm=volume.width_mm,
        build_depth_mm=volume.depth_mm,
        build_height_mm=volume.height_mm,
    )
    db.add(profile)
    await db.flush()
    return profile


async def ensure_profiles_for_active_printers(db: AsyncSession) -> int:
    """Repair and maintain production profiles for all active real printers."""

    models = list(
        (
            await db.execute(
                select(Printer.model)
                .where(Printer.is_active.is_(True), Printer.model.is_not(None))
                .distinct()
                .order_by(Printer.model)
            )
        ).scalars()
    )
    created = 0
    for model in models:
        before = await _existing_generic_profile(db, str(model))
        await ensure_generic_profile_for_model(db, str(model))
        if before is None:
            created += 1
    return created
