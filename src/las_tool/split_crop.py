from __future__ import annotations

import copy
import math
import threading
import uuid
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import laspy
import numpy as np

from .cancellation import raise_if_cancelled


ProgressCallback = Callable[[int, int], None]
PreviewProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class Bounds2D:
    min_x: float
    max_x: float
    min_y: float
    max_y: float

    @classmethod
    def from_points(
        cls,
        first: tuple[float, float],
        second: tuple[float, float],
    ) -> "Bounds2D":
        x1, y1 = first
        x2, y2 = second
        return cls(
            min_x=min(x1, x2),
            max_x=max(x1, x2),
            min_y=min(y1, y2),
            max_y=max(y1, y2),
        )

    def is_valid(self) -> bool:
        return self.max_x > self.min_x and self.max_y > self.min_y


@dataclass(frozen=True)
class LineSelection:
    x1: float
    y1: float
    x2: float
    y2: float

    def is_valid(self) -> bool:
        return not (math.isclose(self.x1, self.x2) and math.isclose(self.y1, self.y2))


@dataclass(frozen=True)
class PolygonSelection:
    points: tuple[tuple[float, float], ...]

    def is_valid(self) -> bool:
        if len(self.points) < 3:
            return False

        xs = np.asarray([point[0] for point in self.points], dtype=np.float64)
        ys = np.asarray([point[1] for point in self.points], dtype=np.float64)
        area = 0.5 * abs(np.dot(xs, np.roll(ys, -1)) - np.dot(ys, np.roll(xs, -1)))
        return area > 0

    @property
    def bounds(self) -> Bounds2D:
        xs = [point[0] for point in self.points]
        ys = [point[1] for point in self.points]
        return Bounds2D(min(xs), max(xs), min(ys), max(ys))


@dataclass(frozen=True)
class GridSelection:
    bounds: Bounds2D
    rows: int
    cols: int

    def is_valid(self) -> bool:
        return self.bounds.is_valid() and self.rows > 0 and self.cols > 0

    @property
    def part_count(self) -> int:
        return self.rows * self.cols


@dataclass(frozen=True)
class PreviewData:
    input_path: Path
    total_points: int
    bounds: Bounds2D
    preview_points: np.ndarray
    preview_colors: np.ndarray
    preview_z: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.float64))


@dataclass
class CropResult:
    input_path: Path
    output_path: Path
    input_points: int
    output_points: int
    skipped: bool = False
    empty: bool = False
    message: str = ""


@dataclass
class SplitResult:
    input_path: Path
    left_output_path: Path
    right_output_path: Path
    input_points: int
    left_points: int
    right_points: int
    skipped: bool = False
    empty_left: bool = False
    empty_right: bool = False
    message: str = ""


@dataclass(frozen=True)
class GridPartResult:
    part_number: int
    output_path: Path
    point_count: int
    empty: bool = False


@dataclass
class GridSplitResult:
    input_path: Path
    input_points: int
    rows: int
    cols: int
    parts: list[GridPartResult]
    skipped: bool = False
    message: str = ""


def _validate_las_path(input_path: Path | str) -> Path:
    path = Path(input_path)
    if path.suffix.lower() != ".las":
        raise ValueError(f"Only .las files are supported: {path.name}")
    return path


def build_crop_output_path(input_path: Path | str) -> Path:
    path = _validate_las_path(input_path)
    return path.with_name(f"{path.stem}_crop{path.suffix.lower()}")


def build_split_output_paths(input_path: Path | str) -> tuple[Path, Path]:
    path = _validate_las_path(input_path)
    left = path.with_name(f"{path.stem}_split_left{path.suffix.lower()}")
    right = path.with_name(f"{path.stem}_split_right{path.suffix.lower()}")
    return left, right


def build_grid_output_paths(
    input_path: Path | str,
    rows: int,
    cols: int,
) -> list[Path]:
    path = _validate_las_path(input_path)
    if rows <= 0 or cols <= 0:
        raise ValueError("rows and cols must be greater than 0")

    return [
        path.with_name(f"{path.stem}_grid_{rows}x{cols}_p{part_number}{path.suffix.lower()}")
        for part_number in range(1, rows * cols + 1)
    ]


def load_preview_data(
    input_path: Path | str,
    *,
    max_points: int = 100_000,
    chunk_size: int = 1_000_000,
    progress_callback: Optional[PreviewProgressCallback] = None,
) -> PreviewData:
    path = _validate_las_path(input_path)
    if max_points <= 0:
        raise ValueError("max_points must be greater than 0")

    with laspy.open(path) as reader:
        total_points = int(reader.header.point_count)
        bounds = Bounds2D(
            min_x=float(reader.header.mins[0]),
            max_x=float(reader.header.maxs[0]),
            min_y=float(reader.header.mins[1]),
            max_y=float(reader.header.maxs[1]),
        )

        if total_points == 0:
            preview_points = np.empty((0, 2), dtype=np.float64)
            preview_colors = np.empty((0, 3), dtype=np.uint8)
            preview_z = np.empty(0, dtype=np.float64)
            if progress_callback is not None:
                progress_callback(0, 0)
            return PreviewData(
                input_path=path,
                total_points=0,
                bounds=bounds,
                preview_points=preview_points,
                preview_colors=preview_colors,
                preview_z=preview_z,
            )

        step = max(1, math.ceil(total_points / max_points))
        offset = 0
        xyz_samples: list[np.ndarray] = []
        rgb_samples: list[np.ndarray] = []
        has_rgb = _header_has_rgb(reader.header)

        for points in reader.chunk_iterator(chunk_size):
            point_count = len(points)
            if point_count == 0:
                continue

            sample_indices = _sample_indices(step, offset, point_count)
            if sample_indices.size:
                sample_x = np.asarray(points.x)[sample_indices]
                sample_y = np.asarray(points.y)[sample_indices]
                sample_z = np.asarray(points.z)[sample_indices]
                xyz_samples.append(np.column_stack((sample_x, sample_y, sample_z)))

                if has_rgb:
                    sample_red = np.asarray(points.red)[sample_indices]
                    sample_green = np.asarray(points.green)[sample_indices]
                    sample_blue = np.asarray(points.blue)[sample_indices]
                    rgb_samples.append(np.column_stack((sample_red, sample_green, sample_blue)))

            offset += point_count
            if progress_callback is not None:
                progress_callback(offset, total_points)

        preview_xyz = (
            np.concatenate(xyz_samples, axis=0)
            if xyz_samples
            else np.empty((0, 3), dtype=np.float64)
        )
        preview_points = preview_xyz[:, :2]
        preview_z = preview_xyz[:, 2] if preview_xyz.size else np.empty(0, dtype=np.float64)
        preview_colors = _resolve_preview_colors(
            preview_z,
            np.concatenate(rgb_samples, axis=0) if rgb_samples else None,
        )

    return PreviewData(
        input_path=path,
        total_points=total_points,
        bounds=bounds,
        preview_points=preview_points,
        preview_colors=preview_colors,
        preview_z=preview_z,
    )


def combine_preview_data(
    previews: list[PreviewData],
    *,
    label_path: Path | None = None,
) -> PreviewData:
    if not previews:
        raise ValueError("at least one preview is required")

    if len(previews) == 1:
        preview = previews[0]
        if label_path is None or label_path == preview.input_path:
            return preview
        return PreviewData(
            input_path=label_path,
            total_points=preview.total_points,
            bounds=preview.bounds,
            preview_points=preview.preview_points,
            preview_colors=preview.preview_colors,
            preview_z=preview.preview_z,
        )

    total_points = sum(preview.total_points for preview in previews)
    bounds = Bounds2D(
        min_x=min(preview.bounds.min_x for preview in previews),
        max_x=max(preview.bounds.max_x for preview in previews),
        min_y=min(preview.bounds.min_y for preview in previews),
        max_y=max(preview.bounds.max_y for preview in previews),
    )
    preview_points = np.concatenate([preview.preview_points for preview in previews], axis=0)
    preview_colors = np.concatenate([preview.preview_colors for preview in previews], axis=0)
    preview_z = (
        np.concatenate([preview.preview_z for preview in previews], axis=0)
        if any(preview.preview_z.size for preview in previews)
        else np.empty(0, dtype=np.float64)
    )

    return PreviewData(
        input_path=label_path or previews[0].input_path,
        total_points=total_points,
        bounds=bounds,
        preview_points=preview_points,
        preview_colors=preview_colors,
        preview_z=preview_z,
    )


def _normalize_crop_selection(selection: Bounds2D | PolygonSelection) -> PolygonSelection:
    if isinstance(selection, PolygonSelection):
        return selection

    if isinstance(selection, Bounds2D):
        return PolygonSelection(
            points=(
                (selection.min_x, selection.min_y),
                (selection.max_x, selection.min_y),
                (selection.max_x, selection.max_y),
                (selection.min_x, selection.max_y),
            )
        )

    raise TypeError("Unsupported crop selection type")


def _points_in_polygon(xs: np.ndarray, ys: np.ndarray, polygon: PolygonSelection) -> np.ndarray:
    vertices = np.asarray(polygon.points, dtype=np.float64)
    x1 = vertices[:, 0]
    y1 = vertices[:, 1]
    x2 = np.roll(x1, -1)
    y2 = np.roll(y1, -1)

    inside = np.zeros(xs.shape[0], dtype=bool)
    on_boundary = np.zeros(xs.shape[0], dtype=bool)
    tolerance = 1e-9

    for ax, ay, bx, by in zip(x1, y1, x2, y2):
        min_x = min(ax, bx) - tolerance
        max_x = max(ax, bx) + tolerance
        min_y = min(ay, by) - tolerance
        max_y = max(ay, by) + tolerance

        cross = (xs - ax) * (by - ay) - (ys - ay) * (bx - ax)
        edge_scale = max(abs(bx - ax), abs(by - ay), 1.0)
        on_segment = (
            (np.abs(cross) <= tolerance * edge_scale)
            & (xs >= min_x)
            & (xs <= max_x)
            & (ys >= min_y)
            & (ys <= max_y)
        )
        on_boundary |= on_segment

        denominator = by - ay if not math.isclose(by, ay) else 1.0
        intersects = ((ay > ys) != (by > ys)) & (
            xs <= ((bx - ax) * (ys - ay) / denominator + ax)
        )
        inside ^= intersects

    return inside | on_boundary


def crop_las(
    input_path: Path | str,
    selection: Bounds2D | PolygonSelection,
    *,
    chunk_size: int = 1_000_000,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> CropResult:
    path = _validate_las_path(input_path)
    polygon = _normalize_crop_selection(selection)
    if not polygon.is_valid():
        raise ValueError("Crop polygon is not valid.")
    bounds = polygon.bounds

    output_path = build_crop_output_path(path)
    if output_path.exists():
        return CropResult(
            input_path=path,
            output_path=output_path,
            input_points=0,
            output_points=0,
            skipped=True,
            message=f"Skipped because output already exists: {output_path.name}",
        )

    temporaries: dict[Path, Path] = {}
    try:
        with laspy.open(path) as reader:
            total_points = int(reader.header.point_count)
            header = copy.deepcopy(reader.header)
            kept_points = 0

            with ExitStack() as stack:
                writer = None
                processed = 0

                for points in reader.chunk_iterator(chunk_size):
                    raise_if_cancelled(cancel_event)
                    point_count = len(points)
                    if point_count == 0:
                        continue

                    x = np.asarray(points.x)
                    y = np.asarray(points.y)
                    bbox_mask = (
                        (x >= bounds.min_x)
                        & (x <= bounds.max_x)
                        & (y >= bounds.min_y)
                        & (y <= bounds.max_y)
                    )

                    if bbox_mask.any():
                        mask = np.zeros(point_count, dtype=bool)
                        bbox_indices = np.flatnonzero(bbox_mask)
                        polygon_mask = _points_in_polygon(x[bbox_mask], y[bbox_mask], polygon)
                        mask[bbox_indices[polygon_mask]] = True

                    else:
                        mask = np.zeros(point_count, dtype=bool)

                    if mask.any():
                        if writer is None:
                            temporaries[output_path] = _temporary_path(output_path)
                            writer = stack.enter_context(
                                laspy.open(temporaries[output_path], mode="w", header=header)
                            )
                        writer.write_points(points[mask])
                        kept_points += int(mask.sum())

                    processed += point_count
                    if progress_callback is not None:
                        progress_callback(processed, total_points)

            _commit_temporaries(temporaries)

            if kept_points == 0:
                return CropResult(
                    input_path=path,
                    output_path=output_path,
                    input_points=total_points,
                    output_points=0,
                    empty=True,
                    message="No points fell inside the selected polygon.",
                )

            return CropResult(
                input_path=path,
                output_path=output_path,
                input_points=total_points,
                output_points=kept_points,
                message=f"Cropped point cloud saved to {output_path.name}.",
            )
    except BaseException:
        for temporary_path in temporaries.values():
            _remove_file_if_exists(temporary_path)
        raise


def split_las(
    input_path: Path | str,
    selection: LineSelection,
    *,
    chunk_size: int = 1_000_000,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> SplitResult:
    path = _validate_las_path(input_path)
    if not selection.is_valid():
        raise ValueError("Split line is not valid.")

    left_output_path, right_output_path = build_split_output_paths(path)
    existing_outputs = [
        output_path.name
        for output_path in (left_output_path, right_output_path)
        if output_path.exists()
    ]
    if existing_outputs:
        joined = ", ".join(existing_outputs)
        return SplitResult(
            input_path=path,
            left_output_path=left_output_path,
            right_output_path=right_output_path,
            input_points=0,
            left_points=0,
            right_points=0,
            skipped=True,
            message=f"Skipped because output already exists: {joined}",
        )

    dx = selection.x2 - selection.x1
    dy = selection.y2 - selection.y1

    temporaries: dict[Path, Path] = {}
    try:
        with laspy.open(path) as reader:
            total_points = int(reader.header.point_count)
            left_header = copy.deepcopy(reader.header)
            right_header = copy.deepcopy(reader.header)
            left_points = 0
            right_points = 0

            with ExitStack() as stack:
                left_writer = None
                right_writer = None
                processed = 0

                for points in reader.chunk_iterator(chunk_size):
                    raise_if_cancelled(cancel_event)
                    point_count = len(points)
                    if point_count == 0:
                        continue

                    x = np.asarray(points.x)
                    y = np.asarray(points.y)
                    cross = dx * (y - selection.y1) - dy * (x - selection.x1)
                    left_mask = cross >= 0
                    right_mask = ~left_mask

                    if left_mask.any():
                        if left_writer is None:
                            temporaries[left_output_path] = _temporary_path(left_output_path)
                            left_writer = stack.enter_context(
                                laspy.open(
                                    temporaries[left_output_path], mode="w", header=left_header
                                )
                            )
                        selected_left = points[left_mask]
                        left_writer.write_points(selected_left)
                        left_points += len(selected_left)

                    if right_mask.any():
                        if right_writer is None:
                            temporaries[right_output_path] = _temporary_path(right_output_path)
                            right_writer = stack.enter_context(
                                laspy.open(
                                    temporaries[right_output_path], mode="w", header=right_header
                                )
                            )
                        selected_right = points[right_mask]
                        right_writer.write_points(selected_right)
                        right_points += len(selected_right)

                    processed += point_count
                    if progress_callback is not None:
                        progress_callback(processed, total_points)

            _commit_temporaries(temporaries)

            messages: list[str] = []
            if left_points:
                messages.append(f"Left side saved to {left_output_path.name}")
            else:
                messages.append("No points were written to the left side")
            if right_points:
                messages.append(f"Right side saved to {right_output_path.name}")
            else:
                messages.append("No points were written to the right side")

            return SplitResult(
                input_path=path,
                left_output_path=left_output_path,
                right_output_path=right_output_path,
                input_points=total_points,
                left_points=left_points,
                right_points=right_points,
                empty_left=left_points == 0,
                empty_right=right_points == 0,
                message=". ".join(messages) + ".",
            )
    except BaseException:
        for temporary_path in temporaries.values():
            _remove_file_if_exists(temporary_path)
        raise


def grid_split_las(
    input_path: Path | str,
    selection: GridSelection,
    *,
    chunk_size: int = 1_000_000,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> GridSplitResult:
    path = _validate_las_path(input_path)
    if not selection.is_valid():
        raise ValueError("Grid selection is not valid.")

    output_paths = build_grid_output_paths(path, selection.rows, selection.cols)
    existing_outputs = [output_path.name for output_path in output_paths if output_path.exists()]
    if existing_outputs:
        joined = ", ".join(existing_outputs)
        return GridSplitResult(
            input_path=path,
            input_points=0,
            rows=selection.rows,
            cols=selection.cols,
            parts=[
                GridPartResult(part_number=index, output_path=output_paths[index - 1], point_count=0, empty=True)
                for index in range(1, selection.part_count + 1)
            ],
            skipped=True,
            message=f"Skipped because output already exists: {joined}",
        )

    cell_width = (selection.bounds.max_x - selection.bounds.min_x) / selection.cols
    cell_height = (selection.bounds.max_y - selection.bounds.min_y) / selection.rows
    if cell_width <= 0 or cell_height <= 0:
        raise ValueError("Grid cell size must be greater than 0.")

    point_counts = [0] * selection.part_count
    temporaries: dict[Path, Path] = {}

    try:
        with laspy.open(path) as reader:
            total_points = int(reader.header.point_count)
            headers = [copy.deepcopy(reader.header) for _ in range(selection.part_count)]

            with ExitStack() as stack:
                writers: list[laspy.LasWriter | None] = [None] * selection.part_count
                processed = 0

                for points in reader.chunk_iterator(chunk_size):
                    raise_if_cancelled(cancel_event)
                    point_count = len(points)
                    if point_count == 0:
                        continue

                    x = np.asarray(points.x)
                    y = np.asarray(points.y)
                    inside_mask = (
                        (x >= selection.bounds.min_x)
                        & (x <= selection.bounds.max_x)
                        & (y >= selection.bounds.min_y)
                        & (y <= selection.bounds.max_y)
                    )

                    if inside_mask.any():
                        selected_points = points[inside_mask]
                        selected_x = x[inside_mask]
                        selected_y = y[inside_mask]
                        part_indices = _compute_grid_part_indices(
                            selected_x,
                            selected_y,
                            selection,
                            cell_width,
                            cell_height,
                        )

                        order = np.argsort(part_indices, kind="stable")
                        sorted_part_indices = part_indices[order]
                        boundaries = np.flatnonzero(np.diff(sorted_part_indices)) + 1
                        start = 0
                        for end in np.append(boundaries, order.size):
                            group = order[start:end]
                            if group.size == 0:
                                start = end
                                continue
                            part_index = int(sorted_part_indices[start])
                            writer = writers[part_index]
                            if writer is None:
                                temporaries[output_paths[part_index]] = _temporary_path(
                                    output_paths[part_index]
                                )
                                writer = stack.enter_context(
                                    laspy.open(
                                        temporaries[output_paths[part_index]],
                                        mode="w",
                                        header=headers[part_index],
                                    )
                                )
                                writers[part_index] = writer

                            writer.write_points(selected_points[group])
                            point_counts[part_index] += int(group.size)
                            start = end

                    processed += point_count
                    if progress_callback is not None:
                        progress_callback(processed, total_points)

        _commit_temporaries(temporaries)

        parts = [
            GridPartResult(
                part_number=index + 1,
                output_path=output_paths[index],
                point_count=point_counts[index],
                empty=point_counts[index] == 0,
            )
            for index in range(selection.part_count)
        ]
        message = _format_grid_message(parts)

        return GridSplitResult(
            input_path=path,
            input_points=total_points,
            rows=selection.rows,
            cols=selection.cols,
            parts=parts,
            message=message,
        )
    except BaseException:
        for temporary_path in temporaries.values():
            _remove_file_if_exists(temporary_path)
        raise


def _sample_indices(step: int, offset: int, point_count: int) -> np.ndarray:
    if step == 1:
        return np.arange(point_count, dtype=np.int64)

    start = (-offset) % step
    return np.arange(start, point_count, step, dtype=np.int64)


def _header_has_rgb(header: laspy.LasHeader) -> bool:
    dims = {str(name).lower() for name in header.point_format.dimension_names}
    return {"red", "green", "blue"}.issubset(dims)


def _resolve_preview_colors(
    z_values: np.ndarray,
    rgb_samples: np.ndarray | None,
) -> np.ndarray:
    if z_values.size == 0:
        return np.empty((0, 3), dtype=np.uint8)

    if rgb_samples is not None and rgb_samples.size:
        return _normalize_rgb_samples(rgb_samples)

    return _colorize_from_elevation(z_values)


def _normalize_rgb_samples(rgb_samples: np.ndarray) -> np.ndarray:
    rgb = rgb_samples.astype(np.float32)
    low = np.percentile(rgb, 1, axis=0)
    high = np.percentile(rgb, 99, axis=0)
    span = np.maximum(high - low, 1.0)
    normalized = np.clip((rgb - low) / span, 0.0, 1.0)

    # A small gamma lift keeps previews readable when source RGB is dim.
    boosted = 0.25 + 0.75 * np.sqrt(normalized)
    return np.rint(boosted * 255.0).astype(np.uint8)


def _colorize_from_elevation(z_values: np.ndarray) -> np.ndarray:
    z_min = float(np.min(z_values))
    z_max = float(np.max(z_values))
    if math.isclose(z_min, z_max):
        flat_color = np.array([56, 116, 191], dtype=np.uint8)
        return np.repeat(flat_color[np.newaxis, :], z_values.shape[0], axis=0)

    normalized = np.clip((z_values - z_min) / (z_max - z_min), 0.0, 1.0)
    anchors = np.array([0.0, 0.35, 0.7, 1.0], dtype=np.float64)
    palette = np.array(
        [
            [35, 79, 158],
            [41, 182, 246],
            [110, 201, 125],
            [245, 158, 11],
        ],
        dtype=np.float64,
    )

    channels = [
        np.interp(normalized, anchors, palette[:, channel_index])
        for channel_index in range(3)
    ]
    return np.rint(np.column_stack(channels)).astype(np.uint8)


def _compute_grid_part_indices(
    xs: np.ndarray,
    ys: np.ndarray,
    selection: GridSelection,
    cell_width: float,
    cell_height: float,
) -> np.ndarray:
    cols = np.floor((xs - selection.bounds.min_x) / cell_width).astype(np.int64)
    rows_from_bottom = np.floor((ys - selection.bounds.min_y) / cell_height).astype(np.int64)

    cols = np.clip(cols, 0, selection.cols - 1)
    rows_from_bottom = np.clip(rows_from_bottom, 0, selection.rows - 1)
    rows_from_top = selection.rows - 1 - rows_from_bottom
    return rows_from_top * selection.cols + cols


def _format_grid_message(parts: list[GridPartResult]) -> str:
    messages: list[str] = []
    for part in parts:
        label = f"p{part.part_number}"
        if part.empty:
            messages.append(f"{label}: no points written")
        else:
            messages.append(f"{label}: saved to {part.output_path.name} ({part.point_count:,} pts)")
    return ". ".join(messages) + "."


def _temporary_path(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex[:8]}.tmp")


def _commit_temporaries(temporaries: dict[Path, Path]) -> None:
    """Move finished temporary files to their final names."""
    for output_path, temporary_path in temporaries.items():
        temporary_path.replace(output_path)


def _remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
