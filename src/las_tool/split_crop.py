from __future__ import annotations

import copy
import math
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import laspy
import numpy as np


ProgressCallback = Callable[[int, int], None]


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
class PreviewData:
    input_path: Path
    total_points: int
    bounds: Bounds2D
    preview_points: np.ndarray


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


def load_preview_data(
    input_path: Path | str,
    *,
    max_points: int = 100_000,
    chunk_size: int = 1_000_000,
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
        else:
            step = max(1, math.ceil(total_points / max_points))
            offset = 0
            samples: list[np.ndarray] = []

            for points in reader.chunk_iterator(chunk_size):
                point_count = len(points)
                if point_count == 0:
                    continue

                if step == 1:
                    sample_x = np.asarray(points.x)
                    sample_y = np.asarray(points.y)
                else:
                    start = (-offset) % step
                    sample_indices = np.arange(start, point_count, step, dtype=np.int64)
                    sample_x = np.asarray(points.x)[sample_indices]
                    sample_y = np.asarray(points.y)[sample_indices]

                if sample_x.size:
                    samples.append(np.column_stack((sample_x, sample_y)))

                offset += point_count

            preview_points = (
                np.concatenate(samples, axis=0)
                if samples
                else np.empty((0, 2), dtype=np.float64)
            )

    return PreviewData(
        input_path=path,
        total_points=total_points,
        bounds=bounds,
        preview_points=preview_points,
    )


def crop_las(
    input_path: Path | str,
    bounds: Bounds2D,
    *,
    chunk_size: int = 1_000_000,
    progress_callback: Optional[ProgressCallback] = None,
) -> CropResult:
    path = _validate_las_path(input_path)
    if not bounds.is_valid():
        raise ValueError("Crop bounds are not valid.")

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

    try:
        with laspy.open(path) as reader:
            total_points = int(reader.header.point_count)
            header = copy.deepcopy(reader.header)
            kept_points = 0

            with ExitStack() as stack:
                writer = None
                processed = 0

                for points in reader.chunk_iterator(chunk_size):
                    point_count = len(points)
                    if point_count == 0:
                        continue

                    x = np.asarray(points.x)
                    y = np.asarray(points.y)
                    mask = (
                        (x >= bounds.min_x)
                        & (x <= bounds.max_x)
                        & (y >= bounds.min_y)
                        & (y <= bounds.max_y)
                    )

                    if mask.any():
                        if writer is None:
                            writer = stack.enter_context(
                                laspy.open(output_path, mode="w", header=header)
                            )
                        selected = points[mask]
                        writer.write_points(selected)
                        kept_points += len(selected)

                    processed += point_count
                    if progress_callback is not None:
                        progress_callback(processed, total_points)

            if kept_points == 0:
                return CropResult(
                    input_path=path,
                    output_path=output_path,
                    input_points=total_points,
                    output_points=0,
                    empty=True,
                    message="No points fell inside the selected rectangle.",
                )

            return CropResult(
                input_path=path,
                output_path=output_path,
                input_points=total_points,
                output_points=kept_points,
                message=f"Cropped point cloud saved to {output_path.name}.",
            )
    except Exception:
        _remove_file_if_exists(output_path)
        raise


def split_las(
    input_path: Path | str,
    selection: LineSelection,
    *,
    chunk_size: int = 1_000_000,
    progress_callback: Optional[ProgressCallback] = None,
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
                            left_writer = stack.enter_context(
                                laspy.open(left_output_path, mode="w", header=left_header)
                            )
                        selected_left = points[left_mask]
                        left_writer.write_points(selected_left)
                        left_points += len(selected_left)

                    if right_mask.any():
                        if right_writer is None:
                            right_writer = stack.enter_context(
                                laspy.open(right_output_path, mode="w", header=right_header)
                            )
                        selected_right = points[right_mask]
                        right_writer.write_points(selected_right)
                        right_points += len(selected_right)

                    processed += point_count
                    if progress_callback is not None:
                        progress_callback(processed, total_points)

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
    except Exception:
        _remove_file_if_exists(left_output_path)
        _remove_file_if_exists(right_output_path)
        raise


def _remove_file_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
