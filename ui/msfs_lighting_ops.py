"""
MSFS Lighting Operators for Blender.
Provides viewport operators for importing, visualizing, and synchronizing
MSFS aircraft lights (Landing, Taxi, Nav, Strobe, Beacon) with accurate optical vectors.
"""

from __future__ import annotations

import logging
import math
import os
import re
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
    from ..core.msfs_models import CFGLineRecord, LightPoint
    from ..core.msfs_transforms import (
        FEET_TO_METERS,
        METERS_TO_FEET,
        blender_rotation_to_msfs_pbh,
        format_coordinate_float,
        msfs_pbh_to_blender_rotation,
    )
except (ImportError, ValueError):
    from core.msfs_cst_parser import MSFSCSTParser
    from core.msfs_models import CFGLineRecord, LightPoint
    from core.msfs_transforms import (
        FEET_TO_METERS,
        METERS_TO_FEET,
        blender_rotation_to_msfs_pbh,
        format_coordinate_float,
        msfs_pbh_to_blender_rotation,
    )

logger = logging.getLogger(__name__)

LIGHTS_COLLECTION_NAME = "MSFS_Spatial_Lights"
PARENT_COLLECTION_NAME = "MSFS_Spatial_Config"


def get_or_create_lights_collection(context: Any) -> Optional[Collection]:
    """Finds or creates the dedicated MSFS_Spatial_Lights collection in the active scene."""
    if not bpy:
        return None

    scene = context.scene
    parent_col = bpy.data.collections.get(PARENT_COLLECTION_NAME)
    if not parent_col:
        parent_col = bpy.data.collections.new(PARENT_COLLECTION_NAME)
        scene.collection.children.link(parent_col)

    lights_col = bpy.data.collections.get(LIGHTS_COLLECTION_NAME)
    if not lights_col:
        lights_col = bpy.data.collections.new(LIGHTS_COLLECTION_NAME)
        parent_col.children.link(lights_col)
    elif lights_col.name not in parent_col.children:
        try:
            parent_col.children.link(lights_col)
        except RuntimeError:
            pass

    return lights_col


class OMNIMESH_OT_import_msfs_lights(Operator):
    """Parses [LIGHTS] from systems.cfg or light.cfg and spawns visual Point and Spot lights."""

    bl_idname = "omnimesh.import_msfs_lights"
    bl_label = "Import MSFS Lights"
    bl_description = "Parse [LIGHTS] from systems.cfg or light.cfg and spawn visual Point/Spot lights"
    bl_options = {"REGISTER", "UNDO"}

    filepath: Any = (
        bpy.props.StringProperty(
            name="File Path",
            description="Path to systems.cfg or light.cfg",
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

        props = getattr(context.scene, "lod_tool", None)
        if props and getattr(props, "msfs_systems_cfg_path", None) and os.path.isfile(props.msfs_systems_cfg_path):
            self.filepath = props.msfs_systems_cfg_path
        elif props and getattr(props, "msfs_spatial_cfg_path", None) and os.path.isfile(props.msfs_spatial_cfg_path):
            folder = os.path.dirname(props.msfs_spatial_cfg_path)
            candidate = os.path.join(folder, "systems.cfg")
            if os.path.isfile(candidate):
                self.filepath = candidate

        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        target_file = self.filepath.strip()
        props = getattr(context.scene, "lod_tool", None)

        if not target_file and props and getattr(props, "msfs_systems_cfg_path", None):
            target_file = props.msfs_systems_cfg_path.strip()

        if not target_file or not os.path.isfile(target_file):
            self.report({"ERROR"}, "Please select a valid systems.cfg or light.cfg file.")
            return {"CANCELLED"}

        try:
            config = MSFSCSTParser.parse_file(target_file)
        except Exception as exc:
            logger.error("Failed to parse MSFS lights config %s: %s", target_file, exc)
            self.report({"ERROR"}, f"Failed parsing config: {exc}")
            return {"CANCELLED"}

        if not config.lights:
            self.report({"WARNING"}, f"No [LIGHTS] definitions found in {os.path.basename(target_file)}.")
            return {"CANCELLED"}

        lights_col = get_or_create_lights_collection(context)
        if not lights_col:
            self.report({"ERROR"}, "Failed to access lights collection.")
            return {"CANCELLED"}

        # Find MSFS_Datum empty in scene for airframe-relative lights
        datum_empty = bpy.data.objects.get("MSFS_Datum")

        count = 0
        for light in config.lights:
            self._ensure_light_object(
                col=lights_col,
                light=light,
                datum_empty=datum_empty,
                context=context,
            )
            count += 1

        if props:
            props.msfs_systems_cfg_path = target_file
            props.msfs_spatial_status = f"Imported {count} lights"

        self.report(
            {"INFO"},
            f"Successfully imported {count} lights from {os.path.basename(target_file)}",
        )
        return {"FINISHED"}

    def _ensure_light_object(
        self,
        col: Collection,
        light: LightPoint,
        datum_empty: Optional[Object],
        context: Any,
    ) -> Object:
        """Idempotently creates or updates a Blender Light object with accurate optics."""
        existing = None
        for obj in col.objects:
            if obj.get("msfs_id") == light.point_id:
                existing = obj
                break

        light_data_type = "POINT"
        energy = 50.0
        color = (1.0, 1.0, 1.0)
        spot_size_rad = math.radians(45.0)

        # 1. Optical Properties based on MSFS Light Type
        if light.light_type in (5, 6):  # 5=Landing, 6=Taxi
            light_data_type = "SPOT"
            energy = 1000.0 if light.light_type == 5 else 500.0
            color = (1.0, 0.98, 0.90)
            spot_size_rad = math.radians(35.0 if light.light_type == 5 else 55.0)
        elif light.light_type == 3:  # Navigation
            light_data_type = "POINT"
            energy = 40.0
            # Color by lateral offset: +X Green, -X Red, Center/Aft White
            lat_ft = light.coords_msfs_rel_ft[1]
            if lat_ft > 0.5:
                color = (0.0, 1.0, 0.15)  # Starboard Green
            elif lat_ft < -0.5:
                color = (1.0, 0.05, 0.05)  # Port Red
            else:
                color = (1.0, 1.0, 1.0)  # Tail White
        elif light.light_type == 2:  # Strobe
            light_data_type = "POINT"
            energy = 250.0
            color = (1.0, 1.0, 1.0)
        elif light.light_type == 1:  # Beacon
            light_data_type = "POINT"
            energy = 100.0
            color = (1.0, 0.05, 0.0)  # Red Beacon

        light_name = f"MSFS_Light_{light.light_type}_{light.light_index}"
        if light.em_mesh:
            light_name = f"MSFS_Light_{light.em_mesh}"

        if existing and existing.type == "LIGHT":
            light_obj = existing
            light_data = light_obj.data
            if light_data.type != light_data_type:
                light_data.type = light_data_type
        else:
            light_data = bpy.data.lights.new(name=light_name, type=light_data_type)
            light_obj = bpy.data.objects.new(name=light_name, object_data=light_data)
            col.objects.link(light_obj)

        light_data.energy = energy
        light_data.color = color
        if light_data_type == "SPOT":
            light_data.spot_size = spot_size_rad
            light_data.spot_blend = 0.2

        # 2. Rotation & Orientation
        if light_data_type == "SPOT":
            pbh = light.rotation_pbh_deg
            euler_rot = msfs_pbh_to_blender_rotation(pbh[0], pbh[1], pbh[2])
            light_obj.rotation_euler = euler_rot

        # 3. Parenting & Location
        # Check for EmMesh node-relative attachment
        parent_node: Optional[Object] = None
        if light.em_mesh:
            parent_node = bpy.data.objects.get(light.em_mesh)

        target_parent = parent_node or datum_empty
        if target_parent and light_obj.parent != target_parent:
            light_obj.parent = target_parent

        # Position in parent local space
        rel = light.coords_msfs_rel_ft
        local_m = (
            rel[1] * FEET_TO_METERS,
            rel[0] * FEET_TO_METERS,
            rel[2] * FEET_TO_METERS,
        )
        light_obj.location = local_m

        # Custom Properties
        light_obj["msfs_id"] = light.point_id
        light_obj["msfs_section"] = light.section
        light_obj["msfs_key"] = light.key
        light_obj["msfs_type"] = "LIGHT"
        light_obj["msfs_light_type"] = light.light_type
        light_obj["msfs_light_index"] = light.light_index
        light_obj["msfs_em_mesh"] = light.em_mesh

        return light_obj


class OMNIMESH_OT_export_msfs_lights(Operator):
    """Syncs modified Blender light positions and orientations back to systems.cfg / light.cfg."""

    bl_idname = "omnimesh.export_msfs_lights"
    bl_label = "Sync Lights to CFG"
    bl_description = "Sync modified Blender lights losslessly back to systems.cfg / light.cfg with automatic backup"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        props = getattr(context.scene, "lod_tool", None)
        return bool(
            props and getattr(props, "msfs_systems_cfg_path", None) and os.path.isfile(props.msfs_systems_cfg_path)
        )

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        cfg_path = getattr(props, "msfs_systems_cfg_path", "")
        if not cfg_path or not os.path.isfile(cfg_path):
            self.report({"ERROR"}, "No valid systems.cfg or light.cfg selected.")
            return {"CANCELLED"}

        try:
            config = MSFSCSTParser.parse_file(cfg_path)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed reading source config: {exc}")
            return {"CANCELLED"}

        lights_col = bpy.data.collections.get(LIGHTS_COLLECTION_NAME)
        if not lights_col:
            self.report({"ERROR"}, f"Collection '{LIGHTS_COLLECTION_NAME}' not found.")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()
        updated_coords: dict[str, tuple[float, float, float]] = {}
        updated_rotations: dict[str, tuple[float, float, float]] = {}

        # Scan for existing and new mirrored lights
        for obj in lights_col.objects:
            point_id = str(obj.get("msfs_id", ""))
            if not point_id or not point_id.startswith("LIGHTS:"):
                continue

            eval_obj = obj.evaluated_get(depsgraph)

            # Local coordinates relative to parent (datum or em_mesh)
            rel_long = obj.location.y * METERS_TO_FEET
            rel_lat = obj.location.x * METERS_TO_FEET
            rel_vert = obj.location.z * METERS_TO_FEET
            coords_ft = (rel_long, rel_lat, rel_vert)

            # Check rotation if spot light
            rot_pbh = (0.0, 0.0, 0.0)
            if eval_obj.type == "LIGHT" and getattr(eval_obj.data, "type", "") == "SPOT":
                euler = eval_obj.rotation_euler
                rot_pbh = blender_rotation_to_msfs_pbh(euler.x, euler.y, euler.z)

            # Check if this is a newly spawned mirrored light
            if point_id.endswith("_MIRRORED"):
                base_key = str(obj.get("msfs_key", "lightdef.99")).replace("_mir", "")
                # Find highest unused index
                existing_indices = [
                    int(re.search(r"\d+", r.key).group(0))
                    for r in config.lines
                    if r.section == "LIGHTS" and re.search(r"\d+", r.key)
                ]
                next_idx = max(existing_indices) + 1 if existing_indices else len(config.lights)
                new_key = f"lightdef.{next_idx}"
                actual_point_id = f"LIGHTS:{new_key}"

                s_long = format_coordinate_float(coords_ft[0])
                s_lat = format_coordinate_float(coords_ft[1])
                s_vert = format_coordinate_float(coords_ft[2])
                s_p = format_coordinate_float(rot_pbh[0])
                s_b = format_coordinate_float(rot_pbh[1])
                s_h = format_coordinate_float(rot_pbh[2])

                light_type = str(obj.get("msfs_light_type", 3))
                em_mesh = str(obj.get("msfs_em_mesh", ""))
                em_tag = f"#EmMesh:{em_mesh}" if em_mesh else ""

                raw_line = (
                    f"{new_key} = Type:{light_type}#Index:{next_idx}#LocalPosition:{s_long},{s_lat},{s_vert}"
                    f"#LocalRotation:{s_p},{s_b},{s_h}{em_tag}\n"
                )

                new_record = CFGLineRecord(
                    raw_line=raw_line,
                    section="LIGHTS",
                    key=new_key,
                    coordinates=coords_ft,
                    rotation=rot_pbh,
                    raw_tags={
                        "Type": light_type,
                        "Index": str(next_idx),
                        "LocalPosition": f"{s_long},{s_lat},{s_vert}",
                        "LocalRotation": f"{s_p},{s_b},{s_h}",
                    },
                    is_spatial=True,
                )
                MSFSCSTParser.insert_record_into_section(config, "LIGHTS", new_record, after_key=base_key)

                # Update Blender object properties to canonical ID
                obj["msfs_id"] = actual_point_id
                obj["msfs_key"] = new_key
                point_id = actual_point_id

            updated_coords[point_id] = coords_ft
            updated_rotations[point_id] = rot_pbh

        if not updated_coords:
            self.report({"WARNING"}, "No lights found to synchronize.")
            return {"CANCELLED"}

        try:
            backup_path = MSFSCSTParser.serialize_and_save(
                config,
                updated_points=updated_coords,
                updated_rotations=updated_rotations,
                target_path=cfg_path,
            )
        except Exception as exc:
            logger.error("Failed writing lights back to %s: %s", cfg_path, exc)
            self.report({"ERROR"}, f"Failed saving lights: {exc}")
            return {"CANCELLED"}

        backup_name = os.path.basename(backup_path)
        props.msfs_spatial_status = f"Synced {len(updated_coords)} lights (Backup: {backup_name})"
        self.report(
            {"INFO"},
            f"Synced {len(updated_coords)} lights to {os.path.basename(cfg_path)} (Backup: {backup_name})",
        )
        return {"FINISHED"}


classes = (
    OMNIMESH_OT_import_msfs_lights,
    OMNIMESH_OT_export_msfs_lights,
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
