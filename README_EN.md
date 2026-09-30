[简体中文](README.md) | [English](README_EN.md)

# CloudTrim

[![Windows tests and release](https://github.com/Xiaodi23/CloudTrim/actions/workflows/windows-release.yml/badge.svg)](https://github.com/Xiaodi23/CloudTrim/actions/workflows/windows-release.yml)
[![Latest release](https://img.shields.io/github/v/release/Xiaodi23/CloudTrim)](https://github.com/Xiaodi23/CloudTrim/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4.svg)](https://github.com/Xiaodi23/CloudTrim/releases/latest)

CloudTrim is a lightweight Windows desktop application for batch processing `.las` and `.laz` point clouds. It supports voxel downsampling, polygon cropping, line splitting, and grid splitting while preserving the original LAS point format and attributes. All processing happens locally. The application interface is in English.

> [Download the Windows portable package](https://github.com/Xiaodi23/CloudTrim/releases/latest) · [View all releases](https://github.com/Xiaodi23/CloudTrim/releases)

## Features

- Batch voxel downsampling keeps the first point encountered in each 3D voxel.
- Polygon crop lets you draw a polygon in a sampled XY top view, then exports full-resolution points inside it.
- Line split uses a directed line to export points on its left and right sides.
- Grid split divides the full bounds into a configurable row-by-column grid or limits the operation to a selected rectangle.
- Reads and writes both `.las` and compressed `.laz`; outputs keep the format of the input file.
- Multi-file processing previews several LAS/LAZ files and applies one crop or split selection to all of them.
- Long-running work stays in the background, independent files can be processed in parallel, and a progress bar and Cancel button are provided.
- Existing results are never overwritten. Incomplete outputs are removed after a failure.

## Performance

Files are read and written in chunks, so memory use does not grow linearly with file size, and multiple files can be processed in parallel.

The measurements below come from single-file runs on a Windows PC with an Intel Core i9-11900K, 64 GB of RAM, and a solid-state drive, using a random 20-million-point cloud (680 MB, point format 3):

| Operation | Time | Throughput |
| --- | --- | --- |
| Crop (half of the extent) | 2.4 s | about 8.5 M points/s |
| Line split | 2.2 s | about 9.1 M points/s |
| Voxel downsample (0.2 m, almost no duplicates) | 8.2 s | about 2.5 M points/s |
| Voxel downsample (1.0 m, 35% of points kept) | 5.1 s | about 3.9 M points/s |

Notes:

- Results depend on hardware, point distribution, and how many points are kept, so they will differ on other machines. Random points rarely share a voxel, which is a slower case for downsampling.
- For reference, a naive approach that loads all points with `laspy` and de-duplicates them with `numpy.unique` took 27.1 s on the same data.
- CloudTrim was not compared against LAStools, PDAL, CloudCompare, or other software, so no claim is made that it is faster than they are.

## Download and use the portable version

1. Download [CloudTrim-windows-x64.zip](https://github.com/Xiaodi23/CloudTrim/releases/latest).
2. Extract the complete archive to a writable folder.
3. Open the extracted `CloudTrim` folder and double-click `CloudTrim.exe`.

The portable package does not require Python. Do not move `CloudTrim.exe` by itself; the adjacent `_internal` folder contains the runtime components.

The application is not code-signed, so Windows SmartScreen may show a warning. Review the source and the GitHub release before choosing **More info > Run anyway**.

## Run from source

Python 3.9 or later is required. Run these commands in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\cloudtrim.exe
```

You can also run the repository entry point directly:

```powershell
$env:PYTHONPATH = ".\src"
python .\main.py
```

## Output files

Results are written next to each input file. If an output with the same name already exists, that file is skipped rather than overwritten.

| Operation | Output name |
| --- | --- |
| Downsample at 0.2 m | `source_ds_0p2m.las` |
| Polygon crop | `source_crop.las` |
| Line split | `source_split_left.las`, `source_split_right.las` |
| 2 x 4 grid split | `source_grid_2x4_p1.las` through `source_grid_2x4_p8.las` |

Grid part numbers run from the top-left cell to the bottom-right cell, row by row.

## Build the portable version

The build script creates an isolated virtual environment so unrelated packages from a global Python or Anaconda installation are not included:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Expected output:

- `dist\CloudTrim\CloudTrim.exe`
- `dist\CloudTrim-windows-x64.zip`

After a successful build, the script removes the temporary virtual environment and PyInstaller work files. Pass `-KeepBuildEnvironment` when iterating on the build if you want to reuse the environment.

GitHub Actions runs the tests on pushes and pull requests. Tags matching `v*` also build and publish the Windows portable package.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite covers downsampling consistency and failure cleanup, output paths, input validation, preview sampling and coloring, combined previews, polygon crops, line splits, grid splits, and the application source language rule.

## Current limitations

- Selection operates in an XY top view. There is no 3D box selection or free rotation.
- Downsampling keeps the first point in each voxel rather than calculating a centroid.
- Files are read in chunks, but the index of kept voxels still grows with the data (about 8 bytes per voxel). Very large or sparse point clouds may require substantial memory.
- Reading and writing `.laz` needs the `lazrs` backend (bundled in the portable package). On a synthetic 6-million-point terrain, `.laz` was about 3.2x smaller than `.las` with roughly a third lower throughput; real data will compress differently.
- Outputs always go next to the input file, and existing results are always skipped.

## Privacy

CloudTrim does not make network requests, collect telemetry, upload point clouds, or require credentials. Generated LAS files, build directories, virtual environments, archives, caches, and machine-specific PyInstaller files are excluded from Git.

Before publishing a fork, follow [`docs/release-checklist.md`](docs/release-checklist.md) and inspect the Git history for names, email addresses, credentials, data files, and absolute local paths.

## License

CloudTrim is released under the [MIT License](LICENSE).
