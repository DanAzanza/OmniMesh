"""
Master Engine Export Router & Pre-Flight Quality Gate.
"""

from __future__ import annotations

from typing import Any

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

from .godot_export import GodotExporter
from .msfs_export import MSFSExporter
from .ue5_export import UE5Exporter
from .unity_export import UnityExporter


class PreFlightValidator:
    @staticmethod
    def run_checks(context: Any) -> list[str]:
        if not bpy or not context:
            return ["Blender context not available."]
        props = context.scene.lod_tool
        errors: list[str] = []

        if len(props.lods) == 0:
            errors.append("No LOD tiers configured.")
            return errors

        valid_objs = [tier.generated_obj for tier in props.lods if tier.generated_obj]
        if len(valid_objs) != len(props.lods):
            errors.append("Some configured LOD tiers have not been generated yet. Run 'Generate All LODs' first.")
            return errors

        lod0_pivot = valid_objs[0].matrix_world.translation
        for i, obj in enumerate(valid_objs):
            if (obj.matrix_world.translation - lod0_pivot).length > 1e-4:
                errors.append(f"LOD{i} origin does not match LOD0 pivot.")

            scale = obj.scale
            if abs(scale.x - 1.0) > 1e-4 or abs(scale.y - 1.0) > 1e-4 or abs(scale.z - 1.0) > 1e-4:
                errors.append(f"LOD{i} has unapplied scale {tuple(round(s, 2) for s in scale)}. Apply transforms.")

        for i, obj in enumerate(valid_objs):
            if len(obj.material_slots) == 0 and len(valid_objs[0].material_slots) > 0:
                errors.append(f"LOD{i} is missing material slots.")

        return errors


class LOD_OT_export_engine_package(Operator):
    bl_idname = "lod_tool.export_engine_package"
    bl_label = "1-Click Export Asset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bpy and hasattr(context.scene, "lod_tool") and len(context.scene.lod_tool.lods) > 0

    def execute(self, context):
        if not bpy:
            return {"CANCELLED"}
        props = context.scene.lod_tool

        errors = PreFlightValidator.run_checks(context)
        if errors:
            for err in errors:
                self.report({"ERROR"}, f"[Pre-Flight Gate] {err}")
            return {"CANCELLED"}

        export_dir = bpy.path.abspath(props.export_directory)
        asset_name = props.export_base_name or "SM_Asset"
        target = props.target_engine
        success = False
        message = ""

        if target == "MSFS_2024":
            success, message = MSFSExporter.export_asset(context, export_dir, asset_name)
        elif target == "UE5":
            success, message = UE5Exporter.export_asset(context, export_dir, asset_name)
        elif target == "UNITY_6":
            success, message = UnityExporter.export_asset(context, export_dir, asset_name)
        elif target == "GODOT_4":
            success, message = GodotExporter.export_asset(context, export_dir, asset_name)

        if success:
            self.report({"INFO"}, f"[LOD Export] {message}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"[LOD Export Failed] {message}")
            return {"CANCELLED"}


def register_exporters():
    if not bpy:
        return
    bpy.utils.register_class(LOD_OT_export_engine_package)


def unregister_exporters():
    if not bpy:
        return
    bpy.utils.unregister_class(LOD_OT_export_engine_package)
