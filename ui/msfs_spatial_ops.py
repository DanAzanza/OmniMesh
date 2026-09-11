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
    from ..core.msfs_models import SpatialPoint
    from ..core.msfs_transforms import FEET_TO_METERS, METERS_TO_FEET, blender_to_msfs
except (ImportError, ValueError):
    from core.msfs_cst_parser import MSFSCSTParser
    from core.msfs_models import SpatialPoint
    from core.msfs_transforms import FEET_TO_METERS, METERS_TO_FEET, blender_to_msfs

logger = logging.getLogger(__name__)

COLLECTION_NAME = "Spatial_Config"
DATUM_POINT_ID = "WEIGHT_AND_BALANCE:reference_datum_position"


def find_spatial_collection(context: Any) -> Optional[Collection]:
    """Finds existing spatial collection by role tag, asset name, or legacy name."""
    if not bpy:
        return None
    for col in bpy.data.collections:
        if col.get("_omnimesh_role") == "SPATIAL":
            return col
    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    asset_name = getattr(props, "export_base_name", "") if props else ""
    if asset_name and f"{asset_name}_Spatial" in bpy.data.collections:
        return bpy.data.collections[f"{asset_name}_Spatial"]
    for name in ("Spatial_Config", "MSFS_Spatial_Config"):
        if name in bpy.data.collections:
            return bpy.data.collections[name]
    return None


def get_or_create_spatial_collection(context: Any) -> Optional[Collection]:
    """Finds or creates the dedicated spatial collection in the active scene."""
    if not bpy or not context:
        return None

    existing = find_spatial_collection(context)
    if existing:
        return existing

    props = getattr(context.scene, "lod_tool", None)
    asset_name = getattr(props, "export_base_name", "") if props else ""
    if not asset_name:
        asset_name = "Asset"

    try:
        from .utils import get_or_create_engine_import_collection

        return get_or_create_engine_import_collection(context, asset_name, "SPATIAL")
    except Exception:
        col = bpy.data.collections.new(f"{asset_name}_Spatial")
        context.scene.collection.children.link(col)
        col["_omnimesh_role"] = "SPATIAL"
        return col


class OMNIMESH_OT_import_msfs_spatial(Operator):
    """Parses flight_model.cfg and creates/updates visual empties for MSFS spatial markers."""

    bl_idname = "omnimesh.import_msfs_spatial"
    bl_label = "Import MSFS Spatial Config"
    bl_description = "Parse flight_model.cfg and spawn/update visual empties for contact points, fuel tanks, and datum"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(
        name="File Path",
        description="Path to flight_model.cfg",
        subtype="FILE_PATH",
        default="",
    )

    filter_glob: StringProperty(
        default="*.cfg",
        options={"HIDDEN"},
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
            name="Datum",
            local_pos_m=datum_coords_m,
            display_type="PLAIN_AXES",
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
                    clean_tag = point.name_tag or "Wheel"
                    empty_name = f"Point_{point.key.split('.')[-1]}_{clean_tag}"
                elif point.point_class == 2:
                    display_type = "PLAIN_AXES"  # Scrape points
                    display_size = 0.2
                    empty_name = f"Scrape_{point.name_tag or point.key.split('.')[-1]}"
                else:
                    display_type = "PLAIN_AXES"
                    empty_name = f"Point_{point.key.split('.')[-1]}_{point.name_tag or point.point_type}"
            elif point.point_type == "FUEL_TANK":
                display_type = "CUBE"
                display_size = 0.4
                empty_name = f"Fuel_{point.name_tag or point.key}"
            elif point.point_type == "CG":
                display_type = "SPHERE"
                display_size = 0.25
                empty_name = "CG"
            else:
                empty_name = f"{point.name_tag or point.key}"

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
            if obj.get("msfs_id") == point_id or (point_id == DATUM_POINT_ID and obj.name in ("Datum", "MSFS_Datum")):
                existing = obj
                break

        if existing:
            empty = existing
            empty.name = name
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

        col = find_spatial_collection(context)
        candidate_objs = list(col.objects) if col else [o for o in context.scene.objects if o.get("msfs_id")]
        if not candidate_objs:
            self.report({"WARNING"}, "No spatial empties found in scene to synchronize.")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()
        updated_coords: dict[str, tuple[float, float, float]] = {}

        # 1. First locate and evaluate the Datum Empty to determine the active reference datum
        active_datum = config.reference_datum_ft
        datum_empty: Optional[Object] = None

        for obj in candidate_objs:
            if obj.get("msfs_id") == DATUM_POINT_ID or obj.name in ("Datum", "MSFS_Datum"):
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
        for obj in candidate_objs:
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


class OMNIMESH_OT_mirror_msfs_marker(Operator):
    """Reflects the active MSFS marker across the longitudinal symmetry plane (X=0) to its counterpart."""

    bl_idname = "omnimesh.mirror_msfs_marker"
    bl_label = "Mirror Selected Marker (L ↔ R)"
    bl_description = "Reflects active contact point, tank, or light across the sagittal plane (X=0) to counterpart"
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

        # 1. Centerline Safety Guard
        loc = empty.location
        if abs(loc.x) < 0.05:
            self.report({"WARNING"}, "Cannot mirror centerline marker (|X| < 0.05m).")
            return {"CANCELLED"}

        mir_x = -loc.x
        mir_y = loc.y
        mir_z = loc.z

        # 2. Spatial-First Counterpart Resolution
        counterpart: Optional[Object] = None
        col = empty.users_collection[0] if empty.users_collection else None
        search_objects = col.objects if col else context.scene.objects

        for cand in search_objects:
            if cand == empty or not cand.get("msfs_id"):
                continue
            # Must match same type (e.g. CONTACT_POINT or FUEL_TANK or LIGHT)
            if cand.get("msfs_type") != empty.get("msfs_type"):
                continue

            c_loc = cand.location
            if abs(c_loc.x - mir_x) < 0.05 and abs(c_loc.y - mir_y) < 0.05:
                counterpart = cand
                break

        if counterpart:
            # Update existing counterpart
            counterpart.location = (mir_x, mir_y, mir_z)
            # If object has rotation, reflect bank and heading
            if empty.rotation_mode == "XYZ":
                counterpart.rotation_euler = (
                    empty.rotation_euler.x,
                    -empty.rotation_euler.y,
                    -empty.rotation_euler.z,
                )
            self.report({"INFO"}, f"Updated mirrored counterpart {counterpart.name}")
            return {"FINISHED"}

        # 3. Spawn Mirrored Counterpart
        mir_name = self._compute_mirrored_name(empty.name)
        new_obj = bpy.data.objects.new(mir_name, empty.data)
        if col:
            col.objects.link(new_obj)
        else:
            context.scene.collection.objects.link(new_obj)

        if empty.parent:
            new_obj.parent = empty.parent
        new_obj.location = (mir_x, mir_y, mir_z)
        new_obj.empty_display_type = empty.empty_display_type
        new_obj.empty_display_size = empty.empty_display_size

        if empty.rotation_mode == "XYZ":
            new_obj.rotation_euler = (
                empty.rotation_euler.x,
                -empty.rotation_euler.y,
                -empty.rotation_euler.z,
            )

        # Copy custom properties with mirrored IDs
        orig_id = empty.get("msfs_id", "")
        new_obj["msfs_id"] = f"{orig_id}_MIRRORED"
        new_obj["msfs_section"] = empty.get("msfs_section", "")
        new_obj["msfs_key"] = f"{empty.get('msfs_key', '')}_mir"
        new_obj["msfs_type"] = empty.get("msfs_type", "")
        new_obj["msfs_class"] = empty.get("msfs_class", 0)
        new_obj["msfs_name_tag"] = self._compute_mirrored_name(str(empty.get("msfs_name_tag", "")))

        self.report({"INFO"}, f"Created mirrored marker {new_obj.name}")
        return {"FINISHED"}

    @staticmethod
    def _compute_mirrored_name(name: str) -> str:
        """Heuristically mirrors lateral identifiers in names."""
        if "_L" in name:
            return name.replace("_L", "_R")
        if "_R" in name:
            return name.replace("_R", "_L")
        if "Left" in name:
            return name.replace("Left", "Right")
        if "Right" in name:
            return name.replace("Right", "Left")
        if "left" in name:
            return name.replace("left", "right")
        if "right" in name:
            return name.replace("right", "left")
        if "Port" in name:
            return name.replace("Port", "Stbd")
        if "Stbd" in name:
            return name.replace("Stbd", "Port")
        return f"{name}_Mirrored"


classes = (
    OMNIMESH_OT_import_msfs_spatial,
    OMNIMESH_OT_export_msfs_spatial,
    OMNIMESH_OT_snap_msfs_point_to_vertex,
    OMNIMESH_OT_mirror_msfs_marker,
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
