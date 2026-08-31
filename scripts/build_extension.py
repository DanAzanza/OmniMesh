"""
OmniMesh Packaging Script.
Builds the official blender extension .zip archive (omnimesh-v1.2.0.zip) for Blender 4.2+ and 5.2 LTS.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path

PACKAGE_NAME = "omnimesh-v1.2.0.zip"
INCLUDE_DIRS = ["core", "exporters", "ui"]
INCLUDE_FILES = [
    "__init__.py",
    "blender_manifest.toml",
    "LICENSE",
    "README.md",
]


def build_package():
    repo_root = Path(__file__).resolve().parent.parent
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(exist_ok=True)
    zip_path = dist_dir / PACKAGE_NAME

    print(f"Building OmniMesh release package: {zip_path}")

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
