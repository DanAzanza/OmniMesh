# pyright: reportInvalidTypeForm=none
"""
OmniMesh PBR Map Rules & Channel Routing Interactive Operators.
Handles adding, templating, removing, and reordering texture map rules in active presets.
"""

from __future__ import annotations

from contextlib import nullcontext
import logging
from typing import TYPE_CHECKING, Any

try:
    from ..core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from .properties import (
        ExportMapSyncGuard,
        MapSyncGuard,
        sync_export_maps_to_preset,
        sync_maps_to_preset,
    )
    from .utils import resolve_lod_context, safe_report
except (ImportError, ValueError):
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRExportPresetManager,
        PBRImportPresetManager,
    )
    from ui.properties import (
        ExportMapSyncGuard,
        MapSyncGuard,
        sync_export_maps_to_preset,
        sync_maps_to_preset,
    )
    from ui.utils import resolve_lod_context, safe_report

if TYPE_CHECKING:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
    from bpy.types import Operator
else:
    try:
        import bpy
        from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
        from bpy.types import Operator
    except ImportError:
        bpy = None
        Operator = object

        def BoolProperty(**kwargs: Any) -> Any:
            return Any

        def EnumProperty(**kwargs: Any) -> Any:
            return Any

        def IntProperty(**kwargs: Any) -> Any:
            return Any

        def StringProperty(**kwargs: Any) -> Any:
            return Any


logger = logging.getLogger(__name__)

MAP_TEMPLATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "BASE_COLOR": {
        "map_id": "base_color",
        "name": "Base Color",
        "suffixes": "_BaseColor, _BC, _Albedo, _Diff, _Diffuse, _Col, _Color",
        "color_space": "sRGB",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Base Color",
        "invert_rgb": False,
        "target_a": "Alpha",
        "invert_a": False,
    },
    "ROUGHNESS": {
        "map_id": "roughness",
        "name": "Roughness",
        "suffixes": "_Roughness, _Rough, _RGH, _R",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Roughness",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
    "GLOSSINESS": {
        "map_id": "glossiness",
        "name": "Glossiness (Inverted Roughness)",
        "suffixes": "_Glossiness, _Gloss, _Smoothness",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Roughness",
        "invert_rgb": True,
        "target_a": "NONE",
        "invert_a": False,
    },
    "METALLIC": {
        "map_id": "metallic",
        "name": "Metallic",
        "suffixes": "_Metallic, _Metal, _MET, _M",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Metallic",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
    "NORMAL_OPENGL": {
        "map_id": "normal_gl",
        "name": "Normal Map (OpenGL)",
        "suffixes": "_Normal, _Norm, _NRM, _N, _NormalGL",
        "color_space": "Non-Color",
        "is_normal_map": True,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Normal",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
    "NORMAL_DIRECTX": {
        "map_id": "normal_dx",
        "name": "Normal Map (DirectX)",
        "suffixes": "_NormalDX, _NormDX, _Normal_DirectX",
        "color_space": "Non-Color",
        "is_normal_map": True,
        "normal_format": "DIRECTX",
        "is_packed": False,
        "target_rgb": "Normal",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
    "OCCLUSION": {
        "map_id": "occlusion",
        "name": "Ambient Occlusion",
        "suffixes": "_AO, _AmbientOcclusion, _Occ",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Ambient Occlusion",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
    "ORM": {
        "map_id": "orm",
        "name": "Packed ORM (UE5)",
        "suffixes": "_ORM, _OccRoughMetal, _ARM",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": True,
        "target_r": "Ambient Occlusion",
        "invert_r": False,
        "target_g": "Roughness",
        "invert_g": False,
        "target_b": "Metallic",
        "invert_b": False,
    },
    "MSFS_COMP": {
        "map_id": "comp",
        "name": "Packed COMP (MSFS 2024)",
        "suffixes": "_COMP",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": True,
        "target_r": "Ambient Occlusion",
        "invert_r": False,
        "target_g": "Roughness",
        "invert_g": False,
        "target_b": "Metallic",
        "invert_b": False,
    },
    "UNITY_MASKMAP": {
        "map_id": "maskmap",
        "name": "Packed MaskMap (Unity HDRP)",
        "suffixes": "_MaskMap, _Mask",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": True,
        "target_r": "Metallic",
        "invert_r": False,
        "target_g": "Ambient Occlusion",
        "invert_g": False,
        "target_b": "NONE",
        "invert_b": False,
        "target_a": "Roughness",
        "invert_a": True,
    },
    "DISPLACEMENT": {
        "map_id": "displacement",
        "name": "Height / Displacement",
        "suffixes": "_Height, _Disp, _Displacement, _Bump",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Displacement",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
    "EMISSION": {
        "map_id": "emission",
        "name": "Emission / Emissive",
        "suffixes": "_Emissive, _Emission, _Emit, _E",
        "color_space": "sRGB",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Emission Color",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
    "ALPHA": {
        "map_id": "alpha",
        "name": "Alpha / Opacity",
        "suffixes": "_Alpha, _Opacity, _Mask",
        "color_space": "Non-Color",
        "is_normal_map": False,
        "normal_format": "OPENGL",
        "is_packed": False,
        "target_rgb": "Alpha",
        "invert_rgb": False,
        "target_a": "NONE",
        "invert_a": False,
    },
}

TEMPLATE_ITEMS: list[tuple[str, str, str]] = [
    ("BASE_COLOR", "Base Color / Albedo", "Diffuse / Base Color map with standard suffixes"),
    ("ROUGHNESS", "Roughness", "Roughness scalar map"),
    ("GLOSSINESS", "Glossiness (Inverted)", "Inverted roughness scalar map"),
    ("METALLIC", "Metallic", "Metalness scalar map"),
    ("NORMAL_OPENGL", "Normal Map (OpenGL)", "Tangent-space normal (+Y green)"),
    ("NORMAL_DIRECTX", "Normal Map (DirectX)", "Tangent-space normal (-Y green inverted)"),
    ("OCCLUSION", "Ambient Occlusion", "Ambient occlusion mask"),
    ("ORM", "Packed ORM (R:AO, G:Rough, B:Metal)", "Unreal Engine 5 packed texture format"),
    ("MSFS_COMP", "Packed COMP (MSFS 2024)", "Microsoft Flight Simulator COMP texture format"),
    ("UNITY_MASKMAP", "Packed MaskMap (Unity HDRP)", "Unity HDRP packed MaskMap format"),
    ("DISPLACEMENT", "Height / Displacement", "Height displacement mask"),
    ("EMISSION", "Emission / Emissive", "Self-illumination color map"),
    ("ALPHA", "Alpha / Opacity", "Cutout or transparency opacity mask"),
]


class LOD_OT_init_preset_maps(Operator):
    """Initializes active PBR preset maps from built-in or custom definition."""

    bl_idname = "lod_tool.init_preset_maps"
    bl_label = "Initialize Preset Maps"
    bl_description = "Synchronizes active preset maps for texture import and export"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        from .properties import sync_export_maps_from_preset, sync_maps_from_preset

        props, _, _ = resolve_lod_context(context)
        if not props and hasattr(context, "scene"):
            props = getattr(context.scene, "lod_tool", None)
        if not props:
            return {"CANCELLED"}

        imp_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        exp_id = getattr(props, "pbr_export_preset", "") or DEFAULT_PRESET_ID
        sync_maps_from_preset(props, PBRImportPresetManager.get_preset(imp_id))
        sync_export_maps_from_preset(props, PBRExportPresetManager.get_preset(exp_id))
        safe_report(self, {"INFO"}, "Initialized active preset maps.")
        return {"FINISHED"}


class LOD_OT_add_preset_map(Operator):
    """Add a new custom texture map rule to the active import preset."""

    bl_idname = "lod_tool.add_preset_map"
    bl_label = "Add Custom Map"
    bl_description = "Adds a new texture map rule to the active preset"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
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
            item.invert_rgb = False
            props.pbr_active_map_index = len(props.pbr_active_maps) - 1
            for i, m in enumerate(props.pbr_active_maps):
                m.priority = (i + 1) * 10

        if sync_maps_to_preset:
            sync_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Added map '{item.name}'.")
        return {"FINISHED"}


class LOD_OT_add_map_template(Operator):
    """Add a standard PBR texture map rule preconfigured with industry-standard suffixes and channels."""

    bl_idname = "lod_tool.add_map_template"
    bl_label = "Add Standard PBR Map"
    bl_description = "Adds a standard PBR texture map with preconfigured suffixes, color space, and socket routing"
    bl_options = {"REGISTER"}

    template_type: EnumProperty(
        name="Texture Type",
        items=TEMPLATE_ITEMS,
        default="BASE_COLOR",
    )

    def invoke(self, context: Any, event: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context: Any) -> None:
        if not bpy or not self.layout:
            return
        layout = self.layout
        layout.prop(self, "template_type", text="Map Type")

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
            return {"CANCELLED"}

        t_data = MAP_TEMPLATE_DEFINITIONS.get(self.template_type)
        if not t_data:
            return {"CANCELLED"}

        with MapSyncGuard() if MapSyncGuard else nullcontext():
            item = props.pbr_active_maps.add()
            item.map_id = t_data["map_id"]
            item.name = t_data["name"]
            item.suffixes_str = t_data["suffixes"]
            item.color_space = t_data["color_space"]
            item.is_normal_map = t_data["is_normal_map"]
            item.normal_format = t_data["normal_format"]
            item.is_packed = t_data["is_packed"]

            if not item.is_packed:
                item.target_rgb = t_data.get("target_rgb", "Base Color")
                item.invert_rgb = t_data.get("invert_rgb", False)
                item.target_a = t_data.get("target_a", "NONE")
                item.invert_a = t_data.get("invert_a", False)
            else:
                for ch in ("r", "g", "b", "a"):
                    setattr(item, f"target_{ch}", t_data.get(f"target_{ch}", "NONE"))
                    setattr(item, f"invert_{ch}", t_data.get(f"invert_{ch}", False))

            props.pbr_active_map_index = len(props.pbr_active_maps) - 1
            for i, m in enumerate(props.pbr_active_maps):
                m.priority = (i + 1) * 10

        if sync_maps_to_preset:
            sync_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Added PBR map rule '{item.name}'.")
        return {"FINISHED"}


class LOD_OT_delete_preset_map(Operator):
    """Delete the selected texture map rule from the active import preset."""

    bl_idname = "lod_tool.delete_preset_map"
    bl_label = "Delete Map Definition"
    bl_description = "Removes the selected texture map rule from the active preset"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
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
            for i, m in enumerate(props.pbr_active_maps):
                m.priority = (i + 1) * 10

        if sync_maps_to_preset:
            sync_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Deleted map '{deleted_name}'.")
        return {"FINISHED"}


class LOD_OT_move_preset_map(Operator):
    """Move texture map rule up or down in the evaluation sequence."""

    bl_idname = "lod_tool.move_preset_map"
    bl_label = "Move Map Rule"
    bl_description = "Moves selected map rule up or down, automatically synchronizing classifier priority"
    bl_options = {"REGISTER"}

    direction: EnumProperty(
        name="Direction",
        items=[("UP", "Up", "Move rule earlier in priority"), ("DOWN", "Down", "Move rule later in priority")],
        default="UP",
    )

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_import_preset", "") or DEFAULT_PRESET_ID
        if PBRImportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
            return {"CANCELLED"}

        count = len(props.pbr_active_maps)
        idx = props.pbr_active_map_index
        if idx < 0 or idx >= count:
            return {"CANCELLED"}

        target_idx = idx - 1 if self.direction == "UP" else idx + 1
        if 0 <= target_idx < count:
            with MapSyncGuard() if MapSyncGuard else nullcontext():
                props.pbr_active_maps.move(idx, target_idx)
                props.pbr_active_map_index = target_idx
                for i, m in enumerate(props.pbr_active_maps):
                    m.priority = (i + 1) * 10

            if sync_maps_to_preset:
                sync_maps_to_preset(props)
            return {"FINISHED"}

        return {"CANCELLED"}


class LOD_OT_add_export_preset_map(Operator):
    """Add a new texture map rule to the active export preset."""

    bl_idname = "lod_tool.add_export_preset_map"
    bl_label = "Add Export Map Definition"
    bl_description = "Adds a new texture map rule to the active export preset"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_export_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
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
            item.invert_rgb = False
            props.pbr_export_active_map_index = len(props.pbr_export_active_maps) - 1

        if sync_export_maps_to_preset:
            sync_export_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Added export map '{item.name}'.")
        return {"FINISHED"}


class LOD_OT_add_export_map_template(Operator):
    """Add a standard PBR export texture map rule preconfigured with suffixes and channels."""

    bl_idname = "lod_tool.add_export_map_template"
    bl_label = "Add Standard Export Map"
    bl_description = "Adds a standard PBR export map with preconfigured suffix, color space, and socket routing"
    bl_options = {"REGISTER"}

    template_type: EnumProperty(
        name="Texture Type",
        items=TEMPLATE_ITEMS,
        default="BASE_COLOR",
    )

    def invoke(self, context: Any, event: Any) -> set[Any]:
        if not bpy:
            return {"FINISHED"}
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
            return {"CANCELLED"}
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context: Any) -> None:
        if not bpy or not self.layout:
            return
        self.layout.prop(self, "template_type", text="Map Type")

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_export_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
            return {"CANCELLED"}

        t_data = MAP_TEMPLATE_DEFINITIONS.get(self.template_type)
        if not t_data:
            return {"CANCELLED"}

        first_suffix = t_data["suffixes"].split(",")[0].strip()
        with ExportMapSyncGuard() if ExportMapSyncGuard else nullcontext():
            item = props.pbr_export_active_maps.add()
            item.map_id = t_data["map_id"]
            item.name = t_data["name"]
            item.export = True
            item.export_suffix = first_suffix
            item.color_space = t_data["color_space"]
            item.is_normal_map = t_data["is_normal_map"]
            item.normal_format = t_data["normal_format"]
            item.is_packed = t_data["is_packed"]

            if not item.is_packed:
                item.target_rgb = t_data.get("target_rgb", "Base Color")
                item.invert_rgb = t_data.get("invert_rgb", False)
                item.target_a = t_data.get("target_a", "NONE")
                item.invert_a = t_data.get("invert_a", False)
            else:
                for ch in ("r", "g", "b", "a"):
                    setattr(item, f"target_{ch}", t_data.get(f"target_{ch}", "NONE"))
                    setattr(item, f"invert_{ch}", t_data.get(f"invert_{ch}", False))

            props.pbr_export_active_map_index = len(props.pbr_export_active_maps) - 1

        if sync_export_maps_to_preset:
            sync_export_maps_to_preset(props)

        safe_report(self, {"INFO"}, f"Added export map rule '{item.name}'.")
        return {"FINISHED"}


class LOD_OT_delete_export_preset_map(Operator):
    """Delete the selected texture map rule from the active export preset."""

    bl_idname = "lod_tool.delete_export_preset_map"
    bl_label = "Delete Export Map Definition"
    bl_description = "Removes the selected texture map rule from the active export preset"
    bl_options = {"REGISTER"}

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_export_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
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


class LOD_OT_move_export_preset_map(Operator):
    """Move export texture map rule up or down in the export list."""

    bl_idname = "lod_tool.move_export_preset_map"
    bl_label = "Move Export Map Rule"
    bl_description = "Moves selected export map rule up or down"
    bl_options = {"REGISTER"}

    direction: EnumProperty(
        name="Direction",
        items=[("UP", "Up", "Move rule earlier"), ("DOWN", "Down", "Move rule later")],
        default="UP",
    )

    def execute(self, context: Any) -> set[Any]:
        props = getattr(context.scene, "lod_tool", None) if context and hasattr(context, "scene") else None
        if not props:
            props, _, _ = resolve_lod_context(context)
        if not props or not hasattr(props, "pbr_export_active_maps"):
            return {"CANCELLED"}

        preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", DEFAULT_PRESET_ID)
        if PBRExportPresetManager.is_builtin(preset_id):
            safe_report(self, {"WARNING"}, "Built-in presets are read-only. Duplicate to edit.")
            return {"CANCELLED"}

        count = len(props.pbr_export_active_maps)
        idx = props.pbr_export_active_map_index
        if idx < 0 or idx >= count:
            return {"CANCELLED"}

        target_idx = idx - 1 if self.direction == "UP" else idx + 1
        if 0 <= target_idx < count:
            with ExportMapSyncGuard() if ExportMapSyncGuard else nullcontext():
                props.pbr_export_active_maps.move(idx, target_idx)
                props.pbr_export_active_map_index = target_idx

            if sync_export_maps_to_preset:
                sync_export_maps_to_preset(props)
            return {"FINISHED"}

        return {"CANCELLED"}


PBR_MAP_OPERATOR_CLASSES = (
    LOD_OT_init_preset_maps,
    LOD_OT_add_preset_map,
    LOD_OT_add_map_template,
    LOD_OT_delete_preset_map,
    LOD_OT_move_preset_map,
    LOD_OT_add_export_preset_map,
    LOD_OT_add_export_map_template,
    LOD_OT_delete_export_preset_map,
    LOD_OT_move_export_preset_map,
)

__all__ = [
    "PBR_MAP_OPERATOR_CLASSES",
    "LOD_OT_init_preset_maps",
    "LOD_OT_add_preset_map",
    "LOD_OT_add_map_template",
    "LOD_OT_delete_preset_map",
    "LOD_OT_move_preset_map",
    "LOD_OT_add_export_preset_map",
    "LOD_OT_add_export_map_template",
    "LOD_OT_delete_export_preset_map",
    "LOD_OT_move_export_preset_map",
    "MAP_TEMPLATE_DEFINITIONS",
    "TEMPLATE_ITEMS",
]
