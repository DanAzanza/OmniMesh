"""
OmniMesh Packaging Script.
Builds the official blender extension .zip archive (omnimesh-v1.2.0.zip) for Blender 4.2+ and 5.2 LTS.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

INCLUDE_DIRS = ["bridges", "core", "exporters", "presets", "ui"]
INCLUDE_FILES = [
    "__init__.py",
    "blender_manifest.toml",
    "LICENSE",
    "README.md",
]


def get_version(repo_root: Path) -> str:
    """Reads the version string from blender_manifest.toml."""
    manifest_path = repo_root / "blender_manifest.toml"
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("version ="):
                return line.split("=")[1].strip().strip('"').strip("'")
    return "0.8.0"


def build_package():
    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(exist_ok=True)
    version = get_version(repo_root)
    package_name = f"omnimesh-v{version}.zip"
    zip_path = dist_dir / package_name

    print(f"Building OmniMesh release package v{version}: {zip_path}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Include root files
        for filename in INCLUDE_FILES:
            file_path = repo_root / filename
            if file_path.exists():
                zf.write(file_path, arcname=filename)
                print(f"  + Added file: {filename}")

        # Include subdirectories
        for dir_name in INCLUDE_DIRS:
            dir_path = repo_root / dir_name
            if dir_path.exists():
                for root, _, files in os.walk(dir_path):
                    for file in files:
                        if file.endswith((".py", ".json", ".txt")) and not file.startswith("."):
                            full_path = Path(root) / file
                            arc_name = full_path.relative_to(repo_root)
                            zf.write(full_path, arcname=str(arc_name).replace("\\", "/"))
                            print(f"  + Added: {arc_name}")

    print(f"\nSuccessfully built {zip_path} ({zip_path.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build_package()
