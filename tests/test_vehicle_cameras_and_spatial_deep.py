"""Deep headless test suite for ui/vehicle_camera_ops.py."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ui import vehicle_camera_ops


class _Vec3:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)


class _Mat4:
    def __init__(self, tx: float = 0.0, ty: float = 0.0, tz: float = 0.0) -> None:
        self.translation = _Vec3(tx, ty, tz)

    def inverted(self) -> _Mat4:
        return _Mat4(-self.translation.x, -self.translation.y, -self.translation.z)

    def __matmul__(self, other: _Mat4) -> _Mat4:
        return _Mat4(
            self.translation.x + other.translation.x,
            self.translation.y + other.translation.y,
            self.translation.z + other.translation.z,
        )


class _FakeColList(list[Any]):
    def get(self, name: str, default: Any = None) -> Any:
        for item in self:
            if getattr(item, "name", None) == name:
                return item
        return default

    def link(self, item: Any) -> None:
        if item not in self:
            self.append(item)


class _FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.objects = _FakeColList()
        self.children = _FakeColList()
        self._props: dict[str, Any] = {}

    def get(self, k: str, default: Any = None) -> Any:
        return self._props.get(k, default)

    def __setitem__(self, k: str, v: Any) -> None:
        self._props[k] = v


class _FakeCamData:
    def __init__(self, name: str) -> None:
        self.name = name
        self.lens = 35.0
        self.clip_start = 0.1
        self.clip_end = 100.0


class _FakeObject:
    def __init__(self, name: str, object_data: Any = None) -> None:
        self.name = name
        self.data = object_data
        self.type = "CAMERA" if isinstance(object_data, _FakeCamData) else "EMPTY"
        self.parent: Any = None
        self._location = _Vec3()
        self._rotation_euler = _Vec3()
        self.empty_display_type = "PLAIN_AXES"
        self.empty_display_size = 1.0
        self.matrix_world = _Mat4()
        self.matrix_local = _Mat4()
        self._props: dict[str, Any] = {}

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

    def get(self, k: str, default: Any = None) -> Any:
        return self._props.get(k, default)

    def __setitem__(self, k: str, v: Any) -> None:
        self._props[k] = v

    def __getitem__(self, k: str) -> Any:
        return self._props[k]

    def evaluated_get(self, _depsgraph: Any) -> _FakeObject:
        self.matrix_world = _Mat4(self._location.x, self._location.y, self._location.z)
        return self


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
        self.data = SimpleNamespace(
            objects=_FakeRegistry(lambda n, d=None: _FakeObject(n, d)),
            collections=_FakeRegistry(lambda n: _FakeCollection(n)),
            cameras=_FakeRegistry(lambda name: _FakeCamData(name)),
        )
        self.utils = SimpleNamespace(register_class=self._reg, unregister_class=self._unreg)

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
class _MockCamProps:
    msfs_cameras_cfg_path: str = ""
    msfs_spatial_status: str = ""
    export_base_name: str = "TestPlane"
    active_asset: str = "TestPlane"


def _make_context(mock_bpy: _MockBpy, props: _MockCamProps) -> Any:
    root_col = _FakeCollection("Scene Collection")
    scene_props: dict[str, Any] = {}
    r3d = SimpleNamespace(view_perspective="PERSP", view_matrix=_Mat4(1.0, 2.0, 3.0))
    space = SimpleNamespace(type="VIEW_3D", region_3d=r3d)
    area = SimpleNamespace(type="VIEW_3D", spaces=[space])
    screen = SimpleNamespace(areas=[area])

    class _MockScene:
        def __init__(self) -> None:
            self.lod_tool = props
            self.collection = root_col
            self.objects: list[Any] = []
            self.camera: Any = None

        def get(self, k: str, default: Any = None) -> Any:
            return scene_props.get(k, default)

        def __contains__(self, k: object) -> bool:
            return k in scene_props

        def __setitem__(self, k: str, v: Any) -> None:
            scene_props[k] = v

        def __getitem__(self, k: str) -> Any:
            return scene_props[k]

        def __delitem__(self, k: str) -> None:
            del scene_props[k]

    return SimpleNamespace(
        scene=_MockScene(),
        active_object=None,
        screen=screen,
        evaluated_depsgraph_get=lambda: object(),
        view_layer=SimpleNamespace(update=lambda: None, objects=SimpleNamespace(active=None)),
        window_manager=SimpleNamespace(fileselect_add=lambda op: setattr(op, "_fileselect_called", True)),
    )


def _new_op(cls: Any) -> tuple[Any, list[tuple[set[str], str]]]:
    op = cls()
    reports: list[tuple[set[str], str]] = []
    op.report = lambda lvl, msg: reports.append((set(lvl), str(msg)))
    op.filepath = ""
    return op, reports


def test_vehicle_cameras_import_export_look_restore_align_and_errors(tmp_path: Path) -> None:
    """Exercise camera collections, cameras.cfg import/export roundtrip, viewport look/align/restore, and error paths."""
    mock_bpy = _MockBpy()
    props = _MockCamProps()
    ctx = _make_context(mock_bpy, props)

    with patch.object(vehicle_camera_ops, "bpy", mock_bpy):
        assert vehicle_camera_ops.find_cameras_collection(ctx, "TestPlane") is None

        # Fallback hierarchy creation when ui.utils.get_or_create_engine_import_collection fails
        with patch("ui.utils.get_or_create_engine_import_collection", side_effect=RuntimeError("fallback")):
            cam_col = vehicle_camera_ops.get_or_create_cameras_collection(ctx, "TestPlane", is_interior=False)
            assert cam_col is not None and cam_col.name == "TestPlane_Cameras"
        assert vehicle_camera_ops.find_cameras_collection(ctx, "TestPlane") is cam_col

        # Import missing path -> ERROR; invoke opens fileselect if no path yet
        imp_cls: Any = vehicle_camera_ops.OMNIMESH_OT_import_msfs_cameras
        assert imp_cls.poll(ctx) is True
        imp_op, imp_reports = _new_op(imp_cls)
        assert imp_op.invoke(ctx, None) == {"RUNNING_MODAL"}
        assert getattr(imp_op, "_fileselect_called", False) is True
        assert imp_op.execute(ctx) == {"CANCELLED"}
        assert "ERROR" in imp_reports[-1][0]

        # Valid cameras.cfg with VC + External cameras
        cam_cfg = tmp_path / "cameras.cfg"
        cam_cfg.write_text(
            "[VIEWS]\n"
            "eyepoint = -3.9, -0.85, 2.1\n\n"
            "[CAMERADEFINITION.0]\n"
            'Title="Pilot"\n'
            "Guid={11111111-1111-1111-1111-111111111111}\n"
            'Origin="Virtual Cockpit"\n'
            'Category="Cockpit"\n'
            'SubCategory="Pilot"\n'
            "InitialZoom=0.35\n"
            "InitialXyz=0.0, 0.05, 0.1\n"
            "InitialPbh=0, 0, 0\n\n"
            "[CAMERADEFINITION.1]\n"
            'Title="WingLeft"\n'
            "Guid={22222222-2222-2222-2222-222222222222}\n"
            'Origin="Center"\n'
            'Category="FixedOnPlane"\n'
            'SubCategory="FixedOnPlaneExtern"\n'
            "InitialZoom=0.6\n"
            "InitialXyz=-4.0, 0.5, -1.0\n"
            "InitialPbh=5, 0, 90\n",
            encoding="utf-8",
        )
        props.msfs_cameras_cfg_path = str(cam_cfg)
        mock_bpy.data.objects.new("Datum", None)
        with patch("ui.utils.bpy", mock_bpy):
            assert imp_op.invoke(ctx, None) == {"FINISHED"}
        assert props.msfs_spatial_status == "Imported 2 cameras"

        # Parse error branch during import
        with patch.object(vehicle_camera_ops.MSFSCSTParser, "parse_cameras_file", side_effect=OSError("bad cam")):
            assert imp_op.execute(ctx) == {"CANCELLED"}
            assert "ERROR" in imp_reports[-1][0]

        # Look-through, align to view, and restore camera operators
        orig_scene_cam = mock_bpy.data.objects.new("MainCamera", _FakeCamData("MainCamera"))
        ctx.scene.camera = orig_scene_cam
        vc_cam = mock_bpy.data.objects["Cam_0_Pilot"]
        ctx.active_object = vc_cam

        look_cls: Any = vehicle_camera_ops.OMNIMESH_OT_look_through_vehicle_camera
        align_cls: Any = vehicle_camera_ops.OMNIMESH_OT_align_vehicle_camera_to_view
        restore_cls: Any = vehicle_camera_ops.OMNIMESH_OT_restore_scene_camera

        assert look_cls.poll(ctx) is True
        look_op, _ = _new_op(look_cls)
        assert look_op.execute(ctx) == {"FINISHED"}
        assert ctx.scene.camera is vc_cam
        assert ctx.screen.areas[0].spaces[0].region_3d.view_perspective == "CAMERA"

        assert align_cls.poll(ctx) is True
        align_op, _ = _new_op(align_cls)
        assert align_op.execute(ctx) == {"FINISHED"}

        # Missing 3D viewport error branch on align
        ctx_no_screen = SimpleNamespace(active_object=vc_cam, screen=None)
        align_op_err, align_reports = _new_op(align_cls)
        assert align_op_err.execute(ctx_no_screen) == {"CANCELLED"}
        assert "ERROR" in align_reports[-1][0]

        assert restore_cls.poll(ctx) is True
        restore_op, _ = _new_op(restore_cls)
        assert restore_op.execute(ctx) == {"FINISHED"}
        assert ctx.scene.camera is orig_scene_cam
        assert ctx.screen.areas[0].spaces[0].region_3d.view_perspective == "PERSP"

        # Export roundtrip + error paths
        exp_cls: Any = vehicle_camera_ops.OMNIMESH_OT_export_msfs_cameras
        assert exp_cls.poll(ctx) is True
        exp_op, exp_reports = _new_op(exp_cls)
        ctx.scene.objects = list(mock_bpy.data.objects)
        assert exp_op.execute(ctx) == {"FINISHED"}
        assert "Synced 2 cameras" in props.msfs_spatial_status

        with patch.object(
            vehicle_camera_ops.MSFSCSTParser, "serialize_and_save_cameras", side_effect=OSError("disk full")
        ):
            assert exp_op.execute(ctx) == {"CANCELLED"}
            assert "ERROR" in exp_reports[-1][0]

        ctx.scene.objects = []
        mock_bpy.data.objects._items.clear()
        assert exp_op.execute(ctx) == {"CANCELLED"}
        assert "WARNING" in exp_reports[-1][0]

        props.msfs_cameras_cfg_path = ""
        assert exp_cls.poll(ctx) is False
        assert exp_op.execute(ctx) == {"CANCELLED"}

        vehicle_camera_ops.register()
        assert len(mock_bpy.registered) == 5
        vehicle_camera_ops.unregister()
        assert len(mock_bpy.registered) == 0
