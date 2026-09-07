"""
OmniMesh Headless Batch Worker Script.

Executed in isolated background Blender instances:
blender.exe -b <blend_file> --factory-startup --disable-autoexec --python core/batch_worker.py -- <args>
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import bpy

# Set up clean logging
logging.basicConfig(level=logging.INFO, format="[OmniMesh Worker] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def setup_omnimesh_path() -> None:
    """Injects OmniMesh root directory into sys.path to load core modules directly."""
    current_file = Path(__file__).resolve()
    # current_file is <addon_root>/core/batch_worker.py -> addon_root is parent.parent
    addon_root = str(current_file.parent.parent)
    if addon_root not in sys.path:
        sys.path.insert(0, addon_root)


def parse_worker_args() -> argparse.Namespace:
    """Parses command line arguments passed after '--'."""
    raw_args = []
    if "--" in sys.argv:
        raw_args = sys.argv[sys.argv.index("--") + 1 :]

    parser = argparse.ArgumentParser(description="OmniMesh Headless Batch Export Worker")
    parser.add_argument("--preset", type=str, default="", help="Active PBR Export Preset ID")
    parser.add_argument("--export-dir", type=str, required=True, help="Target export directory")
    parser.add_argument("--engine", type=str, default="", help="Target game engine (UE5, UNITY_6, etc.)")
    parser.add_argument("--asset-name", type=str, default="", help="Override asset base name")

    return parser.parse_args(raw_args)


def run_worker() -> int:
    """Executes the export pipeline on the opened .blend file."""
    setup_omnimesh_path()
    args = parse_worker_args()

    export_dir = os.path.normpath(args.export_dir)
    os.makedirs(export_dir, exist_ok=True)

    blend_name = Path(bpy.data.filepath).stem if bpy.data.filepath else "Asset"
    asset_name = args.asset_name or blend_name

    logger.info("Processing asset '%s' into '%s'...", asset_name, export_dir)

    # Initialize / Register OmniMesh minimal dependencies
    try:
        import ui

        ui.register_ui()
        import exporters

        if hasattr(exporters, "register_exporters") and exporters.register_exporters:
            exporters.register_exporters()
        from exporters.godot_export import GodotExporter
        from exporters.msfs_export import MSFSExporter
        from exporters.ue5_export import UE5Exporter
        from exporters.unity_export import UnityExporter
    except Exception as exc:
        logger.error("Failed importing OmniMesh dependencies: %s", exc)
        return 1

    props = bpy.context.scene.lod_tool
    props.export_directory = export_dir + "/"
    props.export_base_name = asset_name
    props.enable_live_sync = False

    preset_id = args.preset
    if preset_id:
        props.pbr_export_preset = preset_id

    target_engine = args.engine or props.target_engine or "UE5"
    props.target_engine = target_engine

    # Ensure mesh objects are selectable and visible
    mesh_objs = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.name.startswith(("UCX_", "UBX_", "USP_"))
    ]
    if not mesh_objs:
        logger.warning("No mesh objects found in '%s'. Skipping.", bpy.data.filepath)
        return 0

    # Ensure an active object and selection exists
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    for obj in mesh_objs:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objs[0]

    # Check if pre-generated LOD collections exist; if not, trigger pipeline
    lod_colls = [c for c in bpy.data.collections if "_LOD" in c.name]
    if not lod_colls:
        logger.info("No pre-existing LOD collections found. Generating LODs for '%s'...", asset_name)
        if len(props.lods) == 0:
            logger.info("Configuring default LOD tiers...")
            try:
                bpy.ops.lod_tool.analyze_and_configure()
            except Exception as exc:
                logger.warning("Auto-configure tiers fallback: %s", exc)
        try:
            bpy.ops.lod_tool.generate_all()
        except Exception as exc:
            logger.error("Failed generating LODs for '%s': %s", asset_name, exc)
            return 1

    # Execute export matching the target engine
    success = False
    message = ""
    try:
        if target_engine == "UE5":
            success, message = UE5Exporter.export_asset(bpy.context, export_dir, asset_name)
        elif target_engine == "UNITY_6":
            success, message = UnityExporter.export_asset(bpy.context, export_dir, asset_name)
        elif target_engine == "GODOT_4":
            success, message = GodotExporter.export_asset(bpy.context, export_dir, asset_name)
        elif target_engine == "MSFS_2024":
            success, message = MSFSExporter.export_asset(bpy.context, export_dir, asset_name)
        else:
            logger.error("Unsupported target engine: %s", target_engine)
            return 1
    except Exception as exc:
        logger.error("Export exception for '%s': %s", asset_name, exc)
        return 1

    if success:
        logger.info("Successfully exported '%s': %s", asset_name, message)
        return 0
    else:
        logger.error("Export failed for '%s': %s", asset_name, message)
        return 1


if __name__ == "__main__":
    code = run_worker()
    sys.exit(code)
