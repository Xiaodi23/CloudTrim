from __future__ import annotations

from pathlib import Path

import laspy

SUPPORTED_SUFFIXES = (".las", ".laz")
FILE_DIALOG_TYPES = [("LAS / LAZ files", "*.las *.laz"), ("LAS files", "*.las"), ("LAZ files", "*.laz")]


def is_supported_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_SUFFIXES


def is_compressed_path(path: Path | str) -> bool:
    return Path(path).suffix.lower() == ".laz"


def laz_backend_available() -> bool:
    try:
        return bool(laspy.LazBackend.detect_available())
    except Exception:  # noqa: BLE001
        return False


def validate_point_cloud_path(path: Path | str) -> Path:
    """Return ``path`` if it is a readable/writable LAS or LAZ file name."""
    path = Path(path)
    if not is_supported_path(path):
        raise ValueError(f"Only .las and .laz files are supported: {path.name}")
    if is_compressed_path(path) and not laz_backend_available():
        raise ValueError(
            f"{path.name} is compressed, but no LAZ backend is installed. "
            "Install the 'lazrs' package to read or write .laz files."
        )
    return path
