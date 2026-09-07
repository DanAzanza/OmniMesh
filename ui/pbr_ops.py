"""
PBR Texture Set Importer, Slot Auto-Matcher, and Preset Management Operators.
"""

from __future__ import annotations

from contextlib import nullcontext
import copy
import logging
import os
import sys
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
        PBRExportPresetManager,
        PBRImportPresetManager,
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
        PBRExportPresetManager,
        PBRImportPresetManager,
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
                active_obj.material_slots[0].material = mat
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


class LOD_OT_reload_pbr_presets(Operator):
    """Reload all PBR texture set presets from disk."""

    bl_idname = "lod_tool.reload_pbr_presets"
    bl_label = "Reload Presets"
    bl_description = "Refreshes the PBR importer and exporter presets from built-in and user folders"

    def execute(self, _context: Any) -> set[str]:
        loaded_imp = PBRImportPresetManager.load_presets(force_reload=True)
        loaded_exp = PBRExportPresetManager.load_presets(force_reload=True)
        safe_report(
            self,
            {"INFO"},
            f"Loaded {len(loaded_imp)} import preset(s), {len(loaded_exp)} export preset(s).",
        )
        return {"FINISHED"}


class LOD_OT_reset_pbr_preset(Operator):
    """Revert current custom preset override to factory default."""

    bl_idname = "lod_tool.reset_pbr_preset"
    bl_label = "Reset to Built-in Default"
    bl_description = "Deletes user custom overrides for this preset and restores factory defaults"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        props, _, _ = resolve_lod_context(context)
        preset_id = getattr(props, "pbr_import_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        deleted = PBRImportPresetManager.delete_custom_preset(preset_id)
        if deleted:
            safe_report(self, {"INFO"}, f"Reset preset '{preset_id}' to built-in default.")
        else:
            safe_report(self, {"INFO"}, f"Preset '{preset_id}' is already a built-in default.")
        return {"FINISHED"}


try:
    from .properties import (
        ENGINE_TO_FACTORY_PRESET,
        ExportMapSyncGuard,
        MapSyncGuard,
        PresetSyncGuard,
        sync_export_maps_from_preset,
        sync_export_maps_to_preset,
        sync_maps_from_preset,
        sync_maps_to_preset,
    )
except (ImportError, ValueError):
    try:
        from ui.properties import (
            ENGINE_TO_FACTORY_PRESET,
            ExportMapSyncGuard,
            MapSyncGuard,
            PresetSyncGuard,
            sync_export_maps_from_preset,
            sync_export_maps_to_preset,
            sync_maps_from_preset,
            sync_maps_to_preset,
        )
    except (ImportError, ValueError):
        ENGINE_TO_FACTORY_PRESET = {"UE5": "unreal_engine_5"}
        ExportMapSyncGuard = None
        MapSyncGuard = None
        PresetSyncGuard = None
        sync_export_maps_from_preset = None
        sync_export_maps_to_preset = None
        sync_maps_from_preset = None
        sync_maps_to_preset = None


class LOD_OT_duplicate_preset(Operator):
    """Create an editable custom copy of the active preset."""

    bl_idname = "lod_tool.duplicate_preset"
    bl_label = "Duplicate Preset"
    bl_description = "Clones the active preset into a new editable custom user preset"
    bl_options = {"REGISTER", "UNDO"}

    preset_type: Any = (
        bpy.props.EnumProperty(  # type: ignore
            name="Preset Type",
            items=[
                ("EXPORT", "Export Preset", "Duplicate active export preset"),
                ("IMPORT", "Import Preset", "Duplicate active import preset"),
            ],
            default="EXPORT",
        )
        if bpy
        else "EXPORT"
    )

    new_name: Any = (
        bpy.props.StringProperty(  # type: ignore
            name="Preset Name",
            description="Name for the duplicated preset",
            default="",
        )
        if bpy
        else ""
    )

    def invoke(self, context: Any, _event: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)

        if self.preset_type == "IMPORT":
            source_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
            preset = PBRImportPresetManager.get_preset(source_id)
        else:
            source_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
            preset = PBRExportPresetManager.get_preset(source_id)

        current_name = preset.get("name", source_id)
        self.new_name = f"{current_name} (Copy)"
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, _context: Any) -> None:
        if not bpy:
            return
        layout = self.layout
        layout.prop(self, "new_name")

    def execute(self, context: Any) -> set[str]:
        targets = []
        if context and hasattr(context, "scene") and hasattr(context.scene, "lod_tool"):
            targets.append(context.scene.lod_tool)
        obj_props, _, _ = resolve_lod_context(context)
        if obj_props and obj_props not in targets:
            targets.append(obj_props)

        props = targets[0] if targets else None

        if self.preset_type == "IMPORT":
            source_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
            mgr = PBRImportPresetManager
        else:
            source_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
            mgr = PBRExportPresetManager

        try:
            new_id = mgr.duplicate_preset(source_id, self.new_name)
            guard_ctx = (
                PresetSyncGuard()
                if (PresetSyncGuard and hasattr(PresetSyncGuard, "is_locked") and not PresetSyncGuard.is_locked())
                else nullcontext()
            )
            map_ctx = (
                MapSyncGuard()
                if (MapSyncGuard and hasattr(MapSyncGuard, "is_active") and not MapSyncGuard.is_active())
                else nullcontext()
            )

            def apply_target_preset(target_prop: Any, target_nid: str) -> None:
                if self.preset_type == "IMPORT":
                    if hasattr(target_prop, "pbr_import_preset"):
                        target_prop.pbr_import_preset = target_nid
                        if sync_maps_from_preset:
                            preset_data = mgr.get_preset(target_nid)
                            sync_maps_from_preset(target_prop, preset_data)
                else:
                    if hasattr(target_prop, "pbr_export_preset"):
                        target_prop.pbr_export_preset = target_nid
                    if hasattr(target_prop, "pbr_preset"):
                        target_prop.pbr_preset = target_nid

            with guard_ctx, map_ctx:
                for p in targets:
                    try:
                        apply_target_preset(p, new_id)
                    except (TypeError, ValueError) as val_err:
                        logger.debug("Immediate preset assignment deferred: %s", val_err)
                        if bpy and hasattr(bpy, "app") and hasattr(bpy.app, "timers"):

                            def make_deferred(prop_obj: Any, nid: str):
                                def _deferred_apply() -> None:
                                    guard = (
                                        PresetSyncGuard()
                                        if (
                                            PresetSyncGuard
                                            and hasattr(PresetSyncGuard, "is_locked")
                                            and not PresetSyncGuard.is_locked()
                                        )
                                        else nullcontext()
                                    )
                                    mguard = (
                                        MapSyncGuard()
                                        if (
                                            MapSyncGuard
                                            and hasattr(MapSyncGuard, "is_active")
                                            and not MapSyncGuard.is_active()
                                        )
                                        else nullcontext()
                                    )
                                    with guard, mguard:
                                        try:
                                            apply_target_preset(prop_obj, nid)
                                        except Exception as exc:
                                            logger.debug("Deferred preset assignment exception: %s", exc)

                                return _deferred_apply

                            bpy.app.timers.register(make_deferred(p, new_id), first_interval=0.005)

            mgr.set_last_active_preset(new_id)
            safe_report(self, {"INFO"}, f"Created custom preset '{new_id}'.")
            return {"FINISHED"}
        except Exception as exc:
            import traceback

            traceback.print_exc()
            logger.error("Failed to duplicate preset '%s': %s", source_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Duplicate failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_duplicate_export_preset(Operator):
    """Legacy alias for duplicating export presets."""

    bl_idname = "lod_tool.duplicate_export_preset"
    bl_label = "Duplicate Export Preset"
    bl_description = "Legacy operator alias to clone active export preset"
    bl_options = {"REGISTER", "UNDO"}

    new_name: Any = (
        bpy.props.StringProperty(  # type: ignore
            name="Preset Name",
            description="Name for the duplicated preset",
            default="",
        )
        if bpy
        else ""
    )

    def execute(self, _context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        return bpy.ops.lod_tool.duplicate_preset(preset_type="EXPORT", new_name=self.new_name)


class LOD_OT_add_preset_map(Operator):
    """Add a new texture map rule to the active import preset."""

    bl_idname = "lod_tool.add_preset_map"
    bl_label = "Add Map Definition"
    bl_description = "Adds a new texture map rule to the active preset (creates an editable copy if built-in)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_active_maps"):
            return {"CANCELLED"}

        idx = len(props.pbr_active_maps) + 1
        with MapSyncGuard() if MapSyncGuard else nullcontext():
            item = props.pbr_active_maps.add()
            item.map_id = f"custom_map_{idx}"
            item.name = f"Custom Map {idx}"
            item.suffixes_str = f"_Map{idx}"
            item.color_space = "Non-Color"
            item.is_normal_map = False
            item.is_packed = False
            item.target_rgb = "Base Color"
            props.pbr_active_map_index = len(props.pbr_active_maps) - 1

        if sync_maps_to_preset:
            sync_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Added map '{item.name}'.")
        return {"FINISHED"}


class LOD_OT_delete_preset_map(Operator):
    """Delete the selected texture map rule from the active import preset."""

    bl_idname = "lod_tool.delete_preset_map"
    bl_label = "Delete Map Definition"
    bl_description = "Removes the selected texture map rule from the active preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_active_maps"):
            return {"CANCELLED"}

        count = len(props.pbr_active_maps)
        if count <= 1:
            safe_report(self, {"WARNING"}, "A preset must contain at least one texture map.")
            return {"CANCELLED"}

        idx = props.pbr_active_map_index
        if idx < 0 or idx >= count:
            return {"CANCELLED"}

        deleted_name = props.pbr_active_maps[idx].name
        with MapSyncGuard() if MapSyncGuard else nullcontext():
            props.pbr_active_maps.remove(idx)
            props.pbr_active_map_index = max(0, min(idx, len(props.pbr_active_maps) - 1))

        if sync_maps_to_preset:
            sync_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Deleted map '{deleted_name}'.")
        return {"FINISHED"}


class LOD_OT_add_export_preset_map(Operator):
    """Add a new texture map rule to the active export preset."""

    bl_idname = "lod_tool.add_export_preset_map"
    bl_label = "Add Export Map Definition"
    bl_description = "Adds a new texture map rule to the active export preset (creates an editable copy if built-in)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_export_active_maps"):
            return {"CANCELLED"}

        idx = len(props.pbr_export_active_maps) + 1
        with ExportMapSyncGuard() if ExportMapSyncGuard else nullcontext():
            item = props.pbr_export_active_maps.add()
            item.map_id = f"custom_map_{idx}"
            item.name = f"Custom Map {idx}"
            item.export = True
            item.export_suffix = f"_Map{idx}"
            item.color_space = "Non-Color"
            item.is_normal_map = False
            item.is_packed = False
            item.target_rgb = "Base Color"
            props.pbr_export_active_map_index = len(props.pbr_export_active_maps) - 1

        if sync_export_maps_to_preset:
            sync_export_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Added export map '{item.name}'.")
        return {"FINISHED"}


class LOD_OT_delete_export_preset_map(Operator):
    """Delete the selected texture map rule from the active export preset."""

    bl_idname = "lod_tool.delete_export_preset_map"
    bl_label = "Delete Export Map Definition"
    bl_description = "Removes the selected texture map rule from the active export preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_export_active_maps"):
            return {"CANCELLED"}

        count = len(props.pbr_export_active_maps)
        if count <= 1:
            safe_report(self, {"WARNING"}, "An export preset must contain at least one texture map.")
            return {"CANCELLED"}

        idx = props.pbr_export_active_map_index
        if idx < 0 or idx >= count:
            return {"CANCELLED"}

        deleted_name = props.pbr_export_active_maps[idx].name
        with ExportMapSyncGuard() if ExportMapSyncGuard else nullcontext():
            props.pbr_export_active_maps.remove(idx)
            props.pbr_export_active_map_index = max(0, min(idx, len(props.pbr_export_active_maps) - 1))

        if sync_export_maps_to_preset:
            sync_export_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Deleted export map '{deleted_name}'.")
        return {"FINISHED"}


class LOD_OT_open_presets_directory(Operator):
    """Open the user presets directory in the operating system file manager."""

    bl_idname = "lod_tool.open_presets_directory"
    bl_label = "Open Presets Folder"
    bl_description = "Opens the custom preset folder in the operating system file manager"

    category: Any = (
        bpy.props.EnumProperty(  # type: ignore
            name="Category",
            items=[
                ("IMPORTER", "Importer", "Open importer presets folder"),
                ("EXPORTER", "Exporter", "Open exporter presets folder"),
            ],
            default="EXPORTER",
        )
        if bpy
        else "EXPORTER"
    )

    def execute(self, _context: Any) -> set[str]:
        if self.category == "IMPORTER":
            target_dir = str(PBRImportPresetManager.get_user_dir())
        else:
            target_dir = str(PBRExportPresetManager.get_user_dir())

        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(target_dir)  # noqa: S606
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", target_dir])  # noqa: S603, S607
            else:
                import subprocess

                subprocess.Popen(["xdg-open", target_dir])  # noqa: S603, S607
            safe_report(self, {"INFO"}, f"Opened presets folder: {target_dir}")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed to open presets directory: %s", exc)
            safe_report(self, {"ERROR"}, f"Could not open directory: {exc}")
            return {"CANCELLED"}


class LOD_OT_save_export_preset(Operator):
    """Save modified export configuration into the active custom preset."""

    bl_idname = "lod_tool.save_export_preset"
    bl_label = "Save Export Preset"
    bl_description = "Saves target engine, channel strategy, and naming settings to the active custom preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        props, _, _ = resolve_lod_context(context)
        if not props:
            props = getattr(context.scene, "lod_tool", None)
        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)

        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Cannot overwrite built-in factory preset. Click 'Duplicate' first.")
            return {"CANCELLED"}

        try:
            pdata = copy.deepcopy(PBRExportPresetManager.get_preset(preset_id))
            pdata["target_engine"] = getattr(props, "target_engine", "UE5")
            pdata["strategy"] = getattr(props, "pbr_export_texture_strategy", "CONVERT_PNG")
            pdata["bit_depth"] = int(getattr(props, "pbr_export_bit_depth", "8"))
            pdata["naming_pattern"] = getattr(props, "pbr_export_naming_pattern", "{material}{suffix}")

            PBRExportPresetManager.save_custom_preset(pdata, custom_id=preset_id)
            safe_report(self, {"INFO"}, f"Saved settings to custom preset '{pdata.get('name', preset_id)}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed to save custom preset '%s': %s", preset_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_delete_import_preset(Operator):
    """Permanently delete active custom import preset with confirmation."""

    bl_idname = "lod_tool.delete_import_preset"
    bl_label = "Delete Custom Preset"
    bl_description = "Deletes the active custom import preset file and resets to factory default"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Cannot delete built-in factory presets.")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context: Any) -> set[str]:
        targets = []
        if context and hasattr(context, "scene") and hasattr(context.scene, "lod_tool"):
            targets.append(context.scene.lod_tool)
        obj_props, _, _ = resolve_lod_context(context)
        if obj_props and obj_props not in targets:
            targets.append(obj_props)

        props = targets[0] if targets else None
        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID

        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Cannot delete factory presets.")
            return {"CANCELLED"}

        try:
            fallback_id = PBRImportPresetManager.DEFAULT_PRESET_ID
            for p in targets:
                if hasattr(p, "pbr_import_preset") and p.pbr_import_preset == preset_id:
                    p.pbr_import_preset = fallback_id

            success = PBRImportPresetManager.delete_custom_preset(preset_id)
            if success:
                safe_report(self, {"INFO"}, f"Deleted custom preset '{preset_id}'.")
                return {"FINISHED"}
            safe_report(self, {"WARNING"}, f"Could not find or delete preset '{preset_id}'.")
            return {"CANCELLED"}
        except Exception as exc:
            logger.error("Failed to delete custom preset '%s': %s", preset_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Delete failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_delete_export_preset(Operator):
    """Permanently delete active custom export preset and cleanly sanitize scene properties."""

    bl_idname = "lod_tool.delete_export_preset"
    bl_label = "Delete Custom Preset"
    bl_description = "Deletes the active custom export preset file and resets to factory default"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Cannot delete built-in factory presets.")
            return {"CANCELLED"}
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context: Any) -> set[str]:
        targets = []
        if context and hasattr(context, "scene") and hasattr(context.scene, "lod_tool"):
            targets.append(context.scene.lod_tool)
        obj_props, _, _ = resolve_lod_context(context)
        if obj_props and obj_props not in targets:
            targets.append(obj_props)

        props = targets[0] if targets else None
        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)

        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Cannot delete factory presets.")
            return {"CANCELLED"}

        try:
            fallback_id = ENGINE_TO_FACTORY_PRESET.get(getattr(props, "target_engine", "UE5"), DEFAULT_PRESET_ID)
            for p in targets:
                if hasattr(p, "pbr_export_preset") and p.pbr_export_preset == preset_id:
                    p.pbr_export_preset = fallback_id
                if hasattr(p, "pbr_preset") and p.pbr_preset == preset_id:
                    p.pbr_preset = fallback_id
                if hasattr(p, "pbr_import_preset") and p.pbr_import_preset == preset_id:
                    p.pbr_import_preset = fallback_id

            success = PBRExportPresetManager.delete_custom_preset(preset_id)
            if success:
                safe_report(self, {"INFO"}, f"Deleted custom preset '{preset_id}'.")
                return {"FINISHED"}
            safe_report(self, {"WARNING"}, f"Could not find or delete preset '{preset_id}'.")
            return {"CANCELLED"}
        except Exception as exc:
            logger.error("Failed to delete custom preset '%s': %s", preset_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Delete failed: {exc}")
            return {"CANCELLED"}


PBR_OPERATOR_CLASSES = (
    LOD_OT_import_pbr_set,
    LOD_OT_auto_match_pbr_folder,
    LOD_OT_reload_pbr_presets,
    LOD_OT_reset_pbr_preset,
    LOD_OT_duplicate_preset,
    LOD_OT_duplicate_export_preset,
    LOD_OT_add_preset_map,
    LOD_OT_delete_preset_map,
    LOD_OT_add_export_preset_map,
    LOD_OT_delete_export_preset_map,
    LOD_OT_open_presets_directory,
    LOD_OT_save_export_preset,
    LOD_OT_delete_import_preset,
    LOD_OT_delete_export_preset,
)
