"""
OmniMesh Engine Project Import Helpers.
Encapsulates sub-parsers for MSFS 2024 spatial markers, aviation lighting, cockpit cameras, and attached objects.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

try:
    import bpy
except ImportError:
    bpy = None

try:
    from ..core.msfs.cst_parser import MSFSCSTParser
    from ..core.msfs.transforms import (
        FEET_TO_METERS,
        msfs_pbh_to_blender_rotation,
        msfs_zoom_to_blender_focal_length,
    )
    from .utils import get_or_create_engine_import_collection
except (ImportError, ValueError):
    from core.msfs.cst_parser import MSFSCSTParser
    from core.msfs.transforms import (
        FEET_TO_METERS,
        msfs_pbh_to_blender_rotation,
        msfs_zoom_to_blender_focal_length,
    )
    from ui.utils import get_or_create_engine_import_collection

logger = logging.getLogger(__name__)


def import_spatial_points(
    context: Any,
    manifest: Any,
    asset_name: str,
    props: Any,
) -> tuple[int, Optional[Any]]:
    """Parses flight_model.cfg and creates datum and spatial locator empties."""
    spatial_count = 0
    datum_empty: Optional[Any] = None
    if not manifest.flight_model_cfg_path or not os.path.isfile(manifest.flight_model_cfg_path):
        return 0, None

    spatial_col = get_or_create_engine_import_collection(context, asset_name, "SPATIAL")
    if not spatial_col:
        return 0, None

    try:
        cfg = MSFSCSTParser.parse_file(manifest.flight_model_cfg_path)
        datum_coords = cfg.points[0].coords_blender_m if cfg.points else (0.0, 0.0, 0.0)

        # Datum Empty (scoped strictly to spatial_col)
        datum_empty = next(
            (o for o in spatial_col.objects if o.get("msfs_id") == "WEIGHT_AND_BALANCE:reference_datum_position"),
            None,
        )
        if not datum_empty:
            d_name = "Datum" if "Datum" not in bpy.data.objects else f"{asset_name}_Datum"
            datum_empty = bpy.data.objects.new(d_name, None)
            spatial_col.objects.link(datum_empty)

        datum_empty.location = datum_coords
        datum_empty.empty_display_type = "PLAIN_AXES"
        datum_empty.empty_display_size = 0.5
        datum_empty["msfs_id"] = "WEIGHT_AND_BALANCE:reference_datum_position"
        context.view_layer.update()

        # Relative points
        for point in cfg.points:
            if point.point_type == "DATUM":
                continue

            display_type = "PLAIN_AXES"
            display_size = 0.25
            if point.point_type == "CONTACT_POINT":
                if point.point_class == 1:
                    display_type = "CIRCLE"
                    display_size = 0.35
                    clean_tag = point.name_tag or "Wheel"
                    empty_name = f"Point_{point.key.split('.')[-1]}_{clean_tag}"
                elif point.point_class == 2:
                    display_type = "PLAIN_AXES"
                    display_size = 0.2
                    empty_name = f"Scrape_{point.name_tag or point.key.split('.')[-1]}"
                elif point.point_class == 3:
                    display_type = "SINGLE_ARROW"
                    display_size = 0.3
                    empty_name = f"Skid_{point.name_tag or point.key.split('.')[-1]}"
                elif point.point_class == 4:
                    display_type = "CUBE"
                    display_size = 0.35
                    empty_name = f"Float_{point.name_tag or point.key.split('.')[-1]}"
                elif point.point_class == 5:
                    display_type = "SPHERE"
                    display_size = 0.35
                    empty_name = f"WaterRudder_{point.name_tag or point.key.split('.')[-1]}"
                else:
                    empty_name = f"ContactPoint_{point.key.split('.')[-1]}"
            elif point.point_type == "FUEL_TANK":
                display_type = "SPHERE"
                display_size = 0.3
                clean_tag = point.name_tag or "Tank"
                empty_name = f"Fuel_{clean_tag}"
            elif point.point_type == "ENGINE":
                display_type = "CONE"
                display_size = 0.4
                empty_name = f"Engine_{point.key.split('.')[-1]}"
            elif point.point_type == "PAYLOAD_STATION":
                display_type = "CUBE"
                display_size = 0.25
                clean_tag = point.name_tag or f"Station_{point.key.split('.')[-1]}"
                empty_name = f"Payload_{clean_tag}"
            else:
                empty_name = f"Point_{point.key.replace('.', '_')}"

            # Ensure unique name or find existing
            p_empty = next((o for o in spatial_col.objects if o.get("msfs_id") == point.key), None)
            if not p_empty:
                clean_empty_name = re.sub(r"[^\w]", "_", empty_name).strip("_")
                p_empty = bpy.data.objects.new(clean_empty_name, None)
                spatial_col.objects.link(p_empty)

            p_empty.empty_display_type = display_type
            p_empty.empty_display_size = display_size
            p_empty["msfs_id"] = point.key
            p_empty["msfs_type"] = point.point_type
            p_empty["msfs_class"] = point.point_class
            p_empty["msfs_tag"] = point.name_tag

            p_empty.parent = datum_empty
            p_empty.location = (
                point.coords_msfs_rel_ft[1] * FEET_TO_METERS,
                point.coords_msfs_rel_ft[0] * FEET_TO_METERS,
                point.coords_msfs_rel_ft[2] * FEET_TO_METERS,
            )
            spatial_count += 1

        if props:
            props.msfs_spatial_cfg_path = str(manifest.flight_model_cfg_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
        logger.warning("Error ingesting spatial points: %s", exc)

    return spatial_count, datum_empty


def import_lighting_points(
    context: Any,
    manifest: Any,
    asset_name: str,
    datum_empty: Optional[Any],
    props: Any,
) -> int:
    """Parses systems.cfg and creates aviation light sources."""
    lights_count = 0
    if not manifest.systems_cfg_path or not os.path.isfile(manifest.systems_cfg_path):
        return 0

    lights_col = get_or_create_engine_import_collection(context, asset_name, "LIGHTS")
    has_interior = manifest.interior_model is not None or (
        bpy
        and hasattr(bpy.data, "collections")
        and (
            f"{asset_name}_Interior" in bpy.data.collections
            or bpy.data.collections.get(f"{asset_name}_Interior_LOD0") is not None
        )
    )
    inte_lights_col = (
        get_or_create_engine_import_collection(context, f"{asset_name}_Interior", "LIGHTS") if has_interior else None
    )
    if lights_col:
        try:
            from .msfs_lighting_ops import OMNIMESH_OT_import_msfs_lights

            cfg_lights = MSFSCSTParser.parse_file(manifest.systems_cfg_path)
            datum = datum_empty or bpy.data.objects.get("Datum") or bpy.data.objects.get("MSFS_Datum")

            for light in cfg_lights.lights:
                target_col = inte_lights_col if (inte_lights_col and light.light_type in (4, 10)) else lights_col
                OMNIMESH_OT_import_msfs_lights._ensure_light_object(
                    col=target_col,
                    light=light,
                    datum_empty=datum,
                    context=context,
                )
                lights_count += 1

            if props:
                props.msfs_systems_cfg_path = str(manifest.systems_cfg_path)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.warning("Error ingesting lights: %s", exc)

    return lights_count


def import_cameras(
    context: Any,
    manifest: Any,
    asset_name: str,
    datum_empty: Optional[Any],
    props: Any,
) -> int:
    """Parses cameras.cfg and creates eyepoint and camera objects."""
    cameras_count = 0
    if not manifest.cameras_cfg_path or not os.path.isfile(manifest.cameras_cfg_path):
        return 0

    try:
        cam_cfg = MSFSCSTParser.parse_cameras_file(manifest.cameras_cfg_path)
        datum = datum_empty or bpy.data.objects.get("Datum") or bpy.data.objects.get("MSFS_Datum")

        has_interior = (
            manifest.interior_model is not None
            or f"{asset_name}_Interior" in bpy.data.collections
            or bpy.data.collections.get(f"{asset_name}_Interior_LOD0") is not None
        )

        ext_cam_col = get_or_create_engine_import_collection(context, asset_name, "CAMERAS")
        inte_cam_col = (
            get_or_create_engine_import_collection(context, f"{asset_name}_Interior", "CAMERAS")
            if has_interior
            else None
        )
        target_eye_col = inte_cam_col or ext_cam_col

        # Eyepoint (scoped strictly to target_eye_col)
        eye_empty = None
        if target_eye_col:
            eye_empty = next(
                (
                    o
                    for o in target_eye_col.objects
                    if o.get("msfs_id") == "VIEWS:eyepoint" or o.get("msfs_type") == "EYEPOINT"
                ),
                None,
            )
        if not eye_empty:
            e_name = "Eyepoint" if "Eyepoint" not in bpy.data.objects else f"{asset_name}_Eyepoint"
            eye_empty = bpy.data.objects.new(e_name, None)
            if target_eye_col:
                target_eye_col.objects.link(eye_empty)

        if datum and eye_empty != datum:
            eye_empty.parent = datum

        eye_ft = cam_cfg.eyepoint_ft
        eye_empty.location = (
            eye_ft[1] * FEET_TO_METERS,
            eye_ft[0] * FEET_TO_METERS,
            eye_ft[2] * FEET_TO_METERS,
        )
        eye_empty.empty_display_type = "SINGLE_ARROW"
        eye_empty.empty_display_size = 0.3
        eye_empty["msfs_id"] = "VIEWS:eyepoint"
        eye_empty["msfs_type"] = "EYEPOINT"
        context.view_layer.update()

        # Cameras
        for cam in cam_cfg.cameras:
            clean_title = re.sub(r"[^\w]", "_", cam.title or cam.category or f"Cam_{cam.index}").strip("_")
            cam_name = f"Cam_{cam.index}_{clean_title}"
            is_vc = cam.origin == "Virtual Cockpit"
            target_cam_col = inte_cam_col if is_vc and inte_cam_col else ext_cam_col
            if not target_cam_col:
                continue

            cam_obj = None
            for obj in target_cam_col.objects:
                if obj.get("msfs_camera_guid") == cam.guid or obj.get("msfs_camera_index") == cam.index:
                    cam_obj = obj
                    break

            if not cam_obj:
                camera_data = bpy.data.cameras.new(name=cam_name)
                cam_obj = bpy.data.objects.new(cam_name, camera_data)
                target_cam_col.objects.link(cam_obj)
            else:
                cam_obj.name = cam_name
                camera_data = cam_obj.data

            camera_data.lens = msfs_zoom_to_blender_focal_length(cam.initial_zoom)
            camera_data.clip_start = 0.05
            camera_data.clip_end = 1000.0

            p_deg, b_deg, h_deg = cam.initial_pbh_deg
            cam_obj.rotation_euler = msfs_pbh_to_blender_rotation(p_deg, b_deg, h_deg)

            init_x, init_y, init_z = cam.initial_xyz_m
            offset_m = (init_x, init_z, init_y)
            if is_vc and eye_empty:
                cam_obj.parent = eye_empty
                cam_obj.location = offset_m
            elif datum:
                cam_obj.parent = datum
                cam_obj.location = offset_m
            else:
                cam_obj.location = offset_m

            cam_obj["msfs_camera_index"] = cam.index
            cam_obj["msfs_camera_guid"] = cam.guid
            cam_obj["msfs_camera_title"] = cam.title
            cam_obj["msfs_camera_origin"] = cam.origin
            cam_obj["msfs_camera_category"] = cam.category
            cameras_count += 1

        if props:
            props.msfs_cameras_cfg_path = str(manifest.cameras_cfg_path)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
        logger.warning("Error ingesting cameras: %s", exc)

    return cameras_count


def import_attachments(context: Any, manifest: Any) -> int:
    """Parses and imports attached objects configuration."""
    attachments_count = 0
    if not manifest.attached_objects_cfg_path or not os.path.isfile(manifest.attached_objects_cfg_path):
        return 0
    try:
        from .msfs_attachment_ops import OMNIMESH_OT_import_msfs_attachments

        att_op = OMNIMESH_OT_import_msfs_attachments()
        att_op.filepath = manifest.attached_objects_cfg_path
        res = att_op.execute(context)
        if "FINISHED" in res:
            attachments_count = getattr(att_op, "imported_count", 1)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
        logger.warning("Error ingesting attachments: %s", exc)
    return attachments_count
