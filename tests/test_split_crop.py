from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import laspy
import numpy as np

from las_tool.split_crop import (
    Bounds2D,
    LineSelection,
    build_crop_output_path,
    build_split_output_paths,
    crop_las,
    load_preview_data,
    split_las,
)


def _write_sample_las(path: Path) -> None:
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.01, 0.01, 0.01])
    header.offsets = np.array([0.0, 0.0, 0.0])

    las = laspy.LasData(header)
    las.x = np.array([-2.0, -0.5, 0.0, 0.5, 2.0], dtype=np.float64)
    las.y = np.array([0.0, 0.4, 0.8, 1.2, 1.6], dtype=np.float64)
    las.z = np.array([1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float64)
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


if __name__ == "__main__":
    unittest.main()
