from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import laspy
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from las_tool import formats
from las_tool.downsample import downsample_las
from las_tool.split_crop import (
    Bounds2D,
    GridSelection,
    LineSelection,
    crop_las,
    grid_split_las,
    load_preview_data,
    split_las,
)


HAS_LAZ_BACKEND = formats.laz_backend_available()


def _write_sample(path: Path, count: int = 200) -> None:
    header = laspy.LasHeader(point_format=3, version="1.2")
    header.scales = np.array([0.01, 0.01, 0.01])
    header.offsets = np.array([0.0, 0.0, 0.0])
    las = laspy.LasData(header)
    xs = np.linspace(0, 10, count)
    las.x = xs
    las.y = xs[::-1]
    las.z = xs / 2
    las.write(path)


def _is_compressed_on_disk(path: Path) -> bool:
    # The high bit of the point data format id marks LAZ-compressed points.
    with open(path, "rb") as handle:
        handle.seek(104)
        return bool(handle.read(1)[0] & 0x80)


@unittest.skipUnless(HAS_LAZ_BACKEND, "no LAZ backend installed")
class LazRoundTripTests(unittest.TestCase):
    def test_downsample_reads_and_writes_laz(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "cloud.laz"
            _write_sample(source)

            result = downsample_las(source, 1.0, chunk_size=50)

            self.assertEqual(result.output_path.suffix, ".laz")
            self.assertTrue(_is_compressed_on_disk(result.output_path))
            self.assertEqual(len(laspy.read(result.output_path).x), result.output_points)
            self.assertLess(result.output_points, result.input_points)
            self.assertEqual([p.suffix for p in Path(tmpdir).iterdir() if p.suffix == ".tmp"], [])

    def test_crop_split_and_grid_write_compressed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "cloud.laz"
            _write_sample(source)

            crop = crop_las(source, Bounds2D(0, 5, 0, 10), chunk_size=50)
            self.assertTrue(_is_compressed_on_disk(crop.output_path))
            self.assertGreater(crop.output_points, 0)

            split = split_las(source, LineSelection(5, 0, 5, 10), chunk_size=50)
            for path in (split.left_output_path, split.right_output_path):
                self.assertTrue(_is_compressed_on_disk(path))
            self.assertEqual(split.left_points + split.right_points, split.input_points)

            grid = grid_split_las(
                source, GridSelection(Bounds2D(0, 10, 0, 10), rows=1, cols=2), chunk_size=50
            )
            written = [part for part in grid.parts if not part.empty]
            self.assertTrue(written)
            for part in written:
                self.assertTrue(_is_compressed_on_disk(part.output_path))

    def test_las_input_can_produce_las_output_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "cloud.las"
            _write_sample(source)

            result = downsample_las(source, 1.0)

            self.assertEqual(result.output_path.suffix, ".las")
            self.assertFalse(_is_compressed_on_disk(result.output_path))

    def test_preview_loads_laz(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "cloud.laz"
            _write_sample(source)

            preview = load_preview_data(source, max_points=100)

            self.assertEqual(preview.total_points, 200)
            self.assertGreater(len(preview.preview_points), 0)


class LazValidationTests(unittest.TestCase):
    def test_missing_backend_gives_a_clear_error(self) -> None:
        with mock.patch.object(formats, "laz_backend_available", return_value=False):
            with self.assertRaisesRegex(ValueError, "lazrs"):
                downsample_las(Path("missing.laz"), 1.0)

    def test_unsupported_extension_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\.las and \.laz"):
            downsample_las(Path("cloud.xyz"), 1.0)


if __name__ == "__main__":
    unittest.main()
