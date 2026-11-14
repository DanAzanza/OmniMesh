# pyright: reportInvalidTypeForm=none
"""
OmniMesh PBR Preset CRUD & Management Operators.
Handles creation, duplication, renaming, persistence, deletion, and directory access
for PBR import presets and unified engine export presets.
Map-level rule operators are modularized in ui.pbr_map_ops.
"""

import logging
import os
import sys
from contextlib import nullcontext
import copy
from typing import TYPE_CHECKING, Any, cast

try:
    from ..core.lod_presets import DEFAULT_LOD_PRESET_ID, LODPresetManager
    from ..core.pbr_presets import DEFAULT_PRESET_ID, PBRExportPresetManager, PBRImportPresetManager
    from .pbr_map_ops import (
        LOD_OT_add_export_map_template,
        LOD_OT_add_export_preset_map,
        LOD_OT_add_map_template,
        LOD_OT_add_preset_map,
        LOD_OT_delete_export_preset_map,
        LOD_OT_delete_preset_map,
        LOD_OT_init_preset_maps,
        LOD_OT_move_export_preset_map,
        LOD_OT_move_preset_map,
        PBR_MAP_OPERATOR_CLASSES,
    )
    from .properties import (
        ENGINE_TO_FACTORY_PRESET,
        ExportMapSyncGuard,
        MapSyncGuard,
        PresetSyncGuard,
        sync_export_maps_from_preset,
        sync_maps_from_preset,
        sync_maps_to_preset,
        sync_preset_tiers_from_preset,
    )
    from .rna_helpers import assign_or_defer_enum, mock_prop
    from .utils import resolve_lod_context, safe_report
except (ImportError, ValueError):
    from core.lod_presets import DEFAULT_LOD_PRESET_ID, LODPresetManager
    from core.pbr_presets import DEFAULT_PRESET_ID, PBRExportPresetManager, PBRImportPresetManager
    from ui.pbr_map_ops import (
        LOD_OT_add_export_map_template,
        LOD_OT_add_export_preset_map,
        LOD_OT_add_map_template,
        LOD_OT_add_preset_map,
        LOD_OT_delete_export_preset_map,
        LOD_OT_delete_preset_map,
        LOD_OT_init_preset_maps,
        LOD_OT_move_export_preset_map,
        LOD_OT_move_preset_map,
        PBR_MAP_OPERATOR_CLASSES,
    )
    from ui.properties import (
        ENGINE_TO_FACTORY_PRESET,
        ExportMapSyncGuard,
        MapSyncGuard,
        PresetSyncGuard,
        sync_export_maps_from_preset,
        sync_maps_from_preset,
        sync_maps_to_preset,
        sync_preset_tiers_from_preset,
    )
    from ui.rna_helpers import assign_or_defer_enum, mock_prop
    from ui.utils import resolve_lod_context, safe_report

if TYPE_CHECKING:
    import bpy
    from bpy.props import EnumProperty, StringProperty
    from bpy.types import Operator
else:
    try:
        import bpy
        from bpy.props import EnumProperty, StringProperty
        from bpy.types import Operator
    except ImportError:
        bpy = None
        Operator = object
        EnumProperty = mock_prop
        StringProperty = mock_prop


logger = logging.getLogger(__name__)


class LOD_OT_reload_pbr_presets(Operator):
    """Reload all PBR texture set presets from disk."""

    bl_idname = "lod_tool.reload_pbr_presets"
    bl_label = "Reload Presets"
    bl_description = "Refreshes the PBR importer and exporter presets from built-in and user folders"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        loaded_imp = PBRImportPresetManager.load_presets(force_reload=True)
        loaded_exp = PBRExportPresetManager.load_presets(force_reload=True)
        safe_report(self, {"INFO"}, f"Loaded {len(loaded_imp)} import preset(s), {len(loaded_exp)} export preset(s).")
        return {"FINISHED"}


class LOD_OT_reset_pbr_preset(Operator):
    """Revert current custom preset override to factory default."""

    bl_idname = "lod_tool.reset_pbr_preset"
    bl_label = "Reset to Built-in Default"
    bl_description = "Deletes user custom overrides for this preset and restores factory defaults"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        preset_id = getattr(props, "pbr_import_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        deleted = PBRImportPresetManager.delete_custom_preset(preset_id)
        if props:
            sync_maps_from_preset(props, PBRImportPresetManager.get_preset(preset_id))
        msg = (
            f"Reset preset '{preset_id}' to built-in default."
            if deleted
            else f"Preset '{preset_id}' is already a built-in default."
        )
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


class LOD_OT_create_import_preset(Operator):
    """Create a new custom PBR import preset from scratch or starter template."""

    bl_idname = "lod_tool.create_import_preset"
    bl_label = "New Import Preset"
    bl_description = "Creates a new custom PBR import preset profile with name and starter template"
    bl_options = {"REGISTER"}

    preset_name: StringProperty(name="Preset Name", default="Custom Import Preset")
    template_type: EnumProperty(
        name="Starter Template",
        items=[
            ("standard_pbr_split", "Standard PBR (Split Maps)", "Discrete texture files for each channel"),
            ("unreal_engine_5", "Unreal Engine 5 (Packed ORM)", "Base Color, Packed ORM, and Normal"),
            ("msfs_2024_comp", "MSFS 2024 (Packed COMP)", "Base Color, Packed COMP, and Normal"),
            ("unity_hdrp_maskmap", "Unity HDRP (MaskMap)", "Base Color, Packed MaskMap, and Normal"),
            ("minimal", "Minimal (Base Color Only)", "Minimal single-texture starter rule"),
        ],
        default="standard_pbr_split",
    )

    def invoke(self, context: Any, event: Any) -> set[Any]:
        return context.window_manager.invoke_props_dialog(self, width=340) if bpy else {"FINISHED"}

    def draw(self, context: Any) -> None:
        if bpy and self.layout:
            col = self.layout.column(align=True)
            col.prop(self, "preset_name", text="Name")
            col.separator()
            col.prop(self, "template_type", text="Template")

    def execute(self, context: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        try:
            new_id = PBRImportPresetManager.create_new_preset(name=self.preset_name, template_id=self.template_type)
            if props and hasattr(props, "pbr_import_preset"):
                from .rna_helpers import assign_or_defer_enum

                def _apply_new_pre(p_obj: Any = props, nid: str = new_id) -> None:
                    p_obj.pbr_import_preset = nid
                    sync_maps_from_preset(p_obj, PBRImportPresetManager.get_preset(nid))

                with PresetSyncGuard(), MapSyncGuard():
                    assign_or_defer_enum(
                        bpy,
                        _apply_new_pre,
                        first_interval=0.005,
                        label="pbr_import_preset assignment",
                        logger_inst=logger,
                    )
            PBRImportPresetManager.set_last_active_preset(new_id)
            safe_report(self, {"INFO"}, f"Created import preset '{self.preset_name}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed creating import preset: %s", exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Could not create preset: {exc}")
            return {"CANCELLED"}


class LOD_OT_rename_import_preset(Operator):
    """Rename the active custom PBR import preset."""

    bl_idname = "lod_tool.rename_import_preset"
    bl_label = "Rename Import Preset"
    bl_description = "Renames the active custom import preset file and display metadata"
    bl_options = {"REGISTER"}

    new_name: StringProperty(name="New Name", description="New name for the custom preset", default="")

    def invoke(self, context: Any, event: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Built-in factory presets cannot be renamed. Duplicate it first.")
            return {"CANCELLED"}
        preset = PBRImportPresetManager.get_preset(preset_id)
        self.new_name = preset.get("name", preset_id)
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context: Any) -> None:
        if bpy and self.layout:
            self.layout.prop(self, "new_name", text="Name")

    def execute(self, context: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        old_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(old_id):
            safe_report(self, {"ERROR"}, "Cannot rename built-in factory presets.")
            return {"CANCELLED"}
        clean_name = self.new_name.strip()
        if not clean_name:
            safe_report(self, {"ERROR"}, "Preset name cannot be empty.")
            return {"CANCELLED"}
        try:
            new_id = PBRImportPresetManager.rename_custom_preset(old_id, clean_name)
            if props and hasattr(props, "pbr_import_preset"):
                with PresetSyncGuard():
                    try:
                        props.pbr_import_preset = new_id
                    except (TypeError, ValueError):
                        pass
            PBRImportPresetManager.set_last_active_preset(new_id)
            safe_report(self, {"INFO"}, f"Renamed preset to '{clean_name}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed renaming preset '%s': %s", old_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Rename failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_create_export_preset(Operator):
    """Create a new custom PBR export preset from a starter template."""

    bl_idname = "lod_tool.create_export_preset"
    bl_label = "New Export Preset"
    bl_description = "Creates a new custom PBR export preset profile"
    bl_options = {"REGISTER"}

    preset_name: StringProperty(name="Preset Name", default="Custom Export Preset")
    template_type: EnumProperty(
        name="Starter Template",
        items=[
            ("unreal_engine_5", "Unreal Engine 5 (Packed ORM)", "UE5 Base Color, Packed ORM, and DirectX Normal"),
            ("unity_hdrp_maskmap", "Unity HDRP (MaskMap)", "Unity HDRP Base Color, MaskMap, and OpenGL Normal"),
            ("msfs_2024_comp", "MSFS 2024 (Packed COMP)", "MSFS 2024 Base Color, COMP, and DirectX Normal"),
            ("standard_pbr_split", "Standard PBR (Split Maps)", "Discrete sRGB/Non-Color export maps"),
            ("minimal", "Minimal (Base Color Only)", "Minimal single-texture export preset"),
        ],
        default="unreal_engine_5",
    )

    def invoke(self, context: Any, event: Any) -> set[Any]:
        return context.window_manager.invoke_props_dialog(self, width=340) if bpy else {"FINISHED"}

    def draw(self, context: Any) -> None:
        if bpy and self.layout:
            col = self.layout.column(align=True)
            col.prop(self, "preset_name", text="Name")
            col.separator()
            col.prop(self, "template_type", text="Template")

    def execute(self, context: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        try:
            new_id = PBRExportPresetManager.create_new_preset(name=self.preset_name, template_id=self.template_type)
            if props:
                with PresetSyncGuard(), ExportMapSyncGuard():
                    try:
                        if hasattr(props, "pbr_export_preset"):
                            props.pbr_export_preset = new_id
                        if hasattr(props, "pbr_preset"):
                            props.pbr_preset = new_id
                    except (TypeError, ValueError):
                        pass
                sync_export_maps_from_preset(props, PBRExportPresetManager.get_preset(new_id))
            PBRExportPresetManager.set_last_active_preset(new_id)
            safe_report(self, {"INFO"}, f"Created export preset '{self.preset_name}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed creating export preset: %s", exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Could not create preset: {exc}")
            return {"CANCELLED"}


class LOD_OT_rename_export_preset(Operator):
    """Rename the active custom PBR export preset."""

    bl_idname = "lod_tool.rename_export_preset"
    bl_label = "Rename Export Preset"
    bl_description = "Renames the active custom export preset file and display metadata"
    bl_options = {"REGISTER"}

    new_name: StringProperty(name="New Name", description="New name for the custom export preset", default="")

    def invoke(self, context: Any, event: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Built-in factory presets cannot be renamed. Duplicate it first.")
            return {"CANCELLED"}
        preset = PBRExportPresetManager.get_preset(preset_id)
        self.new_name = preset.get("name", preset_id)
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context: Any) -> None:
        if bpy and self.layout:
            self.layout.prop(self, "new_name", text="Name")

    def execute(self, context: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        old_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(old_id):
            safe_report(self, {"ERROR"}, "Cannot rename built-in factory presets.")
            return {"CANCELLED"}
        clean_name = self.new_name.strip()
        if not clean_name:
            safe_report(self, {"ERROR"}, "Preset name cannot be empty.")
            return {"CANCELLED"}
        try:
            new_id = PBRExportPresetManager.rename_custom_preset(old_id, clean_name)
            if props:
                with PresetSyncGuard():
                    try:
                        if hasattr(props, "pbr_export_preset"):
                            props.pbr_export_preset = new_id
                        if hasattr(props, "pbr_preset"):
                            props.pbr_preset = new_id
                    except (TypeError, ValueError):
                        pass
            PBRExportPresetManager.set_last_active_preset(new_id)
            safe_report(self, {"INFO"}, f"Renamed export preset to '{clean_name}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed renaming export preset '%s': %s", old_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Rename failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_duplicate_preset(Operator):
    """Create an editable custom copy of the active preset."""

    bl_idname = "lod_tool.duplicate_preset"
    bl_label = "Duplicate Preset"
    bl_description = "Clones the active preset into a new editable custom user preset"
    bl_options = {"REGISTER"}

    preset_type: EnumProperty(
        name="Preset Type",
        items=[
            ("EXPORT", "Export Preset", "Duplicate active export preset"),
            ("IMPORT", "Import Preset", "Duplicate active import preset"),
            ("LOD", "LOD Preset", "Duplicate active LOD preset"),
        ],
        default="EXPORT",
    )
    new_name: StringProperty(name="Preset Name", description="Name for the duplicated preset", default="")

    def invoke(self, context: Any, event: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if self.preset_type == "IMPORT":
            source_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
            preset = PBRImportPresetManager.get_preset(source_id)
        elif self.preset_type == "LOD":
            source_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID
            preset = LODPresetManager.get_preset(source_id)
        else:
            source_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
            preset = PBRExportPresetManager.get_preset(source_id)
        self.new_name = f"{preset.get('name', source_id)} (Copy)"
        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context: Any) -> None:
        if bpy and self.layout:
            self.layout.prop(self, "new_name", text="Name")

    def execute(self, context: Any) -> set[Any]:
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
        elif self.preset_type == "LOD":
            source_id = getattr(props, "lod_preset", "") or DEFAULT_LOD_PRESET_ID
            mgr = LODPresetManager
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
                preset_data = mgr.get_preset(target_nid)
                if self.preset_type == "IMPORT":
                    if hasattr(target_prop, "pbr_import_preset"):
                        target_prop.pbr_import_preset = target_nid
                        sync_maps_from_preset(target_prop, preset_data)
                elif self.preset_type == "LOD":
                    if hasattr(target_prop, "lod_preset"):
                        target_prop.lod_preset = target_nid
                        sync_preset_tiers_from_preset(target_prop, preset_data)
                else:
                    if hasattr(target_prop, "pbr_export_preset"):
                        target_prop.pbr_export_preset = target_nid
                    if hasattr(target_prop, "pbr_preset"):
                        target_prop.pbr_preset = target_nid
                    sync_export_maps_from_preset(target_prop, preset_data)

            for p in targets:

                def _apply_guarded(prop_obj: Any = p, nid: str = new_id) -> None:
                    with guard_ctx, map_ctx:
                        apply_target_preset(prop_obj, nid)

                assign_or_defer_enum(
                    bpy,
                    _apply_guarded,
                    first_interval=0.005,
                    label="duplicate preset assignment",
                    logger_inst=logger,
                )
            mgr.set_last_active_preset(new_id)
            safe_report(self, {"INFO"}, f"Created custom preset '{self.new_name}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed to duplicate preset '%s': %s", source_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Duplicate failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_duplicate_export_preset(Operator):
    """Legacy alias for duplicating export presets."""

    bl_idname = "lod_tool.duplicate_export_preset"
    bl_label = "Duplicate Export Preset"
    bl_description = "Legacy operator alias to clone active export preset"
    bl_options = {"REGISTER"}

    new_name: StringProperty(name="Preset Name", description="Name for the duplicated preset", default="")

    def execute(self, context: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        return cast(Any, bpy.ops).lod_tool.duplicate_preset(preset_type="EXPORT", new_name=self.new_name)


class LOD_OT_save_import_preset(Operator):
    """Save active import configuration into the custom preset on disk."""

    bl_idname = "lod_tool.save_import_preset"
    bl_label = "Save Import Preset"
    bl_description = "Persists modified texture map rules and options to the active custom preset file"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"ERROR"}, "Cannot overwrite built-in factory preset. Click 'Duplicate' first.")
            return {"CANCELLED"}
        try:
            sync_maps_to_preset(props)
            preset = PBRImportPresetManager.get_preset(preset_id)
            safe_report(self, {"INFO"}, f"Saved import preset '{preset.get('name', preset_id)}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed to save custom import preset '%s': %s", preset_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_save_export_preset(Operator):
    """Save modified export configuration into the active custom preset."""

    bl_idname = "lod_tool.save_export_preset"
    bl_label = "Save Export Preset"
    bl_description = "Saves target engine, channel strategy, and naming settings to the active custom preset"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
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
            pdata["naming_pattern"] = getattr(props, "pbr_export_naming_pattern", "{asset}_{material}{suffix}{udim}")
            PBRExportPresetManager.save_custom_preset(pdata, custom_id=preset_id)
            safe_report(self, {"INFO"}, f"Saved settings to custom preset '{pdata.get('name', preset_id)}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed to save custom preset '%s': %s", preset_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Save failed: {exc}")
            return {"CANCELLED"}


class LOD_OT_open_presets_directory(Operator):
    """Open the user presets directory in the operating system file manager."""

    bl_idname = "lod_tool.open_presets_directory"
    bl_label = "Open Presets Folder"
    bl_description = "Opens the custom preset folder in the operating system file manager"
    bl_options = {"REGISTER"}

    category: EnumProperty(
        name="Category",
        items=[
            ("IMPORTER", "Importer", "Open importer presets folder"),
            ("EXPORTER", "Exporter", "Open exporter presets folder"),
        ],
        default="IMPORTER",
    )

    def execute(self, context: Any) -> set[Any]:
        target_dir = str(
            PBRImportPresetManager.get_user_dir()
            if self.category == "IMPORTER"
            else PBRExportPresetManager.get_user_dir()
        )
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


class LOD_OT_delete_import_preset(Operator):
    """Permanently delete active custom import preset with confirmation."""

    bl_idname = "lod_tool.delete_import_preset"
    bl_label = "Delete Custom Preset"
    bl_description = "Deletes the active custom import preset file and resets to factory default"
    bl_options = {"REGISTER"}

    def invoke(self, context: Any, event: Any) -> set[Any]:
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

    def execute(self, context: Any) -> set[Any]:
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
            if PBRImportPresetManager.delete_custom_preset(preset_id):
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
    bl_options = {"REGISTER"}

    def invoke(self, context: Any, event: Any) -> set[Any]:
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

    def execute(self, context: Any) -> set[Any]:
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
            if PBRExportPresetManager.delete_custom_preset(preset_id):
                safe_report(self, {"INFO"}, f"Deleted custom preset '{preset_id}'.")
                return {"FINISHED"}
            safe_report(self, {"WARNING"}, f"Could not find or delete preset '{preset_id}'.")
            return {"CANCELLED"}
        except Exception as exc:
            logger.error("Failed to delete custom preset '%s': %s", preset_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Delete failed: {exc}")
            return {"CANCELLED"}


PBR_PRESET_OPERATOR_CLASSES = (
    *PBR_MAP_OPERATOR_CLASSES,
    LOD_OT_reload_pbr_presets,
    LOD_OT_reset_pbr_preset,
    LOD_OT_create_import_preset,
    LOD_OT_rename_import_preset,
    LOD_OT_create_export_preset,
    LOD_OT_rename_export_preset,
    LOD_OT_duplicate_preset,
    LOD_OT_duplicate_export_preset,
    LOD_OT_save_import_preset,
    LOD_OT_save_export_preset,
    LOD_OT_delete_import_preset,
    LOD_OT_delete_export_preset,
    LOD_OT_open_presets_directory,
)

__all__ = [
    "PBR_PRESET_OPERATOR_CLASSES",
    "LOD_OT_reload_pbr_presets",
    "LOD_OT_reset_pbr_preset",
    "LOD_OT_create_import_preset",
    "LOD_OT_rename_import_preset",
    "LOD_OT_create_export_preset",
    "LOD_OT_rename_export_preset",
    "LOD_OT_duplicate_preset",
    "LOD_OT_duplicate_export_preset",
    "LOD_OT_save_import_preset",
    "LOD_OT_save_export_preset",
    "LOD_OT_delete_import_preset",
    "LOD_OT_delete_export_preset",
    "LOD_OT_open_presets_directory",
    "LOD_OT_init_preset_maps",
    "LOD_OT_add_preset_map",
    "LOD_OT_add_map_template",
    "LOD_OT_delete_preset_map",
    "LOD_OT_move_preset_map",
    "LOD_OT_add_export_preset_map",
    "LOD_OT_add_export_map_template",
    "LOD_OT_delete_export_preset_map",
    "LOD_OT_move_export_preset_map",
]
