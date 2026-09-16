"""
Multi-Engine Autonomous Export & Ingestion Test Suite.
Validates export artifact schemas and companion scripts across:
- Microsoft Flight Simulator 2024 (ModelInfo XML Schema, descending minSize to 0.0, glTF validity)
- Unreal Engine 5 (FBX LODGroup & UCX collision hierarchy, live ingest payload)
- Unity 6 (Postprocessor C# generation, LODGroup setup)
- Godot 4 (Post-import GDScript generation, -convcolonly naming)

Tier 1: Static schema and artifact validation without external engine binaries.
Tier 2: Live engine integration tests (skipped if engine executables are missing).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import pytest

from bridges.godot_bridge import GodotLiveBridge
from bridges.unity_bridge import UnityLiveBridge
from bridges.unreal_bridge import UnrealLiveBridge
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


def test_unity6_postprocessor_code_structure():
    """Validates that Unity 6 postprocessor companion C# script contains correct LODGroup API calls."""
    cs_code = UnityLiveBridge.generate_postprocessor_csharp_code()
    assert "class OmniMeshUnityPostprocessor" in cs_code
    assert "AssetPostprocessor" in cs_code
    assert "LODGroup" in cs_code
    assert "MeshCollider" in cs_code
    assert "OnPostprocessModel" in cs_code
    # Verify regex patterns for LOD tier matching
    assert "_LOD" in cs_code


def test_godot4_post_import_gdscript_structure():
    """Validates that Godot 4 post-import GDScript contains visibility ranges and impostor setup."""
    gd_code = GodotLiveBridge.generate_post_import_gdscript()
    assert "@tool" in gd_code
    assert "EditorScenePostImport" in gd_code
    assert "_post_import" in gd_code
    assert "visibility_range_begin" in gd_code
    assert "visibility_range_end" in gd_code
    assert "impostor" in gd_code


def test_unreal_engine_ingest_payload_structure():
    """Validates that Unreal Engine 5 ingest payload generates correct Python script with LODGroup setup."""
    fbx_dummy_path = "C:/Projects/Game/Art/SM_Prop.fbx"
    payload = UnrealLiveBridge.build_non_destructive_ingest_payload(fbx_dummy_path, "/Game/Props", "SM_Prop")
    assert "unreal.AssetImportTask" in payload
    assert "unreal.FbxImportUI" in payload
    assert "import_mesh_lods = True" in payload
    assert "SM_Prop" in payload


# ==============================================================================
# Tier 2: Live Engine Integration Tests (Skipped when engines not installed)
# ==============================================================================


def test_live_godot_headless_import():
    """Live headless import into Godot 4 editor (skipped if godot executable is not found)."""
    godot_cmd = os.environ.get("GODOT_PATH") or shutil.which("godot")
    if not godot_cmd and sys.platform == "win32":
        default_cmd = os.path.expanduser(r"~/.gemini/antigravity/bin/godot.cmd")
        if os.path.exists(default_cmd):
            godot_cmd = default_cmd

    if not godot_cmd:
        pytest.skip("Godot 4 executable not found in PATH or environment")

    with tempfile.TemporaryDirectory() as tmpdir:
        proj_file = os.path.join(tmpdir, "project.godot")
        with open(proj_file, "w", encoding="utf-8") as f:
            f.write('config_version=5\n[application]\nconfig/name="OmniMeshTest"\n')

        addons_dir = os.path.join(tmpdir, "addons", "omnimesh")
        os.makedirs(addons_dir, exist_ok=True)
        with open(os.path.join(addons_dir, "OmniMeshPostImport.gd"), "w", encoding="utf-8") as f:
            f.write(GodotLiveBridge.generate_post_import_gdscript())

        # Create dummy minimal glTF
        gltf_p = os.path.join(tmpdir, "SM_Box_LOD0.gltf")
        with open(gltf_p, "w", encoding="utf-8") as gf:
            json.dump({"asset": {"version": "2.0"}, "scenes": [{"nodes": [0]}], "nodes": [{"name": "LOD0"}]}, gf)

        cmd = [godot_cmd, "--headless", "--path", tmpdir, "--editor", "--quit"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        assert res.returncode == 0, f"Godot headless import failed: {res.stderr}"


def test_live_unity_cli_integration():
    """Live check for Unity 6 CLI (skipped if unity executable is not found)."""
    unity_bin = shutil.which("unity")
    if not unity_bin and sys.platform == "win32":
        default_unity = os.path.expandvars(r"%LOCALAPPDATA%\Unity\bin\unity.exe")
        if os.path.exists(default_unity):
            unity_bin = default_unity

    if not unity_bin:
        pytest.skip("Unity CLI executable not found in PATH or environment")

    res = subprocess.run([unity_bin, "editors"], capture_output=True, text=True, timeout=15)
    assert res.returncode == 0
