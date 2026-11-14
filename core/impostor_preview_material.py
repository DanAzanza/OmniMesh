"""
OmniMesh In-Blender Preview Material Construction for Octahedral Impostors.
Blender 5.0+ & 5.2 LTS Compatible.

Constructs native dynamic shader node networks for in-viewport octahedral tile decoding
and material assignment with zero production transform pollution.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Optional, cast

from .compat import set_node_prop, set_socket_default_value
from .io_utils import resolve_blender_path

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
    blend_fp = getattr(blend_data, "filepath", "") or ""
    for img in blend_data.images:
        img_fp = img.filepath
        if img_fp:
            resolved_fp = resolve_blender_path(
                img_fp,
                blend_fp,
                abspath_fn=bpy.path.abspath,
                fallback_raw_on_unsaved=False,
            )
            if not resolved_fp:
                continue
            existing_abs = os.path.abspath(resolved_fp)

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


def _build_view_direction_outputs(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    view_dir_mode: str,
) -> bpy.types.Node:
    """Builds shader nodes yielding normalized world-space view vector X/Y/Z outputs (surface -> viewer)."""
    if view_dir_mode == "VIEWPORT_INCOMING":
        # Billboard card tracks viewer with its -Y face via OmniMesh_Viewport_Billboard;
        # transforming local (0, -1, 0) to WORLD yields a uniform per-card view direction
        # without per-fragment perspective split seams or requiring an active scene camera.
        view_vec = nodes.new(type="ShaderNodeVectorTransform")
        view_vec.name = "BillboardWorldViewDir"
        set_node_prop(view_vec, "vector_type", "VECTOR")
        set_node_prop(view_vec, "convert_from", "OBJECT")
        set_node_prop(view_vec, "convert_to", "WORLD")
        set_socket_default_value(view_vec.inputs["Vector"], (0.0, -1.0, 0.0))
        view_vec.location = (-1000, 200)

        v_norm = nodes.new(type="ShaderNodeVectorMath")
        set_node_prop(v_norm, "operation", "NORMALIZE")
        v_norm.location = (-820, 200)
        links.new(view_vec.outputs["Vector"], v_norm.inputs[0])
    else:
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

        v_norm = nodes.new(type="ShaderNodeVectorMath")
        set_node_prop(v_norm, "operation", "NORMALIZE")
        v_norm.location = (-820, 200)
        links.new(sub_vec.outputs["Vector"], v_norm.inputs[0])

    sep_v = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_v.location = (-640, 200)
    links.new(v_norm.outputs["Vector"], sep_v.inputs["Vector"])
    return sep_v


def _build_hemi_octahedral_uv(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    sep_v: bpy.types.Node,
) -> tuple[bpy.types.NodeSocket, bpy.types.NodeSocket]:
    """Maps world-space view direction to upper-hemisphere octahedral (u, v) in [0, 1]^2."""
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
    return u_coord.outputs["Value"], v_coord.outputs["Value"]


def _build_full_octahedral_uv(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    sep_v: bpy.types.Node,
) -> tuple[bpy.types.NodeSocket, bpy.types.NodeSocket]:
    """Maps world-space view direction to full-sphere octahedral (u, v) in [0, 1]^2."""
    abs_x = nodes.new(type="ShaderNodeMath")
    set_node_prop(abs_x, "operation", "ABSOLUTE")
    links.new(sep_v.outputs["X"], abs_x.inputs[0])

    abs_y = nodes.new(type="ShaderNodeMath")
    set_node_prop(abs_y, "operation", "ABSOLUTE")
    links.new(sep_v.outputs["Y"], abs_y.inputs[0])

    abs_z = nodes.new(type="ShaderNodeMath")
    set_node_prop(abs_z, "operation", "ABSOLUTE")
    links.new(sep_v.outputs["Z"], abs_z.inputs[0])

    add_xy = nodes.new(type="ShaderNodeMath")
    set_node_prop(add_xy, "operation", "ADD")
    links.new(abs_x.outputs["Value"], add_xy.inputs[0])
    links.new(abs_y.outputs["Value"], add_xy.inputs[1])

    l1_raw = nodes.new(type="ShaderNodeMath")
    set_node_prop(l1_raw, "operation", "ADD")
    links.new(add_xy.outputs["Value"], l1_raw.inputs[0])
    links.new(abs_z.outputs["Value"], l1_raw.inputs[1])

    l1_safe = nodes.new(type="ShaderNodeMath")
    set_node_prop(l1_safe, "operation", "MAXIMUM")
    set_socket_default_value(l1_safe.inputs[1], 1e-5)
    links.new(l1_raw.outputs["Value"], l1_safe.inputs[0])

    nx = nodes.new(type="ShaderNodeMath")
    set_node_prop(nx, "operation", "DIVIDE")
    links.new(sep_v.outputs["X"], nx.inputs[0])
    links.new(l1_safe.outputs["Value"], nx.inputs[1])

    ny = nodes.new(type="ShaderNodeMath")
    set_node_prop(ny, "operation", "DIVIDE")
    links.new(sep_v.outputs["Y"], ny.inputs[0])
    links.new(l1_safe.outputs["Value"], ny.inputs[1])

    # Fold lower hemisphere (z < 0): ox = (1 - |ny|) * sign_ge0(nx), oy = (1 - |nx|) * sign_ge0(ny)
    abs_nx = nodes.new(type="ShaderNodeMath")
    set_node_prop(abs_nx, "operation", "ABSOLUTE")
    links.new(nx.outputs["Value"], abs_nx.inputs[0])

    abs_ny = nodes.new(type="ShaderNodeMath")
    set_node_prop(abs_ny, "operation", "ABSOLUTE")
    links.new(ny.outputs["Value"], abs_ny.inputs[0])

    one_m_ny = nodes.new(type="ShaderNodeMath")
    set_node_prop(one_m_ny, "operation", "SUBTRACT")
    set_socket_default_value(one_m_ny.inputs[0], 1.0)
    links.new(abs_ny.outputs["Value"], one_m_ny.inputs[1])

    one_m_nx = nodes.new(type="ShaderNodeMath")
    set_node_prop(one_m_nx, "operation", "SUBTRACT")
    set_socket_default_value(one_m_nx.inputs[0], 1.0)
    links.new(abs_nx.outputs["Value"], one_m_nx.inputs[1])

    def _signed_fold(coord_socket: bpy.types.NodeSocket, mag_socket: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
        is_neg = nodes.new(type="ShaderNodeMath")
        set_node_prop(is_neg, "operation", "LESS_THAN")
        set_socket_default_value(is_neg.inputs[1], 0.0)
        links.new(coord_socket, is_neg.inputs[0])

        sign_ge0 = nodes.new(type="ShaderNodeMath")
        set_node_prop(sign_ge0, "operation", "MULTIPLY_ADD")
        set_socket_default_value(sign_ge0.inputs[1], -2.0)
        set_socket_default_value(sign_ge0.inputs[2], 1.0)
        links.new(is_neg.outputs["Value"], sign_ge0.inputs[0])

        folded = nodes.new(type="ShaderNodeMath")
        set_node_prop(folded, "operation", "MULTIPLY")
        links.new(mag_socket, folded.inputs[0])
        links.new(sign_ge0.outputs["Value"], folded.inputs[1])
        return folded.outputs["Value"]

    ox_sock = _signed_fold(nx.outputs["Value"], one_m_ny.outputs["Value"])
    oy_sock = _signed_fold(ny.outputs["Value"], one_m_nx.outputs["Value"])

    z_neg = nodes.new(type="ShaderNodeMath")
    set_node_prop(z_neg, "operation", "LESS_THAN")
    set_socket_default_value(z_neg.inputs[1], 0.0)
    links.new(sep_v.outputs["Z"], z_neg.inputs[0])

    def _select_hemi(orig_sock: bpy.types.NodeSocket, fold_sock: bpy.types.NodeSocket) -> bpy.types.NodeSocket:
        diff = nodes.new(type="ShaderNodeMath")
        set_node_prop(diff, "operation", "SUBTRACT")
        links.new(fold_sock, diff.inputs[0])
        links.new(orig_sock, diff.inputs[1])

        sel = nodes.new(type="ShaderNodeMath")
        set_node_prop(sel, "operation", "MULTIPLY_ADD")
        links.new(z_neg.outputs["Value"], sel.inputs[0])
        links.new(diff.outputs["Value"], sel.inputs[1])
        links.new(orig_sock, sel.inputs[2])
        return sel.outputs["Value"]

    final_nx = _select_hemi(nx.outputs["Value"], ox_sock)
    final_ny = _select_hemi(ny.outputs["Value"], oy_sock)

    u_coord = nodes.new(type="ShaderNodeMath")
    set_node_prop(u_coord, "operation", "MULTIPLY_ADD")
    set_socket_default_value(u_coord.inputs[1], 0.5)
    set_socket_default_value(u_coord.inputs[2], 0.5)
    links.new(final_nx, u_coord.inputs[0])

    v_coord = nodes.new(type="ShaderNodeMath")
    set_node_prop(v_coord, "operation", "MULTIPLY_ADD")
    set_socket_default_value(v_coord.inputs[1], 0.5)
    set_socket_default_value(v_coord.inputs[2], 0.5)
    links.new(final_ny, v_coord.inputs[0])
    return u_coord.outputs["Value"], v_coord.outputs["Value"]


def _wire_octahedral_textures(
    nodes: bpy.types.Nodes,
    links: bpy.types.NodeLinks,
    comb_uv: bpy.types.Node,
    bsdf: bpy.types.Node,
    base_color_path: str,
    normal_path: Optional[str],
    orm_path: Optional[str],
    target_engine: str,
    allow_unbound_tex_nodes: bool,
    blend_data: BlendData,
) -> None:
    """Creates and links Tex_BaseColor, Tex_Normal, and Tex_ORM for octahedral evaluation."""
    base_img = safe_load_image(base_color_path, blend_data=blend_data) if base_color_path else None
    if base_img is not None or allow_unbound_tex_nodes:
        tex_base = nodes.new(type="ShaderNodeTexImage")
        tex_base.name = "Tex_BaseColor"
        tex_base.label = "Base Color & Alpha"
        set_node_prop(tex_base, "extension", "CLIP")
        if base_img is not None:
            set_node_prop(tex_base, "image", base_img)
        tex_base.mute = base_img is None
        tex_base.location = (540, 200)
        links.new(comb_uv.outputs["Vector"], tex_base.inputs["Vector"])
        links.new(tex_base.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(tex_base.outputs["Alpha"], bsdf.inputs["Alpha"])

    norm_img = (
        safe_load_image(normal_path, blend_data=blend_data) if normal_path and os.path.exists(normal_path) else None
    )
    if norm_img is not None or allow_unbound_tex_nodes:
        if norm_img is not None and norm_img.colorspace_settings:
            cast("Any", norm_img.colorspace_settings).name = "Non-Color"

        tex_norm = nodes.new(type="ShaderNodeTexImage")
        tex_norm.name = "Tex_Normal"
        tex_norm.label = "Normal Map"
        set_node_prop(tex_norm, "extension", "CLIP")
        if norm_img is not None:
            set_node_prop(tex_norm, "image", norm_img)
        tex_norm.mute = norm_img is None
        tex_norm.location = (540, -150)
        links.new(comb_uv.outputs["Vector"], tex_norm.inputs["Vector"])

        norm_map = nodes.new(type="ShaderNodeNormalMap")
        norm_map.location = (880, -150)

        if target_engine in {"UE5", "DIRECTX"}:
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

    orm_img = safe_load_image(orm_path, blend_data=blend_data) if orm_path and os.path.exists(orm_path) else None
    if orm_img is not None or allow_unbound_tex_nodes:
        if orm_img is not None and orm_img.colorspace_settings:
            cast("Any", orm_img.colorspace_settings).name = "Non-Color"

        tex_orm = nodes.new(type="ShaderNodeTexImage")
        tex_orm.name = "Tex_ORM"
        tex_orm.label = "ORM / MaskMap"
        set_node_prop(tex_orm, "extension", "CLIP")
        if orm_img is not None:
            set_node_prop(tex_orm, "image", orm_img)
        tex_orm.mute = orm_img is None
        tex_orm.location = (540, -450)
        links.new(comb_uv.outputs["Vector"], tex_orm.inputs["Vector"])

        sep_orm = nodes.new(type="ShaderNodeSeparateColor")
        sep_orm.location = (720, -450)
        links.new(tex_orm.outputs["Color"], sep_orm.inputs["Color"])

        if target_engine in {"UNITY_6", "UNITY"}:
            links.new(sep_orm.outputs["Red"], bsdf.inputs["Metallic"])
            inv_smooth = nodes.new(type="ShaderNodeInvert")
            inv_smooth.location = (900, -450)
            links.new(tex_orm.outputs["Alpha"], inv_smooth.inputs["Color"])
            links.new(inv_smooth.outputs["Color"], bsdf.inputs["Roughness"])
        else:
            links.new(sep_orm.outputs["Green"], bsdf.inputs["Roughness"])
            links.new(sep_orm.outputs["Blue"], bsdf.inputs["Metallic"])


def create_octahedral_preview_material(
    mat_name: str,
    base_color_path: str,
    normal_path: Optional[str] = None,
    orm_path: Optional[str] = None,
    grid_size: int = 8,
    target_engine: str = "UE5",
    mode: str = "OCTAHEDRAL_HEMI",
    view_dir_mode: str = "CAMERA_TRANSFORM",
    allow_unbound_tex_nodes: bool = False,
    *,
    blend_data: BlendData,
) -> Optional[bpy.types.Material]:
    """
    Constructs a native Blender Shader Node material that evaluates the hemi or full-sphere
    octahedral projection dynamically on the GPU in real-time.

    view_dir_mode='CAMERA_TRANSFORM' tracks the active scene camera (used by dedicated preview rigs);
    view_dir_mode='VIEWPORT_INCOMING' derives view direction from the billboard object's -Y tracking axis
    so free 3D viewport orbiting works without requiring an active scene camera.
    """
    if not bpy or blend_data is None:
        return None

    mat = blend_data.materials.get(mat_name)
    if not mat:
        mat = blend_data.materials.new(mat_name)
    mat.use_nodes = True

    # Smooth alpha blending preserves semi-transparent propellers and canopies
    mat.surface_render_method = "BLENDED"
    mat.use_transparent_shadow = True
    mat.use_backface_culling = view_dir_mode != "VIEWPORT_INCOMING"

    if not mat.node_tree:
        return mat
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    out_node = nodes.new(type="ShaderNodeOutputMaterial")
    out_node.location = (1400, 0)

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (1100, 0)
    links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    sep_v = _build_view_direction_outputs(nodes, links, view_dir_mode)
    if mode == "OCTAHEDRAL_SPHERE":
        u_socket, v_socket = _build_full_octahedral_uv(nodes, links, sep_v)
    else:
        u_socket, v_socket = _build_hemi_octahedral_uv(nodes, links, sep_v)

    # 4. Grid Tile Coordinates: col = clamp(floor(u * N), 0, N - 1)
    mul_u = nodes.new(type="ShaderNodeMath")
    set_node_prop(mul_u, "operation", "MULTIPLY")
    set_socket_default_value(mul_u.inputs[1], float(grid_size))
    mul_u.location = (-600, -100)
    links.new(u_socket, mul_u.inputs[0])

    floor_col = nodes.new(type="ShaderNodeMath")
    set_node_prop(floor_col, "operation", "FLOOR")
    floor_col.location = (-460, -100)
    links.new(mul_u.outputs["Value"], floor_col.inputs[0])

    col = nodes.new(type="ShaderNodeClamp")
    set_socket_default_value(col.inputs["Min"], 0.0)
    set_socket_default_value(col.inputs["Max"], float(max(0, grid_size - 1)))
    col.location = (-320, -100)
    links.new(floor_col.outputs["Value"], col.inputs["Value"])

    mul_v = nodes.new(type="ShaderNodeMath")
    set_node_prop(mul_v, "operation", "MULTIPLY")
    set_socket_default_value(mul_v.inputs[1], float(grid_size))
    mul_v.location = (-600, -250)
    links.new(v_socket, mul_v.inputs[0])

    floor_row = nodes.new(type="ShaderNodeMath")
    set_node_prop(floor_row, "operation", "FLOOR")
    floor_row.location = (-460, -250)
    links.new(mul_v.outputs["Value"], floor_row.inputs[0])

    row = nodes.new(type="ShaderNodeClamp")
    set_socket_default_value(row.inputs["Min"], 0.0)
    set_socket_default_value(row.inputs["Max"], float(max(0, grid_size - 1)))
    row.location = (-320, -250)
    links.new(floor_row.outputs["Value"], row.inputs["Value"])

    # Blender UV row convention: (grid_size - 1) - row
    row_blender = nodes.new(type="ShaderNodeMath")
    set_node_prop(row_blender, "operation", "SUBTRACT")
    set_socket_default_value(row_blender.inputs[0], float(grid_size - 1))
    row_blender.location = (-160, -250)
    links.new(row.outputs["Result"], row_blender.inputs[1])

    # 5. Local Quad UVs with border bleed prevention
    tex_coord = nodes.new(type="ShaderNodeTexCoord")
    tex_coord.location = (-600, -400)
    sep_uv = nodes.new(type="ShaderNodeSeparateXYZ")
    sep_uv.location = (-400, -400)
    links.new(tex_coord.outputs["UV"], sep_uv.inputs["Vector"])

    clamp_u_sub = nodes.new(type="ShaderNodeClamp")
    set_socket_default_value(clamp_u_sub.inputs["Min"], 0.004)
    set_socket_default_value(clamp_u_sub.inputs["Max"], 0.996)
    clamp_u_sub.location = (-220, -400)
    links.new(sep_uv.outputs["X"], clamp_u_sub.inputs["Value"])

    clamp_v_sub = nodes.new(type="ShaderNodeClamp")
    set_socket_default_value(clamp_v_sub.inputs["Min"], 0.004)
    set_socket_default_value(clamp_v_sub.inputs["Max"], 0.996)
    clamp_v_sub.location = (-220, -550)
    links.new(sep_uv.outputs["Y"], clamp_v_sub.inputs["Value"])

    add_u = nodes.new(type="ShaderNodeMath")
    set_node_prop(add_u, "operation", "ADD")
    add_u.location = (-40, -100)
    links.new(clamp_u_sub.outputs["Result"], add_u.inputs[0])
    links.new(col.outputs["Result"], add_u.inputs[1])

    final_u = nodes.new(type="ShaderNodeMath")
    set_node_prop(final_u, "operation", "DIVIDE")
    set_socket_default_value(final_u.inputs[1], float(grid_size))
    final_u.location = (140, -100)
    links.new(add_u.outputs["Value"], final_u.inputs[0])

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

    _wire_octahedral_textures(
        nodes=nodes,
        links=links,
        comb_uv=comb_uv,
        bsdf=bsdf,
        base_color_path=base_color_path,
        normal_path=normal_path,
        orm_path=orm_path,
        target_engine=target_engine,
        allow_unbound_tex_nodes=allow_unbound_tex_nodes,
        blend_data=blend_data,
    )
    return mat


__all__ = [
    "safe_load_image",
    "create_octahedral_preview_material",
]
