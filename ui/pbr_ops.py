# pyright: reportInvalidTypeForm=none
"""
PBR Texture Set Importer and Slot Auto-Matcher Operators.
Preset CRUD operations are modularized in ui.pbr_preset_ops and ui.preset_ops.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.props import CollectionProperty, StringProperty
    from bpy.types import Operator, OperatorFileListElement
else:
    try:
        import bpy
        from bpy.props import CollectionProperty, StringProperty
        from bpy.types import Operator, OperatorFileListElement
    except ImportError:
        bpy = None
        Operator = object
        OperatorFileListElement = object  # type: ignore

        def _mock_prop(*args: Any, **kwargs: Any) -> Any:
            return None

        StringProperty = _mock_prop  # type: ignore
        CollectionProperty = _mock_prop  # type: ignore

try:
    from ..core.pbr_importer import (
        BatchMaterialSlotMatcher,
        ShaderGraphBuilder,
    )
    from ..core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImportPresetManager,
    )
    from ..core.texture_resolver import PBRTextureResolver
    from .lod_preset_ops import LOD_OT_delete_lod_preset  # noqa: F401
    from .pbr_preset_ops import (
        LOD_OT_add_export_preset_map,
        LOD_OT_add_preset_map,
        LOD_OT_delete_export_preset,
        LOD_OT_delete_export_preset_map,
        LOD_OT_delete_import_preset,
        LOD_OT_delete_preset_map,
        LOD_OT_duplicate_export_preset,
        LOD_OT_duplicate_preset,
        LOD_OT_open_presets_directory,
        LOD_OT_reload_pbr_presets,
        LOD_OT_reset_pbr_preset,
        LOD_OT_save_export_preset,
    )
    from .utils import (
        get_lod0_mesh_objects,
        get_selected_mesh_objects,
        resolve_lod_context,
        safe_report,
    )
except (ImportError, ValueError):
    from core.pbr_importer import (
        BatchMaterialSlotMatcher,
        ShaderGraphBuilder,
    )
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImportPresetManager,
    )
    from core.texture_resolver import PBRTextureResolver
    from ui.lod_preset_ops import LOD_OT_delete_lod_preset  # noqa: F401
    from ui.pbr_preset_ops import (
        LOD_OT_add_export_preset_map,
        LOD_OT_add_preset_map,
        LOD_OT_delete_export_preset,
        LOD_OT_delete_export_preset_map,
        LOD_OT_delete_import_preset,
        LOD_OT_delete_preset_map,
        LOD_OT_duplicate_export_preset,
        LOD_OT_duplicate_preset,
        LOD_OT_open_presets_directory,
        LOD_OT_reload_pbr_presets,
        LOD_OT_reset_pbr_preset,
        LOD_OT_save_export_preset,
    )
    from ui.utils import (
        get_lod0_mesh_objects,
        get_selected_mesh_objects,
        resolve_lod_context,
        safe_report,
    )


class LOD_OT_import_pbr_set(Operator):
    """Inspect and resolve PBR textures across all LOD0 materials using the active preset."""

    bl_idname = "lod_tool.import_pbr_set"
    bl_label = "Import PBR Textures"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    files: CollectionProperty(type=OperatorFileListElement)

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)

        # 1. Resolve search roots from directory, props, or blend file
        search_roots: list[str] = []
        dir_val = getattr(self, "directory", "")
        if dir_val and os.path.isdir(dir_val):
            search_roots.append(dir_val)

        pbr_dir = getattr(props, "pbr_import_directory", "") if props else ""
        if pbr_dir:
            abs_p = bpy.path.abspath(pbr_dir)
            if os.path.isdir(abs_p) and abs_p not in search_roots:
                search_roots.append(abs_p)

        eng_dir = getattr(props, "engine_import_directory", "") if props else ""
        if eng_dir:
            abs_eng = bpy.path.abspath(eng_dir)
            if os.path.isdir(abs_eng) and abs_eng not in search_roots:
                search_roots.append(abs_eng)

        blend_file = getattr(getattr(bpy, "data", None), "filepath", None)
        if blend_file:
            blend_dir = os.path.dirname(os.path.abspath(blend_file))
            if blend_dir and blend_dir not in search_roots:
                search_roots.append(blend_dir)
                parent_dir = os.path.dirname(blend_dir)
                if parent_dir and parent_dir not in search_roots:
                    search_roots.append(parent_dir)

        if not search_roots:
            safe_report(self, {"WARNING"}, "No texture or project directory found. Please specify a folder.")
            return {"CANCELLED"}

        if search_roots and props and hasattr(props, "pbr_import_directory"):
            props.pbr_import_directory = search_roots[0]

        # 2. Resolve target LOD0 meshes (consistent with Modify panel)
        lod0_meshes = get_lod0_mesh_objects(context)
        if not lod0_meshes:
            lod0_meshes = get_selected_mesh_objects(context)
        if not lod0_meshes and hasattr(context, "scene"):
            lod0_meshes = [o for o in getattr(context.scene, "objects", []) if getattr(o, "type", "") == "MESH"]

        if not lod0_meshes:
            safe_report(self, {"WARNING"}, "No LOD0 or target mesh objects found in scene.")
            return {"CANCELLED"}

        # 3. Extract unique materials across all LOD0 meshes
        unique_materials = PBRTextureResolver.extract_unique_materials_from_objects(lod0_meshes)

        asset_name = getattr(props, "export_base_name", "") if props else ""
        if not asset_name and lod0_meshes:
            raw_name = getattr(lod0_meshes[0], "name", "")
            asset_name = raw_name.split("_LOD")[0].split("_Collider")[0]

        preset_id = getattr(props, "pbr_import_preset", "") if props else DEFAULT_PRESET_ID
        preset = PBRImportPresetManager.get_preset(preset_id)

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            return {"CANCELLED"}

        # 4. Resolve textures across material nodes
        summary = PBRTextureResolver.resolve_material_textures(
            materials=unique_materials,
            search_roots=search_roots,
            asset_name=asset_name,
            preset=preset,
            blend_filepath=blend_file,
            make_relative=True,
            blend_data=bdata,
        )

        # 5. Populate shader graphs for materials with 0 texture nodes if matching folder textures exist
        populated_slots = 0
        if search_roots:
            primary_dir = search_roots[0]
            ao_mode = getattr(props, "pbr_import_ao_mode", "MULTIPLY") if props else "MULTIPLY"
            preserve = True
            path_mode = "RELATIVE"

            for obj in lod0_meshes:
                for slot in getattr(obj, "material_slots", []):
                    mat = getattr(slot, "material", None)
                    if mat and getattr(mat, "use_nodes", False) and getattr(mat, "node_tree", None):
                        tex_nodes = [n for n in mat.node_tree.nodes if getattr(n, "type", "") == "TEX_IMAGE"]
                        if not tex_nodes:
                            matched = BatchMaterialSlotMatcher.match_directory_to_slots(obj, primary_dir, preset=preset)
                            if matched and slot.name in matched:
                                if ShaderGraphBuilder.build_pbr_graph(
                                    mat,
                                    matched[slot.name],
                                    preset=preset,
                                    preserve_existing=preserve,
                                    ao_blend_mode=ao_mode,
                                    path_mode=path_mode,
                                    blend_data=bdata,
                                ):
                                    populated_slots += 1

        # 6. Report results: Error Toast if unresolved textures, INFO Toast if success
        if summary.has_errors:
            unresolved_by_mat: dict[str, list[str]] = {}
            for unres in summary.unresolved:
                unresolved_by_mat.setdefault(unres.material_name, []).append(unres.expected_type)
                logger.warning(
                    "Missing texture in material '%s' node '%s' (type: %s, original path: %s)",
                    unres.material_name,
                    unres.node_name,
                    unres.expected_type,
                    unres.original_filepath,
                )

            mat_details = ", ".join(f"'{m}' ({'/'.join(set(t))})" for m, t in list(unresolved_by_mat.items())[:3])
            if len(unresolved_by_mat) > 3:
                mat_details += f" +{len(unresolved_by_mat) - 3} more"

            err_msg = f"PBR Import: {len(summary.unresolved)} texture(s) missing in {mat_details}. Check console."
            safe_report(self, {"ERROR"}, err_msg)
            return {"FINISHED"}

        relinked_total = summary.relinked + populated_slots
        if relinked_total > 0:
            msg = f"PBR Import: {summary.relinked} texture(s) relinked across {len(unique_materials)} LOD0 material(s)."
            safe_report(self, {"INFO"}, msg)
        else:
            msg = f"PBR Import: All {summary.total_nodes_checked} textures verified and valid."
            safe_report(self, {"INFO"}, msg)

        return {"FINISHED"}

    def invoke(self, context: Any, event: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)

        pbr_dir = getattr(props, "pbr_import_directory", "") if props else ""
        blend_file = getattr(getattr(bpy, "data", None), "filepath", None)

        if (pbr_dir and os.path.isdir(bpy.path.abspath(pbr_dir))) or blend_file:
            if pbr_dir and os.path.isdir(bpy.path.abspath(pbr_dir)):
                self.directory = bpy.path.abspath(pbr_dir)
            return self.execute(context)

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LOD_OT_auto_match_pbr_folder(Operator):
    """Scan directory and match texture sets to mesh material slots using active preset."""

    bl_idname = "lod_tool.auto_match_pbr_folder"
    bl_label = "Auto-Match PBR Folder"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")

    def execute(self, context: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        active_obj = context.active_object
        if not active_obj or active_obj.type != "MESH":
            safe_report(self, {"WARNING"}, "Please select a target mesh object.")
            return {"CANCELLED"}

        folder_to_scan = self.directory
        if not folder_to_scan and getattr(props, "pbr_import_directory", ""):
            folder_to_scan = bpy.path.abspath(props.pbr_import_directory)

        if not folder_to_scan or not os.path.isdir(folder_to_scan):
            safe_report(self, {"WARNING"}, "Please choose a valid directory.")
            return {"CANCELLED"}

        # Remember directory in props
        if hasattr(props, "pbr_import_directory"):
            props.pbr_import_directory = folder_to_scan

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        preset = PBRImportPresetManager.get_preset(preset_id)
        matched = BatchMaterialSlotMatcher.match_directory_to_slots(active_obj, folder_to_scan, preset=preset)

        if not matched:
            safe_report(self, {"WARNING"}, "No texture sets matched object material slots.")
            return {"CANCELLED"}

        ao_mode = getattr(props, "pbr_import_ao_mode", "MULTIPLY")
        preserve = True
        path_mode = "RELATIVE"
        count = 0

        for slot_name, tex_dict in matched.items():
            if not tex_dict:
                continue
            slot_mat = None
            target_slot = None
            for slot in active_obj.material_slots:
                if slot.name == slot_name:
                    slot_mat = slot.material
                    target_slot = slot
                    break
            if not slot_mat:
                slot_mat = bpy.data.materials.new(name=slot_name)
                slot_mat.use_nodes = True
                if target_slot:
                    target_slot.material = slot_mat
                else:
                    empty_slot = next((s for s in active_obj.material_slots if s.material is None), None)
                    if empty_slot:
                        empty_slot.material = slot_mat
                    else:
                        active_obj.data.materials.append(slot_mat)

            bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
            if bdata is None:
                continue
            if ShaderGraphBuilder.build_pbr_graph(
                slot_mat,
                tex_dict,
                preset=preset,
                preserve_existing=preserve,
                ao_blend_mode=ao_mode,
                path_mode=path_mode,
                blend_data=bdata,
            ):
                count += 1

        summary = f"Matched {count} material slot(s) using '{preset.get('name', preset_id)}'."
        safe_report(self, {"INFO"}, summary)
        return {"FINISHED"}

    def invoke(self, context: Any, event: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        imp_dir = getattr(props, "pbr_import_directory", "")
        if imp_dir:
            abs_dir = bpy.path.abspath(imp_dir)
            if os.path.isdir(abs_dir):
                self.directory = abs_dir
                return self.execute(context)

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LOD_OT_relink_project_textures(Operator):
    """Compatibility alias redirecting to Import PBR Textures."""

    bl_idname = "lod_tool.relink_project_textures"
    bl_label = "Auto-Relink Missing Textures"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}
        op_fn = getattr(getattr(bpy.ops, "lod_tool", None), "import_pbr_set", None)
        if callable(op_fn):
            res = op_fn(directory=getattr(self, "directory", ""))
            return res if isinstance(res, set) else {"FINISHED"}
        return {"FINISHED"}


PBR_OPERATOR_CLASSES = (
    LOD_OT_import_pbr_set,
    LOD_OT_auto_match_pbr_folder,
    LOD_OT_relink_project_textures,
)

__all__ = [
    "PBR_OPERATOR_CLASSES",
    "LOD_OT_import_pbr_set",
    "LOD_OT_auto_match_pbr_folder",
    "LOD_OT_relink_project_textures",
    "LOD_OT_reload_pbr_presets",
    "LOD_OT_reset_pbr_preset",
    "LOD_OT_duplicate_preset",
    "LOD_OT_duplicate_export_preset",
    "LOD_OT_add_preset_map",
    "LOD_OT_delete_preset_map",
    "LOD_OT_add_export_preset_map",
    "LOD_OT_delete_export_preset_map",
    "LOD_OT_open_presets_directory",
    "LOD_OT_save_export_preset",
    "LOD_OT_delete_import_preset",
    "LOD_OT_delete_export_preset",
]
