"""Stage 9 production eligibility without printer communication.

The allocator deliberately uses persisted configuration only.  It does not
read MQTT state, connect to a printer, or invoke any print command.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.material_type import MaterialType
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.production import PlateJob
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.services.production_printer_capabilities import (
    capabilities_from_rows,
    match_filament_requirements,
)

ACTIVE_QUEUE_STATUSES = ("pending", "printing")


def _is_a1_class(model: str | None) -> bool:
    """Return whether a profile represents an A1/A1 Mini class printer."""

    normalized = "".join(str(model or "").upper().split())
    return normalized in {"A1", "A1MINI", "A1M", "N1", "N2S", "A11", "A12", "A04"}


@dataclass(frozen=True)
class ProductionAssignment:
    printer: Printer | None
    profile: PrinterProfile
    required_filament_types: str | None
    virtual_printer: VirtualPrinter | None = None


async def find_assignment(db: AsyncSession, job: PlateJob) -> ProductionAssignment | None:
    """Lock and return one configured, currently unreserved printer.

    PostgreSQL skips printer rows already locked by another allocator. SQLite
    is serialized by ``production_allocator`` before this function is called.
    """

    snapshot = job.requirement.recipe_snapshot or {}
    profile_ids: list[int] = []
    for raw_id in (
        job.printer_profile_id,
        snapshot.get("printer_profile_id"),
        *(snapshot.get("compatible_profile_ids") or []),
    ):
        if raw_id and int(raw_id) not in profile_ids:
            profile_ids.append(int(raw_id))
    file_snapshot = snapshot.get("product_file_snapshot") or {}
    product_size_class = (
        snapshot.get("product_size_class")
        or file_snapshot.get("product_size_class")
        or "standard"
    )
    filament_requirements = file_snapshot.get("filament_requirements") or []
    if not filament_requirements and file_snapshot.get("product_color"):
        # A single-colour product variant can be matched without explicit
        # per-slot metadata. Multi-colour files should provide slot records.
        filament_requirements = [{"slot": 0, "color": file_snapshot["product_color"]}]
    compatible_models = file_snapshot.get("compatible_printer_models") or []
    if not profile_ids and compatible_models:
        profile_rows = await db.execute(
            select(PrinterProfile.id)
            .where(PrinterProfile.printer_model.in_(compatible_models))
            .where(PrinterProfile.is_active.is_(True))
            .where(PrinterProfile.auto_production_enabled.is_(True))
            .order_by(PrinterProfile.id)
        )
        profile_ids = [int(value) for value in profile_rows.scalars().all()]
    # A product-owned source file may intentionally leave printer models open;
    # in that case use every active production profile and let capability
    # matching (material/colour plus current loaded filament) decide.
    if not profile_ids and not compatible_models:
        profile_rows = await db.execute(
            select(PrinterProfile.id)
            .where(PrinterProfile.is_active.is_(True))
            .where(PrinterProfile.auto_production_enabled.is_(True))
            .order_by(PrinterProfile.id)
        )
        profile_ids = [int(value) for value in profile_rows.scalars().all()]
    if not profile_ids:
        return None

    busy_printer = exists(
        select(PrintQueueItem.id).where(
            PrintQueueItem.printer_id == Printer.id,
            PrintQueueItem.status.in_(ACTIVE_QUEUE_STATUSES),
        )
    )
    profile = None
    printer = None
    for profile_id in profile_ids:
        candidate_profile = await db.get(PrinterProfile, profile_id)
        if (
            not candidate_profile
            or not candidate_profile.is_active
            or not candidate_profile.auto_production_enabled
        ):
            continue
        # A large product is a user-declared routing constraint. It excludes
        # A1-class printers before capability matching; bed dimensions and
        # plate capacity remain slicer/planning concerns.
        if product_size_class == "large" and _is_a1_class(candidate_profile.printer_model):
            continue
        compatible_models = file_snapshot.get("compatible_printer_models") or []
        if compatible_models and candidate_profile.printer_model not in compatible_models:
            continue
        virtual_model_names = {"N2S": "A1", "N9": "A2L"}
        virtual_query = select(VirtualPrinter).where(VirtualPrinter.model.in_([code for code, name in virtual_model_names.items() if name == candidate_profile.printer_model]))
        virtual_candidates = list((await db.execute(virtual_query.order_by(VirtualPrinter.id))).scalars().all())
        for virtual in virtual_candidates:
            capability_result = match_filament_requirements(
                filament_requirements,
                capabilities_from_rows(
                    supported_materials=virtual.supported_materials,
                    supported_colors=virtual.supported_colors,
                    loaded_filaments=virtual.loaded_filaments,
                ),
            )
            if (
                capability_result.matched
                and virtual.units_per_plate_capacity >= max(1, int(file_snapshot.get("units_per_plate", 1)))
            ):
                return ProductionAssignment(printer=None, profile=candidate_profile, required_filament_types=None, virtual_printer=virtual)
        query = (
            select(Printer)
            .where(
                Printer.is_active.is_(True),
                Printer.model == candidate_profile.printer_model,
                ~busy_printer,
            )
            .order_by(Printer.id)
        )
        if candidate_profile.location:
            query = query.where(Printer.location == candidate_profile.location)
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True, of=Printer)
        candidate_printers = list((await db.execute(query)).scalars().all())
        for candidate_printer in candidate_printers:
            capability_result = match_filament_requirements(
                filament_requirements,
                capabilities_from_rows(
                    supported_materials=candidate_profile.supported_materials,
                    supported_colors=candidate_profile.supported_colors,
                    loaded_filaments=candidate_printer.loaded_filaments,
                ),
            )
            if not capability_result.matched:
                continue
            profile = candidate_profile
            printer = candidate_printer
            break
        if printer is not None:
            break
    if profile is None or printer is None:
        return None

    required_filament_types = None
    material_type_id = snapshot.get("material_type_id")
    if material_type_id:
        material = await db.get(MaterialType, int(material_type_id))
        if material and material.material:
            required_filament_types = json.dumps([material.material.strip().upper()])

    return ProductionAssignment(
        printer=printer,
        profile=profile,
        required_filament_types=required_filament_types,
    )
