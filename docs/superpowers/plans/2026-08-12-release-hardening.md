# LasTool Release Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a clean, English-language LasTool source repository and a compact Windows portable ZIP.

**Architecture:** Preserve the existing Tkinter GUI and LAS processing modules, add transactional output handling to downsampling, and make packaging reproducible through isolated dependency installation. Repository metadata and CI describe one supported build path shared by local and GitHub release builds.

**Tech Stack:** Python 3.9+, Tkinter, laspy, NumPy, tkinterdnd2, unittest, PyInstaller, PowerShell, GitHub Actions.

---

### Task 1: Lock Down Downsample Output Behavior

**Files:**
- Modify: `tests/test_downsample.py`
- Modify: `src/las_tool/downsample.py`

- [ ] **Step 1: Write failing tests for validation, naming, and failed-write cleanup**

Add tests that call `validate_resolution`, `build_output_path`, and inject a failing progress callback after the first written chunk. Assert that the final output and temporary output are absent after failure.

- [ ] **Step 2: Run the focused test and verify the cleanup test fails**

Run: `python -m unittest tests.test_downsample -v`

Expected: the injected failure leaves the current direct-write final output behind.

- [ ] **Step 3: Implement transactional output**

Create a unique sibling temporary path with `tempfile.NamedTemporaryFile(delete=False)`, write LAS data there, close the writer, and use `Path.replace` only after success. In `except`, remove the temporary file and re-raise.

- [ ] **Step 4: Run focused and full tests**

Run: `python -m unittest tests.test_downsample -v`

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass.

### Task 2: Translate the Product Surface to English

**Files:**
- Modify: `src/las_tool/gui.py`
- Modify: `src/las_tool/downsample.py`
- Modify: `src/las_tool/split_crop.py`

- [ ] **Step 1: Add a source-level UI language test**

Create a test that parses the GUI source and fails if CJK characters remain in user-facing application modules.

- [ ] **Step 2: Run the language test and verify it fails**

Run: `python -m unittest tests.test_ui_language -v`

Expected: failure lists current Chinese UI text.

- [ ] **Step 3: Translate all user-facing strings**

Translate window and tab titles, controls, table headings, hints, status text, message boxes, logs, and processing messages. Keep function names and output filenames stable.

- [ ] **Step 4: Run language and regression tests**

Run: `python -m unittest tests.test_ui_language -v`

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass and no CJK text remains in application source.

### Task 3: Add Public Repository Metadata

**Files:**
- Modify: `.gitignore`
- Create: `.gitattributes`
- Create: `LICENSE`
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`
- Modify: `requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: Define runtime and build dependencies**

Keep only runtime packages in `requirements.txt`; place test/build tooling in `requirements-dev.txt`. Define the `las-tool` package and `lastool` GUI entry point in `pyproject.toml`.

- [ ] **Step 2: Add repository hygiene and licensing**

Ignore local environments, caches, build folders, generated archives, generated point-cloud outputs, and editor/OS files. Add text normalization and an MIT license.

- [ ] **Step 3: Replace README with current English documentation**

Document all four processing modes, supported inputs, source installation, portable usage, build instructions, output names, limitations, tests, privacy, and release workflow.

- [ ] **Step 4: Validate installation metadata**

Run: `python -m pip install --no-deps -e .`

Run: `python -c "import las_tool; print(las_tool.__all__)"`

Expected: editable installation succeeds and the package imports.

### Task 4: Create Reproducible Portable Builds

**Files:**
- Modify: `build_exe.ps1`
- Create: `.github/workflows/windows-release.yml`

- [ ] **Step 1: Replace the build script with an isolated build**

Create `.build-venv`, install `requirements-dev.txt`, run PyInstaller with `--onedir`, explicit package collection, an English executable name, and exclusions for unrelated scientific packages. Verify the EXE, then archive the distribution as `dist/LasTool-windows-x64.zip`.

- [ ] **Step 2: Add Windows CI and release artifact upload**

On pushes and pull requests, run unit tests. On version tags, also run the build script and upload the ZIP as a workflow artifact and GitHub release asset.

- [ ] **Step 3: Build locally from the isolated environment**

Run: `powershell -ExecutionPolicy Bypass -File .\build_exe.ps1`

Expected: `dist/LasTool/LasTool.exe` and `dist/LasTool-windows-x64.zip` exist.

### Task 5: Release Audit and Verification

**Files:**
- Create: `docs/release-checklist.md`

- [ ] **Step 1: Run complete verification**

Run: `python -m unittest discover -s tests -v`

Run: `python -m compileall -q main.py src tests`

Run: `python -m pip check`

Expected: project tests and compilation pass; environment-only package conflicts are recorded separately if the global Anaconda environment is inconsistent.

- [ ] **Step 2: Inspect the archive**

List ZIP entries, confirm `LasTool.exe`, measure archive and extracted size, and scan source plus archive strings for private absolute paths, credentials, tokens, and email addresses.

- [ ] **Step 3: Record release results**

Document commands, expected release files, manual smoke-test instructions, known limitations, and GitHub tag/release steps in `docs/release-checklist.md`.

- [ ] **Step 4: Review the final diff**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors; only intended source, test, documentation, and packaging changes appear.
