from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

import laspy
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from las_tool.downsample import build_output_path, downsample_las, validate_resolution


def _write_sample_las(path: Path, xs: np.ndarray, ys: np.ndarray, zs: np.ndarray) -> None:
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.01, 0.01, 0.01])
    header.offsets = np.array([0.0, 0.0, 0.0])

    las = laspy.LasData(header)
    las.x = xs.astype(np.float64)
    las.y = ys.astype(np.float64)
    las.z = zs.astype(np.float64)
    las.red = np.linspace(1000, 4000, xs.shape[0], dtype=np.uint16)
    las.green = np.linspace(2000, 5000, xs.shape[0], dtype=np.uint16)
    las.blue = np.linspace(3000, 6000, xs.shape[0], dtype=np.uint16)
    las.write(path)


def _legacy_keep_indices(xs: np.ndarray, ys: np.ndarray, zs: np.ndarray, resolution: float, chunk_size: int) -> list[int]:
    kept_indices: list[int] = []
    seen_voxels: set[bytes] = set()

    for start in range(0, xs.shape[0], chunk_size):
        end = min(start + chunk_size, xs.shape[0])
        vx = np.floor(xs[start:end] / resolution).astype(np.int64)
        vy = np.floor(ys[start:end] / resolution).astype(np.int64)
        vz = np.floor(zs[start:end] / resolution).astype(np.int64)

        structured = np.empty(
            vx.shape[0],
            dtype=[("x", np.int64), ("y", np.int64), ("z", np.int64)],
        )
        structured["x"] = vx
        structured["y"] = vy
        structured["z"] = vz

        _, first_indices = np.unique(structured, return_index=True)
        first_indices.sort()

        for local_index in first_indices.tolist():
            key = structured[local_index].tobytes()
            if key in seen_voxels:
                continue
            seen_voxels.add(key)
            kept_indices.append(start + local_index)

    return kept_indices


class DownsampleTests(unittest.TestCase):
    def test_output_path_uses_resolution_tag(self) -> None:
        input_path = Path("survey.LAS")

        output_path = build_output_path(input_path, 0.25)

        self.assertEqual(output_path, Path("survey_ds_0p25m.las"))

    def test_validate_resolution_rejects_non_positive_and_non_numeric_values(self) -> None:
        self.assertEqual(validate_resolution(" 0.5 "), 0.5)

        for value in ("0", "-1", "not-a-number"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_resolution(value)

    def test_downsample_removes_incomplete_output_after_processing_error(self) -> None:
        xs = np.array([0.1, 1.1, 2.1, 3.1], dtype=np.float64)
        ys = np.array([0.1, 1.1, 2.1, 3.1], dtype=np.float64)
        zs = np.array([0.1, 1.1, 2.1, 3.1], dtype=np.float64)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sample.las"
            _write_sample_las(input_path, xs, ys, zs)
            output_path = build_output_path(input_path, 1.0)

            def fail_after_first_chunk(_done: int, _total: int) -> None:
                raise RuntimeError("injected processing failure")

            with self.assertRaisesRegex(RuntimeError, "injected processing failure"):
                downsample_las(
                    input_path,
                    1.0,
                    chunk_size=2,
                    progress_callback=fail_after_first_chunk,
                )

            self.assertFalse(output_path.exists())
            self.assertEqual(list(output_path.parent.glob(f".{output_path.name}.*.tmp")), [])

    def test_downsample_matches_legacy_result_across_chunks(self) -> None:
        xs = np.array([0.10, 0.20, 0.95, 1.10, 0.15, 2.20, 2.25, 3.01, 1.18, 4.90], dtype=np.float64)
        ys = np.array([0.10, 0.25, 0.90, 1.15, 0.40, 2.10, 2.15, 3.01, 1.19, 4.80], dtype=np.float64)
        zs = np.array([0.10, 0.15, 0.98, 1.05, 0.12, 2.20, 2.21, 3.02, 1.06, 4.81], dtype=np.float64)

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sample.las"
            _write_sample_las(input_path, xs, ys, zs)

            result = downsample_las(input_path, 1.0, chunk_size=3)

            expected_indices = _legacy_keep_indices(xs, ys, zs, resolution=1.0, chunk_size=3)
            output = laspy.read(result.output_path)

            self.assertEqual(result.output_points, len(expected_indices))
            self.assertTrue(np.allclose(output.x, xs[expected_indices]))
            self.assertTrue(np.allclose(output.y, ys[expected_indices]))
            self.assertTrue(np.allclose(output.z, zs[expected_indices]))

    def test_understated_header_bounds_do_not_drop_distinct_voxels(self) -> None:
        rng = np.random.default_rng(7)
        xs = rng.random(1000) * 100
        ys = rng.random(1000) * 100
        zs = rng.random(1000) * 10

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "bad_header.las"
            _write_sample_las(input_path, xs, ys, zs)

            # Overwrite max/min X, Y, Z in the header with a tiny box.
            data = bytearray(input_path.read_bytes())
            struct.pack_into("<6d", data, 179, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0)
            input_path.write_bytes(bytes(data))

            result = downsample_las(input_path, 0.5)

            source = laspy.read(input_path)
            expected = len(
                set(
                    zip(
                        np.floor(np.asarray(source.x) / 0.5).tolist(),
                        np.floor(np.asarray(source.y) / 0.5).tolist(),
                        np.floor(np.asarray(source.z) / 0.5).tolist(),
                    )
                )
            )
            self.assertEqual(result.output_points, expected)


if __name__ == "__main__":
    unittest.main()
