"""
Unit tests for GLTFAssemblyEngine dependency injection and utility methods.
"""

from __future__ import annotations

from typing import TYPE_CHECKING as _TC, Any as _Any

if _TC:
    _MockBase: type[_Any] = object
else:
    _MockBase = object

from typing import Any
from unittest.mock import MagicMock

from core.gltf_assembly import GLTFAssemblyEngine
from tests.conftest import MockBlendData


class DummyMaterialSlot(_MockBase):
    def __init__(self, material: Any = None) -> None:
        self.material = material


class DummyModifier(_MockBase):
    def __init__(self, mod_type: str = "ARMATURE", target: Any = None) -> None:
        self.type = mod_type
        self.object = target


class DummyObject(_MockBase):
    def __init__(
        self,
        name: str,
        obj_type: str = "MESH",
        material_slots: list[Any] | None = None,
        modifiers: list[Any] | None = None,
        data: Any = None,
        parent: Any = None,
    ) -> None:
        self.name = name
        self.type = obj_type
        self.material_slots = material_slots or []
        self.modifiers = modifiers or []
        self.data = data
        self.parent = parent


class DummyMaterial(_MockBase):
    def __init__(self, name: str, users: int = 1) -> None:
        self.name = name
        self.users = users


def test_deduplicate_materials_remaps_and_purges() -> None:
    bdata = MockBlendData()
    base_mat = DummyMaterial("Fuselage", users=2)
    bdata.materials.new("Fuselage")
    bdata.materials._items["Fuselage"] = base_mat

    dup_mat = DummyMaterial("Fuselage.001", users=0)
    bdata.materials.new("Fuselage.001")
    bdata.materials._items["Fuselage.001"] = dup_mat

    slot = DummyMaterialSlot(material=dup_mat)
    obj = DummyObject("Fuselage_Mesh", material_slots=[slot])

    remapped = GLTFAssemblyEngine.deduplicate_materials([obj], blend_data=bdata)

    assert remapped == 1
    assert slot.material == base_mat
    assert "Fuselage.001" not in bdata.materials


def test_deduplicate_materials_empty_or_none_bdata() -> None:
    from typing import Any, cast

    # None blend_data should be resilient and not crash
    slot = DummyMaterialSlot(material=DummyMaterial("Fuselage.001"))
    obj = DummyObject("Mesh", material_slots=[slot])
    assert GLTFAssemblyEngine.deduplicate_materials([obj], blend_data=cast(Any, None)) == 0
    assert GLTFAssemblyEngine.deduplicate_materials([], blend_data=cast(Any, None)) == 0


def test_retarget_armatures_to_master() -> None:
    bdata = MockBlendData()

    master_arm_data = MagicMock(users=1)
    master_arm_data.name = "MasterRigData"
    master_arm = DummyObject("MasterRig", obj_type="ARMATURE", data=master_arm_data)
    bdata.objects._items["MasterRig"] = master_arm

    redundant_arm_data = MagicMock(users=0)
    redundant_arm_data.name = "LOD1RigData"
    redundant_arm = DummyObject("LOD1Rig", obj_type="ARMATURE", data=redundant_arm_data)
    bdata.objects._items["LOD1Rig"] = redundant_arm
    bdata.armatures._items["LOD1RigData"] = redundant_arm_data

    mod = DummyModifier(mod_type="ARMATURE", target=redundant_arm)
    lod1_mesh = DummyObject("LOD1_Mesh", modifiers=[mod])
    bdata.objects._items["LOD1_Mesh"] = lod1_mesh

    retargeted = GLTFAssemblyEngine.retarget_armatures_to_master(
        master_arm,
        [master_arm, lod1_mesh],
        blend_data=bdata,
    )

    assert retargeted == 1
    assert mod.object == master_arm
    assert "LOD1Rig" not in bdata.objects
    assert "LOD1RigData" not in bdata.armatures


def test_retarget_armatures_none_or_empty() -> None:
    from typing import Any, cast

    assert GLTFAssemblyEngine.retarget_armatures_to_master(None, [], blend_data=cast(Any, None)) == 0
    obj = DummyObject("Mesh")
    assert GLTFAssemblyEngine.retarget_armatures_to_master(None, [obj], blend_data=cast(Any, None)) == 0
