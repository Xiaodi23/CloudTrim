from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import laspy
import numpy as np


ProgressCallback = Callable[[int, int], None]


@dataclass
class DownsampleResult:
    input_path: Path
    output_path: Path
    input_points: int
    output_points: int
    skipped: bool = False
    message: str = ""


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
        raise ValueError("分辨率必须是数字。") from exc

    if resolution <= 0:
        raise ValueError("分辨率必须大于 0。")

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


def downsample_las(
    input_path: Path,
    resolution: float,
    *,
    chunk_size: int = 1_000_000,
    progress_callback: Optional[ProgressCallback] = None,
) -> DownsampleResult:
    input_path = Path(input_path)

    if input_path.suffix.lower() != ".las":
        raise ValueError(f"仅支持 .las 文件: {input_path.name}")

    output_path = build_output_path(input_path, resolution)
    if output_path.exists():
        return DownsampleResult(
            input_path=input_path,
            output_path=output_path,
            input_points=0,
            output_points=0,
            skipped=True,
            message="输出文件已存在，已跳过。",
        )

    total_points = 0
    kept_points = 0
    seen_voxels: set[bytes] = set()

    with laspy.open(input_path) as reader:
        total_points = reader.header.point_count
        header = copy.deepcopy(reader.header)

        with laspy.open(output_path, mode="w", header=header) as writer:
            processed = 0

            for points in reader.chunk_iterator(chunk_size):
                point_count = len(points)
                if point_count == 0:
                    continue

                keys = _voxel_keys(points, resolution)
                _, first_indices = np.unique(keys, return_index=True)
                first_indices.sort()

                keep_indices = []
                for index in first_indices.tolist():
                    key = keys[index].tobytes()
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

    return DownsampleResult(
        input_path=input_path,
        output_path=output_path,
        input_points=total_points,
        output_points=kept_points,
        skipped=False,
        message="处理完成。",
    )
