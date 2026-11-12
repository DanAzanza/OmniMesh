"""
OmniMesh In-Blender Preview & Test Rig System for Octahedral Impostors.
Blender 5.0+ & 5.2 LTS Compatible.

Constructs native dynamic shader node networks for in-viewport octahedral tile decoding,
camera tracking constraints, and occlusion-free comparison turntables with zero production
transform pollution.
"""

from __future__ import annotations

import logging
import math
import os
from typing import TYPE_CHECKING, Any, Optional, Sequence, cast

from .impostor_preview_material import (
    create_octahedral_preview_material,
    safe_load_image,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    import mathutils
    from mathutils import Matrix, Vector
else:
    try:
        import bpy
        import mathutils
        from mathutils import Matrix, Vector
    except ImportError:
        bpy = None
        mathutils = None
        from .compat import Vector  # type: ignore

        Matrix = None  # type: ignore
    BlendData = object  # runtime fallback for type annotations


def _resolve_scene(context: bpy.types.Context | None, blend_data: BlendData) -> bpy.types.Scene | None:
    if context and context.scene:
        return context.scene
    if blend_data and len(blend_data.scenes) > 0:
        return blend_data.scenes[0]
    return None


def setup_impostor_tracking(
    proxy_obj: bpy.types.Object | None,
    camera_obj: Optional[bpy.types.Object] = None,
    context: bpy.types.Context | None = None,
    *,
    blend_data: BlendData,
) -> Optional[bpy.types.Constraint]:
    """
    Configures a TRACK_TO constraint on the proxy quad to orient continuously toward the camera.
    """
    if not bpy or not proxy_obj or proxy_obj.constraints is None:
        return None

    effective_bdata = blend_data
    sc = _resolve_scene(context, effective_bdata)
    cam = camera_obj or (sc.camera if sc else None)
    if not cam:
        return None

    # Find or create TRACK_TO constraint
    track_c = cast(
        "bpy.types.TrackToConstraint",
        next((c for c in proxy_obj.constraints if c.type == "TRACK_TO"), None)
        or proxy_obj.constraints.new(type="TRACK_TO"),
    )

    track_c.name = "OmniMesh_Preview_Track"
    track_c.target = cam
    track_c.track_axis = "TRACK_NEGATIVE_Y"
    track_c.up_axis = "UP_Z"
    return track_c


def setup_preview_turntable(
    cam_obj: bpy.types.Object | None,
    target_center: Sequence[float] | Vector,
    radius: float,
    height: float,
    num_frames: int = 72,
    context: bpy.types.Context | None = None,
    *,
    blend_data: BlendData,
) -> bool:
    """
    Keyframes an elevated circular camera orbit around target_center over frames 1..num_frames.
    Dynamically updates the world-space view ray (-Incoming) on every frame so the shader
    samples matching octahedral tiles while preventing lateral occlusion.
    Leaves mesh_objs completely un-animated and preserves production transforms.
    """
    if not bpy or not cam_obj:
        return False

    effective_bdata = blend_data
    scene = _resolve_scene(context, effective_bdata)
    if not scene:
        return False
    scene.frame_start = 1
    scene.frame_end = num_frames

    if cam_obj.animation_data:
        cam_obj.animation_data_clear()

    center_vec = Vector((target_center[0], target_center[1], target_center[2])) if Vector else target_center

    for f in range(1, num_frames + 1):
        scene.frame_set(f)
        angle = (f - 1) / float(num_frames) * 2.0 * math.pi
        cam_x = center_vec[0] + radius * math.sin(angle)
        cam_y = center_vec[1] - radius * math.cos(angle)
        cam_z = center_vec[2] + height

        cam_loc = Vector((cam_x, cam_y, cam_z)) if Vector else (cam_x, cam_y, cam_z)
        cam_obj.location = cam_loc

        dir_vec = cast("Vector", center_vec) - cast("Vector", cam_loc)
        if mathutils is not None:
            cam_obj.rotation_euler = dir_vec.to_track_quat("-Z", "Y").to_euler()

        cam_obj.keyframe_insert(data_path="location", frame=f)
        cam_obj.keyframe_insert(data_path="rotation_euler", frame=f)

    # Set linear interpolation on camera fcurves
    if cam_obj.animation_data and cam_obj.animation_data.action:
        try:
            fcurves = cast("Any", cam_obj.animation_data.action).fcurves
        except AttributeError:
            fcurves = ()
        for fcurve in fcurves or ():
            for kp in fcurve.keyframe_points or ():
                kp.interpolation = "LINEAR"

    scene.frame_set(1)
    return True


def setup_impostor_preview_rig(
    context: bpy.types.Context | None,
    mesh_objs: list[bpy.types.Object],
    base_name: str,
    texture_dir: str,
    mode: str = "SIDE_BY_SIDE",
    num_frames: int = 72,
    target_engine: str = "UE5",
    create_turntable: bool = False,
    *,
    blend_data: BlendData,
) -> dict[str, Any]:
    """
    Constructs an isolated, complete In-Blender preview test rig for Octahedral Impostors.
    Places all temporary objects in a dedicated '{base_name}_Preview_Rig' collection.
    Never alters the production transforms of mesh_objs.
    """
    if not bpy or blend_data is None:
        return {}

    effective_bdata = blend_data
    scene = _resolve_scene(context, effective_bdata)
    if not scene:
        return {}
    rig_coll_name = f"{base_name}_Preview_Rig"

    # 1. Manage dedicated collection
    rig_coll = effective_bdata.collections.get(rig_coll_name)
    if not rig_coll:
        rig_coll = effective_bdata.collections.new(rig_coll_name)
        if scene.collection and scene.collection.children is not None:
            scene.collection.children.link(rig_coll)

    if not rig_coll:
        return {}

    # 2. Compute bounding parameters
    coords = []
    for obj in mesh_objs:
        mat_w = obj.matrix_world
        try:
            bbox = obj.bound_box
        except AttributeError:
            bbox = ()
        for c in bbox or ():
            v = Vector(c)
            try:
                res = mat_w @ v if mat_w is not None else v
                coords.append(res if isinstance(res.x, (int, float)) else v)
            except (TypeError, ValueError, AttributeError, RuntimeError):
                coords.append(v)
    if not coords:
        coords = [Vector((-1.0, -1.0, -1.0)), Vector((1.0, 1.0, 1.0))]

    min_b = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    max_b = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    center = (min_b + max_b) * 0.5
    radius = max((max_b - min_b).length * 0.5, 0.5)

    # 3. Locate baked textures
    base_color_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_BaseColor.png")
    if not os.path.exists(base_color_file):
        for obj in mesh_objs:
            obj_n = obj.name or ""
            for candidate in (obj_n, obj_n.split("_")[0]):
                cand_clean = candidate.split("_LOD")[0].split("_Test")[0]
                alt_base = os.path.join(texture_dir, f"T_{cand_clean}_Impostor_BaseColor.png")
                if os.path.exists(alt_base):
                    base_name, base_color_file = cand_clean, alt_base
                    break
            if os.path.exists(base_color_file):
                break
    normal_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_Normal.png")
    orm_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_ORM.png")

    if not os.path.exists(base_color_file):
        logger.warning("Preview rig could not find BaseColor atlas: %s", base_color_file)
        return {}

    # 4. Create preview billboard quad
    proxy_name = f"{base_name}_Preview_Impostor"
    proxy_obj = effective_bdata.objects.get(proxy_name)
    if not proxy_obj:
        mesh_data = effective_bdata.meshes.new(f"{proxy_name}_Mesh")
        s = radius * 2.08
        hs = s * 0.5
        verts = [(-hs, 0.0, -hs), (hs, 0.0, -hs), (hs, 0.0, hs), (-hs, 0.0, hs)]
        faces = [(0, 1, 2, 3)]
        mesh_data.from_pydata(verts, [], faces)
        mesh_data.update()

        # Add UV layer
        uv_layer = mesh_data.uv_layers.new(name="UVMap")
        uv_coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        if uv_layer is not None:
            for loop in mesh_data.loops:
                uv_layer.data[loop.index].uv = uv_coords[loop.vertex_index]

        proxy_obj = effective_bdata.objects.new(proxy_name, mesh_data)
        rig_coll.objects.link(proxy_obj)

    if not proxy_obj:
        return {}

    # Position proxy
    offset_x = radius * 2.8 if mode == "SIDE_BY_SIDE" else 0.0
    proxy_obj.location = Vector((center.x + offset_x, center.y, center.z))

    # 5. Build and assign preview material
    mat_name = f"M_{base_name}_Octahedral_Preview"
    preview_mat = create_octahedral_preview_material(
        mat_name=mat_name,
        base_color_path=base_color_file,
        normal_path=normal_file if os.path.exists(normal_file) else None,
        orm_path=orm_file if os.path.exists(orm_file) else None,
        grid_size=8,
        target_engine=target_engine,
        blend_data=effective_bdata,
    )
    if preview_mat:
        proxy_data = cast("bpy.types.Mesh", proxy_obj.data)
        proxy_data.materials.clear()
        proxy_data.materials.append(preview_mat)

    # 6. Setup dedicated preview camera
    cam_name = f"{base_name}_Preview_Camera"
    cam_obj = effective_bdata.objects.get(cam_name)
    if not cam_obj:
        cam_data = effective_bdata.cameras.new(f"{cam_name}_Data")
        cam_data.lens = 50
        cam_obj = effective_bdata.objects.new(cam_name, cam_data)
        rig_coll.objects.link(cam_obj)

    if not cam_obj:
        return {}

    cam_dist = radius * 5.6
    cam_x = center.x + (offset_x * 0.5 if mode == "SIDE_BY_SIDE" else 0.0)
    cam_obj.location = Vector((cam_x, center.y - cam_dist, center.z + radius * 0.5))
    aim_target = Vector((cam_x, center.y, center.z))
    dir_cam = aim_target - cam_obj.location
    if mathutils is not None:
        cam_obj.rotation_euler = dir_cam.to_track_quat("-Z", "Y").to_euler()

    # Create Tracker Target Empty to decouple billboard orientation from camera animation
    target_name = f"{base_name}_Preview_Tracker_Target"
    target_empty = effective_bdata.objects.get(target_name)
    if not target_empty:
        target_empty = effective_bdata.objects.new(target_name, None)
        target_empty.empty_display_type = "PLAIN_AXES"
        target_empty.empty_display_size = 0.2
        rig_coll.objects.link(target_empty)
    if target_empty:
        target_empty.location = cam_obj.location.copy()

    # Track constraint on proxy targets the Empty
    setup_impostor_tracking(proxy_obj, target_empty, context=context, blend_data=effective_bdata)

    # 7. Setup preview sun light for normal map lighting validation
    sun_name = f"{base_name}_Preview_Sun"
    sun_obj = effective_bdata.objects.get(sun_name)
    if not sun_obj:
        sun_data = cast("bpy.types.SunLight", effective_bdata.lights.new(name=f"{sun_name}_Data", type="SUN"))
        sun_data.energy = 3.0
        sun_obj = effective_bdata.objects.new(sun_name, sun_data)
        rig_coll.objects.link(sun_obj)
        sun_obj.location = Vector((center.x + 5.0, center.y - 5.0, center.z + 10.0))
        sun_obj.rotation_euler = (0.7, 0.2, 0.5)

    # 8. Setup elevated camera turntable animation (only if explicitly requested)
    if create_turntable:
        setup_preview_turntable(
            cam_obj=cam_obj,
            target_center=aim_target,
            radius=cam_dist,
            height=radius * 2.2,
            num_frames=num_frames,
            context=context,
            blend_data=effective_bdata,
        )

    # Set active camera
    scene.camera = cam_obj

    return {
        "collection": rig_coll_name,
        "proxy_object": proxy_name,
        "camera_object": cam_name,
        "material": mat_name,
    }


def teardown_impostor_preview_rig(
    context: bpy.types.Context | None,
    base_name: str,
    *,
    blend_data: BlendData,
) -> bool:
    """
    Cleanly destroys all preview rig elements and removes the '{base_name}_Preview_Rig' collection.
    Restores original camera and removes animation data from mesh objects.
    """
    if not bpy or blend_data is None:
        return False

    effective_bdata = blend_data
    rig_coll_name = f"{base_name}_Preview_Rig"
    rig_coll = effective_bdata.collections.get(rig_coll_name)
    if not rig_coll:
        return False

    # Capture objects and unshared datablocks
    for obj in list(rig_coll.objects):
        if obj.animation_data:
            obj.animation_data_clear()

        obj_data = obj.data
        try:
            effective_bdata.objects.remove(obj, do_unlink=True)
        except (TypeError, RuntimeError):
            effective_bdata.objects.remove(obj)

        # Deallocate orphaned datablocks
        users = obj_data.users if obj_data else 1
        if obj_data and isinstance(users, (int, float)) and users <= 1:
            try:
                if effective_bdata.meshes is not None and obj_data in effective_bdata.meshes.values():
                    effective_bdata.meshes.remove(cast("bpy.types.Mesh", obj_data))
                elif effective_bdata.cameras is not None and obj_data in effective_bdata.cameras.values():
                    effective_bdata.cameras.remove(cast("bpy.types.Camera", obj_data))
                elif effective_bdata.lights is not None and obj_data in effective_bdata.lights.values():
                    effective_bdata.lights.remove(cast("bpy.types.Light", obj_data))
            except (TypeError, RuntimeError, ValueError, AttributeError):
                pass

    # Remove collection
    effective_bdata.collections.remove(rig_coll)

    # Remove preview material
    mats = effective_bdata.materials
    if mats:
        mat = mats.get(f"M_{base_name}_Octahedral_Preview")
        if mat:
            mats.remove(mat)

    # Restore default active camera if possible
    scene = _resolve_scene(context, effective_bdata)
    cam = scene.camera if scene else None
    if cam and cam.name == f"{base_name}_Preview_Camera" and scene:
        scene.camera = next((o for o in scene.objects if o.type == "CAMERA"), None)

    return True


__all__ = [
    "create_octahedral_preview_material",
    "safe_load_image",
]
