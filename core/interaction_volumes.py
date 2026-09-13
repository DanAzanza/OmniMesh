"""
OmniMesh Multi-Engine Interaction Volumes & Clickspot Subsystem.
Spawns non-blocking trigger geometry (Box, Sphere, Cylinder) into isolated
collection {AssetName}_Interactions under {AssetName}_Config, with multi-engine
export tags for MSFS MouseRects, Unreal Engine Overlap Triggers, Unity MeshTriggers,
and Godot Area3D nodes.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    bmesh = None
    Matrix = None
    Vector = None

try:
    from .hierarchy import get_or_create_engine_import_collection
    from .material_presets import create_or_update_material_preset
except (ImportError, ValueError):
    from core.hierarchy import get_or_create_engine_import_collection
    from core.material_presets import create_or_update_material_preset


def get_engine_interaction_name(asset_name: str, role: str, name: str, engine: str = "GENERIC") -> str:
    """
    Computes engine-specific object and node identifiers to ensure non-blocking
    trigger semantics across all target engines.
    """
    clean_role = str(role).strip().upper() or "TRIGGER"
    clean_name = str(name).strip() or "Clickspot"
    eng_upper = str(engine).strip().upper()

    if "MSFS" in eng_upper:
        # MSFS MouseRect convention
        return f"Collision_{clean_role}_{clean_name}"
    elif "UE" in eng_upper or "UNREAL" in eng_upper:
        # Unreal Engine non-blocking gameplay trigger (never UCX_)
        return f"INTERACT_{clean_role}_{clean_name}"
    elif "GODOT" in eng_upper:
        # Godot Area3D non-blocking trigger suffix
        return f"{clean_name}_{clean_role}-areacol"
    elif "UNITY" in eng_upper:
        # Unity trigger volume naming
        return f"TRIGGER_{clean_role}_{clean_name}"
    return f"{asset_name}_{clean_role}_{clean_name}"


def create_interaction_volume(
    context: Any,
    asset_name: str,
    name: str = "Clickspot",
    shape: str = "BOX",
    role: str = "BUTTON",
    size: Sequence[float] = (0.08, 0.08, 0.08),
    parent_obj: Optional[Any] = None,
) -> Optional[Any]:
    """
    Spawns a lightweight non-blocking interaction trigger volume into {AssetName}_Interactions.

    Shapes:
        - BOX: Rectangular volume for buttons, levers, and entry portals.
        - SPHERE: Radial volume for knobs, dials, and omnidirectional sensors.
        - CYLINDER: Axial volume for throttles, levers, and handles.
    """
    if not bpy:
        return None

    clean_asset = str(asset_name).strip() or "Asset"
    clean_name = str(name).strip() or "Clickspot"
    shape_upper = str(shape).strip().upper()
    role_upper = str(role).strip().upper()

    sx = float(size[0]) if len(size) > 0 else 0.08
    sy = float(size[1]) if len(size) > 1 else 0.08
    sz = float(size[2]) if len(size) > 2 else 0.08

    obj_name = f"{clean_asset}_{role_upper}_{clean_name}"
    mesh_data = bpy.data.meshes.new(name=f"{obj_name}_Mesh")

    # Generate primitive wire geometry with bmesh
    if bmesh:
        bm = bmesh.new()
        try:
            if shape_upper == "SPHERE":
                radius = 0.5 * max(sx, sy, sz)
                bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=radius)
            elif shape_upper == "CYLINDER":
                radius = 0.5 * max(sx, sy)
                bmesh.ops.create_cone(
                    bm,
                    cap_ends=True,
                    cap_tris=False,
                    segments=12,
                    radius1=radius,
                    radius2=radius,
                    depth=sz,
                )
            else:
                # Default Box
                bmesh.ops.create_cube(bm, size=1.0)
                bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
            bm.to_mesh(mesh_data)
        finally:
            bm.free()

    obj = bpy.data.objects.new(obj_name, mesh_data)
    obj.display_type = "WIRE"
    obj.show_wire = True

    # Assign Invisible Collision material preset
    invis_mat = create_or_update_material_preset(
        material_name="Mat_OmniMesh_Invisible_Trigger",
        preset_type="INVISIBLE_COLLIDER",
    )
    if invis_mat:
        mesh_data.materials.append(invis_mat)

    # Multi-engine metadata properties
    obj["_omnimesh_role"] = "INTERACTION_VOLUME"
    obj["_omnimesh_interaction_role"] = role_upper
    obj["_omnimesh_interaction_shape"] = shape_upper
    obj["_is_trigger"] = True
    obj["msfs_interaction_name"] = get_engine_interaction_name(clean_asset, role_upper, clean_name, "MSFS")
    obj["ue5_trigger_name"] = get_engine_interaction_name(clean_asset, role_upper, clean_name, "UNREAL")
    obj["godot_trigger_name"] = get_engine_interaction_name(clean_asset, role_upper, clean_name, "GODOT")
    obj["unity_is_trigger"] = True

    # Link to isolated Interactions collection under {AssetName}_Config
    interact_col = get_or_create_engine_import_collection(context, clean_asset, "INTERACTIONS")
    if interact_col and hasattr(interact_col, "objects"):
        interact_col.objects.link(obj)
    elif context and hasattr(context, "scene") and hasattr(context.scene, "collection"):
        context.scene.collection.objects.link(obj)

    # Parenting to active control / prop
    if parent_obj and hasattr(parent_obj, "matrix_world"):
        obj.location = parent_obj.location
        obj.rotation_euler = parent_obj.rotation_euler
        obj.parent = parent_obj
        if hasattr(parent_obj, "matrix_world") and Matrix:
            try:
                obj.matrix_parent_inverse = parent_obj.matrix_world.inverted()
            except Exception as exc:
                logger.debug("Could not invert parent matrix for interaction volume: %s", exc)

    logger.info("Created interaction volume '%s' (Role: %s, Shape: %s)", obj.name, role_upper, shape_upper)
    return obj
