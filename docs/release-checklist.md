# Release Checklist

## Release Candidate

- Artifact: `dist/LasTool-windows-x64.zip`
- Archive size: 26,155,625 bytes (24.94 MB)
- Extracted size: 69.53 MB
- ZIP entries: 1,132
- SHA-256: `F56CEEEEB5E3F0859BE459BFEA7F81D37B3D8D798444AA477D4EA4FE537D3C22`
- Required entries confirmed: `LasTool/LasTool.exe`, `LasTool/README.md`, and `LasTool/LICENSE`

These values describe the local release candidate built on 2026-08-12. A GitHub Actions build can have a different hash when its Python or dependency patch versions differ.

## Automated Verification Performed

- `python -m unittest discover -s tests -v` — 15 tests passed.
- `python -m compileall -q main.py src tests` — passed.
- `.build-venv\Scripts\python.exe -m pip check` — no broken requirements.
- Workflow YAML parsed successfully.
- PyInstaller completed from the isolated `.build-venv` environment.
- Temporary `.build-venv` and `build` directories were removed automatically after packaging.
- Portable executable remained running during a three-second launch smoke test and was then terminated by the test harness.
- ZIP contains the executable, README, license, and portable runtime.
- No directories for MKL, SciPy, matplotlib, pandas, scikit-learn, PyProj, Torch, TensorFlow, or Conda were bundled.
- No user-profile paths, local Python-install paths, common credential patterns, private keys, tokens, or personal email addresses were found in the source release surface or packaged binaries.
- `git diff --check` reported no whitespace errors.

NumPy 2 ships an OpenBLAS binary whose filename contains `libscipy_openblas`; this is a NumPy runtime dependency, not the SciPy package.

The machine-wide Anaconda environment has unrelated package conflicts involving `conda-repo-cli`, Pillow, `ocrmypdf`, and `pikepdf`. They are not present in the isolated build environment and do not affect the portable archive.

## Manual Smoke Test Before a Public Release

1. Copy the ZIP to a clean Windows 10 or Windows 11 machine.
2. Verify the SHA-256 published with that release.
3. Extract the complete `LasTool` folder.
4. Launch `LasTool.exe` and confirm both tabs open with English controls.
5. Load a small `.las` sample and run batch downsampling.
6. Load the same sample in Split / Crop and verify polygon crop, line split, and a 2 x 2 grid split.
7. Confirm outputs retain LAS attributes and appear next to the source file.
8. Run an operation a second time and confirm existing outputs are skipped rather than overwritten.
9. Confirm no unexpected network or firewall prompt appears.
10. Scan the archive with Microsoft Defender or the release service of choice.

## GitHub Release Steps

1. Review the working tree and commit the intended source, test, workflow, and documentation changes.
2. Push the release branch and merge it through the preferred review process.
3. Create and push a version tag, for example:

   ```powershell
   git tag v0.1.0
   git push origin v0.1.0
   ```

4. The `Windows tests and release` workflow will run tests, build the portable archive, upload the workflow artifact, and attach the ZIP to the GitHub release.
5. Download the GitHub-built artifact, repeat the manual smoke test, and publish its SHA-256 in the release notes.

## Repository Privacy Check

Before pushing a new repository or fork, inspect both tracked files and history:

```powershell
git status --short
git ls-files
git log --all --format="%h | %an | %ae | %s"
git remote -v
```

Generated `.spec` files remain under ignored build output and must not be committed because PyInstaller may write machine-specific absolute paths into them.
