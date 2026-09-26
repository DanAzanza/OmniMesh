"""
Cross-Platform CLI Runner for OmniMesh In-Blender Integration Tests.
Executes headless Blender with factory startup and streams results.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger("om_test_runner")


def find_blender_binary() -> str | None:
    """Locate Blender executable across Windows, macOS, and Linux platforms."""
    # 1. User-specified environment variable
    custom_bin = os.environ.get("BLENDER_PATH") or os.environ.get("BLENDER_BIN")
    if custom_bin and os.path.isfile(custom_bin):
        return custom_bin

    # 2. System PATH
    path_bin = shutil.which("blender")
    if path_bin:
        return path_bin

    # 3. Windows Default Locations
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            for alias in ("blender.exe", "blender-launcher.exe"):
                windows_app_alias = os.path.join(local_app_data, "Microsoft", "WindowsApps", alias)
                if os.path.isfile(windows_app_alias):
                    return windows_app_alias

        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates = sorted(
            glob.glob(os.path.join(program_files, "Blender Foundation", "Blender *", "blender.exe")),
            reverse=True,
        )
        if candidates:
            return candidates[0]

        # 3b. Windows Store AppX Package detection via PowerShell
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "(Get-AppxPackage *BlenderFoundation*).InstallLocation"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                for loc in res.stdout.strip().splitlines():
                    cand = os.path.join(loc.strip(), "Blender", "blender.exe")
                    if os.path.isfile(cand):
                        return cand
                    cand_direct = os.path.join(loc.strip(), "blender.exe")
                    if os.path.isfile(cand_direct):
                        return cand_direct
        except (subprocess.SubprocessError, OSError) as exc:
            logger.debug("PowerShell AppX query skipped: %s", exc)

    # 4. macOS Default Locations
    elif sys.platform == "darwin":
        mac_app = "/Applications/Blender.app/Contents/MacOS/Blender"
        if os.path.isfile(mac_app):
            return mac_app

    # 5. Linux Default Locations
    elif sys.platform.startswith("linux"):
        for loc in ("/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender"):
            if os.path.isfile(loc):
                return loc

    return None


def ensure_extension_zip(repo_root: str) -> str | None:
    """Ensure a fresh extension ZIP exists on the host matching the current manifest version."""
    configured_zip = os.environ.get("OMNIMESH_EXTENSION_ZIP")
    if configured_zip and os.path.isfile(configured_zip):
        return configured_zip

    build_script = os.path.join(repo_root, "scripts", "build_extension.py")
    if not os.path.isfile(build_script):
        return None

    try:
        try:
            from scripts.build_extension import build_package, get_version
        except ImportError:
            sys.path.insert(0, repo_root)
            from scripts.build_extension import build_package, get_version

        from pathlib import Path

        version = get_version(Path(repo_root))
        expected_zip = Path(repo_root) / "dist" / f"omnimesh-v{version}.zip"
        if not expected_zip.is_file():
            print(f"Extension package missing. Auto-building on host: {expected_zip.name}...")
            return str(build_package(Path(repo_root)))
        return str(expected_zip)
    except Exception as exc:
        logger.debug("Failed checking or building extension package: %s", exc)
        return None


def main() -> int:
    blender_bin = find_blender_binary()
    if not blender_bin:
        print(
            "ERROR: Could not locate Blender executable. Please set BLENDER_PATH environment variable.", file=sys.stderr
        )
        return 1

    print(f"Using Blender Binary: {blender_bin}")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    runner_script = os.path.join(repo_root, "tests", "in_blender", "runner.py")

    if not os.path.isfile(runner_script):
        print(f"ERROR: Runner script not found at {runner_script}", file=sys.stderr)
        return 1

    target_zip = ensure_extension_zip(repo_root)
    env = os.environ.copy()
    if target_zip:
        env["OMNIMESH_EXTENSION_ZIP"] = target_zip
        print(f"Using Extension ZIP: {target_zip}")

    cmd = [
        blender_bin,
        "-b",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        runner_script,
    ]

    print(f"Executing: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=repo_root, env=env)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
