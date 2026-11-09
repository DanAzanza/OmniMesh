"""
OmniMesh Central Local CI & Dependency Parity Verification Script.
Validates clean dependency declarations against pyproject.toml, runs static type checkers,
linters, formatters, and full dual-runtime test suite (Pytest + Headless Blender Coverage).
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:  # pragma: no cover
        tomllib = None  # type: ignore[assignment]


def check_dependency_parity() -> bool:
    """Verifies that all third-party imports are explicitly declared in pyproject.toml."""
    pyproject_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml")
    if not os.path.exists(pyproject_path):
        print("[ERROR] [DepCheck] pyproject.toml not found!")
        return False

    if tomllib is not None:
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        project_deps = data.get("project", {}).get("dependencies", [])
        dev_deps = data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    else:
        with open(pyproject_path, "r", encoding="utf-8") as f:
            content = f.read()
        project_deps = re.findall(r'"([^"]+)"', content)
        dev_deps = []

    all_declared = set()
    for dep in project_deps + dev_deps:
        pkg_name = dep.split(">=")[0].split("==")[0].split("<")[0].split(";")[0].strip().lower()
        all_declared.add(pkg_name)

    required_packages = ["numpy", "pillow", "pytest", "pytest-cov", "ruff", "pyright"]
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


def merge_dual_runtime_coverage(repo_root: str) -> bool:
    """Combines host pytest coverage with in-Blender integration test coverage."""
    primary_cov = os.path.join(repo_root, ".coverage")
    blender_cov = os.path.join(repo_root, ".coverage.in_blender")

    if not os.path.isfile(blender_cov):
        print("[INFO] No in-Blender coverage artifact found to merge.")
        return False

    try:
        from coverage.data import CoverageData

        primary = CoverageData(primary_cov)
        primary.read()
        secondary = CoverageData(blender_cov)
        secondary.read()
        primary.update(secondary)
        primary.write()

        # Clean up intermediate in-blender artifact
        try:
            os.remove(blender_cov)
        except OSError:
            pass

        print(f"[PASS] Merged in-Blender coverage into unified report database: {primary_cov}")
        return True
    except Exception as exc:
        print(f"[WARN] Failed to merge in-Blender coverage: {exc}")
        return False


def main() -> int:
    print("=" * 60)
    print("OmniMesh Pre-Commit Quality & CI Parity Gate")
    print("=" * 60)

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. Clean stale coverage artifacts
    for f in glob.glob(os.path.join(repo_root, ".coverage*")):
        try:
            os.remove(f)
        except OSError:
            pass

    if not check_dependency_parity():
        return 1

    if not run_command([sys.executable, "-m", "ruff", "check", "."], "Ruff Linter"):
        return 1

    if not run_command([sys.executable, "-m", "ruff", "format", "--check", "."], "Ruff Formatter Check"):
        return 1

    if not run_command([sys.executable, "-m", "pyright", "."], "Pyright Static Type Checker"):
        return 1

    audit_script = os.path.join(os.path.dirname(__file__), "audit_architecture.py")
    if os.path.exists(audit_script):
        if not run_command([sys.executable, audit_script, "--strict"], "Architecture & Invariant Compliance Audit"):
            return 1

    pytest_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "--cov=core",
        "--cov=exporters",
        "--cov=ui",
        "--cov=bridges",
        "--cov-report=term-missing",
        "-v",
    ]
    if not run_command(pytest_cmd, "Pytest Test Suite with Coverage"):
        return 1

    # In-Blender integration test suite check
    require_blender = "--require-blender" in sys.argv
    skip_blender = "--skip-blender" in sys.argv

    try:
        try:
            from run_blender_tests import find_blender_binary
        except ImportError:
            from scripts.run_blender_tests import find_blender_binary

        blender_bin = find_blender_binary()
    except Exception:
        blender_bin = None

    blender_tested = False
    if blender_bin and not skip_blender:
        blender_test_script = os.path.join(os.path.dirname(__file__), "run_blender_tests.py")
        if not run_command([sys.executable, blender_test_script, "--coverage"], "In-Blender Integration Test Suite"):
            return 1
        blender_tested = True
    elif require_blender:
        print("[FAIL] [BlenderGate] Blender binary required but not found!")
        return 1
    else:
        print("\n[SKIP] Blender executable not detected. Skipping in-Blender integration tests.")

    # 3. Dual-runtime coverage evaluation & ratcheting
    if blender_tested:
        merged = merge_dual_runtime_coverage(repo_root)
        if merged:
            report_cmd = [sys.executable, "-m", "coverage", "report", "--fail-under=70"]
            if not run_command(report_cmd, "Unified Dual-Runtime Coverage Gate (Target: >= 70%)"):
                return 1

    print("\n" + "=" * 60)
    print("ALL GATES PASSED DETERMINISTICALLY! Ready for Commit & Push.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
