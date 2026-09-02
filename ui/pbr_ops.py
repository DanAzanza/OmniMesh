"""
PBR Texture Set Importer and Material Slot Auto-Matcher Operators.
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
    from core.pbr_importer import BatchMaterialSlotMatcher, ShaderGraphBuilder
    from ui.utils import resolve_lod_context, safe_report
except (ImportError, ValueError):
    from ..core.pbr_importer import BatchMaterialSlotMatcher, ShaderGraphBuilder
    from .utils import resolve_lod_context, safe_report


class LOD_OT_import_pbr_set(Operator):
    """Import and construct PBR shader graph from texture maps."""

    bl_idname = "lod_tool.import_pbr_set"
    bl_label = "Import PBR Textures"
    bl_options = {"REGISTER", "UNDO"}

    if bpy:
        directory: Any = bpy.props.StringProperty(subtype="DIR_PATH")
        files: Any = bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    else:
        directory: Any = ""
        files: Any = None

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

        mat = bpy.data.materials.new(name=f"M_{active_obj.name}")
        mat.use_nodes = True
        success = ShaderGraphBuilder.build_pbr_graph(mat, file_paths)
        if success:
            if len(active_obj.material_slots) == 0:
                active_obj.data.materials.append(mat)
            else:
                active_obj.material_slots[0].material = mat
            safe_report(self, {"INFO"}, f"Successfully built PBR shader '{mat.name}'")
            return {"FINISHED"}

        safe_report(self, {"WARNING"}, "No compatible PBR textures found.")
        return {"CANCELLED"}

    def invoke(self, context: Any, _event: Any) -> set[str]:
        if bpy:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return {"FINISHED"}


class LOD_OT_auto_match_pbr_folder(Operator):
    """Scan directory and match texture sets to mesh material slots."""

    bl_idname = "lod_tool.auto_match_pbr_folder"
    bl_label = "Auto-Match PBR Folder"
    bl_options = {"REGISTER", "UNDO"}

    if bpy:
        directory: Any = bpy.props.StringProperty(subtype="DIR_PATH")
    else:
        directory: Any = ""

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        active_obj = context.active_object
        if not active_obj or active_obj.type != "MESH":
            safe_report(self, {"WARNING"}, "Please select a target mesh object.")
            return {"CANCELLED"}

        if not self.directory:
            safe_report(self, {"WARNING"}, "Please choose a valid directory.")
            return {"CANCELLED"}

        matched = BatchMaterialSlotMatcher.match_directory_to_slots(active_obj, self.directory)
        count = 0
        for slot_name, tex_dict in matched.items():
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
                    # Look for empty slot or append
                    empty_slot = next((s for s in active_obj.material_slots if s.material is None), None)
                    if empty_slot:
                        empty_slot.material = slot_mat
                    else:
                        active_obj.data.materials.append(slot_mat)
            if ShaderGraphBuilder.build_pbr_graph(slot_mat, list(tex_dict.values())):
                count += 1

        props = context.scene.lod_tool if hasattr(context.scene, "lod_tool") else None
        if props:
            props.last_pbr_import_summary = f"Matched {count} PBR material slots from folder."
        safe_report(self, {"INFO"}, f"Matched {count} PBR material slots.")
        return {"FINISHED"}

    def invoke(self, context: Any, _event: Any) -> set[str]:
        if bpy:
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}
        return {"FINISHED"}


PBR_OPERATOR_CLASSES = (
    LOD_OT_import_pbr_set,
    LOD_OT_auto_match_pbr_folder,
)
