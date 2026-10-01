[简体中文](README.md) | [English](README_EN.md)

# CloudTrim

[![Tests and release](https://github.com/Xiaodi23/CloudTrim/actions/workflows/windows-release.yml/badge.svg)](https://github.com/Xiaodi23/CloudTrim/actions/workflows/windows-release.yml)
[![Latest release](https://img.shields.io/github/v/release/Xiaodi23/CloudTrim)](https://github.com/Xiaodi23/CloudTrim/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

CloudTrim is a lightweight Windows desktop tool for batch processing `.las` and `.laz` point clouds: voxel downsampling, polygon crop, line split, and grid split. Outputs keep the original point format and all attributes, and everything runs locally.

**[Download the Windows portable build](https://github.com/Xiaodi23/CloudTrim/releases/latest)**

## Features

- **Voxel downsampling**: keeps the first point hit in each 3D voxel.
- **Polygon crop**: draw a polygon on an XY top-view preview and export every original point inside it.
- **Line split**: draw a directed line and export the points on each side.
- **Grid split**: cut the cloud into rows × columns, optionally within a selected rectangle.
- **LAS / LAZ**: outputs keep the input format.
- **Batch processing**: one selection is applied to many files, processed in parallel in the background with a progress bar and Cancel button.
- **Safe output**: existing files are never overwritten; incomplete outputs are removed on failure or cancel.

## Performance

Files are streamed in chunks, so memory does not grow linearly with file size. Measured on an i9-11900K, 64 GB RAM, SSD, with a random 20-million-point (680 MB) cloud, single file:

| Operation | Time | Throughput |
| --- | --- | --- |
| Crop (half of the extent) | 2.4 s | ~8.5 M points/s |
| Line split | 2.2 s | ~9.1 M points/s |
| Voxel downsample (0.2 m, almost no duplicates) | 8.2 s | ~2.5 M points/s |
| Voxel downsample (1.0 m, 35% kept) | 5.1 s | ~3.9 M points/s |

Results vary with hardware and point distribution; random points rarely share voxels, which is a slow case for downsampling. For reference, loading everything with `laspy` and de-duplicating with `numpy.unique` took 27.1 s. No comparison with other software was made.

## Usage

### Portable build

1. Download [CloudTrim-windows-x64.zip](https://github.com/Xiaodi23/CloudTrim/releases/latest) and extract it completely.
2. Run `CloudTrim\CloudTrim.exe` (no Python needed; don't move the exe on its own).

The app is not code-signed, so SmartScreen may warn; choose **More info > Run anyway**.

### From source

Requires Python 3.9+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\cloudtrim.exe
```

## Output files

Results are written next to each input file; existing files are skipped.

| Operation | Output name |
| --- | --- |
| Downsample at 0.2 m | `source_ds_0p2m.las` |
| Polygon crop | `source_crop.las` |
| Line split | `source_split_left.las`, `source_split_right.las` |
| 2 x 4 grid split | `source_grid_2x4_p1.las` … `p8.las` (numbered row by row from top-left) |

## Development

```powershell
python -m unittest discover -s tests -v          # tests
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1   # build the portable package
```

The build script uses an isolated virtual environment and produces `dist\CloudTrim-windows-x64.zip`. Pushing a `v*` tag makes GitHub Actions test, build, and publish a release.

## Limitations

- Selection works in an XY top view; there is no 3D box selection.
- Downsampling keeps the first point in a voxel rather than the centroid.
- The index of kept voxels grows with the data (~8 bytes per voxel), so very large or sparse clouds can use a lot of memory.
- `.laz` needs `lazrs` (bundled in the portable build) and runs about a third slower than `.las`.
- Outputs always go next to the input file.

## Privacy

CloudTrim makes no network requests, collects no telemetry, and uploads no point clouds.

## License

[MIT](LICENSE)
