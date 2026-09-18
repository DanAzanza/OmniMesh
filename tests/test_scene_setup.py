"""
Unit tests for OmniMesh Scene Setup & Asset Hierarchy Module (core/scene_setup.py).
"""

from __future__ import annotations

from typing import Any

from core.scene_setup import (
    COLLECTION_COLOR_TAGS,
    assign_objects_to_asset_hierarchy,
    configure_game_scene_settings,
    sanitize_asset_name,
    setup_asset_collections,
)


class DummyUnitSettings:
    def __init__(self):
        self.system = "NONE"
        self.scale_length = 0.001
        self.length_unit = "NONE"


class DummyRender:
    def __init__(self):
        self.fps = 24
        self.fps_base = 1.0


class DummyScene:
    def __init__(self):
        self.unit_settings = DummyUnitSettings()
        self.render = DummyRender()
        self.collection = DummyCollection("Scene Collection")


class DummyOverlay:
    def __init__(self):
        self.show_stats = False
        self.show_face_orientation = False


class DummyShading:
    def __init__(self):
        self.show_cavity = False
        self.cavity_type = "SCREEN"
        self.show_backface_culling = False


class DummySpaceView3D:
    def __init__(self):
        self.type = "VIEW_3D"
        self.clip_start = 0.1
        self.clip_end = 100.0
        self.overlay = DummyOverlay()
        self.shading = DummyShading()


class DummyArea:
    def __init__(self, spaces: list[Any] | None = None):
        self.type = "VIEW_3D"
        self.spaces = spaces if spaces is not None else [DummySpaceView3D()]


class DummyScreen:
    def __init__(self, areas: list[Any] | None = None):
        self.areas = areas if areas is not None else [DummyArea()]


class DummyWindow:
    def __init__(self, screen: Any | None = None):
        self.screen = screen or DummyScreen()


class DummyWindowManager:
    def __init__(self, windows: list[Any] | None = None):
        self.windows = windows if windows is not None else [DummyWindow()]


class DummyContext:
    def __init__(self, scene: Any | None = None, wm: Any | None = None):
        self.scene = scene or DummyScene()
        self.window_manager = wm or DummyWindowManager()


class DummyCollection:
    def __init__(self, name: str):
        self.name = name
        self.children = DummyCollectionChildren(self)
        self.objects = DummyCollectionObjects(self)
        self.color_tag = "NONE"
        self._custom_props: dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any):
        self._custom_props[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._custom_props[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom_props.get(key, default)


class DummyCollectionChildren:
    def __init__(self, parent: DummyCollection):
        self.parent = parent
        self._items: dict[str, DummyCollection] = {}

    def link(self, col: DummyCollection):
        self._items[col.name] = col

    def unlink(self, col: DummyCollection):
        self._items.pop(col.name, None)

    def get(self, name: str, default: Any = None) -> Any:
        return self._items.get(name, default)

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __iter__(self):
        return iter(self._items.values())


class DummyCollectionObjects:
    def __init__(self, col: DummyCollection):
        self.col = col
        self._objs: dict[str, Any] = {}

    def link(self, obj: Any):
        self._objs[obj.name] = obj
        if hasattr(obj, "users_collection") and self.col not in obj.users_collection:
            obj.users_collection.append(self.col)

    def unlink(self, obj: Any):
        self._objs.pop(obj.name, None)
        if hasattr(obj, "users_collection") and self.col in obj.users_collection:
            obj.users_collection.remove(self.col)

    def __contains__(self, name: str) -> bool:
        return name in self._objs

    def __iter__(self):
        return iter(self._objs.values())


class DummyObject:
    def __init__(self, name: str, obj_type: str = "MESH", library: Any = None):
        self.name = name
        self.type = obj_type
        self.library = library
        self.users_collection: list[DummyCollection] = []


class DummyCollectionsDict:
    def __init__(self):
        self._cols: dict[str, DummyCollection] = {}

    def get(self, name: str, default: Any = None) -> Any:
        return self._cols.get(name, default)

    def new(self, name: str) -> DummyCollection:
        col = DummyCollection(name)
        self._cols[name] = col
        return col

    def __contains__(self, name: str) -> bool:
        return name in self._cols

    def __iter__(self):
        return iter(self._cols.values())


class DummyBpyData:
    def __init__(self):
        self.collections = DummyCollectionsDict()


class DummyBpy:
    def __init__(self):
        self.data = DummyBpyData()


# =========================================================================
# TESTS
# =========================================================================


def test_sanitize_asset_name():
    assert sanitize_asset_name("MyVehicle.001") == "MyVehicle"
    assert sanitize_asset_name("FighterJet_LOD0") == "FighterJet"
    assert sanitize_asset_name("FighterJet_LOD1.002") == "FighterJet"
    assert sanitize_asset_name("SportsCar_Colliders") == "SportsCar"
    assert sanitize_asset_name("Airplane_Helpers") == "Airplane"
    assert sanitize_asset_name("Helicopter_Config") == "Helicopter"
    assert sanitize_asset_name("Asset With Spaces & Symbols!") == "Asset_With_Spaces_Symbols"
    assert sanitize_asset_name("") == "Asset"
    assert sanitize_asset_name("   ") == "Asset"


def test_configure_game_scene_settings_headless():
    scene = DummyScene()
    res = configure_game_scene_settings(scene, context=None)

    assert res["scene_configured"] is True
    assert res["viewports_updated"] == 0
    assert scene.unit_settings.system == "METRIC"
    assert scene.unit_settings.scale_length == 1.0
    assert scene.unit_settings.length_unit == "METERS"
    assert scene.render.fps == 60
    assert scene.render.fps_base == 1.0


def test_configure_game_scene_settings_with_viewports():
    scene = DummyScene()
    space = DummySpaceView3D()
    area = DummyArea(spaces=[space])
    screen = DummyScreen(areas=[area])
    wm = DummyWindowManager(windows=[DummyWindow(screen=screen)])
    ctx = DummyContext(scene=scene, wm=wm)

    res = configure_game_scene_settings(
        scene,
        clip_start=0.05,
        clip_end=1000.0,
        enable_stats=True,
        enable_cavity=True,
        enable_backface_culling=True,
        context=ctx,
    )

    assert res["scene_configured"] is True
    assert res["viewports_updated"] == 1
    assert space.clip_start == 0.05
    assert space.clip_end == 1000.0
    assert space.overlay.show_stats is True
    assert space.shading.show_cavity is True
    assert space.shading.cavity_type == "BOTH"
    assert space.shading.show_backface_culling is True


def test_setup_asset_collections_hierarchy():
    dummy_bpy = DummyBpy()
    scene = DummyScene()
    ctx = DummyContext(scene=scene)

    colls = setup_asset_collections(
        ctx,
        "SuperCar",
        create_lod0=True,
        create_colliders=True,
        create_helpers=True,
        create_config=True,
        apply_color_tags=True,
        bpy_module=dummy_bpy,
    )

    assert "root" in colls
    assert "lod0" in colls
    assert "colliders" in colls
    assert "helpers" in colls
    assert "config" in colls

    root = colls["root"]
    assert root.name == "SuperCar"
    assert root["_omnimesh_role"] == "MODEL_ROOT"
    assert root.color_tag == COLLECTION_COLOR_TAGS["ROOT"]
    assert "SuperCar" in scene.collection.children

    lod0 = colls["lod0"]
    assert lod0.name == "SuperCar_LOD0"
    assert lod0["_omnimesh_role"] == "LOD0"
    assert lod0.color_tag == COLLECTION_COLOR_TAGS["LOD0"]
    assert "SuperCar_LOD0" in root.children

    colliders = colls["colliders"]
    assert colliders.name == "SuperCar_Colliders"
    assert colliders["_omnimesh_role"] == "COLLIDERS"
    assert colliders.color_tag == COLLECTION_COLOR_TAGS["COLLIDERS"]
    assert "SuperCar_Colliders" in root.children

    helpers = colls["helpers"]
    assert helpers.name == "SuperCar_Helpers"
    assert helpers["_omnimesh_role"] == "HELPERS"
    assert helpers.color_tag == COLLECTION_COLOR_TAGS["HELPERS"]
    assert "SuperCar_Helpers" in root.children

    config = colls["config"]
    assert config.name == "SuperCar_Config"
    assert config["_omnimesh_role"] == "CONFIG"
    assert config.color_tag == COLLECTION_COLOR_TAGS["CONFIG"]
    assert "SuperCar_Config" in root.children


def test_assign_objects_to_asset_hierarchy():
    dummy_bpy = DummyBpy()
    scene = DummyScene()
    ctx = DummyContext(scene=scene)

    colls = setup_asset_collections(
        ctx,
        "Drone",
        create_lod0=True,
        create_colliders=True,
        create_helpers=True,
        create_config=True,
        bpy_module=dummy_bpy,
    )

    # Prepare loose objects in scene collection
    initial_col = DummyCollection("Collection")
    mesh1 = DummyObject("Body", "MESH")
    mesh2 = DummyObject("Propeller", "MESH")
    armature = DummyObject("Drone_Rig", "ARMATURE")
    socket_empty = DummyObject("SOCKET_Camera", "EMPTY")
    guide_empty = DummyObject("Reference_Image", "EMPTY")
    camera = DummyObject("Main_Camera", "CAMERA")
    lib_obj = DummyObject("ExternalMesh", "MESH", library="external.blend")
    curve_obj = DummyObject("PathCurve", "CURVE")

    for obj in [mesh1, mesh2, armature, socket_empty, guide_empty, camera, lib_obj, curve_obj]:
        initial_col.objects.link(obj)

    selected = [mesh1, mesh2, armature, socket_empty, guide_empty, camera, lib_obj, curve_obj]
    summary = assign_objects_to_asset_hierarchy(selected, colls, scene=scene, unlink_from_others=True)

    # 1. Meshes and Sockets go to LOD0
    assert "Body" in summary["moved_to_lod0"]
    assert "Propeller" in summary["moved_to_lod0"]
    assert "SOCKET_Camera" in summary["moved_to_lod0"]
    assert "Body" in colls["lod0"].objects
    assert "Propeller" in colls["lod0"].objects
    assert "SOCKET_Camera" in colls["lod0"].objects

    # 2. Armatures stay at Root (SharedRigAnchor)
    assert "Drone_Rig" in summary["moved_to_root"]
    assert "Drone_Rig" in colls["root"].objects
    assert "Drone_Rig" not in colls["lod0"].objects

    # 3. Reference empties go to Helpers
    assert "Reference_Image" in summary["moved_to_helpers"]
    assert "Reference_Image" in colls["helpers"].objects

    # 4. Cameras go to Config
    assert "Main_Camera" in summary["moved_to_config"]
    assert "Main_Camera" in colls["config"].objects

    # 5. Library objects are skipped safely
    assert "ExternalMesh" in summary["skipped_library"]
    assert "ExternalMesh" not in colls["lod0"].objects

    # 6. Curves/unsupported are skipped safely
    assert "PathCurve" in summary["skipped_unsupported"]
    assert "PathCurve" not in colls["lod0"].objects

    # 7. Unlink hygiene: moved objects are unlinked from initial_col
    assert "Body" not in initial_col.objects
    assert "Propeller" not in initial_col.objects
    assert "Drone_Rig" not in initial_col.objects
    # Skipped objects remain in initial_col
    assert "ExternalMesh" in initial_col.objects
    assert "PathCurve" in initial_col.objects
