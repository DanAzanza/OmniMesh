"""
PBR Texture Set Importer and Slot Auto-Matcher Operators.
Preset CRUD operations are modularized in ui.pbr_preset_ops and ui.preset_ops.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

try:
    from ..core.pbr_importer import (
        BatchMaterialSlotMatcher,
        PBRSemanticClassifier,
        ShaderGraphBuilder,
    )
    from ..core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImportPresetManager,
    )
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
    from .utils import resolve_lod_context, safe_report
except (ImportError, ValueError):
    from core.pbr_importer import (
        BatchMaterialSlotMatcher,
        PBRSemanticClassifier,
        ShaderGraphBuilder,
    )
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImportPresetManager,
    )
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
    from ui.utils import resolve_lod_context, safe_report


class LOD_OT_import_pbr_set(Operator):
    """Import and construct PBR shader graph from selected texture files or folder using the active preset."""

    bl_idname = "lod_tool.import_pbr_set"
    bl_label = "Import PBR Textures"
    bl_options = {"REGISTER", "UNDO"}

    directory: Any = bpy.props.StringProperty(subtype="DIR_PATH") if bpy else ""  # type: ignore
    files: Any = bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement) if bpy else None  # type: ignore

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        active_obj = context.active_object
        if not active_obj or active_obj.type != "MESH":
            safe_report(self, {"WARNING"}, "Please select a target mesh object.")
            return {"CANCELLED"}

        file_paths = []
        if self.files and self.directory:
            for f in self.files:
                file_paths.append(os.path.join(self.directory, f.name))
        elif self.directory and os.path.isdir(self.directory):
            valid_exts = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".tif", ".tiff", ".webp", ".dds"}
            try:
                file_paths = [
                    os.path.join(self.directory, f)
                    for f in os.listdir(self.directory)
                    if os.path.splitext(f)[1].lower() in valid_exts
                ]
            except OSError:
                pass
        elif getattr(props, "pbr_import_directory", ""):
            abs_dir = bpy.path.abspath(props.pbr_import_directory)
            if os.path.isdir(abs_dir):
                valid_exts = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".tif", ".tiff", ".webp", ".dds"}
                try:
                    file_paths = [
                        os.path.join(abs_dir, f)
                        for f in os.listdir(abs_dir)
                        if os.path.splitext(f)[1].lower() in valid_exts
                    ]
                    self.directory = abs_dir
                except OSError:
                    pass

        if not file_paths:
            safe_report(self, {"WARNING"}, "No texture files found or selected.")
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        preset = PBRImportPresetManager.get_preset(preset_id)

        # Classify selected files against active preset rules
        tex_dict: dict[str, str] = {}
        for fpath in file_paths:
            res = PBRSemanticClassifier.classify_with_preset(fpath, preset)
            if res:
                map_id = res[0]
                tex_dict[map_id] = fpath

        if not tex_dict:
            safe_report(self, {"WARNING"}, f"No matching textures found for preset '{preset.get('name', preset_id)}'.")
            return {"CANCELLED"}

        # If user picked a valid folder, remember it in pbr_import_directory
        if self.directory and hasattr(props, "pbr_import_directory"):
            props.pbr_import_directory = self.directory

        mat = bpy.data.materials.new(name=f"M_{active_obj.name}")
        mat.use_nodes = True

        ao_mode = getattr(props, "pbr_import_ao_mode", "MULTIPLY")
        preserve = getattr(props, "pbr_import_preserve_existing", False)
        path_mode = getattr(props, "pbr_import_path_mode", "RELATIVE")
        success = ShaderGraphBuilder.build_pbr_graph(
            mat,
            tex_dict,
            preset=preset,
            preserve_existing=preserve,
            ao_blend_mode=ao_mode,
            path_mode=path_mode,
        )

        if success:
            if len(active_obj.material_slots) == 0:
                active_obj.data.materials.append(mat)
            else:
                act_idx = max(0, min(active_obj.active_material_index, len(active_obj.material_slots) - 1))
                active_obj.material_slots[act_idx].material = mat
            summary = f"Imported {len(tex_dict)} map(s) using '{preset.get('name', preset_id)}'"
            if hasattr(props, "last_pbr_import_summary"):
                props.last_pbr_import_summary = summary
            safe_report(self, {"INFO"}, summary)
            return {"FINISHED"}

        safe_report(self, {"WARNING"}, "Failed to construct shader network.")
        return {"CANCELLED"}

    def invoke(self, context: Any, _event: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = context.scene.lod_tool

        imp_dir = getattr(props, "pbr_import_directory", "")
        if imp_dir:
            abs_dir = bpy.path.abspath(imp_dir)
            if os.path.isdir(abs_dir):
                valid_exts = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".tif", ".tiff", ".webp", ".dds"}
                try:
                    candidates = [f for f in os.listdir(abs_dir) if os.path.splitext(f)[1].lower() in valid_exts]
                    if candidates:
                        self.directory = abs_dir
                        return self.execute(context)
                except OSError:
                    pass

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class LOD_OT_auto_match_pbr_folder(Operator):
    """Scan directory and match texture sets to mesh material slots using active preset."""

    bl_idname = "lod_tool.auto_match_pbr_folder"
    bl_label = "Auto-Match PBR Folder"
    bl_options = {"REGISTER", "UNDO"}

    directory: Any = bpy.props.StringProperty(subtype="DIR_PATH") if bpy else ""  # type: ignore

    def execute(self, context: Any) -> set[str]:
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
        preserve = getattr(props, "pbr_import_preserve_existing", False)
        path_mode = getattr(props, "pbr_import_path_mode", "RELATIVE")
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

            if ShaderGraphBuilder.build_pbr_graph(
                slot_mat,
                tex_dict,
                preset=preset,
                preserve_existing=preserve,
                ao_blend_mode=ao_mode,
                path_mode=path_mode,
            ):
                count += 1

        summary = f"Matched {count} material slot(s) using '{preset.get('name', preset_id)}'."
        if hasattr(props, "last_pbr_import_summary"):
            props.last_pbr_import_summary = summary
        safe_report(self, {"INFO"}, summary)
        return {"FINISHED"}

    def invoke(self, context: Any, _event: Any) -> set[str]:
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


PBR_OPERATOR_CLASSES = (
    LOD_OT_import_pbr_set,
    LOD_OT_auto_match_pbr_folder,
)

__all__ = [
    "PBR_OPERATOR_CLASSES",
    "LOD_OT_import_pbr_set",
    "LOD_OT_auto_match_pbr_folder",
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
