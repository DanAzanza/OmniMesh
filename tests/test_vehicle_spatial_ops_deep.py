# pyright: reportAttributeAccessIssue=none
"""Deep tests for ui.vehicle_spatial_ops covering import, sync, snap, mirror, and failure paths."""

from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

from core.msfs.models import SpatialPoint
from core.msfs.transforms import FEET_TO_METERS
import ui.vehicle_spatial_ops as vsp


class _Vec3:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x = x
        self.y = y
        self.z = z

    def __sub__(self, other: _Vec3) -> _Vec3:
        return _Vec3(self.x - other.x, self.y - other.y, self.z - other.z)

    @property
    def length_squared(self) -> float:
        return self.x * self.x + self.y * self.y + self.z * self.z


class _Mat4:
    def __init__(self, tx: float = 0.0, ty: float = 0.0, tz: float = 0.0) -> None:
        self.translation = _Vec3(tx, ty, tz)

    def __matmul__(self, v: _Vec3) -> _Vec3:
        return _Vec3(self.translation.x + v.x, self.translation.y + v.y, self.translation.z + v.z)

    def inverted(self) -> _Mat4:
        return _Mat4(-self.translation.x, -self.translation.y, -self.translation.z)


class _FakeColObjs(list[Any]):
    def link(self, obj: Any) -> None:
        if obj not in self:
            self.append(obj)
        if hasattr(obj, "users_collection") and self._owner not in obj.users_collection:
            obj.users_collection.append(self._owner)

    def __init__(self, owner: Any) -> None:
        super().__init__()
        self._owner = owner


class _FakeChildList(list[Any]):
    def get(self, name: str) -> Any:
        return next((c for c in self if c.name == name), None)

    def link(self, col: Any) -> None:
        if any(c.name == col.name for c in self):
            raise RuntimeError("already linked")
        self.append(col)

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return any(c.name == item for c in self)
        return super().__contains__(item)


class _FakeCollection(dict[str, Any]):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.objects = _FakeColObjs(self)
        self.children = _FakeChildList()

    def __bool__(self) -> bool:
        return True

    def __eq__(self, other: object) -> bool:
        return self is other


class _FakeColStore(list[_FakeCollection]):
    def get(self, name: str) -> Any:
        return next((c for c in self if c.name == name), None)

    def new(self, name: str) -> _FakeCollection:
        col = _FakeCollection(name)
        self.append(col)
        return col

    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return any(c.name == item for c in self)
        return super().__contains__(item)

    def __getitem__(self, item: Any) -> Any:
        if isinstance(item, str):
            found = self.get(item)
            if found is None:
                raise KeyError(item)
            return found
        return super().__getitem__(item)


class _FakeObj(dict[str, Any]):
    def __init__(self, name: str, data: Any = None) -> None:
        super().__init__()
        self.name = name
        self.data = data
        self.type = "MESH" if data is not None else "EMPTY"
        self.parent: Any = None
        self.location = _Vec3()
        self.empty_display_type = "PLAIN_AXES"
        self.empty_display_size = 0.25
        self.rotation_mode = "XYZ"
        self.rotation_euler = _Vec3(0.1, 0.2, 0.3)
        self.matrix_world = _Mat4()
        self.users_collection: list[Any] = []
        self._mesh_data: Any = data

    def __bool__(self) -> bool:
        return True

    def __eq__(self, other: object) -> bool:
        return self is other

    def evaluated_get(self, _deps: Any) -> _FakeObj:
        tx, ty, tz = (
            tuple(self.location)
            if isinstance(self.location, tuple)
            else (self.location.x, self.location.y, self.location.z)
        )
        if self.parent is not None:
            ptx = self.parent.location[0] if isinstance(self.parent.location, tuple) else self.parent.location.x
            pty = self.parent.location[1] if isinstance(self.parent.location, tuple) else self.parent.location.y
            ptz = self.parent.location[2] if isinstance(self.parent.location, tuple) else self.parent.location.z
            tx += ptx
            ty += pty
            tz += ptz
        self.matrix_world = _Mat4(tx, ty, tz)
        return self

    def to_mesh(self) -> Any:
        return self._mesh_data

    def to_mesh_clear(self) -> None:
        self._cleared = True


class _FakeObjStore(list[_FakeObj]):
    def new(self, name: str, data: Any = None) -> _FakeObj:
        obj = _FakeObj(name, data)
        self.append(obj)
        return obj


def _make_fake_bpy() -> SimpleNamespace:
    cols = _FakeColStore()
    objs = _FakeObjStore()
    reg_log: list[tuple[str, Any]] = []
    return SimpleNamespace(
        data=SimpleNamespace(collections=cols, objects=objs),
        utils=SimpleNamespace(
            register_class=lambda cls: reg_log.append(("reg", cls)),
            unregister_class=lambda cls: reg_log.append(("unreg", cls)),
        ),
        _reg_log=reg_log,
    )


def _bind_report(cls: type[Any]) -> tuple[Any, list[tuple[set[str], str]]]:
    reports: list[tuple[set[str], str]] = []
    inst = object.__new__(cls)
    inst.filepath = ""
    inst.report = lambda lvl, msg: reports.append((lvl, msg))
    return inst, reports


def _make_context(cfg_path: str = "", asset_name: str = "Plane") -> SimpleNamespace:
    scene_col = _FakeCollection("Scene Collection")
    props = SimpleNamespace(
        export_base_name=asset_name,
        active_asset=asset_name,
        msfs_spatial_cfg_path=cfg_path,
        msfs_spatial_status="",
    )
    scene = SimpleNamespace(lod_tool=props, collection=scene_col, objects=[])
    return SimpleNamespace(
        scene=scene,
        window_manager=SimpleNamespace(fileselect_add=lambda _op: None),
        view_layer=SimpleNamespace(update=lambda: None),
        evaluated_depsgraph_get=lambda: object(),
        active_object=None,
        selected_objects=[],
    )


def test_spatial_collection_discovery_and_fallback(monkeypatch: Any) -> None:
    fake_bpy = _make_fake_bpy()
    monkeypatch.setattr(vsp, "bpy", fake_bpy)

    ctx = _make_context(asset_name="")
    assert vsp.find_spatial_collection(ctx) is None

    # Fallback creation when ui.utils fails
    fake_utils = ModuleType("ui.utils")
    fake_utils.get_or_create_engine_import_collection = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
    monkeypatch.setitem(sys.modules, "ui.utils", fake_utils)

    ctx.scene.lod_tool.export_base_name = "Jet"
    created = vsp.get_or_create_spatial_collection(ctx)
    assert created is not None
    assert created.name == "Jet_Spatial"
    assert created["_omnimesh_role"] == "SPATIAL"
    assert vsp.find_spatial_collection(ctx, asset_name="Jet") is created

    # Legacy fallback discovery when target asset not directly matched
    legacy = fake_bpy.data.collections.new("Spatial_Config")
    assert vsp.find_spatial_collection(_make_context(asset_name=""), asset_name="") is not None
    assert legacy.name == "Spatial_Config"


def test_import_and_export_msfs_spatial_roundtrip(monkeypatch: Any, tmp_path: Path) -> None:
    fake_bpy = _make_fake_bpy()
    monkeypatch.setattr(vsp, "bpy", fake_bpy)

    cfg_file = tmp_path / "flight_model.cfg"
    cfg_file.write_text("[WEIGHT_AND_BALANCE]\nreference_datum_position = 1, 0, 0\n", encoding="utf-8")

    # Failure paths for import
    imp_op, imp_reports = _bind_report(vsp.OMNIMESH_OT_import_msfs_spatial)
    assert imp_op.execute(None) == {"CANCELLED"}
    assert imp_op.execute(_make_context()) == {"CANCELLED"}
    assert imp_reports[-1][0] == {"ERROR"}

    # invoke copies scene path and triggers fileselect
    ctx = _make_context(cfg_path=str(cfg_file), asset_name="Aircraft")
    assert imp_op.invoke(ctx, None) == {"RUNNING_MODAL"}
    assert imp_op.filepath == str(cfg_file)

    # Parser exception path
    monkeypatch.setattr(vsp.MSFSCSTParser, "parse_file", lambda _p: (_ for _ in ()).throw(ValueError("bad cfg")))
    assert imp_op.execute(ctx) == {"CANCELLED"}

    # Success import + idempotent re-import across all SpatialPoint categories
    parsed = SimpleNamespace(
        reference_datum_ft=(1.0, 0.0, 0.0),
        points=[
            SpatialPoint(
                vsp.DATUM_POINT_ID,
                "WEIGHT_AND_BALANCE",
                "reference_datum_position",
                "DATUM",
                coords_msfs_rel_ft=(1.0, 0.0, 0.0),
                coords_blender_m=(0.0, FEET_TO_METERS, 0.0),
            ),
            SpatialPoint(
                "CONTACT_POINTS:point.0",
                "CONTACT_POINTS",
                "point.0",
                "CONTACT_POINT",
                name_tag="LeftMain",
                point_class=1,
                coords_msfs_rel_ft=(2.0, -3.0, -4.0),
            ),
            SpatialPoint(
                "CONTACT_POINTS:point.1",
                "CONTACT_POINTS",
                "point.1",
                "CONTACT_POINT",
                name_tag="TailScrape",
                point_class=2,
                coords_msfs_rel_ft=(-1.0, 0.0, -0.5),
            ),
            SpatialPoint(
                "CONTACT_POINTS:point.2",
                "CONTACT_POINTS",
                "point.2",
                "CONTACT_POINT",
                point_class=3,
                coords_msfs_rel_ft=(0.0, 0.0, 1.0),
            ),
            SpatialPoint(
                "FUEL:Center1",
                "FUEL",
                "Center1",
                "FUEL_TANK",
                name_tag="CenterTank",
            ),
            SpatialPoint(
                "WEIGHT_AND_BALANCE:empty_weight_CG_position",
                "WEIGHT_AND_BALANCE",
                "empty_weight_CG_position",
                "CG",
                coords_msfs_rel_ft=(0.5, 0.0, 0.2),
            ),
            SpatialPoint(
                "EXITS:exit.0",
                "EXITS",
                "exit.0",
                "EXIT",
                coords_msfs_rel_ft=(0.0, 2.0, 1.0),
            ),
        ],
    )
    monkeypatch.setattr(vsp.MSFSCSTParser, "parse_file", lambda _p: parsed)

    sp_col = _FakeCollection("Aircraft_Spatial")
    fake_bpy.data.collections.append(sp_col)
    cfg_col = fake_bpy.data.collections.new("Aircraft_Config")
    cfg_col.children.append(sp_col)

    assert imp_op.execute(ctx) == {"FINISHED"}
    assert len(sp_col.objects) == 7
    assert "Imported 7 markers" in ctx.scene.lod_tool.msfs_spatial_status
    # Re-run updates existing empties in place without duplicating objects
    assert imp_op.execute(ctx) == {"FINISHED"}
    assert len(sp_col.objects) == 7

    # Export operator poll + negative + roundtrip serialize
    assert vsp.OMNIMESH_OT_export_msfs_spatial.poll(None) is False
    assert vsp.OMNIMESH_OT_export_msfs_spatial.poll(ctx) is True

    exp_op, exp_reports = _bind_report(vsp.OMNIMESH_OT_export_msfs_spatial)
    saved_payloads: list[tuple[Any, str]] = []
    backup_file = tmp_path / "flight_model.cfg.bak"
    monkeypatch.setattr(
        vsp.MSFSCSTParser,
        "serialize_and_save",
        lambda _cfg, coords, target_path: saved_payloads.append((coords, target_path)) or str(backup_file),
    )

    assert exp_op.execute(ctx) == {"FINISHED"}
    assert saved_payloads and saved_payloads[0][1] == str(cfg_file)
    assert vsp.DATUM_POINT_ID in saved_payloads[0][0]
    assert "Synced" in exp_reports[-1][1]

    # Empty spatial collection cancels export
    sp_col.objects.clear()
    assert exp_op.execute(ctx) == {"CANCELLED"}


def test_snap_mirror_and_register(monkeypatch: Any) -> None:
    fake_bpy = _make_fake_bpy()
    monkeypatch.setattr(vsp, "bpy", fake_bpy)

    # Snap negative guards
    snap_op, _ = _bind_report(vsp.OMNIMESH_OT_snap_vehicle_point_to_vertex)
    ctx = _make_context()
    assert vsp.OMNIMESH_OT_snap_vehicle_point_to_vertex.poll(ctx) is False
    assert snap_op.execute(ctx) == {"CANCELLED"}

    datum = _FakeObj("Datum")
    datum.location = _Vec3(1.0, 2.0, 0.0)
    marker = _FakeObj("Point_0_Left_Main")
    marker["msfs_id"] = "CONTACT_POINTS:point.0"
    marker["msfs_type"] = "CONTACT_POINT"
    marker["msfs_section"] = "CONTACT_POINTS"
    marker["msfs_key"] = "point.0"
    marker["msfs_name_tag"] = "Left_Main"
    marker.parent = datum
    marker.location = _Vec3(-2.0, 0.5, -0.5)
    marker.matrix_world = _Mat4(-1.0, 2.5, -0.5)

    ctx.active_object = marker
    assert vsp.OMNIMESH_OT_snap_vehicle_point_to_vertex.poll(ctx) is True
    assert snap_op.execute(ctx) == {"CANCELLED"}  # No target mesh selected

    mesh_obj = _FakeObj(
        "WheelMesh",
        data=SimpleNamespace(
            vertices=[SimpleNamespace(co=_Vec3(0.0, 0.0, 0.0)), SimpleNamespace(co=_Vec3(5.0, 0.0, 0.0))]
        ),
    )
    mesh_obj.matrix_world = _Mat4(-1.2, 2.4, -0.4)
    ctx.selected_objects = [marker, mesh_obj]
    assert snap_op.execute(ctx) == {"FINISHED"}
    assert getattr(mesh_obj, "_cleared", False) is True

    # Target mesh returning None or empty vertices cancels safely
    empty_mesh = _FakeObj("Empty", data=SimpleNamespace(vertices=[]))
    ctx.selected_objects = [marker, empty_mesh]
    assert snap_op.execute(ctx) == {"CANCELLED"}
    none_mesh = _FakeObj("NullEval", data=None)
    none_mesh.type = "MESH"
    ctx.selected_objects = [marker, none_mesh]
    assert snap_op.execute(ctx) == {"CANCELLED"}

    # Mirror operator: centerline guard, spawn mirrored counterpart, then update counterpart
    mir_op, _ = _bind_report(vsp.OMNIMESH_OT_mirror_vehicle_marker)
    assert vsp.OMNIMESH_OT_mirror_vehicle_marker.poll(ctx) is True
    marker.location = _Vec3(0.01, 0.5, -0.5)
    assert mir_op.execute(ctx) == {"CANCELLED"}  # |X| < 0.05 guard

    col = _FakeCollection("Aircraft_Spatial")
    col.objects.link(marker)
    marker.location = _Vec3(-1.5, 0.8, -0.4)
    assert mir_op.execute(ctx) == {"FINISHED"}
    mirrored = next(o for o in fake_bpy.data.objects if o.name != marker.name)
    assert mirrored.location == (1.5, 0.8, -0.4)
    assert mirrored["msfs_id"] == "CONTACT_POINTS:point.0_MIRRORED"

    # Second call updates existing counterpart in place
    mirrored.location = _Vec3(1.5, 0.8, -0.4)
    assert mir_op.execute(ctx) == {"FINISHED"}
    assert mirrored.location == (1.5, 0.8, -0.4)

    # Mirror name helper variants
    for src, expected in [
        ("Wheel_L", "Wheel_R"),
        ("Wheel_R", "Wheel_L"),
        ("LeftWing", "RightWing"),
        ("RightWing", "LeftWing"),
        ("left_tank", "right_tank"),
        ("right_tank", "left_tank"),
        ("PortBeacon", "StbdBeacon"),
        ("StbdBeacon", "PortBeacon"),
        ("NoseWheel", "NoseWheel_Mirrored"),
    ]:
        assert vsp.OMNIMESH_OT_mirror_vehicle_marker._compute_mirrored_name(src) == expected

    vsp.register()
    vsp.unregister()
    assert len(fake_bpy._reg_log) >= 8
