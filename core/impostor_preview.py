"""
OmniMesh In-Blender Preview & Test Rig System for Octahedral Impostors.
Blender 4.2+ and 5.0+ LTS Compatible.

Constructs native dynamic shader node networks for in-viewport octahedral tile decoding,
camera tracking constraints, and occlusion-free comparison turntables with zero production
transform pollution.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import bpy
    import mathutils
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    mathutils = None
    Vector = None  # type: ignore
    Matrix = None  # type: ignore


def safe_load_image(filepath: str) -> Optional[Any]:
    """
    Loads an image from filepath while preventing duplicate datablocks in Blender.
    Re-uses existing image if already loaded with matching absolute path.
    """
    if not bpy or not filepath or not os.path.exists(filepath):
        return None

    abs_target = os.path.abspath(filepath)
    for img in bpy.data.images:
        if img.filepath:
            existing_abs = os.path.abspath(bpy.path.abspath(img.filepath))
            if existing_abs == abs_target:
                try:
                    img.reload()
                except Exception as reload_err:
                    logger.debug("Failed reloading existing image %s: %s", filepath, reload_err)
                return img

    try:
        return bpy.data.images.load(filepath)
    except Exception as exc:
        logger.error("Failed loading image from %s: %s", filepath, exc)
        return None


def create_octahedral_preview_material(
    mat_name: str,
    base_color_path: str,
    normal_path: Optional[str] = None,
    orm_path: Optional[str] = None,
    grid_size: int = 8,
    target_engine: str = "UE5",
) -> Optional[Any]:
    """
    Constructs a native Blender Shader Node material that evaluates the upper-hemisphere
    octahedral projection dynamically on the GPU in real-time.

    Decodes `-Incoming` view ray into (u, v) atlas coordinates, selects the matching tile,
    and applies BaseColor cutout, Normal map (with DirectX Green-inversion compensation for UE5),
    and optional ORM roughness.
    """
    if not bpy:
        return None

    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
    mat.use_nodes = True

    # Defensive EEVEE Next & EEVEE Legacy transparency configuration
    if hasattr(mat, "surface_render_method"):
        try:
            mat.surface_render_method = "DITHERED"
        except Exception as exc:
            logger.debug("Failed setting surface_render_method on material: %s", exc)
    if hasattr(mat, "use_transparent_shadow"):
        try:
            mat.use_transparent_shadow = True
        except Exception as exc:
            logger.debug("Failed setting use_transparent_shadow on material: %s", exc)
    if hasattr(mat, "use_backface_culling"):
        try:
            mat.use_backface_culling = True
        except Exception as exc:
            logger.debug("Failed setting use_backface_culling on material: %s", exc)
    if hasattr(mat, "blend_method"):
        try:
            mat.blend_method = "CLIP"
        except Exception as exc:
            logger.debug("Failed setting blend_method on material: %s", exc)

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Output & Principled BSDF
    out_node = nodes.new(type="ShaderNodeOutputMaterial")
    out_node.location = (1400, 0)

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (1100, 0)
    links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    # 2. View Direction Vector: D = -Incoming
    geom = nodes.new(type="ShaderNodeNewGeometry")
    geom.location = (-1200, 200)

    neg_v = nodes.new(type="ShaderNodeVectorMath")
    neg_v.operation = "MULTIPLY"
    neg_v.inputs[1].default_value = (-1.0, -1.0, -1.0)
    neg_v.location = (-1000, 200)
    links.new(geom.outputs["Incoming"], neg_v.inputs[0])

    sep_v = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_v.location = (-800, 200)
    links.new(neg_v.outputs["Vector"], sep_v.inputs["Vector"])

    # 3. Hemi-Octahedral Projection Math
    # denom = abs(X) + abs(Y) + max(Z, 0.001)
    abs_x = nodes.new(type="ShaderNodeMath")
    abs_x.operation = "ABSOLUTE"
    abs_x.location = (-600, 400)
    links.new(sep_v.outputs["X"], abs_x.inputs[0])

    abs_y = nodes.new(type="ShaderNodeMath")
    abs_y.operation = "ABSOLUTE"
    abs_y.location = (-600, 250)
    links.new(sep_v.outputs["Y"], abs_y.inputs[0])

    max_z = nodes.new(type="ShaderNodeMath")
    max_z.operation = "MAXIMUM"
    max_z.inputs[1].default_value = 0.001
    max_z.location = (-600, 100)
    links.new(sep_v.outputs["Z"], max_z.inputs[0])

    add_xy = nodes.new(type="ShaderNodeMath")
    add_xy.operation = "ADD"
    add_xy.location = (-400, 350)
    links.new(abs_x.outputs["Value"], add_xy.inputs[0])
    links.new(abs_y.outputs["Value"], add_xy.inputs[1])

    denom = nodes.new(type="ShaderNodeMath")
    denom.operation = "ADD"
    denom.location = (-220, 350)
    links.new(add_xy.outputs["Value"], denom.inputs[0])
    links.new(max_z.outputs["Value"], denom.inputs[1])

    # nx = X / denom, ny = Y / denom
    nx = nodes.new(type="ShaderNodeMath")
    nx.operation = "DIVIDE"
    nx.location = (-40, 400)
    links.new(sep_v.outputs["X"], nx.inputs[0])
    links.new(denom.outputs["Value"], nx.inputs[1])

    ny = nodes.new(type="ShaderNodeMath")
    ny.operation = "DIVIDE"
    ny.location = (-40, 250)
    links.new(sep_v.outputs["Y"], ny.inputs[0])
    links.new(denom.outputs["Value"], ny.inputs[1])

    # u = (nx + ny) * 0.5 + 0.5
    add_nx_ny = nodes.new(type="ShaderNodeMath")
    add_nx_ny.operation = "ADD"
    add_nx_ny.location = (140, 400)
    links.new(nx.outputs["Value"], add_nx_ny.inputs[0])
    links.new(ny.outputs["Value"], add_nx_ny.inputs[1])

    u_coord = nodes.new(type="ShaderNodeMath")
    u_coord.operation = "MULTIPLY_ADD"
    u_coord.inputs[1].default_value = 0.5
    u_coord.inputs[2].default_value = 0.5
    u_coord.location = (320, 400)
    links.new(add_nx_ny.outputs["Value"], u_coord.inputs[0])

    # v = (nx - ny) * 0.5 + 0.5
    sub_nx_ny = nodes.new(type="ShaderNodeMath")
    sub_nx_ny.operation = "SUBTRACT"
    sub_nx_ny.location = (140, 250)
    links.new(nx.outputs["Value"], sub_nx_ny.inputs[0])
    links.new(ny.outputs["Value"], sub_nx_ny.inputs[1])

    v_coord = nodes.new(type="ShaderNodeMath")
    v_coord.operation = "MULTIPLY_ADD"
    v_coord.inputs[1].default_value = 0.5
    v_coord.inputs[2].default_value = 0.5
    v_coord.location = (320, 250)
    links.new(sub_nx_ny.outputs["Value"], v_coord.inputs[0])

    # 4. Grid Tile Coordinates: col = floor(u * N), row = floor(v * N)
    clamp_u = nodes.new(type="ShaderNodeMath")
    clamp_u.operation = "MULTIPLY"
    clamp_u.inputs[1].default_value = float(grid_size)
    clamp_u.location = (-600, -100)
    links.new(u_coord.outputs["Value"], clamp_u.inputs[0])

    col = nodes.new(type="ShaderNodeMath")
    col.operation = "FLOOR"
    col.location = (-400, -100)
    links.new(clamp_u.outputs["Value"], col.inputs[0])

    clamp_v = nodes.new(type="ShaderNodeMath")
    clamp_v.operation = "MULTIPLY"
    clamp_v.inputs[1].default_value = float(grid_size)
    clamp_v.location = (-600, -250)
    links.new(v_coord.outputs["Value"], clamp_v.inputs[0])

    row = nodes.new(type="ShaderNodeMath")
    row.operation = "FLOOR"
    row.location = (-400, -250)
    links.new(clamp_v.outputs["Value"], row.inputs[0])

    # Blender UV row convention: (grid_size - 1) - row
    row_blender = nodes.new(type="ShaderNodeMath")
    row_blender.operation = "SUBTRACT"
    row_blender.inputs[0].default_value = float(grid_size - 1)
    row_blender.location = (-220, -250)
    links.new(row.outputs["Value"], row_blender.inputs[1])

    # 5. Local Quad UVs
    tex_coord = nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-600, -400)
    sep_uv = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_uv.location = (-400, -400)
    links.new(tex_coord.outputs["UV"], sep_uv.inputs["Vector"])

    # final_u = (uv.x + col) / grid_size
    add_u = nodes.new(type="ShaderNodeMath")
    add_u.operation = "ADD"
    add_u.location = (-40, -100)
    links.new(sep_uv.outputs["X"], add_u.inputs[0])
    links.new(col.outputs["Value"], add_u.inputs[1])

    final_u = nodes.new(type="ShaderNodeMath")
    final_u.operation = "DIVIDE"
    final_u.inputs[1].default_value = float(grid_size)
    final_u.location = (140, -100)
    links.new(add_u.outputs["Value"], final_u.inputs[0])

    # final_v = (uv.y + row_blender) / grid_size
    add_v = nodes.new(type="ShaderNodeMath")
    add_v.operation = "ADD"
    add_v.location = (-40, -250)
    links.new(sep_uv.outputs["Y"], add_v.inputs[0])
    links.new(row_blender.outputs["Value"], add_v.inputs[1])

    final_v = nodes.new(type="ShaderNodeMath")
    final_v.operation = "DIVIDE"
    final_v.inputs[1].default_value = float(grid_size)
    final_v.location = (140, -250)
    links.new(add_v.outputs["Value"], final_v.inputs[0])

    comb_uv = nodes.new(type="ShaderNodeCombineXYZ")
    comb_uv.location = (320, -150)
    links.new(final_u.outputs["Value"], comb_uv.inputs["X"])
    links.new(final_v.outputs["Value"], comb_uv.inputs["Y"])

    # 6. BaseColor Texture Node
    base_img = safe_load_image(base_color_path)
    if base_img:
        tex_base = nodes.new(type="ShaderNodeTexImage")
        tex_base.image = base_img
        tex_base.location = (540, 200)
        links.new(comb_uv.outputs["Vector"], tex_base.inputs["Vector"])
        links.new(tex_base.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(tex_base.outputs["Alpha"], bsdf.inputs["Alpha"])

    # 7. Normal Map Texture Node (with DirectX Green-flip compensation for UE5)
    if normal_path and os.path.exists(normal_path):
        norm_img = safe_load_image(normal_path)
        if norm_img:
            if hasattr(norm_img, "colorspace_settings"):
                norm_img.colorspace_settings.name = "Non-Color"

            tex_norm = nodes.new(type="ShaderNodeTexImage")
            tex_norm.image = norm_img
            tex_norm.location = (540, -150)
            links.new(comb_uv.outputs["Vector"], tex_norm.inputs["Vector"])

            norm_map = nodes.new(type="ShaderNodeNormalMap")
            norm_map.location = (880, -150)

            if target_engine in {"UE5", "DIRECTX"}:
                # Invert Green channel (1.0 - G) for accurate Blender viewport lighting
                sep_col = nodes.new(type="ShaderNodeSeparateColor")
                sep_col.location = (700, -150)
                inv_green = nodes.new(type="ShaderNodeMath")
                inv_green.operation = "SUBTRACT"
                inv_green.inputs[0].default_value = 1.0
                inv_green.location = (700, -320)
                comb_col = nodes.new(type="ShaderNodeCombineColor")
                comb_col.location = (700, 0)

                links.new(tex_norm.outputs["Color"], sep_col.inputs["Color"])
                links.new(sep_col.outputs["Red"], comb_col.inputs["Red"])
                links.new(sep_col.outputs["Green"], inv_green.inputs[1])
                links.new(inv_green.outputs["Value"], comb_col.inputs["Green"])
                links.new(sep_col.outputs["Blue"], comb_col.inputs["Blue"])
                links.new(comb_col.outputs["Color"], norm_map.inputs["Color"])
            else:
                links.new(tex_norm.outputs["Color"], norm_map.inputs["Color"])

            links.new(norm_map.outputs["Normal"], bsdf.inputs["Normal"])

    # 8. Optional ORM (Roughness / Metallic)
    if orm_path and os.path.exists(orm_path):
        orm_img = safe_load_image(orm_path)
        if orm_img:
            if hasattr(orm_img, "colorspace_settings"):
                orm_img.colorspace_settings.name = "Non-Color"

            tex_orm = nodes.new(type="ShaderNodeTexImage")
            tex_orm.image = orm_img
            tex_orm.location = (540, -450)
            links.new(comb_uv.outputs["Vector"], tex_orm.inputs["Vector"])

            sep_orm = nodes.new(type="ShaderNodeSeparateColor")
            sep_orm.location = (720, -450)
            links.new(tex_orm.outputs["Color"], sep_orm.inputs["Color"])

            # Green = Roughness, Blue = Metallic
            links.new(sep_orm.outputs["Green"], bsdf.inputs["Roughness"])
            links.new(sep_orm.outputs["Blue"], bsdf.inputs["Metallic"])

    return mat


def setup_impostor_tracking(proxy_obj: Any, camera_obj: Optional[Any] = None) -> Optional[Any]:
    """
    Configures a TRACK_TO constraint on the proxy quad to orient continuously toward the camera.
    """
    if not bpy or not proxy_obj:
        return None

    cam = camera_obj or bpy.context.scene.camera
    if not cam:
        return None

    # Find or create TRACK_TO constraint
    track_c = next((c for c in proxy_obj.constraints if c.type == "TRACK_TO"), None)
    if not track_c:
        track_c = proxy_obj.constraints.new(type="TRACK_TO")

    track_c.name = "OmniMesh_Preview_Track"
    track_c.target = cam
    track_c.track_axis = "TRACK_NEGATIVE_Y"
    track_c.up_axis = "UP_Z"
    return track_c


def setup_preview_turntable(
    cam_obj: Any,
    target_center: Any,
    radius: float,
    height: float,
    num_frames: int = 72,
) -> bool:
    """
    Keyframes an elevated circular camera orbit around target_center over frames 1..num_frames.
    Dynamically updates the world-space view ray (-Incoming) on every frame so the shader
    samples matching octahedral tiles while preventing lateral occlusion.
    Leaves mesh_objs completely un-animated and preserves production transforms.
    """
    if not bpy or not cam_obj:
        return False

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = num_frames

    if cam_obj.animation_data:
        cam_obj.animation_data_clear()

    center_vec = Vector(target_center) if Vector else target_center

    for f in range(1, num_frames + 1):
        scene.frame_set(f)
        angle = (f - 1) / float(num_frames) * 2.0 * math.pi
        cam_x = center_vec[0] + radius * math.sin(angle)
        cam_y = center_vec[1] - radius * math.cos(angle)
        cam_z = center_vec[2] + height

        cam_loc = Vector((cam_x, cam_y, cam_z)) if Vector else (cam_x, cam_y, cam_z)
        cam_obj.location = cam_loc

        dir_vec = center_vec - cam_loc
        if hasattr(dir_vec, "to_track_quat"):
            cam_obj.rotation_euler = dir_vec.to_track_quat("-Z", "Y").to_euler()

        cam_obj.keyframe_insert(data_path="location", frame=f)
        cam_obj.keyframe_insert(data_path="rotation_euler", frame=f)

    # Set linear interpolation on camera fcurves
    if cam_obj.animation_data and cam_obj.animation_data.action:
        for fcurve in getattr(cam_obj.animation_data.action, "fcurves", []):
            for kp in getattr(fcurve, "keyframe_points", []):
                kp.interpolation = "LINEAR"

    scene.frame_set(1)
    return True


def setup_impostor_preview_rig(
    context: Any,
    mesh_objs: list[Any],
    base_name: str,
    texture_dir: str,
    mode: str = "SIDE_BY_SIDE",
    num_frames: int = 72,
    target_engine: str = "UE5",
) -> dict[str, Any]:
    """
    Constructs an isolated, complete In-Blender preview test rig for Octahedral Impostors.
    Places all temporary objects in a dedicated '{base_name}_Preview_Rig' collection.
    Never alters the production transforms of mesh_objs.
    """
    if not bpy or not mesh_objs:
        return {}

    scene = context.scene if context and hasattr(context, "scene") else bpy.context.scene
    rig_coll_name = f"{base_name}_Preview_Rig"

    # 1. Manage dedicated collection
    rig_coll = bpy.data.collections.get(rig_coll_name)
    if not rig_coll:
        rig_coll = bpy.data.collections.new(rig_coll_name)
        scene.collection.children.link(rig_coll)

    # 2. Compute bounding parameters
    coords = []
    for obj in mesh_objs:
        if hasattr(obj, "bound_box") and obj.bound_box:
            coords.extend([obj.matrix_world @ Vector(c) for c in obj.bound_box])
    if not coords:
        coords = [Vector((-1.0, -1.0, -1.0)), Vector((1.0, 1.0, 1.0))]

    min_b = Vector((min(c.x for c in coords), min(c.y for c in coords), min(c.z for c in coords)))
    max_b = Vector((max(c.x for c in coords), max(c.y for c in coords), max(c.z for c in coords)))
    center = (min_b + max_b) * 0.5
    radius = max((max_b - min_b).length * 0.5, 0.5)

    # 3. Locate baked textures
    base_color_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_BaseColor.png")
    normal_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_Normal.png")
    orm_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_ORM.png")

    if not os.path.exists(base_color_file):
        for obj in mesh_objs:
            for candidate in [getattr(obj, "name", ""), getattr(obj, "name", "").split("_")[0]]:
                cand_clean = candidate.split("_LOD")[0].split("_Test")[0]
                alt_base = os.path.join(texture_dir, f"T_{cand_clean}_Impostor_BaseColor.png")
                if os.path.exists(alt_base):
                    base_name = cand_clean
                    base_color_file = alt_base
                    normal_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_Normal.png")
                    orm_file = os.path.join(texture_dir, f"T_{base_name}_Impostor_ORM.png")
                    break
            if os.path.exists(base_color_file):
                break

    if not os.path.exists(base_color_file):
        logger.warning("Preview rig could not find BaseColor atlas: %s", base_color_file)
        return {}

    # 4. Create preview billboard quad
    proxy_name = f"{base_name}_Preview_Impostor"
    proxy_obj = bpy.data.objects.get(proxy_name)
    if not proxy_obj:
        mesh_data = bpy.data.meshes.new(f"{proxy_name}_Mesh")
        s = radius * 2.08
        hs = s * 0.5
        verts = [(-hs, 0.0, -hs), (hs, 0.0, -hs), (hs, 0.0, hs), (-hs, 0.0, hs)]
        faces = [(0, 1, 2, 3)]
        mesh_data.from_pydata(verts, [], faces)
        mesh_data.update()

        # Add UV layer
        uv_layer = mesh_data.uv_layers.new(name="UVMap")
        uv_coords = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        for loop in mesh_data.loops:
            uv_layer.data[loop.index].uv = uv_coords[loop.vertex_index]

        proxy_obj = bpy.data.objects.new(proxy_name, mesh_data)
        rig_coll.objects.link(proxy_obj)

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
    )
    if preview_mat:
        proxy_obj.data.materials.clear()
        proxy_obj.data.materials.append(preview_mat)

    # 6. Setup dedicated preview camera
    cam_name = f"{base_name}_Preview_Camera"
    cam_obj = bpy.data.objects.get(cam_name)
    if not cam_obj:
        cam_data = bpy.data.cameras.new(f"{cam_name}_Data")
        cam_data.lens = 50
        cam_obj = bpy.data.objects.new(cam_name, cam_data)
        rig_coll.objects.link(cam_obj)

    cam_dist = radius * 5.6
    cam_x = center.x + (offset_x * 0.5 if mode == "SIDE_BY_SIDE" else 0.0)
    cam_obj.location = Vector((cam_x, center.y - cam_dist, center.z + radius * 0.5))
    aim_target = Vector((cam_x, center.y, center.z))
    dir_cam = aim_target - cam_obj.location
    cam_obj.rotation_euler = dir_cam.to_track_quat("-Z", "Y").to_euler()

    # Track constraint on proxy
    setup_impostor_tracking(proxy_obj, cam_obj)

    # 7. Setup preview sun light for normal map lighting validation
    sun_name = f"{base_name}_Preview_Sun"
    sun_obj = bpy.data.objects.get(sun_name)
    if not sun_obj:
        sun_data = bpy.data.lights.new(name=f"{sun_name}_Data", type="SUN")
        sun_data.energy = 3.0
        sun_obj = bpy.data.objects.new(sun_name, sun_data)
        rig_coll.objects.link(sun_obj)
        sun_obj.location = Vector((center.x + 5.0, center.y - 5.0, center.z + 10.0))
        sun_obj.rotation_euler = (0.7, 0.2, 0.5)

    # 8. Setup elevated camera turntable animation
    aim_target = Vector((cam_x, center.y, center.z))
    elev_height = radius * 2.2
    setup_preview_turntable(
        cam_obj=cam_obj,
        target_center=aim_target,
        radius=cam_dist,
        height=elev_height,
        num_frames=num_frames,
    )

    # Set active camera
    scene.camera = cam_obj

    # 9. Safely switch active 3D Viewport to Camera View
    if not getattr(bpy.app, "background", False) and hasattr(context, "screen") and context.screen:
        for area in getattr(context.screen, "areas", []):
            if getattr(area, "type", "") == "VIEW_3D":
                for space in getattr(area, "spaces", []):
                    if getattr(space, "type", "") == "VIEW_3D":
                        try:
                            space.region_3d.view_perspective = "CAMERA"
                            if hasattr(space, "shading"):
                                space.shading.type = "MATERIAL"
                        except Exception as vp_err:
                            logger.debug("Could not switch viewport to camera: %s", vp_err)

    return {
        "collection": rig_coll_name,
        "proxy_object": proxy_name,
        "camera_object": cam_name,
        "material": mat_name,
    }


def teardown_impostor_preview_rig(context: Any, base_name: str) -> bool:
    """
    Cleanly destroys all preview rig elements and removes the '{base_name}_Preview_Rig' collection.
    Restores original camera and removes animation data from mesh objects.
    """
    if not bpy:
        return False

    rig_coll_name = f"{base_name}_Preview_Rig"
    rig_coll = bpy.data.collections.get(rig_coll_name)
    if not rig_coll:
        return False

    # Clear animation on any objects that were keyed
    for obj in list(rig_coll.objects):
        if obj.animation_data:
            obj.animation_data_clear()
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove collection
    bpy.data.collections.remove(rig_coll)

    # Remove preview material
    mat_name = f"M_{base_name}_Octahedral_Preview"
    mat = bpy.data.materials.get(mat_name)
    if mat:
        bpy.data.materials.remove(mat)

    # Restore default active camera if possible
    scene = context.scene if context and hasattr(context, "scene") else bpy.context.scene
    if scene.camera and scene.camera.name == f"{base_name}_Preview_Camera":
        first_cam = next((o for o in scene.objects if o.type == "CAMERA"), None)
        scene.camera = first_cam

    return True
