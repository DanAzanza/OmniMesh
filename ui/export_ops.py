# pyright: reportInvalidTypeForm=none
"""
OmniMesh Export & Baking Operators.
Provides UI operators for 1-click multi-engine packaging, PBR texture packing,
and animation baking.
"""

from __future__ import annotations

import logging
import os
import re
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import bpy
    from bpy.types import Operator
else:
    try:
        import bpy
        from bpy.types import Operator
    except ImportError:
        bpy = None
        Operator = object

try:
    from ..core.animations import AnimationRigSanitizer
    from ..core.pbr_presets import PBRExportPresetManager
    from ..core.textures import TextureChannelPacker, TexturePoolManager
    from ..exporters.engine_export import AssetMeshResolver, PreFlightValidator, resolve_export_asset_name
    from ..exporters.manager import ExporterManager
    from .utils import get_lod0_mesh_objects, resolve_effective_asset_name, resolve_lod_context
except (ImportError, ValueError):
    from core.animations import AnimationRigSanitizer
    from core.pbr_presets import PBRExportPresetManager
    from core.textures import TextureChannelPacker, TexturePoolManager
    from exporters.engine_export import AssetMeshResolver, PreFlightValidator, resolve_export_asset_name
    from exporters.manager import ExporterManager
    from ui.utils import get_lod0_mesh_objects, resolve_effective_asset_name, resolve_lod_context

logger = logging.getLogger(__name__)


class LOD_OT_pack_pbr_textures(Operator):
    bl_idname = "lod_tool.pack_pbr_textures"
    bl_label = "Pack & Export Textures"
    bl_description = "Channel-pack PBR textures for the selected target game engine"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        props, _, _ = resolve_lod_context(context)
        return bool(props)

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"CANCELLED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            self.report({"ERROR"}, "LOD tool properties not found.")
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
        objs_to_check = get_lod0_mesh_objects(context) or (
            list(context.selected_objects) if getattr(context, "selected_objects", None) else []
        )
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

        # Resolve active PBR preset
        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", "")
        if not preset_id:
            engine_map = {
                "UE5": "unreal_engine_5",
                "UNITY_6": "unity_hdrp_maskmap",
                "MSFS_2024": "msfs_2024_comp",
            }
            preset_id = engine_map.get(target_engine, "unreal_engine_5")

        try:
            preset = PBRExportPresetManager.get_preset(preset_id)
        except Exception as exc:
            logger.warning("Could not load export preset '%s', falling back: %s", preset_id, exc)
            preset = PBRExportPresetManager.get_preset("unreal_engine_5")

        strategy = getattr(props, "pbr_export_texture_strategy", "CONVERT_PNG")
        bit_depth = int(getattr(props, "pbr_export_bit_depth", "8"))
        naming_pattern = (
            getattr(props, "pbr_export_naming_pattern", "{asset}_{material}{suffix}{udim}")
            or "{asset}_{material}{suffix}{udim}"
        )
        raw_asset = getattr(props, "export_base_name", "").strip()
        if not raw_asset:
            raw_asset = resolve_effective_asset_name(context, props)
        asset_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_asset) if raw_asset else "SM_Asset"

        all_futures: list[Any] = []
        packed_count = 0

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            return {"CANCELLED"}

        for mat in materials:
            try:
                futs = TextureChannelPacker.pack_material_preset(
                    material=mat,
                    preset=preset,
                    export_dir=tex_dir,
                    asset_name=asset_name,
                    target_size=target_size,
                    bit_depth=bit_depth,
                    strategy=strategy,
                    naming_pattern=naming_pattern,
                    context=context,
                    blend_data=bdata,
                )
                if futs:
                    all_futures.extend(futs)
                    packed_count += 1
            except Exception as exc:
                logger.error("Failed packing texture set for material '%s': %s", getattr(mat, "name", "Mat"), exc)

        # Synchronize background disk compression barrier
        if all_futures:
            TexturePoolManager.wait_all(all_futures, timeout=60.0)

        self.report(
            {"INFO"},
            f"Successfully packed {packed_count} PBR texture set(s) using '{preset.get('name', preset_id)}' into {tex_dir}",
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

    def execute(self, context: Any) -> set[Any]:
        if not bpy:
            return {"CANCELLED"}
        obj = context.active_object
        armature = obj if obj.type == "ARMATURE" else obj.parent

        if not armature or not armature.animation_data or not armature.animation_data.action:
            self.report({"WARNING"}, "No active Action found on Armature.")
            return {"CANCELLED"}

        action = armature.animation_data.action
        baked = AnimationRigSanitizer.bake_deform_animation(context, armature, action, blend_data=context.blend_data)
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
        if not bpy or not context:
            return False
        props, _, _ = resolve_lod_context(context)
        return bool(props and len(getattr(props, "lods", [])) > 0)

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"CANCELLED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            self.report({"ERROR"}, "LOD configuration context could not be resolved.")
            return {"CANCELLED"}

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        errors = PreFlightValidator.run_checks(context, blend_data=bdata)
        if errors:
            for err in errors:
                self.report({"ERROR"}, f"[Pre-Flight Gate] {err}")
            return {"CANCELLED"}

        export_dir = bpy.path.abspath(props.export_directory)

        raw_name = resolve_export_asset_name(context, props)
        asset_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_name) or "SM_Asset"
        target = props.target_engine

        # Auto-pack PBR textures if enabled
        if props.export_packed_textures:
            try:
                cast(Any, bpy.ops).lod_tool.pack_pbr_textures()
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
                    cast(Any, bpy.ops).lod_tool.bake_rig_animation()
                except (RuntimeError, AttributeError, ValueError) as exc:
                    logger.warning("Auto animation baking failed during export: %s", exc)

        pkg_base = asset_name
        if target == "MSFS_2024" and getattr(props, "msfs_export_full_package", True):
            # If active asset is interior or variant, resolve the base package name
            payload = (
                AssetMeshResolver.resolve_payload(context, asset_name, blend_data=bdata) if AssetMeshResolver else None
            )
            if payload and payload.parent_asset_name:
                pkg_base = payload.parent_asset_name
            else:
                pkg_base = asset_name.split("_Interior")[0]

        success, message = ExporterManager.export_asset(
            context,
            target,
            export_dir,
            asset_name,
            blend_data=getattr(context, "blend_data", None),
            full_package=getattr(props, "msfs_export_full_package", True),
            package_name=pkg_base,
        )

        if success:
            self.report({"INFO"}, f"[LOD Export] {message}")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"[LOD Export Failed] {message}")
            return {"CANCELLED"}


EXPORT_OPS_CLASSES = (
    LOD_OT_pack_pbr_textures,
    LOD_OT_bake_rig_animation,
    LOD_OT_export_engine_package,
)


def register_export_ops() -> None:
    if not bpy:
        return
    for cls in EXPORT_OPS_CLASSES:
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
        bpy.utils.register_class(cls)


def unregister_export_ops() -> None:
    if not bpy:
        return
    for cls in reversed(EXPORT_OPS_CLASSES):
        existing = getattr(bpy.types, cls.__name__, None)
        if existing is not None:
            try:
                bpy.utils.unregister_class(existing)
            except Exception as exc:
                logger.debug("Safe unregister skipped %s: %s", cls.__name__, exc)
