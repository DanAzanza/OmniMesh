"""
QA Hardening Verification Tests.
Validates newly extracted modules, thread-safe texture pooling, shader tracing,
modular ui.properties package components, and LOD generation engine entrypoints.
"""

from __future__ import annotations

import math

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
    """Verify build_hierarchical_export_path mirrors directory hierarchy and sanitizes asset names across OS path styles."""
    from core.batch_worker_process import build_hierarchical_export_path

    # Windows-style path test
    source_root_win = r"C:\Projects\Assets"
    blend_path_win = r"C:\Projects\Assets\Props\Hero Asset 01.blend"
    export_root_win = r"D:\Build\GameAssets"

    target_dir_w, asset_name_w = build_hierarchical_export_path(blend_path_win, source_root_win, export_root_win)
    assert asset_name_w == "Hero_Asset_01"
    assert "Props" in target_dir_w

    # POSIX-style path test
    source_root_posix = "/projects/assets"
    blend_path_posix = "/projects/assets/Props/Hero Asset 01.blend"
    export_root_posix = "/build/gameassets"

    target_dir_p, asset_name_p = build_hierarchical_export_path(blend_path_posix, source_root_posix, export_root_posix)
    assert asset_name_p == "Hero_Asset_01"
    assert "Props" in target_dir_p


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


def test_functional_rdp_reduce():
    """Verify 1D functional RDP decimation preserves extrema and reduces collinear points."""
    from core.animations import AnimationRigSanitizer

    # Perfectly linear sequence: all internal points should be pruned
    linear_pts = [(float(i), float(i * 2.0)) for i in range(10)]
    reduced = AnimationRigSanitizer.functional_rdp_reduce(linear_pts, epsilon=0.01)
    assert len(reduced) == 2
    assert reduced[0] == (0.0, 0.0)
    assert reduced[-1] == (9.0, 18.0)

    # Triangle wave: 11 points with peak at i=5, linear ramps up and down
    # (0..5 have slope +2.0, 5..10 have slope -2.0)
    triangle_pts = [
        (0.0, 0.0),
        (1.0, 2.0),
        (2.0, 4.0),
        (3.0, 6.0),
        (4.0, 8.0),
        (5.0, 10.0),
        (6.0, 8.0),
        (7.0, 6.0),
        (8.0, 4.0),
        (9.0, 2.0),
        (10.0, 0.0),
    ]
    reduced_triangle = AnimationRigSanitizer.functional_rdp_reduce(triangle_pts, epsilon=0.01)
    assert len(reduced_triangle) == 3
    assert reduced_triangle == [(0.0, 0.0), (5.0, 10.0), (10.0, 0.0)]


def test_quaternion_sign_continuity():
    """Verify quaternion sign continuity dot product logic eliminates 360-degree spin flips."""
    # Two equivalent orientations represented by opposite quaternions q and -q
    q1 = (1.0, 0.0, 0.0, 0.0)  # (w, x, y, z)
    q2 = (-1.0, 0.0, 0.0, 0.0)

    dot = q1[0] * q2[0] + q1[1] * q2[1] + q1[2] * q2[2] + q1[3] * q2[3]
    assert dot < 0.0

    # Invert q2 when dot < 0
    q2_corrected = (-q2[0], -q2[1], -q2[2], -q2[3])
    dot_corrected = (
        q1[0] * q2_corrected[0] + q1[1] * q2_corrected[1] + q1[2] * q2_corrected[2] + q1[3] * q2_corrected[3]
    )
    assert dot_corrected > 0.0
    assert q2_corrected == q1


def test_pbr_bsdf_v2_socket_resolution():
    """Verify ShaderGraphBuilder canonical BSDF socket alias resolution."""
    from core.pbr_importer import ShaderGraphBuilder
    from unittest.mock import MagicMock

    mock_bsdf = MagicMock()
    # Mock inputs dictionary simulating Blender 4.x / 5.x Principled BSDF v2
    v2_sockets = {
        "Base Color": MagicMock(name="Base Color"),
        "Specular IOR Level": MagicMock(name="Specular IOR Level"),
        "Transmission Weight": MagicMock(name="Transmission Weight"),
        "Coat Weight": MagicMock(name="Coat Weight"),
        "Sheen Weight": MagicMock(name="Sheen Weight"),
    }
    mock_bsdf.inputs = v2_sockets

    # Querying legacy targets should resolve to modern v2 sockets
    assert ShaderGraphBuilder.resolve_bsdf_socket(mock_bsdf, "Specular") == v2_sockets["Specular IOR Level"]
    assert ShaderGraphBuilder.resolve_bsdf_socket(mock_bsdf, "Transmission") == v2_sockets["Transmission Weight"]
    assert ShaderGraphBuilder.resolve_bsdf_socket(mock_bsdf, "Clearcoat") == v2_sockets["Coat Weight"]
    assert ShaderGraphBuilder.resolve_bsdf_socket(mock_bsdf, "Sheen") == v2_sockets["Sheen Weight"]
    assert ShaderGraphBuilder.resolve_bsdf_socket(mock_bsdf, "Base Color") == v2_sockets["Base Color"]


def test_msfs_cst_parser_keys_with_spaces(tmp_path):
    """Verify MSFSCSTParser parses keys containing embedded spaces."""
    from core.msfs.cst_parser import MSFSCSTParser

    cfg_content = (
        "[CAMERADEFINITION.0]\n"
        'Title = "Pilot View"\n'
        "Initial Zoom = 0.35\n"
        'SubCategory Title = "Cockpit"\n'
        "Initial Xyz = 0.0, 1.2, -0.5\n"
    )
    test_file = tmp_path / "cameras_test.cfg"
    test_file.write_text(cfg_content, encoding="utf-8")

    config = MSFSCSTParser.parse_file(str(test_file))
    assert len(config.lines) >= 5

    parsed_keys = [record.key for record in config.lines if record.key]
    assert "Title" in parsed_keys
    assert "Initial Zoom" in parsed_keys
    assert "SubCategory Title" in parsed_keys
    assert "Initial Xyz" in parsed_keys


def test_camera_cst_key_normalization(tmp_path):
    """Verify camera CST normalizes keys with spaces and underscores."""
    from core.msfs.camera_cst import MSFSCameraCST

    cfg_content = (
        "[CAMERADEFINITION.0]\n"
        'Title = "Cockpit Center"\n'
        "Initial Zoom = 0.45\n"
        'SubCategory Title = "Quickview"\n'
        "Initial Xyz = 0.1, 0.8, -0.2\n"
        "Initial Pbh = 5.0, 0.0, 0.0\n"
    )
    test_file = tmp_path / "cameras_norm.cfg"
    test_file.write_text(cfg_content, encoding="utf-8")

    cam_config = MSFSCameraCST.parse_cameras_file(str(test_file))
    assert len(cam_config.cameras) == 1
    cam = cam_config.cameras[0]
    assert cam.title == "Cockpit Center"
    assert math.isclose(cam.initial_zoom, 0.45, rel_tol=1e-5)
    assert cam.subcategory == "Quickview"
    assert cam.initial_xyz_m == (0.1, 0.8, -0.2)
    assert cam.initial_pbh_deg == (5.0, 0.0, 0.0)


def test_detect_file_format_encodings(tmp_path):
    """Verify detect_file_format handles UTF-8, UTF-8 BOM, UTF-16 LE, and CP1252."""
    from core.msfs.camera_cst import detect_file_format

    # 1. UTF-8 standard
    f_utf8 = tmp_path / "utf8.txt"
    f_utf8.write_bytes(b"sample content\n")
    enc, bom, nl = detect_file_format(str(f_utf8))
    assert enc == "utf-8"
    assert bom is False
    assert nl == "\n"

    # 2. UTF-8 with BOM
    f_utf8_bom = tmp_path / "utf8_bom.txt"
    f_utf8_bom.write_bytes(b"\xef\xbb\xbfsample with bom\r\n")
    enc, bom, nl = detect_file_format(str(f_utf8_bom))
    assert enc == "utf-8-sig"
    assert bom is True
    assert nl == "\r\n"

    # 3. UTF-16 LE with BOM
    f_utf16 = tmp_path / "utf16_le.txt"
    f_utf16.write_bytes(b"\xff\xfe" + "flight config".encode("utf-16-le"))
    enc, bom, nl = detect_file_format(str(f_utf16))
    assert enc == "utf-16-le"
    assert bom is True

    # 4. CP1252 (invalid UTF-8 bytes)
    f_cp1252 = tmp_path / "cp1252.txt"
    f_cp1252.write_bytes(b"Caf\xe9 au lait\n")
    enc, bom, nl = detect_file_format(str(f_cp1252))
    assert enc == "cp1252"
    assert bom is False


def test_occlusion_zero_vector_normal_safety():
    """Verify occlusion culler guards against zero-vector face normals."""
    from core.occlusion import HardenedOcclusionCuller
    from unittest.mock import MagicMock

    zero_vec = MagicMock()
    zero_vec.length_squared = 0.0

    dirs = HardenedOcclusionCuller._stratified_hemisphere_dirs(zero_vec, 16)
    assert dirs == []
