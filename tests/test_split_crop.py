from __future__ import annotations

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

from las_tool.split_crop import (
    Bounds2D,
    GridSelection,
    LineSelection,
    PolygonSelection,
    build_crop_output_path,
    build_grid_output_paths,
    build_split_output_paths,
    combine_preview_data,
    crop_las,
    grid_split_las,
    load_preview_data,
    split_las,
)


def _write_sample_las(
    path: Path,
    *,
    xs: np.ndarray | None = None,
    ys: np.ndarray | None = None,
    zs: np.ndarray | None = None,
    point_format: int = 3,
    rgb: np.ndarray | None = None,
) -> None:
    header = laspy.LasHeader(point_format=point_format, version="1.2")
    header.scales = np.array([0.01, 0.01, 0.01])
    header.offsets = np.array([0.0, 0.0, 0.0])

    las = laspy.LasData(header)
    las.x = (
        xs.astype(np.float64)
        if xs is not None
        else np.array([-2.0, -0.5, 0.0, 0.5, 2.0], dtype=np.float64)
    )
    las.y = (
        ys.astype(np.float64)
        if ys is not None
        else np.array([0.0, 0.4, 0.8, 1.2, 1.6], dtype=np.float64)
    )
    las.z = (
        zs.astype(np.float64)
        if zs is not None
        else np.array([1.0, 1.2, 1.4, 1.6, 1.8], dtype=np.float64)
    )

    if rgb is not None:
        las.red = rgb[:, 0].astype(np.uint16)
        las.green = rgb[:, 1].astype(np.uint16)
        las.blue = rgb[:, 2].astype(np.uint16)

    las.write(path)


class SplitCropTests(unittest.TestCase):
    def test_load_preview_data_respects_bounds_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sample.las"
            _write_sample_las(input_path)

            preview = load_preview_data(input_path, max_points=2)

            self.assertEqual(preview.total_points, 5)
            self.assertLessEqual(len(preview.preview_points), 2)
            self.assertEqual(preview.bounds.min_x, -2.0)
            self.assertEqual(preview.bounds.max_x, 2.0)
            self.assertEqual(preview.bounds.min_y, 0.0)
            self.assertEqual(preview.bounds.max_y, 1.6)
            self.assertEqual(preview.preview_colors.shape[1], 3)

    def test_load_preview_data_uses_rgb_colors_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "color_sample.las"
            _write_sample_las(
                input_path,
                xs=np.array([0.0, 1.0], dtype=np.float64),
                ys=np.array([0.0, 1.0], dtype=np.float64),
                zs=np.array([10.0, 20.0], dtype=np.float64),
                point_format=2,
                rgb=np.array([[65535, 0, 0], [0, 65535, 0]], dtype=np.uint16),
            )

            preview = load_preview_data(input_path, max_points=10)

            self.assertEqual(preview.preview_colors.shape, (2, 3))
            self.assertGreater(preview.preview_colors[0, 0], preview.preview_colors[0, 1])
            self.assertGreater(preview.preview_colors[1, 1], preview.preview_colors[1, 0])

    def test_load_preview_data_falls_back_to_elevation_colors_without_rgb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "z_sample.las"
            _write_sample_las(
                input_path,
                xs=np.array([0.0, 1.0, 2.0], dtype=np.float64),
                ys=np.array([0.0, 1.0, 2.0], dtype=np.float64),
                zs=np.array([10.0, 20.0, 30.0], dtype=np.float64),
                point_format=1,
            )

            preview = load_preview_data(input_path, max_points=10)

            self.assertEqual(preview.preview_colors.shape, (3, 3))
            unique_colors = np.unique(preview.preview_colors, axis=0)
            self.assertGreaterEqual(unique_colors.shape[0], 2)

    def test_combine_preview_data_merges_bounds_and_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            left_path = Path(tmpdir) / "left.las"
            right_path = Path(tmpdir) / "right.las"
            _write_sample_las(
                left_path,
                xs=np.array([0.0, 1.0], dtype=np.float64),
                ys=np.array([0.0, 1.0], dtype=np.float64),
                zs=np.array([1.0, 2.0], dtype=np.float64),
            )
            _write_sample_las(
                right_path,
                xs=np.array([10.0, 11.0], dtype=np.float64),
                ys=np.array([10.0, 11.0], dtype=np.float64),
                zs=np.array([3.0, 4.0], dtype=np.float64),
            )

            combined = combine_preview_data(
                [
                    load_preview_data(left_path, max_points=10),
                    load_preview_data(right_path, max_points=10),
                ]
            )

            self.assertEqual(combined.total_points, 4)
            self.assertEqual(combined.bounds.min_x, 0.0)
            self.assertEqual(combined.bounds.max_x, 11.0)
            self.assertEqual(combined.bounds.min_y, 0.0)
            self.assertEqual(combined.bounds.max_y, 11.0)
            self.assertEqual(combined.preview_points.shape, (4, 2))
            self.assertEqual(combined.preview_colors.shape, (4, 3))

    def test_crop_las_writes_only_points_inside_rectangle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sample.las"
            _write_sample_las(input_path)

            result = crop_las(input_path, Bounds2D(min_x=-1.0, max_x=1.0, min_y=0.0, max_y=1.2))

            self.assertFalse(result.skipped)
            self.assertFalse(result.empty)
            self.assertEqual(result.output_points, 3)
            self.assertTrue(result.output_path.exists())

            cropped = laspy.read(result.output_path)
            self.assertEqual(len(cropped.points), 3)
            self.assertTrue(np.all(cropped.x >= -1.0))
            self.assertTrue(np.all(cropped.x <= 1.0))
            self.assertTrue(np.all(cropped.y >= 0.0))
            self.assertTrue(np.all(cropped.y <= 1.2))

    def test_crop_las_writes_only_points_inside_polygon(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "polygon_sample.las"
            _write_sample_las(
                input_path,
                xs=np.array([0.2, 0.9, 1.8, 2.6, 3.4], dtype=np.float64),
                ys=np.array([0.2, 1.0, 2.1, 1.1, 0.3], dtype=np.float64),
                zs=np.ones(5, dtype=np.float64),
                point_format=1,
            )

            polygon = PolygonSelection(points=((0.0, 0.0), (2.0, 3.0), (3.0, 0.0)))
            result = crop_las(input_path, polygon)

            self.assertFalse(result.skipped)
            self.assertFalse(result.empty)
            cropped = laspy.read(result.output_path)
            self.assertEqual(len(cropped.points), 4)
            self.assertTrue(np.allclose(cropped.x, [0.2, 0.9, 1.8, 2.6]))

    def test_crop_las_returns_empty_without_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sample.las"
            _write_sample_las(input_path)
            output_path = build_crop_output_path(input_path)

            result = crop_las(input_path, Bounds2D(min_x=10.0, max_x=11.0, min_y=10.0, max_y=11.0))

            self.assertTrue(result.empty)
            self.assertFalse(output_path.exists())

    def test_split_las_writes_left_and_right_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sample.las"
            _write_sample_las(input_path)

            result = split_las(input_path, LineSelection(x1=0.0, y1=-1.0, x2=0.0, y2=2.0))

            self.assertFalse(result.skipped)
            self.assertEqual(result.left_points, 3)
            self.assertEqual(result.right_points, 2)
            self.assertEqual(result.left_points + result.right_points, 5)

            left = laspy.read(result.left_output_path)
            right = laspy.read(result.right_output_path)
            self.assertTrue(np.all(left.x <= 0.0))
            self.assertTrue(np.all(right.x > 0.0))

    def test_split_las_skips_when_output_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "sample.las"
            _write_sample_las(input_path)
            left_output, right_output = build_split_output_paths(input_path)
            _write_sample_las(left_output)

            result = split_las(input_path, LineSelection(x1=0.0, y1=-1.0, x2=0.0, y2=2.0))

            self.assertTrue(result.skipped)
            self.assertIn(left_output.name, result.message)
            self.assertFalse(right_output.exists())

    def test_grid_split_las_writes_expected_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "grid_sample.las"
            _write_sample_las(
                input_path,
                xs=np.array([0.8, 1.2, 2.8, 3.2, 0.9, 1.1, 2.9, 3.1], dtype=np.float64),
                ys=np.array([3.2, 2.8, 3.2, 2.8, 1.2, 0.8, 1.2, 0.8], dtype=np.float64),
                zs=np.ones(8, dtype=np.float64),
                point_format=2,
                rgb=np.array(
                    [
                        [60000, 1000, 1000],
                        [50000, 2000, 2000],
                        [1000, 60000, 1000],
                        [2000, 50000, 2000],
                        [1000, 1000, 60000],
                        [2000, 2000, 50000],
                        [30000, 30000, 1000],
                        [28000, 28000, 2000],
                    ],
                    dtype=np.uint16,
                ),
            )

            selection = GridSelection(bounds=Bounds2D(0.0, 4.0, 0.0, 4.0), rows=2, cols=2)
            result = grid_split_las(input_path, selection)
            output_paths = build_grid_output_paths(input_path, 2, 2)

            self.assertFalse(result.skipped)
            self.assertEqual(len(result.parts), 4)
            self.assertEqual([part.output_path.name for part in result.parts], [path.name for path in output_paths])
            self.assertTrue(all(path.exists() for path in output_paths))
            self.assertEqual(sum(part.point_count for part in result.parts), 8)

            p1 = laspy.read(output_paths[0])
            p2 = laspy.read(output_paths[1])
            p3 = laspy.read(output_paths[2])
            p4 = laspy.read(output_paths[3])

            self.assertTrue(np.all(p1.x < 2.0))
            self.assertTrue(np.all(p1.y >= 2.0))
            self.assertTrue(np.all(p2.x >= 2.0))
            self.assertTrue(np.all(p2.y >= 2.0))
            self.assertTrue(np.all(p3.x < 2.0))
            self.assertTrue(np.all(p3.y < 2.0))
            self.assertTrue(np.all(p4.x >= 2.0))
            self.assertTrue(np.all(p4.y < 2.0))


if __name__ == "__main__":
    unittest.main()
