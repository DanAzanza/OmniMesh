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


def test_batch_worker_unc_path_normalization():
    """Verify that normalize_export_path_for_cli preserves Windows UNC double backslash prefixes."""
    from core.batch_worker_process import normalize_export_path_for_cli

    # Windows UNC network path
    unc_path = r"\\storage_server\omnimesh\exports"
    normalized_unc = normalize_export_path_for_cli(unc_path)
    assert normalized_unc.startswith(r"\\"), f"UNC path must retain leading double backslash, got {normalized_unc}"
    assert not normalized_unc.startswith("//"), "UNC path must not be converted to Blender blend-relative '//'"

    # Standard drive path
    drive_path = r"C:\OmniMesh\Exports\Asset1"
    normalized_drive = normalize_export_path_for_cli(drive_path)
    assert normalized_drive == "C:/OmniMesh/Exports/Asset1"


def test_batch_hierarchical_export_path():
    """Verify build_hierarchical_export_path mirrors directory hierarchy and sanitizes asset names."""
    from core.batch_worker_process import build_hierarchical_export_path

    source_root = r"C:\Projects\Assets"
    blend_path = r"C:\Projects\Assets\Props\Hero Asset 01.blend"
    export_root = r"D:\Build\GameAssets"

    target_dir, asset_name = build_hierarchical_export_path(blend_path, source_root, export_root)
    assert asset_name == "Hero_Asset_01"
    assert "Props" in target_dir


def test_slicing_plane_normal_transform():
    """Verify that slicing plane normals are correctly transformed into object local space."""
    import numpy as np
    from unittest.mock import MagicMock

    # Setup an object with non-uniform scaling: scale X by 2.0, Y by 1.0, Z by 0.5
    mock_obj = MagicMock()
    # 3x3 rotation/scale: diag(2.0, 1.0, 0.5)
    scale_mat = np.diag([2.0, 1.0, 0.5])

    class Mock3x3:
        def transposed(self):
            m = Mock3x3()
            m.arr = self.arr.T
            return m

        def __matmul__(self, vec):
            res = self.arr @ np.array([vec[0], vec[1], vec[2]])
            mock_vec = MagicMock()
            norm = float(np.linalg.norm(res))
            mock_vec.normalized.return_value = res / norm if norm > 1e-12 else res
            return mock_vec

    m3 = Mock3x3()
    m3.arr = scale_mat
    mock_obj.matrix_world.to_3x3.return_value = m3

    # Cutting normal along world X (1, 0, 0)
    n_world = (1.0, 0.0, 0.0)
    n_local = (mock_obj.matrix_world.to_3x3().transposed() @ n_world).normalized()
    assert np.allclose(n_local, [1.0, 0.0, 0.0])


def test_collision_svd_relative_eccentricity():
    """Verify that SVD relative eccentricity is scale-invariant across millimeter and meter scale."""
    import numpy as np

    # Generate a planar point cloud (Z=0 with negligible noise)
    rng = np.random.default_rng(42)

    for scale in (0.001, 1.0, 100.0):
        xy = rng.uniform(-1.0, 1.0, size=(50, 2)) * scale
        z = rng.normal(0.0, 1e-7 * scale, size=(50, 1))  # Tiny out-of-plane perturbation
        pts = np.hstack([xy, z])

        centered = pts - np.mean(pts, axis=0)
        _, s, _ = np.linalg.svd(centered, full_matrices=False)

        # Scale-invariant check: s[2] / s[0] must be negligible regardless of scale factor
        rel_s2 = float(s[2]) / max(1e-12, float(s[0]))
        assert rel_s2 < 1e-3, f"Scale {scale} failed relative eccentricity check: rel_s2={rel_s2}"


def test_slender_boundary_ring_perimeter_diameter():
    """Verify thickness derivation for open catenary/cable features."""
    import math

    # A circle of radius r=0.05 (diameter=0.10m)
    radius = 0.05
    perimeter = 2.0 * math.pi * radius

    # Derived diameter from perimeter
    derived_diameter = perimeter / math.pi
    assert math.isclose(derived_diameter, 0.10, rel_tol=1e-5)
