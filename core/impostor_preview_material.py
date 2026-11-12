"""
OmniMesh In-Blender Preview Material Construction for Octahedral Impostors.
Blender 4.2+ and 5.0+ LTS Compatible.

Constructs native dynamic shader node networks for in-viewport octahedral tile decoding
and material assignment with zero production transform pollution.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Optional, cast

from .compat import set_node_prop, set_socket_default_value

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
else:
    try:
        import bpy
    except ImportError:
        bpy = None
    BlendData = object  # runtime fallback for type annotations


def safe_load_image(
    filepath: str,
    *,
    blend_data: BlendData,
) -> Optional[bpy.types.Image]:
    """
    Loads an image from filepath while preventing duplicate datablocks in Blender.
    Re-uses existing image if already loaded with matching absolute path.
    """
    if not bpy or not filepath or not os.path.exists(filepath) or blend_data is None:
        return None

    abs_target = os.path.abspath(filepath)
    for img in blend_data.images:
        img_fp = img.filepath
        if img_fp:
            try:
                existing_abs = os.path.abspath(bpy.path.abspath(img_fp))
            except (RuntimeError, ValueError, AttributeError):
                existing_abs = os.path.abspath(img_fp)

            if existing_abs == abs_target:
                try:
                    img.reload()
                except (RuntimeError, ValueError, AttributeError) as reload_err:
                    logger.debug("Failed reloading existing image %s: %s", filepath, reload_err)
                return img

    try:
        return blend_data.images.load(filepath)
    except (RuntimeError, ValueError, AttributeError) as exc:
        logger.error("Failed loading image from %s: %s", filepath, exc)
        return None


def create_octahedral_preview_material(
    mat_name: str,
    base_color_path: str,
    normal_path: Optional[str] = None,
    orm_path: Optional[str] = None,
    grid_size: int = 8,
    target_engine: str = "UE5",
    *,
    blend_data: BlendData,
) -> Optional[bpy.types.Material]:
    """
    Constructs a native Blender Shader Node material that evaluates the upper-hemisphere
    octahedral projection dynamically on the GPU in real-time.

    Decodes `-Incoming` view ray into (u, v) atlas coordinates, selects the matching tile,
    and applies BaseColor cutout, Normal map (with DirectX Green-inversion compensation for UE5),
    and optional ORM roughness.
    """
    if not bpy or blend_data is None:
        return None

    mat = blend_data.materials.get(mat_name)
    if not mat:
        mat = blend_data.materials.new(mat_name)
    mat.use_nodes = True

    # Defensive EEVEE Next & EEVEE Legacy transparency configuration
    try:
        mat.surface_render_method = "DITHERED"
    except (TypeError, ValueError, AttributeError) as exc:
        logger.debug("Failed setting surface_render_method on material: %s", exc)
    try:
        mat.use_transparent_shadow = True
    except (TypeError, ValueError, AttributeError) as exc:
        logger.debug("Failed setting use_transparent_shadow on material: %s", exc)
    try:
        mat.use_backface_culling = True
    except (TypeError, ValueError, AttributeError) as exc:
        logger.debug("Failed setting use_backface_culling on material: %s", exc)

    if not mat.node_tree:
        return mat
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    # 1. Output & Principled BSDF
    out_node = nodes.new(type="ShaderNodeOutputMaterial")
    out_node.location = (1400, 0)

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (1100, 0)
    links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    # 2. Uniform View Direction Vector (CamWorldPos - ObjWorldPos)
    cam_trans = nodes.new(type="ShaderNodeVectorTransform")
    cam_trans.name = "CamWorldPos"
    set_node_prop(cam_trans, "vector_type", "POINT")
    set_node_prop(cam_trans, "convert_from", "CAMERA")
    set_node_prop(cam_trans, "convert_to", "WORLD")
    set_socket_default_value(cam_trans.inputs["Vector"], (0.0, 0.0, 0.0))
    cam_trans.location = (-1200, 280)

    obj_trans = nodes.new(type="ShaderNodeVectorTransform")
    obj_trans.name = "ObjWorldPos"
    set_node_prop(obj_trans, "vector_type", "POINT")
    set_node_prop(obj_trans, "convert_from", "OBJECT")
    set_node_prop(obj_trans, "convert_to", "WORLD")
    set_socket_default_value(obj_trans.inputs["Vector"], (0.0, 0.0, 0.0))
    obj_trans.location = (-1200, 120)

    sub_vec = nodes.new(type="ShaderNodeVectorMath")
    set_node_prop(sub_vec, "operation", "SUBTRACT")
    sub_vec.location = (-1000, 200)
    links.new(cam_trans.outputs["Vector"], sub_vec.inputs[0])
    links.new(obj_trans.outputs["Vector"], sub_vec.inputs[1])

    # Normalize view vector
    v_norm = nodes.new(type="ShaderNodeVectorMath")
    set_node_prop(v_norm, "operation", "NORMALIZE")
    v_norm.location = (-820, 200)
    links.new(sub_vec.outputs["Vector"], v_norm.inputs[0])

    sep_v = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_v.location = (-640, 200)
    links.new(v_norm.outputs["Vector"], sep_v.inputs["Vector"])

    # 3. Hemi-Octahedral Projection Math
    # denom = abs(X) + abs(Y) + max(Z, 0.001)
    abs_x = nodes.new(type="ShaderNodeMath")
    set_node_prop(abs_x, "operation", "ABSOLUTE")
    abs_x.location = (-600, 400)
    links.new(sep_v.outputs["X"], abs_x.inputs[0])

    abs_y = nodes.new(type="ShaderNodeMath")
    set_node_prop(abs_y, "operation", "ABSOLUTE")
    abs_y.location = (-600, 250)
    links.new(sep_v.outputs["Y"], abs_y.inputs[0])

    max_z = nodes.new(type="ShaderNodeMath")
    set_node_prop(max_z, "operation", "MAXIMUM")
    set_socket_default_value(max_z.inputs[1], 0.001)
    max_z.location = (-600, 100)
    links.new(sep_v.outputs["Z"], max_z.inputs[0])

    add_xy = nodes.new(type="ShaderNodeMath")
    set_node_prop(add_xy, "operation", "ADD")
    add_xy.location = (-400, 350)
    links.new(abs_x.outputs["Value"], add_xy.inputs[0])
    links.new(abs_y.outputs["Value"], add_xy.inputs[1])

    denom = nodes.new(type="ShaderNodeMath")
    set_node_prop(denom, "operation", "ADD")
    denom.location = (-220, 350)
    links.new(add_xy.outputs["Value"], denom.inputs[0])
    links.new(max_z.outputs["Value"], denom.inputs[1])

    # nx = X / denom, ny = Y / denom
    nx = nodes.new(type="ShaderNodeMath")
    set_node_prop(nx, "operation", "DIVIDE")
    nx.location = (-40, 400)
    links.new(sep_v.outputs["X"], nx.inputs[0])
    links.new(denom.outputs["Value"], nx.inputs[1])

    ny = nodes.new(type="ShaderNodeMath")
    set_node_prop(ny, "operation", "DIVIDE")
    ny.location = (-40, 250)
    links.new(sep_v.outputs["Y"], ny.inputs[0])
    links.new(denom.outputs["Value"], ny.inputs[1])

    # u = (nx + ny) * 0.5 + 0.5
    add_nx_ny = nodes.new(type="ShaderNodeMath")
    set_node_prop(add_nx_ny, "operation", "ADD")
    add_nx_ny.location = (140, 400)
    links.new(nx.outputs["Value"], add_nx_ny.inputs[0])
    links.new(ny.outputs["Value"], add_nx_ny.inputs[1])

    u_coord = nodes.new(type="ShaderNodeMath")
    set_node_prop(u_coord, "operation", "MULTIPLY_ADD")
    set_socket_default_value(u_coord.inputs[1], 0.5)
    set_socket_default_value(u_coord.inputs[2], 0.5)
    u_coord.location = (320, 400)
    links.new(add_nx_ny.outputs["Value"], u_coord.inputs[0])

    # v = (nx - ny) * 0.5 + 0.5
    sub_nx_ny = nodes.new(type="ShaderNodeMath")
    set_node_prop(sub_nx_ny, "operation", "SUBTRACT")
    sub_nx_ny.location = (140, 250)
    links.new(nx.outputs["Value"], sub_nx_ny.inputs[0])
    links.new(ny.outputs["Value"], sub_nx_ny.inputs[1])

    v_coord = nodes.new(type="ShaderNodeMath")
    set_node_prop(v_coord, "operation", "MULTIPLY_ADD")
    set_socket_default_value(v_coord.inputs[1], 0.5)
    set_socket_default_value(v_coord.inputs[2], 0.5)
    v_coord.location = (320, 250)
    links.new(sub_nx_ny.outputs["Value"], v_coord.inputs[0])

    # 4. Grid Tile Coordinates: col = floor(u * N), row = floor(v * N)
    clamp_u = nodes.new(type="ShaderNodeMath")
    set_node_prop(clamp_u, "operation", "MULTIPLY")
    set_socket_default_value(clamp_u.inputs[1], float(grid_size))
    clamp_u.location = (-600, -100)
    links.new(u_coord.outputs["Value"], clamp_u.inputs[0])

    col = nodes.new(type="ShaderNodeMath")
    set_node_prop(col, "operation", "FLOOR")
    col.location = (-400, -100)
    links.new(clamp_u.outputs["Value"], col.inputs[0])

    clamp_v = nodes.new(type="ShaderNodeMath")
    set_node_prop(clamp_v, "operation", "MULTIPLY")
    set_socket_default_value(clamp_v.inputs[1], float(grid_size))
    clamp_v.location = (-600, -250)
    links.new(v_coord.outputs["Value"], clamp_v.inputs[0])

    row = nodes.new(type="ShaderNodeMath")
    set_node_prop(row, "operation", "FLOOR")
    row.location = (-400, -250)
    links.new(clamp_v.outputs["Value"], row.inputs[0])

    # Blender UV row convention: (grid_size - 1) - row
    row_blender = nodes.new(type="ShaderNodeMath")
    set_node_prop(row_blender, "operation", "SUBTRACT")
    set_socket_default_value(row_blender.inputs[0], float(grid_size - 1))
    row_blender.location = (-220, -250)
    links.new(row.outputs["Value"], row_blender.inputs[1])

    # 5. Local Quad UVs with border bleed prevention
    tex_coord = nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-600, -400)
    sep_uv = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_uv.location = (-400, -400)
    links.new(tex_coord.outputs["UV"], sep_uv.inputs["Vector"])

    clamp_u_sub = nodes.new(type="ShaderNodeClamp")
    set_socket_default_value(clamp_u_sub.inputs["Min"], 0.002)
    set_socket_default_value(clamp_u_sub.inputs["Max"], 0.998)
    clamp_u_sub.location = (-220, -400)
    links.new(sep_uv.outputs["X"], clamp_u_sub.inputs["Value"])

    clamp_v_sub = nodes.new(type="ShaderNodeClamp")
    set_socket_default_value(clamp_v_sub.inputs["Min"], 0.002)
    set_socket_default_value(clamp_v_sub.inputs["Max"], 0.998)
    clamp_v_sub.location = (-220, -550)
    links.new(sep_uv.outputs["Y"], clamp_v_sub.inputs["Value"])

    # final_u = (uv.x + col) / grid_size
    add_u = nodes.new(type="ShaderNodeMath")
    set_node_prop(add_u, "operation", "ADD")
    add_u.location = (-40, -100)
    links.new(clamp_u_sub.outputs["Result"], add_u.inputs[0])
    links.new(col.outputs["Value"], add_u.inputs[1])

    final_u = nodes.new(type="ShaderNodeMath")
    set_node_prop(final_u, "operation", "DIVIDE")
    set_socket_default_value(final_u.inputs[1], float(grid_size))
    final_u.location = (140, -100)
    links.new(add_u.outputs["Value"], final_u.inputs[0])

    # final_v = (uv.y + row_blender) / grid_size
    add_v = nodes.new(type="ShaderNodeMath")
    set_node_prop(add_v, "operation", "ADD")
    add_v.location = (-40, -250)
    links.new(clamp_v_sub.outputs["Result"], add_v.inputs[0])
    links.new(row_blender.outputs["Value"], add_v.inputs[1])

    final_v = nodes.new(type="ShaderNodeMath")
    set_node_prop(final_v, "operation", "DIVIDE")
    set_socket_default_value(final_v.inputs[1], float(grid_size))
    final_v.location = (140, -250)
    links.new(add_v.outputs["Value"], final_v.inputs[0])

    comb_uv = nodes.new(type="ShaderNodeCombineXYZ")
    comb_uv.location = (320, -150)
    links.new(final_u.outputs["Value"], comb_uv.inputs["X"])
    links.new(final_v.outputs["Value"], comb_uv.inputs["Y"])

    # 6. BaseColor Texture Node
    base_img = safe_load_image(base_color_path, blend_data=blend_data)
    if base_img:
        tex_base = nodes.new(type="ShaderNodeTexImage")
        set_node_prop(tex_base, "image", base_img)
        tex_base.location = (540, 200)
        links.new(comb_uv.outputs["Vector"], tex_base.inputs["Vector"])
        links.new(tex_base.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(tex_base.outputs["Alpha"], bsdf.inputs["Alpha"])

    # 7. Normal Map Texture Node (with DirectX Green-flip compensation for UE5)
    if normal_path and os.path.exists(normal_path):
        norm_img = safe_load_image(normal_path, blend_data=blend_data)
        if norm_img:
            if norm_img.colorspace_settings:
                cast("Any", norm_img.colorspace_settings).name = "Non-Color"

            tex_norm = nodes.new(type="ShaderNodeTexImage")
            set_node_prop(tex_norm, "image", norm_img)
            tex_norm.location = (540, -150)
            links.new(comb_uv.outputs["Vector"], tex_norm.inputs["Vector"])

            norm_map = nodes.new(type="ShaderNodeNormalMap")
            norm_map.location = (880, -150)

            if target_engine in {"UE5", "DIRECTX"}:
                # Invert Green channel (1.0 - G) for accurate Blender viewport lighting
                sep_col = nodes.new(type="ShaderNodeSeparateColor")
                sep_col.location = (700, -150)
                inv_green = nodes.new(type="ShaderNodeMath")
                set_node_prop(inv_green, "operation", "SUBTRACT")
                set_socket_default_value(inv_green.inputs[0], 1.0)
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
        orm_img = safe_load_image(orm_path, blend_data=blend_data)
        if orm_img:
            if orm_img.colorspace_settings:
                cast("Any", orm_img.colorspace_settings).name = "Non-Color"

            tex_orm = nodes.new(type="ShaderNodeTexImage")
            set_node_prop(tex_orm, "image", orm_img)
            tex_orm.location = (540, -450)
            links.new(comb_uv.outputs["Vector"], tex_orm.inputs["Vector"])

            sep_orm = nodes.new(type="ShaderNodeSeparateColor")
            sep_orm.location = (720, -450)
            links.new(tex_orm.outputs["Color"], sep_orm.inputs["Color"])

            # Green = Roughness, Blue = Metallic
            links.new(sep_orm.outputs["Green"], bsdf.inputs["Roughness"])
            links.new(sep_orm.outputs["Blue"], bsdf.inputs["Metallic"])

    return mat


__all__ = [
    "safe_load_image",
    "create_octahedral_preview_material",
]
