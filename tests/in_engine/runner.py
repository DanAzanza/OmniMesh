"""
Dual-Engine In-Engine Test Runner for OmniMesh (Blender MCP & Headless CLI).
"""

from __future__ import annotations

import importlib
import io
import logging
import os
import sys
import time
import unittest
from typing import Any

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
        logger.info("Registered fresh OmniMesh add-on for in-engine testing.")
    except Exception as exc:
        logger.error("Failed to register OmniMesh add-on: %s", exc)


def run_all_in_engine_tests() -> dict[str, Any]:
    """Execute all in-engine integration test suites.

    Safe for interactive MCP sessions (does NOT call sys.exit).
    Returns a JSON-serializable dictionary of test results.
    """
    bootstrap_addon()

    from tests.in_engine.test_cleanup_pipeline import TestCleanupPipeline
    from tests.in_engine.test_export_pipeline import TestExportPipeline
    from tests.in_engine.test_lod_generation_pipeline import TestLODGenerationPipeline
    from tests.in_engine.test_simulator_pipeline import TestSimulatorPipeline

    suite = unittest.TestSuite()
    loader = unittest.TestLoader()

    suite.addTests(loader.loadTestsFromTestCase(TestCleanupPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestLODGenerationPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestSimulatorPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestExportPipeline))

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
    result = run_all_in_engine_tests()
    print(
        f"\nIn-Engine Suite Completed in {result['duration_sec']}s: "
        f"{result['tests_run']} tests run, {result['failures_count']} failures, {result['errors_count']} errors."
    )

    # Only exit if running in headless CLI mode; keep Blender GUI open during interactive sessions
    if bpy and getattr(bpy.app, "background", False):
        sys.exit(0 if result["success"] else 1)
