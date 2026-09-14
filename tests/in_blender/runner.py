"""
Dual-Mode In-Blender Test Runner for OmniMesh (Blender MCP & Headless CLI).
"""

from __future__ import annotations

import importlib
import io
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from typing import Any
import zipfile

logger = logging.getLogger(__name__)

# 1. Bootstrap Repository Root to sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    import bpy
except ImportError:
    bpy = None


def bootstrap_addon() -> None:
    """Ensure OmniMesh add-on properties and operators are freshly registered in live/headless sessions."""
    if not bpy:
        return

    import __init__ as omnimesh

    try:
        omnimesh.unregister()
    except Exception as exc:
        logger.debug("Safe unregister skipped: %s", exc)

    # Reload modules in dependency order to reflect disk changes
    for attr in (
        "metrics",
        "sanitizer",
        "occlusion",
        "collision",
        "impostor",
        "decimator",
        "materials",
        "pbr_importer",
        "pivot",
        "slender",
        "normals",
        "hierarchy",
        "rigging",
        "textures",
        "animations",
        "batch",
        "bridges",
        "simulator",
        "properties",
        "lists",
        "utils",
        "cleanup_ops",
        "hull_impostor_ops",
        "lod_ops",
        "pbr_ops",
        "operators",
        "panel",
        "simulator_ops",
        "batch_panel",
        "split_preview",
        "hud",
        "msfs_export",
        "ue5_export",
        "unity_export",
        "godot_export",
        "engine_export",
    ):
        mod = getattr(omnimesh, attr, None)
        if mod:
            try:
                importlib.reload(mod)
            except Exception as exc:
                logger.debug("Module %s reload skipped: %s", attr, exc)

    try:
        omnimesh.register()
        logger.info("Registered fresh OmniMesh add-on for in-blender testing.")
    except Exception as exc:
        logger.error("Failed to register OmniMesh add-on: %s", exc)


def run_extension_installation_smoke_test() -> None:
    """Install the built ZIP into Blender's extension namespace and register it."""
    if not bpy:
        raise RuntimeError("Blender bpy runtime is required for the extension smoke test.")

    repo_root = Path(REPO_ROOT)
    configured_zip = os.environ.get("OMNIMESH_EXTENSION_ZIP")
    if configured_zip:
        zip_path = Path(configured_zip)
    else:
        candidates = sorted((repo_root / "dist").glob("omnimesh-v*.zip"))
        zip_path = candidates[-1] if candidates else Path()
    if not zip_path.is_file():
        raise FileNotFoundError(
            "Built extension ZIP not found. Run scripts/build_extension.py or set OMNIMESH_EXTENSION_ZIP."
        )

    module_name = "bl_ext.user_default.omnimesh"
    with tempfile.TemporaryDirectory(prefix="omnimesh-extension-") as temp_dir:
        install_dir = Path(temp_dir) / "extensions" / "user_default" / "omnimesh"
        install_dir.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(install_dir)

        if not (install_dir / "blender_manifest.toml").is_file():
            raise AssertionError("Installed extension is missing blender_manifest.toml.")

        previous_path = list(sys.path)
        sys.path.insert(0, temp_dir)
        module = None
        try:
            spec = importlib.util.spec_from_file_location(
                module_name,
                install_dir / "__init__.py",
                submodule_search_locations=[str(install_dir)],
            )
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create import specification for {module_name}.")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            module.register()
            logger.info("Installed extension smoke test passed for %s.", zip_path.name)
        finally:
            if module is not None:
                try:
                    module.unregister()
                except Exception as exc:
                    logger.debug("Extension smoke-test unregister skipped: %s", exc)
            for loaded_name in list(sys.modules):
                if loaded_name == module_name or loaded_name.startswith(f"{module_name}."):
                    del sys.modules[loaded_name]
            sys.path[:] = previous_path


def run_all_in_blender_tests() -> dict[str, Any]:
    """Execute all in-blender integration test suites.

    Safe for interactive MCP sessions (does NOT call sys.exit).
    Returns a JSON-serializable dictionary of test results.
    """
    run_extension_installation_smoke_test()
    bootstrap_addon()

    from tests.in_blender.test_cleanup_pipeline import TestCleanupPipeline
    from tests.in_blender.test_collision_pipeline import TestCollisionPipeline
    from tests.in_blender.test_decimator_pipeline import TestDecimatorPipeline
    from tests.in_blender.test_export_pipeline import TestExportPipeline
    from tests.in_blender.test_impostor_pipeline import TestImpostorPipeline
    from tests.in_blender.test_lod_generation_pipeline import TestLODGenerationPipeline
    from tests.in_blender.test_material_pipeline import TestMaterialPipeline
    from tests.in_blender.test_normals_pipeline import TestNormalsPipeline
    from tests.in_blender.test_pbr_pipeline import TestPBRPipeline
    from tests.in_blender.test_pivot_pipeline import TestPivotPipeline
    from tests.in_blender.test_simulator_pipeline import TestSimulatorPipeline

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    suite.addTests(loader.loadTestsFromTestCase(TestCleanupPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestCollisionPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestDecimatorPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestExportPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestImpostorPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestLODGenerationPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestMaterialPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestNormalsPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestPBRPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestPivotPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestSimulatorPipeline))

    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)

    start_time = time.time()
    test_result = runner.run(suite)
    duration = time.time() - start_time

    output_text = stream.getvalue()
    print(output_text)

    failures_list = []
    for test_case, err_trace in test_result.failures:
        failures_list.append({"test": str(test_case), "error": err_trace})

    errors_list = []
    for test_case, err_trace in test_result.errors:
        errors_list.append({"test": str(test_case), "error": err_trace})

    summary = {
        "success": test_result.wasSuccessful(),
        "tests_run": test_result.testsRun,
        "failures_count": len(test_result.failures),
        "errors_count": len(test_result.errors),
        "skipped_count": len(test_result.skipped),
        "duration_sec": round(duration, 3),
        "failures": failures_list,
        "errors": errors_list,
    }

    return summary


if __name__ == "__main__":
    result = run_all_in_blender_tests()
    print(
        f"\nIn-Blender Suite Completed in {result['duration_sec']}s: "
        f"{result['tests_run']} tests run, {result['failures_count']} failures, {result['errors_count']} errors."
    )

    # Only exit if running in headless CLI mode; keep Blender GUI open during interactive sessions
    if bpy and getattr(bpy.app, "background", False):
        sys.exit(0 if result["success"] else 1)
