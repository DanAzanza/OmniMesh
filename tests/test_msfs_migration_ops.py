from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from ui.msfs_migration_ops import OMNIMESH_OT_convert_asobo_hierarchy


class MockCollection:
    def __init__(self, name: str):
        self.name = name
        self.objects: list[Any] = []
        self.children: list[Any] = []

    def link(self, obj: Any) -> None:
        if obj not in self.objects:
            self.objects.append(obj)

    def unlink(self, obj: Any) -> None:
        if obj in self.objects:
            self.objects.remove(obj)


class MockObject:
    def __init__(self, name: str, obj_type: str = "MESH"):
        self.name = name
        self.type = obj_type


def test_asobo_migration_poll_false_when_no_collections():
    mock_bpy = MagicMock()
    mock_bpy.data.collections = []
    with patch("ui.msfs_migration_ops.bpy", mock_bpy):
        context = MagicMock()
        assert not OMNIMESH_OT_convert_asobo_hierarchy.poll(context)


def test_asobo_migration_poll_true_when_x0_exists():
    mock_bpy = MagicMock()
    c1 = MockCollection("x0_Cessna172")
    mock_bpy.data.collections = [c1]
    with patch("ui.msfs_migration_ops.bpy", mock_bpy):
        context = MagicMock()
        assert OMNIMESH_OT_convert_asobo_hierarchy.poll(context)


def test_asobo_migration_execution():
    mock_bpy = MagicMock()
    coll_x0 = MockCollection("x0_DA62")
    coll_x1 = MockCollection("x1_DA62")

    mesh_lod0 = MockObject("fuselage", "MESH")
    attach_light = MockObject("ATTACH_POINT_light_beacon", "EMPTY")
    mesh_lod1 = MockObject("fuselage_lod1", "MESH")

    coll_x0.objects = [mesh_lod0, attach_light]
    coll_x1.objects = [mesh_lod1]

    mock_bpy.data.collections = [coll_x0, coll_x1]

    op = OMNIMESH_OT_convert_asobo_hierarchy()
    op.report = MagicMock()
    context = MagicMock()

    # Track target collections created
    created_colls: dict[str, MockCollection] = {}

    def mock_get_or_create(ctx, asset_name, role, *args, **kwargs):
        role_upper = role.upper()
        if role_upper == "ROOT":
            cname = asset_name
        elif role_upper == "CONFIG":
            cname = f"{asset_name}_Config"
        elif role_upper == "HELPERS":
            cname = f"{asset_name}_Helpers"
        elif role_upper == "LOD0":
            cname = f"{asset_name}_LOD0"
        elif role_upper == "LOD1":
            cname = f"{asset_name}_LOD1"
        else:
            cname = f"{asset_name}_{role}"

        if cname not in created_colls:
            created_colls[cname] = MockCollection(cname)
        return created_colls[cname]

    with (
        patch("ui.msfs_migration_ops.bpy", mock_bpy),
        patch("ui.msfs_migration_ops.get_or_create_engine_import_collection", side_effect=mock_get_or_create),
    ):
        res = op.execute(context)
        assert res == {"FINISHED"}

        # Attachment point should be in HELPERS
        helpers = created_colls.get("DA62_Helpers")
        assert helpers is not None
        assert attach_light in helpers.objects

        # Mesh should be in LOD0
        lod0 = created_colls.get("DA62_LOD0")
        assert lod0 is not None
        assert mesh_lod0 in lod0.objects

        # LOD1 mesh should be in LOD1
        lod1 = created_colls.get("DA62_LOD1")
        assert lod1 is not None
        assert mesh_lod1 in lod1.objects
