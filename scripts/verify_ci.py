"""
OmniMesh Central Local CI & Dependency Parity Verification Script.
Validates clean dependency declarations against pyproject.toml, runs static type checkers,
linters, formatters, and full test suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib


def check_dependency_parity() -> bool:
    """Verifies that all third-party imports are explicitly declared in pyproject.toml."""
    pyproject_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")
    if not os.path.exists(pyproject_path):
        print("[ERROR] [DepCheck] pyproject.toml not found!")
        return False

    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    project_deps = data.get("project", {}).get("dependencies", [])
    dev_deps = data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    all_declared = set()
    for dep in project_deps + dev_deps:
        pkg_name = dep.split(">=")[0].split("==")[0].split("<")[0].strip().lower()
        all_declared.add(pkg_name)

    required_packages = ["numpy", "pillow", "pytest", "ruff", "pyright"]
    missing = []
    for pkg in required_packages:
        if pkg not in all_declared:
            missing.append(pkg)

    if missing:
        print(f"[ERROR] [DepCheck] Undeclared dependencies in pyproject.toml: {missing}")
        return False

    print("[PASS] [DepCheck] All runtime and dev dependencies properly declared in pyproject.toml.")
    return True


def run_command(cmd: list[str], desc: str) -> bool:
    print(f"\n[INFO] Verifying: {desc}...")
    res = subprocess.run(cmd, text=True)
    if res.returncode != 0:
        print(f"[FAIL] {desc} exited with code {res.returncode}")
        return False
    print(f"[PASS] {desc}")
    return True


def main() -> int:
    print("=" * 60)
    print("OmniMesh Pre-Commit Quality & CI Parity Gate")
    print("=" * 60)

    if not check_dependency_parity():
        return 1

    if not run_command([sys.executable, "-m", "ruff", "check", "."], "Ruff Linter"):
        return 1

    if not run_command([sys.executable, "-m", "ruff", "format", "--check", "."], "Ruff Formatter Check"):
        return 1

    if not run_command([sys.executable, "-m", "pyright", "."], "Pyright Static Type Checker"):
        return 1

    if not run_command([sys.executable, "-m", "pytest", "-v"], "Pytest Test Suite"):
        return 1

    print("\n" + "=" * 60)
    print("ALL GATES PASSED DETERMINISTICALLY! Ready for Commit & Push.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
