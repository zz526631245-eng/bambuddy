"""Stage 10 slicing planner and real slicer adapter.

The deterministic planner remains available for safe capacity previews.  The
real adapter sends the original product 3MF to Bambuddy's existing slicer API
sidecar, preserving embedded process/object settings and never contacting a
printer.
"""

from __future__ import annotations

import json
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.models.library import LibraryFile
from backend.app.models.product_file import ProductFile
from backend.app.models.production import PlateJob
from backend.app.models.slice_artifact import SliceArtifact
from backend.app.models.virtual_printer import VirtualPrinter


class SlicePlanningError(ValueError):
    """A source file cannot be planned for the requested printer volume."""


@dataclass(frozen=True)
class SourceDimensions:
    width_mm: float
    depth_mm: float
    height_mm: float


@dataclass(frozen=True)
class PrinterBuildVolume:
    width_mm: float
    depth_mm: float
    height_mm: float


@dataclass(frozen=True)
class SliceOutputInspection:
    """Facts read back from the *real* slicer output.

    The planner is only allowed to propose a candidate quantity.  The
    returned 3MF/G-code is the authority for how many plates were actually
    produced.
    """

    plate_count: int
    plate_names: tuple[str, ...]
    xy_bounds_mm: tuple[float, float, float, float] | None = None


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return a deterministic 2-D convex hull without a geometry package."""

    unique = sorted(set(points))
    if len(unique) <= 2:
        return unique

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in unique:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(unique):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def _rotate_xy(point: tuple[float, float], rotation_deg: float) -> tuple[float, float]:
    radians = math.radians(rotation_deg)
    cosine, sine = math.cos(radians), math.sin(radians)
    return (point[0] * cosine - point[1] * sine, point[0] * sine + point[1] * cosine)


def _polygon_bounds(polygon: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def _polygons_overlap(
    first: list[tuple[float, float]], second: list[tuple[float, float]], clearance_mm: float
) -> bool:
    """Conservative SAT overlap test for convex projected footprints."""

    def axes(polygon: list[tuple[float, float]]) -> list[tuple[float, float]]:
        result = []
        for index, point in enumerate(polygon):
            other = polygon[(index + 1) % len(polygon)]
            edge = (other[0] - point[0], other[1] - point[1])
            result.append((-edge[1], edge[0]))
        return result

    def project(polygon: list[tuple[float, float]], axis: tuple[float, float]) -> tuple[float, float]:
        values = [point[0] * axis[0] + point[1] * axis[1] for point in polygon]
        return min(values), max(values)

    if not first or not second:
        return False
    for axis in [*axes(first), *axes(second)]:
        first_min, first_max = project(first, axis)
        second_min, second_max = project(second, axis)
        if first_max + clearance_mm <= second_min or second_max + clearance_mm <= first_min:
            return False
    return True


def inspect_projected_footprint(path: Path) -> list[tuple[float, float]]:
    """Read the real XY projection of the source mesh, not just its bbox."""

    try:
        with zipfile.ZipFile(path) as archive:
            points: list[tuple[float, float]] = []
            for name in archive.namelist():
                if not name.endswith(".model"):
                    continue
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError:
                    continue
                for element in root.iter():
                    if element.tag.rsplit("}", 1)[-1] == "vertex":
                        try:
                            points.append((float(element.attrib["x"]), float(element.attrib["y"])))
                        except (KeyError, TypeError, ValueError):
                            continue
            hull = _convex_hull(points)
            if len(hull) < 3:
                raise SlicePlanningError("3MF 没有可用于摆盘的 XY 投影轮廓")
            return hull
    except SlicePlanningError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise SlicePlanningError(f"无法读取 3MF 投影轮廓：{exc}") from exc


def _projected_layout(
    footprint: list[tuple[float, float]],
    quantity: int,
    printer: PrinterBuildVolume,
    *,
    clearance_mm: float = 2.0,
) -> list[dict[str, float]]:
    """Find a collision-free XY/Z-rotation layout for one candidate plate."""

    if quantity < 1:
        return []
    best: list[dict[str, float]] | None = None
    for rotation in (0.0, 90.0, 180.0, 270.0):
        rotated = [_rotate_xy(point, rotation) for point in footprint]
        min_x, min_y, max_x, max_y = _polygon_bounds(rotated)
        width, depth = max_x - min_x, max_y - min_y
        if width + clearance_mm > printer.width_mm or depth + clearance_mm > printer.depth_mm:
            continue
        for columns in range(1, quantity + 1):
            rows = math.ceil(quantity / columns)
            if columns * width + (columns + 1) * clearance_mm > printer.width_mm:
                continue
            if rows * depth + (rows + 1) * clearance_mm > printer.depth_mm:
                continue
            candidate: list[dict[str, float]] = []
            polygons: list[list[tuple[float, float]]] = []
            for index in range(quantity):
                column, row = index % columns, index // columns
                center_x = clearance_mm + width / 2 + column * (width + clearance_mm)
                center_y = clearance_mm + depth / 2 + row * (depth + clearance_mm)
                polygon = [(point[0] - min_x + center_x - width / 2, point[1] - min_y + center_y - depth / 2) for point in rotated]
                if any(_polygons_overlap(polygon, other, clearance_mm) for other in polygons):
                    candidate = []
                    break
                polygons.append(polygon)
                candidate.append({"x_mm": round(center_x, 3), "y_mm": round(center_y, 3), "rotation_deg": rotation})
            if candidate and (best is None or len(candidate) > len(best)):
                best = candidate
    if best is None:
        raise SlicePlanningError("真实模型投影和安全间距无法在打印板上摆下一个产品")
    return best


def _projected_capacity(
    footprint: list[tuple[float, float]], printer: PrinterBuildVolume, *, clearance_mm: float = 2.0
) -> tuple[int, list[dict[str, float]]]:
    """Find the largest collision-free candidate using the projected shape."""

    min_x, min_y, max_x, max_y = _polygon_bounds(footprint)
    width, depth = max_x - min_x, max_y - min_y
    upper = max(
        1,
        math.floor(printer.width_mm / max(width, 0.001)) * math.floor(printer.depth_mm / max(depth, 0.001)),
    )
    for quantity in range(upper, 0, -1):
        try:
            return quantity, _projected_layout(footprint, quantity, printer, clearance_mm=clearance_mm)
        except SlicePlanningError:
            continue
    raise SlicePlanningError("真实模型投影和安全间距无法在打印板上摆下一个产品")


@dataclass(frozen=True)
class SlicePlan:
    strategy: str
    requested_quantity: int
    actual_units_per_plate: int
    plate_count: int
    source_plate_count: int
    rearranged: bool
    source_dimensions: SourceDimensions
    printer_volume: PrinterBuildVolume
    placements: list[dict[str, float]]

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "requested_quantity": self.requested_quantity,
            "actual_units_per_plate": self.actual_units_per_plate,
            "plate_count": self.plate_count,
            "source_plate_count": self.source_plate_count,
            "rearranged": self.rearranged,
            "source_dimensions_mm": {
                "width": self.source_dimensions.width_mm,
                "depth": self.source_dimensions.depth_mm,
                "height": self.source_dimensions.height_mm,
            },
            "printer_volume_mm": {
                "width": self.printer_volume.width_mm,
                "depth": self.printer_volume.depth_mm,
                "height": self.printer_volume.height_mm,
            },
            "placements": self.placements,
        }


def inspect_3mf(path: Path) -> tuple[SourceDimensions, int]:
    """Read model bounds and source plate count from a 3MF archive."""

    try:
        with zipfile.ZipFile(path) as archive:
            model_name = "3D/3dmodel.model"
            if model_name not in archive.namelist():
                raise SlicePlanningError("3MF 缺少 3D/3dmodel.model 模型文件")
            vertices = []
            # Bambu Studio stores the root resources in 3dmodel.model and
            # mesh vertices in 3D/Objects/*.model. Inspect both forms.
            model_names = [name for name in archive.namelist() if name.endswith(".model")]
            for name in model_names:
                try:
                    root = ElementTree.fromstring(archive.read(name))
                except ElementTree.ParseError:
                    continue
                for element in root.iter():
                    if element.tag.rsplit("}", 1)[-1] != "vertex":
                        continue
                    try:
                        vertices.append(
                            (
                                float(element.attrib["x"]),
                                float(element.attrib["y"]),
                                float(element.attrib["z"]),
                            )
                        )
                    except (KeyError, TypeError, ValueError):
                        continue
            if not vertices:
                raise SlicePlanningError("3MF 模型没有可计算尺寸的顶点")
            xs, ys, zs = zip(*vertices, strict=True)
            dimensions = SourceDimensions(
                width_mm=max(xs) - min(xs),
                depth_mm=max(ys) - min(ys),
                height_mm=max(zs) - min(zs),
            )
            plate_count = 1
            plate_indices = [
                int(match.group(1))
                for name in archive.namelist()
                if (match := re.fullmatch(r"Metadata/plate_(\d+)\.png", name))
            ]
            if plate_indices:
                plate_count = max(plate_indices)
            slice_info = "Metadata/slice_info.config"
            if slice_info in archive.namelist():
                slice_root = ElementTree.fromstring(archive.read(slice_info))
                plate_count = max(plate_count, len([node for node in slice_root.iter() if node.tag.rsplit("}", 1)[-1] == "plate"]))
            return dimensions, plate_count
    except SlicePlanningError:
        raise
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SlicePlanningError(f"无法读取 3MF 源文件：{exc}") from exc


def _validate_dimensions(source: SourceDimensions, printer: PrinterBuildVolume) -> None:
    if min(source.width_mm, source.depth_mm, source.height_mm) <= 0:
        raise SlicePlanningError("源文件模型尺寸必须大于 0")
    if min(printer.width_mm, printer.depth_mm, printer.height_mm) <= 0:
        raise SlicePlanningError("打印机尺寸必须大于 0")
    if source.height_mm > printer.height_mm:
        raise SlicePlanningError(
            f"模型高度 {source.height_mm:g}mm 超过打印机高度 {printer.height_mm:g}mm"
        )


def _grid_capacity(source: SourceDimensions, printer: PrinterBuildVolume) -> tuple[int, list[dict[str, float]]]:
    columns = math.floor(printer.width_mm / source.width_mm)
    rows = math.floor(printer.depth_mm / source.depth_mm)
    if columns < 1 or rows < 1:
        raise SlicePlanningError(
            f"模型底面 {source.width_mm:g}x{source.depth_mm:g}mm 放不进打印机底板 "
            f"{printer.width_mm:g}x{printer.depth_mm:g}mm"
        )
    placements = [
        {
            "x_mm": round((column + 0.5) * source.width_mm, 3),
            "y_mm": round((row + 0.5) * source.depth_mm, 3),
            "rotation_deg": 0,
        }
        for row in range(rows)
        for column in range(columns)
    ]
    return columns * rows, placements


def plan_slice(
    *,
    strategy: str,
    requested_quantity: int,
    configured_units_per_plate: float,
    source: SourceDimensions,
    printer: PrinterBuildVolume,
    source_plate_count: int = 1,
    projected_footprint: list[tuple[float, float]] | None = None,
) -> SlicePlan:
    """Create a fixed-layout or auto-packed deterministic plate plan."""

    if strategy not in {"fixed_plate", "auto_pack", "multi_plate_fixed"}:
        raise SlicePlanningError("摆盘策略必须是 fixed_plate、auto_pack 或 multi_plate_fixed")
    if requested_quantity < 1:
        raise SlicePlanningError("生产数量必须至少为 1")
    if configured_units_per_plate < 1:
        raise SlicePlanningError("每盘套数必须至少为 1")
    if source_plate_count < 1:
        raise SlicePlanningError("源文件盘数必须至少为 1")
    # A multi-plate project is sliced one source-plate job at a time.  The
    # aggregate bounds of all source plates are not a meaningful bed check.
    if strategy != "multi_plate_fixed":
        _validate_dimensions(source, printer)

    if strategy == "multi_plate_fixed":
        return SlicePlan(
            strategy=strategy,
            requested_quantity=requested_quantity,
            actual_units_per_plate=1,
            plate_count=requested_quantity,
            source_plate_count=1,
            rearranged=False,
            source_dimensions=source,
            printer_volume=printer,
            placements=[],
        )

    if strategy == "fixed_plate":
        units = int(configured_units_per_plate)
        plates_for_quantity = math.ceil(requested_quantity / units)
        return SlicePlan(
            strategy=strategy,
            requested_quantity=requested_quantity,
            actual_units_per_plate=units,
            plate_count=plates_for_quantity * source_plate_count,
            source_plate_count=source_plate_count,
            rearranged=False,
            source_dimensions=source,
            printer_volume=printer,
            placements=[],
        )

    if projected_footprint:
        capacity, placements = _projected_capacity(projected_footprint, printer)
    else:
        capacity, placements = _grid_capacity(source, printer)
    return SlicePlan(
        strategy=strategy,
        requested_quantity=requested_quantity,
        actual_units_per_plate=capacity,
        plate_count=math.ceil(requested_quantity / capacity),
        source_plate_count=1,
        rearranged=True,
        source_dimensions=source,
        printer_volume=printer,
        placements=placements,
    )


def _absolute_library_path(file_path: str | None) -> Path | None:
    if not file_path:
        return None
    path = Path(file_path)
    return path if path.is_absolute() else settings.base_dir / path


def slice_settings_fingerprint(
    *,
    source_sha256: str,
    source_version: int,
    strategy: str,
    preferred_slicer: str,
    target_printer_preset: str | None,
    target_printer_model: str | None,
    plate_index: int | None = None,
    plate_quantity: int | None = None,
    source_product_file_id: int | None = None,
) -> str:
    """Return the stable cache key for one exact slicer input set."""

    payload = {
        # Keep cache entries tied to the human-readable output convention so
        # changing a filename does not leave an older, ambiguous artifact in
        # the slice library.
        "output_naming": "plate-quantity-v1",
        "layout_normalization": "preserve-z-v2",
        "layout_algorithm": "projected-footprint-z-rotation-v1",
        "sliced_metadata": "direct-send-gcode-3mf-v1",
        "source_sha256": source_sha256,
        "source_version": source_version,
        "strategy": strategy,
        "preferred_slicer": preferred_slicer,
        "target_printer_preset": target_printer_preset,
        "target_printer_model": target_printer_model,
        "plate_index": plate_index,
        "plate_quantity": plate_quantity,
        "source_product_file_id": source_product_file_id,
        "arrange": False,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def slice_output_filename(
    source_filename: str,
    *,
    plate_index: int,
    plate_quantity: int,
) -> str:
    """Build a filename that states the plate number and units on that plate."""

    if plate_index < 0:
        raise ValueError("plate_index must be non-negative")
    if plate_quantity < 1:
        raise ValueError("plate_quantity must be positive")
    stem = Path(source_filename).stem
    return f"{stem}.plate-{plate_index + 1}.qty-{plate_quantity}.gcode.3mf"


def duplicate_build_items(source_bytes: bytes, copies: int) -> bytes:
    """Duplicate the source 3MF build set without changing print settings.

    A product source file represents one product set.  Auto-packing a plate
    therefore needs multiple build items before the real slicer is called.
    Only the build references are duplicated; meshes, project settings and
    object-level settings are copied byte-for-byte.
    """

    if copies < 1:
        raise SlicePlanningError("每盘套数必须至少为 1")
    if copies == 1:
        return source_bytes
    source = BytesIO(source_bytes)
    output = BytesIO()
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            model_name = "3D/3dmodel.model"
            if model_name not in source_zip.namelist():
                raise SlicePlanningError("3MF 缺少 3D/3dmodel.model 模型文件")
            try:
                root = ElementTree.fromstring(source_zip.read(model_name))
            except ElementTree.ParseError as exc:
                raise SlicePlanningError(f"3MF 模型 XML 无效：{exc}") from exc
            build = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "build"), None)
            if build is None or not list(build):
                raise SlicePlanningError("3MF 缺少可复制的打印对象")
            original_items = list(build)
            for _ in range(1, copies):
                for item in original_items:
                    cloned = ElementTree.fromstring(ElementTree.tostring(item, encoding="utf-8"))
                    for attr_name in cloned.attrib:
                        if attr_name.rsplit("}", 1)[-1].lower() == "uuid":
                            cloned.set(attr_name, str(uuid4()))
                    build.append(cloned)
            # Keep the standard prefixes used by Bambu Studio. Some versions
            # of its parser reject an otherwise equivalent ns0/ns1 rewrite.
            ElementTree.register_namespace("", "http://schemas.microsoft.com/3dmanufacturing/core/2015/02")
            ElementTree.register_namespace("BambuStudio", "http://schemas.bambulab.com/package/2021")
            ElementTree.register_namespace("p", "http://schemas.microsoft.com/3dmanufacturing/production/2015/06")
            model_bytes = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    output_zip.writestr(item, model_bytes if item.filename == model_name else source_zip.read(item.filename))
    except (OSError, zipfile.BadZipFile) as exc:
        raise SlicePlanningError(f"无法读取 3MF 源文件：{exc}") from exc
    return output.getvalue()


def normalize_build_item_positions(source_bytes: bytes) -> bytes:
    """Reset stale XY layout offsets while preserving rotation and Z height.

    Bambu project files can contain an old multi-plate layout with negative
    translations. Passing that layout to ``--arrange`` may make the slicer
    validate the stale coordinates before it repositions objects. X/Y are
    layout metadata, but Z is also the model's height above the build plate;
    reset only X/Y so the slicer can arrange the same oriented objects without
    sinking a model that intentionally has a positive Z offset into the plate.
    """

    source = BytesIO(source_bytes)
    output = BytesIO()
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            model_name = "3D/3dmodel.model"
            if model_name not in source_zip.namelist():
                raise SlicePlanningError("3MF 缺少 3D/3dmodel.model 模型文件")
            try:
                root = ElementTree.fromstring(source_zip.read(model_name))
            except ElementTree.ParseError as exc:
                raise SlicePlanningError(f"3MF 模型 XML 无效：{exc}") from exc
            for item in root.iter():
                if item.tag.rsplit("}", 1)[-1] != "item" or "transform" not in item.attrib:
                    continue
                values = item.attrib["transform"].split()
                if len(values) == 12:
                    item.attrib["transform"] = " ".join([*values[:9], "0", "0", values[11]])
            ElementTree.register_namespace("", "http://schemas.microsoft.com/3dmanufacturing/core/2015/02")
            ElementTree.register_namespace("BambuStudio", "http://schemas.bambulab.com/package/2021")
            ElementTree.register_namespace("p", "http://schemas.microsoft.com/3dmanufacturing/production/2015/06")
            model_bytes = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    output_zip.writestr(item, model_bytes if item.filename == model_name else source_zip.read(item.filename))
    except (OSError, zipfile.BadZipFile) as exc:
        raise SlicePlanningError(f"无法读取 3MF 源文件：{exc}") from exc
    return output.getvalue()


def apply_build_item_layout(
    source_bytes: bytes,
    placements: list[dict[str, float]],
) -> bytes:
    """Write explicit XY/Z-rotation placements into duplicated build items.

    The mesh and every embedded process/object setting remain byte-for-byte
    unchanged.  Only the build-item transform is changed, and only in the
    degrees that are safe for automatic packing: XY translation and rotation
    around the Z axis.  The original Z translation is preserved so a model
    cannot be sunk into the bed.
    """

    source = BytesIO(source_bytes)
    output = BytesIO()
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            model_name = "3D/3dmodel.model"
            root = ElementTree.fromstring(source_zip.read(model_name))
            build = next((node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "build"), None)
            items = [node for node in (list(build) if build is not None else []) if node.tag.rsplit("}", 1)[-1] == "item"]
            if len(items) != len(placements):
                raise SlicePlanningError("摆盘对象数量与产品套数不一致")
            for item, placement in zip(items, placements, strict=True):
                values = item.attrib.get("transform", "").split()
                if not values:
                    values = ["1", "0", "0", "0", "1", "0", "0", "0", "1", "0", "0", "0"]
                if len(values) != 12:
                    raise SlicePlanningError("3MF build item 的变换矩阵无效")
                try:
                    numbers = [float(value) for value in values]
                    x_mm = float(placement["x_mm"])
                    y_mm = float(placement["y_mm"])
                    rotation = float(placement.get("rotation_deg", 0.0))
                except (KeyError, TypeError, ValueError) as exc:
                    raise SlicePlanningError("摆盘坐标无效") from exc
                radians = math.radians(rotation)
                cosine, sine = math.cos(radians), math.sin(radians)
                # Build transforms are row-major.  Left-multiplying by Rz
                # changes only the XY orientation while retaining the source
                # model's Z orientation and height.
                matrix = numbers[:9]
                rotated = [
                    cosine * matrix[0] - sine * matrix[3],
                    cosine * matrix[1] - sine * matrix[4],
                    matrix[2],
                    sine * matrix[0] + cosine * matrix[3],
                    sine * matrix[1] + cosine * matrix[4],
                    matrix[5],
                    matrix[6],
                    matrix[7],
                    matrix[8],
                ]
                item.attrib["transform"] = " ".join(
                    [*(f"{value:.9g}" for value in rotated), f"{x_mm:.9g}", f"{y_mm:.9g}", f"{numbers[11]:.9g}"]
                )
            ElementTree.register_namespace("", "http://schemas.microsoft.com/3dmanufacturing/core/2015/02")
            ElementTree.register_namespace("BambuStudio", "http://schemas.bambulab.com/package/2021")
            ElementTree.register_namespace("p", "http://schemas.microsoft.com/3dmanufacturing/production/2015/06")
            model_bytes = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    output_zip.writestr(item, model_bytes if item.filename == model_name else source_zip.read(item.filename))
    except KeyError as exc:
        raise SlicePlanningError("3MF 缺少 3D/3dmodel.model 模型文件") from exc
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SlicePlanningError(f"无法写入 3MF 摆盘坐标：{exc}") from exc
    return output.getvalue()


def inspect_slice_output(content: bytes, printer: PrinterBuildVolume | None = None) -> SliceOutputInspection:
    """Inspect actual plate files and toolpath bounds returned by the slicer."""

    plate_names: list[str] = []
    xy_values: list[tuple[float, float]] = []

    def collect_toolpath_coordinates(text: str) -> None:
        geometry_started = False
        last_x: float | None = None
        last_y: float | None = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("; layer num/total_layer_count:"):
                geometry_started = True
            if stripped.startswith("; EXECUTABLE_BLOCK_END"):
                break
            if not geometry_started:
                continue
            if not re.match(r"^G(?:0|1|2|3)(?:\s|$)", stripped):
                continue
            coordinates = {axis: float(value) for axis, value in re.findall(r"([XY])(-?\d+(?:\.\d+)?)", stripped)}
            last_x = coordinates.get("X", last_x)
            last_y = coordinates.get("Y", last_y)
            extrusion = re.search(r"(?:^|\s)E(-?\d+(?:\.\d+)?)", stripped)
            if last_x is not None and last_y is not None and extrusion and float(extrusion.group(1)) > 0:
                xy_values.append((last_x, last_y))
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            for name in archive.namelist():
                if re.fullmatch(r"Metadata/plate_\d+\.gcode", name):
                    plate_names.append(name)
                    text = archive.read(name).decode("utf-8", errors="ignore")
                    collect_toolpath_coordinates(text)
            if not plate_names:
                # Some sidecars return an exported 3MF without per-plate G-code
                # metadata. It is still one candidate plate, but we retain the
                # check for a single returned archive.
                plate_names = ["Metadata/plate_1.gcode"]
    except (OSError, zipfile.BadZipFile):
        # Raw G-code responses are one plate and are still valid sidecar output.
        plate_names = ["plate_1.gcode"]
        text = content.decode("utf-8", errors="ignore")
        collect_toolpath_coordinates(text)
    bounds = None
    if xy_values:
        bounds = (min(x for x, _ in xy_values), min(y for _, y in xy_values), max(x for x, _ in xy_values), max(y for _, y in xy_values))
        if printer is not None and (
            bounds[0] < -0.5 or bounds[1] < -0.5 or bounds[2] > printer.width_mm + 0.5 or bounds[3] > printer.depth_mm + 0.5
        ):
            raise SlicePlanningError(
                f"真实切片支撑或模型超出打印板：X {bounds[0]:.2f}..{bounds[2]:.2f}，Y {bounds[1]:.2f}..{bounds[3]:.2f}"
            )
    return SliceOutputInspection(len(plate_names), tuple(sorted(plate_names)), bounds)


class _LazySlicer:
    """Open the sidecar only when at least one plate is not cached."""

    def __init__(self, api_url: str):
        self.api_url = api_url
        self._service = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        if self._service is not None:
            await self._service.__aexit__(exc_type, exc, traceback)

    async def slice_without_profiles(self, **kwargs):
        if self._service is None:
            from backend.app.services.slicer_api import SlicerApiService

            self._service = SlicerApiService(self.api_url)
            await self._service.__aenter__()
        return await self._service.slice_without_profiles(**kwargs)


def _format_real_slice_error(exc: Exception) -> str:
    """Turn the sidecar's geometry failure into an actionable UI message."""

    raw = str(exc)
    lowered = raw.lower()
    if "outside of the printable area" in lowered or "zfiller" in lowered:
        return (
            "自动摆盘失败：切片器判定模型或其支撑/裙边超出打印区域。"
            "请检查源 3MF 是否包含旧的多盘摆放、负坐标或超出目标打印机尺寸的对象；"
            f"原始原因：{raw}"
        )
    return f"真实切片失败：{raw}"


def patch_embedded_printer_preset(
    source_bytes: bytes,
    *,
    printer_preset: str | None = None,
    printer_model: str | None = None,
) -> bytes:
    """Change only the embedded printer identity in a 3MF project.

    The project settings contain the user's orientation, infill, support and
    per-object overrides.  A printer switch must not rebuild those settings
    from a local default profile, so this helper deliberately changes only
    the two printer identity fields and copies every other ZIP entry verbatim.
    With no target supplied the original bytes are returned unchanged.
    """

    if printer_preset is None and printer_model is None:
        return source_bytes

    source = BytesIO(source_bytes)
    output = BytesIO()
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            settings_name = "Metadata/project_settings.config"
            if settings_name not in source_zip.namelist():
                raise SlicePlanningError("3MF 缺少内嵌打印参数，无法安全切换打印机")
            project_settings = json.loads(source_zip.read(settings_name).decode("utf-8"))
            if not isinstance(project_settings, dict):
                raise SlicePlanningError("3MF 内嵌打印参数格式无效，无法安全切换打印机")
            if printer_preset is not None:
                project_settings["printer_settings_id"] = printer_preset
                # Keep the source process/object settings intact, but make
                # the selected printer an explicitly compatible identity.
                # Bambu Studio otherwise rejects a valid model when the
                # source was authored for another printer family.
                compatible = project_settings.get("print_compatible_printers")
                if isinstance(compatible, list):
                    if printer_preset not in compatible:
                        project_settings["print_compatible_printers"] = [*compatible, printer_preset]
                else:
                    project_settings["print_compatible_printers"] = [printer_preset]
            if printer_model is not None:
                project_settings["printer_model"] = printer_model
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    if item.filename == settings_name:
                        output_zip.writestr(
                            item,
                            json.dumps(project_settings, ensure_ascii=False, separators=(",", ":")),
                        )
                    else:
                        output_zip.writestr(item, source_zip.read(item.filename))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError, zipfile.BadZipFile) as exc:
        raise SlicePlanningError(f"无法读取 3MF 内嵌打印参数：{exc}") from exc
    return output.getvalue()


def _printer_model_id(printer_model: str | None) -> str | None:
    """Map Bambuddy's human-readable model to Bambu Studio's plate ID."""

    if not printer_model:
        return None
    normalized = printer_model.strip().lower()
    return {
        "bambu lab a1": "N2S",
        "a1": "N2S",
        "bambu lab a1 mini": "N1",
        "a1 mini": "N1",
        "bambu lab a2l": "N9",
        "a2l": "N9",
    }.get(normalized)


def patch_sliced_output_printer_metadata(
    content: bytes,
    *,
    printer_model: str | None,
) -> bytes:
    """Bind a sliced 3MF to its target printer without re-slicing.

    Bambu Studio uses Metadata/slice_info.config rather than only
    project_settings.config to decide whether an archive is a directly
    sendable sliced job. The sidecar can leave printer_model_id empty even
    when the G-code itself is complete, so fill that identity field only.
    """

    model_id = _printer_model_id(printer_model)
    if model_id is None:
        return content
    source = BytesIO(content)
    output = BytesIO()
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            metadata_name = "Metadata/slice_info.config"
            if metadata_name not in source_zip.namelist():
                raise SlicePlanningError("切片结果缺少 Metadata/slice_info.config，无法标记目标打印机")
            root = ElementTree.fromstring(source_zip.read(metadata_name))
            changed = False
            for node in root.iter():
                if node.tag.rsplit("}", 1)[-1] != "metadata":
                    continue
                if node.attrib.get("key") == "printer_model_id":
                    node.attrib["value"] = model_id
                    changed = True
            if not changed:
                raise SlicePlanningError("切片结果缺少 printer_model_id 元数据")
            metadata_bytes = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    output_zip.writestr(
                        item,
                        metadata_bytes if item.filename == metadata_name else source_zip.read(item.filename),
                    )
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SlicePlanningError(f"无法更新切片打印机元数据：{exc}") from exc
    return output.getvalue()


def make_direct_sendable_sliced_output(content: bytes) -> bytes:
    """Remove editable model payloads from a sliced Bambu 3MF package.

    Bambu Studio treats a package containing model resources/build items as an
    editable project, even when it also contains complete per-plate G-code.
    A sendable G-code 3MF keeps the sliced plate metadata and settings, but its
    3D model resources and object entries must be empty.
    """

    source = BytesIO(content)
    output = BytesIO()
    model_name = "3D/3dmodel.model"
    settings_name = "Metadata/model_settings.config"
    names: set[str]
    model_bytes: bytes | None = None
    settings_bytes: bytes | None = None
    try:
        with zipfile.ZipFile(source, "r") as source_zip:
            names = set(source_zip.namelist())
            if model_name not in names:
                raise SlicePlanningError("切片结果缺少 3D/3dmodel.model，无法生成可发送文件")
            model_root = ElementTree.fromstring(source_zip.read(model_name))
            for node in model_root.iter():
                if node.tag.rsplit("}", 1)[-1] not in {"resources", "build"}:
                    continue
                for child in list(node):
                    node.remove(child)
            model_bytes = ElementTree.tostring(model_root, encoding="utf-8", xml_declaration=True)

            if settings_name in names:
                settings_root = ElementTree.fromstring(source_zip.read(settings_name))
                for child in list(settings_root):
                    if child.tag.rsplit("}", 1)[-1] in {"object", "assemble"}:
                        settings_root.remove(child)
                settings_bytes = ElementTree.tostring(settings_root, encoding="utf-8", xml_declaration=True)

            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as output_zip:
                for item in source_zip.infolist():
                    filename = item.filename
                    if filename.startswith("3D/Objects/") or filename == "3D/_rels/3dmodel.model.rels":
                        continue
                    if filename == model_name:
                        data = model_bytes
                    elif filename == settings_name:
                        data = settings_bytes
                    else:
                        data = source_zip.read(filename)
                    output_zip.writestr(item, data)
                if settings_bytes is None:
                    minimal_settings = ElementTree.Element("config")
                    plate = ElementTree.SubElement(minimal_settings, "plate")
                    for key, value in (
                        ("plater_id", "1"),
                        ("gcode_file", "Metadata/plate_1.gcode"),
                        ("thumbnail_file", "Metadata/plate_1.png"),
                        ("thumbnail_no_light_file", "Metadata/plate_no_light_1.png"),
                        ("top_file", "Metadata/top_1.png"),
                        ("pick_file", "Metadata/pick_1.png"),
                        ("pattern_bbox_file", "Metadata/plate_1.json"),
                    ):
                        ElementTree.SubElement(plate, "metadata", key=key, value=value)
                    output_zip.writestr(
                        settings_name,
                        ElementTree.tostring(minimal_settings, encoding="utf-8", xml_declaration=True),
                    )
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise SlicePlanningError(f"无法生成可发送的 G-code 3MF：{exc}") from exc
    return output.getvalue()


async def _job_source_product_file(db: AsyncSession, job: PlateJob) -> ProductFile | None:
    """Resolve the source file for this physical plate job.

    New product-level multi-plate products upload one 3MF per source plate;
    the order snapshot carries the immutable ordered source-file ids. Legacy
    embedded multi-plate files continue to resolve to their single row.
    """
    requirement = job.requirement
    product_file = await db.get(ProductFile, requirement.product_file_id)
    if product_file is None:
        return None
    snapshot = requirement.recipe_snapshot or {}
    file_snapshot = snapshot.get("product_file_snapshot") or {}
    source_file_ids = file_snapshot.get("source_file_ids") or []
    if file_snapshot.get("production_mode") == "multi_plate" and source_file_ids:
        index = job.source_plate_index
        if 0 <= index < len(source_file_ids):
            selected = await db.get(ProductFile, int(source_file_ids[index]))
            if selected is not None:
                return selected
    return product_file


async def slice_plate_job_real(
    db: AsyncSession,
    plate_job_id: int,
    *,
    target_printer_preset: str | None = None,
    target_printer_model: str | None = None,
) -> PlateJob:
    """Run the real slicer sidecar for a product plate job.

    The sidecar receives the original 3MF, so its embedded process, filament,
    orientation, infill and object-level settings remain authoritative.  The
    only optional input rewrite is the printer identity requested by the
    caller.  This function never opens a print queue or contacts a printer.
    """

    job = await db.scalar(
        select(PlateJob)
        .where(PlateJob.id == plate_job_id)
        .options(selectinload(PlateJob.requirement))
    )
    if job is None:
        raise SlicePlanningError("打印任务不存在")
    job.slice_attempts += 1
    job.slice_error = None
    job.slice_status = "slicing"
    # Do not expose an earlier simulation plan as a successful real output.
    job.slice_result = None
    await db.commit()

    requirement = job.requirement
    product_file = await _job_source_product_file(db, job)
    assigned_virtual = await db.get(VirtualPrinter, job.virtual_printer_id) if job.virtual_printer_id else None
    library_file = await db.get(LibraryFile, product_file.library_file_id) if product_file else None
    source_path = _absolute_library_path(library_file.file_path if library_file else None)
    try:
        if product_file is None or library_file is None or source_path is None:
            raise SlicePlanningError("产品源文件关联记录不存在")
        if not source_path.exists():
            raise SlicePlanningError("产品源文件在文件库中不存在")
        if not library_file.filename.lower().endswith(".3mf"):
            raise SlicePlanningError("真实切片目前只接受产品源 3MF 文件")

        # Use the printer selected by the allocator unless the caller
        # explicitly overrides it. This keeps the real slice tied to the
        # assigned A1/A2L target instead of the source file's model.
        if target_printer_model is None and assigned_virtual is not None:
            assigned_identity = {
                "N2S": ("Bambu Lab A1", "Bambu Lab A1 0.4 nozzle"),
                "N1": ("Bambu Lab A1 mini", "Bambu Lab A1 mini 0.4 nozzle"),
                "N9": ("Bambu Lab A2L", "Bambu Lab A2L 0.4 nozzle"),
            }.get(assigned_virtual.model or "")
            if assigned_identity:
                target_printer_model, default_preset = assigned_identity
                if target_printer_preset is None:
                    target_printer_preset = default_preset

        source_bytes = source_path.read_bytes()
        file_snapshot = requirement.recipe_snapshot.get("product_file_snapshot", {}) if requirement.recipe_snapshot else {}
        effective_strategy = "multi_plate_fixed" if file_snapshot.get("production_mode") == "multi_plate" else product_file.strategy
        if effective_strategy == "auto_pack":
            try:
                layout_source_bytes = normalize_build_item_positions(source_bytes)
            except SlicePlanningError:
                # Keep malformed/legacy files intact so the sidecar can
                # return its more specific validation error.
                layout_source_bytes = source_bytes
        else:
            layout_source_bytes = source_bytes

        from backend.app.api.routes.settings import get_setting

        preferred = (await get_setting(db, "preferred_slicer")) or "bambu_studio"
        if preferred == "orcaslicer":
            configured = await get_setting(db, "orcaslicer_api_url")
            api_url = (configured or settings.slicer_api_url).strip()
        elif preferred == "bambu_studio":
            configured = await get_setting(db, "bambu_studio_api_url")
            api_url = (configured or settings.bambu_studio_api_url).strip()
        else:
            raise SlicePlanningError(f"不支持的切片器：{preferred}")
        if not api_url:
            raise SlicePlanningError("未配置真实切片器服务，请先配置 Bambu Studio 或 OrcaSlicer sidecar")

        # Auto packing is now explicit: Bambuddy computes the projected
        # footprint and Z rotations, then sends fixed coordinates to the
        # slicer. Leaving arrange on would let the slicer throw away the
        # validated layout and silently create a different number of plates.
        arrange = False
        digest = sha256(source_bytes).hexdigest()
        plate_quantities = [job.planned_quantity]
        layout_plan = None
        if effective_strategy == "auto_pack" and assigned_virtual is not None:
            try:
                source_dimensions, source_plate_count = inspect_3mf(source_path)
            except SlicePlanningError:
                # Let the sidecar provide its detailed validation message for
                # malformed/legacy 3MFs; valid files use the deterministic
                # capacity plan below to create quantity-specific plates.
                source_dimensions = None
                source_plate_count = 1
            if source_dimensions is not None:
                projected_footprint = inspect_projected_footprint(source_path)
                plan = plan_slice(
                    strategy=effective_strategy,
                    requested_quantity=job.planned_quantity,
                    configured_units_per_plate=float(product_file.units_per_plate),
                    source=source_dimensions,
                    printer=PrinterBuildVolume(
                        width_mm=assigned_virtual.build_width_mm,
                        depth_mm=assigned_virtual.build_depth_mm,
                        height_mm=assigned_virtual.build_height_mm,
                    ),
                    source_plate_count=source_plate_count,
                    projected_footprint=projected_footprint,
                )
                layout_plan = plan
                plate_quantities = []
                remaining = job.planned_quantity
                while remaining > 0:
                    current = min(plan.actual_units_per_plate, remaining)
                    plate_quantities.append(current)
                    remaining -= current

        plates: list[dict] = []
        all_reused = True
        output_dir = Path(settings.archive_dir) / "library" / "files"
        output_dir.mkdir(parents=True, exist_ok=True)
        source_plate_index = job.source_plate_index if effective_strategy == "multi_plate_fixed" else None
        async with _LazySlicer(api_url) as slicer:
            for plate_index, initial_plate_quantity in enumerate(plate_quantities):
                plate_quantity = initial_plate_quantity
                cached_plate = False
                while True:
                    if effective_strategy == "auto_pack" and layout_plan is not None:
                        expanded_bytes = duplicate_build_items(layout_source_bytes, plate_quantity)
                        expanded_bytes = apply_build_item_layout(
                            expanded_bytes,
                            layout_plan.placements[:plate_quantity],
                        )
                    else:
                        expanded_bytes = source_bytes
                    model_bytes = patch_embedded_printer_preset(
                        expanded_bytes,
                        printer_preset=target_printer_preset,
                        printer_model=target_printer_model,
                    )
                    fingerprint = slice_settings_fingerprint(
                    source_sha256=digest,
                    source_version=product_file.version,
                    strategy=effective_strategy,
                    preferred_slicer=preferred,
                    target_printer_preset=target_printer_preset,
                    target_printer_model=target_printer_model,
                    plate_index=source_plate_index if source_plate_index is not None else plate_index,
                    plate_quantity=plate_quantity,
                    source_product_file_id=product_file.id,
                )
                    cached = await db.scalar(
                    select(SliceArtifact).where(SliceArtifact.settings_fingerprint == fingerprint)
                )
                    cached_file = await db.get(LibraryFile, cached.output_library_file_id) if cached else None
                    cached_path = _absolute_library_path(cached_file.file_path if cached_file else None)
                    if cached and cached_file and cached_path and cached_path.exists() and not cached_file.deleted_at:
                        if effective_strategy == "auto_pack":
                            try:
                                cached_inspection = inspect_slice_output(cached_path.read_bytes())
                            except (OSError, SlicePlanningError):
                                cached_inspection = None
                            if cached_inspection is None or cached_inspection.plate_count != 1:
                                cached = None
                        if cached is not None:
                            plate = {
                        "plate_index": source_plate_index if source_plate_index is not None else plate_index,
                        "source_plate_index": source_plate_index,
                        "product_set_index": job.product_set_index,
                        "plate_quantity": plate_quantity,
                        "slice_artifact_id": cached.id,
                        "output_library_file_id": cached.output_library_file_id,
                        "output_file_name": cached_file.filename,
                        "output_sha256": cached.output_sha256,
                        "reused": True,
                        "print_time_seconds": cached.print_time_seconds,
                        "filament_used_g": cached.filament_used_g,
                        "filament_used_mm": cached.filament_used_mm,
                        "target_printer_preset": cached.target_printer_preset,
                        "target_printer_model": cached.target_printer_model,
                            }
                            plates.append(plate)
                            cached_plate = True
                            break

                    all_reused = False
                    result = await slicer.slice_without_profiles(
                    model_bytes=model_bytes,
                    model_filename=library_file.filename,
                    plate=source_plate_index if source_plate_index is not None else plate_index,
                    export_3mf=True,
                    arrange=arrange,
                )
                    result = result._replace(
                        content=patch_sliced_output_printer_metadata(
                            result.content,
                            printer_model=target_printer_model,
                        )
                    )
                    result = result._replace(content=make_direct_sendable_sliced_output(result.content))
                    try:
                        inspection = inspect_slice_output(
                            result.content,
                            PrinterBuildVolume(
                                width_mm=assigned_virtual.build_width_mm if assigned_virtual else 256,
                                depth_mm=assigned_virtual.build_depth_mm if assigned_virtual else 256,
                                height_mm=assigned_virtual.build_height_mm if assigned_virtual else 250,
                            ),
                        )
                    except SlicePlanningError:
                        if effective_strategy == "auto_pack" and plate_quantity > 1:
                            plate_quantities[plate_index] = plate_quantity - 1
                            if plate_index + 1 < len(plate_quantities):
                                plate_quantities[plate_index + 1] += 1
                            else:
                                plate_quantities.append(1)
                            plate_quantity -= 1
                            continue
                        raise
                    if inspection.plate_count != 1:
                        if effective_strategy == "auto_pack" and plate_quantity > 1:
                            plate_quantities[plate_index] = plate_quantity - 1
                            if plate_index + 1 < len(plate_quantities):
                                plate_quantities[plate_index + 1] += 1
                            else:
                                plate_quantities.append(1)
                            plate_quantity -= 1
                            continue
                        raise SlicePlanningError(
                            f"候选摆盘 {plate_quantity} 套经真实切片后仍生成 {inspection.plate_count} 盘，不能作为一盘结果"
                        )
                    break
                if cached_plate:
                    continue
                output_name = slice_output_filename(
                    library_file.filename,
                    plate_index=source_plate_index if source_plate_index is not None else plate_index,
                    plate_quantity=plate_quantity,
                )
                output_path = output_dir / f"{uuid4().hex}.gcode.3mf"
                output_path.write_bytes(result.content)
                output_file = LibraryFile(
                    folder_id=library_file.folder_id,
                    filename=output_name,
                    file_path=str(output_path.relative_to(settings.base_dir)),
                    file_type="gcode.3mf",
                    file_size=len(result.content),
                    file_hash=sha256(result.content).hexdigest(),
                    file_metadata={
                        "sliced_from_product_file_id": product_file.id,
                        "sliced_from_library_file_id": library_file.id,
                        "embedded_settings_preserved": True,
                        "target_printer_preset": target_printer_preset,
                        "target_printer_model": target_printer_model,
                        "arranged_by_slicer": arrange,
                        "layout_algorithm": "projected-footprint-z-rotation-v1" if layout_plan is not None else "source-layout",
                        "actual_plate_count": inspection.plate_count,
                        "plate_index": plate_index,
                        "source_plate_index": source_plate_index,
                        "product_set_index": job.product_set_index,
                        "plate_quantity": plate_quantity,
                    },
                    source_type="sliced",
                )
                db.add(output_file)
                await db.flush()
                artifact = SliceArtifact(
                    source_product_file_id=product_file.id,
                    source_library_file_id=library_file.id,
                    output_library_file_id=output_file.id,
                    source_sha256=digest,
                    source_version=product_file.version,
                    strategy=effective_strategy,
                    target_printer_preset=target_printer_preset,
                    target_printer_model=target_printer_model,
                    settings_fingerprint=fingerprint,
                    arranged_by_slicer=arrange,
                    print_time_seconds=result.print_time_seconds,
                    filament_used_g=result.filament_used_g,
                    filament_used_mm=result.filament_used_mm,
                    output_sha256=output_file.file_hash,
                    metadata_json=json.dumps(
                        {
                            "preferred_slicer": preferred,
                            "plate_index": source_plate_index if source_plate_index is not None else plate_index,
                            "source_plate_index": source_plate_index,
                            "product_set_index": job.product_set_index,
                            "plate_quantity": plate_quantity,
                            "actual_plate_count": inspection.plate_count,
                            "layout_algorithm": "projected-footprint-z-rotation-v1" if layout_plan is not None else "source-layout",
                        },
                        ensure_ascii=False,
                    ),
                )
                db.add(artifact)
                await db.flush()
                plates.append(
                    {
                        "plate_index": source_plate_index if source_plate_index is not None else plate_index,
                        "source_plate_index": source_plate_index,
                        "product_set_index": job.product_set_index,
                        "plate_quantity": plate_quantity,
                        "slice_artifact_id": artifact.id,
                        "output_library_file_id": output_file.id,
                        "output_file_name": output_file.filename,
                        "output_sha256": output_file.file_hash,
                        "reused": False,
                        "print_time_seconds": result.print_time_seconds,
                        "filament_used_g": result.filament_used_g,
                        "filament_used_mm": result.filament_used_mm,
                        "target_printer_preset": target_printer_preset,
                        "target_printer_model": target_printer_model,
                    }
                )

        first = plates[0]
        job.slice_result = {
            "real_slice": True,
            "simulation_only": False,
            "embedded_settings_preserved": True,
            "arranged_by_slicer": arrange,
            "layout_applied": layout_plan is not None,
            "source_product_file_id": product_file.id,
            "source_library_file_id": library_file.id,
            "source_file_name": library_file.filename,
            "source_sha256": digest,
            "requested_quantity": job.planned_quantity,
            "source_plate_index": job.source_plate_index,
            "product_set_index": job.product_set_index,
            "plate_count": len(plates),
            "plate_quantities": plate_quantities,
            "plates": plates,
            "output_library_file_id": first["output_library_file_id"],
            "output_file_name": first["output_file_name"],
            "output_sha256": first["output_sha256"],
            "slice_artifact_id": first["slice_artifact_id"],
            "reused": all_reused,
            "target_printer_preset": first["target_printer_preset"],
            "target_printer_model": first["target_printer_model"],
            "print_time_seconds": first["print_time_seconds"],
            "filament_used_g": first["filament_used_g"],
            "filament_used_mm": first["filament_used_mm"],
        }
        job.slice_status = "succeeded"
        job.sliced_at = datetime.now(timezone.utc)
    except SlicePlanningError as exc:
        job.slice_status = "failed"
        job.slice_error = str(exc)
    except Exception as exc:
        # Keep the user's original source untouched and expose the sidecar's
        # error instead of falling back to a simulation or another printer.
        job.slice_status = "failed"
        job.slice_error = _format_real_slice_error(exc)
    await db.commit()
    await db.refresh(job)
    return job


async def slice_plate_job(db: AsyncSession, plate_job_id: int) -> PlateJob:
    """Create or retry a deterministic simulated slice result for one job."""

    job = await db.scalar(
        select(PlateJob)
        .where(PlateJob.id == plate_job_id)
        .options(selectinload(PlateJob.requirement))
    )
    if job is None:
        raise SlicePlanningError("打印任务不存在")
    job.slice_attempts += 1
    job.slice_error = None
    job.slice_status = "pending"
    requirement = job.requirement
    product_file = await _job_source_product_file(db, job)
    virtual_printer = await db.get(VirtualPrinter, job.virtual_printer_id)
    library_file = await db.get(LibraryFile, product_file.library_file_id) if product_file else None
    source_path = _absolute_library_path(library_file.file_path if library_file else None)
    try:
        if product_file is None or library_file is None or source_path is None:
            raise SlicePlanningError("产品源文件关联记录不存在")
        if virtual_printer is None:
            raise SlicePlanningError("任务尚未分配虚拟打印机")
        if not source_path.exists():
            raise SlicePlanningError("产品源文件在文件库中不存在")
        source_dimensions, source_plate_count = inspect_3mf(source_path)
        snapshot = requirement.recipe_snapshot or {}
        file_snapshot = snapshot.get("product_file_snapshot") or {}
        effective_strategy = "multi_plate_fixed" if file_snapshot.get("production_mode") == "multi_plate" else product_file.strategy
        plan = plan_slice(
            strategy=effective_strategy,
            requested_quantity=job.planned_quantity,
            configured_units_per_plate=float(product_file.units_per_plate),
            source=source_dimensions,
            printer=PrinterBuildVolume(
                width_mm=virtual_printer.build_width_mm,
                depth_mm=virtual_printer.build_depth_mm,
                height_mm=virtual_printer.build_height_mm,
            ),
            source_plate_count=source_plate_count,
        )
        digest = sha256(source_path.read_bytes()).hexdigest()
        result = plan.to_dict()
        result.update(
            {
                "source_product_file_id": product_file.id,
                "source_library_file_id": library_file.id,
                "source_file_name": library_file.filename,
                "source_sha256": digest,
                "printer_id": virtual_printer.id,
                "printer_model": virtual_printer.model,
                "source_snapshot_version": file_snapshot.get("version", product_file.version),
                "source_plate_index": job.source_plate_index,
                "product_set_index": job.product_set_index,
                "simulation_only": True,
            }
        )
        job.slice_result = result
        job.slice_status = "succeeded"
        job.sliced_at = datetime.now(timezone.utc)
    except SlicePlanningError as exc:
        job.slice_status = "failed"
        job.slice_error = str(exc)
    await db.commit()
    await db.refresh(job)
    return job
