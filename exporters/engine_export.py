"""
Master Engine Export Router & Pre-Flight Quality Gate with PBR Texture, Animation & Live Bridge Integration.
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
    from ..bridges.manager import BridgeManager
    from ..core.animations import AnimationRigSanitizer
    from ..core.textures import TextureChannelPacker, TexturePoolManager
except (ImportError, ValueError):
    from bridges.manager import BridgeManager
    from core.animations import AnimationRigSanitizer
    from core.textures import TextureChannelPacker, TexturePoolManager

from .godot_export import GodotExporter
from .msfs_export import MSFSExporter
from .ue5_export import UE5Exporter
from .unity_export import UnityExporter

logger = logging.getLogger(__name__)


class PreFlightValidator:
    @staticmethod
    def run_checks(context: Any) -> list[str]:
        if not context or not getattr(context, "scene", None):
            return ["Blender context not available."]
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            return ["LOD tool properties not initialized on scene."]
        errors: list[str] = []

        if len(props.lods) == 0:
            errors.append("No LOD tiers configured.")
            return errors

        valid_objs = []
        for tier in props.lods:
            try:
                obj = tier.generated_obj
                obj_name = getattr(obj, "name", None)
                if obj and (not bpy or (isinstance(obj_name, str) and obj_name in bpy.data.objects)):
                    valid_objs.append(obj)
            except (ReferenceError, AttributeError, KeyError) as exc:
                logger.debug("Failed to resolve tier generated_obj: %s", exc)

        if len(valid_objs) != len(props.lods):
            errors.append("Some configured LOD tiers have not been generated yet. Run 'Generate All LODs' first.")
            return errors

        # Empty geometry check
        for i, obj in enumerate(valid_objs):
            if (
                getattr(obj, "type", "") == "MESH"
                and getattr(obj, "data", None)
                and hasattr(obj.data, "polygons")
                and len(obj.data.polygons) == 0
            ):
                errors.append(f"LOD{i} ('{obj.name}') has 0 polygons (empty geometry).")

        # Pivot / origin matching
        lod0_pivot = valid_objs[0].matrix_world.translation if hasattr(valid_objs[0], "matrix_world") else None
        for i, obj in enumerate(valid_objs):
            if lod0_pivot and hasattr(obj, "matrix_world"):
                if (obj.matrix_world.translation - lod0_pivot).length > 1e-4:
                    errors.append(f"LOD{i} origin does not match LOD0 pivot.")

            scale = getattr(obj, "scale", None)
            if scale:
                sx = getattr(scale, "x", scale[0] if isinstance(scale, (list, tuple)) else 1.0)
                sy = getattr(scale, "y", scale[1] if isinstance(scale, (list, tuple)) else 1.0)
                sz = getattr(scale, "z", scale[2] if isinstance(scale, (list, tuple)) else 1.0)
                if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4:
                    errors.append(
                        f"LOD{i} has unapplied scale ({round(sx, 2)}, {round(sy, 2)}, {round(sz, 2)}). Apply transforms."
                    )

        # Material checks
        for i, obj in enumerate(valid_objs):
            if len(getattr(obj, "material_slots", [])) == 0 and len(getattr(valid_objs[0], "material_slots", [])) > 0:
                errors.append(f"LOD{i} is missing material slots.")
            for slot_idx, slot in enumerate(getattr(obj, "material_slots", [])):
                if slot.material is None:
                    errors.append(f"LOD{i} has unassigned material in slot {slot_idx}.")

        # Asset name validation
        if props.export_base_name:
            import re

            if re.search(r'[<>:"/\\|?*\x00-\x1f]', props.export_base_name):
                errors.append(f"Export asset name '{props.export_base_name}' contains invalid characters.")

        # Export directory validation
        export_dir_str = props.export_directory.strip() if props.export_directory else ""
        if not export_dir_str:
            errors.append("Export directory path is empty.")
        elif "\x00" in export_dir_str:
            errors.append("Export directory path contains invalid null bytes.")

        return errors


class LOD_OT_pack_pbr_textures(Operator):
    bl_idname = "lod_tool.pack_pbr_textures"
    bl_label = "Pack & Export Textures"
    bl_description = "Channel-pack PBR textures for the selected target game engine"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(
            bpy and context and (getattr(context, "active_object", None) or getattr(context.scene, "lod_tool", None))
        )

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        if not props:
            self.report({"ERROR"}, "LOD tool scene properties not found.")
            return {"CANCELLED"}

        export_dir = (
            bpy.path.abspath(props.export_directory) if props.export_directory else bpy.path.abspath("//Export/")
        )
        tex_dir = os.path.join(export_dir, "Textures")
        os.makedirs(tex_dir, exist_ok=True)

        res_str = str(getattr(props, "texture_max_resolution", "2048"))
        if res_str.isdigit():
            res = int(res_str)
            target_size = (res, res)
        else:
            target_size = (2048, 2048)

        target_engine = props.target_engine

        materials: set[Any] = set()
        objs_to_check = list(context.selected_objects) if getattr(context, "selected_objects", None) else []
        if not objs_to_check and getattr(context, "active_object", None):
            objs_to_check.append(context.active_object)
        if not objs_to_check and len(props.lods) > 0:
            for tier in props.lods:
                if tier.generated_obj:
                    objs_to_check.append(tier.generated_obj)

        for obj in objs_to_check:
            for slot in getattr(obj, "material_slots", []):
                if slot.material:
                    materials.add(slot.material)

        if not materials:
            self.report({"WARNING"}, "No materials found on selected or LOD objects.")
            return {"CANCELLED"}

        import re

        packed_count = 0
        for mat in materials:
            mat_name = re.sub(r"[^\w\-_\.]", "_", mat.name)
            try:
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
            except Exception as exc:
                logger.error("Failed packing texture set for material '%s': %s", mat.name, exc)

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


class LOD_OT_sync_live_bridge(Operator):
    bl_idname = "lod_tool.sync_live_bridge"
    bl_label = "Sync to Engine"
    bl_description = "Synchronize exported asset and textures with active game engine or project directory"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and hasattr(context.scene, "lod_tool"))

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"CANCELLED"}
        props = context.scene.lod_tool
        export_dir = bpy.path.abspath(props.export_directory)
        asset_name = props.export_base_name or "SM_Asset"
        target = props.target_engine
        proj_dir = bpy.path.abspath(props.engine_project_path) if props.engine_project_path else ""

        ok, msg = BridgeManager.sync_asset(context, target, export_dir, asset_name, proj_dir)
        if ok:
            self.report({"INFO"}, f"[Live Bridge] {msg}")
            return {"FINISHED"}
        else:
            self.report({"WARNING"}, f"[Live Bridge] {msg}")
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
        import re

        raw_name = props.export_base_name.strip() if props.export_base_name else "SM_Asset"
        asset_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_name) or "SM_Asset"
        target = props.target_engine

        # Auto-pack PBR textures if enabled
        if props.export_packed_textures:
            try:
                bpy.ops.lod_tool.pack_pbr_textures()
                TexturePoolManager.wait_all([], timeout=30.0)
            except (RuntimeError, AttributeError, OSError) as exc:
                logger.warning("Auto PBR texture packing failed during export: %s", exc)

        # Auto-bake Armature animation if enabled
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

            # Auto Live Bridge Trigger if enabled
            if props.enable_live_sync:
                proj_dir = bpy.path.abspath(props.engine_project_path) if props.engine_project_path else ""
                bridge_ok, bridge_msg = BridgeManager.sync_asset(context, target, export_dir, asset_name, proj_dir)
                if bridge_ok:
                    self.report({"INFO"}, f"[Live Bridge] {bridge_msg}")
                else:
                    self.report({"WARNING"}, f"[Live Bridge] {bridge_msg}")

            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"[LOD Export Failed] {message}")
            return {"CANCELLED"}


def register_exporters() -> None:
    if not bpy:
        return
    bpy.utils.register_class(LOD_OT_pack_pbr_textures)
    bpy.utils.register_class(LOD_OT_bake_rig_animation)
    bpy.utils.register_class(LOD_OT_sync_live_bridge)
    bpy.utils.register_class(LOD_OT_export_engine_package)


def unregister_exporters() -> None:
    if not bpy:
        return
    bpy.utils.unregister_class(LOD_OT_export_engine_package)
    bpy.utils.unregister_class(LOD_OT_sync_live_bridge)
    bpy.utils.unregister_class(LOD_OT_bake_rig_animation)
    bpy.utils.unregister_class(LOD_OT_pack_pbr_textures)
