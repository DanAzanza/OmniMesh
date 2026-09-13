from __future__ import annotations

import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

from exporters.engine_export import AssetMeshResolver, AssetExportPayload
from exporters.msfs_export import MSFSExporter


class MockObject:
    def __init__(self, name: str, obj_type: str = "MESH"):
        self.name = name
        self.type = obj_type
        self.hide_viewport = False
        self._hidden_layer = False
        self._selected = False
        self.data = MagicMock()
        self.data.polygons = [1, 2, 3]

    def hide_get(self, view_layer=None):
        return self._hidden_layer

    def hide_set(self, val, view_layer=None):
        self._hidden_layer = val

    def select_set(self, val):
        self._selected = val

    def get(self, key, default=None):
        return default


class MockChildrenDict:
    def __init__(self, colls: list[Any]):
        self._colls = {c.name: c for c in colls}

    def get(self, key: str, default=None):
        return self._colls.get(key, default)

    def __iter__(self):
        return iter(self._colls.values())

    def __contains__(self, key: str):
        return key in self._colls


class MockCollection:
    def __init__(self, name: str):
        self.name = name
        self.objects: list[Any] = []
        self.children = MockChildrenDict([])


class MockCollectionDict:
    def __init__(self, colls: list[MockCollection]):
        self._colls = {c.name: c for c in colls}

    def get(self, key: str, default=None):
        return self._colls.get(key, default)

    def __iter__(self):
        return iter(self._colls.values())


def test_asset_mesh_resolver_includes_attachment_nodes():
    """Verify that attachment empties in _Helpers are collected into attachment_nodes."""
    mock_bpy = MagicMock()

    root_coll = MockCollection("C172")
    lod0_coll = MockCollection("C172_LOD0")
    helpers_coll = MockCollection("C172_Helpers")

    mesh0 = MockObject("fuselage_lod0", "MESH")
    lod0_coll.objects = [mesh0]

    att_point = MockObject("ATTACH_POINT_light_beacon", "EMPTY")
    fx_point = MockObject("ATTACH_FX_smoke", "EMPTY")
    socket_point = MockObject("SOCKET_pilot_seat", "EMPTY")
    eye_point = MockObject("EYE_pilot", "EMPTY")
    random_empty = MockObject("random_guide", "EMPTY")

    helpers_coll.objects = [att_point, fx_point, socket_point, eye_point, random_empty]

    root_coll.children = MockChildrenDict([lod0_coll, helpers_coll])
    mock_bpy.data.collections = MockCollectionDict([root_coll, lod0_coll, helpers_coll])

    context = MagicMock()
    with patch("exporters.engine_export.bpy", mock_bpy):
        payload = AssetMeshResolver.resolve_payload(context, "C172")

        # Geometry tier 0 should contain only mesh
        assert 0 in payload.lod_tiers
        assert mesh0 in payload.lod_tiers[0]
        assert att_point not in payload.lod_tiers[0]

        # Attachment nodes should contain the 4 recognized attachment empties
        assert len(payload.attachment_nodes) == 4
        assert att_point in payload.attachment_nodes
        assert fx_point in payload.attachment_nodes
        assert socket_point in payload.attachment_nodes
        assert eye_point in payload.attachment_nodes
        assert random_empty not in payload.attachment_nodes


def test_msfs_export_selects_attachment_nodes_for_lod0():
    """Verify that MSFSExporter unhides and selects attachment nodes for LOD0 glTF export."""
    mock_bpy = MagicMock()

    mesh0 = MockObject("airframe_lod0", "MESH")
    att_node = MockObject("ATTACH_POINT_wing_strobe", "EMPTY")

    payload = AssetExportPayload(
        asset_name="TestPlane",
        lod_tiers={0: [mesh0]},
        attachment_nodes=[att_node],
    )

    context = MagicMock()
    context.view_layer.objects.active = None
    mock_gltf = MagicMock()
    mock_bpy.ops.export_scene.gltf = mock_gltf

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("exporters.msfs_export.bpy", mock_bpy),
            patch("exporters.engine_export.AssetMeshResolver.resolve_payload", return_value=payload),
        ):
            ok, msg = MSFSExporter.export_asset(context, tmpdir, "TestPlane")
            assert ok
            assert "MSFS package (1 LOD tiers) exported" in msg

            # Check that att_node was selected for export
            assert att_node._selected is True
            assert att_node.hide_viewport is False
            assert att_node._hidden_layer is False

            # Verify glTF export was called
            assert mock_gltf.called
