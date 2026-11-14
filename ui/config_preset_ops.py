# pyright: reportInvalidTypeForm=none
"""
OmniMesh Config Preset Spawning Operators.
Instantiates MSFS spatial markers, lights, cameras, exits, and engines from preset definitions
into the active asset collection hierarchy ({AssetName}_Config -> _Spatial, _Lights, _Cameras).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.props import EnumProperty, StringProperty
    from bpy.types import Operator
    from mathutils import Euler, Vector
else:
    try:
        import bpy
        from bpy.props import EnumProperty, StringProperty
        from bpy.types import Operator
        from mathutils import Euler, Vector
    except ImportError:
        bpy = None
        Operator = object
        Euler = None
        Vector = None

        def EnumProperty(**kwargs: Any) -> Any:
            return Any

        def StringProperty(**kwargs: Any) -> Any:
            return Any


if not TYPE_CHECKING and Vector is None:

    class Vector(tuple):  # type: ignore[no-redef]
        def __new__(cls, coords):
            return super().__new__(cls, (float(c) for c in coords))

        @property
        def x(self) -> float:
            return self[0]

        @property
        def y(self) -> float:
            return self[1]

        @property
        def z(self) -> float:
            return self[2]

        def __add__(self, other):
            return Vector((self[0] + other[0], self[1] + other[1], self[2] + other[2]))

        def __sub__(self, other):
            return Vector((self[0] - other[0], self[1] - other[1], self[2] - other[2]))

        def __mul__(self, scalar):
            return Vector((self[0] * scalar, self[1] * scalar, self[2] * scalar))

        def __rmul__(self, scalar):
            return Vector((self[0] * scalar, self[1] * scalar, self[2] * scalar))


try:
    from ..core.config_presets import DEFAULT_CONFIG_PRESET_ID, ConfigPresetManager
    from ..core.preset_spawner import ConfigPresetSpawner
    from .utils import (
        get_asset_base_meshes,
        get_or_create_engine_import_collection,
        resolve_effective_asset_name,
        safe_report,
    )
except (ImportError, ValueError):
    from core.config_presets import DEFAULT_CONFIG_PRESET_ID, ConfigPresetManager
    from core.preset_spawner import ConfigPresetSpawner
    from ui.utils import (
        get_asset_base_meshes,
        get_or_create_engine_import_collection,
        resolve_effective_asset_name,
        safe_report,
    )


class OMNIMESH_OT_add_config_preset(Operator):
    """Adds missing configuration objects (spatial, lights, cameras, exits, engines, interactions) from preset."""

    bl_idname = "omnimesh.add_config_preset"
    bl_label = "Add Config Objects"
    bl_description = (
        "Spawn missing configuration objects (Spatial, Lights, Cameras, Exits, Engines, Interactions) "
        "from the active preset without overwriting existing objects"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context)

    def execute(self, context: Any) -> set[Any]:
        if not bpy or not context:
            return {"FINISHED"}

        scene = getattr(context, "scene", None)
        props = getattr(scene, "lod_tool", None) if scene else None
        cfg_props = getattr(props, "config_presets", None) if props else None

        asset_name = resolve_effective_asset_name(context, props)
        if not asset_name or asset_name in ("AUTO", "NONE"):
            asset_name = "Asset"

        preset_id = (
            getattr(cfg_props, "config_preset", DEFAULT_CONFIG_PRESET_ID) if cfg_props else DEFAULT_CONFIG_PRESET_ID
        )
        preset_data = ConfigPresetManager.get_preset(preset_id)
        if not preset_data:
            safe_report(self, {"ERROR"}, f"Could not load config preset '{preset_id}'.")
            return {"CANCELLED"}

        bdata = getattr(context, "blend_data", None) or (bpy.data if bpy and hasattr(bpy, "data") else None)
        if bdata is None:
            return {"CANCELLED"}

        added_count = ConfigPresetSpawner.spawn_preset_objects(
            context=context,
            asset_name=asset_name,
            preset_data=preset_data,
            cfg_props=cfg_props,
            blend_data=bdata,
            bpy_module=bpy,
            get_base_meshes_fn=get_asset_base_meshes,
            get_import_collection_fn=get_or_create_engine_import_collection,
        )

        msg = f"Added {added_count} missing config object(s) from preset '{preset_data.get('name', preset_id)}'."
        if cfg_props:
            cfg_props.last_spawn_summary = msg
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


class OMNIMESH_OT_create_config_preset(Operator):
    """Create a new custom configuration preset from a starter template."""

    bl_idname = "omnimesh.create_config_preset"
    bl_label = "New Config Preset"
    bl_description = "Creates a new custom configuration preset profile from a starter template"
    bl_options = {"REGISTER", "UNDO"}

    preset_name: StringProperty(
        name="Preset Name",
        description="Display name for the new custom config preset",
        default="Custom Aircraft",
    )

    template_type: EnumProperty(
        name="Starter Template",
        items=[
            ("plane_general_aviation", "General Aviation (Single/Twin)", "Cessna 172 / DA40 style GA aircraft"),
            ("plane_commercial_airliner", "Commercial Airliner (Twin-Jet)", "A320 / B737 style twin-jet airliner"),
            ("plane_taildragger", "Taildragger (Tailwheel GA)", "Cub / bush-plane tailwheel configuration"),
            ("helicopter_standard", "Helicopter (Single Main Rotor)", "Single main rotor + tail rotor helicopter"),
            ("glider_sailplane", "Glider / Sailplane", "Unpowered glider configuration"),
            ("car_playermodel", "Car - Playermodel", "4-wheel ground vehicle configuration"),
            ("minimal", "Minimal (Empty Markers)", "Blank config preset template"),
        ],
        default="plane_general_aviation",
    )

    def invoke(self, context: Any, event: Any) -> set[Any]:
        wm = getattr(context, "window_manager", None)
        if wm and hasattr(wm, "invoke_props_dialog"):
            return wm.invoke_props_dialog(self, width=320)
        return self.execute(context)

    def draw(self, context: Any) -> None:
        if not bpy or not self.layout:
            return
        col = self.layout.column(align=True)
        col.prop(self, "preset_name", text="Name")
        col.separator()
        col.prop(self, "template_type", text="Template")

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        try:
            new_id = ConfigPresetManager.create_new_preset(
                name=self.preset_name,
                template_id=self.template_type,
            )
            if cfg_props and hasattr(cfg_props, "config_preset"):
                cfg_props.config_preset = new_id
            safe_report(self, {"INFO"}, f"Created config preset '{self.preset_name}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed creating config preset: %s", exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Could not create preset: {exc}")
            return {"CANCELLED"}


class OMNIMESH_OT_rename_config_preset(Operator):
    """Rename the active custom MSFS configuration preset."""

    bl_idname = "omnimesh.rename_config_preset"
    bl_label = "Rename Config Preset"
    bl_description = "Renames the active custom configuration preset"
    bl_options = {"REGISTER", "UNDO"}

    new_name: StringProperty(
        name="New Name",
        description="New display name for the custom config preset",
        default="",
    )

    def invoke(self, context: Any, event: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        curr_id = (
            getattr(cfg_props, "config_preset", DEFAULT_CONFIG_PRESET_ID) if cfg_props else DEFAULT_CONFIG_PRESET_ID
        )
        if ConfigPresetManager.is_builtin(curr_id):
            safe_report(self, {"ERROR"}, "Built-in factory presets cannot be renamed. Duplicate it first.")
            return {"CANCELLED"}
        preset = ConfigPresetManager.get_preset(curr_id)
        self.new_name = preset.get("name", curr_id)
        wm = getattr(context, "window_manager", None)
        if wm and hasattr(wm, "invoke_props_dialog"):
            return wm.invoke_props_dialog(self, width=300)
        return self.execute(context)

    def draw(self, context: Any) -> None:
        if not bpy or not self.layout:
            return
        self.layout.prop(self, "new_name", text="Name")

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        old_id = (
            getattr(cfg_props, "config_preset", DEFAULT_CONFIG_PRESET_ID) if cfg_props else DEFAULT_CONFIG_PRESET_ID
        )
        if ConfigPresetManager.is_builtin(old_id):
            safe_report(self, {"ERROR"}, "Cannot rename built-in factory presets.")
            return {"CANCELLED"}
        clean_name = self.new_name.strip()
        if not clean_name:
            safe_report(self, {"ERROR"}, "Preset name cannot be empty.")
            return {"CANCELLED"}
        try:
            new_id = ConfigPresetManager.rename_custom_preset(old_id, clean_name)
            if cfg_props and hasattr(cfg_props, "config_preset"):
                cfg_props.config_preset = new_id
            safe_report(self, {"INFO"}, f"Renamed config preset to '{clean_name}'.")
            return {"FINISHED"}
        except Exception as exc:
            logger.error("Failed renaming config preset '%s': %s", old_id, exc, exc_info=True)
            safe_report(self, {"ERROR"}, f"Rename failed: {exc}")
            return {"CANCELLED"}


class OMNIMESH_OT_duplicate_config_preset(Operator):
    """Duplicates active configuration preset as a custom editable preset."""

    bl_idname = "omnimesh.duplicate_config_preset"
    bl_label = "Duplicate Config Preset"
    bl_description = "Duplicate the active configuration preset into an editable user copy"
    bl_options = {"REGISTER", "UNDO"}

    new_name: StringProperty(
        name="Preset Name",
        description="Name for the duplicated config preset",
        default="Custom Aircraft",
    )

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        curr_id = (
            getattr(cfg_props, "config_preset", DEFAULT_CONFIG_PRESET_ID) if cfg_props else DEFAULT_CONFIG_PRESET_ID
        )

        new_id = ConfigPresetManager.duplicate_preset(curr_id, self.new_name)
        if new_id and cfg_props:
            cfg_props.config_preset = new_id
            safe_report(self, {"INFO"}, f"Created custom preset '{new_id}'.")
            return {"FINISHED"}

        safe_report(self, {"WARNING"}, "Failed duplicating config preset.")
        return {"CANCELLED"}

    def invoke(self, context: Any, event: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        curr_id = (
            getattr(cfg_props, "config_preset", DEFAULT_CONFIG_PRESET_ID) if cfg_props else DEFAULT_CONFIG_PRESET_ID
        )
        preset = ConfigPresetManager.get_preset(curr_id)
        self.new_name = f"{preset.get('name', curr_id)} (Copy)"
        wm = getattr(context, "window_manager", None)
        if wm and hasattr(wm, "invoke_props_dialog"):
            return wm.invoke_props_dialog(self, width=300)
        return self.execute(context)

    def draw(self, context: Any) -> None:
        if not bpy or not self.layout:
            return
        self.layout.prop(self, "new_name", text="Name")


class OMNIMESH_OT_delete_config_preset(Operator):
    """Deletes custom configuration preset from user storage."""

    bl_idname = "omnimesh.delete_config_preset"
    bl_label = "Delete Config Preset"
    bl_description = "Delete the active custom configuration preset from user storage"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        curr_id = getattr(cfg_props, "config_preset", "") if cfg_props else ""
        return bool(curr_id and not ConfigPresetManager.is_builtin(curr_id))

    def invoke(self, context: Any, event: Any) -> set[Any]:
        wm = getattr(context, "window_manager", None)
        if wm and hasattr(wm, "invoke_confirm"):
            return wm.invoke_confirm(self, event)
        return self.execute(context)

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        curr_id = getattr(cfg_props, "config_preset", "") if cfg_props else ""

        # Safe fallback reassignment before deletion (BLENDER_KNOWLEDGE.md §3)
        if cfg_props:
            cfg_props.config_preset = DEFAULT_CONFIG_PRESET_ID

        ok = ConfigPresetManager.delete_preset(curr_id)
        if ok:
            safe_report(self, {"INFO"}, f"Deleted preset '{curr_id}'.")
            return {"FINISHED"}

        safe_report(self, {"WARNING"}, f"Could not delete preset '{curr_id}'.")
        return {"CANCELLED"}


CONFIG_PRESET_OPERATOR_CLASSES = (
    OMNIMESH_OT_add_config_preset,
    OMNIMESH_OT_create_config_preset,
    OMNIMESH_OT_rename_config_preset,
    OMNIMESH_OT_duplicate_config_preset,
    OMNIMESH_OT_delete_config_preset,
)


def register():
    from .rna_helpers import register_classes

    register_classes(bpy, CONFIG_PRESET_OPERATOR_CLASSES, logger_inst=logger)


def unregister():
    from .rna_helpers import unregister_classes

    unregister_classes(bpy, CONFIG_PRESET_OPERATOR_CLASSES, logger_inst=logger)
