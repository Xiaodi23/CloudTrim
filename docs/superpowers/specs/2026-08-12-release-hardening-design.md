# LasTool Release Hardening Design

## Goal

Prepare LasTool for a public GitHub repository and provide a compact Windows portable ZIP that can be extracted and launched without installing Python.

## Scope

- Translate all user-facing desktop UI text, dialogs, status messages, and logs to English.
- Preserve the existing processing features: batch voxel downsampling, polygon crop, line split, grid split, multi-file preview, and parallel processing.
- Prevent incomplete downsample outputs from being mistaken for completed files after an error.
- Remove private build paths and keep generated artifacts out of source control.
- Add standard project metadata, licensing, contributor-facing documentation, automated tests, and a reproducible Windows build workflow.
- Produce and inspect a local portable ZIP.

## Release Shape

The repository will contain source code, tests, project metadata, and build automation. End users will receive a folder-style PyInstaller distribution inside `LasTool-windows-x64.zip`; after extraction they launch `LasTool.exe`. A folder distribution is preferred over one-file mode because it starts faster and is less likely to trigger antivirus heuristics.

The local package will be built from a clean virtual environment so PyInstaller cannot collect unrelated Anaconda packages. GitHub Actions will build on a clean Windows runner using a supported CPython release.

## Application Changes

All strings visible to users will be English, including buttons, tab names, table headings, hints, progress states, message boxes, logs, and core processing messages. Python symbol names and file naming conventions remain stable to avoid unnecessary behavioral changes.

Downsampling will write to a unique temporary LAS file in the destination directory. Only a successfully closed output is moved atomically to the final name. Any exception removes the temporary file. Existing final outputs continue to be skipped.

No large GUI restructuring is included. The current `gui.py` is large, but splitting it while simultaneously translating and release-hardening would increase regression risk. Modularizing the two pages is documented as a future improvement.

## Packaging and Repository Hygiene

- Runtime dependencies and development/build dependencies will be separated.
- `pyproject.toml` will define project metadata, supported Python version, console entry point, and package discovery.
- `.gitignore` will cover virtual environments, test/tool caches, build artifacts, archives, generated LAS outputs, and local Codex directories.
- `.gitattributes` will normalize text files and keep generated archives out of diffs.
- The repository will include an MIT license and an English README with source and portable usage instructions.
- A Windows GitHub Actions workflow will run tests and build the portable ZIP without embedding machine-specific paths.

## Error Handling

Processing functions validate input type and parameters before writing. Existing outputs are never overwritten. Crop and split operations continue to remove outputs created during a failed run. Downsampling gains the same guarantee through temporary-file output and atomic promotion.

Build scripts stop on errors, create an isolated environment, install only declared build dependencies, remove only the known project build directories, and verify that the expected executable exists before creating the archive.

## Verification

- Unit tests cover output naming, validation, downsampling across chunks, and cleanup after an injected processing failure.
- Existing crop, split, preview, color, and grid tests remain green.
- Static compilation and package metadata validation run successfully.
- A clean PyInstaller build produces `LasTool.exe` and the portable ZIP.
- The archive is inspected for expected files, reasonable size, and absence of private absolute paths or common secret patterns.

## Out of Scope and Follow-up Opportunities

- LAZ support, configurable output directories, overwrite policies, cancellation, and true bounded-memory external voxel deduplication are not added in this release.
- `gui.py` should later be split into application, downsample-page, split/crop-page, and shared-widget modules.
- Very large point clouds can still require memory proportional to the number of unique voxels during downsampling; solving this cleanly needs an external sort or partitioned deduplication design.
