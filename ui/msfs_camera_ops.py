"""
MSFS Camera Configuration Operators for Blender.
Provides operators for importing, visualizing, aligning, and synchronizing
MSFS 2020 & 2024 cockpit and external cameras (cameras.cfg).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

try:
    import bpy
    from bpy.props import StringProperty
    from bpy.types import Collection, Object, Operator
except ImportError:
    bpy = None
    Collection = object
    Object = object
    Operator = object

    def StringProperty(**kwargs: Any) -> Any:
        return ""


try:
    from ..core.msfs_cst_parser import MSFSCSTParser
    from ..core.msfs_models import CameraDefinition
    from ..core.msfs_transforms import (
        FEET_TO_METERS,
        METERS_TO_FEET,
        blender_focal_length_to_msfs_zoom,
        blender_rotation_to_msfs_pbh,
        msfs_pbh_to_blender_rotation,
        msfs_zoom_to_blender_focal_length,
    )
except (ImportError, ValueError):
    from core.msfs_cst_parser import MSFSCSTParser
    from core.msfs_models import CameraDefinition
    from core.msfs_transforms import (
        FEET_TO_METERS,
        METERS_TO_FEET,
        blender_focal_length_to_msfs_zoom,
        blender_rotation_to_msfs_pbh,
        msfs_pbh_to_blender_rotation,
        msfs_zoom_to_blender_focal_length,
    )

logger = logging.getLogger(__name__)

DATUM_POINT_ID = "WEIGHT_AND_BALANCE:reference_datum_position"


def find_cameras_collection(context: Any) -> Optional[Collection]:
    """Finds existing cameras collection by role tag, asset name, or legacy name."""
    if not bpy:
        return None
    for col in bpy.data.collections:
        if col.get("_omnimesh_role") == "CAMERAS":
            return col
    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    asset_name = getattr(props, "export_base_name", "") if props else ""
    if asset_name and f"{asset_name}_Cameras" in bpy.data.collections:
        return bpy.data.collections[f"{asset_name}_Cameras"]
    for name in ("Cameras", "MSFS_Spatial_Cameras"):
        if name in bpy.data.collections:
            return bpy.data.collections[name]
    return None


def get_or_create_cameras_collection(
    context: Any, asset_name: str = "", is_interior: bool = False
) -> Optional[Collection]:
    """Finds or creates the dedicated cameras collection in the active scene."""
    if not bpy or not context:
        return None

    props = getattr(context.scene, "lod_tool", None)
    base_asset = asset_name or (getattr(props, "export_base_name", "") if props else "") or "Asset"
    target_asset = f"{base_asset}_Interior" if is_interior and not base_asset.endswith("_Interior") else base_asset

    try:
        from .utils import get_or_create_engine_import_collection

        return get_or_create_engine_import_collection(context, target_asset, "CAMERAS")
    except Exception:
        col_name = f"{target_asset}_Cameras"
        col = bpy.data.collections.get(col_name)
        if not col:
            col = bpy.data.collections.new(col_name)
            context.scene.collection.children.link(col)
            col["_omnimesh_role"] = "CAMERAS"
        return col


class OMNIMESH_OT_import_msfs_cameras(Operator):
    """Parses cameras.cfg and spawns Blender cameras for pilot and external views."""

    bl_idname = "omnimesh.import_msfs_cameras"
    bl_label = "Import MSFS Cameras"
    bl_description = "Parse cameras.cfg and create/update Blender cameras for pilot and external views"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(
        name="File Path",
        description="Path to cameras.cfg",
        subtype="FILE_PATH",
        default="",
    )

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(bpy and context and context.scene)

    def invoke(self, context: Any, event: Any) -> set[str]:
        props = getattr(context.scene, "lod_tool", None)
        target = getattr(props, "msfs_cameras_cfg_path", "") if props else ""
        if target and os.path.isfile(target):
            self.filepath = target
            return self.execute(context)
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        target_file = self.filepath or getattr(context.scene.lod_tool, "msfs_cameras_cfg_path", "")
        if not target_file or not os.path.isfile(target_file):
            self.report({"ERROR"}, "Please select a valid cameras.cfg file.")
            return {"CANCELLED"}

        try:
            cam_config = MSFSCSTParser.parse_cameras_file(target_file)
        except Exception as exc:
            logger.error("Failed parsing cameras.cfg from %s: %s", target_file, exc)
            self.report({"ERROR"}, f"Failed parsing cameras.cfg: {exc}")
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        base_asset = getattr(props, "export_base_name", "") if props else ""
        if not base_asset:
            base_asset = "Asset"

        # Check if interior model is part of this scene
        has_interior = (
            f"{base_asset}_Interior" in bpy.data.collections
            or bpy.data.collections.get(f"{base_asset}_Interior_LOD0") is not None
        )

        ext_col = get_or_create_cameras_collection(context, asset_name=base_asset, is_interior=False)
        inte_col = (
            get_or_create_cameras_collection(context, asset_name=base_asset, is_interior=True) if has_interior else None
        )

        target_eye_col = inte_col or ext_col
        if not target_eye_col:
            self.report({"ERROR"}, "Could not create cameras collection.")
            return {"CANCELLED"}

        # 1. Resolve Datum Position from active scene or companion flight_model.cfg
        datum_empty: Optional[Object] = bpy.data.objects.get("Datum") or bpy.data.objects.get("MSFS_Datum")
        if not datum_empty:
            for obj in context.scene.objects:
                if obj.get("msfs_id") == DATUM_POINT_ID:
                    datum_empty = obj
                    break

        # 2. Setup Eyepoint Marker (in Blender meters relative to datum)
        eyepoint_ft = cam_config.eyepoint_ft
        eyepoint_local_m = (
            eyepoint_ft[1] * FEET_TO_METERS,  # Lat -> X
            eyepoint_ft[0] * FEET_TO_METERS,  # Long -> Y
            eyepoint_ft[2] * FEET_TO_METERS,  # Vert -> Z
        )

        eye_empty: Optional[Object] = None
        for obj in target_eye_col.objects:
            if obj.get("msfs_id") == "VIEWS:eyepoint" or obj.name in ("Eyepoint", "MSFS_Eyepoint"):
                eye_empty = obj
                break

        if not eye_empty:
            eye_empty = bpy.data.objects.new("Eyepoint", None)
            target_eye_col.objects.link(eye_empty)
            if datum_empty:
                eye_empty.parent = datum_empty
        else:
            eye_empty.name = "Eyepoint"

        if eye_empty is None:
            self.report({"ERROR"}, "Failed to create Eyepoint empty.")
            return {"CANCELLED"}

        eye_empty.location = eyepoint_local_m
        eye_empty.empty_display_type = "SINGLE_ARROW"
        eye_empty.empty_display_size = 0.3
        eye_empty["msfs_id"] = "VIEWS:eyepoint"
        eye_empty["msfs_type"] = "EYEPOINT"

        context.view_layer.update()

        # 3. Spawn / Update Blender Camera Objects
        count = 0
        for cam in cam_config.cameras:
            clean_title = re.sub(r"[^\w]", "_", cam.title or cam.category or f"Cam_{cam.index}").strip("_")
            cam_name = f"Cam_{cam.index}_{clean_title}"
            is_vc = cam.origin == "Virtual Cockpit"
            target_col = inte_col if is_vc and inte_col else ext_col
            if not target_col:
                continue

            cam_obj: Optional[Object] = None
            for obj in target_col.objects:
                if obj.get("msfs_camera_guid") == cam.guid or obj.get("msfs_camera_index") == cam.index:
                    cam_obj = obj
                    break

            if not cam_obj:
                camera_data = bpy.data.cameras.new(name=cam_name)
                cam_obj = bpy.data.objects.new(cam_name, camera_data)
                target_col.objects.link(cam_obj)
            else:
                cam_obj.name = cam_name
                camera_data = cam_obj.data

            if cam_obj is None or camera_data is None:
                continue

            # Set focal length from InitialZoom
            camera_data.lens = msfs_zoom_to_blender_focal_length(cam.initial_zoom)
            camera_data.clip_start = 0.05
            camera_data.clip_end = 1000.0

            # Compute orientation (PBH -> Blender Euler XYZ)
            p_deg, b_deg, h_deg = cam.initial_pbh_deg
            rx, ry, rz = msfs_pbh_to_blender_rotation(p_deg, b_deg, h_deg)
            cam_obj.rotation_euler = (rx, ry, rz)

            # Compute location based on Origin
            # InitialXyz is (Lateral, Vertical, Longitudinal) in METERS
            init_x, init_y, init_z = cam.initial_xyz_m
            # Blender space: X=Lat, Y=Long, Z=Vert
            offset_blender_m = (init_x, init_z, init_y)

            if is_vc and eye_empty:
                # Relative to Eyepoint
                cam_obj.parent = eye_empty
                cam_obj.location = offset_blender_m
            elif datum_empty:
                cam_obj.parent = datum_empty
                cam_obj.location = offset_blender_m
            else:
                cam_obj.parent = None
                cam_obj.location = offset_blender_m

            # Custom properties for round-trip tracking
            cam_obj["msfs_id"] = f"CAMERADEFINITION:{cam.index}"
            cam_obj["msfs_camera_index"] = cam.index
            cam_obj["msfs_camera_guid"] = cam.guid
            cam_obj["msfs_camera_title"] = cam.title
            cam_obj["msfs_camera_origin"] = cam.origin
            cam_obj["msfs_camera_category"] = cam.category
            cam_obj["msfs_camera_subcategory"] = cam.subcategory
            count += 1

        if props:
            props.msfs_cameras_cfg_path = target_file
            props.msfs_spatial_status = f"Imported {count} cameras"

        self.report({"INFO"}, f"Successfully imported {count} cameras from {os.path.basename(target_file)}")
        return {"FINISHED"}


class OMNIMESH_OT_export_msfs_cameras(Operator):
    """Synchronizes modified Blender camera transforms back into cameras.cfg losslessly."""

    bl_idname = "omnimesh.export_msfs_cameras"
    bl_label = "Sync Cameras to CFG"
    bl_description = "Reads current Blender camera transforms and writes back to cameras.cfg with atomic backup"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        props = getattr(context.scene, "lod_tool", None)
        return bool(props and props.msfs_cameras_cfg_path and os.path.isfile(props.msfs_cameras_cfg_path))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = context.scene.lod_tool
        target_file = props.msfs_cameras_cfg_path
        if not target_file or not os.path.isfile(target_file):
            self.report({"ERROR"}, "Valid cameras.cfg path must be specified.")
            return {"CANCELLED"}

        try:
            cam_config = MSFSCSTParser.parse_cameras_file(target_file)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed reading {target_file}: {exc}")
            return {"CANCELLED"}

        # Collect candidate cameras and eyepoint across all collections in the scene
        candidate_objs = [
            o
            for o in getattr(context.scene, "objects", [])
            if o.get("msfs_camera_index") is not None or o.get("msfs_id") == "VIEWS:eyepoint"
        ]
        if not candidate_objs and hasattr(bpy, "data") and hasattr(bpy.data, "objects"):
            candidate_objs = [
                o
                for o in bpy.data.objects
                if o.get("msfs_camera_index") is not None or o.get("msfs_id") == "VIEWS:eyepoint"
            ]
        if not candidate_objs:
            self.report({"WARNING"}, "No cameras found in scene to synchronize.")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()

        # Check for modified eyepoint
        eye_empty: Optional[Object] = None
        for obj in candidate_objs:
            if obj.get("msfs_id") == "VIEWS:eyepoint" or obj.name in ("Eyepoint", "MSFS_Eyepoint"):
                eye_empty = obj
                break

        updated_eyepoint_ft: Optional[tuple[float, float, float]] = None
        if eye_empty:
            loc = eye_empty.location
            # Blender (X_lat, Y_long, Z_vert) -> MSFS (Long, Lat, Vert) in feet
            updated_eyepoint_ft = (
                loc.y * METERS_TO_FEET,
                loc.x * METERS_TO_FEET,
                loc.z * METERS_TO_FEET,
            )

        updated_cams: dict[str, CameraDefinition] = {}

        for obj in candidate_objs:
            guid = obj.get("msfs_camera_guid")
            idx = obj.get("msfs_camera_index")
            if guid is None and idx is None:
                continue

            eval_obj = obj.evaluated_get(depsgraph)

            # Invert rotation
            rot = eval_obj.rotation_euler
            p_deg, b_deg, h_deg = blender_rotation_to_msfs_pbh(rot.x, rot.y, rot.z)

            # Invert focal length to zoom
            cam_data = obj.data
            focal_mm = getattr(cam_data, "lens", 35.0)
            zoom = blender_focal_length_to_msfs_zoom(focal_mm)

            # Invert position
            origin = obj.get("msfs_camera_origin", "Virtual Cockpit")
            if origin == "Virtual Cockpit" and eye_empty:
                # Relative to eyepoint
                mat_rel = eye_empty.matrix_world.inverted() @ eval_obj.matrix_world
                pos_m = mat_rel.translation
            else:
                pos_m = eval_obj.matrix_world.translation

            # Blender (X_lat, Y_long, Z_vert) -> MSFS (Lateral, Vertical, Longitudinal) in METERS
            initial_xyz_m = (pos_m.x, pos_m.z, pos_m.y)

            # Find matching definition in config
            match_def: Optional[CameraDefinition] = None
            for c in cam_config.cameras:
                if (guid and c.guid == guid) or (idx is not None and c.index == idx):
                    match_def = c
                    break

            if match_def:
                match_def.initial_xyz_m = initial_xyz_m
                match_def.initial_pbh_deg = (p_deg, b_deg, h_deg)
                match_def.initial_zoom = zoom
                ident = match_def.guid or match_def.title or f"Camera_{match_def.index}"
                updated_cams[ident] = match_def

        try:
            backup_path = MSFSCSTParser.serialize_and_save_cameras(
                config=cam_config,
                updated_cameras=updated_cams,
                updated_eyepoint_ft=updated_eyepoint_ft,
                target_path=target_file,
            )
        except Exception as exc:
            logger.error("Failed syncing cameras to %s: %s", target_file, exc)
            self.report({"ERROR"}, f"Failed saving cameras.cfg: {exc}")
            return {"CANCELLED"}

        backup_name = os.path.basename(backup_path)
        props.msfs_spatial_status = f"Synced {len(updated_cams)} cameras (Backup: {backup_name})"
        self.report(
            {"INFO"}, f"Synced {len(updated_cams)} cameras to {os.path.basename(target_file)} (Backup: {backup_name})"
        )
        return {"FINISHED"}


class OMNIMESH_OT_look_through_msfs_camera(Operator):
    """Switches Blender viewport to look through the active MSFS camera."""

    bl_idname = "omnimesh.look_through_msfs_camera"
    bl_label = "Look Through MSFS Camera"
    bl_description = "Set active MSFS camera as active scene camera and view through it"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        active = getattr(context, "active_object", None)
        return bool(active and active.type == "CAMERA" and active.get("msfs_camera_index") is not None)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        cam_obj = context.active_object
        scene = context.scene

        # Save previous scene camera if not already set to an MSFS camera (explicit None check to handle index 0)
        if scene.camera and scene.camera.get("msfs_camera_index") is None:
            scene["omnimesh_previous_scene_camera"] = scene.camera.name

        scene.camera = cam_obj

        # Set 3D viewport to camera view if in 3D area
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.region_3d.view_perspective = "CAMERA"
                        break

        self.report({"INFO"}, f"Looking through {cam_obj.name}")
        return {"FINISHED"}


class OMNIMESH_OT_restore_scene_camera(Operator):
    """Restores the previous original scene camera before MSFS camera switching."""

    bl_idname = "omnimesh.restore_scene_camera"
    bl_label = "Restore Original Camera"
    bl_description = "Restores the previous scene camera that was active before switching to an MSFS camera"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context or not context.scene:
            return False
        has_prev = bool(context.scene.get("omnimesh_previous_scene_camera"))
        is_msfs_cam = bool(context.scene.camera and context.scene.camera.get("msfs_camera_index") is not None)
        return has_prev or is_msfs_cam

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context or not context.scene:
            return {"CANCELLED"}

        prev_name = context.scene.get("omnimesh_previous_scene_camera")
        if prev_name and prev_name in bpy.data.objects:
            orig_cam = bpy.data.objects[prev_name]
            context.scene.camera = orig_cam
            self.report({"INFO"}, f"Restored active camera to {orig_cam.name}")
        else:
            context.scene.camera = None
            self.report({"INFO"}, "Exited camera view to free perspective.")

        if "omnimesh_previous_scene_camera" in context.scene:
            del context.scene["omnimesh_previous_scene_camera"]

        # Reset 3D viewport back to User Perspective
        if hasattr(context, "screen") and context.screen:
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    for space in area.spaces:
                        if space.type == "VIEW_3D":
                            space.region_3d.view_perspective = "PERSP"
                            break

        return {"FINISHED"}


class OMNIMESH_OT_align_msfs_camera_to_view(Operator):
    """Aligns the selected MSFS camera directly to current 3D viewport position and orientation."""

    bl_idname = "omnimesh.align_msfs_camera_to_view"
    bl_label = "Align MSFS Camera to View"
    bl_description = "Copies current 3D viewport perspective and position into active MSFS camera"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        active = getattr(context, "active_object", None)
        return bool(active and active.type == "CAMERA" and active.get("msfs_camera_index") is not None)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        cam_obj = context.active_object

        # Find active 3D view region matrix
        r3d = None
        for area in context.screen.areas:
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        r3d = space.region_3d
                        break
                if r3d:
                    break

        if not r3d:
            self.report({"ERROR"}, "Could not access 3D Viewport perspective.")
            return {"CANCELLED"}

        view_matrix = r3d.view_matrix.inverted()

        # If parented (e.g. to Eyepoint), convert to parent-local coordinates
        if cam_obj.parent:
            parent_inv = cam_obj.parent.matrix_world.inverted()
            local_matrix = parent_inv @ view_matrix
            cam_obj.matrix_local = local_matrix
        else:
            cam_obj.matrix_world = view_matrix

        self.report({"INFO"}, f"Aligned {cam_obj.name} to 3D Viewport.")
        return {"FINISHED"}


classes = (
    OMNIMESH_OT_import_msfs_cameras,
    OMNIMESH_OT_export_msfs_cameras,
    OMNIMESH_OT_look_through_msfs_camera,
    OMNIMESH_OT_restore_scene_camera,
    OMNIMESH_OT_align_msfs_camera_to_view,
)


def register():
    if not bpy:
        return
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    if not bpy:
        return
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except ValueError:
            pass
