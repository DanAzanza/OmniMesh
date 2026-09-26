"""
OmniMesh Config Preset Spawning Operators.
Instantiates MSFS spatial markers, lights, cameras, exits, and engines from preset definitions
into the active asset collection hierarchy ({AssetName}_Config -> _Spatial, _Lights, _Cameras).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.props import StringProperty
    from bpy.types import Operator
    from mathutils import Euler, Vector
except ImportError:
    bpy = None
    Operator = object
    Euler = None
    Vector = None

    def StringProperty(**kwargs: Any) -> Any:
        return ""


if Vector is None:

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
    from ..core.hierarchy import get_or_create_engine_import_collection
    from ..core.msfs.preset_spawner import ConfigPresetSpawner
    from .utils import (
        get_asset_base_meshes,
        resolve_effective_asset_name,
        safe_report,
    )
except (ImportError, ValueError):
    from core.config_presets import DEFAULT_CONFIG_PRESET_ID, ConfigPresetManager
    from core.hierarchy import get_or_create_engine_import_collection
    from core.msfs.preset_spawner import ConfigPresetSpawner
    from ui.utils import (
        get_asset_base_meshes,
        resolve_effective_asset_name,
        safe_report,
    )


class OMNIMESH_OT_add_config_preset(Operator):
    """Adds missing MSFS configuration objects (spatial, lights, cameras, engines, exits) from preset."""

    bl_idname = "omnimesh.add_config_preset"
    bl_label = "Add Config Objects"
    bl_description = (
        "Adds missing MSFS configuration markers (Spatial, Lights, Cameras) to the active asset. "
        "Positions are automatically scaled and anchored to the active model geometry without overwriting existing objects."
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context)

    def execute(self, context: Any) -> set[str]:
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

        added_count = ConfigPresetSpawner.spawn_preset_objects(
            context=context,
            asset_name=asset_name,
            preset_data=preset_data,
            cfg_props=cfg_props,
            bpy_module=bpy,
            get_base_meshes_fn=get_asset_base_meshes,
            get_import_collection_fn=get_or_create_engine_import_collection,
        )

        msg = f"Added {added_count} missing config object(s) from preset '{preset_data.get('name', preset_id)}'."
        if cfg_props:
            cfg_props.last_spawn_summary = msg
        safe_report(self, {"INFO"}, msg)
        return {"FINISHED"}


class OMNIMESH_OT_duplicate_config_preset(Operator):
    """Duplicates active configuration preset as a custom editable preset."""

    bl_idname = "omnimesh.duplicate_config_preset"
    bl_label = "Duplicate Config Preset"
    bl_options = {"REGISTER", "UNDO"}

    new_name: StringProperty(
        name="Preset Name",
        description="Name for the duplicated config preset",
        default="Custom Aircraft",
    )

    def execute(self, context: Any) -> set[str]:
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

    def invoke(self, context: Any, event: Any) -> set[str]:
        wm = getattr(context, "window_manager", None)
        if wm and hasattr(wm, "invoke_props_dialog"):
            return wm.invoke_props_dialog(self)
        return self.execute(context)


class OMNIMESH_OT_delete_config_preset(Operator):
    """Deletes custom configuration preset from user storage."""

    bl_idname = "omnimesh.delete_config_preset"
    bl_label = "Delete Config Preset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        curr_id = getattr(cfg_props, "config_preset", "") if cfg_props else ""
        return bool(curr_id and not ConfigPresetManager.is_builtin(curr_id))

    def execute(self, context: Any) -> set[str]:
        props = getattr(context.scene, "lod_tool", None) if context else None
        cfg_props = getattr(props, "config_presets", None) if props else None
        curr_id = getattr(cfg_props, "config_preset", "") if cfg_props else ""

        # Safe fallback reassignment before deletion (KNOWLEDGE.md §1.7)
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
    OMNIMESH_OT_duplicate_config_preset,
    OMNIMESH_OT_delete_config_preset,
)


def register():
    if not bpy:
        return
    for cls in CONFIG_PRESET_OPERATOR_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Register skipped %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister():
    if not bpy:
        return
    for cls in reversed(CONFIG_PRESET_OPERATOR_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
