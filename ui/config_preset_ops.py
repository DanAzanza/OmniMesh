"""
OmniMesh Config Preset Spawning Operators.
Instantiates MSFS spatial markers, lights, cameras, exits, and engines from preset definitions
into the active asset collection hierarchy ({AssetName}_Config -> _Spatial, _Lights, _Cameras).
"""

from __future__ import annotations

import logging
import uuid
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
    from ..core.config_presets import ConfigPresetManager, DEFAULT_CONFIG_PRESET_ID
    from ..core.hierarchy import get_or_create_engine_import_collection
    from ..core.msfs.geometry import detect_airframe_extrema, extract_world_vertices_numpy
    from .utils import (
        get_asset_base_meshes,
        resolve_effective_asset_name,
        safe_report,
    )
except (ImportError, ValueError):
    from core.config_presets import ConfigPresetManager, DEFAULT_CONFIG_PRESET_ID
    from core.hierarchy import get_or_create_engine_import_collection
    from core.msfs.geometry import detect_airframe_extrema, extract_world_vertices_numpy
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

        # 1. Inspect active asset meshes to extract geometry anchors
        base_meshes = get_asset_base_meshes(context, asset_name)
        extrema: dict[str, tuple[float, float, float]] = {}
        bbox_min = Vector((-5.0, -5.0, -1.0))
        bbox_max = Vector((5.0, 5.0, 3.0))

        if base_meshes:
            try:
                coords = extract_world_vertices_numpy(base_meshes)
                if coords.shape[0] >= 4:
                    extrema = detect_airframe_extrema(coords)
                    bbox_min = Vector((float(coords[:, 0].min()), float(coords[:, 1].min()), float(coords[:, 2].min())))
                    bbox_max = Vector((float(coords[:, 0].max()), float(coords[:, 1].max()), float(coords[:, 2].max())))
            except Exception as exc:
                logger.debug("Could not compute geometry extrema: %s", exc)

        half_span = max(0.1, (bbox_max.x - bbox_min.x) * 0.5)
        length = max(0.1, bbox_max.y - bbox_min.y)
        height = max(0.1, bbox_max.z - bbox_min.z)
        bbox_center = (bbox_min + bbox_max) * 0.5

        def resolve_anchor_pos(anchor_name: str, offset_norm: list[float]) -> Vector:
            ox = float(offset_norm[0]) if len(offset_norm) > 0 else 0.0
            oy = float(offset_norm[1]) if len(offset_norm) > 1 else 0.0
            oz = float(offset_norm[2]) if len(offset_norm) > 2 else 0.0

            if anchor_name == "EXTREMA_NOSE" and "Scrape_Nose" in extrema:
                base = Vector(extrema["Scrape_Nose"])
            elif anchor_name == "EXTREMA_TAIL" and "Scrape_Tail" in extrema:
                base = Vector(extrema["Scrape_Tail"])
            elif anchor_name == "EXTREMA_WING_L" and "Scrape_Wing_L" in extrema:
                base = Vector(extrema["Scrape_Wing_L"])
            elif anchor_name == "EXTREMA_WING_R" and "Scrape_Wing_R" in extrema:
                base = Vector(extrema["Scrape_Wing_R"])
            elif anchor_name == "EXTREMA_FIN" and "Scrape_Fin" in extrema:
                base = Vector(extrema["Scrape_Fin"])
            elif anchor_name in ("COCKPIT_ESTIMATE", "EXTREMA_COCKPIT"):
                base = Vector((bbox_center.x, bbox_center.y + 0.2 * length, bbox_center.z + 0.15 * height))
            elif anchor_name in ("AABB_MIN_Z", "EXTREMA_BELLY"):
                base = Vector((bbox_center.x, bbox_center.y, bbox_min.z))
            elif anchor_name == "ROTOR_HUB_MAIN":
                base = Vector((bbox_center.x, bbox_center.y, bbox_max.z))
            elif anchor_name == "ROTOR_HUB_TAIL":
                base = Vector((bbox_center.x, bbox_min.y, bbox_center.z + 0.2 * height))
            elif anchor_name == "FLOAT_LEFT_KEEL":
                base = Vector((bbox_center.x + 0.25 * half_span, bbox_center.y, bbox_min.z))
            elif anchor_name == "FLOAT_RIGHT_KEEL":
                base = Vector((bbox_center.x - 0.25 * half_span, bbox_center.y, bbox_min.z))
            elif anchor_name == "TOW_HOOK":
                base = Vector((bbox_center.x, bbox_max.y, bbox_min.z + 0.1 * height))
            elif anchor_name == "AABB_ORIGIN":
                base = Vector((0.0, 0.0, 0.0))
            elif anchor_name == "AABB_CENTER":
                base = bbox_center
            else:
                base = bbox_center

            # Add scaled normalized offset
            return Vector((base.x + ox * half_span, base.y + oy * length, base.z + oz * height))

        # 2. Ensure Collections Exist (Variante A)
        spatial_col = get_or_create_engine_import_collection(context, asset_name, "SPATIAL")
        lights_col = get_or_create_engine_import_collection(context, asset_name, "LIGHTS")
        cameras_col = get_or_create_engine_import_collection(context, asset_name, "CAMERAS")

        # Map existing objects by msfs_id to guarantee NEVER overwriting existing objects
        existing_ids = set()
        for col in (spatial_col, lights_col, cameras_col):
            if col and hasattr(col, "objects"):
                for o in col.objects:
                    mid = o.get("msfs_id") if hasattr(o, "get") else None
                    if mid:
                        existing_ids.add(mid)

        if bpy and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
            try:
                for o in bpy.data.objects:
                    mid = o.get("msfs_id") if hasattr(o, "get") else None
                    if mid:
                        existing_ids.add(mid)
            except TypeError:
                pass

        added_count = 0
        datum_obj = None

        # 3. Always Ensure Datum Reference Exists
        datum_id = "WEIGHT_AND_BALANCE:reference_datum_position"
        for o in getattr(spatial_col, "objects", []):
            if o.get("msfs_id") == datum_id:
                datum_obj = o
                break

        if not datum_obj:
            datum_pos = resolve_anchor_pos("AABB_ORIGIN", [0.0, 0.0, 0.0])
            datum_obj = bpy.data.objects.new(f"{asset_name}_Datum", None)
            datum_obj.empty_display_type = "PLAIN_AXES"
            datum_obj.empty_display_size = 1.0
            datum_obj.location = datum_pos
            datum_obj["_omnimesh_role"] = "CONFIG_MARKER"
            datum_obj["msfs_id"] = datum_id
            datum_obj["msfs_type"] = "DATUM"
            datum_obj["msfs_section"] = "WEIGHT_AND_BALANCE"
            datum_obj["msfs_key"] = "reference_datum_position"
            if spatial_col:
                spatial_col.objects.link(datum_obj)
            existing_ids.add(datum_id)
            added_count += 1

        # 4. Spawn Spatial Points if enabled
        inc_spatial = getattr(cfg_props, "include_spatial", True) if cfg_props else True
        if inc_spatial:
            for item in preset_data.get("spatial", []):
                item_id = item.get("id", "")
                if not item_id or item_id in existing_ids or item_id == datum_id:
                    continue

                pos = resolve_anchor_pos(
                    item.get("anchor", "AABB_CENTER"), item.get("offset_normalized", [0.0, 0.0, 0.0])
                )
                p_name = f"{asset_name}_{item.get('name', 'Point')}"
                obj = bpy.data.objects.new(p_name, None)
                obj.empty_display_type = "CIRCLE" if item.get("point_class") == 1 else "PLAIN_AXES"
                obj.empty_display_size = 0.3 if item.get("point_class") == 1 else 0.2
                obj.location = pos
                obj["_omnimesh_role"] = "CONFIG_MARKER"
                obj["msfs_id"] = item_id
                obj["msfs_section"] = item.get("section", "CONTACT_POINTS")
                obj["msfs_key"] = item.get("key", "")
                obj["msfs_type"] = item.get("point_type", "CONTACT_POINT")
                if "point_class" in item:
                    obj["msfs_point_class"] = int(item["point_class"])
                if "default_properties" in item:
                    obj["msfs_raw_properties"] = list(item["default_properties"])

                if spatial_col:
                    spatial_col.objects.link(obj)
                if datum_obj and obj != datum_obj:
                    obj.parent = datum_obj
                    if hasattr(datum_obj, "matrix_world") and hasattr(obj, "matrix_parent_inverse"):
                        try:
                            obj.matrix_parent_inverse = datum_obj.matrix_world.inverted()
                        except Exception as exc:
                            logger.debug("Could not invert parent matrix: %s", exc)
                existing_ids.add(item_id)
                added_count += 1

        # 5. Spawn Exits if enabled
        inc_exits = getattr(cfg_props, "include_exits", True) if cfg_props else True
        if inc_exits:
            for item in preset_data.get("exits", []):
                item_id = item.get("id", "")
                if not item_id or item_id in existing_ids:
                    continue

                pos = resolve_anchor_pos(
                    item.get("anchor", "AABB_CENTER"), item.get("offset_normalized", [0.0, 0.0, 0.0])
                )
                p_name = f"{asset_name}_{item.get('name', 'Exit')}"
                obj = bpy.data.objects.new(p_name, None)
                obj.empty_display_type = "CUBE"
                obj.empty_display_size = 0.4
                obj.location = pos
                obj["_omnimesh_role"] = "CONFIG_MARKER"
                obj["msfs_id"] = item_id
                obj["msfs_section"] = "EXITS"
                obj["msfs_key"] = item.get("key", "")
                obj["msfs_type"] = "EXIT"
                obj["msfs_exit_type"] = int(item.get("exit_type", 0))
                obj["msfs_open_rate"] = float(item.get("open_rate", 0.5))

                if spatial_col:
                    spatial_col.objects.link(obj)
                if datum_obj and obj != datum_obj:
                    obj.parent = datum_obj
                    if hasattr(datum_obj, "matrix_world") and hasattr(obj, "matrix_parent_inverse"):
                        try:
                            obj.matrix_parent_inverse = datum_obj.matrix_world.inverted()
                        except Exception as exc:
                            logger.debug("Could not invert parent matrix: %s", exc)
                existing_ids.add(item_id)
                added_count += 1

        # 6. Spawn Engines if enabled
        inc_engines = getattr(cfg_props, "include_engines", True) if cfg_props else True
        if inc_engines:
            for item in preset_data.get("engines", []):
                item_id = item.get("id", "")
                if not item_id or item_id in existing_ids:
                    continue

                pos = resolve_anchor_pos(
                    item.get("anchor", "EXTREMA_NOSE"), item.get("offset_normalized", [0.0, 0.0, 0.0])
                )
                p_name = f"{asset_name}_{item.get('name', 'Engine')}"
                obj = bpy.data.objects.new(p_name, None)
                obj.empty_display_type = "SINGLE_ARROW"
                obj.empty_display_size = 0.6
                obj.location = pos
                obj["_omnimesh_role"] = "CONFIG_MARKER"
                obj["msfs_id"] = item_id
                obj["msfs_section"] = "GENERALENGINEDATA"
                obj["msfs_key"] = item.get("key", "")
                obj["msfs_type"] = "ENGINE"
                obj["msfs_engine_index"] = int(item.get("engine_index", 1))
                obj["msfs_engine_type"] = int(item.get("engine_type", 0))

                if spatial_col:
                    spatial_col.objects.link(obj)
                if datum_obj and obj != datum_obj:
                    obj.parent = datum_obj
                    if hasattr(datum_obj, "matrix_world") and hasattr(obj, "matrix_parent_inverse"):
                        try:
                            obj.matrix_parent_inverse = datum_obj.matrix_world.inverted()
                        except Exception as exc:
                            logger.debug("Could not invert parent matrix: %s", exc)
                existing_ids.add(item_id)
                added_count += 1

        # 6.5 Spawn Station Loads if enabled
        if inc_spatial:
            for item in preset_data.get("station_loads", []):
                item_id = item.get("id", "")
                if not item_id or item_id in existing_ids:
                    continue

                pos = resolve_anchor_pos(
                    item.get("anchor", "EXTREMA_COCKPIT"), item.get("offset_normalized", [0.0, 0.0, 0.0])
                )
                p_name = f"{asset_name}_{item.get('name', 'Station')}"
                obj = bpy.data.objects.new(p_name, None)
                obj.empty_display_type = "SPHERE"
                obj.empty_display_size = 0.25
                obj.location = pos
                obj["_omnimesh_role"] = "CONFIG_MARKER"
                obj["msfs_id"] = item_id
                obj["msfs_section"] = "WEIGHT_AND_BALANCE"
                obj["msfs_key"] = item.get("key", "")
                obj["msfs_type"] = "PAYLOAD_STATION"
                obj["msfs_station_name"] = str(item.get("station_name", ""))
                obj["msfs_station_type"] = int(item.get("station_type", 0))
                obj["msfs_weight_lbs"] = float(item.get("weight_lbs", 170.0))

                if spatial_col:
                    spatial_col.objects.link(obj)
                if datum_obj and obj != datum_obj:
                    obj.parent = datum_obj
                    if hasattr(datum_obj, "matrix_world") and hasattr(obj, "matrix_parent_inverse"):
                        try:
                            obj.matrix_parent_inverse = datum_obj.matrix_world.inverted()
                        except Exception as exc:
                            logger.debug("Could not invert parent matrix: %s", exc)
                existing_ids.add(item_id)
                added_count += 1

        # 6.6 Spawn Interaction Volumes from preset if present
        for item in preset_data.get("interactions", []):
            i_name = item.get("name", "Interaction")
            try:
                from ..core.interaction_volumes import create_interaction_volume

                create_interaction_volume(
                    context=context,
                    asset_name=asset_name,
                    name=i_name,
                    shape=item.get("shape", "BOX"),
                    role=item.get("role", "BUTTON"),
                    size=item.get("size", (0.08, 0.08, 0.08)),
                )
                added_count += 1
            except Exception as exc:
                logger.debug("Failed spawning interaction from preset: %s", exc)

        # 7. Spawn Lights if enabled
        inc_lights = getattr(cfg_props, "include_lights", True) if cfg_props else True
        if inc_lights:
            for item in preset_data.get("lights", []):
                item_id = item.get("id", "")
                if not item_id or item_id in existing_ids:
                    continue

                pos = resolve_anchor_pos(
                    item.get("anchor", "AABB_CENTER"), item.get("offset_normalized", [0.0, 0.0, 0.0])
                )
                p_name = f"{asset_name}_{item.get('name', 'Light')}"
                l_type = int(item.get("type", 1))

                is_spot = l_type in (5, 6)  # Landing or Taxi
                light_data = bpy.data.lights.new(name=p_name, type="SPOT" if is_spot else "POINT")
                col_rgb = item.get("color", [1.0, 1.0, 1.0, 1.0])
                light_data.color = (float(col_rgb[0]), float(col_rgb[1]), float(col_rgb[2]))
                light_data.energy = 250.0 if is_spot else 15.0

                light_obj = bpy.data.objects.new(p_name, light_data)
                light_obj.location = pos
                if is_spot:
                    rot = (1.57079, 0.0, 0.0)
                    light_obj.rotation_euler = Euler(rot, "XYZ") if Euler else rot  # Point forward

                light_obj["_omnimesh_role"] = "CONFIG_MARKER"
                light_obj["msfs_id"] = item_id
                light_obj["msfs_section"] = "LIGHTS"
                light_obj["msfs_key"] = item.get("key", "")
                light_obj["msfs_type"] = "LIGHT"
                light_obj["msfs_light_type"] = l_type

                if lights_col:
                    lights_col.objects.link(light_obj)
                existing_ids.add(item_id)
                added_count += 1

        # 8. Spawn Cameras if enabled (ensuring Eyepoint exists)
        inc_cams = getattr(cfg_props, "include_cameras", True) if cfg_props else True
        if inc_cams:
            eyepoint_id = "CAMERAS:eyepoint"
            eyepoint_obj = None
            for o in getattr(cameras_col, "objects", []):
                if o.get("msfs_id") == eyepoint_id:
                    eyepoint_obj = o
                    break

            if not eyepoint_obj:
                eye_pos = resolve_anchor_pos("COCKPIT_ESTIMATE", [0.0, 0.0, 0.0])
                eyepoint_obj = bpy.data.objects.new(f"{asset_name}_Eyepoint", None)
                eyepoint_obj.empty_display_type = "PLAIN_AXES"
                eyepoint_obj.empty_display_size = 0.3
                eyepoint_obj.location = eye_pos
                eyepoint_obj["_omnimesh_role"] = "CONFIG_MARKER"
                eyepoint_obj["msfs_id"] = eyepoint_id
                eyepoint_obj["msfs_section"] = "VIEWS"
                eyepoint_obj["msfs_key"] = "eyepoint"
                eyepoint_obj["msfs_type"] = "EYEPOINT"
                if cameras_col:
                    cameras_col.objects.link(eyepoint_obj)
                existing_ids.add(eyepoint_id)
                added_count += 1

            for item in preset_data.get("cameras", []):
                item_id = item.get("id", "")
                if not item_id or item_id in existing_ids or item_id == eyepoint_id:
                    continue

                cam_name = f"{asset_name}_{item.get('name', 'Camera')}"
                cam_data = bpy.data.cameras.new(cam_name)
                cam_data.lens = 28.0
                cam_obj = bpy.data.objects.new(cam_name, cam_data)

                if item.get("parent_to_eyepoint", False) and eyepoint_obj:
                    cam_obj.location = eyepoint_obj.location
                else:
                    cam_obj.location = resolve_anchor_pos(item.get("anchor", "COCKPIT_ESTIMATE"), [0.0, 0.0, 0.0])

                cam_rot = (1.57079, 0.0, 0.0)
                cam_obj.rotation_euler = Euler(cam_rot, "XYZ") if Euler else cam_rot
                cam_obj["_omnimesh_role"] = "CONFIG_MARKER"
                cam_obj["msfs_id"] = item_id
                cam_obj["msfs_section"] = "CAMERAS"
                cam_obj["msfs_title"] = item.get("title", "Camera")
                cam_obj["msfs_guid"] = f"{{{uuid.uuid4()}}}"
                cam_obj["msfs_origin"] = item.get("origin", "Virtual Cockpit")
                cam_obj["msfs_category"] = item.get("category", "Cockpit")
                cam_obj["msfs_subcategory"] = item.get("subcategory", "Pilot")

                if cameras_col:
                    cameras_col.objects.link(cam_obj)
                existing_ids.add(item_id)
                added_count += 1

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
