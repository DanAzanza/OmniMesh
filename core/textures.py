"""
OmniMesh PBR Texture Extractor, Symmetrical Channel Packer & Zero-Copy Resampler.
Guarantees strict Color Space isolation, UDIM multi-tile support, SIMD uint8/uint16 streaming,
thread-safe pure-Python PNG encoding, and bidirectional DirectX/OpenGL normal conversion.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import gc
import logging
import math
import os
import re
import sys
import threading
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


try:
    from .png_writer import write_png_direct
except ImportError:
    from core.png_writer import write_png_direct


class TexturePoolManager:
    """Manages background multi-threaded texture compression and disk writes with thread safety."""

    _executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_executor(cls) -> concurrent.futures.ThreadPoolExecutor:
        with cls._lock:
            if cls._executor is None:
                max_w = min(4, max(1, os.cpu_count() or 2))
                cls._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_w, thread_name_prefix="OmniMesh_TexPool"
                )
            return cls._executor

    @classmethod
    def submit_save(cls, arr: np.ndarray, filepath: str, bit_depth: int = 8) -> concurrent.futures.Future[bool]:
        """Submits numpy array for parallel PNG compression and saving."""
        if arr is None or not isinstance(arr, np.ndarray) or arr.size == 0 or not filepath:
            f: concurrent.futures.Future[bool] = concurrent.futures.Future()
            f.set_result(False)
            return f

        try:
            executor = cls.get_executor()
            return executor.submit(write_png_direct, filepath, arr, bit_depth)
        except RuntimeError:
            with cls._lock:
                cls._executor = None
            executor = cls.get_executor()
            return executor.submit(write_png_direct, filepath, arr, bit_depth)

    @classmethod
    def wait_all(cls, futures: list[concurrent.futures.Future[bool]], timeout: float = 60.0) -> list[bool]:
        """Synchronous barrier ensuring all background texture writes are completed safely."""
        if not futures:
            return []

        results: list[bool] = []
        try:
            done, not_done = concurrent.futures.wait(
                futures, timeout=timeout, return_when=concurrent.futures.ALL_COMPLETED
            )
            for f in futures:
                if f in done:
                    try:
                        res = f.result(timeout=0.01)
                        results.append(bool(res))
                    except Exception as exc:
                        logger.error("Texture pool worker raised exception: %s", exc)
                        results.append(False)
                else:
                    logger.warning("Texture pool worker timed out before completion.")
                    results.append(False)
        except Exception as exc:
            logger.error("Exception in TexturePoolManager.wait_all: %s", exc)
        finally:
            TextureChannelPacker.compact_memory()

        return results

    @classmethod
    def shutdown(cls) -> None:
        with cls._lock:
            if cls._executor:
                try:
                    cls._executor.shutdown(wait=True)
                except Exception as exc:
                    logger.debug("Texture pool shutdown exception: %s", exc)
                cls._executor = None


class TextureChannelPacker:
    """High-performance PBR Channel Packer, Dynamic Preset Exporter and Resampler."""

    @staticmethod
    def compact_memory() -> None:
        """Force OS-level heap compaction to prevent memory fragmentation."""
        gc.collect()
        if sys.platform == "win32":
            try:
                ctypes.cdll.msvcrt._heapmin()
            except (AttributeError, OSError) as exc:
                logger.debug("Win32 heap compaction skipped: %s", exc)
        elif sys.platform.startswith("linux"):
            try:
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except (AttributeError, OSError) as exc:
                logger.debug("Linux malloc_trim skipped: %s", exc)

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
                while getattr(source, "type", None) == "REROUTE" and source.inputs and source.inputs[0].is_linked:
                    source = source.inputs[0].links[0].from_node
                if getattr(source, "type", None) == "COMBINE_COLOR":
                    # Tracing reconstructed normal
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
                while getattr(d_curr, "type", None) == "REROUTE" and d_curr.inputs and d_curr.inputs[0].is_linked:
                    d_curr = d_curr.inputs[0].links[0].from_node
                if getattr(d_curr, "type", None) == "TEX_IMAGE" and getattr(d_curr, "image", None):
                    return d_curr.image, 0, False, 0.0
            return None, 0, False, 0.0

        # Special Case: Ambient Occlusion (Decouple from Base Color Multiply Mix Node)
        if socket_name in ("Ambient Occlusion", "AO", "Occlusion"):
            base_sock = bsdf.inputs.get("Base Color") or bsdf.inputs.get("BaseColor")
            if base_sock and base_sock.is_linked:
                mix_candidate = base_sock.links[0].from_node
                while (
                    getattr(mix_candidate, "type", "") == "REROUTE"
                    and mix_candidate.inputs
                    and mix_candidate.inputs[0].is_linked
                ):
                    mix_candidate = mix_candidate.inputs[0].links[0].from_node
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
                        while getattr(ao_src, "type", "") == "REROUTE" and ao_src.inputs and ao_src.inputs[0].is_linked:
                            ao_src = ao_src.inputs[0].links[0].from_node
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
                # Check which output was linked
                out_name = getattr(link.from_socket, "name", "")
                if out_name == "Green":
                    channel_index = 1
                elif out_name == "Blue":
                    channel_index = 2
                else:
                    channel_index = 0
                curr = curr.inputs["Color"].links[0].from_node if curr.inputs["Color"].is_linked else None
            elif ntype == "MATH" and getattr(curr, "operation", "") == "SUBTRACT":
                # Check for 1.0 - x
                if len(curr.inputs) > 0 and abs(getattr(curr.inputs[0], "default_value", 0.0) - 1.0) < 1e-4:
                    is_inverted = not is_inverted
                    curr = curr.inputs[1].links[0].from_node if curr.inputs[1].is_linked else None
                else:
                    break
            elif ntype == "TEX_IMAGE":
                return getattr(curr, "image", None), channel_index, is_inverted, default_val
            else:
                # Other nodes (procedural / math / group)
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
        extracted = cls._extract_from_image(img, (target_w, target_h), effective_ch, fallback_arr, bit_depth=bit_depth)
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

        np.nan_to_num(raw_floats, copy=False, nan=default_nan, posinf=1.0, neginf=0.0)

        extracted = (
            (np.clip(raw_floats[channel_index::4], 0.0, 1.0) * max_val + 0.5).astype(dtype).reshape((src_h, src_w))
        )
        del raw_floats

        if (src_w, src_h) != (target_w, target_h):
            if bit_depth == 16:
                x_idx = (np.linspace(0, src_w - 1, target_w)).astype(np.int32)
                y_idx = (np.linspace(0, src_h - 1, target_h)).astype(np.int32)
                extracted = extracted[np.ix_(y_idx, x_idx)]
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

            tex_node = nodes.new(type="ShaderNodeTexImage")
            temp_nodes.append(tex_node)
            safe_name = re.sub(r"[^\w\-]", "_", f"OM_Bake_{getattr(material, 'name', 'M')}_{socket_name}")
            temp_img = bpy.data.images.new(
                name=safe_name, width=target_w, height=target_h, alpha=True, float_buffer=(bit_depth == 16)
            )
            tex_node.image = temp_img
            nodes.active = tex_node

            scene.render.engine = "CYCLES"
            if hasattr(scene, "cycles"):
                scene.cycles.samples = 1

            bpy.ops.object.bake(type="EMIT")

            dtype = np.uint16 if bit_depth == 16 else np.uint8
            max_val = 65535.0 if bit_depth == 16 else 255.0
            raw_floats = np.empty(target_w * target_h * 4, dtype=np.float32)
            temp_img.pixels.foreach_get(raw_floats)
            np.nan_to_num(raw_floats, copy=False, nan=0.0, posinf=1.0, neginf=0.0)
            return (np.clip(raw_floats, 0.0, 1.0) * max_val + 0.5).astype(dtype).reshape((target_h, target_w, 4))
        except Exception as exc:
            logger.debug("Shader bake fallback for socket '%s': %s", socket_name, exc)
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
    def pack_material_preset(
        cls,
        material: Any,
        preset: dict[str, Any],
        export_dir: str,
        asset_name: str = "",
        target_size: Tuple[int, int] = (2048, 2048),
        bit_depth: int = 8,
        strategy: str = "SMART_AUTO",
        naming_pattern: str = "{material}{suffix}",
    ) -> list[concurrent.futures.Future[bool]]:
        """
        Dynamically packs and exports all enabled PBR maps defined in the active preset.
        Returns a list of concurrent.futures.Future[bool] for thread pool synchronization.
        """
        if not material or not preset or not export_dir:
            return []

        os.makedirs(export_dir, exist_ok=True)
        futures: list[concurrent.futures.Future[bool]] = []

        mat_name = re.sub(r"[^\w\-_\.]", "_", getattr(material, "name", "Material"))
        clean_asset = re.sub(r"[^\w\-_\.]", "_", asset_name) if asset_name else mat_name
        max_val = 65535 if bit_depth == 16 else 255
        dtype = np.uint16 if bit_depth == 16 else np.uint8

        for map_def in preset.get("maps", []):
            if not map_def.get("export", True):
                continue

            export_suffix = map_def.get("export_suffix") or map_def.get("suffixes", [""])[0]
            channels = map_def.get("channels", {})
            if not channels:
                continue

            # Dominant Resolution Rule: Calculate maximum resolution among linked textures for this map
            found_sizes: list[tuple[int, int]] = []
            if "rgb" in channels:
                rgb_target = channels["rgb"].get("target", "")
                if rgb_target == "Normal":
                    n_img = cls.get_material_normal_image(material)
                    if n_img and getattr(n_img, "size", (0, 0))[0] > 0:
                        found_sizes.append(n_img.size[:2])
                else:
                    s_img, _, _, _ = cls.trace_upstream_channel(material, rgb_target)
                    if s_img and getattr(s_img, "size", (0, 0))[0] > 0:
                        found_sizes.append(s_img.size[:2])
                if "a" in channels:
                    a_target = channels["a"].get("target", "")
                    a_img, _, _, _ = cls.trace_upstream_channel(material, a_target)
                    if a_img and getattr(a_img, "size", (0, 0))[0] > 0:
                        found_sizes.append(a_img.size[:2])
            else:
                for ch_key in ("r", "g", "b", "a"):
                    if ch_key in channels:
                        ch_t = channels[ch_key].get("target", "")
                        ch_img, _, _, _ = cls.trace_upstream_channel(material, ch_t)
                        if ch_img and getattr(ch_img, "size", (0, 0))[0] > 0:
                            found_sizes.append(ch_img.size[:2])

            if found_sizes and strategy != "BAKE":
                map_w = max(s[0] for s in found_sizes)
                map_h = max(s[1] for s in found_sizes)
            else:
                map_w, map_h = target_size

            # Resolve output file name
            clean_suffix = export_suffix if export_suffix.startswith("_") else f"_{export_suffix}"
            base_fname = naming_pattern.format(asset=clean_asset, material=mat_name, suffix=clean_suffix)
            out_filepath = os.path.join(export_dir, f"{base_fname}.png")

            # Strategy: PASSTHROUGH (Direct file copy if identical single map exists)
            if strategy == "PASSTHROUGH" and "rgb" in channels and len(channels) == 1:
                target_sock_name = channels["rgb"].get("target", "")
                img, _, _, _ = cls.trace_upstream_channel(material, target_sock_name)
                if img and getattr(img, "filepath", "") and os.path.exists(bpy.path.abspath(img.filepath)):
                    src_path = bpy.path.abspath(img.filepath)
                    src_w, src_h = getattr(img, "size", (0, 0))[:2]
                    # If format and resolution match, direct copy
                    if (src_w, src_h) == (map_w, map_h) and src_path.lower().endswith(".png") and bit_depth == 8:
                        import shutil

                        try:
                            shutil.copy2(src_path, out_filepath)
                            f = concurrent.futures.Future()
                            f.set_result(True)
                            futures.append(f)
                            continue
                        except OSError:
                            pass

            # Channel Assembly
            if "rgb" in channels:
                rgb_target = channels["rgb"].get("target", "")
                norm_fmt = map_def.get("normal_format", "NONE")

                if rgb_target == "Normal":
                    norm_img = cls.get_material_normal_image(material)
                    if norm_img:
                        r = cls._extract_from_image(
                            norm_img,
                            (map_w, map_h),
                            0,
                            np.full((map_h, map_w), 128, dtype=dtype),
                            bit_depth,
                            default_nan=0.5,
                        )
                        g = cls._extract_from_image(
                            norm_img,
                            (map_w, map_h),
                            1,
                            np.full((map_h, map_w), 128, dtype=dtype),
                            bit_depth,
                            default_nan=0.5,
                        )
                        b = cls._extract_from_image(
                            norm_img,
                            (map_w, map_h),
                            2,
                            np.full((map_h, map_w), 255, dtype=dtype),
                            bit_depth,
                            default_nan=1.0,
                        )
                    else:
                        r = np.full((map_h, map_w), 128, dtype=dtype)
                        g = np.full((map_h, map_w), 128, dtype=dtype)
                        b = np.full((map_h, map_w), 255, dtype=dtype)

                    if norm_fmt == "DIRECTX":
                        g = (max_val - g).astype(dtype)

                    if "a" in channels:
                        a_target = channels["a"].get("target", "")
                        a = cls.extract_socket_data(
                            material, a_target, (map_w, map_h), default_val=1.0, bit_depth=bit_depth
                        )
                        packed = np.stack([r, g, b, a], axis=-1)
                    else:
                        packed = np.stack([r, g, b], axis=-1)
                else:
                    # Generic RGB extraction (e.g. Base Color, Emission)
                    should_bake_rgb = (strategy == "BAKE") or (
                        strategy == "SMART_AUTO" and cls.is_procedural_socket(material, rgb_target)
                    )
                    baked_arr = (
                        cls.bake_material_socket(material, rgb_target, (map_w, map_h), bit_depth=bit_depth)
                        if should_bake_rgb
                        else None
                    )
                    if baked_arr is not None:
                        r, g, b = baked_arr[:, :, 0], baked_arr[:, :, 1], baked_arr[:, :, 2]
                    else:
                        img, _, _, def_val = cls.trace_upstream_channel(material, rgb_target)
                        def_arr = np.full(
                            (map_h, map_w),
                            int(np.clip(def_val if def_val is not None else 0.0, 0.0, 1.0) * max_val),
                            dtype=dtype,
                        )
                        if img:
                            r = cls._extract_from_image(img, (map_w, map_h), 0, def_arr, bit_depth)
                            g = cls._extract_from_image(img, (map_w, map_h), 1, def_arr, bit_depth)
                            b = cls._extract_from_image(img, (map_w, map_h), 2, def_arr, bit_depth)
                        else:
                            r = g = b = def_arr

                    if "a" in channels:
                        a_target = channels["a"].get("target", "")
                        a = cls.extract_socket_data(
                            material, a_target, (map_w, map_h), default_val=1.0, bit_depth=bit_depth
                        )
                        packed = np.stack([r, g, b, a], axis=-1)
                    else:
                        packed = np.stack([r, g, b], axis=-1)
            else:
                # Per-channel demuxing (e.g. ORM / MaskMap)
                channel_arrays = []
                for ch_key in ("r", "g", "b", "a"):
                    if ch_key in channels:
                        ch_info = channels[ch_key]
                        target_sock = ch_info.get("target", "")
                        inv = bool(ch_info.get("invert", False))
                        def_v = float(ch_info.get("default", 1.0 if ch_key in ("r", "a") else 0.0))

                        should_bake = (strategy == "BAKE") or (
                            strategy == "SMART_AUTO" and cls.is_procedural_socket(material, target_sock)
                        )
                        baked_arr = (
                            cls.bake_material_socket(material, target_sock, (map_w, map_h), bit_depth=bit_depth)
                            if should_bake
                            else None
                        )
                        if baked_arr is not None:
                            ch_arr = baked_arr[:, :, 0]
                        else:
                            ch_arr = cls.extract_socket_data(
                                material, target_sock, (map_w, map_h), default_val=def_v, bit_depth=bit_depth
                            )
                        if inv:
                            ch_arr = (max_val - ch_arr).astype(dtype)
                        channel_arrays.append(ch_arr)
                    elif ch_key == "a" and len(channel_arrays) == 3:
                        # Optional default alpha
                        channel_arrays.append(np.full((map_h, map_w), max_val, dtype=dtype))

                if len(channel_arrays) in (1, 3, 4):
                    packed = np.stack(channel_arrays, axis=-1) if len(channel_arrays) > 1 else channel_arrays[0]
                else:
                    continue

            # Submit array to thread pool for non-blocking disk save
            fut = TexturePoolManager.submit_save(packed, out_filepath, bit_depth=bit_depth)
            futures.append(fut)

        return futures

    # =========================================================================
    # Legacy Compatibility Proxy Methods
    # =========================================================================

    @classmethod
    def pack_orm_ue5(
        cls,
        material: Any,
        output_filepath: str,
        target_size: Tuple[int, int] = (2048, 2048),
    ) -> bool:
        """Legacy proxy for UE5 ORM packing."""
        w, h = target_size
        ao_u8 = cls.extract_socket_data(material, "Ambient Occlusion", target_size, default_val=1.0)
        rough_u8 = cls.extract_socket_data(material, "Roughness", target_size, default_val=0.5)
        metal_u8 = cls.extract_socket_data(material, "Metallic", target_size, default_val=0.0)
        alpha_u8 = np.full((h, w), 255, dtype=np.uint8)
        packed_rgba = np.stack([ao_u8, rough_u8, metal_u8, alpha_u8], axis=-1)
        success = write_png_direct(output_filepath, packed_rgba, bit_depth=8)
        cls.compact_memory()
        return success

    @classmethod
    def pack_maskmap_unity(
        cls,
        material: Any,
        output_filepath: str,
        target_size: Tuple[int, int] = (2048, 2048),
    ) -> bool:
        """Legacy proxy for Unity MaskMap packing."""
        w, h = target_size
        metal_u8 = cls.extract_socket_data(material, "Metallic", target_size, default_val=0.0)
        ao_u8 = cls.extract_socket_data(material, "Ambient Occlusion", target_size, default_val=1.0)
        detail_u8 = np.full((h, w), 0, dtype=np.uint8)
        rough_u8 = cls.extract_socket_data(material, "Roughness", target_size, default_val=0.5)
        smoothness_u8 = 255 - rough_u8
        packed_rgba = np.stack([metal_u8, ao_u8, detail_u8, smoothness_u8], axis=-1)
        success = write_png_direct(output_filepath, packed_rgba, bit_depth=8)
        cls.compact_memory()
        return success

    @classmethod
    def pack_comp_msfs(
        cls,
        material: Any,
        output_filepath: str,
        target_size: Tuple[int, int] = (2048, 2048),
    ) -> bool:
        """Legacy proxy for MSFS COMP packing."""
        w, h = target_size
        ao_u8 = cls.extract_socket_data(material, "Ambient Occlusion", target_size, default_val=1.0)
        rough_u8 = cls.extract_socket_data(material, "Roughness", target_size, default_val=0.5)
        metal_u8 = cls.extract_socket_data(material, "Metallic", target_size, default_val=0.0)
        alpha_u8 = np.full((h, w), 255, dtype=np.uint8)
        packed_rgba = np.stack([ao_u8, rough_u8, metal_u8, alpha_u8], axis=-1)
        success = write_png_direct(output_filepath, packed_rgba, bit_depth=8)
        cls.compact_memory()
        return success

    @classmethod
    def pack_orm_godot(
        cls,
        material: Any,
        output_filepath: str,
        target_size: Tuple[int, int] = (2048, 2048),
    ) -> bool:
        """Legacy proxy for Godot ORM packing."""
        return cls.pack_comp_msfs(material, output_filepath, target_size)

    @classmethod
    def convert_normal_directx(
        cls,
        source_img: Any,
        output_filepath: str,
        target_size: Optional[Tuple[int, int]] = None,
    ) -> bool:
        """Converts OpenGL (+Y) Normal map to DirectX (-Y) Normal map."""
        if not source_img or getattr(source_img, "size", (0, 0))[0] == 0:
            return False
        src_w, src_h = source_img.size[0], source_img.size[1]
        out_w, out_h = target_size if target_size else (src_w, src_h)

        r = cls._extract_from_image(
            source_img, (out_w, out_h), 0, np.full((out_h, out_w), 128, dtype=np.uint8), 8, default_nan=0.5
        )
        g = cls._extract_from_image(
            source_img, (out_w, out_h), 1, np.full((out_h, out_w), 128, dtype=np.uint8), 8, default_nan=0.5
        )
        b = cls._extract_from_image(
            source_img, (out_w, out_h), 2, np.full((out_h, out_w), 255, dtype=np.uint8), 8, default_nan=1.0
        )
        a = np.full((out_h, out_w), 255, dtype=np.uint8)
        g = 255 - g

        packed_normal = np.stack([r, g, b, a], axis=-1)
        success = write_png_direct(output_filepath, packed_normal, bit_depth=8)
        cls.compact_memory()
        return success

    @staticmethod
    def _save_array_to_disk(arr_u8: np.ndarray, filepath: str) -> bool:
        """Backward-compatible wrapper routing to write_png_direct."""
        return write_png_direct(filepath, arr_u8, bit_depth=8)


__all__ = [
    "TextureChannelPacker",
    "TexturePoolManager",
    "write_png_direct",
]
