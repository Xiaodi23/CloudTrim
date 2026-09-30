from __future__ import annotations

import copy
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import laspy
import numpy as np

from .cancellation import raise_if_cancelled


ProgressCallback = Callable[[int, int], None]

_INT64_MAX = np.iinfo(np.int64).max


@dataclass
class DownsampleResult:
    input_path: Path
    output_path: Path
    input_points: int
    output_points: int
    skipped: bool = False
    message: str = ""


class _LayoutMismatch(Exception):
    """Raised when points fall outside the bounds declared in the LAS header."""


@dataclass(frozen=True)
class PackedVoxelLayout:
    base_x: int
    base_y: int
    base_z: int
    size_x: int
    size_y: int
    size_z: int


def format_resolution_tag(resolution: float) -> str:
    text = f"{resolution:.6f}".rstrip("0").rstrip(".")
    return text.replace(".", "p") + "m"


def build_output_path(input_path: Path, resolution: float) -> Path:
    suffix = format_resolution_tag(resolution)
    return input_path.with_name(f"{input_path.stem}_ds_{suffix}{input_path.suffix.lower()}")


def validate_resolution(value: str) -> float:
    try:
        resolution = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Resolution must be a number.") from exc

    if resolution <= 0:
        raise ValueError("Resolution must be greater than 0.")

    return resolution


def _voxel_keys(points: laspy.ScaleAwarePointRecord, resolution: float) -> np.ndarray:
    x = np.floor(np.asarray(points.x) / resolution).astype(np.int64)
    y = np.floor(np.asarray(points.y) / resolution).astype(np.int64)
    z = np.floor(np.asarray(points.z) / resolution).astype(np.int64)

    structured = np.empty(
        x.shape[0],
        dtype=[("x", np.int64), ("y", np.int64), ("z", np.int64)],
    )
    structured["x"] = x
    structured["y"] = y
    structured["z"] = z
    return structured


def _compute_packed_layout(header: laspy.LasHeader, resolution: float) -> PackedVoxelLayout | None:
    min_x = int(np.floor(float(header.mins[0]) / resolution))
    min_y = int(np.floor(float(header.mins[1]) / resolution))
    min_z = int(np.floor(float(header.mins[2]) / resolution))
    max_x = int(np.floor(float(header.maxs[0]) / resolution))
    max_y = int(np.floor(float(header.maxs[1]) / resolution))
    max_z = int(np.floor(float(header.maxs[2]) / resolution))

    size_x = max_x - min_x + 1
    size_y = max_y - min_y + 1
    size_z = max_z - min_z + 1

    if min(size_x, size_y, size_z) <= 0:
        return None

    if size_y > _INT64_MAX // size_z:
        return None
    yz_size = size_y * size_z
    if size_x > _INT64_MAX // yz_size:
        return None

    return PackedVoxelLayout(
        base_x=min_x,
        base_y=min_y,
        base_z=min_z,
        size_x=size_x,
        size_y=size_y,
        size_z=size_z,
    )


def _packed_voxel_keys(
    points: laspy.ScaleAwarePointRecord,
    resolution: float,
    layout: PackedVoxelLayout,
) -> np.ndarray:
    x = np.floor(np.asarray(points.x) / resolution).astype(np.int64) - layout.base_x
    y = np.floor(np.asarray(points.y) / resolution).astype(np.int64) - layout.base_y
    z = np.floor(np.asarray(points.z) / resolution).astype(np.int64) - layout.base_z
    # Headers written by some exporters understate the real extent. Packed keys
    # would alias distinct voxels in that case, so refuse and let the caller
    # fall back to unpacked keys.
    if (
        x.min() < 0
        or y.min() < 0
        or z.min() < 0
        or x.max() >= layout.size_x
        or y.max() >= layout.size_y
        or z.max() >= layout.size_z
    ):
        raise _LayoutMismatch
    return (x * layout.size_y + y) * layout.size_z + z


def _chunk_first_indices(keys: np.ndarray) -> np.ndarray:
    _, first_indices = np.unique(keys, return_index=True)
    first_indices.sort()
    return first_indices.astype(np.int64, copy=False)


def _downsample_to_output(
    input_path: Path,
    output_path: Path,
    resolution: float,
    chunk_size: int,
    progress_callback: Optional[ProgressCallback],
    use_packed_layout: bool,
    cancel_event: Optional[threading.Event] = None,
) -> tuple[int, int]:
    temporary_file = tempfile.NamedTemporaryFile(
        prefix=f".{output_path.name}.",
        suffix=".tmp",
        dir=output_path.parent,
        delete=False,
    )
    temporary_path = Path(temporary_file.name)
    temporary_file.close()

    try:
        with laspy.open(input_path) as reader:
            total_points = int(reader.header.point_count)
            header = copy.deepcopy(reader.header)
            packed_layout = (
                _compute_packed_layout(reader.header, resolution) if use_packed_layout else None
            )

            kept_points = 0
            processed = 0
            seen_voxels: set = set()

            with laspy.open(temporary_path, mode="w", header=header) as writer:
                for points in reader.chunk_iterator(chunk_size):
                    raise_if_cancelled(cancel_event)
                    point_count = len(points)
                    if point_count == 0:
                        continue

                    if packed_layout is None:
                        keys = _voxel_keys(points, resolution)
                        first_indices = _chunk_first_indices(keys)
                        keep_indices: list[int] = []
                        for index in first_indices.tolist():
                            key = keys[index].tobytes()
                            if key in seen_voxels:
                                continue
                            seen_voxels.add(key)
                            keep_indices.append(index)
                    else:
                        packed_keys = _packed_voxel_keys(points, resolution, packed_layout)
                        first_indices = _chunk_first_indices(packed_keys)
                        keep_indices = []
                        for index in first_indices.tolist():
                            key = int(packed_keys[index])
                            if key in seen_voxels:
                                continue
                            seen_voxels.add(key)
                            keep_indices.append(index)

                    if keep_indices:
                        selected = points[np.asarray(keep_indices, dtype=np.int64)]
                        writer.write_points(selected)
                        kept_points += len(selected)

                    processed += point_count
                    if progress_callback is not None:
                        progress_callback(processed, total_points)

        temporary_path.replace(output_path)
    except BaseException:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return total_points, kept_points


def downsample_las(
    input_path: Path,
    resolution: float,
    *,
    chunk_size: int = 2_000_000,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
) -> DownsampleResult:
    input_path = Path(input_path)

    if input_path.suffix.lower() != ".las":
        raise ValueError(f"Only .las files are supported: {input_path.name}")

    output_path = build_output_path(input_path, resolution)
    if output_path.exists():
        return DownsampleResult(
            input_path=input_path,
            output_path=output_path,
            input_points=0,
            output_points=0,
            skipped=True,
            message="Skipped because the output file already exists.",
        )

    use_packed_layout = True
    while True:
        try:
            total_points, kept_points = _downsample_to_output(
                input_path,
                output_path,
                resolution,
                chunk_size,
                progress_callback,
                use_packed_layout,
                cancel_event,
            )
            break
        except _LayoutMismatch:
            use_packed_layout = False

    return DownsampleResult(
        input_path=input_path,
        output_path=output_path,
        input_points=total_points,
        output_points=kept_points,
        skipped=False,
        message="Processing completed.",
    )
