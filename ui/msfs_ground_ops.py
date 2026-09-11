"""
MSFS Airframe Geometry & Ground Level Alignment Operators.
Provides operators for auto-generating Class 2 scrape points and aligning
landing gear contact points to tire contact patches with static CG height calculation.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import numpy as np

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
    from ..core.msfs_geometry import (
        collect_airframe_vertices,
        detect_airframe_extrema,
        extract_world_vertices_numpy,
        format_class_2_scrape_tokens,
    )
    from ..core.msfs_transforms import METERS_TO_FEET
    from .msfs_spatial_ops import (
        COLLECTION_NAME,
        DATUM_POINT_ID,
        find_spatial_collection,
        get_or_create_spatial_collection,
    )
except (ImportError, ValueError):
    from core.msfs_cst_parser import MSFSCSTParser
    from core.msfs_geometry import (
        collect_airframe_vertices,
        detect_airframe_extrema,
        extract_world_vertices_numpy,
        format_class_2_scrape_tokens,
    )
    from core.msfs_transforms import METERS_TO_FEET
    from ui.msfs_spatial_ops import (
        COLLECTION_NAME,
        DATUM_POINT_ID,
        find_spatial_collection,
        get_or_create_spatial_collection,
    )

logger = logging.getLogger(__name__)


class OMNIMESH_OT_generate_msfs_scrape_points(Operator):
    """Automatically analyzes airframe mesh geometry to detect extreme boundary points for Class 2 scrape points."""

    bl_idname = "omnimesh.generate_msfs_scrape_points"
    bl_label = "Auto-Generate Scrape Points"
    bl_description = "Vectorized geometry analysis to compute Wingtips, Nose, Tail, Keel, and Fin scrape points"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        margin_m = getattr(props, "msfs_scrape_margin_m", 0.0) if props else 0.0
        margin_ft = margin_m * METERS_TO_FEET

        # 1. Determine candidate mesh objects from selection or scene LOD0 meshes
        mesh_objs: list[Object] = [obj for obj in context.selected_objects if obj.type == "MESH"]

        if not mesh_objs:
            # Fallback: scan all scene mesh objects
            mesh_objs = [obj for obj in context.scene.objects if obj.type == "MESH"]

        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects found in scene to analyze.")
            return {"CANCELLED"}

        # 2. Extract airframe vertices with semantic exclusion
        depsgraph = context.evaluated_depsgraph_get()
        verts = collect_airframe_vertices(mesh_objs, depsgraph=depsgraph, filter_non_structural=True)

        if verts.shape[0] < 4:
            self.report({"ERROR"}, "Insufficient airframe vertices found after filtering.")
            return {"CANCELLED"}

        # 3. Detect extrema in world meters
        try:
            extrema = detect_airframe_extrema(verts)
        except Exception as exc:
            self.report({"ERROR"}, f"Extrema detection failed: {exc}")
            return {"CANCELLED"}

        # 4. Resolve Datum Empty in collection
        col = get_or_create_spatial_collection(context)
        if not col:
            self.report({"ERROR"}, "Could not access spatial markers collection.")
            return {"CANCELLED"}

        datum_empty: Optional[Object] = None
        for obj in col.objects:
            if obj.get("msfs_id") == DATUM_POINT_ID:
                datum_empty = obj
                break

        datum_world_m = datum_empty.matrix_world.translation if datum_empty else None

        # 5. Determine next contiguous point.N index
        existing_indices: list[int] = []
        for obj in col.objects:
            key = str(obj.get("msfs_key", ""))
            if key.startswith("point."):
                try:
                    idx = int(key.split(".")[1])
                    existing_indices.append(idx)
                except (ValueError, IndexError):
                    pass

        next_idx = max(existing_indices) + 1 if existing_indices else 0

        # 6. Create or update Empties for detected scrape features
        created_count = 0
        for name_tag, world_pos in extrema.items():
            # Check if empty already exists with this name_tag
            target_empty: Optional[Object] = None
            for obj in col.objects:
                if obj.get("msfs_name_tag") == name_tag:
                    target_empty = obj
                    break

            # Local position relative to datum
            if datum_world_m:
                local_pos_m = (
                    world_pos[0] - datum_world_m.x,
                    world_pos[1] - datum_world_m.y,
                    world_pos[2] - datum_world_m.z,
                )
            else:
                local_pos_m = world_pos

            point_key = str(target_empty.get("msfs_key")) if target_empty else f"point.{next_idx}"
            if not target_empty:
                next_idx += 1
                empty_name = f"MSFS_CONT_{name_tag}"
                target_empty = bpy.data.objects.new(empty_name, None)
                col.objects.link(target_empty)
                if datum_empty:
                    target_empty.parent = datum_empty

            if target_empty is None:
                continue

            target_empty.location = local_pos_m
            target_empty.empty_display_type = "PLAIN_AXES"
            target_empty.empty_display_size = 0.2

            # Store Class 2 metadata and raw tokens
            coords_ft = (
                local_pos_m[1] * METERS_TO_FEET,
                local_pos_m[0] * METERS_TO_FEET,
                local_pos_m[2] * METERS_TO_FEET,
            )
            raw_tokens = format_class_2_scrape_tokens(name_tag, coords_ft, margin_ft=margin_ft)

            target_empty["msfs_id"] = f"CONTACT_POINTS:{point_key}"
            target_empty["msfs_section"] = "CONTACT_POINTS"
            target_empty["msfs_key"] = point_key
            target_empty["msfs_type"] = "CONTACT_POINT"
            target_empty["msfs_class"] = 2
            target_empty["msfs_name_tag"] = name_tag
            target_empty["msfs_raw_tokens"] = raw_tokens
            target_empty["msfs_name_tag_fmt"] = f"Name:{name_tag}#Properties:"

            created_count += 1

        if props:
            props.msfs_spatial_status = f"Generated {created_count} scrape points"

        self.report({"INFO"}, f"Generated {created_count} scrape points across {len(mesh_objs)} airframe objects.")
        return {"FINISHED"}


class OMNIMESH_OT_align_gear_ground_level(Operator):
    """Snaps landing gear contact points to tire contact patch and calculates static_cg_height."""

    bl_idname = "omnimesh.align_gear_ground_level"
    bl_label = "Align Gear to Ground Level"
    bl_description = "Snaps gear wheel contact points to lowest tire vertices and updates static_cg_height in CFG"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        return True

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        cfg_path = props.msfs_spatial_cfg_path if props else ""
        gear_state = getattr(props, "msfs_gear_state", "STATIC_COMPRESSED") if props else "STATIC_COMPRESSED"
        compression_m = getattr(props, "msfs_gear_compression_m", 0.12) if props else 0.12

        col = find_spatial_collection(context) or bpy.data.collections.get(COLLECTION_NAME)
        if not col:
            self.report({"ERROR"}, "Spatial collection not found.")
            return {"CANCELLED"}

        # 1. Identify Wheel (Class 1) contact points
        wheel_empties: list[Object] = [
            obj for obj in col.objects if obj.get("msfs_type") == "CONTACT_POINT" and obj.get("msfs_class") == 1
        ]

        if not wheel_empties:
            self.report({"WARNING"}, "No Class 1 (Wheel) contact points found.")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()

        # 2. For each wheel empty, find nearest tire mesh and snap to lowest vertex
        all_meshes = [obj for obj in context.scene.objects if obj.type == "MESH"]
        lowest_contact_z_world: list[float] = []

        for empty in wheel_empties:
            empty_world = empty.matrix_world.translation

            # Find nearest mesh to this wheel empty
            best_mesh: Optional[Object] = None
            min_dist_sq = float("inf")

            for mesh_obj in all_meshes:
                mesh_pos = mesh_obj.matrix_world.translation
                dist_sq = (mesh_pos - empty_world).length_squared
                if dist_sq < min_dist_sq:
                    min_dist_sq = dist_sq
                    best_mesh = mesh_obj

            if best_mesh:
                verts = extract_world_vertices_numpy(best_mesh, depsgraph=depsgraph)
                if verts.shape[0] > 0:
                    # Filter vertices in close lateral/longitudinal radius of the wheel (within 0.6m)
                    dx = verts[:, 0] - empty_world.x
                    dy = verts[:, 1] - empty_world.y
                    r_sq = dx**2 + dy**2
                    local_tire_verts = verts[r_sq <= 0.6**2]

                    if local_tire_verts.shape[0] > 0:
                        lowest_z = float(np.min(local_tire_verts[:, 2]))
                    else:
                        lowest_z = float(np.min(verts[:, 2]))

                    # Snap empty Z to contact patch
                    if empty.parent:
                        parent_inv = empty.parent.matrix_world.inverted()
                        new_world = (empty_world.x, empty_world.y, lowest_z)
                        empty.location = (
                            parent_inv @ bpy.types.Vector(new_world)
                            if hasattr(bpy.types, "Vector")
                            else (empty.location.x, empty.location.y, lowest_z)
                        )
                    else:
                        empty.location.z = lowest_z

                    lowest_contact_z_world.append(lowest_z)

        # 3. Check for CG Empty to calculate static_cg_height
        cg_empty: Optional[Object] = None
        for obj in col.objects:
            if obj.get("msfs_type") == "CG":
                cg_empty = obj
                break

        if lowest_contact_z_world and cg_empty:
            ground_plane_z = float(np.mean(lowest_contact_z_world))
            cg_world_z = cg_empty.matrix_world.translation.z

            # Ground height in static equilibrium
            if gear_state == "UNCOMPRESSED_EXTENDED":
                effective_ground_z = ground_plane_z + compression_m
            else:
                effective_ground_z = ground_plane_z

            cg_height_m = max(0.0, cg_world_z - effective_ground_z)
            cg_height_ft = cg_height_m * METERS_TO_FEET

            if props:
                props.msfs_calculated_cg_height_ft = cg_height_ft

            # Update static_cg_height in flight_model.cfg if file is set
            if cfg_path and os.path.isfile(cfg_path):
                try:
                    config = MSFSCSTParser.parse_file(cfg_path)
                    val_str = f"{cg_height_ft:.2f}"
                    backup_path = MSFSCSTParser.update_scalar_param(
                        config=config,
                        section="CONTACT_POINTS",
                        key="static_cg_height",
                        value_str=val_str,
                    )
                    backup_name = os.path.basename(str(backup_path))
                    if props:
                        props.msfs_spatial_status = f"Updated static_cg_height = {val_str} ft (Backup: {backup_name})"
                    self.report({"INFO"}, f"Updated static_cg_height = {val_str} ft in {os.path.basename(cfg_path)}")
                except Exception as exc:
                    logger.error("Failed updating static_cg_height in %s: %s", cfg_path, exc)
                    self.report({"WARNING"}, f"Ground aligned, but failed writing static_cg_height: {exc}")
            else:
                self.report({"INFO"}, f"Aligned wheels to ground. Calculated static_cg_height = {cg_height_ft:.2f} ft.")
        else:
            self.report({"INFO"}, f"Aligned {len(wheel_empties)} gear contact points to tire contact patch.")

        return {"FINISHED"}


classes = (
    OMNIMESH_OT_generate_msfs_scrape_points,
    OMNIMESH_OT_align_gear_ground_level,
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
