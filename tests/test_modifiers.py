"""
Unit tests for OmniMesh Modifier Manager & Non-Destructive Evaluated Mesh Extraction.
Tests ModifierManager.has_unapplied_modifiers, get_evaluated_mesh,
and apply_all_modifiers_in_place.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.modifiers import ModifierManager


class MockModifier:
    def __init__(self, name: str, mod_type: str, show_viewport: bool = True):
        self.name = name
        self.type = mod_type
        self.show_viewport = show_viewport


class MockMesh:
    def __init__(self, name: str = "TestMesh", users: int = 1):
        self.name = name
        self.users = users
        self.polygons = [0] * 10

    def copy(self) -> MockMesh:
        return MockMesh(name=f"{self.name}_copy", users=1)


class MockObject:
    def __init__(self, name: str = "TestObj", obj_type: str = "MESH"):
        self.name = name
        self.type = obj_type
        self.data = MockMesh(f"{name}_Data")
        self.modifiers: list[MockModifier] = []


def test_has_unapplied_modifiers_null_or_empty():
    assert not ModifierManager.has_unapplied_modifiers(None)
    assert not ModifierManager.has_unapplied_modifiers(object())

    obj = MockObject()
    assert not ModifierManager.has_unapplied_modifiers(obj)


def test_has_unapplied_modifiers_armature_only():
    obj = MockObject()
    obj.modifiers.append(MockModifier("Armature", "ARMATURE"))

    # When ignore_armature=True (default), armature does not count
    assert not ModifierManager.has_unapplied_modifiers(obj, ignore_armature=True)
    # When ignore_armature=False, armature counts
    assert ModifierManager.has_unapplied_modifiers(obj, ignore_armature=False)


def test_has_unapplied_modifiers_procedural():
    obj = MockObject()
    obj.modifiers.append(MockModifier("Subdivision", "SUBSURF"))
    assert ModifierManager.has_unapplied_modifiers(obj)

    obj.modifiers.append(MockModifier("Displace", "DISPLACE"))
    assert ModifierManager.has_unapplied_modifiers(obj)


def test_get_evaluated_mesh_null_or_non_mesh():
    mesh, eval_obj = ModifierManager.get_evaluated_mesh(None)
    assert mesh is None
    assert eval_obj is None

    empty_obj = MockObject("Empty", obj_type="EMPTY")
    mesh, eval_obj = ModifierManager.get_evaluated_mesh(empty_obj)
    assert mesh == empty_obj.data
    assert eval_obj is None


def test_get_evaluated_mesh_with_mocked_depsgraph():
    obj = MockObject()
    arm_mod = MockModifier("Armature", "ARMATURE", show_viewport=True)
    sub_mod = MockModifier("Subsurf", "SUBSURF")
    obj.modifiers = [arm_mod, sub_mod]

    eval_mesh_mock = MagicMock()
    eval_mesh_mock.polygons = [0] * 50

    eval_obj_mock = MagicMock()
    eval_obj_mock.to_mesh.return_value = eval_mesh_mock
    eval_obj_mock.data = eval_mesh_mock

    obj.evaluated_get = MagicMock(return_value=eval_obj_mock)

    mock_depsgraph = MagicMock()
    mock_bpy = MagicMock()
    mock_bpy.context.evaluated_depsgraph_get.return_value = mock_depsgraph

    with patch("core.modifiers.bpy", mock_bpy):
        eval_mesh, returned_eval_obj = ModifierManager.get_evaluated_mesh(obj, preserve_armature=True)

        assert eval_mesh == eval_mesh_mock
        assert returned_eval_obj == eval_obj_mock
        # Ensure armature modifier was restored
        assert arm_mod.show_viewport is True
        obj.evaluated_get.assert_called_once_with(mock_depsgraph)


def test_apply_all_modifiers_in_place_multi_user_unlinking():
    obj = MockObject()
    obj.data.users = 3
    orig_data = obj.data

    sub_mod = MockModifier("Subsurf", "SUBSURF")
    arm_mod = MockModifier("Armature", "ARMATURE")
    obj.modifiers = [sub_mod, arm_mod]

    mock_bpy = MagicMock()

    with patch("core.modifiers.bpy", mock_bpy):
        res = ModifierManager.apply_all_modifiers_in_place(obj, preserve_armature=True)
        assert res is True
        # Verify multi-user mesh was unlinked via copy
        assert obj.data != orig_data
        assert obj.data.users == 1
        # Verify bpy.ops.object.modifier_apply was called for Subsurf but NOT Armature
        mock_bpy.ops.object.modifier_apply.assert_called_once_with(modifier="Subsurf")


def test_apply_all_modifiers_in_place_no_modifiers():
    obj = MockObject()
    obj.modifiers = []
    # When bpy is None, returns False safely
    assert ModifierManager.apply_all_modifiers_in_place(obj) is False

    # When bpy is present, returns True because there are no modifiers to apply
    with patch("core.modifiers.bpy", MagicMock()):
        assert ModifierManager.apply_all_modifiers_in_place(obj) is True


def test_sync_viewport_to_render_settings():
    assert ModifierManager.sync_viewport_to_render_settings(None) == 0
    assert ModifierManager.sync_viewport_to_render_settings(object()) == 0

    obj = MockObject()

    # Subsurf with differing levels
    sub_mod = MockModifier("Subsurf", "SUBSURF")
    sub_mod.levels = 2
    sub_mod.render_levels = 6
    sub_mod.show_viewport = True
    sub_mod.show_render = True

    # Screw with differing steps
    screw_mod = MockModifier("Screw", "SCREW")
    screw_mod.steps = 16
    screw_mod.render_steps = 32
    screw_mod.show_viewport = True
    screw_mod.show_render = True

    # Ocean with differing resolution
    ocean_mod = MockModifier("Ocean", "OCEAN")
    ocean_mod.viewport_resolution = 8
    ocean_mod.resolution = 14
    ocean_mod.show_viewport = True
    ocean_mod.show_render = True

    # Hidden modifier
    hidden_mod = MockModifier("Bevel", "BEVEL")
    hidden_mod.show_viewport = False
    hidden_mod.show_render = True

    obj.modifiers = [sub_mod, screw_mod, ocean_mod, hidden_mod]

    synced = ModifierManager.sync_viewport_to_render_settings(obj)
    assert synced == 4

    assert sub_mod.render_levels == 2
    assert screw_mod.render_steps == 16
    assert ocean_mod.resolution == 8
    assert hidden_mod.show_render is False


def test_apply_all_modifiers_in_place_removes_hidden():
    obj = MockObject()
    visible_mod = MockModifier("Subsurf", "SUBSURF", show_viewport=True)
    visible_mod.levels = 3
    visible_mod.render_levels = 8

    hidden_mod = MockModifier("Displace", "DISPLACE", show_viewport=False)

    obj.modifiers = [visible_mod, hidden_mod]

    mock_bpy = MagicMock()
    with patch("core.modifiers.bpy", mock_bpy):
        res = ModifierManager.apply_all_modifiers_in_place(obj)
        assert res is True
        # Hidden mod was removed from modifiers
        assert hidden_mod not in obj.modifiers
        # Render levels on visible mod was synced to levels (3)
        assert visible_mod.render_levels == 3
        # modifier_apply was called ONLY for visible_mod
        mock_bpy.ops.object.modifier_apply.assert_called_once_with(modifier="Subsurf")
