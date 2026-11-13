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
import time
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

    target_dir = os.path.dirname(os.path.abspath(filepath))

    # For 8-bit images, Pillow is faster if available
    if not is_16 and Image:
        mode_map = {0: "L", 2: "RGB", 6: "RGBA"}
        for attempt in range(3):
            try:
                pil_img = Image.fromarray(save_arr, mode=mode_map[color_type])
                os.makedirs(target_dir, exist_ok=True)
                pil_img.save(filepath, format="PNG", compress_level=4)
                return True
            except (PermissionError, OSError) as exc:
                if attempt < 2 and (isinstance(exc, PermissionError) or "WinError 32" in str(exc)):
                    time.sleep(0.05 * (2**attempt))
                    continue
                logger.debug("Pillow save fallback to raw PNG encoder: %s", exc)
                break
            except (ValueError, TypeError) as exc:
                logger.debug("Pillow save fallback to raw PNG encoder: %s", exc)
                break

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

    for attempt in range(3):
        try:
            os.makedirs(target_dir, exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(png_bytes)
            return True
        except (PermissionError, OSError) as exc:
            if attempt < 2 and (isinstance(exc, PermissionError) or "WinError 32" in str(exc)):
                time.sleep(0.05 * (2**attempt))
                continue
            logger.error("Failed to write PNG to '%s': %s", filepath, exc)
            return False

    return False


def _paeth_predictor(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Vectorized PNG Paeth predictor over matching integer arrays."""
    pa = np.abs(b - c)
    pb = np.abs(a - c)
    pc = np.abs(a + b - 2 * c)
    pred = np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))
    return pred


def _unfilter_png_scanlines(raw: bytes, width: int, height: int, channels: int, bit_depth: int) -> np.ndarray:
    """Decodes raw decompressed PNG scanlines (filters 0-4) into (H, W, C) array."""
    bytes_per_sample = bit_depth // 8
    bpp = channels * bytes_per_sample
    stride = width * bpp
    expected = height * (1 + stride)
    if len(raw) < expected:
        raise ValueError(f"Truncated PNG scanline stream: expected {expected} bytes, got {len(raw)}")

    rows = np.frombuffer(raw[:expected], dtype=np.uint8).reshape((height, 1 + stride))
    filter_types = rows[:, 0]
    scan_data = rows[:, 1:]

    # Fast path when all rows use Filter 0 (standard for OmniMesh write_png_direct PNGs)
    if not np.any(filter_types):
        recon = np.ascontiguousarray(scan_data)
    else:
        recon = np.zeros((height, stride), dtype=np.uint8)
        prev = np.zeros(stride, dtype=np.uint8)
        for y in range(height):
            ftype = int(filter_types[y])
            cur = scan_data[y]
            if ftype == 0:
                row_out = cur.copy()
            elif ftype == 1:
                row_out = cur.reshape((width, bpp)).cumsum(axis=0, dtype=np.uint8).reshape(stride)
            elif ftype == 2:
                row_out = (cur.astype(np.uint16) + prev.astype(np.uint16)).astype(np.uint8)
            elif ftype == 3:
                row_i = cur.astype(np.int32)
                prev_i = prev.astype(np.int32)
                out_row = np.zeros(stride, dtype=np.uint8)
                out_row[:bpp] = ((row_i[:bpp] + (prev_i[:bpp] >> 1)) & 0xFF).astype(np.uint8)
                for px in range(1, width):
                    s = px * bpp
                    e = s + bpp
                    left = out_row[s - bpp : s].astype(np.int32)
                    out_row[s:e] = ((row_i[s:e] + ((left + prev_i[s:e]) >> 1)) & 0xFF).astype(np.uint8)
                row_out = out_row
            elif ftype == 4:
                row_i = cur.astype(np.int32)
                prev_i = prev.astype(np.int32)
                out_row = np.zeros(stride, dtype=np.uint8)
                out_row[:bpp] = ((row_i[:bpp] + prev_i[:bpp]) & 0xFF).astype(np.uint8)
                for px in range(1, width):
                    s = px * bpp
                    e = s + bpp
                    a = out_row[s - bpp : s].astype(np.int32)
                    b = prev_i[s:e]
                    c = prev_i[s - bpp : s]
                    out_row[s:e] = ((row_i[s:e] + _paeth_predictor(a, b, c)) & 0xFF).astype(np.uint8)
                row_out = out_row
            else:
                raise ValueError(f"Unsupported PNG filter type: {ftype}")

            recon[y] = row_out
            prev = row_out

    if bit_depth == 16:
        arr_16 = recon.view(">u2").astype(np.uint16).reshape((height, width, channels))
        return np.ascontiguousarray(arr_16)
    arr_8 = recon.reshape((height, width, channels))
    return np.ascontiguousarray(arr_8)


def read_png_direct(filepath: str) -> np.ndarray:
    """Reads an 8-bit or 16-bit PNG file into a NumPy array without requiring bpy.data or PIL."""
    if not filepath or not os.path.isfile(filepath):
        raise FileNotFoundError(f"PNG file not found: {filepath}")

    with open(filepath, "rb") as f:
        blob = f.read()

    if len(blob) < 8 or blob[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"Invalid PNG signature in '{filepath}'")

    # Pillow silently truncates 16-bit RGB/RGBA PNGs to 8-bit uint8; only use PIL fast-path for 8-bit PNGs.
    is_16bit_ihdr = len(blob) >= 26 and blob[12:16] == b"IHDR" and blob[24] == 16
    if Image is not None and not is_16bit_ihdr:
        try:
            with Image.open(filepath) as pil_img:
                arr = np.asarray(pil_img)
                if arr.ndim == 2:
                    arr = arr[:, :, None]
                return np.ascontiguousarray(arr)
        except (OSError, ValueError, TypeError, EOFError) as exc:
            logger.debug("Pillow PNG read fallback to native decoder for '%s': %s", filepath, exc)

    pos = 8
    width = height = bit_depth = color_type = 0
    found_ihdr = False
    idat_chunks: list[bytes] = []

    while pos + 12 <= len(blob):
        length = struct.unpack(">I", blob[pos : pos + 4])[0]
        chunk_type = blob[pos + 4 : pos + 8]
        data_end = pos + 8 + length
        if data_end + 4 > len(blob):
            raise ValueError(f"Truncated PNG chunk '{chunk_type!r}' in '{filepath}'")
        chunk_data = blob[pos + 8 : data_end]
        pos = data_end + 4

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, comp, flt, interlace = struct.unpack(">IIBBBBB", chunk_data)
            if comp != 0 or flt != 0 or interlace != 0:
                raise ValueError(f"Unsupported PNG compression/filter/interlace in '{filepath}'")
            found_ihdr = True
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    if not found_ihdr or width <= 0 or height <= 0:
        raise ValueError(f"Missing or invalid PNG IHDR in '{filepath}'")

    channels_map = {0: 1, 2: 3, 4: 2, 6: 4}
    if color_type not in channels_map or bit_depth not in (8, 16):
        raise ValueError(f"Unsupported PNG color_type={color_type}, bit_depth={bit_depth} in '{filepath}'")

    raw = zlib.decompress(b"".join(idat_chunks))
    return _unfilter_png_scanlines(raw, width, height, channels_map[color_type], bit_depth)
