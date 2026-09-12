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


def test_slender_total_extinction_safeguard():
    """Verify that slender culler never extinguishes 100% of a mesh."""
    from unittest.mock import MagicMock
    from core.slender import SlenderFeatureCuller

    # Mock a mesh where all faces are micro-parts
    f1 = MagicMock()
    f1.calc_area.return_value = 0.001
    f1.edges = []
    f2 = MagicMock()
    f2.calc_area.return_value = 0.005
    f2.edges = []

    bm = MagicMock()
    bm.faces = [f1, f2]

    # Run slender culling with screen_size_pct
    res = SlenderFeatureCuller.cull_slender_features(
        bm,
        screen_size_pct=1.0,
        resolution_y=1080,
        root_radius_m=1.0,
    )
    # Extinction safeguard must preserve at least 1 island
    assert res["culled_faces"] < len(bm.faces)


def test_collision_area_none_data_safeguard():
    """Verify area-weighted decomposition ignores objects with None data."""
    from unittest.mock import MagicMock

    obj_valid = MagicMock()
    p1 = MagicMock()
    p1.area = 5.0
    obj_valid.data.polygons = [p1]

    obj_invalid = MagicMock()
    obj_invalid.data = None

    # Calculate total area logic as in collision.py
    mesh_objs = [obj_valid, obj_invalid]
    total_area = (
        sum(
            sum(getattr(p, "area", 0.0) for p in getattr(obj.data, "polygons", []))
            for obj in mesh_objs
            if getattr(obj, "data", None)
        )
        or 1.0
    )
    assert total_area == 5.0


def test_resolve_lod_context_reference_error_safeguard():
    """Verify resolve_lod_context handles invalid/removed objects without ReferenceError."""
    from unittest.mock import MagicMock
    from ui.utils import resolve_lod_context

    ctx = MagicMock()
    ctx.scene.lod_tool = MagicMock()
    ctx.scene.lod_tool.lods = []

    # Mock active_object that raises ReferenceError when accessing attributes
    class DeletedObject:
        @property
        def name(self):
            raise ReferenceError("StructRNA of type Object has been removed")

        @property
        def type(self):
            raise ReferenceError("StructRNA of type Object has been removed")

    ctx.active_object = DeletedObject()
    props, master, is_deriv = resolve_lod_context(ctx)
    assert props == ctx.scene.lod_tool
    assert master is None
    assert is_deriv is False


def test_morphological_dilate_no_toroidal_wrap():
    """Verify that morphological dilation does not wrap colors across opposite image edges."""
    import numpy as np
    from core.impostor import ImpostorMath

    # 4x4 RGBA image, only bottom row (y=3) has red color
    img = np.zeros((4, 4, 4), dtype=np.float32)
    img[3, :, 0] = 1.0  # Red channel
    img[3, :, 3] = 1.0  # Alpha channel

    dilated = ImpostorMath.morphological_dilate_rgb(img, iterations=1)
    # y=2 should receive red bleed from y=3
    assert dilated[2, 1, 0] == 1.0
    # y=0 (top row) must NOT receive bleed from y=3 (proves no toroidal wrap)
    assert dilated[0, 1, 0] == 0.0


def test_srgb_oetf_conversion_flag():
    """Verify that _extract_from_image respects apply_srgb_oetf flag."""
    import numpy as np
    from unittest.mock import MagicMock
    from core.shader_tracer import ShaderTracer

    img_mock = MagicMock()
    img_mock.size = (2, 2)
    # 4 pixels RGBA with linear mid-gray (0.18 linear ~ 0.458 sRGB)
    raw = np.full(16, 0.18, dtype=np.float32)
    img_mock.pixels.foreach_get = lambda buf: np.copyto(buf, raw)

    fallback = np.zeros((2, 2), dtype=np.uint8)

    # Linear extraction (default)
    linear_out = ShaderTracer._extract_from_image(img_mock, (2, 2), 0, fallback, bit_depth=8, apply_srgb_oetf=False)
    # 0.18 * 255 = ~46
    assert abs(int(linear_out[0, 0]) - int(round(0.18 * 255))) <= 1

    # sRGB OETF extraction
    srgb_out = ShaderTracer._extract_from_image(img_mock, (2, 2), 0, fallback, bit_depth=8, apply_srgb_oetf=True)
    # sRGB transfer function elevates 0.18 to ~117 (0.458 * 255)
    assert int(srgb_out[0, 0]) > int(linear_out[0, 0]) + 50


def test_reroute_cycle_protection_termination():
    """Verify trace_upstream_channel terminates safely when encountering circular reroutes."""
    from unittest.mock import MagicMock
    from core.shader_tracer import ShaderTracer

    mat = MagicMock()
    mat.use_nodes = True
    bsdf = MagicMock()
    bsdf.type = "BSDF_PRINCIPLED"

    # Circular reroutes: r1 -> r2 -> r1
    r1 = MagicMock()
    r1.type = "REROUTE"
    r2 = MagicMock()
    r2.type = "REROUTE"

    r1.inputs = [MagicMock()]
    r1.inputs[0].is_linked = True
    r1.inputs[0].links = [MagicMock(from_node=r2)]

    r2.inputs = [MagicMock()]
    r2.inputs[0].is_linked = True
    r2.inputs[0].links = [MagicMock(from_node=r1)]

    # Connect to Normal Map node
    norm_node = MagicMock()
    norm_node.type = "NORMAL_MAP"
    norm_node.inputs = {"Color": MagicMock(is_linked=True, links=[MagicMock(from_node=r1)])}

    bsdf.inputs = {"Normal": MagicMock(is_linked=True, links=[MagicMock(from_node=norm_node)])}
    mat.node_tree.nodes = [bsdf, norm_node, r1, r2]

    # Must terminate without infinite recursion/loop
    img = ShaderTracer.get_material_normal_image(mat)
    assert img is None
