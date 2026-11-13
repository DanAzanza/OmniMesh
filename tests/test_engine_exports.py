"""
Multi-Engine Autonomous Export & Ingestion Test Suite.
Validates export artifact schemas across:
- Microsoft Flight Simulator 2024 (ModelInfo XML Schema, descending minSize to 0.0, glTF validity)
- Unreal Engine 5 / Unity 6 export pipeline error handling

Tier 1: Static schema and artifact validation without external engine binaries.
Tier 2: Live engine integration tests (skipped if engine executables are missing).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from exporters.msfs_export import MSFSExporter


# ==============================================================================
# Tier 1: Static Schema & Artifact Integrity Tests (Engine-independent)
# ==============================================================================


def test_msfs2024_model_info_xml_schema():
    """Validates that generated MSFS 2024 ModelInfo.xml matches official SDK schema rules."""
    sample_tiers = [
        {"screen_size_pct": 100.0, "obj_name": "SM_Aircraft_LOD0"},
        {"screen_size_pct": 50.0, "obj_name": "SM_Aircraft_LOD1"},
        {"screen_size_pct": 20.0, "obj_name": "SM_Aircraft_LOD2"},
        {"screen_size_pct": 5.0, "obj_name": "SM_Aircraft_LOD3"},
    ]
    xml_content = MSFSExporter.generate_model_info_xml("SM_Aircraft", sample_tiers)

    # Must be valid XML
    root = ET.fromstring(xml_content)
    assert root.tag == "ModelInfo"

    # GUID format check: {[8]-[4]-[4]-[4]-[12]}
    guid = root.get("guid", "")
    assert re.match(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$", guid)

    lods = root.find("LODS")
    assert lods is not None
    lod_elements = list(lods.findall("LOD"))
    assert len(lod_elements) == len(sample_tiers)

    prev_min_size = float("inf")
    for idx, lod in enumerate(lod_elements):
        min_size_str = lod.get("minSize")
        model_file = lod.get("ModelFile")
        assert min_size_str is not None, f"LOD tier {idx} missing minSize"
        assert model_file is not None, f"LOD tier {idx} missing ModelFile"
        assert model_file.endswith(".gltf"), f"ModelFile must be .gltf, got {model_file}"

        min_size = float(min_size_str)
        assert min_size < prev_min_size, (
            f"LOD {idx} minSize ({min_size}) must be strictly less than previous ({prev_min_size})"
        )
        prev_min_size = min_size

    # Terminal tier MUST end at 0 or 0.0
    assert float(lod_elements[-1].get("minSize", -1)) == 0.0


# ==============================================================================
# Tier 2: Live Engine Integration Tests (Skipped when engines not installed)
# ==============================================================================


def test_live_unity_cli_integration():
    """Live check for Unity 6 CLI (skipped unless RUN_LIVE_ENGINE_TESTS=1)."""
    if not os.environ.get("RUN_LIVE_ENGINE_TESTS"):
        pytest.skip("Live Unity engine process test skipped by default. Set RUN_LIVE_ENGINE_TESTS=1 to execute.")

    unity_bin = shutil.which("unity")
    if not unity_bin and sys.platform == "win32":
        default_unity = os.path.expandvars(r"%LOCALAPPDATA%\Unity\bin\unity.exe")
        if os.path.exists(default_unity):
            unity_bin = default_unity

    if not unity_bin:
        pytest.skip("Unity CLI executable not found in PATH or environment")

    res = subprocess.run([unity_bin, "editors"], capture_output=True, text=True, timeout=15)
    assert res.returncode == 0


def test_exporter_manager_catches_export_pipeline_error():
    """Verifies ExporterManager catches ExportPipelineError and returns (False, error_str)."""
    from unittest.mock import MagicMock, patch

    from core.exceptions import ExportPipelineError
    from exporters.manager import ExporterManager
    from exporters.ue5_export import UE5Exporter

    mock_context = MagicMock()
    with patch.object(UE5Exporter, "export_asset", side_effect=ExportPipelineError("Geometry corrupted")):
        ok, msg = ExporterManager.export_asset(mock_context, "UE5", "/tmp", "TestAsset")
        assert ok is False
        assert "Geometry corrupted" in msg


def test_msfs_gltf_export_isolates_active_scene(tmp_path):
    """Verifies MSFS glTF export passes use_active_scene=True to prevent multi-scene leakage."""
    from types import SimpleNamespace
    from typing import Any, cast
    from unittest.mock import MagicMock, patch

    from exporters import msfs_export

    fake_obj = MagicMock()
    fake_obj.name = "SM_Test_LOD0"
    fake_obj.visible_get.return_value = True
    fake_obj.hide_viewport = False
    fake_obj.hide_render = False
    fake_obj.users_collection = []

    fake_scene = SimpleNamespace(objects=[], lod_tool=None)
    fake_context = SimpleNamespace(
        scene=fake_scene,
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
        selected_objects=[],
    )
    mock_gltf_op = MagicMock()
    mock_bpy = SimpleNamespace(
        ops=SimpleNamespace(
            object=SimpleNamespace(select_all=MagicMock()),
            export_scene=SimpleNamespace(gltf=mock_gltf_op),
        )
    )

    with patch.object(msfs_export, "bpy", mock_bpy):
        err = MSFSExporter._export_single_lod_tier_gltf(
            context=cast("Any", fake_context),
            tier_idx=0,
            tier_objs=[fake_obj],
            attachment_nodes=[],
            export_dir=str(tmp_path),
            clean_name="SM_Test",
            is_skeletal=False,
        )

    assert err is None
    mock_gltf_op.assert_called_once()
    call_kwargs = mock_gltf_op.call_args.kwargs
    assert call_kwargs["use_selection"] is True
    assert call_kwargs["use_active_scene"] is True
    assert call_kwargs["export_format"] == "GLTF_SEPARATE"


def test_msfs_export_creates_v11_xml_and_merges_existing_shifted_minsize(tmp_path):
    """Verify new MSFS XMLs include v1.1+GUID while existing XML merges preserve behaviors and shifted minSize."""
    from types import SimpleNamespace
    from typing import Any, cast
    from unittest.mock import MagicMock, patch

    from exporters import msfs_export
    from exporters.engine_export import AssetMeshResolver

    def _make_obj(name: str) -> Any:
        obj = MagicMock()
        obj.name = name
        obj.hide_viewport = False
        obj.hide_get.return_value = False
        obj.users_collection = []
        return obj

    lod0, lod1, lod2 = _make_obj("Plane_LOD0"), _make_obj("Plane_LOD1"), _make_obj("Plane_LOD2")
    payload = SimpleNamespace(
        lod_tiers={0: [lod0], 1: [lod1], 2: [lod2]},
        attachment_nodes=[],
        is_skeletal=False,
        has_impostor_tier=False,
    )
    props = SimpleNamespace(
        lods=[
            SimpleNamespace(screen_size_pct=100.0),
            SimpleNamespace(screen_size_pct=25.0),
            SimpleNamespace(screen_size_pct=8.0),
        ],
        cull_screen_size_pct=1.5,
    )
    ctx = SimpleNamespace(
        mode="OBJECT",
        scene=SimpleNamespace(lod_tool=props),
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
        selected_objects=[],
        blend_data=None,
    )
    fake_bpy = SimpleNamespace(
        ops=SimpleNamespace(
            object=SimpleNamespace(select_all=MagicMock()),
            export_scene=SimpleNamespace(gltf=MagicMock()),
        )
    )

    out_dir = tmp_path / "msfs_new"
    with (
        patch.object(msfs_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok, _ = MSFSExporter.export_asset(cast("Any", ctx), str(out_dir), "TestPlane")
    assert ok is True
    new_xml = (out_dir / "TestPlane.xml").read_text(encoding="utf-8")
    root_new = ET.fromstring(new_xml)
    assert root_new.attrib["version"] == "1.1"
    assert root_new.attrib["guid"].startswith("{")
    lods_new = root_new.find("LODS").findall("LOD")  # type: ignore[union-attr]
    assert [el.attrib["minSize"] for el in lods_new] == ["25", "8", "1.5"]
    assert [el.attrib["ModelFile"] for el in lods_new] == [
        "TestPlane_LOD0.gltf",
        "TestPlane_LOD1.gltf",
        "TestPlane_LOD2.gltf",
    ]

    # Existing XML with <Behaviors> must merge shifted minSize cleanly without stripping custom tags
    existing_xml_path = out_dir / "TestPlane.xml"
    existing_xml_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ModelInfo guid="{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}">\n'
        "    <LODS>\n"
        '        <LOD minSize="99" ModelFile="Old.gltf"/>\n'
        "    </LODS>\n"
        '    <Behaviors><Include ModelBehaviorFile="Asobo\\Generic.xml"/></Behaviors>\n'
        "</ModelInfo>\n",
        encoding="utf-8",
    )
    with (
        patch.object(msfs_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok_merge, _ = MSFSExporter.export_asset(cast("Any", ctx), str(out_dir), "TestPlane")
    assert ok_merge is True
    merged_xml = existing_xml_path.read_text(encoding="utf-8")
    assert "<Behaviors>" in merged_xml
    assert "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}" in merged_xml
    root_merged = ET.fromstring(merged_xml)
    lods_merged = root_merged.find("LODS").findall("LOD")  # type: ignore[union-attr]
    assert [el.attrib["minSize"] for el in lods_merged] == ["25", "8", "1.5"]


def test_unity_export_normalizes_lod0_impostor_and_writes_postprocessor(tmp_path):
    """Verify UnityExporter normalizes _LOD0 + impostor names transactionally and emits Editor C# helper."""
    from types import SimpleNamespace
    from typing import Any, cast
    from unittest.mock import MagicMock, patch

    from exporters import unity_export
    from exporters.engine_export import AssetMeshResolver

    def _obj(name: str) -> Any:
        o = MagicMock()
        o.name = name
        o.hide_viewport = False
        o.hide_get.return_value = False
        o.users_collection = []
        return o

    fuselage = _obj("Fuselage")
    fuselage_lod1 = _obj("Fuselage_LOD1")
    impostor = _obj("TestPlane_LOD_Impostor")
    collider = _obj("Fuselage_Shell")

    payload = SimpleNamespace(
        lod_tiers={0: [fuselage], 1: [fuselage_lod1], 2: [impostor]},
        collider_objects=[collider],
        armature_obj=None,
        has_impostor_tier=True,
    )
    ctx = SimpleNamespace(
        mode="OBJECT",
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
        selected_objects=[],
        blend_data=None,
    )

    observed_names: list[str] = []

    def _capture_fbx(**_kwargs: Any) -> None:
        observed_names.extend([fuselage.name, fuselage_lod1.name, impostor.name, collider.name])

    fake_bpy = SimpleNamespace(
        ops=SimpleNamespace(
            object=SimpleNamespace(select_all=MagicMock()),
            export_scene=SimpleNamespace(fbx=_capture_fbx),
        )
    )

    out_dir = tmp_path / "unity_out"
    with (
        patch.object(unity_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok, _ = unity_export.UnityExporter.export_asset(cast("Any", ctx), str(out_dir), "TestPlane")

    assert ok is True
    assert observed_names == ["Fuselage_LOD0", "Fuselage_LOD1", "TestPlane_LOD2", "TestPlane_Collider_01"]
    assert (fuselage.name, fuselage_lod1.name, impostor.name, collider.name) == (
        "Fuselage",
        "Fuselage_LOD1",
        "TestPlane_LOD_Impostor",
        "Fuselage_Shell",
    )
    cs_path = out_dir / "Editor" / "OmniMeshPostprocessor.cs"
    assert cs_path.is_file()
    cs_text = cs_path.read_text(encoding="utf-8")
    assert "class OmniMeshPostprocessor : AssetPostprocessor" in cs_text
    assert "AddComponent<MeshCollider>()" in cs_text

    # Negative: failing FBX export skips writing companion C# helper and restores names
    fail_dir = tmp_path / "unity_fail"
    fake_bpy_fail = SimpleNamespace(
        ops=SimpleNamespace(
            object=SimpleNamespace(select_all=MagicMock()),
            export_scene=SimpleNamespace(fbx=MagicMock(side_effect=RuntimeError("fbx write error"))),
        )
    )
    with (
        patch.object(unity_export, "bpy", fake_bpy_fail),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok_fail, msg_fail = unity_export.UnityExporter.export_asset(cast("Any", ctx), str(fail_dir), "TestPlane")
    assert ok_fail is False and "fbx write error" in msg_fail
    assert not (fail_dir / "Editor" / "OmniMeshPostprocessor.cs").exists()
    assert fuselage.name == "Fuselage" and impostor.name == "TestPlane_LOD_Impostor"


def test_ue5_export_writes_valid_import_helper_script(tmp_path):
    """Verify UE5Exporter writes syntactically valid Python import helper on success only."""
    import ast
    from types import SimpleNamespace
    from typing import Any, cast
    from unittest.mock import MagicMock, patch

    from exporters import ue5_export
    from exporters.engine_export import AssetMeshResolver

    lod0 = MagicMock()
    lod0.name = "SM_Plane_LOD0"
    lod0.parent = None
    lod0.matrix_world = None
    lod0.hide_viewport = False
    lod0.hide_get.return_value = False
    lod0.users_collection = []

    arm = MagicMock()
    arm.name = "Plane_Rig"
    arm.hide_viewport = False
    arm.hide_get.return_value = False
    arm.users_collection = []

    payload = SimpleNamespace(
        lod_tiers={0: [lod0]},
        collider_objects=[],
        armature_obj=arm,
        has_impostor_tier=False,
    )
    ctx = SimpleNamespace(
        mode="OBJECT",
        view_layer=SimpleNamespace(objects=SimpleNamespace(active=None)),
        selected_objects=[],
        blend_data=None,
    )
    fake_bpy = SimpleNamespace(
        ops=SimpleNamespace(
            object=SimpleNamespace(select_all=MagicMock()),
            export_scene=SimpleNamespace(fbx=MagicMock()),
        )
    )

    out_dir = tmp_path / "ue5_out"
    with (
        patch.object(ue5_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok, _ = ue5_export.UE5Exporter.export_asset(cast("Any", ctx), str(out_dir), "SM_Plane")

    assert ok is True
    helper_path = out_dir / "SM_Plane_ue5_import.py"
    assert helper_path.is_file()
    helper_src = helper_path.read_text(encoding="utf-8")
    ast.parse(helper_src)
    assert "IS_SKELETAL = True" in helper_src
    assert "import_mesh_lo_ds" in helper_src
    assert "TC_MASKS" in helper_src

    # Negative: failed FBX leaves no orphan UE5 helper script
    fail_dir = tmp_path / "ue5_fail"
    fake_bpy_fail = SimpleNamespace(
        ops=SimpleNamespace(
            object=SimpleNamespace(select_all=MagicMock()),
            export_scene=SimpleNamespace(fbx=MagicMock(side_effect=RuntimeError("ue5 fbx error"))),
        )
    )
    with (
        patch.object(ue5_export, "bpy", fake_bpy_fail),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=payload),
    ):
        ok_fail, _ = ue5_export.UE5Exporter.export_asset(cast("Any", ctx), str(fail_dir), "SM_Plane")
    assert ok_fail is False
    assert not (fail_dir / "SM_Plane_ue5_import.py").exists()

    # Negative: adversarial asset_name cannot inject code or break Python syntax
    adversarial = 'Bad"; import os; os.system("calc"); """\n__import__("sys")'
    safe_script = ue5_export.UE5Exporter.generate_import_script_py(adversarial, is_skeletal=False)
    tree = ast.parse(safe_script)
    assign_names = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "ASSET_NAME"
        and isinstance(node.value, ast.Constant)
    ]
    assert len(assign_names) == 1
    assert "import os" in str(assign_names[0]) or "_" in str(assign_names[0])
    assert not any(isinstance(n, ast.Expr) for n in tree.body)

    # Negative: ReferenceError during Unity name rollback in finally must not crash export_asset
    from exporters import unity_export

    class _DeadOnRestoreObj:
        def __init__(self, initial_name: str) -> None:
            self._name = initial_name
            self.hide_viewport = False
            self.users_collection: list[Any] = []
            self._renamed = False

        @property
        def name(self) -> str:
            if self._renamed:
                raise ReferenceError("StructRNA removed")
            return self._name

        @name.setter
        def name(self, value: str) -> None:
            if self._renamed:
                raise ReferenceError("StructRNA removed")
            self._name = value
            self._renamed = True

        def hide_get(self, *, view_layer: Any = None) -> bool:
            return False

        def hide_set(self, _hide: bool, *, view_layer: Any = None) -> None:
            pass

        def select_set(self, _state: bool) -> None:
            pass

    dead_lod = _DeadOnRestoreObj("Plane")
    dead_lod1 = _DeadOnRestoreObj("Plane_LOD1")
    dead_col = _DeadOnRestoreObj("Hull_Box")
    dead_payload = SimpleNamespace(
        lod_tiers={0: [dead_lod], 1: [dead_lod1]},
        collider_objects=[dead_col],
        armature_obj=None,
        has_impostor_tier=False,
    )
    with (
        patch.object(unity_export, "bpy", fake_bpy),
        patch.object(AssetMeshResolver, "resolve_payload", return_value=dead_payload),
    ):
        ok_dead, _msg_dead = unity_export.UnityExporter.export_asset(
            cast("Any", ctx), str(tmp_path / "unity_dead"), "Plane"
        )
    assert ok_dead is True
