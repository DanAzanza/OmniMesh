"""
Master Engine Export Router & Pre-Flight Quality Gate with PBR Texture & Animation Integration.
"""

from __future__ import annotations

import logging
import os
from typing import Any

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.animations import AnimationRigSanitizer
    from ..core.textures import TextureChannelPacker
except (ImportError, ValueError):
    from core.animations import AnimationRigSanitizer
    from core.textures import TextureChannelPacker

from .godot_export import GodotExporter
from .msfs_export import MSFSExporter
from .ue5_export import UE5Exporter
from .unity_export import UnityExporter

logger = logging.getLogger(__name__)


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


class LOD_OT_pack_pbr_textures(Operator):
    bl_idname = "lod_tool.pack_pbr_textures"
    bl_label = "Pack & Export Textures"
    bl_description = "Channel-pack PBR textures for the selected target game engine"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context and getattr(context, "active_object", None))

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"CANCELLED"}
        props = context.scene.lod_tool
        export_dir = bpy.path.abspath(props.export_directory)
        tex_dir = os.path.join(export_dir, "Textures")
        os.makedirs(tex_dir, exist_ok=True)

        res = int(props.texture_max_resolution)
        target_size = (res, res)
        target_engine = props.target_engine

        # Collect unique materials across active/selected objects
        materials: set[Any] = set()
        for obj in context.selected_objects:
            for slot in obj.material_slots:
                if slot.material:
                    materials.add(slot.material)

        if not materials:
            self.report({"WARNING"}, "No materials found on selected objects.")
            return {"CANCELLED"}

        packed_count = 0
        for mat in materials:
            mat_name = mat.name.replace(" ", "_")
            if target_engine == "UE5":
                orm_path = os.path.join(tex_dir, f"T_{mat_name}_ORM.png")
                TextureChannelPacker.pack_orm_ue5(mat, orm_path, target_size)
                norm_img = TextureChannelPacker.get_material_normal_image(mat)
                if norm_img:
                    norm_path = os.path.join(tex_dir, f"T_{mat_name}_Normal_DirectX.png")
                    TextureChannelPacker.convert_normal_directx(norm_img, norm_path, target_size)
                packed_count += 1
            elif target_engine == "UNITY_6":
                mask_path = os.path.join(tex_dir, f"T_{mat_name}_MaskMap.png")
                TextureChannelPacker.pack_maskmap_unity(mat, mask_path, target_size)
                packed_count += 1
            elif target_engine == "MSFS_2024":
                comp_path = os.path.join(tex_dir, f"T_{mat_name}_COMP.png")
                TextureChannelPacker.pack_comp_msfs(mat, comp_path, target_size)
                packed_count += 1
            elif target_engine == "GODOT_4":
                orm_path = os.path.join(tex_dir, f"T_{mat_name}_ORM.png")
                TextureChannelPacker.pack_orm_godot(mat, orm_path, target_size)
                packed_count += 1

        self.report(
            {"INFO"}, f"Successfully packed {packed_count} PBR texture set(s) for {target_engine} into {tex_dir}"
        )
        return {"FINISHED"}


class LOD_OT_bake_rig_animation(Operator):
    bl_idname = "lod_tool.bake_rig_animation"
    bl_label = "Bake & Validate Animation"
    bl_description = "Bake evaluated depsgraph deform bone matrices (IK to FK) for clean engine export"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        obj = getattr(context, "active_object", None)
        return bool(obj and (obj.type == "ARMATURE" or (obj.parent and obj.parent.type == "ARMATURE")))

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"CANCELLED"}
        obj = context.active_object
        armature = obj if obj.type == "ARMATURE" else obj.parent

        if not armature or not armature.animation_data or not armature.animation_data.action:
            self.report({"WARNING"}, "No active Action found on Armature.")
            return {"CANCELLED"}

        action = armature.animation_data.action
        baked = AnimationRigSanitizer.bake_deform_animation(context, armature, action)
        if baked:
            AnimationRigSanitizer.setup_clean_nla_export(armature, baked)
            self.report({"INFO"}, f"Successfully baked deform Action '{baked.name}' and assigned to solo NLA track.")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Failed to bake deform animation.")
            return {"CANCELLED"}


class LOD_OT_export_engine_package(Operator):
    bl_idname = "lod_tool.export_engine_package"
    bl_label = "1-Click Export Asset"
    bl_description = "Export complete LOD package with meshes, packed PBR textures, and baked animations"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and hasattr(context.scene, "lod_tool") and len(context.scene.lod_tool.lods) > 0)

    def execute(self, context: Any) -> set[str]:
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

        # Optional: Auto-pack PBR textures
        if props.export_packed_textures:
            try:
                bpy.ops.lod_tool.pack_pbr_textures()
            except (RuntimeError, AttributeError, OSError) as exc:
                logger.warning("Auto PBR texture packing failed during export: %s", exc)

        # Optional: Auto-bake Armature animation if present
        if props.bake_animations and context.active_object:
            obj = context.active_object
            armature = (
                obj
                if obj.type == "ARMATURE"
                else (obj.parent if obj.parent and obj.parent.type == "ARMATURE" else None)
            )
            if armature and armature.animation_data and armature.animation_data.action:
                try:
                    bpy.ops.lod_tool.bake_rig_animation()
                except (RuntimeError, AttributeError, ValueError) as exc:
                    logger.warning("Auto animation baking failed during export: %s", exc)

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


def register_exporters() -> None:
    if not bpy:
        return
    bpy.utils.register_class(LOD_OT_pack_pbr_textures)
    bpy.utils.register_class(LOD_OT_bake_rig_animation)
    bpy.utils.register_class(LOD_OT_export_engine_package)


def unregister_exporters() -> None:
    if not bpy:
        return
    bpy.utils.unregister_class(LOD_OT_export_engine_package)
    bpy.utils.unregister_class(LOD_OT_bake_rig_animation)
    bpy.utils.unregister_class(LOD_OT_pack_pbr_textures)
