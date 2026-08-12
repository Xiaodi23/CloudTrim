# LasTool

LasTool is a lightweight Windows desktop application for batch processing `.las` point clouds. It keeps the original LAS point format and attributes while providing a simple English-language interface for common preprocessing tasks.

## Features

- **Batch voxel downsampling** — keep the first point encountered in each 3D voxel.
- **Polygon crop** — draw a polygon in a sampled XY top view and export all full-resolution points inside it.
- **Line split** — draw a directed line and export the points on its left and right sides.
- **Grid split** — divide the full bounds or a selected rectangle into a configurable row-by-column grid.
- **Multi-file workflow** — preview and apply the same crop or split selection to several LAS files.
- **Background processing** — keep the interface responsive and process independent files in parallel.
- **Safe outputs** — never overwrite an existing result and remove incomplete files after failures.

## Download and Use the Portable Version

1. Download `LasTool-windows-x64.zip` from the latest GitHub release.
2. Extract the complete archive to a writable folder.
3. Double-click `LasTool.exe` inside the extracted `LasTool` folder.

No Python installation is required. Keep the `_internal` folder next to `LasTool.exe`; it contains the portable runtime.

Windows SmartScreen may warn about unsigned community software. Review the release source and checksums before choosing **More info > Run anyway**.

## Run from Source

Python 3.9 or later is required. On Windows:

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

## Output Files

Results are written next to each input file. Existing outputs are skipped.

| Operation | Output naming |
| --- | --- |
| Downsample at 0.2 m | `source_ds_0p2m.las` |
| Polygon crop | `source_crop.las` |
| Line split | `source_split_left.las`, `source_split_right.las` |
| 2 x 4 grid split | `source_grid_2x4_p1.las` through `source_grid_2x4_p8.las` |

Grid part numbers run from the top-left cell to the bottom-right cell, row by row.

## Build the Portable ZIP

The build script creates an isolated virtual environment so packages from a global Python or Anaconda installation are not collected into the application:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Expected outputs:

- `dist\LasTool\LasTool.exe`
- `dist\LasTool-windows-x64.zip`

The script removes its temporary virtual environment and PyInstaller work files after a successful build. Pass `-KeepBuildEnvironment` while iterating locally if you want to reuse the environment.

GitHub Actions runs the tests on pushes and pull requests. Tags matching `v*` also build and publish the Windows archive.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite covers downsampling consistency and failure cleanup, output paths, input validation, preview sampling and coloring, combined previews, polygon crops, line splits, grid splits, and the English-only application UI rule.

## Current Limitations

- Only uncompressed `.las` files are supported; `.laz` is not yet supported.
- Selection operates in an XY top view. There is no 3D box selection or free rotation.
- Downsampling keeps the first point in each voxel rather than computing a centroid.
- Downsampling reads in chunks, but its set of unique voxel keys can still grow with the data. Extremely large or very sparse clouds may require substantial memory.
- Processing cannot currently be cancelled after it starts.
- Outputs always go next to the input file and use a skip-if-existing policy.

## Privacy and Repository Hygiene

LasTool performs all point-cloud processing locally. It does not make network requests, collect telemetry, upload files, or require credentials. Generated LAS files, build folders, virtual environments, archives, caches, and machine-specific PyInstaller specifications are excluded from Git.

Before publishing a fork, run the checks in [`docs/release-checklist.md`](docs/release-checklist.md) and inspect your Git history for personal names, email addresses, credentials, data files, and absolute local paths.

## License

LasTool is released under the [MIT License](LICENSE).
