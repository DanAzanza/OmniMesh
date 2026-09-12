"""
OmniMesh Shader AST Tracer & Socket Evaluator.
Provides AST shader node graph traversal, socket tracing, procedural detection,
and baking decoupling for PBR texture pipelines.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional, Tuple
import numpy as np

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import bpy
except ImportError:
    bpy = None

logger = logging.getLogger(__name__)


class ShaderTracer:
    """Extracts and traces Principled BSDF socket connections and upstream image datablocks."""

    @classmethod
    def get_material_normal_image(cls, material: Any) -> Optional[Any]:
        """Finds image datablock connected to Principled BSDF Normal socket."""
        if not material or not getattr(material, "use_nodes", False) or not material.node_tree:
            return None
        bsdf = next((n for n in material.node_tree.nodes if getattr(n, "type", None) == "BSDF_PRINCIPLED"), None)
        if not bsdf or "Normal" not in bsdf.inputs or not bsdf.inputs["Normal"].is_linked:
            return None

        link = bsdf.inputs["Normal"].links[0]
        from_node = link.from_node

        visited = {id(from_node)}
        while getattr(from_node, "type", None) == "REROUTE" and from_node.inputs and from_node.inputs[0].is_linked:
            from_node = from_node.inputs[0].links[0].from_node
            if id(from_node) in visited:
                break
            visited.add(id(from_node))

        if getattr(from_node, "type", None) in ("NORMAL_MAP", "BUMP"):
            sock = from_node.inputs.get("Color") or from_node.inputs.get("Height")
            if sock and sock.is_linked:
                source = sock.links[0].from_node
                visited_reroute = {id(source)}
                while getattr(source, "type", None) == "REROUTE" and source.inputs and source.inputs[0].is_linked:
                    source = source.inputs[0].links[0].from_node
                    if id(source) in visited_reroute:
                        break
                    visited_reroute.add(id(source))
                if getattr(source, "type", None) == "COMBINE_COLOR":
                    red_sock = source.inputs.get("Red")
                    if red_sock and red_sock.is_linked:
                        sep = red_sock.links[0].from_node
                        if getattr(sep, "type", None) == "SEPARATE_COLOR" and sep.inputs["Color"].is_linked:
                            source = sep.inputs["Color"].links[0].from_node
                if getattr(source, "type", None) == "TEX_IMAGE":
                    return getattr(source, "image", None)
        elif getattr(from_node, "type", None) == "TEX_IMAGE":
            return getattr(from_node, "image", None)
        return None

    @classmethod
    def trace_upstream_channel(
        cls, material: Any, socket_name: str
    ) -> tuple[Optional[Any], int, bool, Optional[float]]:
        """
        Traces socket upstream to locate: (image_datablock, channel_idx, is_inverted, default_val).
        Handles BSDF sockets, BaseColor/AO Mix decoupling, SeparateColor, and Math Invert.
        """
        if not material or not getattr(material, "use_nodes", False) or not material.node_tree:
            return None, 0, False, None

        nodes = getattr(material.node_tree, "nodes", [])
        bsdf = next((n for n in nodes if getattr(n, "type", None) == "BSDF_PRINCIPLED"), None)
        if not bsdf:
            return None, 0, False, None

        # Special Case: Displacement / Height
        if socket_name in ("Displacement", "Height"):
            out_node = next(
                (
                    n
                    for n in nodes
                    if getattr(n, "type", None) == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True)
                ),
                None,
            )
            if not out_node:
                out_node = next((n for n in nodes if getattr(n, "type", None) == "OUTPUT_MATERIAL"), None)
            if out_node and "Displacement" in out_node.inputs and out_node.inputs["Displacement"].is_linked:
                d_curr = out_node.inputs["Displacement"].links[0].from_node
                if getattr(d_curr, "type", None) == "DISPLACEMENT":
                    h_sock = d_curr.inputs.get("Height")
                    if h_sock and h_sock.is_linked:
                        d_curr = h_sock.links[0].from_node
                visited_d = {id(d_curr)}
                while getattr(d_curr, "type", None) == "REROUTE" and d_curr.inputs and d_curr.inputs[0].is_linked:
                    d_curr = d_curr.inputs[0].links[0].from_node
                    if id(d_curr) in visited_d:
                        break
                    visited_d.add(id(d_curr))
                if getattr(d_curr, "type", None) == "TEX_IMAGE" and getattr(d_curr, "image", None):
                    return d_curr.image, 0, False, 0.0
            return None, 0, False, 0.0

        # Special Case: Ambient Occlusion (Decouple from Base Color Multiply Mix Node)
        if socket_name in ("Ambient Occlusion", "AO", "Occlusion"):
            base_sock = bsdf.inputs.get("Base Color") or bsdf.inputs.get("BaseColor")
            if base_sock and base_sock.is_linked:
                mix_candidate = base_sock.links[0].from_node
                visited_mix = {id(mix_candidate)}
                while (
                    getattr(mix_candidate, "type", "") == "REROUTE"
                    and mix_candidate.inputs
                    and mix_candidate.inputs[0].is_linked
                ):
                    mix_candidate = mix_candidate.inputs[0].links[0].from_node
                    if id(mix_candidate) in visited_mix:
                        break
                    visited_mix.add(id(mix_candidate))
                if (
                    getattr(mix_candidate, "type", "") == "MIX"
                    and getattr(mix_candidate, "blend_type", "") == "MULTIPLY"
                ):
                    # Input B is AO in OmniMesh importer standard
                    b_sock = mix_candidate.inputs.get("B") or (
                        mix_candidate.inputs[7] if len(mix_candidate.inputs) > 7 else None
                    )
                    if b_sock and b_sock.is_linked:
                        ao_src = b_sock.links[0].from_node
                        visited_ao = {id(ao_src)}
                        while getattr(ao_src, "type", "") == "REROUTE" and ao_src.inputs and ao_src.inputs[0].is_linked:
                            ao_src = ao_src.inputs[0].links[0].from_node
                            if id(ao_src) in visited_ao:
                                break
                            visited_ao.add(id(ao_src))
                        ch_idx = 0
                        if getattr(ao_src, "type", "") == "SEPARATE_COLOR":
                            ch_idx = 0  # Red is AO in ORM
                            if ao_src.inputs["Color"].is_linked:
                                ao_src = ao_src.inputs["Color"].links[0].from_node
                        if getattr(ao_src, "type", "") == "TEX_IMAGE" and getattr(ao_src, "image", None):
                            return ao_src.image, ch_idx, False, 1.0

            # Fallback for unlinked AO / ORM image nodes in tree
            for node in nodes:
                if getattr(node, "type", None) == "TEX_IMAGE" and getattr(node, "image", None):
                    img_n = getattr(node.image, "name", "").lower()
                    if any(k in img_n for k in ("_ao", "ambient_occlusion", "occlusion", "_orm", "_comp")):
                        return node.image, 0, False, 1.0
            return None, 0, False, 1.0

        # Regular Socket Lookup with Canonical Aliases
        CANONICAL_ALIASES: dict[str, list[str]] = {
            "Specular IOR Level": ["Specular IOR Level", "Specular", "Specular Tint", "specular_ior_level"],
            "Transmission Weight": ["Transmission Weight", "Transmission", "transmission_weight"],
            "Emission Color": ["Emission Color", "Emission", "emission_color"],
            "Base Color": ["Base Color", "BaseColor", "Albedo", "Diffuse", "base_color"],
            "Roughness": ["Roughness", "roughness"],
            "Metallic": ["Metallic", "metallic"],
            "Alpha": ["Alpha", "Opacity", "alpha"],
        }
        candidate_names = CANONICAL_ALIASES.get(
            socket_name, [socket_name, socket_name.replace(" ", ""), socket_name.lower()]
        )
        socket = None
        for alias in candidate_names:
            socket = bsdf.inputs.get(alias)
            if socket:
                break

        default_val: Optional[float] = None
        if socket and hasattr(socket, "default_value"):
            dv = socket.default_value
            if isinstance(dv, (float, int)) and math.isfinite(dv):
                default_val = float(dv)
            elif isinstance(dv, (list, tuple)) and len(dv) > 0:
                try:
                    first = float(dv[0])
                    if math.isfinite(first):
                        default_val = first
                except (TypeError, ValueError, IndexError) as exc:
                    logger.debug("Default value parse error: %s", exc)

        if not socket or not getattr(socket, "is_linked", False):
            return None, 0, False, default_val

        # Follow upstream links
        link = socket.links[0]
        curr = link.from_node
        channel_index = 0
        is_inverted = False
        visited = {id(curr)}

        # Decouple Base Color from AO Mix node if present
        if socket_name in ("Base Color", "BaseColor", "Albedo") and getattr(curr, "type", "") == "MIX":
            if getattr(curr, "blend_type", "") == "MULTIPLY":
                # Socket A is clean Base Color
                a_sock = curr.inputs.get("A") or (curr.inputs[6] if len(curr.inputs) > 6 else None)
                if a_sock and a_sock.is_linked:
                    curr = a_sock.links[0].from_node

        while curr:
            ntype = getattr(curr, "type", "")
            if ntype == "REROUTE" and curr.inputs and curr.inputs[0].is_linked:
                curr = curr.inputs[0].links[0].from_node
            elif ntype in ("NORMAL_MAP", "BUMP"):
                nsock = curr.inputs.get("Color") or curr.inputs.get("Height")
                curr = nsock.links[0].from_node if (nsock and nsock.is_linked) else None
            elif ntype == "COMBINE_COLOR":
                red_sock = curr.inputs.get("Red")
                curr = red_sock.links[0].from_node if (red_sock and red_sock.is_linked) else None
            elif ntype == "SEPARATE_COLOR":
                out_name = getattr(link.from_socket, "name", "")
                if out_name == "Green":
                    channel_index = 1
                elif out_name == "Blue":
                    channel_index = 2
                else:
                    channel_index = 0
                curr = curr.inputs["Color"].links[0].from_node if curr.inputs["Color"].is_linked else None
            elif ntype == "MATH" and getattr(curr, "operation", "") == "SUBTRACT":
                if len(curr.inputs) > 0 and abs(getattr(curr.inputs[0], "default_value", 0.0) - 1.0) < 1e-4:
                    is_inverted = not is_inverted
                    curr = curr.inputs[1].links[0].from_node if curr.inputs[1].is_linked else None
                else:
                    break
            elif ntype == "TEX_IMAGE":
                return getattr(curr, "image", None), channel_index, is_inverted, default_val
            else:
                break

            if curr and id(curr) in visited:
                break
            if curr:
                visited.add(id(curr))

        return None, channel_index, is_inverted, default_val

    @classmethod
    def extract_socket_data(
        cls,
        material: Any,
        socket_name: str,
        target_size: Tuple[int, int],
        default_val: float = 0.0,
        channel_index: int = 0,
        bit_depth: int = 8,
        apply_srgb_oetf: bool = False,
    ) -> np.ndarray:
        """Extracts single-channel data from a Principled BSDF socket into a 2D uint8 or uint16 numpy array."""
        target_w = max(1, int(target_size[0]))
        target_h = max(1, int(target_size[1]))
        max_val = 65535.0 if bit_depth == 16 else 255.0
        dtype = np.uint16 if bit_depth == 16 else np.uint8

        img, ch_idx, is_inv, fallback_val = cls.trace_upstream_channel(material, socket_name)

        effective_default = fallback_val if fallback_val is not None else default_val

        fallback_arr = np.full((target_h, target_w), int(np.clip(effective_default, 0.0, 1.0) * max_val), dtype=dtype)

        if not img or getattr(img, "size", (0, 0))[0] == 0:
            return fallback_arr

        effective_ch = ch_idx if ch_idx != 0 else channel_index
        extracted = cls._extract_from_image(
            img,
            (target_w, target_h),
            effective_ch,
            fallback_arr,
            bit_depth=bit_depth,
            apply_srgb_oetf=apply_srgb_oetf,
        )
        if is_inv:
            extracted = (max_val - extracted).astype(dtype)
        return extracted

    @classmethod
    def _extract_from_image(
        cls,
        img: Any,
        target_size: Tuple[int, int],
        channel_index: int,
        fallback: np.ndarray,
        bit_depth: int = 8,
        default_nan: float = 0.0,
        apply_srgb_oetf: bool = False,
    ) -> np.ndarray:
        """Helper to extract a single channel from an image with SIMD/Pillow resizing."""
        target_w, target_h = target_size
        src_w, src_h = getattr(img, "size", (0, 0))[:2]
        if src_w == 0 or src_h == 0:
            return fallback

        dtype = np.uint16 if bit_depth == 16 else np.uint8
        max_val = 65535.0 if bit_depth == 16 else 255.0

        raw_floats = np.empty(src_w * src_h * 4, dtype=np.float32)
        try:
            img.pixels.foreach_get(raw_floats)
        except Exception as exc:
            logger.warning("Failed reading pixels from '%s': %s", getattr(img, "name", "unknown"), exc)
            return fallback
        finally:
            if hasattr(img, "buffers_free"):
                try:
                    img.buffers_free()
                except Exception as exc:
                    logger.debug("Failed freeing image buffers: %s", exc)

        np.nan_to_num(raw_floats, copy=False, nan=default_nan, posinf=1.0, neginf=0.0)

        ch_data = raw_floats[channel_index::4]
        if apply_srgb_oetf:
            # Linear to sRGB transfer function (IEC 61966-2-1) for Base Color / Albedo targets
            ch_data = np.where(
                ch_data <= 0.0031308,
                ch_data * 12.92,
                1.055 * np.power(np.maximum(ch_data, 1e-8), 1.0 / 2.4) - 0.055,
            )

        extracted = (np.clip(ch_data, 0.0, 1.0) * max_val + 0.5).astype(dtype).reshape((src_h, src_w))
        del raw_floats

        if (src_w, src_h) != (target_w, target_h):
            if bit_depth == 16 and Image:
                pil_img = Image.fromarray(extracted, mode="I;16")
                try:
                    resized = pil_img.resize((target_w, target_h), resample=Image.Resampling.BILINEAR)
                    extracted = np.asarray(resized).clip(0, 65535).astype(np.uint16)
                finally:
                    pil_img.close()
            elif Image:
                pil_img = Image.fromarray(extracted, mode="L")
                try:
                    resized = pil_img.resize((target_w, target_h), resample=Image.Resampling.BILINEAR)
                    extracted = np.asarray(resized)
                finally:
                    pil_img.close()
            else:
                x_idx = (np.linspace(0, src_w - 1, target_w)).astype(np.int32)
                y_idx = (np.linspace(0, src_h - 1, target_h)).astype(np.int32)
                extracted = extracted[np.ix_(y_idx, x_idx)]

        return extracted

    @classmethod
    def is_procedural_socket(cls, material: Any, socket_name: str) -> bool:
        """Determines if a socket is linked to procedural / non-image shader nodes."""
        if not material or not getattr(material, "use_nodes", False) or not material.node_tree:
            return False
        nodes = getattr(material.node_tree, "nodes", [])
        bsdf = next((n for n in nodes if getattr(n, "type", None) == "BSDF_PRINCIPLED"), None)
        if not bsdf:
            return False
        sock = bsdf.inputs.get(socket_name)
        if not sock:
            for alias in (socket_name, socket_name.replace(" ", ""), socket_name.lower()):
                sock = bsdf.inputs.get(alias)
                if sock:
                    break
        if not sock or not getattr(sock, "is_linked", False):
            return False
        img, _, _, _ = cls.trace_upstream_channel(material, socket_name)
        return img is None

    @classmethod
    def bake_material_socket(
        cls,
        material: Any,
        socket_name: str,
        target_size: Tuple[int, int],
        bit_depth: int = 8,
    ) -> Optional[np.ndarray]:
        """Bakes an evaluated shader socket to an image array using Cycles Emission bake."""
        if not bpy or not material or not getattr(material, "use_nodes", False) or not material.node_tree:
            return None

        act_obj = getattr(getattr(bpy, "context", None), "active_object", None)
        if not act_obj or getattr(act_obj, "type", "") != "MESH":
            return None

        target_w, target_h = max(1, int(target_size[0])), max(1, int(target_size[1]))
        nodes = material.node_tree.nodes
        links = material.node_tree.links
        bsdf = next((n for n in nodes if getattr(n, "type", None) == "BSDF_PRINCIPLED"), None)
        if not bsdf:
            return None

        sock = bsdf.inputs.get(socket_name)
        if not sock:
            for alias in (socket_name, socket_name.replace(" ", ""), socket_name.lower()):
                sock = bsdf.inputs.get(alias)
                if sock:
                    break
        if not sock or not sock.is_linked:
            return None

        out_node = next(
            (
                n
                for n in nodes
                if getattr(n, "type", None) == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True)
            ),
            None,
        )
        if not out_node:
            out_node = next((n for n in nodes if getattr(n, "type", None) == "OUTPUT_MATERIAL"), None)
        if not out_node or "Surface" not in out_node.inputs:
            return None

        surf_sock = out_node.inputs["Surface"]
        orig_surf_from = surf_sock.links[0].from_socket if surf_sock.is_linked else None

        scene = bpy.context.scene
        old_engine = scene.render.engine
        old_samples = getattr(getattr(scene, "cycles", None), "samples", 1)
        temp_nodes: list[Any] = []
        temp_img = None

        try:
            emit_node = nodes.new(type="ShaderNodeEmission")
            temp_nodes.append(emit_node)
            links.new(sock.links[0].from_socket, emit_node.inputs["Color"])
            links.new(emit_node.outputs["Emission"], surf_sock)

            temp_img = bpy.data.images.new(
                "_OM_Bake_Temp", width=target_w, height=target_h, alpha=False, float_buffer=(bit_depth == 16)
            )
            if hasattr(temp_img, "colorspace_settings"):
                try:
                    temp_img.colorspace_settings.name = "Non-Color"
                except Exception as exc:
                    logger.debug("Setting colorspace Non-Color skipped: %s", exc)
            tex_node = nodes.new(type="ShaderNodeTexImage")
            temp_nodes.append(tex_node)
            tex_node.image = temp_img
            nodes.active = tex_node

            scene.render.engine = "CYCLES"
            if hasattr(scene, "cycles"):
                scene.cycles.samples = 1

            bpy.ops.object.bake(type="EMIT", margin=0, use_clear=True)

            raw_floats = np.empty(target_w * target_h * 4, dtype=np.float32)
            temp_img.pixels.foreach_get(raw_floats)
            max_val = 65535.0 if bit_depth == 16 else 255.0
            dtype = np.uint16 if bit_depth == 16 else np.uint8
            res = (np.clip(raw_floats[0::4], 0.0, 1.0) * max_val + 0.5).astype(dtype).reshape((target_h, target_w))
            if hasattr(temp_img, "buffers_free"):
                temp_img.buffers_free()
            return res
        except Exception as exc:
            logger.debug("Bake execution fallback: %s", exc)
            return None
        finally:
            try:
                scene.render.engine = old_engine
                if hasattr(scene, "cycles"):
                    scene.cycles.samples = old_samples
                if orig_surf_from:
                    links.new(orig_surf_from, surf_sock)
                for tn in temp_nodes:
                    nodes.remove(tn)
                if temp_img and bpy and hasattr(bpy.data, "images"):
                    bpy.data.images.remove(temp_img, do_unlink=True)
            except Exception as exc:
                logger.debug("Bake cleanup skipped: %s", exc)
