"""
Unit tests for OmniMesh Multi-Convex Collision Hull Generator & Physics Decomposition Engine.
"""

from __future__ import annotations

import math
import numpy as np

from core.collision import CollisionDecomposer, CollisionManager


def test_pca_splitting_plane_basic():
    # Coords forming a symmetric 3D rectangular box elongated along X axis
    coords = np.array(
        [
            [-5.0, -1.0, -1.0],
            [5.0, -1.0, -1.0],
            [-5.0, 1.0, -1.0],
            [5.0, 1.0, -1.0],
            [-5.0, -1.0, 1.0],
            [5.0, -1.0, 1.0],
            [-5.0, 1.0, 1.0],
            [5.0, 1.0, 1.0],
        ],
        dtype=np.float64,
    )
    centroid, normal = CollisionDecomposer.compute_pca_splitting_plane(coords)

    # Centroid should be exactly (0.0, 0.0, 0.0)
    assert math.isclose(centroid.x, 0.0, abs_tol=1e-3)
    assert math.isclose(centroid.y, 0.0, abs_tol=1e-3)
    assert math.isclose(centroid.z, 0.0, abs_tol=1e-3)

    # Normal should be unit length
    assert math.isclose(normal.length, 1.0, rel_tol=1e-3)
    # Principal axis of variance is X axis -> normal should be parallel to (1, 0, 0)
    assert abs(normal.x) > 0.9


def test_pca_splitting_plane_edge_cases():
    # Empty coords
    c_empty, n_empty = CollisionDecomposer.compute_pca_splitting_plane(np.zeros((0, 3)))
    assert c_empty.length == 0.0
    assert math.isclose(n_empty.length, 1.0, rel_tol=1e-3)

    # Single point
    coords_one = np.array([[1.0, 2.0, 3.0]])
    c_one, n_one = CollisionDecomposer.compute_pca_splitting_plane(coords_one)
    assert math.isclose(c_one.x, 1.0)
    assert math.isclose(c_one.y, 2.0)
    assert math.isclose(c_one.z, 3.0)
    assert math.isclose(n_one.length, 1.0, rel_tol=1e-3)


def test_measure_hull_concavity_null_safety():
    assert CollisionDecomposer.measure_hull_concavity(None, None) == 0.0


def test_harden_convex_hull_null_and_empty():
    assert CollisionDecomposer.harden_convex_hull(None, 32) is False


def test_decompose_mesh_null_safety():
    assert CollisionDecomposer.decompose_mesh_to_hulls(None, 4) == []


def test_map_collider_name_for_engine():
    base = "FighterJet"

    # UE5
    assert CollisionManager.map_collider_name_for_engine(base, 1, "UE5") == "UCX_FighterJet_01"
    assert CollisionManager.map_collider_name_for_engine(base, 12, "UE5") == "UCX_FighterJet_12"

    # Godot 4
    assert CollisionManager.map_collider_name_for_engine(base, 1, "GODOT_4") == "FighterJet_Collider_01-convcol"
    assert CollisionManager.map_collider_name_for_engine(base, 5, "GODOT_4") == "FighterJet_Collider_05-convcol"

    # Unity 6
    assert CollisionManager.map_collider_name_for_engine(base, 1, "UNITY_6") == "FighterJet_Collider_01"

    # MSFS 2024
    assert CollisionManager.map_collider_name_for_engine(base, 1, "MSFS_2024") == "FighterJet_Collider_01"


def test_collision_manager_null_mesh_objs():
    assert CollisionManager.generate_colliders_for_objects([], "Test") == []
    assert CollisionManager.remove_colliders_for_objects([], "Test") == 0


def test_get_lod0_mesh_objects_multi_collection(monkeypatch):
    """Verify get_lod0_mesh_objects gathers all meshes in asset collection even when only one is selected."""
    from unittest.mock import MagicMock
    import ui.utils as ui_utils
    from ui.utils import get_lod0_mesh_objects

    mock_bpy = MagicMock()
    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)

    # Setup collection "SM_Car" with 3 LOD0 parts and 1 collider
    chassis = MagicMock()
    chassis.name = "SM_Car_Chassis"
    chassis.type = "MESH"
    chassis.get.return_value = False

    wheel_fl = MagicMock()
    wheel_fl.name = "SM_Car_Wheel_FL"
    wheel_fl.type = "MESH"
    wheel_fl.get.return_value = False

    wheel_fr = MagicMock()
    wheel_fr.name = "SM_Car_Wheel_FR"
    wheel_fr.type = "MESH"
    wheel_fr.get.return_value = False

    collider = MagicMock()
    collider.name = "SM_Car_Collider_01"
    collider.type = "MESH"
    collider.get.return_value = True  # _is_collider = True

    mock_coll = MagicMock()
    mock_coll.name = "SM_Car"
    mock_coll.objects = [chassis, wheel_fl, wheel_fr, collider]

    mock_bpy.data.collections.get.side_effect = lambda name: mock_coll if name in {"SM_Car", "SM_Car_LOD0"} else None

    # Context has only chassis selected!
    mock_context = MagicMock()
    mock_context.scene.lod_tool.export_base_name = "SM_Car"
    mock_context.active_object = chassis
    mock_context.selected_objects = [chassis]

    results = get_lod0_mesh_objects(mock_context, "SM_Car")

    # All 3 mesh parts must be gathered, and the collider must be excluded!
    assert len(results) == 3
    assert chassis in results
    assert wheel_fl in results
    assert wheel_fr in results
    assert collider not in results


def test_get_lod0_mesh_objects_derivative_lod_resolution(monkeypatch):
    """Verify get_lod0_mesh_objects resolves back to LOD0 when user selects a derivative LOD tier."""
    from unittest.mock import MagicMock
    import ui.utils as ui_utils
    from ui.utils import get_lod0_mesh_objects

    mock_bpy = MagicMock()
    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)

    mock_bpy.data.collections.get.return_value = None

    lod0_mesh = MagicMock()
    lod0_mesh.name = "SM_Prop_LOD0"
    lod0_mesh.type = "MESH"
    lod0_mesh.get.return_value = False

    lod2_mesh = MagicMock()
    lod2_mesh.name = "SM_Prop_LOD2"
    lod2_mesh.type = "MESH"
    lod2_mesh.get.return_value = False

    def mock_get_obj(name):
        if name in {"SM_Prop_LOD0", "SM_Prop"}:
            return lod0_mesh
        return None

    mock_bpy.data.objects.get.side_effect = mock_get_obj

    mock_context = MagicMock()
    mock_context.scene.lod_tool.export_base_name = ""
    mock_context.active_object = lod2_mesh
    mock_context.selected_objects = [lod2_mesh]

    results = get_lod0_mesh_objects(mock_context)
    assert len(results) == 1
    assert results[0] == lod0_mesh


def test_remove_colliders_scoped_safety(monkeypatch):
    """Ensure remove_colliders_for_objects purges ONLY target asset colliders and preserves others."""
    from unittest.mock import MagicMock
    import core.collision as col_mod
    from core.collision import CollisionManager

    mock_bpy = MagicMock()
    monkeypatch.setattr(col_mod, "bpy", mock_bpy)

    # Target asset: SM_Chair
    chair_col_1 = MagicMock()
    chair_col_1.name = "SM_Chair_Collider_01"
    chair_col_1.get.side_effect = lambda k, default=None: (
        True if k in {"_is_collider"} else "SM_Chair" if k == "_om_asset_base" else default
    )

    # Other asset: SM_Table
    table_col_1 = MagicMock()
    table_col_1.name = "SM_Table_Collider_01"
    table_col_1.get.side_effect = lambda k, default=None: (
        True if k in {"_is_collider"} else "SM_Table" if k == "_om_asset_base" else default
    )

    mock_objects_coll = MagicMock()
    mock_objects_coll.__iter__.return_value = [chair_col_1, table_col_1]
    mock_bpy.data.objects = mock_objects_coll
    mock_bpy.data.collections.get.return_value = None

    removed = CollisionManager.remove_colliders_for_objects([], "SM_Chair")
    assert removed == 1
    mock_objects_coll.remove.assert_called_once_with(chair_col_1, do_unlink=True)


def test_get_lod0_mesh_objects_from_derivative_collection(monkeypatch):
    """Ensure selecting a derivative LOD part (e.g. SM_Chair_Seat_LOD1) resolves to all LOD0 parts in root collection."""
    from unittest.mock import MagicMock
    import ui.utils as ui_utils
    from ui.utils import get_lod0_mesh_objects, resolve_asset_base_name

    mock_bpy = MagicMock()
    monkeypatch.setattr(ui_utils, "bpy", mock_bpy)

    seat_lod0 = MagicMock()
    seat_lod0.name = "SM_Chair_Seat"
    seat_lod0.type = "MESH"
    seat_lod0.get.return_value = False

    back_lod0 = MagicMock()
    back_lod0.name = "SM_Chair_Back"
    back_lod0.type = "MESH"
    back_lod0.get.return_value = False

    root_coll = MagicMock()
    root_coll.name = "SM_Chair"
    root_coll.objects = [seat_lod0, back_lod0]

    deriv_coll = MagicMock()
    deriv_coll.name = "SM_Chair_LOD1"

    seat_lod1 = MagicMock()
    seat_lod1.name = "SM_Chair_Seat_LOD1"
    seat_lod1.type = "MESH"
    seat_lod1.users_collection = [deriv_coll]

    def mock_get_coll(name):
        if name == "SM_Chair":
            return root_coll
        return None

    mock_bpy.data.collections.get.side_effect = mock_get_coll

    mock_context = MagicMock()
    mock_context.scene.lod_tool.export_base_name = ""
    mock_context.scene.collection = MagicMock()
    mock_context.active_object = seat_lod1
    mock_context.selected_objects = [seat_lod1]

    # 1. Base name resolution from derivative collection
    base_name = resolve_asset_base_name(mock_context)
    assert base_name == "SM_Chair"

    # 2. LOD0 meshes gathered from root collection
    meshes = get_lod0_mesh_objects(mock_context)
    assert len(meshes) == 2
    assert seat_lod0 in meshes
    assert back_lod0 in meshes


def test_collision_collection_nested_under_root_asset(monkeypatch):
    """Ensure generated collision collection is nested under the root model collection if present."""
    from unittest.mock import MagicMock
    import core.collision as collision_mod
    from core.collision import CollisionManager

    mock_bpy = MagicMock()
    monkeypatch.setattr(collision_mod, "bpy", mock_bpy)

    root_coll = MagicMock()
    root_coll.name = "SM_Plane"
    root_coll.children = MagicMock()
    root_coll.children.__contains__.return_value = False

    target_coll = MagicMock()
    target_coll.name = "SM_Plane_Colliders"

    def mock_get(name):
        if name == "SM_Plane":
            return root_coll
        return None

    mock_bpy.data.collections.get.side_effect = mock_get
    mock_bpy.data.collections.new.return_value = target_coll

    mesh_obj = MagicMock()
    mesh_obj.name = "SM_Plane"
    mesh_obj.matrix_world = MagicMock()
    mesh_obj.data = MagicMock()

    CollisionManager.generate_colliders_for_objects(
        [mesh_obj],
        "SM_Plane",
        mode="PER_OBJECT",
        hull_count=1,
    )

    root_coll.children.link.assert_called_once_with(target_coll)
    assert not mock_bpy.context.scene.collection.children.link.called
