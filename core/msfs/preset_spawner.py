"""
OmniMesh MSFS Config Preset Spawning Subsystem.
Instantiates MSFS spatial markers, lights, cameras, exits, and engines from preset definitions
into the active asset collection hierarchy ({AssetName}_Config -> _Spatial, _Lights, _Cameras).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)

try:
    import bpy
    from mathutils import Euler, Vector
except ImportError:
    bpy = None
    Euler = None
    Vector = None

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


def compute_preset_anchor_position(
    anchor_name: str,
    offset_norm: list[float],
    extrema: dict[str, tuple[float, float, float]],
    bbox_min: Vector,
    bbox_max: Vector,
) -> Vector:
    """Computes world-space coordinate for a given named anchor and normalized offset."""
    half_span = max(0.1, (bbox_max.x - bbox_min.x) * 0.5)
    length = max(0.1, bbox_max.y - bbox_min.y)
    height = max(0.1, bbox_max.z - bbox_min.z)
    bbox_center = (bbox_min + bbox_max) * 0.5

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

    return Vector((base.x + ox * half_span, base.y + oy * length, base.z + oz * height))


class ConfigPresetSpawner:
    """Instantiates preset configuration objects into standardized collections."""

    @classmethod
    def _parent_to_datum(cls, obj: Any, datum_obj: Any) -> None:
        """Safely parents obj to datum_obj preserving world transform."""
        if not datum_obj or obj == datum_obj:
            return
        obj.parent = datum_obj
        if hasattr(datum_obj, "matrix_world") and hasattr(obj, "matrix_parent_inverse"):
            try:
                obj.matrix_parent_inverse = datum_obj.matrix_world.inverted()
            except Exception as exc:
                logger.debug("Could not invert parent matrix: %s", exc)

    @classmethod
    def _spawn_datum_if_missing(
        cls,
        _bpy: Any,
        asset_name: str,
        spatial_col: Any,
        existing_ids: set[str],
        anchor_fn: Callable[[str, list[float]], Vector],
    ) -> tuple[Any, int]:
        """Ensures the datum reference empty exists in spatial_col."""
        datum_id = "WEIGHT_AND_BALANCE:reference_datum_position"
        for o in getattr(spatial_col, "objects", []):
            if o.get("msfs_id") == datum_id:
                return o, 0

        datum_pos = anchor_fn("AABB_ORIGIN", [0.0, 0.0, 0.0])
        datum_obj = _bpy.data.objects.new(f"{asset_name}_Datum", None)
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
        return datum_obj, 1

    @classmethod
    def _spawn_spatial_points(
        cls,
        _bpy: Any,
        asset_name: str,
        items: list[dict[str, Any]],
        spatial_col: Any,
        datum_obj: Any,
        existing_ids: set[str],
        anchor_fn: Callable[[str, list[float]], Vector],
    ) -> int:
        """Spawns spatial contact points and markers."""
        count = 0
        datum_id = "WEIGHT_AND_BALANCE:reference_datum_position"
        for item in items:
            item_id = item.get("id", "")
            if not item_id or item_id in existing_ids or item_id == datum_id:
                continue

            pos = anchor_fn(item.get("anchor", "AABB_CENTER"), item.get("offset_normalized", [0.0, 0.0, 0.0]))
            p_name = f"{asset_name}_{item.get('name', 'Point')}"
            obj = _bpy.data.objects.new(p_name, None)
            is_class1 = item.get("point_class") == 1
            obj.empty_display_type = "CIRCLE" if is_class1 else "PLAIN_AXES"
            obj.empty_display_size = 0.3 if is_class1 else 0.2
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
            cls._parent_to_datum(obj, datum_obj)
            existing_ids.add(item_id)
            count += 1
        return count

    @classmethod
    def _spawn_exits(
        cls,
        _bpy: Any,
        asset_name: str,
        items: list[dict[str, Any]],
        spatial_col: Any,
        datum_obj: Any,
        existing_ids: set[str],
        anchor_fn: Callable[[str, list[float]], Vector],
    ) -> int:
        """Spawns aircraft exits from preset."""
        count = 0
        for item in items:
            item_id = item.get("id", "")
            if not item_id or item_id in existing_ids:
                continue

            pos = anchor_fn(item.get("anchor", "AABB_CENTER"), item.get("offset_normalized", [0.0, 0.0, 0.0]))
            p_name = f"{asset_name}_{item.get('name', 'Exit')}"
            obj = _bpy.data.objects.new(p_name, None)
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
            cls._parent_to_datum(obj, datum_obj)
            existing_ids.add(item_id)
            count += 1
        return count

    @classmethod
    def _spawn_engines(
        cls,
        _bpy: Any,
        asset_name: str,
        items: list[dict[str, Any]],
        spatial_col: Any,
        datum_obj: Any,
        existing_ids: set[str],
        anchor_fn: Callable[[str, list[float]], Vector],
    ) -> int:
        """Spawns engine markers from preset."""
        count = 0
        for item in items:
            item_id = item.get("id", "")
            if not item_id or item_id in existing_ids:
                continue

            pos = anchor_fn(item.get("anchor", "EXTREMA_NOSE"), item.get("offset_normalized", [0.0, 0.0, 0.0]))
            p_name = f"{asset_name}_{item.get('name', 'Engine')}"
            obj = _bpy.data.objects.new(p_name, None)
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
            cls._parent_to_datum(obj, datum_obj)
            existing_ids.add(item_id)
            count += 1
        return count

    @classmethod
    def _spawn_station_loads(
        cls,
        _bpy: Any,
        asset_name: str,
        items: list[dict[str, Any]],
        spatial_col: Any,
        datum_obj: Any,
        existing_ids: set[str],
        anchor_fn: Callable[[str, list[float]], Vector],
    ) -> int:
        """Spawns payload station loads from preset."""
        count = 0
        for item in items:
            item_id = item.get("id", "")
            if not item_id or item_id in existing_ids:
                continue

            pos = anchor_fn(item.get("anchor", "EXTREMA_COCKPIT"), item.get("offset_normalized", [0.0, 0.0, 0.0]))
            p_name = f"{asset_name}_{item.get('name', 'Station')}"
            obj = _bpy.data.objects.new(p_name, None)
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
            cls._parent_to_datum(obj, datum_obj)
            existing_ids.add(item_id)
            count += 1
        return count

    @classmethod
    def _spawn_interactions(
        cls,
        context: Any,
        asset_name: str,
        items: list[dict[str, Any]],
    ) -> int:
        """Spawns interaction volumes from preset if defined."""
        count = 0
        for item in items:
            i_name = item.get("name", "Interaction")
            try:
                from ..interaction_volumes import create_interaction_volume

                create_interaction_volume(
                    context=context,
                    asset_name=asset_name,
                    name=i_name,
                    shape=item.get("shape", "BOX"),
                    role=item.get("role", "BUTTON"),
                    size=item.get("size", (0.08, 0.08, 0.08)),
                )
                count += 1
            except Exception as exc:
                logger.debug("Failed spawning interaction from preset: %s", exc)
        return count

    @classmethod
    def _spawn_lights(
        cls,
        _bpy: Any,
        asset_name: str,
        items: list[dict[str, Any]],
        lights_col: Any,
        existing_ids: set[str],
        anchor_fn: Callable[[str, list[float]], Vector],
    ) -> int:
        """Spawns lighting objects from preset."""
        count = 0
        for item in items:
            item_id = item.get("id", "")
            if not item_id or item_id in existing_ids:
                continue

            pos = anchor_fn(item.get("anchor", "AABB_CENTER"), item.get("offset_normalized", [0.0, 0.0, 0.0]))
            p_name = f"{asset_name}_{item.get('name', 'Light')}"
            l_type = int(item.get("type", 1))

            is_spot = l_type in (5, 6)
            light_data = _bpy.data.lights.new(name=p_name, type="SPOT" if is_spot else "POINT")
            col_rgb = item.get("color", [1.0, 1.0, 1.0, 1.0])
            light_data.color = (float(col_rgb[0]), float(col_rgb[1]), float(col_rgb[2]))
            light_data.energy = 250.0 if is_spot else 15.0

            light_obj = _bpy.data.objects.new(p_name, light_data)
            light_obj.location = pos
            if is_spot:
                rot = (1.57079, 0.0, 0.0)
                light_obj.rotation_euler = Euler(rot, "XYZ") if Euler else rot

            light_obj["_omnimesh_role"] = "CONFIG_MARKER"
            light_obj["msfs_id"] = item_id
            light_obj["msfs_section"] = "LIGHTS"
            light_obj["msfs_key"] = item.get("key", "")
            light_obj["msfs_type"] = "LIGHT"
            light_obj["msfs_light_type"] = l_type

            if lights_col:
                lights_col.objects.link(light_obj)
            existing_ids.add(item_id)
            count += 1
        return count

    @classmethod
    def _spawn_cameras(
        cls,
        _bpy: Any,
        asset_name: str,
        items: list[dict[str, Any]],
        cameras_col: Any,
        existing_ids: set[str],
        anchor_fn: Callable[[str, list[float]], Vector],
    ) -> int:
        """Spawns cameras and ensures eyepoint marker exists."""
        count = 0
        eyepoint_id = "CAMERAS:eyepoint"
        eyepoint_obj = None
        for o in getattr(cameras_col, "objects", []):
            if o.get("msfs_id") == eyepoint_id:
                eyepoint_obj = o
                break

        if not eyepoint_obj:
            eye_pos = anchor_fn("COCKPIT_ESTIMATE", [0.0, 0.0, 0.0])
            eyepoint_obj = _bpy.data.objects.new(f"{asset_name}_Eyepoint", None)
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
            count += 1

        for item in items:
            item_id = item.get("id", "")
            if not item_id or item_id in existing_ids or item_id == eyepoint_id:
                continue

            cam_name = f"{asset_name}_{item.get('name', 'Camera')}"
            cam_data = _bpy.data.cameras.new(cam_name)
            cam_data.lens = 28.0
            cam_obj = _bpy.data.objects.new(cam_name, cam_data)

            if item.get("parent_to_eyepoint", False) and eyepoint_obj:
                cam_obj.location = eyepoint_obj.location
            else:
                cam_obj.location = anchor_fn(item.get("anchor", "COCKPIT_ESTIMATE"), [0.0, 0.0, 0.0])

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
            count += 1
        return count

    @classmethod
    def spawn_preset_objects(
        cls,
        context: Any,
        asset_name: str,
        preset_data: dict[str, Any],
        cfg_props: Any = None,
        *,
        bpy_module: Any = None,
        get_base_meshes_fn: Callable[[Any, str], list[Any]] | None = None,
        get_import_collection_fn: Callable[[Any, str, str], Any] | None = None,
    ) -> int:
        """
        Coordinates full instantiation of all missing config markers from preset.
        Returns total count of newly created objects.
        """
        _bpy = bpy_module or bpy
        if not _bpy or not context:
            return 0

        mesh_fn = get_base_meshes_fn
        if not mesh_fn:
            try:
                from ui.utils import get_asset_base_meshes as mesh_fn
            except (ImportError, ValueError):

                def _empty_mesh_fn(_c: Any, _a: Any) -> list[Any]:
                    return []

                mesh_fn = _empty_mesh_fn

        col_fn = get_import_collection_fn
        if not col_fn:
            try:
                from ..hierarchy import get_or_create_engine_import_collection as col_fn
            except (ImportError, ValueError):
                from core.hierarchy import get_or_create_engine_import_collection as col_fn

        from .geometry import detect_airframe_extrema, extract_world_vertices_numpy

        # 1. Inspect geometry extrema
        base_meshes = mesh_fn(context, asset_name)
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

        def anchor_fn(anchor_name: str, offset_norm: list[float]) -> Vector:
            return compute_preset_anchor_position(anchor_name, offset_norm, extrema, bbox_min, bbox_max)

        # 2. Ensure target collections
        spatial_col = col_fn(context, asset_name, "SPATIAL")
        lights_col = col_fn(context, asset_name, "LIGHTS")
        cameras_col = col_fn(context, asset_name, "CAMERAS")

        # Map existing IDs
        existing_ids: set[str] = set()
        for col in (spatial_col, lights_col, cameras_col):
            if col and hasattr(col, "objects"):
                for o in col.objects:
                    mid = o.get("msfs_id") if hasattr(o, "get") else None
                    if mid:
                        existing_ids.add(mid)

        if hasattr(_bpy, "data") and hasattr(_bpy.data, "objects"):
            try:
                for o in _bpy.data.objects:
                    mid = o.get("msfs_id") if hasattr(o, "get") else None
                    if mid:
                        existing_ids.add(mid)
            except TypeError:
                pass

        total_added = 0

        # 3. Datum
        datum_obj, datum_added = cls._spawn_datum_if_missing(_bpy, asset_name, spatial_col, existing_ids, anchor_fn)
        total_added += datum_added

        # 4. Spatial points
        inc_spatial = getattr(cfg_props, "include_spatial", True) if cfg_props else True
        if inc_spatial:
            total_added += cls._spawn_spatial_points(
                _bpy, asset_name, preset_data.get("spatial", []), spatial_col, datum_obj, existing_ids, anchor_fn
            )
            total_added += cls._spawn_station_loads(
                _bpy, asset_name, preset_data.get("station_loads", []), spatial_col, datum_obj, existing_ids, anchor_fn
            )

        # 5. Exits
        inc_exits = getattr(cfg_props, "include_exits", True) if cfg_props else True
        if inc_exits:
            total_added += cls._spawn_exits(
                _bpy, asset_name, preset_data.get("exits", []), spatial_col, datum_obj, existing_ids, anchor_fn
            )

        # 6. Engines
        inc_engines = getattr(cfg_props, "include_engines", True) if cfg_props else True
        if inc_engines:
            total_added += cls._spawn_engines(
                _bpy, asset_name, preset_data.get("engines", []), spatial_col, datum_obj, existing_ids, anchor_fn
            )

        # 7. Interactions
        total_added += cls._spawn_interactions(context, asset_name, preset_data.get("interactions", []))

        # 8. Lights
        inc_lights = getattr(cfg_props, "include_lights", True) if cfg_props else True
        if inc_lights:
            total_added += cls._spawn_lights(
                _bpy, asset_name, preset_data.get("lights", []), lights_col, existing_ids, anchor_fn
            )

        # 9. Cameras
        inc_cams = getattr(cfg_props, "include_cameras", True) if cfg_props else True
        if inc_cams:
            total_added += cls._spawn_cameras(
                _bpy, asset_name, preset_data.get("cameras", []), cameras_col, existing_ids, anchor_fn
            )

        return total_added
