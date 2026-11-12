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


from .compat import get_socket_default_value, set_socket_default_value

from .exceptions import ImpostorBakeError


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

            rough_val = 0.5
            metal_val = 0.0
            if src_bsdf:
                if "Roughness" in src_bsdf.inputs and not src_bsdf.inputs["Roughness"].is_linked:
                    try:
                        rough_val = float(get_socket_default_value(src_bsdf.inputs["Roughness"], 0.5))  # type: ignore[arg-type]
                    except (ValueError, TypeError):
                        rough_val = 0.5
                if "Metallic" in src_bsdf.inputs and not src_bsdf.inputs["Metallic"].is_linked:
                    try:
                        metal_val = float(get_socket_default_value(src_bsdf.inputs["Metallic"], 0.0))  # type: ignore[arg-type]
                    except (ValueError, TypeError):
                        metal_val = 0.0

            if target_engine == "UNITY":
                # Unity standard MaskMap: R=Metallic, G=AO (1.0), B=Detail Mask (0.0), A=Smoothness (1-Roughness)
                set_socket_default_value(comb_node.inputs["Red"], metal_val)
                set_socket_default_value(comb_node.inputs["Green"], 1.0)
                set_socket_default_value(comb_node.inputs["Blue"], 1.0 - rough_val)
            else:
                # UE5, MSFS 2024: R=AO, G=Roughness, B=Metallic
                set_socket_default_value(comb_node.inputs["Red"], 1.0)
                set_socket_default_value(comb_node.inputs["Green"], rough_val)
                set_socket_default_value(comb_node.inputs["Blue"], metal_val)

            links.new(comb_node.outputs["Color"], emit_node.inputs["Color"])

        # Cutout Transparency Handling (Crucial for foliage / leaf cards across all passes)
        has_alpha_link = src_bsdf is not None and "Alpha" in src_bsdf.inputs and src_bsdf.inputs["Alpha"].is_linked

        if has_alpha_link and src_bsdf is not None:
            alpha_links = src_bsdf.inputs["Alpha"].links
            if alpha_links:
                transp_node = nodes.new(type="ShaderNodeBsdfTransparent")
                transp_node.location = (200, -150)
                mix_node = nodes.new(type="ShaderNodeMixShader")
                mix_node.location = (400, 0)

                # Input 1: Transparent (when Fac is 0)
                # Input 2: Emission (when Fac is 1)
                links.new(transp_node.outputs["BSDF"], mix_node.inputs[1])
                links.new(emit_node.outputs["Emission"], mix_node.inputs[2])
                links.new(mix_node.outputs["Shader"], out_node.inputs["Surface"])

                src_alpha_link = alpha_links[0]
                cls._duplicate_link_to_target(src_alpha_link, nodes, links, mix_node.inputs["Fac"])

            mat.surface_render_method = "DITHERED"
        else:
            links.new(emit_node.outputs["Emission"], out_node.inputs["Surface"])

        return mat

    @staticmethod
    def _duplicate_link_to_target(
        link: bpy.types.NodeLink,
        target_nodes: bpy.types.Nodes,
        target_links: bpy.types.NodeLinks,
        target_socket: bpy.types.NodeSocket,
    ) -> None:
        """Duplicates an upstream texture node to feed unlit emission or cutout alpha sockets."""
        from_node = link.from_node
        if from_node and from_node.type == "TEX_IMAGE":
            src_tex = cast("bpy.types.ShaderNodeTexImage", from_node)
            if src_tex.image:
                tex = target_nodes.new(type="ShaderNodeTexImage")
                cast("bpy.types.ShaderNodeTexImage", tex).image = src_tex.image
                tex.location = (-250, 0)
                from_socket_name = link.from_socket.name if link.from_socket else "Color"
                if from_socket_name in tex.outputs:
                    target_links.new(tex.outputs[from_socket_name], target_socket)
                elif "Alpha" in (target_socket.name or "") and "Alpha" in tex.outputs:
                    target_links.new(tex.outputs["Alpha"], target_socket)
                else:
                    target_links.new(tex.outputs["Color"], target_socket)


__all__ = ["ImpostorShaderHarness"]
