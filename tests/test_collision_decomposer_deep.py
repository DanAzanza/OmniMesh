"""
Deep unit and negative boundary tests for core/collision_decomposer.py covering
PCA fallback, stratified BVH concavity measurement, planar/1D extrusion hardening,
interior purge, edge-collapse clamping, and hierarchical decomposition rollbacks.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core import collision_decomposer as cd_mod
from core.collision_decomposer import CollisionDecomposer
from core.compat import Vector


class _FakeBMVert:
    def __init__(self, co: tuple[float, float, float]) -> None:
        self.co = Vector(co)
        self.is_valid = True


class _FakeBMEdge:
    def __init__(self, length: float = 1.0) -> None:
        self._length = length
        self.is_valid = True

    def calc_length(self) -> float:
        return self._length


class _FakeBMFace:
    def __init__(self, center: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> None:
        self._center = Vector(center)
        self.is_valid = True

    def calc_center_median(self) -> Vector:
        return self._center


class _BMSeq(list):
    def __init__(self, items: list[Any], *, raise_lookup: bool = False) -> None:
        super().__init__(items)
        self._raise_lookup = raise_lookup

    def ensure_lookup_table(self) -> None:
        if self._raise_lookup:
            raise RuntimeError("lookup failure")


class _FakeBM:
    def __init__(
        self,
        verts: list[Any],
        faces: list[Any] | None = None,
        edges: list[Any] | None = None,
        *,
        raise_face_lookup: bool = False,
    ) -> None:
        self.verts = _BMSeq(verts)
        self.faces = _BMSeq(faces or [], raise_lookup=raise_face_lookup)
        self.edges = _BMSeq(edges or [])
        self.freed = False
        self.copy_factory: Any = None

    def copy(self) -> _FakeBM:
        if self.copy_factory is not None:
            return self.copy_factory(self)
        return _FakeBM(list(self.verts), list(self.faces), list(self.edges))

    def from_mesh(self, mesh: Any) -> None:
        if getattr(mesh, "raise_on_load", False):
            raise RuntimeError("corrupt mesh")

    def free(self) -> None:
        self.freed = True


def _make_bmesh_module(
    *,
    convex_hull_fn: Any = None,
    dissolve_fn: Any = None,
    collapse_fn: Any = None,
    delete_fn: Any = None,
    bisect_fn: Any = None,
    new_bm: Any = None,
) -> Any:
    ops = SimpleNamespace(
        extrude_face_region=lambda bm, geom: {"geom": list(bm.verts)},
        extrude_vert_indiv=lambda bm, verts: None,
        translate=lambda bm, vec, verts: None,
        convex_hull=convex_hull_fn or (lambda bm, input, use_existing_faces=False: {}),
        delete=delete_fn or (lambda bm, geom, context="VERTS": None),
        dissolve_limit=dissolve_fn or (lambda bm, angle_limit, edges, verts: None),
        collapse=collapse_fn or (lambda bm, edges: None),
        bisect_plane=bisect_fn or (lambda bm, geom, plane_co, plane_no, clear_outer=True: None),
    )
    return SimpleNamespace(
        types=SimpleNamespace(BMVert=_FakeBMVert, BMFace=_FakeBMFace, BMEdge=_FakeBMEdge),
        ops=ops,
        new=new_bm or (lambda: _FakeBM([])),
    )


class TestCollisionDecomposerDeep:
    def test_pca_degenerate_zero_normal_and_svd_error(self) -> None:
        # Mock zero singular vector row -> triggers normal_vec.length < 1e-8 fallback -> (0,0,1)
        with patch.object(cd_mod, "Vector", Vector):
            with patch.object(np.linalg, "svd", return_value=(None, None, np.zeros((3, 3)))):
                c, n = CollisionDecomposer.compute_pca_splitting_plane(
                    np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0], [1.0, 2.0, 3.0]])
                )
                assert (c.x, c.y, c.z) == pytest.approx((1.0, 2.0, 3.0))
                assert (n.x, n.y, n.z) == pytest.approx((0.0, 0.0, 1.0))

            with patch.object(np.linalg, "svd", side_effect=np.linalg.LinAlgError("svd fail")):
                _, n_err = CollisionDecomposer.compute_pca_splitting_plane(
                    np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
                )
                assert (n_err.x, n_err.y, n_err.z) == pytest.approx((0.0, 0.0, 1.0))

    def test_measure_concavity_stratified_and_errors(self) -> None:
        assert CollisionDecomposer.measure_hull_concavity(None, None) == 0.0

        bm_small = _FakeBM([], faces=[_FakeBMFace() for _ in range(5)])
        bm_hull = _FakeBM([], faces=[_FakeBMFace()])
        bm_big = _FakeBM([], faces=[_FakeBMFace((float(i), 0.0, 0.0)) for i in range(600)])

        bvh = MagicMock()
        bvh.find_nearest.side_effect = lambda pt: (pt, None, 0, abs(pt.x))
        bvh_cls = SimpleNamespace(FromBMesh=lambda _h, epsilon=1e-5: bvh)

        with patch.object(cd_mod, "BVHTree", bvh_cls):
            assert CollisionDecomposer.measure_hull_concavity(bm_small, bm_hull) == 0.0  # type: ignore[arg-type]
            dist = CollisionDecomposer.measure_hull_concavity(bm_big, bm_hull)  # type: ignore[arg-type]
            assert dist == pytest.approx(599.0)

        with patch.object(cd_mod, "BVHTree", SimpleNamespace(FromBMesh=lambda *_a, **_k: None)):
            assert CollisionDecomposer.measure_hull_concavity(bm_small, bm_hull) == 0.0  # type: ignore[arg-type]

        def _raise_bvh(*_a: Any, **_k: Any) -> Any:
            raise RuntimeError("bvh err")

        with patch.object(cd_mod, "BVHTree", SimpleNamespace(FromBMesh=_raise_bvh)):
            assert CollisionDecomposer.measure_hull_concavity(bm_small, bm_hull) == 0.0  # type: ignore[arg-type]

    def test_harden_convex_hull_planar_needle_purge_and_clamp(self) -> None:
        # 1. Fewer than 3 verts -> False
        assert CollisionDecomposer.harden_convex_hull(_FakeBM([_FakeBMVert((0, 0, 0))])) is False  # type: ignore[arg-type]

        # 2. 1D needle (4 collinear verts, no faces) triggers both planar + needle extrusions,
        # interior face+vert purge (including delete errors), dissolve error fallback, and collapse clamping
        needle_verts = [_FakeBMVert((float(i), 0.0, 0.0)) for i in range(6)]
        unused_face = _FakeBMFace()
        unused_vert = _FakeBMVert((9.0, 9.0, 9.0))
        edges = [_FakeBMEdge(0.2), _FakeBMEdge(0.1)]
        bm_needle = _FakeBM(needle_verts, faces=[], edges=edges)

        ext_calls: list[str] = []

        def _fake_delete(bm: Any, geom: Any, context: str = "VERTS") -> None:
            ext_calls.append(context)
            if context == "VERTS":
                raise RuntimeError("locked vert")

        def _fake_dissolve(*_a: Any, **_k: Any) -> None:
            raise RuntimeError("dissolve skip")

        def _fake_collapse(bm: Any, edges: Any) -> None:
            bm.verts.pop()

        def _fake_hull(_bm: Any, input: Any, use_existing_faces: bool = False) -> dict[str, Any]:
            ext_calls.append("hull")
            return {"geom_unused": [unused_face], "geom_interior": [unused_vert]}

        fake_bmesh = _make_bmesh_module(
            convex_hull_fn=_fake_hull,
            dissolve_fn=_fake_dissolve,
            collapse_fn=_fake_collapse,
            delete_fn=_fake_delete,
        )
        fake_bmesh.ops.extrude_vert_indiv = lambda bm, verts: ext_calls.append("extrude_vert_indiv")

        with patch.object(cd_mod, "bmesh", fake_bmesh), patch.object(cd_mod, "Vector", Vector):
            ok = CollisionDecomposer.harden_convex_hull(bm_needle, max_verts=4)  # type: ignore[arg-type]
            assert ok is True
            assert ext_calls.count("extrude_vert_indiv") == 2
            assert "FACES_ONLY" in ext_calls and "VERTS" in ext_calls

        # 3. Planar sheet WITH faces + convex_hull RuntimeError returning False
        sheet_bm = _FakeBM(
            [_FakeBMVert((0, 0, 0)), _FakeBMVert((1, 0, 0)), _FakeBMVert((1, 1, 0)), _FakeBMVert((0, 1, 0))],
            faces=[_FakeBMFace()],
        )
        err_bmesh = _make_bmesh_module(
            convex_hull_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("hull failed"))
        )
        with patch.object(cd_mod, "bmesh", err_bmesh), patch.object(cd_mod, "Vector", Vector):
            assert CollisionDecomposer.harden_convex_hull(sheet_bm) is False  # type: ignore[arg-type]

    def test_decompose_mesh_to_hulls_paths_and_rollback(self) -> None:
        with patch.object(cd_mod, "bmesh", None):
            assert CollisionDecomposer.decompose_mesh_to_hulls() == []

        # 1. Source object modifier evaluation failure -> fallback mesh -> <4 verts freed
        small_bm = _FakeBM([_FakeBMVert((0, 0, 0)), _FakeBMVert((1, 0, 0))])
        fake_bm_mod = _make_bmesh_module(new_bm=lambda: small_bm)
        src_obj: Any = SimpleNamespace(scale=(2.0, 2.0, 2.0), data=SimpleNamespace(raise_on_load=False))
        with (
            patch.object(cd_mod, "bmesh", fake_bm_mod),
            patch("core.modifiers.ModifierManager.get_evaluated_mesh", side_effect=RuntimeError("no depsgraph")),
        ):
            assert CollisionDecomposer.decompose_mesh_to_hulls(source_obj=src_obj) == []
            assert small_bm.freed is True

        # 2. from_mesh raises BMESH_OP_ERRORS -> frees bm_master and re-raises
        bad_load_bm = _FakeBM([])
        bad_mesh_obj: Any = SimpleNamespace(scale=(1.0, 1.0, 1.0), data=SimpleNamespace(raise_on_load=True))
        eval_obj = SimpleNamespace(to_mesh_clear=MagicMock())
        with (
            patch.object(cd_mod, "bmesh", _make_bmesh_module(new_bm=lambda: bad_load_bm)),
            patch("core.modifiers.ModifierManager.get_evaluated_mesh", return_value=(bad_mesh_obj.data, eval_obj)),
        ):
            with pytest.raises(RuntimeError, match="corrupt mesh"):
                CollisionDecomposer.decompose_mesh_to_hulls(source_obj=bad_mesh_obj)
            assert bad_load_bm.freed is True
            eval_obj.to_mesh_clear.assert_called_once()

        # 3. Bisection with one degenerate slice rollback + harden failure frees c
        verts10 = [_FakeBMVert((float(i % 2), float((i // 2) % 2), float(i // 4))) for i in range(10)]
        master_bm: Any = _FakeBM(verts10, faces=[_FakeBMFace()])

        def _bisect_make_degenerate(bm: Any, geom: Any, plane_co: Any, plane_no: Any, clear_outer: bool = True) -> None:
            if plane_no[0] < 0 or plane_no[1] < 0 or plane_no[2] < 0:
                bm.verts[:] = bm.verts[:2]  # force child_b < 4 verts -> triggers rollback!

        bm_mod_bisect = _make_bmesh_module(bisect_fn=_bisect_make_degenerate)
        with (
            patch.object(cd_mod, "bmesh", bm_mod_bisect),
            patch.object(cd_mod, "Vector", Vector),
            patch.object(CollisionDecomposer, "measure_hull_concavity", return_value=1.0),
            patch.object(CollisionDecomposer, "harden_convex_hull", return_value=True),
        ):
            res = CollisionDecomposer.decompose_mesh_to_hulls(
                bm_source=master_bm,
                k_target=3,
                concavity_threshold=0.05,  # type: ignore[arg-type]
            )
            assert len(res) == 1

        # 4. Mid-bisection crash exercises finally cleanup of child_a/child_b/target_cluster/clusters
        created_bms: list[_FakeBM] = []

        def _tracked_copy(bm_in: _FakeBM) -> _FakeBM:
            cp = _FakeBM(list(bm_in.verts), list(bm_in.faces), list(bm_in.edges))
            cp.copy_factory = _tracked_copy
            created_bms.append(cp)
            return cp

        crash_master: Any = _FakeBM(verts10, faces=[_FakeBMFace()])
        crash_master.copy_factory = _tracked_copy
        crash_mod = _make_bmesh_module(bisect_fn=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bisect boom")))
        with (
            patch.object(cd_mod, "bmesh", crash_mod),
            patch.object(cd_mod, "Vector", Vector),
            patch.object(CollisionDecomposer, "measure_hull_concavity", return_value=1.0),
        ):
            with pytest.raises(RuntimeError, match="bisect boom"):
                CollisionDecomposer.decompose_mesh_to_hulls(
                    bm_source=crash_master,
                    k_target=2,
                    concavity_threshold=0.01,  # type: ignore[arg-type]
                )
            assert all(c.freed for c in created_bms)
