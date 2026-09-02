"""
Cross-Platform CLI Runner for OmniMesh In-Engine Integration Tests.
Executes headless Blender with factory startup and streams results.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys


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
        except Exception:
            pass

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


def main() -> int:
    blender_bin = find_blender_binary()
    if not blender_bin:
        print(
            "ERROR: Could not locate Blender executable. Please set BLENDER_PATH environment variable.", file=sys.stderr
        )
        return 1

    print(f"Using Blender Binary: {blender_bin}")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    runner_script = os.path.join(repo_root, "tests", "in_engine", "runner.py")

    if not os.path.isfile(runner_script):
        print(f"ERROR: Runner script not found at {runner_script}", file=sys.stderr)
        return 1

    cmd = [
        blender_bin,
        "-b",
        "--factory-startup",
        "--python",
        runner_script,
    ]

    print(f"Executing: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=repo_root)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
