"""
OmniMesh PBR Texture Map and Channel Packing RNA Data Models.
Maintains interactive property groups and synchronization handlers for import and export presets.
"""

import copy
import logging
from typing import Any

from .guards import ExportMapSyncGuard, MapSyncGuard, PresetSyncGuard, StateRestorationGuard

try:
    from ...core.pbr_presets import (
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
except (ImportError, ValueError):
    from core.pbr_presets import (
        PBRExportPresetManager,
        PBRImportPresetManager,
    )

try:
    import bpy
    from bpy.props import (
        BoolProperty,
        EnumProperty,
        IntProperty,
        StringProperty,
    )
    from bpy.types import PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def BoolProperty(**kwargs: Any) -> Any:
        return None

    def EnumProperty(**kwargs: Any) -> Any:
        return None

    def IntProperty(**kwargs: Any) -> Any:
        return None

    def StringProperty(**kwargs: Any) -> Any:
        return None


logger = logging.getLogger(__name__)

PRINCIPLED_TARGET_ITEMS: list[tuple[str, str, str]] = [
    ("NONE", "None (Unused)", "Do not route this channel"),
    ("Base Color", "Base Color", "Diffuse / Albedo color input"),
    ("Roughness", "Roughness", "Surface microfacet roughness"),
    ("Metallic", "Metallic", "Metalness mask"),
    ("Normal", "Normal", "Tangent-space normal vector"),
    ("Ambient Occlusion", "Ambient Occlusion", "AO mask for Base Color multiplicative blend"),
    ("Alpha", "Alpha / Opacity", "Surface transparency mask"),
    ("Emission Color", "Emission Color", "Self-illumination color"),
    ("Displacement", "Displacement / Height", "Material Output height displacement"),
    ("Specular IOR Level", "Specular IOR Level", "Dielectric specular reflectivity level"),
]


def on_map_item_updated(self: Any, context: Any) -> None:
    """Invoked when a user modifies a map attribute in the interactive editor."""
    if MapSyncGuard.is_active() or StateRestorationGuard.is_active():
        return
    props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
    if not props:
        return
    sync_maps_to_preset(props)


def sync_maps_from_preset(props: Any, preset: dict[str, Any]) -> None:
    """Populates ephemeral RNA collection from preset dictionary under sync guard."""
    if not hasattr(props, "pbr_active_maps"):
        return
    preset_id = preset.get("id", "") or preset.get("_id", "") or getattr(props, "pbr_import_preset", "")
    with MapSyncGuard():
        props.pbr_active_maps.clear()
        if hasattr(props, "pbr_active_maps_preset_id"):
            props.pbr_active_maps_preset_id = str(preset_id)
        for m in preset.get("maps", []):
            item = props.pbr_active_maps.add()
            item.map_id = str(m.get("id", "map"))
            item.name = str(m.get("name", item.map_id))
            item.priority = int(m.get("priority", 10))
            suffixes = m.get("suffixes", [])
            item.suffixes_str = ", ".join(suffixes) if isinstance(suffixes, list) else str(suffixes)
            item.color_space = str(m.get("color_space", "Non-Color"))
            n_fmt = str(m.get("normal_format", "")).upper()

            channels = m.get("channels", {})
            is_normal_target = False
            if isinstance(channels, dict):
                for ch_val in channels.values():
                    if isinstance(ch_val, dict) and ch_val.get("target") == "Normal":
                        is_normal_target = True
                        break

            item.is_normal_map = is_normal_target or any(t in item.map_id.lower() for t in ("normal", "norm", "bump"))
            item.normal_format = n_fmt if n_fmt in {"OPENGL", "DIRECTX"} else "OPENGL"
            if "rgb" in channels:
                item.is_packed = False
                rgb_info = channels.get("rgb", {})
                item.target_rgb = rgb_info.get("target", "Base Color") if isinstance(rgb_info, dict) else "Base Color"
                if "a" in channels:
                    a_info = channels.get("a", {})
                    item.target_a = a_info.get("target", "NONE") if isinstance(a_info, dict) else "NONE"
                    item.invert_a = bool(a_info.get("invert", False)) if isinstance(a_info, dict) else False
                else:
                    item.target_a = "NONE"
                    item.invert_a = False
            else:
                item.is_packed = True
                for ch in ("r", "g", "b", "a"):
                    ch_data = channels.get(ch, {})
                    if isinstance(ch_data, dict):
                        setattr(item, f"target_{ch}", ch_data.get("target", "NONE"))
                        setattr(item, f"invert_{ch}", bool(ch_data.get("invert", False)))
                    else:
                        setattr(item, f"target_{ch}", "NONE")
                        setattr(item, f"invert_{ch}", False)

        if len(props.pbr_active_maps) > 0 and props.pbr_active_map_index >= len(props.pbr_active_maps):
            props.pbr_active_map_index = 0


def sync_maps_to_preset(props: Any) -> None:
    """Rebuilds JSON structure from RNA and persists to custom preset with safe CoW."""
    if MapSyncGuard.is_active() or StateRestorationGuard.is_active():
        return

    preset_id = getattr(props, "pbr_import_preset", "") or PBRImportPresetManager.DEFAULT_PRESET_ID

    # Handle Copy-on-Write for built-ins
    if PBRImportPresetManager.is_builtin(preset_id):
        with MapSyncGuard(), PresetSyncGuard():
            new_id = PBRImportPresetManager.duplicate_preset(preset_id)
            props.pbr_import_preset = new_id
            preset_id = new_id

    preset_data = copy.deepcopy(PBRImportPresetManager.get_preset(preset_id))
    new_maps = []

    for item in props.pbr_active_maps:
        raw_suffixes = [s.strip() for s in item.suffixes_str.split(",") if s.strip()]
        if not raw_suffixes:
            raw_suffixes = [f"_{item.map_id}"]

        channels: dict[str, Any] = {}
        if not item.is_packed:
            if item.target_rgb != "NONE":
                channels["rgb"] = {"target": item.target_rgb, "invert": False}
            if item.target_a != "NONE":
                channels["a"] = {"target": item.target_a, "invert": item.invert_a}
        else:
            for ch in ("r", "g", "b", "a"):
                target = getattr(item, f"target_{ch}")
                if target != "NONE":
                    channels[ch] = {
                        "target": target,
                        "invert": getattr(item, f"invert_{ch}"),
                        "default": 1.0 if "occlusion" in target.lower() else 0.0,
                    }

        if not channels:
            channels["rgb"] = {"target": "Base Color", "invert": False}

        map_dict = {
            "id": item.map_id,
            "name": item.name,
            "priority": int(item.priority),
            "suffixes": raw_suffixes,
            "color_space": item.color_space,
            "channels": channels,
        }
        if item.is_normal_map:
            map_dict["normal_format"] = item.normal_format

        new_maps.append(map_dict)

    preset_data["maps"] = new_maps
    PBRImportPresetManager.save_custom_preset(preset_data, custom_id=preset_id)


def on_export_map_item_updated(self: Any, context: Any) -> None:
    """Invoked when a user modifies an export map attribute in the interactive editor."""
    if ExportMapSyncGuard.is_active() or StateRestorationGuard.is_active():
        return
    props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
    if not props:
        return
    sync_export_maps_to_preset(props)


def sync_export_maps_from_preset(props: Any, preset: dict[str, Any]) -> None:
    """Populates ephemeral export RNA collection from preset dictionary under sync guard."""
    if not hasattr(props, "pbr_export_active_maps"):
        return
    preset_id = preset.get("id", "") or preset.get("_id", "") or getattr(props, "pbr_export_preset", "")
    with ExportMapSyncGuard():
        props.pbr_export_active_maps.clear()
        if hasattr(props, "pbr_export_active_maps_preset_id"):
            props.pbr_export_active_maps_preset_id = str(preset_id)
        for m in preset.get("maps", []):
            item = props.pbr_export_active_maps.add()
            item.map_id = str(m.get("id", "map"))
            item.name = str(m.get("name", item.map_id))
            item.export = bool(m.get("export", True))
            item.export_suffix = str(m.get("export_suffix", f"_{item.map_id}"))
            item.color_space = str(m.get("color_space", "Non-Color"))
            n_fmt = str(m.get("normal_format", "")).upper()

            channels = m.get("channels", {})
            is_normal_target = False
            if isinstance(channels, dict):
                for ch_val in channels.values():
                    if isinstance(ch_val, dict) and ch_val.get("target") == "Normal":
                        is_normal_target = True
                        break

            item.is_normal_map = is_normal_target or any(t in item.map_id.lower() for t in ("normal", "norm", "bump"))
            item.normal_format = n_fmt if n_fmt in {"OPENGL", "DIRECTX"} else "OPENGL"
            if "rgb" in channels:
                item.is_packed = False
                rgb_info = channels.get("rgb", {})
                item.target_rgb = rgb_info.get("target", "Base Color") if isinstance(rgb_info, dict) else "Base Color"
                if "a" in channels:
                    a_info = channels.get("a", {})
                    item.target_a = a_info.get("target", "NONE") if isinstance(a_info, dict) else "NONE"
                    item.invert_a = bool(a_info.get("invert", False)) if isinstance(a_info, dict) else False
                else:
                    item.target_a = "NONE"
                    item.invert_a = False
            else:
                item.is_packed = True
                for ch in ("r", "g", "b", "a"):
                    ch_data = channels.get(ch, {})
                    if isinstance(ch_data, dict):
                        setattr(item, f"target_{ch}", ch_data.get("target", "NONE"))
                        setattr(item, f"invert_{ch}", bool(ch_data.get("invert", False)))
                    else:
                        setattr(item, f"target_{ch}", "NONE")
                        setattr(item, f"invert_{ch}", False)

        if len(props.pbr_export_active_maps) > 0 and props.pbr_export_active_map_index >= len(
            props.pbr_export_active_maps
        ):
            props.pbr_export_active_map_index = 0


def sync_export_maps_to_preset(props: Any) -> None:
    """Rebuilds JSON structure from export RNA and persists to custom preset with safe CoW."""
    if ExportMapSyncGuard.is_active() or StateRestorationGuard.is_active():
        return

    preset_id = getattr(props, "pbr_export_preset", "") or PBRExportPresetManager.DEFAULT_PRESET_ID

    # Handle Copy-on-Write for built-ins
    if PBRExportPresetManager.is_builtin(preset_id):
        with ExportMapSyncGuard(), PresetSyncGuard():
            new_id = PBRExportPresetManager.duplicate_preset(preset_id)
            props.pbr_export_preset = new_id
            if hasattr(props, "pbr_preset"):
                props.pbr_preset = new_id
            preset_id = new_id
            PBRExportPresetManager.set_last_active_preset(new_id)

    preset_data = copy.deepcopy(PBRExportPresetManager.get_preset(preset_id))
    new_maps = []

    for item in props.pbr_export_active_maps:
        export_suffix = item.export_suffix.strip()
        if not export_suffix:
            export_suffix = f"_{item.map_id}"

        channels: dict[str, Any] = {}
        if not item.is_packed:
            if item.target_rgb != "NONE":
                channels["rgb"] = {"target": item.target_rgb, "invert": False}
            if item.target_a != "NONE":
                channels["a"] = {"target": item.target_a, "invert": item.invert_a}
        else:
            for ch in ("r", "g", "b", "a"):
                target = getattr(item, f"target_{ch}")
                if target != "NONE":
                    channels[ch] = {
                        "target": target,
                        "invert": getattr(item, f"invert_{ch}"),
                        "default": 1.0 if "occlusion" in target.lower() else 0.0,
                    }

        if not channels:
            channels["rgb"] = {"target": "Base Color", "invert": False}

        map_dict = {
            "id": item.map_id,
            "name": item.name,
            "export": bool(item.export),
            "export_suffix": export_suffix,
            "color_space": item.color_space,
            "channels": channels,
        }
        if item.is_normal_map:
            map_dict["normal_format"] = item.normal_format

        new_maps.append(map_dict)

    preset_data["maps"] = new_maps
    PBRExportPresetManager.save_custom_preset(preset_data, custom_id=preset_id)


class PBRMapItem(PropertyGroup):
    """Data model representing a single texture map in the active preset."""

    map_id: StringProperty(name="Map ID", default="custom_map")
    name: StringProperty(name="Display Name", default="New Map", update=on_map_item_updated)
    priority: IntProperty(name="Priority", default=10, min=1, max=1000, update=on_map_item_updated)
    suffixes_str: StringProperty(
        name="Suffixes",
        description="Comma-separated file suffixes (e.g. _BaseColor, _BC, _Albedo)",
        default="_Custom",
        update=on_map_item_updated,
    )
    color_space: EnumProperty(
        name="Color Space",
        items=[("sRGB", "sRGB", "Color data"), ("Non-Color", "Non-Color", "Linear scalar/data mask")],
        default="Non-Color",
        update=on_map_item_updated,
    )
    is_normal_map: BoolProperty(name="Is Normal Map", default=False, update=on_map_item_updated)
    normal_format: EnumProperty(
        name="Normal Format",
        items=[
            ("OPENGL", "OpenGL (+Y)", "Standard OpenGL format"),
            ("DIRECTX", "DirectX (-Y)", "Invert Green channel for Unreal/DirectX"),
        ],
        default="OPENGL",
        update=on_map_item_updated,
    )
    is_packed: BoolProperty(name="Channel Packed", default=False, update=on_map_item_updated)

    # Single RGB Routing
    target_rgb: EnumProperty(
        name="RGB Target", items=PRINCIPLED_TARGET_ITEMS, default="Base Color", update=on_map_item_updated
    )
    target_a: EnumProperty(
        name="Alpha Target", items=PRINCIPLED_TARGET_ITEMS, default="NONE", update=on_map_item_updated
    )
    invert_a: BoolProperty(name="Invert Alpha", default=False, update=on_map_item_updated)

    # Packed R, G, B, A Routing
    target_r: EnumProperty(
        name="R Target", items=PRINCIPLED_TARGET_ITEMS, default="Ambient Occlusion", update=on_map_item_updated
    )
    invert_r: BoolProperty(name="Invert R", default=False, update=on_map_item_updated)
    target_g: EnumProperty(
        name="G Target", items=PRINCIPLED_TARGET_ITEMS, default="Roughness", update=on_map_item_updated
    )
    invert_g: BoolProperty(name="Invert G", default=False, update=on_map_item_updated)
    target_b: EnumProperty(
        name="B Target", items=PRINCIPLED_TARGET_ITEMS, default="Metallic", update=on_map_item_updated
    )
    invert_b: BoolProperty(name="Invert B", default=False, update=on_map_item_updated)


class PBRExportMapItem(PropertyGroup):
    """Data model representing a single texture map in the active export preset."""

    map_id: StringProperty(name="Map ID", default="custom_map")
    name: StringProperty(name="Display Name", default="New Map", update=on_export_map_item_updated)
    export: BoolProperty(
        name="Export", default=True, description="Enable export for this map", update=on_export_map_item_updated
    )
    export_suffix: StringProperty(
        name="Suffix",
        description="File suffix on export (e.g. _BaseColor, _ORM)",
        default="_Custom",
        update=on_export_map_item_updated,
    )
    color_space: EnumProperty(
        name="Color Space",
        items=[("sRGB", "sRGB", "Color data"), ("Non-Color", "Non-Color", "Linear scalar/data mask")],
        default="Non-Color",
        update=on_export_map_item_updated,
    )
    is_normal_map: BoolProperty(name="Is Normal Map", default=False, update=on_export_map_item_updated)
    normal_format: EnumProperty(
        name="Normal Format",
        items=[
            ("OPENGL", "OpenGL (+Y)", "Standard OpenGL format"),
            ("DIRECTX", "DirectX (-Y)", "Invert Green channel for Unreal/DirectX"),
        ],
        default="OPENGL",
        update=on_export_map_item_updated,
    )
    is_packed: BoolProperty(name="Channel Packed", default=False, update=on_export_map_item_updated)

    # Single RGB Routing
    target_rgb: EnumProperty(
        name="RGB Target", items=PRINCIPLED_TARGET_ITEMS, default="Base Color", update=on_export_map_item_updated
    )
    target_a: EnumProperty(
        name="Alpha Target", items=PRINCIPLED_TARGET_ITEMS, default="NONE", update=on_export_map_item_updated
    )
    invert_a: BoolProperty(name="Invert Alpha", default=False, update=on_export_map_item_updated)

    # Packed R, G, B, A Routing
    target_r: EnumProperty(
        name="R Target", items=PRINCIPLED_TARGET_ITEMS, default="Ambient Occlusion", update=on_export_map_item_updated
    )
    invert_r: BoolProperty(name="Invert R", default=False, update=on_export_map_item_updated)
    target_g: EnumProperty(
        name="G Target", items=PRINCIPLED_TARGET_ITEMS, default="Roughness", update=on_export_map_item_updated
    )
    invert_g: BoolProperty(name="Invert G", default=False, update=on_export_map_item_updated)
    target_b: EnumProperty(
        name="B Target", items=PRINCIPLED_TARGET_ITEMS, default="Metallic", update=on_export_map_item_updated
    )
    invert_b: BoolProperty(name="Invert B", default=False, update=on_export_map_item_updated)


__all__ = [
    "PRINCIPLED_TARGET_ITEMS",
    "PBRMapItem",
    "PBRExportMapItem",
    "on_map_item_updated",
    "sync_maps_from_preset",
    "sync_maps_to_preset",
    "on_export_map_item_updated",
    "sync_export_maps_from_preset",
    "sync_export_maps_to_preset",
]
