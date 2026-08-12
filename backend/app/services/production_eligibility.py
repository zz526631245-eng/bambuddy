"""Stage 9/13 production eligibility without printer communication.

The allocator uses persisted configuration plus the normalized Stage 13
heartbeat snapshot. It does not read MQTT state, connect to a printer, or
invoke any print command.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.library import LibraryFile
from backend.app.models.material_type import MaterialType
from backend.app.models.print_queue import PrintQueueItem
from backend.app.models.printer import Printer
from backend.app.models.printer_profile import PrinterProfile
from backend.app.models.product_file import ProductFile
from backend.app.models.production import PlateJob, PlateJobStatus
from backend.app.models.virtual_printer import VirtualPrinter
from backend.app.services.production_printer_capabilities import (
    capabilities_from_rows,
    match_filament_requirements,
)
from backend.app.services.production_printer_status import availability
from backend.app.services.production_slicer import (
    PrinterBuildVolume,
    SlicePlanningError,
    _absolute_library_path,
    _printer_build_volume,
    assess_source_for_printer,
)

ACTIVE_QUEUE_STATUSES = ("pending", "printing")
ACTIVE_VIRTUAL_JOB_STATUSES = (
    PlateJobStatus.ASSIGNED.value,
    PlateJobStatus.READY.value,
    PlateJobStatus.PRINTING.value,
    PlateJobStatus.WAITING_CLEANUP.value,
)


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


async def _source_geometry_context(db: AsyncSession, job: PlateJob) -> tuple[ProductFile | None, Path | None, str]:
    """Resolve the immutable source file used for geometry-aware routing."""

    product_file = await db.get(ProductFile, job.requirement.product_file_id)
    snapshot = job.requirement.recipe_snapshot or {}
    file_snapshot = snapshot.get("product_file_snapshot") or {}
    source_ids = file_snapshot.get("source_file_ids") or []
    if file_snapshot.get("production_mode") == "multi_plate" and source_ids:
        index = max(0, int(job.source_plate_index))
        if index < len(source_ids):
            selected = await db.get(ProductFile, int(source_ids[index]))
            if selected is not None:
                product_file = selected
    library = await db.get(LibraryFile, product_file.library_file_id) if product_file else None
    path = _absolute_library_path(library.file_path if library else None)
    strategy = "multi_plate_fixed" if file_snapshot.get("production_mode") == "multi_plate" else (product_file.strategy if product_file else "auto_pack")
    return product_file, path, strategy


def _profile_volume(profile: PrinterProfile) -> PrinterBuildVolume:
    if min(profile.build_width_mm, profile.build_depth_mm, profile.build_height_mm) > 0:
        return PrinterBuildVolume(profile.build_width_mm, profile.build_depth_mm, profile.build_height_mm)
    return _printer_build_volume(profile.printer_model)


def _has_mesh_geometry(path: Path) -> bool:
    """Return whether a legacy/source archive has inspectable mesh vertices."""

    try:
        with zipfile.ZipFile(path) as archive:
            return any(
                name.endswith(".model") and b"<vertex" in archive.read(name).lower()
                for name in archive.namelist()
            )
    except (OSError, zipfile.BadZipFile):
        return False


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
    filament_requirements = file_snapshot.get("filament_requirements") or []
    if not filament_requirements and file_snapshot.get("product_color"):
        # A single-colour product variant can be matched without explicit
        # per-slot metadata. Multi-colour files should provide slot records.
        filament_requirements = [{"slot": 0, "color": file_snapshot["product_color"]}]
    compatible_models = file_snapshot.get("compatible_printer_models") or []
    if not profile_ids and compatible_models:
        # File metadata is a preference hint, not a hard compatibility rule.
        # Actual transformed geometry below decides whether another model can
        # safely print the source file.
        profile_rows = await db.execute(
            select(PrinterProfile)
            .where(PrinterProfile.is_active.is_(True))
            .where(PrinterProfile.auto_production_enabled.is_(True))
            .order_by(PrinterProfile.id)
        )
        profiles = list(profile_rows.scalars().all())
        rank = {model: index for index, model in enumerate(compatible_models)}
        profiles.sort(key=lambda row: (rank.get(row.printer_model, len(rank)), row.id))
        profile_ids = [int(row.id) for row in profiles]
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
    selected_profile: PrinterProfile | None = None
    selected_printer: Printer | None = None
    real_target_seen = False
    virtual_fallbacks: list[tuple[PrinterProfile, VirtualPrinter, int]] = []
    real_candidates: list[tuple[int, int, PrinterProfile, Printer]] = []
    product_file, source_path, source_strategy = await _source_geometry_context(db, job)
    for profile_id in profile_ids:
        candidate_profile = await db.get(PrinterProfile, profile_id)
        if (
            not candidate_profile
            or not candidate_profile.is_active
            or not candidate_profile.auto_production_enabled
        ):
            continue
        # ``size_class`` is only a UI hint.  The authoritative compatibility
        # check below uses the transformed 3MF geometry and this profile's
        # actual build volume, so future printer models need no hard-coded
        # compatibility matrix.
        # ``compatible_printer_models`` is only a preference ordering.  A
        # model outside that list remains eligible when its real build volume
        # can hold the complete source product set.
        geometry_capacity = 1
        if source_path is not None and source_path.exists() and zipfile.is_zipfile(source_path) and _has_mesh_geometry(source_path) and product_file is not None:
            try:
                geometry_capacity = assess_source_for_printer(
                    source_path,
                    _profile_volume(candidate_profile),
                    strategy=source_strategy,
                    configured_units_per_plate=float(product_file.units_per_plate),
                ).actual_units_per_plate
            except (OSError, SlicePlanningError, ValueError):
                # A real printer model may be configured but physically unable
                # to hold this complete product set. Try another model.
                continue
        virtual_model_names = {"N2S": "A1", "N9": "A2L"}
        virtual_query = select(VirtualPrinter).where(
            VirtualPrinter.model.in_(
                [code for code, name in virtual_model_names.items() if name == candidate_profile.printer_model]
            )
        )
        virtual_candidates = list((await db.execute(virtual_query.order_by(VirtualPrinter.id))).scalars().all())
        for virtual in virtual_candidates:
            try:
                virtual_capacity = geometry_capacity
                if source_path is not None and source_path.exists() and zipfile.is_zipfile(source_path) and _has_mesh_geometry(source_path) and product_file is not None:
                    virtual_capacity = assess_source_for_printer(
                        source_path,
                        PrinterBuildVolume(virtual.build_width_mm, virtual.build_depth_mm, virtual.build_height_mm),
                        strategy=source_strategy,
                        configured_units_per_plate=float(product_file.units_per_plate),
                    ).actual_units_per_plate
                virtual_fallbacks.append((candidate_profile, virtual, virtual_capacity))
            except (OSError, SlicePlanningError, ValueError):
                continue
        configured_real = await db.scalar(
            select(exists().where(Printer.is_active.is_(True), Printer.model == candidate_profile.printer_model))
        )
        if configured_real:
            # A real device that is busy/offline/mismatched still blocks the
            # virtual test fallback for this model. Other compatible real
            # models continue through the outer candidate loop.
            real_target_seen = True
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
        if candidate_printers:
            # Keep this branch for clarity: the existence check above also
            # covers busy/offline devices before the free-printer query.
            real_target_seen = True
        if not candidate_printers and candidate_profile.location:
            # A profile can predate the real-printer adapter (for example the
            # Stage 11 virtual profile may carry a test-only location).  A
            # stale location must not hide an otherwise compatible real
            # printer; when there is no exact location hit, fall back to the
            # model and live loaded-filament contract.
            relaxed_query = (
                select(Printer)
                .where(
                    Printer.is_active.is_(True),
                    Printer.model == candidate_profile.printer_model,
                    ~busy_printer,
                )
                .order_by(Printer.id)
            )
            if db.get_bind().dialect.name == "postgresql":
                relaxed_query = relaxed_query.with_for_update(skip_locked=True, of=Printer)
            candidate_printers = list((await db.execute(relaxed_query)).scalars().all())
            if candidate_printers:
                real_target_seen = True
        for candidate_printer in candidate_printers:
            if not await availability(db, "printer", candidate_printer.id):
                continue
            capability_result = match_filament_requirements(
                filament_requirements,
                capabilities_from_rows(
                    supported_materials=candidate_profile.supported_materials,
                    supported_colors=candidate_profile.supported_colors,
                    loaded_filaments=candidate_printer.loaded_filaments,
                ),
            )
            if not capability_result.matched and capability_result.reason in {
                "material_not_supported",
                "color_not_supported",
            }:
                # For a real printer the scanned direct-feed/AMS snapshot is
                # the current authority.  Static profile capability lists are
                # retained for virtual fallback and as documentation, but a
                # stale Stage 11 list must not reject a scanned PETG/white
                # spool that is actually loaded on the device.
                capability_result = match_filament_requirements(
                    filament_requirements,
                    capabilities_from_rows(
                        supported_materials=[],
                        supported_colors=[],
                        loaded_filaments=candidate_printer.loaded_filaments,
                    ),
                )
            if not capability_result.matched:
                continue
            real_candidates.append((geometry_capacity, candidate_printer.id, candidate_profile, candidate_printer))
    if real_candidates:
        # Prefer the candidate that can keep more complete product sets on a
        # plate; ties remain deterministic by profile/printer id.
        _, _, selected_profile, selected_printer = sorted(
            real_candidates, key=lambda item: (-item[0], item[2].id, item[1])
        )[0]
    if selected_profile is not None and selected_printer is not None:
        required_filament_types = None
        material_type_id = snapshot.get("material_type_id")
        if material_type_id:
            material = await db.get(MaterialType, int(material_type_id))
            if material and material.material:
                required_filament_types = json.dumps([material.material.strip().upper()])

        return ProductionAssignment(
            printer=selected_printer,
            profile=selected_profile,
            required_filament_types=required_filament_types,
        )

    if real_target_seen:
        return None

    # Virtual printers remain available for the Stage 11 software workflow,
    # but an enabled real printer is always selected first when both match.
    for candidate_profile, virtual, virtual_capacity in virtual_fallbacks:
        if not await availability(db, "virtual_printer", virtual.id):
            continue
        virtual_busy = await db.scalar(
            select(
                exists().where(
                    PlateJob.virtual_printer_id == virtual.id,
                    PlateJob.status.in_(ACTIVE_VIRTUAL_JOB_STATUSES),
                )
            )
        )
        if virtual_busy:
            continue
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
            and virtual_capacity >= 1
        ):
            return ProductionAssignment(
                printer=None,
                profile=candidate_profile,
                required_filament_types=None,
                virtual_printer=virtual,
            )
    return None
