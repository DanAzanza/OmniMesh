"""
OmniMesh Unlit Impostor Shader Harness.
Blender 5.0+ & 5.2 LTS Compatible.

Constructs unlit emission shader overrides for the required PBR and depth passes:
- BASE_COLOR (with cutout alpha transparency)
- NORMAL (camera-space normals, DirectX Green-inversion for UE5, cutout alpha)
- DEPTH (camera-space planar Z-depth normalized across bounding sphere, cutout alpha)
- ORM (AO, Roughness, Metallic packed for target engine, cutout alpha)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, cast

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
else:
    try:
        import bpy
    except ImportError:
        bpy = None
        BlendData = object


from .compat import get_socket_default_value, set_node_prop, set_socket_default_value

from .exceptions import ImpostorBakeError

_NODE_TYPE_TO_IDNAME: dict[str, str] = {
    "TEX_IMAGE": "ShaderNodeTexImage",
    "MATH": "ShaderNodeMath",
    "VECT_MATH": "ShaderNodeVectorMath",
    "MIX": "ShaderNodeMix",
    "MIX_RGB": "ShaderNodeMixRGB",
    "SEPARATE_COLOR": "ShaderNodeSeparateColor",
    "COMBINE_COLOR": "ShaderNodeCombineColor",
    "SEPARATE_XYZ": "ShaderNodeSeparateXYZ",
    "COMBINE_XYZ": "ShaderNodeCombineXYZ",
    "VALTORGB": "ShaderNodeValToRGB",
    "INVERT": "ShaderNodeInvert",
    "MAP_RANGE": "ShaderNodeMapRange",
    "CLAMP": "ShaderNodeClamp",
    "HUE_SAT": "ShaderNodeHueSaturation",
    "BRIGHTCONTRAST": "ShaderNodeBrightContrast",
    "GAMMA": "ShaderNodeGamma",
    "UVMAP": "ShaderNodeUVMap",
    "TEX_COORD": "ShaderNodeTexCoord",
    "MAPPING": "ShaderNodeMapping",
    "VALUE": "ShaderNodeValue",
    "RGB": "ShaderNodeRGB",
    "GROUP": "ShaderNodeGroup",
}

_MAX_CLONE_DEPTH = 24


def _resolve_node_idname(node: bpy.types.Node) -> str:
    """Resolves Blender bl_idname for a source shader node with mock-friendly type fallback."""
    bl_id = node.bl_idname
    if isinstance(bl_id, str) and bl_id.startswith("ShaderNode"):
        return bl_id
    node_type = str(node.type or "")
    return _NODE_TYPE_TO_IDNAME.get(node_type, "")


def _copy_tex_image_props(src_node: bpy.types.Node, dst_node: bpy.types.Node) -> None:
    """Copies image reference and sampling settings from a ShaderNodeTexImage."""
    src_tex = cast("bpy.types.ShaderNodeTexImage", src_node)
    if not src_tex.image:
        return
    dst_tex = cast("bpy.types.ShaderNodeTexImage", dst_node)
    dst_tex.image = src_tex.image
    for prop, val in (
        ("extension", src_tex.extension),
        ("interpolation", src_tex.interpolation),
        ("projection", src_tex.projection),
        ("projection_blend", src_tex.projection_blend),
    ):
        set_node_prop(dst_node, prop, val)


def _copy_color_ramp_props(src_node: bpy.types.Node, dst_node: bpy.types.Node) -> None:
    """Copies stops and interpolation modes from a ShaderNodeValToRGB."""
    src_ramp = cast("bpy.types.ShaderNodeValToRGB", src_node).color_ramp
    dst_ramp = cast("bpy.types.ShaderNodeValToRGB", dst_node).color_ramp
    if not src_ramp or not dst_ramp:
        return
    dst_ramp.color_mode = src_ramp.color_mode
    dst_ramp.interpolation = src_ramp.interpolation
    while len(dst_ramp.elements) > len(src_ramp.elements) and len(dst_ramp.elements) > 1:
        dst_ramp.elements.remove(dst_ramp.elements[-1])
    for idx, src_el in enumerate(src_ramp.elements):
        dst_el = dst_ramp.elements[idx] if idx < len(dst_ramp.elements) else dst_ramp.elements.new(src_el.position)
        dst_el.position = src_el.position
        dst_el.color = src_el.color


def _copy_node_attributes(src_node: bpy.types.Node, dst_node: bpy.types.Node, idname: str) -> None:
    """Copies relevant configuration properties from a source shader node without dynamic getattr."""
    try:
        if idname == "ShaderNodeTexImage":
            _copy_tex_image_props(src_node, dst_node)
        elif idname == "ShaderNodeMath":
            m_src = cast("bpy.types.ShaderNodeMath", src_node)
            set_node_prop(dst_node, "operation", m_src.operation)
            set_node_prop(dst_node, "use_clamp", m_src.use_clamp)
        elif idname == "ShaderNodeVectorMath":
            set_node_prop(dst_node, "operation", cast("bpy.types.ShaderNodeVectorMath", src_node).operation)
        elif idname == "ShaderNodeMix":
            mx_src = cast("bpy.types.ShaderNodeMix", src_node)
            for prop, val in (
                ("data_type", mx_src.data_type),
                ("blend_type", mx_src.blend_type),
                ("clamp_factor", mx_src.clamp_factor),
                ("clamp_result", mx_src.clamp_result),
            ):
                set_node_prop(dst_node, prop, val)
        elif idname == "ShaderNodeSeparateColor":
            set_node_prop(dst_node, "mode", cast("bpy.types.ShaderNodeSeparateColor", src_node).mode)
        elif idname == "ShaderNodeCombineColor":
            set_node_prop(dst_node, "mode", cast("bpy.types.ShaderNodeCombineColor", src_node).mode)
        elif idname == "ShaderNodeMapRange":
            mr_src = cast("bpy.types.ShaderNodeMapRange", src_node)
            for prop, val in (
                ("interpolation_type", mr_src.interpolation_type),
                ("clamp", mr_src.clamp),
                ("data_type", mr_src.data_type),
            ):
                set_node_prop(dst_node, prop, val)
        elif idname == "ShaderNodeMapping":
            set_node_prop(dst_node, "vector_type", cast("bpy.types.ShaderNodeMapping", src_node).vector_type)
        elif idname == "ShaderNodeUVMap":
            set_node_prop(dst_node, "uv_map", cast("bpy.types.ShaderNodeUVMap", src_node).uv_map)
        elif idname == "ShaderNodeGroup":
            set_node_prop(dst_node, "node_tree", cast("bpy.types.ShaderNodeGroup", src_node).node_tree)
        elif idname == "ShaderNodeValToRGB":
            _copy_color_ramp_props(src_node, dst_node)
    except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
        logger.debug("Partial node attribute copy for %s: %s", idname, exc)


def _find_socket_index(sockets: object, target_sock: object) -> int:
    """Finds the positional index of a node socket, returning -1 if not found."""
    try:
        for idx, sock in enumerate(sockets):  # type: ignore[arg-type]
            if sock == target_sock:
                return idx
    except TypeError as exc:
        logger.debug("Socket collection not iterable: %s", exc)
    return -1


def _resolve_output_socket(
    src_node: bpy.types.Node,
    src_sock: bpy.types.NodeSocket | None,
    dst_node: bpy.types.Node,
) -> bpy.types.NodeSocket | None:
    """Resolves the corresponding output socket on a cloned node by index, then name."""
    if src_sock is not None:
        idx = _find_socket_index(src_node.outputs, src_sock)
        if idx >= 0:
            try:
                return dst_node.outputs[idx]
            except (IndexError, KeyError, TypeError) as exc:
                logger.debug("Indexed output lookup failed (%d): %s", idx, exc)
        sock_name = src_sock.name or ""
        if sock_name and sock_name in dst_node.outputs:
            return dst_node.outputs[sock_name]
    if "Color" in dst_node.outputs:
        return dst_node.outputs["Color"]
    if "Value" in dst_node.outputs:
        return dst_node.outputs["Value"]
    return None


def _read_scalar_socket(bsdf: bpy.types.Node | None, sock_name: str, default: float) -> float:
    """Reads an unlinked float scalar input from a Principled BSDF with safe fallback."""
    if not bsdf or sock_name not in bsdf.inputs:
        return default
    sock = bsdf.inputs[sock_name]
    if sock.is_linked:
        return default
    try:
        raw = get_socket_default_value(sock, default)
        if isinstance(raw, (int, float)):
            return float(raw)
    except (ValueError, TypeError) as exc:
        logger.debug("Scalar socket read fallback for %s: %s", sock_name, exc)
    return default


class ImpostorShaderHarness:
    """
    Constructs unlit emission shader overrides for isolated impostor baking passes.
    Supports Alpha cutout preservation across all passes so foliage/leaf cards render with
    exact silhouette matching.
    """

    @classmethod
    def create_unlit_override_material(
        cls,
        source_mat: Optional[bpy.types.Material],
        channel_layer: str = "BASE_COLOR",
        target_engine: str = "UE5",
        radius: float = 1.0,
        cam_distance: float = 2.5,
        *,
        blend_data: BlendData,
    ) -> Optional[bpy.types.Material]:
        """
        Creates an ephemeral unlit material for baking a specific PBR or depth pass.
        Preserves alpha cutouts from the source material across all passes.
        """
        if not bpy:
            return None

        bdata = blend_data
        if bdata is None or bdata.materials is None:
            return None

        mat = bdata.materials.new(f"OM_Bake_{channel_layer}")
        mat.use_nodes = True
        if not mat.node_tree:
            raise ImpostorBakeError("Material has no node tree.")
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out_node = nodes.new(type="ShaderNodeOutputMaterial")
        out_node.location = (600, 0)
        emit_node = nodes.new(type="ShaderNodeEmission")
        emit_node.location = (150, 0)

        src_bsdf: bpy.types.Node | None = None
        if source_mat and source_mat.use_nodes and source_mat.node_tree:
            src_bsdf = next((n for n in source_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)

        # 1. BaseColor Pass
        if channel_layer == "BASE_COLOR":
            base_links = src_bsdf.inputs["Base Color"].links if src_bsdf and "Base Color" in src_bsdf.inputs else None
            if src_bsdf and "Base Color" in src_bsdf.inputs and src_bsdf.inputs["Base Color"].is_linked and base_links:
                src_link = base_links[0]
                cls._duplicate_link_to_target(src_link, nodes, links, emit_node.inputs["Color"])
            elif src_bsdf and "Base Color" in src_bsdf.inputs:
                set_socket_default_value(
                    emit_node.inputs["Color"], get_socket_default_value(src_bsdf.inputs["Base Color"])
                )
            else:
                set_socket_default_value(emit_node.inputs["Color"], (0.8, 0.8, 0.8, 1.0))

        # 2. Camera-Space Normal Pass
        elif channel_layer == "NORMAL":
            geom_node = nodes.new(type="ShaderNodeNewGeometry")
            geom_node.location = (-350, 0)
            vec_trans = nodes.new(type="ShaderNodeVectorTransform")
            setattr(vec_trans, "vector_type", "NORMAL")  # noqa: B010
            setattr(vec_trans, "convert_from", "WORLD")  # noqa: B010
            setattr(vec_trans, "convert_to", "CAMERA")  # noqa: B010
            vec_trans.location = (-180, 0)
            links.new(geom_node.outputs["Normal"], vec_trans.inputs["Vector"])

            vec_math = nodes.new(type="ShaderNodeVectorMath")
            setattr(vec_math, "operation", "MULTIPLY_ADD")  # noqa: B010
            vec_math.location = (0, 0)

            if target_engine == "UE5":
                # DirectX normal convention: Invert Green channel (-Y), camera forward (-Z) -> tangent (+Z)
                set_socket_default_value(vec_math.inputs[1], (0.5, -0.5, -0.5))
            else:
                # OpenGL standard: +Y is Up, camera forward (-Z) -> tangent (+Z)
                set_socket_default_value(vec_math.inputs[1], (0.5, 0.5, -0.5))

            set_socket_default_value(vec_math.inputs[2], (0.5, 0.5, 0.5))
            links.new(vec_trans.outputs["Vector"], vec_math.inputs[0])
            links.new(vec_math.outputs["Vector"], emit_node.inputs["Color"])

        # 3. Planar Z-Depth Pass
        elif channel_layer == "DEPTH":
            cam_data = nodes.new(type="ShaderNodeCameraData")
            cam_data.location = (-350, 0)

            map_range = nodes.new(type="ShaderNodeMapRange")
            map_range.location = (-100, 0)
            setattr(map_range, "clamp", True)  # noqa: B010

            # Near and far boundaries of the bounding sphere relative to camera
            from_min = max(0.01, cam_distance - radius)
            from_max = cam_distance + radius

            set_socket_default_value(map_range.inputs["From Min"], from_min)
            set_socket_default_value(map_range.inputs["From Max"], from_max)
            set_socket_default_value(map_range.inputs["To Min"], 0.0)
            set_socket_default_value(map_range.inputs["To Max"], 1.0)

            # Planar Z Depth strictly matches parallel rays of orthographic camera
            links.new(cam_data.outputs["View Z Depth"], map_range.inputs["Value"])
            links.new(map_range.outputs["Result"], emit_node.inputs["Color"])

        # 4. ORM (MaskMap) Pass
        elif channel_layer == "ORM":
            comb_node = nodes.new(type="ShaderNodeCombineColor")
            comb_node.location = (-50, 0)
            cloned: dict[int, bpy.types.Node] = {}

            if target_engine in {"UNITY", "UNITY_6"}:
                # Unity MaskMap bake pass: R=Metallic, G=AO (1.0), B=Smoothness (1-Roughness) for post-bake B->A packing
                cls._wire_orm_channel(src_bsdf, "Metallic", 0.0, comb_node.inputs["Red"], nodes, links, cloned)
                set_socket_default_value(comb_node.inputs["Green"], 1.0)
                cls._wire_orm_channel(
                    src_bsdf,
                    "Roughness",
                    0.5,
                    comb_node.inputs["Blue"],
                    nodes,
                    links,
                    cloned,
                    invert=True,
                )
            else:
                # UE5, MSFS 2024: R=AO, G=Roughness, B=Metallic
                set_socket_default_value(comb_node.inputs["Red"], 1.0)
                cls._wire_orm_channel(src_bsdf, "Roughness", 0.5, comb_node.inputs["Green"], nodes, links, cloned)
                cls._wire_orm_channel(src_bsdf, "Metallic", 0.0, comb_node.inputs["Blue"], nodes, links, cloned)

            links.new(comb_node.outputs["Color"], emit_node.inputs["Color"])

        # Transparency Handling across all passes (preserves cutout & blended/glass visibility in Cycles)
        cls._wire_transparency_output(src_bsdf, emit_node, out_node, mat, nodes, links)

        return mat

    @classmethod
    def _wire_orm_channel(
        cls,
        src_bsdf: bpy.types.Node | None,
        sock_name: str,
        default_val: float,
        target_socket: bpy.types.NodeSocket,
        nodes: bpy.types.Nodes,
        links: bpy.types.NodeLinks,
        cloned: dict[int, bpy.types.Node],
        *,
        invert: bool = False,
    ) -> None:
        """Wires an ORM/MaskMap scalar channel, cloning upstream texture/math links if present."""
        if src_bsdf and sock_name in src_bsdf.inputs:
            src_sock = src_bsdf.inputs[sock_name]
            if src_sock.is_linked and src_sock.links:
                if invert:
                    inv_node = nodes.new(type="ShaderNodeMath")
                    set_node_prop(inv_node, "operation", "SUBTRACT")
                    set_socket_default_value(inv_node.inputs[0], 1.0)
                    inv_node.location = (-200, -100)
                    cls._duplicate_link_to_target(src_sock.links[0], nodes, links, inv_node.inputs[1], cloned=cloned)
                    links.new(inv_node.outputs["Value"], target_socket)
                else:
                    cls._duplicate_link_to_target(src_sock.links[0], nodes, links, target_socket, cloned=cloned)
                return

        val = _read_scalar_socket(src_bsdf, sock_name, default_val)
        set_socket_default_value(target_socket, 1.0 - val if invert else val)

    @classmethod
    def _wire_transparency_output(
        cls,
        src_bsdf: bpy.types.Node | None,
        emit_node: bpy.types.Node,
        out_node: bpy.types.Node,
        mat: bpy.types.Material,
        nodes: bpy.types.Nodes,
        links: bpy.types.NodeLinks,
    ) -> None:
        """Routes Surface output through Transparent BSDF MixShader when source material has alpha or glass."""
        alpha_sock = src_bsdf.inputs["Alpha"] if (src_bsdf and "Alpha" in src_bsdf.inputs) else None
        alpha_linked = bool(alpha_sock is not None and alpha_sock.is_linked and alpha_sock.links)
        alpha_scalar = _read_scalar_socket(src_bsdf, "Alpha", 1.0)
        trans_scalar = _read_scalar_socket(src_bsdf, "Transmission Weight", 0.0)

        if not alpha_linked and alpha_scalar >= 0.999 and trans_scalar <= 0.1:
            links.new(emit_node.outputs["Emission"], out_node.inputs["Surface"])
            return

        transp_node = nodes.new(type="ShaderNodeBsdfTransparent")
        transp_node.location = (200, -150)
        mix_node = nodes.new(type="ShaderNodeMixShader")
        mix_node.location = (400, 0)
        links.new(transp_node.outputs["BSDF"], mix_node.inputs[1])
        links.new(emit_node.outputs["Emission"], mix_node.inputs[2])
        links.new(mix_node.outputs["Shader"], out_node.inputs["Surface"])

        if alpha_linked and alpha_sock is not None and alpha_sock.links:
            cls._duplicate_link_to_target(alpha_sock.links[0], nodes, links, mix_node.inputs["Fac"])
        else:
            effective_fac = alpha_scalar if alpha_scalar < 0.999 else max(0.15, 1.0 - 0.85 * trans_scalar)
            set_socket_default_value(mix_node.inputs["Fac"], effective_fac)

        mat.surface_render_method = "BLENDED"

    @classmethod
    def _duplicate_link_to_target(
        cls,
        link: bpy.types.NodeLink,
        target_nodes: bpy.types.Nodes,
        target_links: bpy.types.NodeLinks,
        target_socket: bpy.types.NodeSocket,
        *,
        cloned: dict[int, bpy.types.Node] | None = None,
        depth: int = 0,
    ) -> None:
        """Recursively clones an upstream shader subgraph to feed unlit emission, ORM, or alpha sockets."""
        from_node = link.from_node
        if not from_node or depth > _MAX_CLONE_DEPTH:
            return

        node_idname = _resolve_node_idname(from_node)
        if not node_idname:
            return

        cache = cloned if cloned is not None else {}
        node_key = id(from_node)
        dst_node = cache.get(node_key)
        if dst_node is None:
            dst_node = target_nodes.new(type=node_idname)
            dst_node.location = (-250 - depth * 180, 0)
            _copy_node_attributes(from_node, dst_node, node_idname)
            cache[node_key] = dst_node
            cls._clone_node_inputs(from_node, dst_node, target_nodes, target_links, cache, depth)

        out_sock = _resolve_output_socket(from_node, link.from_socket, dst_node)
        if out_sock is None:
            if "Alpha" in (target_socket.name or "") and "Alpha" in dst_node.outputs:
                out_sock = dst_node.outputs["Alpha"]
            elif "Color" in dst_node.outputs:
                out_sock = dst_node.outputs["Color"]
        if out_sock is not None:
            target_links.new(out_sock, target_socket)

    @classmethod
    def _clone_node_inputs(
        cls,
        src_node: bpy.types.Node,
        dst_node: bpy.types.Node,
        target_nodes: bpy.types.Nodes,
        target_links: bpy.types.NodeLinks,
        cache: dict[int, bpy.types.Node],
        depth: int,
    ) -> None:
        """Clones socket defaults and upstream links by positional socket index."""
        try:
            src_inputs = list(src_node.inputs)
        except TypeError:
            return
        for idx, src_in in enumerate(src_inputs):
            try:
                dst_in = dst_node.inputs[idx]
            except (IndexError, KeyError, TypeError):
                continue
            if src_in.is_linked and src_in.links:
                cls._duplicate_link_to_target(
                    src_in.links[0], target_nodes, target_links, dst_in, cloned=cache, depth=depth + 1
                )
            else:
                try:
                    default_val = get_socket_default_value(src_in)
                    if default_val is not None:
                        set_socket_default_value(dst_in, default_val)
                except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
                    logger.debug("Skipped copying input default [%d]: %s", idx, exc)


__all__ = ["ImpostorShaderHarness"]
