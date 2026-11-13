"""Deep tests for scoped_export_visibility across hidden LOD collections and GLTFAssemblyEngine."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from core import gltf_assembly
from exporters import msfs_export, ue5_export, unity_export
from exporters.base import scoped_export_visibility
from exporters.engine_export import AssetMeshResolver


class _FakeColObjs(list[Any]):
    def link(self, obj: Any) -> None:
        if obj not in self:
            self.append(obj)

    def unlink(self, obj: Any) -> None:
        if obj in self:
            self.remove(obj)

    def __contains__(self, item: object) -> bool:
        return any(getattr(o, "name", None) == item or o is item for o in self)


class _FakeCollection:
    def __init__(self, name: str, hide_viewport: bool = False) -> None:
        self.name = name
        self.hide_viewport = hide_viewport
        self.objects = _FakeColObjs()

    def __hash__(self) -> int:
        return id(self)


class _FakeLayerCollection:
    def __init__(
        self,
        name: str,
        collection: _FakeCollection,
        children: list[_FakeLayerCollection] | None = None,
        hide_viewport: bool = False,
        exclude: bool = False,
    ) -> None:
        self.name = name
        self.collection = collection
        self.children = children or []
        self.hide_viewport = hide_viewport
        self.exclude = exclude


class _FakeExportObj:
    def __init__(self, name: str, cols: tuple[_FakeCollection, ...], hide_viewport: bool = False) -> None:
        self.name = name
        self.type = "MESH"
        self.parent: Any = None
        self.users_collection = cols
        self.hide_viewport = hide_viewport
        self._hidden_vl = hide_viewport
        self.selected = False
        self.matrix_world = MagicMock()
        self.matrix_world.copy.return_value = self.matrix_world
        self.data = SimpleNamespace(users=1, materials=[], copy=lambda: SimpleNamespace(users=1, materials=[]))
        self.dimensions = SimpleNamespace(x=0.2, y=0.2, z=0.2)
        self.display_type = "TEXTURED"
        self.show_wire = False
        self.modifiers: list[Any] = []
        self._idprops: dict[str, Any] = {}

    def __setitem__(self, k: str, v: Any) -> None:
        self._idprops[k] = v

    def __getitem__(self, k: str) -> Any:
        return self._idprops[k]

    def get(self, k: str, default: Any = None) -> Any:
        return self._idprops.get(k, default)

    def hide_set(self, val: bool, view_layer: Any = None) -> None:
        _ = view_layer
        self._hidden_vl = val

    def hide_get(self, view_layer: Any = None) -> bool:
        _ = view_layer
        return self._hidden_vl

    def select_set(self, val: bool) -> None:
        self.selected = val


def _make_visibility_context() -> tuple[Any, Any, Any, Any, Any]:
    root_col = _FakeCollection("Scene Collection", hide_viewport=False)
    lod0_col = _FakeCollection("Plane_LOD0", hide_viewport=False)
    lod1_col = _FakeCollection("Plane_LOD1", hide_viewport=True)

    lod0 = _FakeExportObj("Fuselage", (lod0_col,), hide_viewport=False)
    lod1 = _FakeExportObj("Fuselage_LOD1", (lod1_col,), hide_viewport=True)
    lod0_col.objects.link(lod0)
    lod1_col.objects.link(lod1)

    lc_lod0 = _FakeLayerCollection("Plane_LOD0", lod0_col, hide_viewport=False, exclude=False)
    lc_lod1 = _FakeLayerCollection("Plane_LOD1", lod1_col, hide_viewport=True, exclude=True)
    lc_root = _FakeLayerCollection("Scene Collection", root_col, children=[lc_lod0, lc_lod1])

    vl = SimpleNamespace(
        objects=SimpleNamespace(active=None), layer_collection=lc_root, active_layer_collection=lc_root
    )
    scene = SimpleNamespace(
        collection=root_col,
        lod_tool=SimpleNamespace(
            lods=[SimpleNamespace(screen_size_pct=100.0), SimpleNamespace(screen_size_pct=40.0)],
            cull_screen_size_pct=1.0,
            msfs_target_version="MSFS2024",
            asset_category="AIRCRAFT",
            msfs_with_exterior_show_interior=False,
            msfs_with_exterior_show_interior_hide_first_lod=False,
            msfs_with_interior_force_first_lod=False,
            msfs_with_interior_show_exterior=False,
        ),
    )

    class _ObjsDict(dict[str, Any]):
        def __bool__(self) -> bool:
            return True

        def new(self, n: str, _d: Any = None) -> _FakeExportObj:
            o = _FakeExportObj(n, (root_col,))
            self[n] = o
            return o

        def remove(self, obj: Any, do_unlink: bool = True) -> None:
            _ = do_unlink
            self.pop(obj.name, None)

    bdata = SimpleNamespace(objects=_ObjsDict(), collections=[])
    ctx = SimpleNamespace(
        mode="OBJECT",
        selected_objects=[lod0],
        view_layer=vl,
        scene=scene,
        blend_data=bdata,
    )
    return ctx, lod1_col, lc_lod1, lod0, lod1


def test_scoped_export_visibility_and_msfs_ue5_unity_hidden_lod_collections(tmp_path: Path) -> None:
    """Verify hidden LOD collections & excluded LayerCollections are revealed during export and restored on exit."""
    ctx, lod1_col, lc_lod1, lod0, lod1 = _make_visibility_context()
    att = _FakeExportObj("ATTACH_PILOT", (lod1_col,), hide_viewport=True)

    # 1. Direct context manager behavior + rollback on exception
    seen_inside: dict[str, bool] = {}
    try:
        with scoped_export_visibility(ctx, [lod0, lod1]):
            seen_inside["col_hide"] = lod1_col.hide_viewport
            seen_inside["lc_hide"] = lc_lod1.hide_viewport
            seen_inside["lc_excl"] = lc_lod1.exclude
            seen_inside["obj_hide"] = lod1.hide_viewport
            seen_inside["obj_vl_hide"] = lod1.hide_get(ctx.view_layer)
            raise RuntimeError("boom during export")
    except RuntimeError:
        pass

    assert seen_inside == {
        "col_hide": False,
        "lc_hide": False,
        "lc_excl": False,
        "obj_hide": False,
        "obj_vl_hide": False,
    }
    assert lod1_col.hide_viewport is True
    assert lc_lod1.hide_viewport is True
    assert lc_lod1.exclude is True
    assert lod1.hide_viewport is True
    assert lod1.hide_get(ctx.view_layer) is True

    # 2. MSFSExporter reveals hidden LOD1 collection when exporting LOD1 glTF, then restores it
    observed_states: list[tuple[str, bool, bool, bool]] = []

    def _fake_gltf(**kwargs: Any) -> None:
        _ = kwargs
        observed_states.append(
            (str(kwargs.get("filepath", "")), lod1_col.hide_viewport, lc_lod1.hide_viewport, lod1.hide_viewport)
        )

    payload = SimpleNamespace(
        export_objects=[lod0, lod1],
        lod_tiers={0: [lod0], 1: [lod1]},
        collider_objects=[],
        attachment_nodes=[att],
        has_impostor_tier=False,
        is_skeletal=False,
        armature_obj=None,
    )
    fake_bpy = MagicMock()
    fake_bpy.ops.export_scene.gltf.side_effect = _fake_gltf

    with (
        patch.object(msfs_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok, _msg = msfs_export.MSFSExporter.export_asset(ctx, str(tmp_path / "msfs"), "Plane")

    assert ok is True
    assert len(observed_states) == 2
    assert all(state[1:] == (False, False, False) for state in observed_states)
    assert lod1_col.hide_viewport is True
    assert lc_lod1.hide_viewport is True
    assert lc_lod1.exclude is True

    # 3. UE5Exporter and UnityExporter also unhide LOD1 collection during FBX export & restore afterward
    ue5_observed: list[tuple[bool, bool, bool]] = []
    fake_bpy.ops.export_scene.fbx.side_effect = lambda **_kw: ue5_observed.append(
        (lod1_col.hide_viewport, lc_lod1.hide_viewport, lod1.hide_viewport)
    )
    with (
        patch.object(ue5_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok_ue5, _ = ue5_export.UE5Exporter.export_asset(ctx, str(tmp_path / "ue5"), "Plane")
    assert ok_ue5 is True
    assert ue5_observed == [(False, False, False)]
    assert lod1_col.hide_viewport is True

    unity_observed: list[tuple[bool, bool, bool]] = []
    fake_bpy.ops.export_scene.fbx.side_effect = lambda **_kw: unity_observed.append(
        (lod1_col.hide_viewport, lc_lod1.hide_viewport, lod1.hide_viewport)
    )
    with (
        patch.object(unity_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok_uni, _ = unity_export.UnityExporter.export_asset(ctx, str(tmp_path / "unity"), "Plane")
    assert ok_uni is True
    assert unity_observed == [(False, False, False)]
    assert lod1_col.hide_viewport is True


def test_gltf_assembly_classification_and_isolation(tmp_path: Path) -> None:
    """Exercise find_layer_collection, classify_imported_mesh_node, and isolated glTF ingestion."""
    ctx, lod1_col, lc_lod1, lod0, _ = _make_visibility_context()
    assert gltf_assembly.find_layer_collection(ctx.view_layer.layer_collection, lod1_col) is lc_lod1
    missing_col: Any = _FakeCollection("Missing")
    assert gltf_assembly.find_layer_collection(ctx.view_layer.layer_collection, missing_col) is None

    # Classification paths
    assert gltf_assembly.classify_imported_mesh_node(None) == "RENDER_MESH"
    assert gltf_assembly.classify_imported_mesh_node(lod0) == "RENDER_MESH"

    trig: Any = _FakeExportObj("Switch_01", (lod1_col,))
    trig["_is_trigger"] = True
    assert gltf_assembly.classify_imported_mesh_node(trig) == "INTERACTION_VOLUME"

    hull: Any = _FakeExportObj("UCX_Hull", (lod1_col,))
    assert gltf_assembly.classify_imported_mesh_node(hull) == "PHYSICS_COLLIDER"

    invis_mat = {"_omnimesh_invisible": True}
    small_col: Any = _FakeExportObj("collision_small", (lod1_col,))
    small_col.data = SimpleNamespace(
        users=2, materials=[invis_mat], copy=lambda: SimpleNamespace(users=1, materials=[])
    )
    small_col.dimensions = SimpleNamespace(x=0.1, y=0.1, z=0.1)
    assert gltf_assembly.classify_imported_mesh_node(small_col, is_interior=True) == "INTERACTION_VOLUME"

    big_col: Any = _FakeExportObj("collision_airframe", (lod1_col,))
    big_col.data = SimpleNamespace(users=1, materials=[invis_mat])
    big_col.dimensions = SimpleNamespace(x=2.0, y=2.0, z=2.0)
    assert gltf_assembly.classify_imported_mesh_node(big_col, is_interior=True) == "PHYSICS_COLLIDER"

    # Non-existent file returns empty list safely
    bdata: Any = SimpleNamespace(objects=[lod0], collections=[lod1_col])
    assert (
        gltf_assembly.GLTFAssemblyEngine.import_gltf_into_collection(
            ctx, tmp_path / "missing.gltf", lod1_col, blend_data=bdata
        )
        == []
    )

    gltf_file = tmp_path / "plane.gltf"
    gltf_file.write_text('{"asset":{"version":"2.0"}}', encoding="utf-8")

    stray_col = _FakeCollection("ImporterDefault")
    new_render = _FakeExportObj("WingMesh", (stray_col,))
    new_trig = _FakeExportObj("Interact_Knob", (stray_col,))
    new_hull = _FakeExportObj("UBX_Gear", (stray_col,))
    stray_col.objects.extend([new_render, new_trig, new_hull])

    interact_col = _FakeCollection("Plane_Interact")
    coll_col = _FakeCollection("Plane_Colliders")
    created_objs = [lod0, new_render, new_trig, new_hull]

    def _fake_import_gltf(filepath: str) -> None:
        _ = filepath
        bdata.objects = created_objs

    fake_bpy = MagicMock()
    fake_bpy.ops.import_scene.gltf.side_effect = _fake_import_gltf

    with (
        patch.object(gltf_assembly, "bpy", fake_bpy),
        patch.object(
            gltf_assembly,
            "get_or_create_engine_import_collection",
            side_effect=lambda _c, _a, role, **_kw: interact_col if role == "INTERACTIONS" else coll_col,
        ),
    ):
        imported = gltf_assembly.GLTFAssemblyEngine.import_gltf_into_collection(
            ctx, gltf_file, lod1_col, asset_name="Plane", blend_data=bdata
        )

    assert len(imported) == 3
    assert new_render in lod1_col.objects
    assert new_trig in interact_col.objects
    assert new_hull in coll_col.objects
    assert new_render not in stray_col.objects


def test_asset_mesh_resolver_ignores_other_scene_objects() -> None:
    class _ColStore(dict[str, Any]):
        def __init__(self, cols: list[Any]) -> None:
            super().__init__({c.name: c for c in cols})

    def _col(name: str, kids: list[Any] | None = None) -> Any:
        c = SimpleNamespace(
            name=name,
            hide_viewport=False,
            objects=_FakeColObjs(),
            children=_ColStore(kids or []),
            get=lambda _k, d=None: d,
        )
        return c

    lod0_col = _col("Asset_LOD0")
    imp_col = _col("Asset_LOD_Impostor")
    root_col = _col("Asset", [lod0_col])  # imp_col belongs to another scene

    lod0_mesh = _FakeExportObj("Wing_LOD0", (lod0_col,))
    lod0_col.objects.append(lod0_mesh)

    other_scene_imp = _FakeExportObj("Asset_LOD_Impostor", (imp_col,))
    other_scene_imp["_is_impostor"] = True
    imp_col.objects.append(other_scene_imp)

    bdata_objs = _FakeColObjs()
    bdata_objs.extend([lod0_mesh, other_scene_imp])
    scene_objs = _FakeColObjs()
    scene_objs.append(lod0_mesh)  # Impostor intentionally absent from active scene

    bdata: Any = SimpleNamespace(
        collections=_ColStore([root_col, lod0_col, imp_col]),
        objects=bdata_objs,
    )
    ctx: Any = SimpleNamespace(
        scene=SimpleNamespace(
            collection=root_col,
            objects=scene_objs,
            lod_tool=SimpleNamespace(lods=[]),
        ),
        blend_data=bdata,
    )

    payload = AssetMeshResolver.resolve_payload(ctx, "Asset", blend_data=bdata)
    assert payload.impostor_object is None
    assert payload.has_impostor_tier is False
    assert payload.lod_tiers == {0: [lod0_mesh]}
