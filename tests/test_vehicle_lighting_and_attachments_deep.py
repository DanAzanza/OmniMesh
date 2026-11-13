"""Deep headless test suite for ui/vehicle_lighting_ops.py and ui/vehicle_attachment_ops.py."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ui import vehicle_attachment_ops, vehicle_lighting_ops


class _Vec3:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)

    def __iter__(self) -> Any:
        yield self.x
        yield self.y
        yield self.z


class _Mat4:
    def __init__(
        self,
        tx: float = 0.0,
        ty: float = 0.0,
        tz: float = 0.0,
        rx: float = 0.0,
        ry: float = 0.0,
        rz: float = 0.0,
    ) -> None:
        self._t = _Vec3(tx, ty, tz)
        self._r = _Vec3(rx, ry, rz)

    def inverted(self) -> _Mat4:
        return _Mat4(-self._t.x, -self._t.y, -self._t.z, -self._r.x, -self._r.y, -self._r.z)

    def __matmul__(self, other: _Mat4) -> _Mat4:
        return _Mat4(
            self._t.x + other._t.x,
            self._t.y + other._t.y,
            self._t.z + other._t.z,
            self._r.x + other._r.x,
            self._r.y + other._r.y,
            self._r.z + other._r.z,
        )

    def to_translation(self) -> _Vec3:
        return self._t

    def to_euler(self, order: str = "XYZ") -> _Vec3:
        _ = order
        return self._r


class _PropsMixin:
    def __init__(self) -> None:
        self._custom: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._custom[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._custom[key] = value


class _FakeBoneCollection(list[Any]):
    def get(self, name: str, default: Any = None) -> Any:
        for b in self:
            if getattr(b, "name", None) == name:
                return b
        return default


class _FakeArmature:
    def __init__(self, bone_names: list[str]) -> None:
        self.bones = _FakeBoneCollection([SimpleNamespace(name=name) for name in bone_names])


class _FakeLightData:
    def __init__(self, name: str, light_type: str) -> None:
        self.name = name
        self.type = light_type
        self.energy = 0.0
        self.color = (1.0, 1.0, 1.0)
        self.spot_size = 0.0
        self.spot_blend = 0.0


class _FakeObject(_PropsMixin):
    def __init__(self, name: str, object_data: Any = None) -> None:
        super().__init__()
        self.name = name
        self.data = object_data
        self.type = (
            "LIGHT"
            if isinstance(object_data, _FakeLightData)
            else ("ARMATURE" if isinstance(object_data, _FakeArmature) else "EMPTY")
        )
        self.parent: Any = None
        self.parent_type = "OBJECT"
        self.parent_bone = ""
        self._location = _Vec3()
        self._rotation_euler = _Vec3()
        self.empty_display_type = "PLAIN_AXES"
        self.empty_display_size = 1.0
        self.matrix_world = _Mat4()
        self.selected = False

    @property
    def location(self) -> _Vec3:
        return self._location

    @location.setter
    def location(self, value: Any) -> None:
        self._location = value if isinstance(value, _Vec3) else _Vec3(*value)

    @property
    def rotation_euler(self) -> _Vec3:
        return self._rotation_euler

    @rotation_euler.setter
    def rotation_euler(self, value: Any) -> None:
        self._rotation_euler = value if isinstance(value, _Vec3) else _Vec3(*value)

    def evaluated_get(self, _depsgraph: Any) -> _FakeObject:
        self.matrix_world = _Mat4(
            self.location.x,
            self.location.y,
            self.location.z,
            self.rotation_euler.x,
            self.rotation_euler.y,
            self.rotation_euler.z,
        )
        return self

    def select_set(self, state: bool) -> None:
        self.selected = state


class _FakeCollectionList(list[Any]):
    def get(self, name: str, default: Any = None) -> Any:
        for item in self:
            if getattr(item, "name", None) == name:
                return item
        return default

    def link(self, item: Any) -> None:
        if item not in self:
            self.append(item)


class _FakeCollection(_PropsMixin):
    def __init__(self, name: str) -> None:
        super().__init__()
        self.name = name
        self.objects = _FakeCollectionList()
        self.children = _FakeCollectionList()


class _FakeRegistry:
    def __init__(self, factory: Any) -> None:
        self._items: dict[str, Any] = {}
        self._factory = factory

    def get(self, name: str, default: Any = None) -> Any:
        return self._items.get(name, default)

    def new(self, *args: Any, **kwargs: Any) -> Any:
        item = self._factory(*args, **kwargs)
        self._items[item.name] = item
        return item

    def __iter__(self) -> Any:
        return iter(self._items.values())

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __getitem__(self, name: str) -> Any:
        return self._items[name]


class _MockBpy:
    def __init__(self, fail_reg: bool = False) -> None:
        self.registered: list[Any] = []
        self.fail_reg = fail_reg

        def _make_obj(name: str, object_data: Any = None) -> _FakeObject:
            return _FakeObject(name, object_data)

        def _make_col(name: str) -> _FakeCollection:
            return _FakeCollection(name)

        def _make_light(name: str, type: str = "POINT") -> _FakeLightData:
            return _FakeLightData(name, type)

        objs = _FakeRegistry(_make_obj)
        cols = _FakeRegistry(_make_col)
        lights = _FakeRegistry(_make_light)
        self.data = SimpleNamespace(objects=objs, collections=cols, lights=lights)
        self.types = SimpleNamespace(Armature=_FakeArmature)
        self.ops = SimpleNamespace(
            object=SimpleNamespace(select_all=lambda action="DESELECT": None),
        )
        self.utils = SimpleNamespace(
            register_class=self._reg,
            unregister_class=self._unreg,
        )

    def _reg(self, cls: Any) -> None:
        if self.fail_reg:
            raise ValueError("already registered")
        self.registered.append(cls)

    def _unreg(self, cls: Any) -> None:
        if self.fail_reg:
            raise ValueError("not registered")
        if cls in self.registered:
            self.registered.remove(cls)


@dataclass
class _MockSceneProps:
    msfs_systems_cfg_path: str = ""
    msfs_spatial_cfg_path: str = ""
    msfs_spatial_status: str = ""
    msfs_configs: Any = field(
        default_factory=lambda: SimpleNamespace(attached_objects_cfg_path="", attachment_status="")
    )
    asset_name: str = "TestPlane"


def _make_context(mock_bpy: _MockBpy, props: _MockSceneProps) -> Any:
    root_col = _FakeCollection("Scene Collection")
    scene = SimpleNamespace(
        lod_tool=props,
        collection=root_col,
        objects=list(mock_bpy.data.objects),
        cursor=SimpleNamespace(location=_Vec3(1.0, 2.0, 3.0)),
    )
    return SimpleNamespace(
        scene=scene,
        active_object=None,
        active_pose_bone=None,
        evaluated_depsgraph_get=lambda: object(),
        view_layer=SimpleNamespace(update=lambda: None, objects=SimpleNamespace(active=None)),
        window_manager=SimpleNamespace(fileselect_add=lambda op: setattr(op, "_fileselect_called", True)),
    )


def _new_op(cls: Any) -> tuple[Any, list[tuple[set[str], str]]]:
    op = cls()
    reports: list[tuple[set[str], str]] = []
    op.report = lambda level, msg: reports.append((set(level), str(msg)))
    op.filepath = ""
    op.alias = "Instrument"
    op.attachment_path = ""
    op.attach_to_model = "Interior"
    return op, reports


def test_vehicle_lighting_collection_import_export_and_negative_paths(tmp_path: Path) -> None:
    """Exercise lights collection lookup, import optical conversion, mirror export, and error paths."""
    mock_bpy = _MockBpy()
    props = _MockSceneProps()
    ctx = _make_context(mock_bpy, props)

    with patch.object(vehicle_lighting_ops, "bpy", mock_bpy):
        assert vehicle_lighting_ops.find_lights_collection(ctx, "TestPlane") is None

        with patch("ui.utils.get_or_create_engine_import_collection", side_effect=RuntimeError("fallback")):
            li_col = vehicle_lighting_ops.get_or_create_lights_collection(ctx, "TestPlane")
            assert li_col is not None
            assert li_col.name == "TestPlane_Lights"

        found = vehicle_lighting_ops.find_lights_collection(ctx, "TestPlane")
        assert found is li_col

        # Negative import paths: missing path, invalid file parse failure, empty lights list
        imp_cls: Any = vehicle_lighting_ops.OMNIMESH_OT_import_msfs_lights

        op, reports = _new_op(imp_cls)
        assert op.execute(ctx) == {"CANCELLED"}
        assert "ERROR" in reports[-1][0]

        # Invoke locates systems.cfg sibling of spatial cfg
        spatial_cfg = tmp_path / "flight_model.cfg"
        spatial_cfg.write_text("[WEIGHT_AND_BALANCE]\n", encoding="utf-8")
        systems_cfg = tmp_path / "systems.cfg"
        systems_cfg.write_text(
            "[LIGHTS]\n"
            "lightdef.0 = Type:5#Index:0#LocalPosition:10,0,1#LocalRotation:0,0,0#EmMesh:MeshLanding\n"
            "lightdef.1 = Type:6#Index:1#LocalPosition:8,0,-1#LocalRotation:5,0,0\n"
            "lightdef.2 = Type:3#Index:2#LocalPosition:0,5,0#LocalRotation:0,0,0\n"
            "lightdef.3 = Type:3#Index:3#LocalPosition:0,-5,0#LocalRotation:0,0,0\n"
            "lightdef.4 = Type:3#Index:4#LocalPosition:-12,0,2#LocalRotation:0,0,0\n"
            "lightdef.5 = Type:2#Index:5#LocalPosition:-1,0,3#LocalRotation:0,0,0\n"
            "lightdef.6 = Type:1#Index:6#LocalPosition:0,0,4#LocalRotation:0,0,0\n",
            encoding="utf-8",
        )
        props.msfs_spatial_cfg_path = str(spatial_cfg)
        assert op.invoke(ctx, None) == {"RUNNING_MODAL"}
        assert op.filepath == str(systems_cfg)

        # Invoke falls back to fileselect when no sibling exists
        props.msfs_spatial_cfg_path = str(tmp_path / "missing_dir" / "flight_model.cfg")
        op_file, _ = _new_op(imp_cls)
        assert op_file.invoke(ctx, None) == {"RUNNING_MODAL"}
        assert getattr(op_file, "_fileselect_called", False) is True

        # Empty lights section triggers WARNING
        empty_cfg = tmp_path / "empty_systems.cfg"
        empty_cfg.write_text("[ELECTRICAL]\nbus.1 = Name:Main\n", encoding="utf-8")
        op_empty, reports_empty = _new_op(imp_cls)
        op_empty.filepath = str(empty_cfg)
        assert op_empty.execute(ctx) == {"CANCELLED"}
        assert "WARNING" in reports_empty[-1][0]

        # Valid import creates 7 lights including SPOT/POINT optical types & parents
        mock_bpy.data.objects.new("MeshLanding", None)
        mock_bpy.data.objects.new("Datum", None)
        op.filepath = str(systems_cfg)
        assert op.execute(ctx) == {"FINISHED"}
        assert props.msfs_spatial_status == "Imported 7 lights"
        assert len(li_col.objects) == 7

        # Re-importing with a flipped existing light type updates data.type in-place
        landing_obj = mock_bpy.data.objects["Light_MeshLanding"]
        landing_obj.data.type = "POINT"
        assert op.execute(ctx) == {"FINISHED"}
        assert landing_obj.data.type == "SPOT"

        # Export negative & positive paths (including _MIRRORED light insertion)
        exp_cls = vehicle_lighting_ops.OMNIMESH_OT_export_msfs_lights
        assert exp_cls.poll(ctx) is True
        exp_op, exp_reports = _new_op(exp_cls)

        mirrored = mock_bpy.data.objects.new("Light_Nav_Mir", _FakeLightData("Mir", "POINT"))
        mirrored["msfs_id"] = "LIGHTS:lightdef.2_MIRRORED"
        mirrored["msfs_key"] = "lightdef.2_mir"
        mirrored["msfs_light_type"] = 3
        mirrored["msfs_em_mesh"] = "WingTip_R"
        mirrored.location = _Vec3(1.5, 0.0, 0.0)
        li_col.objects.link(mirrored)

        ctx.scene.objects = list(mock_bpy.data.objects)
        assert exp_op.execute(ctx) == {"FINISHED"}
        assert "Synced 8 lights" in props.msfs_spatial_status
        assert mirrored["msfs_id"] == "LIGHTS:lightdef.7"
        assert math.isfinite(mirrored.location.x)

        # Export errors on missing file or no lights
        props.msfs_systems_cfg_path = str(tmp_path / "does_not_exist.cfg")
        assert exp_cls.poll(ctx) is False
        assert exp_op.execute(ctx) == {"CANCELLED"}
        assert "ERROR" in exp_reports[-1][0]

        # Parse failure and write failure branches
        props.msfs_systems_cfg_path = str(systems_cfg)
        with patch.object(vehicle_lighting_ops.MSFSCSTParser, "parse_file", side_effect=OSError("bad cfg")):
            assert exp_op.execute(ctx) == {"CANCELLED"}
        with patch.object(vehicle_lighting_ops.MSFSCSTParser, "serialize_and_save", side_effect=OSError("disk full")):
            assert exp_op.execute(ctx) == {"CANCELLED"}

        # Register / unregister idempotency
        vehicle_lighting_ops.register()
        assert len(mock_bpy.registered) == 2
        vehicle_lighting_ops.unregister()
        assert len(mock_bpy.registered) == 0


def test_vehicle_attachments_import_export_add_and_socket_resolution(tmp_path: Path) -> None:
    """Exercise attachments import, bone/socket lookup, sequential CFG export, add op, and failure modes."""
    mock_bpy = _MockBpy()
    props = _MockSceneProps()
    ctx = _make_context(mock_bpy, props)

    # Socket + Armature bone setup
    attach_empty = mock_bpy.data.objects.new("ATTACH_CANOPY_PANEL", None)
    arm_data = _FakeArmature(["RootBone", "PilotSocket"])
    arm_obj = mock_bpy.data.objects.new("AirframeArmature", arm_data)
    ctx.scene.objects = list(mock_bpy.data.objects)

    with (
        patch.object(vehicle_attachment_ops, "bpy", mock_bpy),
        patch.object(vehicle_attachment_ops, "resolve_effective_asset_name", return_value="TestPlane"),
    ):
        assert vehicle_attachment_ops.find_mounting_socket_node(ctx, "") == (None, None)
        assert vehicle_attachment_ops.find_mounting_socket_node(ctx, "attach_canopy_panel") == (attach_empty, None)
        assert vehicle_attachment_ops.find_mounting_socket_node(ctx, "pilotsocket") == (arm_obj, "PilotSocket")

        imp_cls = vehicle_attachment_ops.OMNIMESH_OT_import_msfs_attachments
        assert imp_cls.poll(ctx) is False
        imp_op, imp_reports = _new_op(imp_cls)
        assert imp_op.execute(ctx) == {"CANCELLED"}
        assert "ERROR" in imp_reports[-1][0]

        att_cfg = tmp_path / "attached_objects.cfg"
        att_cfg.write_text(
            "[SIM_ATTACHMENT.0]\n"
            "attachment_root = SimObjects\\Airplanes\\Test\\attachments\n"
            "attachment_file = model\\canopy.xml\n"
            "attach_to_model = Exterior\n"
            "attach_to_node = ATTACH_CANOPY_PANEL\n"
            "attach_offset = 1.0, 0.5, 0.2\n"
            "attach_pbh = 0.0, 0.0, 0.0\n"
            "attach_scale = 1.0\n"
            "always_execute_model_behavior = 0\n"
            "\n"
            "[SIM_ATTACHMENT.1]\n"
            "attachment_file = model\\tablet.xml\n"
            "attach_to_model = Interior\n"
            "attach_to_node = PilotSocket\n"
            "alias = EFB_Tablet\n"
            "attach_offset = 0.0, 0.0, 0.0\n"
            "attach_pbh = 5.0, 0.0, 10.0\n",
            encoding="utf-8",
        )
        props.msfs_configs.attached_objects_cfg_path = str(att_cfg)
        assert imp_cls.poll(ctx) is True

        # Empty attachments file finishes with 0 imported; parse failure cancels with ERROR
        empty_att = tmp_path / "empty_attached.cfg"
        empty_att.write_text("[OTHER]\nkey=1\n", encoding="utf-8")
        props.msfs_configs.attached_objects_cfg_path = str(empty_att)
        assert imp_op.execute(ctx) == {"FINISHED"}
        with patch.object(
            vehicle_attachment_ops.MSFSAttachmentsCST, "parse_attachments_file", side_effect=OSError("bad")
        ):
            assert imp_op.execute(ctx) == {"CANCELLED"}
            assert "ERROR" in imp_reports[-1][0]

        # Valid import creates exterior + interior collections & parents bone/socket
        props.msfs_configs.attached_objects_cfg_path = str(att_cfg)
        with patch("ui.utils.bpy", mock_bpy):
            assert imp_op.execute(ctx) == {"FINISHED"}
            assert "Imported 2 attachments" in props.msfs_configs.attachment_status

        ext_col = vehicle_attachment_ops.find_attachments_collection(ctx, "TestPlane", is_interior=False)
        int_col = vehicle_attachment_ops.find_attachments_collection(ctx, "TestPlane", is_interior=True)
        assert ext_col is not None and len(ext_col.objects) == 1
        assert int_col is not None and len(int_col.objects) == 1

        # Add attachment via active ATTACH_ object, pose bone, and cursor fallback
        add_cls = vehicle_attachment_ops.OMNIMESH_OT_add_vehicle_attachment
        add_op, _ = _new_op(add_cls)
        with patch("ui.utils.bpy", mock_bpy):
            ctx.active_object = attach_empty
            add_op.alias = "NewGauge"
            add_op.attach_to_model = "Exterior"
            assert add_op.execute(ctx) == {"FINISHED"}

            ctx.active_object = arm_obj
            ctx.active_pose_bone = SimpleNamespace(name="PilotSocket")
            add_op.alias = "BoneGauge"
            add_op.attach_to_model = "Interior"
            assert add_op.execute(ctx) == {"FINISHED"}

            ctx.active_object = None
            ctx.active_pose_bone = None
            add_op.alias = "CursorGauge"
            assert add_op.execute(ctx) == {"FINISHED"}

        # Export back to existing attached_objects.cfg assigns sequential sim_attachment.<idx>
        exp_cls = vehicle_attachment_ops.OMNIMESH_OT_export_msfs_attachments
        assert exp_cls.poll(ctx) is True
        exp_op, exp_reports = _new_op(exp_cls)
        assert exp_op.execute(ctx) == {"FINISHED"}
        assert "Synchronized 5 attachments" in props.msfs_configs.attachment_status

        # Export to a brand-new CFG path exercises MSFSAttachmentsCST.build_new_config branch
        new_cfg = tmp_path / "new_attached_objects.cfg"
        exp_op.filepath = str(new_cfg)
        assert exp_op.execute(ctx) == {"FINISHED"}
        assert new_cfg.is_file()

        # Negative export error paths
        exp_op.filepath = str(att_cfg)
        with patch.object(
            vehicle_attachment_ops.MSFSAttachmentsCST, "parse_attachments_file", side_effect=OSError("corrupt")
        ):
            assert exp_op.execute(ctx) == {"CANCELLED"}
            assert "ERROR" in exp_reports[-1][0]
        with patch.object(
            vehicle_attachment_ops.MSFSAttachmentsCST, "serialize_and_save", side_effect=OSError("readonly")
        ):
            assert exp_op.execute(ctx) == {"CANCELLED"}

        vehicle_attachment_ops.register()
        assert len(mock_bpy.registered) == 3
        vehicle_attachment_ops.unregister()
        assert len(mock_bpy.registered) == 0

    # Registration exception tolerance
    fail_bpy = _MockBpy(fail_reg=True)
    with patch.object(vehicle_lighting_ops, "bpy", fail_bpy), patch.object(vehicle_attachment_ops, "bpy", fail_bpy):
        vehicle_lighting_ops.register()
        vehicle_lighting_ops.unregister()
        vehicle_attachment_ops.register()
        vehicle_attachment_ops.unregister()
