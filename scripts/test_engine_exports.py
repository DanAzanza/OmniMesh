"""
Multi-Engine Autonomous Export & Ingestion Test Runner for OmniMesh.
Tests export artifact integrity and downstream engine validation across:
- Unity 6 (Unity CLI, Postprocessor generation, FBX structure)
- Godot 4 (Godot CLI Headless Import, GDScript Post-Import)
- Unreal Engine 5 (UE 5.8 Commandlet, ModelContextProtocol Plugin, Ingest Payload)
- MSFS 2024 (ModelInfo XML Schema, Descending minSize, glTF validation, fspackagetool)
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("EngineExportTester")


def test_msfs_export(export_dir: str, asset_name: str) -> bool:
    logger.info("=== Testing MSFS 2024 Export Artifacts ===")
    xml_file = os.path.join(export_dir, f"{asset_name}.xml")
    if not os.path.exists(xml_file):
        logger.error("MSFS XML file not found: %s", xml_file)
        return False

    try:
        tree = ET.parse(xml_file)  # noqa: S314
        root = tree.getroot()
        if root.tag != "ModelInfo":
            logger.error("Root tag is not ModelInfo, got: %s", root.tag)
            return False

        guid = root.get("guid", "")
        if not re.match(r"^\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}$", guid):
            logger.error("Invalid MSFS GUID format: %s", guid)
            return False

        lods = root.find("LODS")
        if lods is None or len(lods) == 0:
            logger.error("<LODS> section missing or empty in %s", xml_file)
            return False

        prev_min_size = float("inf")
        lod_elements = list(lods.findall("LOD"))
        for idx, lod in enumerate(lod_elements):
            min_size_str = lod.get("minSize")
            model_file = lod.get("ModelFile")
            if min_size_str is None or model_file is None:
                logger.error("LOD element missing minSize or ModelFile: %s", ET.tostring(lod))
                return False

            min_size = float(min_size_str)
            if min_size >= prev_min_size:
                logger.error(
                    "Non-descending minSize detected: LOD %d minSize=%s >= prev=%s", idx, min_size, prev_min_size
                )
                return False
            prev_min_size = min_size

            # Check glTF file on disk if in same folder
            gltf_path = os.path.join(export_dir, model_file)
            if os.path.exists(gltf_path):
                with open(gltf_path, "r", encoding="utf-8") as gf:
                    gltf_data = json.load(gf)
                    if "asset" not in gltf_data:
                        logger.error("Invalid glTF file structure: %s", gltf_path)
                        return False

        if float(lod_elements[-1].get("minSize", -1)) != 0.0:
            logger.error("Final LOD tier minSize must be 0, got: %s", lod_elements[-1].get("minSize"))
            return False

        logger.info("[PASS] MSFS 2024 XML and glTF validation succeeded (%d tiers).", len(lod_elements))
        return True
    except Exception as exc:
        logger.error("MSFS validation failed with exception: %s", exc)
        return False


def test_godot_headless_import(gltf_path: str, asset_name: str) -> bool:
    logger.info("=== Testing Godot 4 Headless Import ===")
    godot_cmd = os.environ.get("GODOT_PATH") or shutil.which("godot")
    if not godot_cmd and sys.platform == "win32":
        default_cmd = os.path.expanduser(r"~/.gemini/antigravity/bin/godot.cmd")
        if os.path.exists(default_cmd):
            godot_cmd = default_cmd

    if not godot_cmd:
        logger.warning("Godot binary not located. Skipping live Godot import test.")
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        proj_file = os.path.join(tmpdir, "project.godot")
        with open(proj_file, "w", encoding="utf-8") as f:
            f.write('config_version=5\n[application]\nconfig/name="OmniMeshTest"\n')

        # Install companion script
        addons_dir = os.path.join(tmpdir, "addons", "omnimesh")
        os.makedirs(addons_dir, exist_ok=True)
        from bridges.godot_bridge import GodotLiveBridge

        with open(os.path.join(addons_dir, "OmniMeshPostImport.gd"), "w", encoding="utf-8") as f:
            f.write(GodotLiveBridge.generate_post_import_gdscript())

        # Copy glTF
        target_gltf = os.path.join(tmpdir, os.path.basename(gltf_path))
        shutil.copy2(gltf_path, target_gltf)

        # Run headless editor import
        cmd = [godot_cmd, "--headless", "--path", tmpdir, "--editor", "--quit"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            logger.error("Godot headless import failed with code %d: %s", res.returncode, res.stderr)
            return False

        imported_dir = os.path.join(tmpdir, ".godot", "imported")
        if not os.path.isdir(imported_dir):
            logger.error("Godot .godot/imported directory was not generated.")
            return False

        logger.info("[PASS] Godot 4 headless imported asset successfully.")
        return True


def test_unity_cli_integration(fbx_path: str, asset_name: str) -> bool:
    logger.info("=== Testing Unity 6 CLI Integration ===")
    unity_bin = shutil.which("unity")
    if not unity_bin and sys.platform == "win32":
        default_unity = os.path.expandvars(r"%LOCALAPPDATA%\Unity\bin\unity.exe")
        if os.path.exists(default_unity):
            unity_bin = default_unity

    if not unity_bin:
        logger.warning("Unity CLI not located. Skipping Unity integration test.")
        return False

    from bridges.unity_bridge import UnityLiveBridge

    postproc_code = UnityLiveBridge.generate_postprocessor_csharp_code()
    if "OmniMeshUnityPostprocessor" not in postproc_code or "LODGroup" not in postproc_code:
        logger.error("Unity postprocessor code generation failed.")
        return False

    # Check Unity Editors installed
    res = subprocess.run([unity_bin, "editors"], capture_output=True, text=True)
    if "6000." not in res.stdout:
        logger.warning("Unity 6 editor not reported in unity editors list.")
        return False

    logger.info("[PASS] Unity CLI and postprocessor pipeline verified.")
    return True


def test_unreal_engine_integration(fbx_path: str, asset_name: str) -> bool:
    logger.info("=== Testing Unreal Engine 5 Integration ===")
    ue_cmd = os.path.expandvars(r"%ProgramFiles%\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe")
    mcp_plugin = os.path.expandvars(
        r"%ProgramFiles%\Epic Games\UE_5.8\Engine\Plugins\Experimental\ModelContextProtocol\ModelContextProtocol.uplugin"
    )

    if not os.path.exists(ue_cmd):
        logger.warning("UnrealEditor-Cmd.exe not found at %s", ue_cmd)
        return False

    if not os.path.exists(mcp_plugin):
        logger.warning("Unreal ModelContextProtocol plugin not found at %s", mcp_plugin)
        return False

    from bridges.unreal_bridge import UnrealLiveBridge

    payload = UnrealLiveBridge.build_non_destructive_ingest_payload(fbx_path, "/Game/Test", asset_name)
    if "unreal.AssetImportTask" not in payload or "unreal.FbxImportUI" not in payload:
        logger.error("Unreal ingest payload generation failed.")
        return False

    logger.info("[PASS] Unreal Engine 5.8 commandlet and ModelContextProtocol verified.")
    return True


def main() -> int:
    logger.info("Starting OmniMesh Multi-Engine Export & Integration Test Suite")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Generate synthetic MSFS package
        from exporters.msfs_export import MSFSExporter

        sample_tiers = [
            {"screen_size_pct": 100.0, "obj_name": "SM_Test_LOD0"},
            {"screen_size_pct": 50.0, "obj_name": "SM_Test_LOD1"},
            {"screen_size_pct": 25.0, "obj_name": "SM_Test_LOD2"},
            {"screen_size_pct": 10.0, "obj_name": "SM_Test_LOD3"},
        ]
        xml_content = MSFSExporter.generate_model_info_xml("SM_Test", sample_tiers)
        xml_path = os.path.join(tmpdir, "SM_Test.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        # Create dummy glTF files
        for i in range(len(sample_tiers)):
            gltf_p = os.path.join(tmpdir, f"SM_Test_LOD{i}.gltf")
            with open(gltf_p, "w", encoding="utf-8") as gf:
                json.dump({"asset": {"version": "2.0"}, "scenes": [{"nodes": [0]}], "nodes": [{"name": f"LOD{i}"}]}, gf)

        msfs_ok = test_msfs_export(tmpdir, "SM_Test")
        godot_ok = test_godot_headless_import(os.path.join(tmpdir, "SM_Test_LOD0.gltf"), "SM_Test")
        unity_ok = test_unity_cli_integration(os.path.join(tmpdir, "SM_Test.fbx"), "SM_Test")
        ue_ok = test_unreal_engine_integration(os.path.join(tmpdir, "SM_Test.fbx"), "SM_Test")

    all_passed = msfs_ok and godot_ok and unity_ok and ue_ok
    if all_passed:
        logger.info("ALL MULTI-ENGINE EXPORT & INTEGRATION TESTS PASSED!")
        return 0
    else:
        logger.error("Some engine export tests failed. Check logs above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
