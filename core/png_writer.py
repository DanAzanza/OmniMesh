"""
Pure-Python, thread-safe 8-bit and 16-bit PNG scanline compressor and writer.
Bypasses Pillow's limitation where PIL.Image.fromarray crashes on 16-bit RGB/RGBA uint16 arrays.
Completely thread-safe and avoids calling Blender's bpy C-API from worker threads.
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import zlib

import numpy as np

try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger(__name__)


def write_png_direct(filepath: str, arr: np.ndarray, bit_depth: int = 8) -> bool:
    """Thread-safe pure-Python PNG encoder supporting 8-bit and 16-bit Grayscale, RGB, and RGBA.

    Bypasses Pillow's limitation where PIL.Image.fromarray crashes on 16-bit RGB/RGBA uint16 arrays.
    Completely avoids calling Blender's bpy C-API from worker threads.
    """
    if arr is None or not isinstance(arr, np.ndarray) or arr.size == 0 or not filepath:
        return False

    is_16 = bit_depth == 16 or arr.dtype == np.uint16
    target_dtype = np.uint16 if is_16 else np.uint8
    actual_depth = 16 if is_16 else 8

    if arr.dtype != target_dtype:
        if is_16:
            arr = (arr.astype(np.float32) * (65535.0 / 255.0) + 0.5).clip(0, 65535).astype(np.uint16)
        else:
            arr = (arr.astype(np.float32) * (255.0 / 65535.0) + 0.5).clip(0, 255).astype(np.uint8)

    if arr.ndim == 2:
        h, w = arr.shape
        color_type = 0  # Grayscale
        channels = 1
        save_arr = arr
    elif arr.ndim == 3:
        h, w, channels = arr.shape
        if channels == 1:
            color_type = 0
            save_arr = arr.squeeze(axis=-1)
        elif channels == 3:
            color_type = 2  # RGB
            save_arr = arr
        elif channels == 4:
            color_type = 6  # RGBA
            save_arr = arr
        else:
            logger.error("Unsupported channel count in write_png_direct: %s", channels)
            return False
    else:
        logger.error("Unsupported array ndim in write_png_direct: %s", arr.ndim)
        return False

    # For 8-bit images, Pillow is faster if available
    if not is_16 and Image:
        mode_map = {0: "L", 2: "RGB", 6: "RGBA"}
        try:
            pil_img = Image.fromarray(save_arr, mode=mode_map[color_type])
            os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
            pil_img.save(filepath, format="PNG", compress_level=4)
            return True
        except Exception as exc:
            logger.debug("Pillow save fallback to raw PNG encoder: %s", exc)

    # Convert to big-endian (network byte order) for PNG
    if is_16 and sys.byteorder == "little":
        save_arr = save_arr.byteswap()

    bytes_per_sample = 2 if is_16 else 1
    row_bytes = w * channels * bytes_per_sample
    raw_scanlines = bytearray(h * (1 + row_bytes))
    arr_bytes = save_arr.tobytes()

    for row in range(h):
        idx_dst = row * (1 + row_bytes)
        raw_scanlines[idx_dst] = 0  # Filter type 0: None
        idx_src = row * row_bytes
        raw_scanlines[idx_dst + 1 : idx_dst + 1 + row_bytes] = arr_bytes[idx_src : idx_src + row_bytes]

    def make_chunk(chunk_type: bytes, data: bytes) -> bytes:
        length = struct.pack(">I", len(data))
        crc = struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        return length + chunk_type + data + crc

    ihdr_data = struct.pack(">IIBBBBB", w, h, actual_depth, color_type, 0, 0, 0)
    idat_data = zlib.compress(bytes(raw_scanlines), level=5)

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + make_chunk(b"IHDR", ihdr_data)
        + make_chunk(b"IDAT", idat_data)
        + make_chunk(b"IEND", b"")
    )

    try:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(png_bytes)
        return True
    except OSError as exc:
        logger.error("Failed to write PNG to '%s': %s", filepath, exc)
        return False
