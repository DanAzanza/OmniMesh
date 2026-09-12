"""
OmniMesh PBR Texture Extractor, Symmetrical Channel Packer & Zero-Copy Resampler.
Guarantees strict Color Space isolation, UDIM multi-tile support, SIMD uint8/uint16 streaming,
thread-safe pure-Python PNG encoding, and bidirectional DirectX/OpenGL normal conversion.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import re
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
    from .texture_pool import TexturePoolManager
    from .shader_tracer import ShaderTracer
    from .png_writer import write_png_direct
except ImportError:
    from core.texture_pool import TexturePoolManager
    from core.shader_tracer import ShaderTracer
    from core.png_writer import write_png_direct


class TextureChannelPacker:
    """High-performance PBR Channel Packer, Dynamic Preset Exporter and Resampler."""

    # Delegated shader node graph analysis and tracing
    get_material_normal_image = ShaderTracer.get_material_normal_image
    trace_upstream_channel = ShaderTracer.trace_upstream_channel
    extract_socket_data = ShaderTracer.extract_socket_data
    _extract_from_image = ShaderTracer._extract_from_image
    is_procedural_socket = ShaderTracer.is_procedural_socket
    bake_material_socket = ShaderTracer.bake_material_socket

    @staticmethod
    def compact_memory() -> None:
        """Force OS-level heap compaction to prevent memory fragmentation."""
        TexturePoolManager.compact_memory()

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
                            is_srgb = rgb_target.lower() in ("base color", "basecolor", "albedo", "emission")
                            r = cls._extract_from_image(
                                img, (map_w, map_h), 0, def_arr, bit_depth, apply_srgb_oetf=is_srgb
                            )
                            g = cls._extract_from_image(
                                img, (map_w, map_h), 1, def_arr, bit_depth, apply_srgb_oetf=is_srgb
                            )
                            b = cls._extract_from_image(
                                img, (map_w, map_h), 2, def_arr, bit_depth, apply_srgb_oetf=is_srgb
                            )
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
