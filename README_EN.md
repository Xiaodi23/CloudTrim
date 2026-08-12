[简体中文](README.md) | [English](README_EN.md)

# LasTool

[![Windows tests and release](https://github.com/xya-0143/lasTool/actions/workflows/windows-release.yml/badge.svg)](https://github.com/xya-0143/lasTool/actions/workflows/windows-release.yml)
[![Latest release](https://img.shields.io/github/v/release/xya-0143/lasTool)](https://github.com/xya-0143/lasTool/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4.svg)](https://github.com/xya-0143/lasTool/releases/latest)

LasTool is a lightweight Windows desktop application for batch processing `.las` point clouds. It supports voxel downsampling, polygon cropping, line splitting, and grid splitting while preserving the original LAS point format and attributes. All processing happens locally. The application interface is in English.

> [Download the Windows portable package v0.1.0](https://github.com/xya-0143/lasTool/releases/download/v0.1.0/LasTool-windows-x64.zip) · [View all releases](https://github.com/xya-0143/lasTool/releases)

## Features

- Batch voxel downsampling keeps the first point encountered in each 3D voxel.
- Polygon crop lets you draw a polygon in a sampled XY top view, then exports full-resolution points inside it.
- Line split uses a directed line to export points on its left and right sides.
- Grid split divides the full bounds into a configurable row-by-column grid or limits the operation to a selected rectangle.
- Multi-file processing previews several LAS files and applies one crop or split selection to all of them.
- Long-running work stays in the background, and independent files can be processed in parallel.
- Existing results are never overwritten. Incomplete outputs are removed after a failure.

## Download and use the portable version

1. Download [LasTool-windows-x64.zip](https://github.com/xya-0143/lasTool/releases/download/v0.1.0/LasTool-windows-x64.zip).
2. Extract the complete archive to a writable folder.
3. Open the extracted `LasTool` folder and double-click `LasTool.exe`.

The portable package does not require Python. Do not move `LasTool.exe` by itself; the adjacent `_internal` folder contains the runtime components.

The application is not code-signed, so Windows SmartScreen may show a warning. Review the source and the GitHub release before choosing **More info > Run anyway**.

## Run from source

Python 3.9 or later is required. Run these commands in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\lastool.exe
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

- `dist\LasTool\LasTool.exe`
- `dist\LasTool-windows-x64.zip`

After a successful build, the script removes the temporary virtual environment and PyInstaller work files. Pass `-KeepBuildEnvironment` when iterating on the build if you want to reuse the environment.

GitHub Actions runs the tests on pushes and pull requests. Tags matching `v*` also build and publish the Windows portable package.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite covers downsampling consistency and failure cleanup, output paths, input validation, preview sampling and coloring, combined previews, polygon crops, line splits, grid splits, and the application source language rule.

## Current limitations

- Only uncompressed `.las` files are supported. `.laz` is not yet supported.
- Selection operates in an XY top view. There is no 3D box selection or free rotation.
- Downsampling keeps the first point in each voxel rather than calculating a centroid.
- Files are read in chunks, but the set of occupied voxel keys still grows with the data. Very large or sparse point clouds may require substantial memory.
- Processing cannot currently be cancelled after it starts.
- Outputs always go next to the input file, and existing results are always skipped.

## Privacy

LasTool does not make network requests, collect telemetry, upload point clouds, or require credentials. Generated LAS files, build directories, virtual environments, archives, caches, and machine-specific PyInstaller files are excluded from Git.

Before publishing a fork, follow [`docs/release-checklist.md`](docs/release-checklist.md) and inspect the Git history for names, email addresses, credentials, data files, and absolute local paths.

## License

LasTool is released under the [MIT License](LICENSE).
