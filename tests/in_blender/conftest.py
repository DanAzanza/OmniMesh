"""
Pytest collection hooks for in-blender test suite.
"""

from __future__ import annotations

import sys


def pytest_ignore_collect(collection_path, config):
    """Ignore in-blender tests if bpy is not available in host Python environment."""
    if "bpy" not in sys.modules:
        try:
            import bpy  # noqa: F401
        except ImportError:
            return True
    return False
