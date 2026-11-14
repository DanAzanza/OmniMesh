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
    from ..core.impostor import resolve_impostor_export_dir
    from ..core.impostor_math import normalize_impostor_grid_size, resolve_effective_impostor_mode
    from ..core.impostor_repacker import ImpostorTextureRepacker, find_canonical_impostor_sources
    from ..core.pbr_presets import PBRExportPresetManager
    from ..core.textures import TextureChannelPacker, TexturePoolManager
    from ..exporters.engine_export import AssetMeshResolver, PreFlightValidator, resolve_export_asset_name
    from ..exporters.manager import ExporterManager
    from ..exporters.shaders import export_octahedral_companion_bundle, resolve_shader_engine_for_preset
    from .rna_helpers import register_classes, unregister_classes
    from .utils import (
        get_lod0_mesh_objects,
        parse_sphere_center,
        resolve_active_pbr_preset,
        resolve_effective_asset_name,
        resolve_lod_context,
    )
except (ImportError, ValueError):
    from core.animations import AnimationRigSanitizer
    from core.impostor import resolve_impostor_export_dir
    from core.impostor_math import normalize_impostor_grid_size, resolve_effective_impostor_mode
    from core.impostor_repacker import ImpostorTextureRepacker, find_canonical_impostor_sources
    from core.pbr_presets import PBRExportPresetManager
    from core.textures import TextureChannelPacker, TexturePoolManager
    from exporters.engine_export import AssetMeshResolver, PreFlightValidator, resolve_export_asset_name
    from exporters.manager import ExporterManager
    from exporters.shaders import export_octahedral_companion_bundle, resolve_shader_engine_for_preset
    from ui.rna_helpers import register_classes, unregister_classes
    from ui.utils import (
        get_lod0_mesh_objects,
        parse_sphere_center,
        resolve_active_pbr_preset,
        resolve_effective_asset_name,
        resolve_lod_context,
    )

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
            if _is_impostor_flagged(obj):
                continue
            for slot in getattr(obj, "material_slots", []):
                if slot.material and slot.material.get("_is_impostor") not in (True, 1):
                    materials.add(slot.material)

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            return {"CANCELLED"}

        raw_effective = resolve_effective_asset_name(context, props) or ""
        raw_asset = getattr(props, "export_base_name", "").strip() or raw_effective
        asset_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_asset) if raw_asset else "SM_Asset"
        effective_base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_effective) if raw_effective else asset_name

        imp_obj = _find_impostor_object(bdata, objs_to_check, [effective_base, asset_name])
        if not materials and imp_obj is None:
            self.report({"WARNING"}, "No materials found on selected or LOD objects.")
            return {"CANCELLED"}

        # Resolve active PBR preset
        preset_id, preset = resolve_active_pbr_preset(props, target_engine, preset_manager=PBRExportPresetManager)

        strategy = getattr(props, "pbr_export_texture_strategy", "CONVERT_PNG")
        bit_depth = int(getattr(props, "pbr_export_bit_depth", "8"))
        naming_pattern = (
            getattr(props, "pbr_export_naming_pattern", "{asset}_{material}{suffix}{udim}")
            or "{asset}_{material}{suffix}{udim}"
        )

        all_futures: list[Any] = []
        packed_count = 0

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

        # Repack canonical engine-independent Impostor atlas textures if present
        impostor_packed = _repack_asset_impostor_if_present(
            props=props,
            imp_obj=imp_obj,
            candidate_names=[effective_base, asset_name],
            tex_dir=tex_dir,
            preset_id=preset_id,
            preset=preset,
            bdata=bdata,
        )
        packed_count += impostor_packed

        if packed_count == 0 and not materials:
            self.report({"WARNING"}, "No materials or canonical impostor textures found to pack.")
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Successfully packed {packed_count} PBR texture set(s) using '{preset.get('name', preset_id)}' into {tex_dir}",
        )
        return {"FINISHED"}


def _is_impostor_flagged(obj: Any) -> bool:
    getter = getattr(obj, "get", None)
    return bool(getter and getter("_is_impostor", False) in (True, 1))


def _find_impostor_object(bdata: Any, objs_to_check: list[Any], candidate_names: list[str]) -> Any:
    """Finds an associated Impostor object from active objects or BlendData."""
    for obj in objs_to_check:
        if _is_impostor_flagged(obj):
            return obj

    exact_names = {f"{name}_LOD_Impostor" for name in candidate_names if name}
    all_objs = list(getattr(bdata, "objects", None) or [])
    for obj in all_objs:
        if getattr(obj, "name", "") in exact_names:
            return obj

    for obj in all_objs:
        if not _is_impostor_flagged(obj):
            continue
        obj_name = getattr(obj, "name", "")
        if any(obj_name.startswith(name) for name in candidate_names if name):
            return obj
    return None


def _extract_impostor_material_paths(impostor_obj: Any) -> dict[str, str]:
    """Reads linked BaseColor, Normal, and ORM image filepaths from an impostor material."""
    paths: dict[str, str] = {}
    if not impostor_obj:
        return paths
    data = getattr(impostor_obj, "data", None)
    mats = list(getattr(data, "materials", None) or [])
    key_map = {
        "Tex_BaseColor": "BaseColor",
        "Tex_Normal": "Normal",
        "Tex_ORM": "ORM",
    }
    for mat in mats:
        node_tree = getattr(mat, "node_tree", None)
        nodes = getattr(node_tree, "nodes", None)
        if not nodes:
            continue
        for node_name, key in key_map.items():
            node = nodes.get(node_name) if hasattr(nodes, "get") else None
            img = getattr(node, "image", None)
            raw_fp = getattr(img, "filepath", "") if img else ""
            if not raw_fp:
                continue
            resolved_fp = bpy.path.abspath(raw_fp) if bpy and hasattr(bpy, "path") else raw_fp
            if isinstance(resolved_fp, str) and os.path.isfile(resolved_fp):
                paths[key] = resolved_fp
    return paths


def _repack_asset_impostor_if_present(
    props: Any,
    imp_obj: Any,
    candidate_names: list[str],
    tex_dir: str,
    preset_id: str,
    preset: dict[str, Any],
    bdata: Any,
) -> int:
    """Repacks baked canonical Impostor textures and companion Octahedral files for the active preset."""
    dedup_names = list(dict.fromkeys(n for n in candidate_names if n))
    raw_imp_base = imp_obj.get("_impostor_base_name", "") if imp_obj else ""
    if isinstance(raw_imp_base, str) and raw_imp_base:
        dedup_names.insert(0, raw_imp_base)
    elif imp_obj and getattr(imp_obj, "name", "").endswith("_LOD_Impostor"):
        dedup_names.insert(0, imp_obj.name[: -len("_LOD_Impostor")])
    dedup_names = list(dict.fromkeys(dedup_names))

    if not dedup_names:
        return 0

    source_convention = "CANONICAL"
    if imp_obj is not None and imp_obj.get("_impostor_canonical") not in (True, 1):
        legacy_eng = imp_obj.get("_impostor_target_engine")
        if isinstance(legacy_eng, str) and legacy_eng:
            source_convention = legacy_eng

    mat_paths = _extract_impostor_material_paths(imp_obj)
    raw_dir = getattr(props, "export_directory", "")
    default_imp_dir = (
        resolve_impostor_export_dir(raw_dir, blend_data=bdata)
        if isinstance(getattr(bdata, "filepath", None), str)
        else tex_dir
    )
    search_dirs = list(dict.fromkeys(d for d in (tex_dir, default_imp_dir) if d))

    sources = None
    for base in dedup_names:
        sources = find_canonical_impostor_sources(
            base_name=base,
            search_dirs=search_dirs,
            material_paths=mat_paths,
            source_convention=source_convention,
        )
        if sources is not None:
            break
    if sources is None:
        return 0

    repacked = ImpostorTextureRepacker.repack_impostor_textures(
        sources=sources,
        output_dir=tex_dir,
        target_engine=getattr(props, "target_engine", "UE5"),
        preset=preset,
    )
    if not repacked:
        return 0

    mode_val = imp_obj.get("_impostor_mode") if imp_obj else None
    mode = (
        mode_val
        if isinstance(mode_val, str) and mode_val
        else resolve_effective_impostor_mode(
            str(getattr(props, "impostor_mode", "ORTHO_3_AXES")),
            bool(getattr(props, "impostor_render_underside", False)),
        )
    )
    if mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
        raw_grid = imp_obj.get("_impostor_grid_size") if imp_obj else getattr(props, "impostor_grid_size", 8)
        grid_size = (
            normalize_impostor_grid_size(raw_grid)
            if isinstance(raw_grid, int) and not isinstance(raw_grid, bool)
            else 8
        )
        raw_radius = imp_obj.get("_impostor_sphere_radius", 1.0) if imp_obj else 1.0
        sphere_radius = float(raw_radius) if isinstance(raw_radius, (int, float)) else 1.0
        sphere_center = parse_sphere_center(imp_obj.get("_impostor_sphere_center") if imp_obj else "")
        shader_eng = resolve_shader_engine_for_preset(preset_id, getattr(props, "target_engine", "UE5"))
        try:
            export_octahedral_companion_bundle(
                base_name=sources.base_name,
                output_dir=tex_dir,
                target_engine=shader_eng,
                grid_size=grid_size,
                sphere_radius=sphere_radius,
                sphere_center=sphere_center,
                mode=mode,
                packed_maps=repacked,
                alpha_scissor=0.5,
            )
        except Exception as exc:
            logger.debug("Skipped companion shader update during PBR repack: %s", exc)

    return 1


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
    register_classes(bpy, EXPORT_OPS_CLASSES, logger_inst=logger)


def unregister_export_ops() -> None:
    unregister_classes(bpy, EXPORT_OPS_CLASSES, logger_inst=logger)
