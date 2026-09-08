"""
QA Hardening Verification Tests.
Validates newly extracted modules, thread-safe texture pooling, shader tracing,
modular ui.properties package components, and LOD generation engine entrypoints.
"""

from __future__ import annotations


from core.lod_generator import generate_all_lods
from core.shader_tracer import ShaderTracer
from core.texture_pool import TexturePoolManager
from ui.lod_preset_ops import LOD_PRESET_OPERATOR_CLASSES
from ui.pbr_preset_ops import PBR_PRESET_OPERATOR_CLASSES
from ui.preset_ops import PRESET_OPERATOR_CLASSES
from ui.properties.guards import PresetSyncGuard, MapSyncGuard, ExportMapSyncGuard
from ui.properties.enums import (
    ASSET_CATEGORY_ITEMS,
    IMPOSTOR_MODE_ITEMS,
    PROGRESSION_MODE_ITEMS,
    TARGET_ENGINE_ITEMS,
)


def test_lod_generator_graceful_handling():
    """Verify generate_all_lods handles None/empty context and objects defensively."""
    success, msg = generate_all_lods(context=None, props=None, mesh_objs=[])
    assert success is True  # Blender context not available in headless test mock
    assert "not available" in msg.lower()


def test_texture_pool_lifecycle():
    """Verify TexturePoolManager singleton lifecycle and shutdown."""
    executor = TexturePoolManager.get_executor()
    assert executor is not None
    executor2 = TexturePoolManager.get_executor()
    assert executor is executor2

    # Shutdown clears executor
    TexturePoolManager.shutdown()
    assert TexturePoolManager._executor is None

    # Clean re-initialization
    new_exec = TexturePoolManager.get_executor()
    assert new_exec is not None
    TexturePoolManager.shutdown()


def test_shader_tracer_methods():
    """Verify ShaderTracer methods handle None/empty materials defensively."""
    assert ShaderTracer.get_material_normal_image(None) is None
    assert ShaderTracer.is_procedural_socket(None, "Base Color") is False
    assert ShaderTracer.trace_upstream_channel(None, "Base Color") == (None, 0, False, None)


def test_preset_operator_classes_integrity():
    """Verify preset operator tuples are populated and distinct."""
    assert len(PBR_PRESET_OPERATOR_CLASSES) >= 10
    assert len(LOD_PRESET_OPERATOR_CLASSES) >= 5
    assert len(PRESET_OPERATOR_CLASSES) == len(PBR_PRESET_OPERATOR_CLASSES) + len(LOD_PRESET_OPERATOR_CLASSES)


def test_ui_properties_enums():
    """Verify enum items in modularized ui.properties.enums."""
    assert len(ASSET_CATEGORY_ITEMS) >= 3
    assert len(IMPOSTOR_MODE_ITEMS) >= 3
    assert len(PROGRESSION_MODE_ITEMS) >= 2
    assert len(TARGET_ENGINE_ITEMS) >= 3


def test_sync_guards_reentrancy():
    """Verify that reentrancy guards lock and unlock cleanly."""
    assert PresetSyncGuard.is_locked() is False
    with PresetSyncGuard():
        assert PresetSyncGuard.is_locked() is True
    assert PresetSyncGuard.is_locked() is False

    assert MapSyncGuard.is_active() is False
    with MapSyncGuard():
        assert MapSyncGuard.is_active() is True
    assert MapSyncGuard.is_active() is False

    assert ExportMapSyncGuard.is_active() is False
    with ExportMapSyncGuard():
        assert ExportMapSyncGuard.is_active() is True
    assert ExportMapSyncGuard.is_active() is False


def test_batch_worker_script_exists():
    """Verify scripts/batch_worker.py exists and can be located."""
    import pathlib

    repo_root = pathlib.Path(__file__).parent.parent
    script_path = repo_root / "scripts" / "batch_worker.py"
    assert script_path.is_file(), f"scripts/batch_worker.py must exist, found at: {script_path}"
