"""
MSFS Spatial Configuration Operators for Blender.
Provides viewport operators for importing, visualizing, and synchronizing
MSFS 2020 & 2024 aircraft contact points, fuel tanks, and datum points.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

try:
    import bpy
    from bpy.types import Collection, Object, Operator
except ImportError:
    bpy = None
    Collection = object
    Object = object
    Operator = object

try:
    from ..core.msfs_cst_parser import MSFSCSTParser
    from ..core.msfs_models import SpatialPoint
    from ..core.msfs_transforms import FEET_TO_METERS, METERS_TO_FEET, blender_to_msfs
except (ImportError, ValueError):
    from core.msfs_cst_parser import MSFSCSTParser
    from core.msfs_models import SpatialPoint
    from core.msfs_transforms import FEET_TO_METERS, METERS_TO_FEET, blender_to_msfs

logger = logging.getLogger(__name__)

COLLECTION_NAME = "MSFS_Spatial_Config"
DATUM_POINT_ID = "WEIGHT_AND_BALANCE:reference_datum_position"


def get_or_create_spatial_collection(context: Any) -> Optional[Collection]:
    """Finds or creates the dedicated MSFS_Spatial_Config collection in the active scene."""
    if not bpy:
        return None

    scene = context.scene
    col = bpy.data.collections.get(COLLECTION_NAME)
    if not col:
        col = bpy.data.collections.new(COLLECTION_NAME)
        scene.collection.children.link(col)
    elif col.name not in scene.collection.children:
        try:
            scene.collection.children.link(col)
        except RuntimeError:
            pass  # Already linked in scene hierarchy
    return col


class OMNIMESH_OT_import_msfs_spatial(Operator):
    """Parses flight_model.cfg and creates/updates visual empties for MSFS spatial markers."""

    bl_idname = "omnimesh.import_msfs_spatial"
    bl_label = "Import MSFS Spatial Config"
    bl_description = "Parse flight_model.cfg and spawn/update visual empties for contact points, fuel tanks, and datum"
    bl_options = {"REGISTER", "UNDO"}

    filepath: Any = (
        bpy.props.StringProperty(
            name="File Path",
            description="Path to flight_model.cfg",
            subtype="FILE_PATH",
            default="",
        )
        if bpy
        else ""
    )

    filter_glob: Any = (
        bpy.props.StringProperty(
            default="*.cfg",
            options={"HIDDEN"},
        )
        if bpy
        else "*.cfg"
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        # If filepath is already set in scene properties, use it as default
        props = getattr(context.scene, "lod_tool", None)
        if props and props.msfs_spatial_cfg_path and os.path.isfile(props.msfs_spatial_cfg_path):
            self.filepath = props.msfs_spatial_cfg_path

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        target_file = self.filepath.strip()
        props = getattr(context.scene, "lod_tool", None)

        if not target_file and props and props.msfs_spatial_cfg_path:
            target_file = props.msfs_spatial_cfg_path.strip()

        if not target_file or not os.path.isfile(target_file):
            self.report({"ERROR"}, "Please select a valid flight_model.cfg file.")
            return {"CANCELLED"}

        try:
            config = MSFSCSTParser.parse_file(target_file)
        except Exception as exc:
            logger.error("Failed to parse MSFS config file %s: %s", target_file, exc)
            self.report({"ERROR"}, f"Failed to parse config: {exc}")
            return {"CANCELLED"}

        col = get_or_create_spatial_collection(context)
        if not col:
            self.report({"ERROR"}, "Failed to access spatial collection.")
            return {"CANCELLED"}

        # 1. Root Datum Empty (Placed in World Space)
        datum_coords_m = config.points[0].coords_blender_m if config.points else (0.0, 0.0, 0.0)
        datum_empty = self._ensure_empty(
            col=col,
            point_id=DATUM_POINT_ID,
            name="MSFS_Datum",
            local_pos_m=datum_coords_m,
            display_type="CROSS",
            display_size=0.5,
            point=config.points[0] if config.points else None,
            parent=None,
        )

        # Force scene graph update so datum transform is live for child parenting
        context.view_layer.update()

        # 2. Process all relative markers (Parented to Datum)
        count = 0
        for point in config.points:
            if point.point_type == "DATUM":
                continue

            display_type = "PLAIN_AXES"
            display_size = 0.25

            if point.point_type == "CONTACT_POINT":
                if point.point_class == 1:
                    display_type = "CIRCLE"  # Wheels
                    display_size = 0.35
                else:
                    display_type = "PLAIN_AXES"  # Scrape points
                    display_size = 0.2
            elif point.point_type == "FUEL_TANK":
                display_type = "CUBE"
                display_size = 0.4
            elif point.point_type == "CG":
                display_type = "SPHERE"
                display_size = 0.25

            empty_name = f"MSFS_{point.point_type[:4]}_{point.name_tag or point.key}"

            # Compute parent-local coordinates (relative to datum in meters)
            rel_ft = point.coords_msfs_rel_ft
            local_pos_m = (
                rel_ft[1] * FEET_TO_METERS,  # Lateral -> X
                rel_ft[0] * FEET_TO_METERS,  # Longitudinal -> Y
                rel_ft[2] * FEET_TO_METERS,  # Vertical -> Z
            )

            self._ensure_empty(
                col=col,
                point_id=point.point_id,
                name=empty_name,
                local_pos_m=local_pos_m,
                display_type=display_type,
                display_size=display_size,
                point=point,
                parent=datum_empty,
            )
            count += 1

        # Store path in central settings
        if props:
            props.msfs_spatial_cfg_path = target_file
            props.msfs_spatial_status = f"Imported {len(config.points)} markers"

        self.report(
            {"INFO"},
            f"Successfully imported {count} spatial markers from {os.path.basename(target_file)}",
        )
        return {"FINISHED"}

    def _ensure_empty(
        self,
        col: Collection,
        point_id: str,
        name: str,
        local_pos_m: tuple[float, float, float],
        display_type: str,
        display_size: float,
        point: Optional[SpatialPoint],
        parent: Optional[Object],
    ) -> Object:
        """Idempotently finds an existing empty by msfs_id or spawns a new one."""
        existing = None
        for obj in col.objects:
            if obj.get("msfs_id") == point_id:
                existing = obj
                break

        if existing:
            empty = existing
        else:
            empty = bpy.data.objects.new(name, None)
            col.objects.link(empty)

        # Parent to datum before setting location so local coordinates match CFG relative meters
        if parent and empty != parent and empty.parent != parent:
            empty.parent = parent

        empty.location = local_pos_m
        empty.empty_display_type = display_type
        empty.empty_display_size = display_size

        # Custom Properties for round-trip tracking
        empty["msfs_id"] = point_id
        if point:
            empty["msfs_section"] = point.section
            empty["msfs_key"] = point.key
            empty["msfs_type"] = point.point_type
            empty["msfs_name_tag"] = point.name_tag
            empty["msfs_class"] = point.point_class

        return empty


class OMNIMESH_OT_export_msfs_spatial(Operator):
    """Syncs modified Blender empty positions back into flight_model.cfg with automatic backup."""

    bl_idname = "omnimesh.export_msfs_spatial"
    bl_label = "Sync Empties to CFG"
    bl_description = "Sync modified Blender empties losslessly back into flight_model.cfg with automatic backup"
    bl_options = {"REGISTER"}  # Explicitly NO 'UNDO' to avoid desync with disk files

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        props = getattr(context.scene, "lod_tool", None)
        return bool(props and props.msfs_spatial_cfg_path and os.path.isfile(props.msfs_spatial_cfg_path))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        if not props or not props.msfs_spatial_cfg_path or not os.path.isfile(props.msfs_spatial_cfg_path):
            self.report({"ERROR"}, "No valid flight_model.cfg selected to synchronize.")
            return {"CANCELLED"}

        cfg_path = props.msfs_spatial_cfg_path

        try:
            config = MSFSCSTParser.parse_file(cfg_path)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed reading source config: {exc}")
            return {"CANCELLED"}

        col = bpy.data.collections.get(COLLECTION_NAME)
        if not col:
            self.report({"ERROR"}, f"Collection '{COLLECTION_NAME}' not found.")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()
        updated_coords: dict[str, tuple[float, float, float]] = {}

        # 1. First locate and evaluate the Datum Empty to determine the active reference datum
        active_datum = config.reference_datum_ft
        datum_empty: Optional[Object] = None

        for obj in col.objects:
            if obj.get("msfs_id") == DATUM_POINT_ID:
                datum_empty = obj
                break

        if datum_empty:
            eval_datum = datum_empty.evaluated_get(depsgraph)
            datum_world = eval_datum.matrix_world.translation
            # Datum in world space maps: X -> Lat, Y -> Long, Z -> Vert in feet
            active_datum = (
                datum_world.y * METERS_TO_FEET,
                datum_world.x * METERS_TO_FEET,
                datum_world.z * METERS_TO_FEET,
            )
            updated_coords[DATUM_POINT_ID] = active_datum

        # 2. Evaluate all child / relative empties against active_datum
        for obj in col.objects:
            point_id = obj.get("msfs_id")
            if not point_id or not isinstance(point_id, str) or point_id == DATUM_POINT_ID:
                continue

            eval_obj = obj.evaluated_get(depsgraph)
            world_pos = eval_obj.matrix_world.translation

            # Convert Blender world meters back to MSFS feet relative to active datum
            rel_long, rel_lat, rel_vert = blender_to_msfs(world_pos.x, world_pos.y, world_pos.z, active_datum)
            updated_coords[point_id] = (rel_long, rel_lat, rel_vert)

        if not updated_coords:
            self.report({"WARNING"}, "No spatial empties found to synchronize.")
            return {"CANCELLED"}

        try:
            backup_path = MSFSCSTParser.serialize_and_save(config, updated_coords, target_path=cfg_path)
        except Exception as exc:
            logger.error("Failed writing spatial config back to %s: %s", cfg_path, exc)
            self.report({"ERROR"}, f"Failed saving config: {exc}")
            return {"CANCELLED"}

        backup_name = os.path.basename(backup_path)
        props.msfs_spatial_status = f"Synced {len(updated_coords)} markers (Backup: {backup_name})"
        self.report(
            {"INFO"},
            f"Synced {len(updated_coords)} markers to {os.path.basename(cfg_path)} (Backup: {backup_name})",
        )
        return {"FINISHED"}


class OMNIMESH_OT_snap_msfs_point_to_vertex(Operator):
    """Snaps the active MSFS marker empty directly to the nearest vertex of selected mesh geometry."""

    bl_idname = "omnimesh.snap_msfs_point_to_vertex"
    bl_label = "Snap Marker to Nearest Vertex"
    bl_description = "Snap the active MSFS marker empty to the nearest vertex of the active mesh object"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        active = getattr(context, "active_object", None)
        return bool(active and active.get("msfs_id"))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        empty = context.active_object
        if not empty or not empty.get("msfs_id"):
            self.report({"ERROR"}, "Active object is not an MSFS spatial marker.")
            return {"CANCELLED"}

        # Find target mesh object among selected objects
        target_mesh: Optional[Object] = None
        for obj in context.selected_objects:
            if obj != empty and obj.type == "MESH":
                target_mesh = obj
                break

        if not target_mesh:
            self.report({"WARNING"}, "Select a target mesh object alongside the marker to snap to.")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()
        eval_mesh_obj = target_mesh.evaluated_get(depsgraph)
        mesh_data = eval_mesh_obj.to_mesh()

        try:
            mat_world = eval_mesh_obj.matrix_world
            empty_pos = empty.matrix_world.translation

            closest_world_pos = None
            min_dist_sq = float("inf")

            for v in mesh_data.vertices:
                v_world = mat_world @ v.co
                dist_sq = (v_world - empty_pos).length_squared
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    closest_world_pos = v_world

            if closest_world_pos is not None:
                if empty.parent:
                    empty.location = empty.parent.matrix_world.inverted() @ closest_world_pos
                else:
                    empty.location = closest_world_pos

                self.report(
                    {"INFO"},
                    f"Snapped {empty.name} to nearest vertex of {target_mesh.name} ({min_dist_sq**0.5:.3f}m)",
                )
                return {"FINISHED"}
            else:
                self.report({"WARNING"}, "No vertices found in target mesh.")
                return {"CANCELLED"}
        finally:
            eval_mesh_obj.to_mesh_clear()


classes = (
    OMNIMESH_OT_import_msfs_spatial,
    OMNIMESH_OT_export_msfs_spatial,
    OMNIMESH_OT_snap_msfs_point_to_vertex,
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
