"""
OmniMesh Packaging Script.
Builds the official Blender extension ZIP archive for Blender 4.2+ and 5.2 LTS.
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
import re
import sys
import zipfile

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]

logger = logging.getLogger("om_build_extension")

INCLUDE_DIRS = ["bridges", "core", "exporters", "presets", "ui"]
INCLUDE_FILES = [
    "__init__.py",
    "blender_manifest.toml",
    "LICENSE",
    "README.md",
]


def get_version(repo_root: Path) -> str:
    """Reads and validates the version string across blender_manifest.toml and __init__.py."""
    manifest_path = repo_root / "blender_manifest.toml"
    manifest_version = None
    if manifest_path.exists():
        if tomllib is not None:
            with manifest_path.open("rb") as manifest_file:
                manifest = tomllib.load(manifest_file)
            manifest_version = manifest.get("version")
        else:
            content = manifest_path.read_text(encoding="utf-8")
            match = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if match:
                manifest_version = match.group(1)

    if not isinstance(manifest_version, str) or not manifest_version:
        raise FileNotFoundError(f"Blender manifest with a valid version not found: {manifest_path}")

    # Validate parity with __init__.py bl_info
    init_path = repo_root / "__init__.py"
    if init_path.exists():
        try:
            tree = ast.parse(init_path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == "bl_info":
                            bl_dict = ast.literal_eval(node.value)
                            bl_ver = bl_dict.get("version")
                            if isinstance(bl_ver, (tuple, list)):
                                bl_ver_str = ".".join(str(x) for x in bl_ver)
                                if bl_ver_str != manifest_version:
                                    raise ValueError(
                                        f"Version mismatch: blender_manifest.toml specifies '{manifest_version}' "
                                        f"but __init__.py specifies '{bl_ver_str}'."
                                    )
        except Exception as exc:
            if isinstance(exc, ValueError):
                raise
            logger.debug("Could not verify bl_info version: %s", exc)

    return manifest_version


def _add_file_to_zip(zf: zipfile.ZipFile, file_path: Path, arc_name: str) -> None:
    """Writes a file into the zip archive with normalized POSIX permissions (0o644)."""
    data = file_path.read_bytes()
    zinfo = zipfile.ZipInfo(arc_name)
    zinfo.create_system = 3  # UNIX
    # POSIX regular file permissions: -rw-r--r-- (0o100644)
    zinfo.external_attr = (0o644 | 0o100000) << 16
    zinfo.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(zinfo, data)


def build_package(repo_root: Path | None = None, clean_dist: bool = True) -> Path:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(exist_ok=True)
    version = get_version(repo_root)
    package_name = f"omnimesh-v{version}.zip"
    zip_path = dist_dir / package_name

    if clean_dist:
        for old_zip in dist_dir.glob("omnimesh-v*.zip"):
            try:
                old_zip.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Could not remove stale zip %s: %s", old_zip, exc)

    print(f"Building OmniMesh release package v{version}: {zip_path}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Include root files
        for filename in INCLUDE_FILES:
            file_path = repo_root / filename
            if file_path.exists():
                _add_file_to_zip(zf, file_path, filename)
                print(f"  + Added file: {filename}")

        # Include subdirectories
        for dir_name in INCLUDE_DIRS:
            dir_path = repo_root / dir_name
            if dir_path.exists():
                for root, _, files in os.walk(dir_path):
                    for file in sorted(files):
                        if file.endswith((".py", ".json", ".txt", ".png", ".svg")) and not file.startswith("."):
                            full_path = Path(root) / file
                            arc_name = str(full_path.relative_to(repo_root)).replace("\\", "/")
                            _add_file_to_zip(zf, full_path, arc_name)
                            print(f"  + Added: {arc_name}")

    print(f"\nSuccessfully built {zip_path} ({zip_path.stat().st_size / 1024:.1f} KB)")
    return zip_path


if __name__ == "__main__":
    build_package()
