"""Deep unit and boundary tests for core.sanitizer and core.lod_generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING as _TC, Any, Any as _Any
from unittest.mock import MagicMock, patch

if _TC:
    _MockBase: type[_Any] = object
else:
    _MockBase = object

import core.lod_generator as lg_mod
import core.sanitizer as san_mod
from core.lod_generator import (
    _compute_lod0_stats,
    _count_triangles,
    generate_all_lods,
)
from core.sanitizer import MeshSanitizer, SanitizeOptions


@dataclass
class FakeVec:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    length: float = 1.0
    length_squared: float = 1.0

    def __getitem__(self, idx: int) -> float:
        return (self.x, self.y, self.z)[idx]

    def __sub__(self, other: FakeVec) -> FakeVec:
        dx, dy, dz = self.x - other.x, self.y - other.y, self.z - other.z
        sq = dx * dx + dy * dy + dz * dz
        return FakeVec(dx, dy, dz, length=sq**0.5, length_squared=sq)

    def dot(self, other: FakeVec) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z

    def normalized(self) -> FakeVec:
        return self


class FakeVert:
    def __init__(self, idx: int, co: FakeVec | None = None, is_wire: bool = False) -> None:
        self.index = idx
        self.co = co or FakeVec(float(idx), 0.0, 0.0)
        self.is_valid = True
        self.is_wire = is_wire
        self.is_boundary = False
        self.link_faces: list[Any] = []
        self.link_edges: list[Any] = []


class FakeLoop:
    def __init__(self, vert: FakeVert, uv: tuple[float, float] = (0.0, 0.0)) -> None:
        self.vert = vert
        self.edge: Any = None
        self.link_loop_next: Any = None
        self._uv = MagicMock()
        self._uv.uv = FakeVec(uv[0], uv[1], 0.0)

    def __getitem__(self, layer: Any) -> Any:
        return self._uv


class FakeEdge:
    def __init__(
        self,
        v1: FakeVert,
        v2: FakeVert,
        length: float = 1.0,
        is_wire: bool = False,
        is_boundary: bool = False,
        is_manifold: bool = True,
        is_contiguous: bool = True,
        seam: bool = False,
    ) -> None:
        self.verts = [v1, v2]
        self.is_valid = True
        self.is_wire = is_wire
        self.is_boundary = is_boundary
        self.is_manifold = is_manifold
        self.is_contiguous = is_contiguous
        self.seam = seam
        self.link_faces: list[Any] = []
        self._len = length
        if not is_wire:
            v1.link_edges.append(self)
            v2.link_edges.append(self)

    def calc_length(self) -> float:
        return self._len


class FakeFace:
    def __init__(
        self,
        idx: int,
        verts: list[FakeVert],
        area: float = 1.0,
        material_index: int = 0,
        normal: FakeVec | None = None,
    ) -> None:
        self.index = idx
        self.verts = verts
        self.edges: list[FakeEdge] = []
        self.loops = [FakeLoop(v) for v in verts]
        for i, lp in enumerate(self.loops):
            lp.link_loop_next = self.loops[(i + 1) % len(self.loops)]
        self.is_valid = True
        self.material_index = material_index
        self.normal = normal or FakeVec(0.0, 0.0, 1.0, length=1.0, length_squared=1.0)
        self._area = area
        for v in verts:
            v.link_faces.append(self)

    def calc_area(self) -> float:
        return self._area

    def calc_perimeter(self) -> float:
        return 4.0

    def normal_flip(self) -> None:
        self.normal = FakeVec(-self.normal.x, -self.normal.y, -self.normal.z)


class FakeElemSeq(list[Any]):
    def __init__(self, items: list[Any] | None = None) -> None:
        super().__init__(items or [])
        self.layers = MagicMock()
        self.layers.uv.values.return_value = ["uv_layer_0"]

    def ensure_lookup_table(self) -> None:
        for i, item in enumerate(self):
            item.index = i

    def index_update(self) -> None:
        self.ensure_lookup_table()


class FakeBMesh(_MockBase):
    def __init__(
        self,
        verts: list[FakeVert] | None = None,
        edges: list[FakeEdge] | None = None,
        faces: list[FakeFace] | None = None,
    ) -> None:
        self.verts = FakeElemSeq(verts)
        self.edges = FakeElemSeq(edges)
        self.faces = FakeElemSeq(faces)
        self.loops = FakeElemSeq()
        self.freed = False

    def normal_update(self) -> None:
        pass

    def from_mesh(self, mesh: Any) -> None:
        pass

    def to_mesh(self, mesh: Any) -> None:
        pass

    def free(self) -> None:
        self.freed = True


# =========================================================================
# 1. MeshSanitizer Deep Tests
# =========================================================================


def test_sanitizer_null_and_empty_bmesh_guards() -> None:
    """Verify MeshSanitizer methods return safe defaults when bmesh is None or empty."""
    with patch.object(san_mod, "bmesh", None):
        assert MeshSanitizer._purge_duplicate_faces(None) == 0
        assert MeshSanitizer.execute_tier0_pure_hygiene(None) == {
            "zero_faces": 0,
            "zero_edges": 0,
            "wire_edges": 0,
            "loose_verts": 0,
            "duplicate_faces": 0,
        }
        assert MeshSanitizer.merge_doubles_boundary_safe(None) == 0
        assert MeshSanitizer.execute_tier2_pipeline_guards(None) == {"recalculated_normals": False}
        assert MeshSanitizer.sanitize_mesh_full(None) == {}


def test_purge_duplicate_faces_and_tier0_hygiene() -> None:
    """Verify duplicate face removal, zero-area face removal, zero-length edge collapse, and wire cleanup."""
    v0, v1, v2 = FakeVert(0), FakeVert(1), FakeVert(2)
    v_wire = FakeVert(3, is_wire=True)
    f1 = FakeFace(0, [v0, v1, v2], area=1.0)
    f_dup = FakeFace(1, [v2, v1, v0], area=1.0)  # Duplicate vertex set & same normal
    f_opp = FakeFace(2, [v0, v1, v2], area=1.0, normal=FakeVec(0.0, 0.0, -1.0))  # Double-sided card (preserved)
    f_zero = FakeFace(3, [v0, v1, v_wire], area=1e-14)
    e_zero = FakeEdge(v0, v1, length=1e-10, is_wire=True)
    e_zero.link_faces = [f1]
    e_wire = FakeEdge(v1, v2, length=1.0, is_wire=True)
    bm = FakeBMesh(
        verts=[v0, v1, v2, v_wire],
        edges=[e_zero, e_wire],
        faces=[f1, f_dup, f_opp, f_zero],
    )

    fake_bmesh_mod = MagicMock()

    def _delete(bm_obj: FakeBMesh, geom: list[Any], context: str) -> None:
        for item in list(geom):
            if item in bm_obj.faces:
                bm_obj.faces.remove(item)
            if item in bm_obj.edges:
                bm_obj.edges.remove(item)
            if item in bm_obj.verts:
                bm_obj.verts.remove(item)

    def _collapse(bm_obj: FakeBMesh, edges: list[Any]) -> None:
        for e in list(edges):
            if e in bm_obj.edges:
                bm_obj.edges.remove(e)

    fake_bmesh_mod.ops.delete.side_effect = _delete
    fake_bmesh_mod.ops.collapse.side_effect = _collapse
    with patch.object(san_mod, "bmesh", fake_bmesh_mod):
        res = MeshSanitizer.execute_tier0_pure_hygiene(bm)
        assert res["duplicate_faces"] == 1
        assert res["zero_faces"] == 1
        assert res["zero_edges"] == 1
        assert res["wire_edges"] == 1
        assert res["loose_verts"] == 4
        assert f_opp in bm.faces


def test_merge_doubles_and_tier2_normal_guards() -> None:
    """Verify merge_doubles_boundary_safe and execute_tier2_pipeline_guards (MANIFOLD_ONLY vs FORCE_ALL vs OFF)."""
    v0 = FakeVert(0, FakeVec(0.0, 0.0, 0.0))
    v1 = FakeVert(1, FakeVec(0.0, 0.0, 0.0))
    v2 = FakeVert(2, FakeVec(1.0, 0.0, 0.0))
    e0 = FakeEdge(v0, v1)
    f0 = FakeFace(0, [v0, v1, v2], area=1.0)
    f1 = FakeFace(1, [v0, v2, v1], area=1.0)
    # Closed 2-manifold shell: every edge has exactly 2 linked faces
    e0.link_faces = [f0, f1]
    f0.edges = [e0]
    f1.edges = [e0]
    bm = FakeBMesh(verts=[v0, v1, v2], edges=[e0], faces=[f0, f1])

    fake_bmesh_mod = MagicMock()

    def _rem_doubles(bm_obj: FakeBMesh, verts: list[Any], dist: float) -> None:
        bm_obj.verts.pop()

    fake_bmesh_mod.ops.remove_doubles.side_effect = _rem_doubles
    with patch.object(san_mod, "bmesh", fake_bmesh_mod):
        merged = MeshSanitizer.merge_doubles_boundary_safe(bm, dist=0.001)
        assert merged == 1

        # MANIFOLD_ONLY on closed 2-manifold shell
        t2_manifold = MeshSanitizer.execute_tier2_pipeline_guards(bm, normal_recalc_policy="MANIFOLD_ONLY")
        assert t2_manifold["recalculated_normals"] is True
        assert t2_manifold["manifold_faces_aligned"] == 2

        # FORCE_ALL
        t2_force = MeshSanitizer.execute_tier2_pipeline_guards(bm, normal_recalc_policy="FORCE_ALL")
        assert t2_force["recalculated_normals"] is True
        assert t2_force["forced_all_aligned"] == 2

        # OFF
        t2_off = MeshSanitizer.execute_tier2_pipeline_guards(bm, normal_recalc_policy="OFF")
        assert t2_off["recalculated_normals"] is False


def test_run_preflight_inspection_and_sanitize_mesh_full() -> None:
    """Verify run_preflight_inspection (clean and dirty meshes) and sanitize_mesh_full."""
    v0, v1, v2 = FakeVert(0), FakeVert(1), FakeVert(2)
    v_loose = FakeVert(3, is_wire=True)
    e_wire = FakeEdge(v0, v1, is_wire=True)
    e_nm = FakeEdge(v1, v2)
    f_degen = FakeFace(0, [v0, v1, v2], area=1e-12)
    f_ok = FakeFace(1, [v0, v1, v2], area=1.0)
    e_nm.link_faces = [f_degen, f_ok, f_ok]
    bm = FakeBMesh(verts=[v0, v1, v2, v_loose], edges=[e_wire, e_nm], faces=[f_degen, f_ok])

    fake_bmesh_mod = MagicMock()
    fake_bmesh_mod.new.return_value = bm
    fake_bpy = MagicMock()

    ctx = MagicMock()
    obj_dirty = MagicMock()
    obj_dirty.name = "DirtyMesh"
    obj_dirty.scale = FakeVec(2.0, 1.0, 1.0)
    obj_dirty.material_slots = []
    obj_dirty.data = MagicMock()

    with (
        patch.object(san_mod, "bpy", fake_bpy),
        patch.object(san_mod, "bmesh", fake_bmesh_mod),
    ):
        # Guard check
        assert MeshSanitizer.run_preflight_inspection(None, []) == {}

        report = MeshSanitizer.run_preflight_inspection(ctx, [obj_dirty])
        assert report["loose_verts"] == 2
        assert report["loose_edges"] == 1
        assert report["non_manifold_edges"] == 1
        assert report["degenerate_tris"] == 1
        assert report["unapplied_scale"] is True
        assert report["missing_materials"] == 1
        assert report["is_clean"] is False
        assert "Unapplied Scale" in ctx.scene.lod_tool.preflight_summary_text

        # Clean mesh check
        bm_clean = FakeBMesh(verts=[v0], edges=[], faces=[f_ok])
        v0.link_edges = [FakeEdge(v0, v1)]
        fake_bmesh_mod.new.return_value = bm_clean
        obj_clean = MagicMock()
        obj_clean.name = "CleanMesh"
        obj_clean.scale = FakeVec(1.0, 1.0, 1.0)
        slot_valid = MagicMock()
        slot_valid.material = MagicMock()
        obj_clean.material_slots = [slot_valid]
        obj_clean.data = MagicMock()

        report_clean = MeshSanitizer.run_preflight_inspection(ctx, [obj_clean])
        assert report_clean["is_clean"] is True
        assert "Healthy" in ctx.scene.lod_tool.preflight_summary_text

        # Full sanitize pipeline
        opts = SanitizeOptions(
            epsilon_merge=0.001,
            w_crit=0.005,
            enable_weld=True,
            enable_cull_micro_islands=True,
            normal_recalc_policy="FORCE_ALL",
        )
        with patch.object(
            MeshSanitizer,
            "execute_tier1_topological_repair",
            return_value={"welded_verts": 3, "split_bowties": 1},
        ):
            full_stats = MeshSanitizer.sanitize_mesh_full(bm, options=opts)
            assert full_stats["merged_doubles"] == 3
            assert full_stats["split_bowties"] == 1
            assert full_stats["recalculated_normals"] is True


# =========================================================================
# 2. LOD Generator Deep Tests
# =========================================================================


def test_count_triangles_and_compute_lod0_stats() -> None:
    """Verify _count_triangles across loop/poly, poly-only, BMesh faces, and null inputs."""
    assert _count_triangles(None) == 0

    mesh_fast = MagicMock()
    mesh_fast.loops = [1, 2, 3, 4]
    mesh_fast.polygons = [MagicMock(vertices=[0, 1, 2, 3])]
    assert _count_triangles(mesh_fast) == 2

    mesh_poly = MagicMock()
    mesh_poly.loops = None
    mesh_poly.polygons = [MagicMock(vertices=[0, 1, 2]), MagicMock(vertices=[0, 1, 2, 3])]
    assert _count_triangles(mesh_poly) == 3

    bm_like = MagicMock()
    del bm_like.loops
    del bm_like.polygons
    bm_like.faces = [1, 2, 3, 4, 5]
    assert _count_triangles(bm_like) == 5

    obj_clean = MagicMock()
    obj_clean.material_slots = [MagicMock(), MagicMock()]
    obj_clean.data = mesh_fast

    obj_mod = MagicMock()
    obj_mod.material_slots = [MagicMock()]
    obj_mod.data = mesh_fast
    eval_obj = MagicMock()

    with (
        patch.object(lg_mod.ModifierManager, "has_unapplied_modifiers", side_effect=[False, True]),
        patch.object(lg_mod.ModifierManager, "get_evaluated_mesh", return_value=(mesh_poly, eval_obj)),
    ):
        tris, mats = _compute_lod0_stats([obj_clean, obj_mod])
        assert tris == 5
        assert mats == 3
        eval_obj.to_mesh_clear.assert_called_once()


@dataclass
class FakeTier:
    screen_size_pct: float = 50.0
    target_tris_pct: float = 50.0
    distance_m: float = 15.0
    last_baked_target_pct: float = 0.0
    last_baked_screen_pct: float = 0.0
    actual_tris: int = 0
    actual_triangles: int = 0
    mat_slots_count: int = 0
    generated_obj: Any = None
    state: str = "PENDING"
    target_tris: int = 100


@dataclass
class FakeLODProps(_MockBase):
    enable_slender_culling: bool = True
    tau_sse: float = 1.0
    enable_occlusion_culling: bool = True
    occlusion_lod_start: int = 1
    occlusion_ray_density: int = 8
    occlusion_evaluate_alpha: bool = True
    pin_uv_seams: bool = True
    pin_material_borders: bool = True
    msfs_preserve_decals: bool = True
    purge_shape_keys: bool = True
    preserve_slot_indexing: bool = False
    enable_bone_pruning: bool = True
    max_bone_influences: int = 4
    hierarchy_mode: str = "MERGE_ALL"
    consolidate_hierarchy: bool = True
    merge_start_tier: int = 1
    enable_impostor_lod: bool = True
    lods: list[FakeTier] = field(default_factory=lambda: [FakeTier(100.0, 100.0), FakeTier(50.0, 50.0)])
    last_culled_slender_count: int = 0
    last_generated_base_tris: int = 0
    last_generated_final_tris: int = 0
    last_generated_reduction_pct: float = 0.0
    last_generated_tier_count: int = 0


def test_generate_all_lods_guards_and_full_pipeline() -> None:
    """Verify generate_all_lods boundary guards, merged/unmerged tiers, and out-of-sync filtering."""
    bdata = MagicMock()
    ctx = MagicMock()
    props = FakeLODProps()
    fake_bpy = MagicMock()

    with patch.object(lg_mod, "bpy", fake_bpy):
        # Guard 1: No context
        ok, msg = generate_all_lods(None, props, [], blend_data=bdata)
        assert ok is True
        assert "not available" in msg

        # Guard 2: Empty mesh_objs
        ok, msg = generate_all_lods(ctx, props, [], base_name="TestAsset", blend_data=bdata)
        assert ok is False
        assert "No mesh objects" in msg

        # Guard 3: Missing props
        mesh_obj1 = MagicMock()
        mesh_obj1.name = "Hero_Body"
        mesh_obj1.data.loops = [1, 2, 3, 4]
        mesh_obj1.data.polygons = [MagicMock(vertices=[0, 1, 2, 3])]
        mesh_obj1.bound_box = [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0)]
        mesh_obj1.matrix_world = MagicMock()
        mesh_obj1.matrix_world.__matmul__.side_effect = lambda v: v
        mesh_obj1.material_slots = [MagicMock()]
        mesh_obj1.vertex_groups = [MagicMock()]

        ok, msg = generate_all_lods(ctx, None, [mesh_obj1], base_name="Hero", blend_data=bdata)
        assert ok is False
        assert "settings not provided" in msg

        # Full pipeline execution with 2 meshes (triggers merged tier path)
        mesh_obj2 = MagicMock()
        mesh_obj2.name = "Hero_Armor"
        mesh_obj2.data = mesh_obj1.data
        mesh_obj2.bound_box = None
        mesh_obj2.data.vertices = [MagicMock(co=FakeVec(1.0, 2.0, 3.0))]
        mesh_obj2.matrix_world = mesh_obj1.matrix_world
        mesh_obj2.material_slots = [MagicMock()]

        arm_obj = MagicMock()
        arm_obj.data.pose_position = "POSE"

        ctx.scene.render.resolution_x = 1920
        ctx.scene.render.resolution_y = 1080
        ctx.scene.camera.type = "CAMERA"
        ctx.scene.camera.data.angle = 1.0
        ctx.scene.camera.data.sensor_fit = "AUTO"

        merged_tier_obj = MagicMock()
        merged_tier_obj.name = "Hero_LOD1"
        merged_tier_obj.data = mesh_obj1.data
        merged_tier_obj.material_slots = [MagicMock()]
        merged_tier_obj.vertex_groups = [MagicMock()]

        fake_bm = FakeBMesh(verts=[FakeVert(0), FakeVert(1), FakeVert(2)], faces=[FakeFace(0, [FakeVert(0)], area=1.0)])
        fake_bmesh_mod = MagicMock()
        fake_bmesh_mod.new.return_value = fake_bm

        with (
            patch.object(lg_mod, "bmesh", fake_bmesh_mod),
            patch.object(lg_mod, "Vector", lambda b: FakeVec(b[0], b[1], b[2])),
            patch.object(
                lg_mod.CollectionCloneDAG,
                "wrap_loose_objects_into_root_collection",
                return_value=(MagicMock(), MagicMock()),
            ),
            patch.object(lg_mod.CollectionCloneDAG, "get_or_create_sibling_collection", return_value=MagicMock()),
            patch.object(
                lg_mod.CollectionCloneDAG,
                "clone_collection_hierarchy",
                return_value={"pivot": MagicMock()},
            ),
            patch.object(lg_mod.MeshMergeEngine, "consolidate_and_merge_meshes", return_value=merged_tier_obj),
            patch.object(lg_mod.MeshSanitizer, "sanitize_mesh_full"),
            patch.object(lg_mod.SlenderFeatureCuller, "cull_slender_features", return_value={"culled_islands": 2}),
            patch.object(lg_mod.HardenedOcclusionCuller, "cull_interior_faces"),
            patch.object(lg_mod.MeshDecimator, "apply_planar_limited_dissolve"),
            patch.object(lg_mod.MeshDecimator, "tag_boundaries_and_uv_seams", return_value={0}),
            patch.object(lg_mod.MeshDecimator, "inject_curvature_weights"),
            patch.object(lg_mod.MeshDecimator, "purge_all_shape_keys"),
            patch.object(lg_mod.MeshDecimator, "execute_decimate_qem"),
            patch.object(lg_mod.MaterialOptimizer, "consolidate_micro_materials"),
            patch.object(lg_mod.NormalManager, "reproject_custom_split_normals"),
            patch.object(lg_mod.KinematicBonePruner, "prune_kinematic_subtrees"),
            patch.object(lg_mod.WeightSanitizer, "normalize_and_clamp_weights"),
        ):
            ok, msg = generate_all_lods(
                ctx, props, [mesh_obj1, mesh_obj2], armature_obj=arm_obj, base_name="Hero_LOD0", blend_data=bdata
            )
            assert ok is True
            assert "Successfully generated" in msg
            assert arm_obj.data.pose_position == "POSE"
            assert props.lods[0].state == "SOURCE"
            assert props.lods[1].state == "BAKED"
            assert props.last_culled_slender_count == 2

            # Test unmerged tier path (single mesh object, tier_idx=2 for bone pruning)
            props.consolidate_hierarchy = False
            props.hierarchy_mode = "PRESERVE"
            props.lods.append(FakeTier(25.0, 25.0))
            lod_copy = MagicMock()
            lod_copy.name = "Hero_LOD2"
            lod_copy.data = mesh_obj1.data
            lod_copy.material_slots = [MagicMock()]
            lod_copy.vertex_groups = [MagicMock()]
            lod_copy.parent = None
            mesh_obj1.copy.return_value = lod_copy
            mesh_obj1.data.copy.return_value = mesh_obj1.data

            ok2, msg2 = generate_all_lods(
                ctx,
                props,
                [mesh_obj1],
                armature_obj=arm_obj,
                base_name="Hero",
                only_out_of_sync=True,
                blend_data=bdata,
            )
            assert ok2 is True
            assert "out-of-sync" in msg2
