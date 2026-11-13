"""
Engine-Independent Canonical Impostor Texture Repacker & PBR Preset Adapter.
Converts a single baked canonical Metalness Impostor texture set (BaseColor, OpenGL Normal + Depth,
Metalness ORM) into target-engine or custom PBR preset formats losslessly in memory without re-baking.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import logging
import os
import shutil
from typing import Any

import numpy as np

from .pbr_presets import PBRExportPresetManager
from .png_writer import read_png_direct, write_png_direct

logger = logging.getLogger(__name__)

_ENGINE_DEFAULT_PRESETS: dict[str, str] = {
    "UE5": "unreal_engine_5",
    "UNITY": "unity_hdrp_maskmap",
    "UNITY_6": "unity_hdrp_maskmap",
    "MSFS_2024": "msfs_2024_comp",
}

_SUPPORTED_CANONICAL_TARGETS: frozenset[str] = frozenset(
    {
        "Base Color",
        "Alpha",
        "Normal",
        "Ambient Occlusion",
        "Roughness",
        "Metallic",
        "Depth",
    }
)


@dataclass(frozen=True)
class CanonicalImpostorSources:
    """Resolved file paths and source channel convention for a baked Impostor master set."""

    base_name: str
    base_color_path: str
    normal_path: str
    orm_path: str
    source_convention: str = "CANONICAL"


def resolve_factory_preset_id_for_engine(target_engine: str) -> str:
    """Returns the default PBR export preset ID matching a game engine identifier."""
    return _ENGINE_DEFAULT_PRESETS.get(target_engine.upper(), "standard_pbr_split")


def resolve_preset_dict(preset: dict[str, Any] | None, target_engine: str) -> dict[str, Any]:
    """Resolves a PBR export preset dict or falls back to the engine's factory preset."""
    if preset and isinstance(preset, dict) and isinstance(preset.get("maps"), list):
        return preset
    preset_id = resolve_factory_preset_id_for_engine(target_engine)
    return PBRExportPresetManager.get_preset(preset_id)


def _to_rgba_u8(arr: np.ndarray, *, default_alpha: int = 255) -> np.ndarray:
    """Normalizes grayscale/RGB/RGBA 8-bit or 16-bit PNG arrays to (H, W, 4) uint8."""
    if arr.dtype == np.uint16:
        arr_u8 = (arr.astype(np.float32) * (255.0 / 65535.0) + 0.5).clip(0, 255).astype(np.uint8)
    elif arr.dtype != np.uint8:
        arr_u8 = np.clip(arr, 0, 255).astype(np.uint8)
    else:
        arr_u8 = arr

    if arr_u8.ndim == 2:
        h, w = arr_u8.shape
        out = np.empty((h, w, 4), dtype=np.uint8)
        out[:, :, :3] = arr_u8[:, :, None]
        out[:, :, 3] = default_alpha
        return out

    h, w, c = arr_u8.shape
    if c == 1:
        out = np.empty((h, w, 4), dtype=np.uint8)
        out[:, :, :3] = arr_u8
        out[:, :, 3] = default_alpha
        return out
    if c == 2:
        out = np.empty((h, w, 4), dtype=np.uint8)
        out[:, :, :3] = arr_u8[:, :, :1]
        out[:, :, 3] = arr_u8[:, :, 1]
        return out
    if c == 3:
        out = np.empty((h, w, 4), dtype=np.uint8)
        out[:, :, :3] = arr_u8
        out[:, :, 3] = default_alpha
        return out
    return np.ascontiguousarray(arr_u8[:, :, :4])


def _extract_canonical_channels(
    base_rgba: np.ndarray,
    norm_rgba: np.ndarray | None,
    orm_rgba: np.ndarray | None,
    source_convention: str,
) -> dict[str, np.ndarray]:
    """Normalizes baked Impostor arrays into engine-independent OpenGL + Metalness channels."""
    h, w = base_rgba.shape[:2]
    if norm_rgba is not None and norm_rgba.shape[:2] != (h, w):
        raise ValueError(
            f"Normal texture dimensions {norm_rgba.shape[1]}x{norm_rgba.shape[0]} do not match BaseColor {w}x{h}"
        )
    if orm_rgba is not None and orm_rgba.shape[:2] != (h, w):
        raise ValueError(
            f"ORM texture dimensions {orm_rgba.shape[1]}x{orm_rgba.shape[0]} do not match BaseColor {w}x{h}"
        )
    norm_conv = norm_rgba.copy() if norm_rgba is not None else np.zeros((h, w, 4), dtype=np.uint8)
    if norm_rgba is None:
        norm_conv[:, :, :4] = (128, 128, 255, 255)

    conv_upper = (source_convention or "CANONICAL").upper()
    if conv_upper in {"UE5", "DIRECTX"}:
        # Unflip UE5 DirectX -Y green channel back to canonical OpenGL +Y
        norm_conv[:, :, 1] = (255 - norm_conv[:, :, 1]).astype(np.uint8)

    if orm_rgba is not None:
        if conv_upper in {"UNITY", "UNITY_6"}:
            ao = orm_rgba[:, :, 1]
            roughness = (255 - orm_rgba[:, :, 3]).astype(np.uint8)
            metallic = orm_rgba[:, :, 0]
        else:
            ao = orm_rgba[:, :, 0]
            roughness = orm_rgba[:, :, 1]
            metallic = orm_rgba[:, :, 2]
    else:
        ao = np.full((h, w), 255, dtype=np.uint8)
        roughness = np.full((h, w), 128, dtype=np.uint8)
        metallic = np.zeros((h, w), dtype=np.uint8)

    return {
        "base_rgb": base_rgba[:, :, :3],
        "alpha": base_rgba[:, :, 3],
        "normal_rgb": norm_conv[:, :, :3],
        "depth": norm_conv[:, :, 3],
        "ao": ao,
        "roughness": roughness,
        "metallic": metallic,
    }


def _map_has_canonical_source(channels_cfg: Mapping[str, Any]) -> bool:
    """Returns True when at least one channel in map definition references a baked canonical target."""
    for ch_spec in channels_cfg.values():
        if isinstance(ch_spec, dict) and ch_spec.get("target") in _SUPPORTED_CANONICAL_TARGETS:
            return True
    return False


def _resolve_scalar_channel(
    ch_spec: Mapping[str, Any],
    canonical: Mapping[str, np.ndarray],
    shape_hw: tuple[int, int],
) -> np.ndarray:
    """Resolves a single grayscale channel from canonical arrays or spec default, applying invert if configured."""
    target = str(ch_spec.get("target", ""))
    invert = bool(ch_spec.get("invert", False))
    default_val = float(ch_spec.get("default", 0.0))

    target_key_map = {
        "Ambient Occlusion": "ao",
        "Roughness": "roughness",
        "Metallic": "metallic",
        "Alpha": "alpha",
        "Depth": "depth",
    }
    key = target_key_map.get(target)
    if key is not None:
        arr = canonical[key]
    elif target == "Base Color":
        arr = canonical["base_rgb"][:, :, 0]
    else:
        fill = int(round(max(0.0, min(1.0, default_val)) * 255.0))
        arr = np.full(shape_hw, fill, dtype=np.uint8)

    return (255 - arr).astype(np.uint8) if invert else arr


def _build_map_array(
    map_def: Mapping[str, Any],
    canonical: Mapping[str, np.ndarray],
) -> np.ndarray | None:
    """Packs one PBR Export Preset map array from canonical Metalness channels."""
    channels_cfg = map_def.get("channels")
    if not isinstance(channels_cfg, dict) or not _map_has_canonical_source(channels_cfg):
        return None

    h, w = canonical["alpha"].shape[:2]
    shape_hw = (h, w)

    if "rgb" in channels_cfg:
        rgb_spec = channels_cfg["rgb"]
        rgb_target = str(rgb_spec.get("target", ""))
        rgb_invert = bool(rgb_spec.get("invert", False))
        if rgb_target == "Normal":
            rgb = canonical["normal_rgb"].copy()
            normal_fmt = str(map_def.get("normal_format", "OPENGL")).upper()
            if normal_fmt == "DIRECTX":
                rgb[:, :, 1] = (255 - rgb[:, :, 1]).astype(np.uint8)
        elif rgb_target == "Base Color":
            rgb = (255 - canonical["base_rgb"]).astype(np.uint8) if rgb_invert else canonical["base_rgb"]
        elif rgb_target in {"Ambient Occlusion", "Roughness", "Metallic", "Alpha", "Depth"}:
            scalar = _resolve_scalar_channel(rgb_spec, canonical, shape_hw)
            rgb = np.stack([scalar, scalar, scalar], axis=-1)
        else:
            fill = int(round(max(0.0, min(1.0, float(rgb_spec.get("default", 0.0)))) * 255.0))
            rgb = np.full((h, w, 3), fill, dtype=np.uint8)

        if "a" in channels_cfg:
            alpha = _resolve_scalar_channel(channels_cfg["a"], canonical, shape_hw)
            return np.dstack([rgb, alpha])
        if rgb_target == "Normal":
            # Always preserve Planar Z-Depth in Normal.A so UE5 PDO & depth consumers keep precision
            return np.dstack([rgb, canonical["depth"]])
        return np.ascontiguousarray(rgb)

    if len(channels_cfg) == 1 and "r" in channels_cfg and isinstance(channels_cfg["r"], dict):
        return np.ascontiguousarray(_resolve_scalar_channel(channels_cfg["r"], canonical, shape_hw))

    if "r" in channels_cfg and "a" in channels_cfg and "g" not in channels_cfg and "b" not in channels_cfg:
        if isinstance(channels_cfg["r"], dict) and isinstance(channels_cfg["a"], dict):
            r_arr = _resolve_scalar_channel(channels_cfg["r"], canonical, shape_hw)
            a_arr = _resolve_scalar_channel(channels_cfg["a"], canonical, shape_hw)
            return np.stack([r_arr, r_arr, r_arr, a_arr], axis=-1)

    has_alpha = "a" in channels_cfg and isinstance(channels_cfg["a"], dict)
    ch_arrays: list[np.ndarray] = []
    for ch_key in ("r", "g", "b"):
        ch_spec = channels_cfg.get(ch_key)
        if isinstance(ch_spec, dict):
            ch_arrays.append(_resolve_scalar_channel(ch_spec, canonical, shape_hw))
        else:
            ch_arrays.append(np.zeros(shape_hw, dtype=np.uint8))

    if has_alpha:
        ch_arrays.append(_resolve_scalar_channel(channels_cfg["a"], canonical, shape_hw))
    else:
        ch_arrays.append(np.full(shape_hw, 255, dtype=np.uint8))

    return np.stack(ch_arrays, axis=-1)


def _resolve_map_suffix(map_def: Mapping[str, Any]) -> str:
    raw_suffix = str(map_def.get("export_suffix", "")).strip()
    clean_suffix = raw_suffix if raw_suffix.startswith("_") else (f"_{raw_suffix}" if raw_suffix else "")
    return clean_suffix or f"_{str(map_def.get('id', 'Map')).title()}"


def _prefer_master_sibling(filepath: str, base_name: str, master_suffix: str) -> str:
    """Returns sibling *_Master.png backup path when present so in-place repacked files never mask masters."""
    if not filepath or not os.path.isfile(filepath):
        return ""
    if filepath.endswith("_Master.png"):
        return filepath
    sibling = os.path.join(os.path.dirname(filepath), f"T_{base_name}_Impostor{master_suffix}")
    return sibling if os.path.isfile(sibling) else filepath


def find_canonical_impostor_sources(
    base_name: str,
    search_dirs: Sequence[str],
    material_paths: Mapping[str, str] | None = None,
    source_convention: str = "CANONICAL",
) -> CanonicalImpostorSources | None:
    """Locates baked Impostor BaseColor, Normal, and ORM textures from material links or search folders."""
    mat_map = dict(material_paths or {})
    base_p = _prefer_master_sibling(mat_map.get("BaseColor", ""), base_name, "_BaseColor_Master.png")
    norm_p = _prefer_master_sibling(mat_map.get("Normal", ""), base_name, "_Normal_Master.png")
    orm_p = _prefer_master_sibling(mat_map.get("ORM", ""), base_name, "_ORM_Master.png")

    for directory in search_dirs:
        if not directory:
            continue
        if not base_p:
            master_bc = os.path.join(directory, f"T_{base_name}_Impostor_BaseColor_Master.png")
            cand_bc = os.path.join(directory, f"T_{base_name}_Impostor_BaseColor.png")
            base_p = master_bc if os.path.isfile(master_bc) else (cand_bc if os.path.isfile(cand_bc) else "")
        if not norm_p:
            master_norm = os.path.join(directory, f"T_{base_name}_Impostor_Normal_Master.png")
            cand_norm = os.path.join(directory, f"T_{base_name}_Impostor_Normal.png")
            norm_p = master_norm if os.path.isfile(master_norm) else (cand_norm if os.path.isfile(cand_norm) else "")
        if not orm_p:
            master_orm = os.path.join(directory, f"T_{base_name}_Impostor_ORM_Master.png")
            cand_orm = os.path.join(directory, f"T_{base_name}_Impostor_ORM.png")
            orm_p = master_orm if os.path.isfile(master_orm) else (cand_orm if os.path.isfile(cand_orm) else "")

    if not base_p or not os.path.isfile(base_p):
        return None

    return CanonicalImpostorSources(
        base_name=base_name,
        base_color_path=base_p,
        normal_path=norm_p if norm_p and os.path.isfile(norm_p) else "",
        orm_path=orm_p if orm_p and os.path.isfile(orm_p) else "",
        source_convention=source_convention,
    )


def _backup_colliding_canonical_masters(
    sources: CanonicalImpostorSources,
    resolved_preset: Mapping[str, Any],
    output_dir: str,
    *,
    refresh_backups: bool = False,
) -> None:
    """Preserves pristine canonical master PNGs whenever an enabled preset map writes to the same path."""
    if sources.source_convention.upper() != "CANONICAL":
        return

    planned_outputs: set[str] = set()
    for map_def in resolved_preset.get("maps", []):
        if not isinstance(map_def, dict) or not map_def.get("export", True):
            continue
        channels_cfg = map_def.get("channels")
        if not isinstance(channels_cfg, dict) or not _map_has_canonical_source(channels_cfg):
            continue
        out_name = f"T_{sources.base_name}_Impostor{_resolve_map_suffix(map_def)}.png"
        planned_outputs.add(os.path.abspath(os.path.join(output_dir, out_name)))

    master_slots = (
        (sources.base_color_path, "_BaseColor_Master.png"),
        (sources.normal_path, "_Normal_Master.png"),
        (sources.orm_path, "_ORM_Master.png"),
    )
    for src_path, backup_suffix in master_slots:
        if not src_path or not os.path.isfile(src_path) or src_path.endswith("_Master.png"):
            continue
        if os.path.abspath(src_path) not in planned_outputs:
            continue
        backup_path = os.path.join(os.path.dirname(src_path), f"T_{sources.base_name}_Impostor{backup_suffix}")
        if refresh_backups or not os.path.isfile(backup_path):
            shutil.copy2(src_path, backup_path)


class ImpostorTextureRepacker:
    """Repacks engine-independent canonical Impostor textures into target PBR presets and companion shaders."""

    @classmethod
    def repack_impostor_textures(
        cls,
        sources: CanonicalImpostorSources,
        output_dir: str,
        target_engine: str = "UE5",
        preset: dict[str, Any] | None = None,
        refresh_master_backups: bool = False,
    ) -> dict[str, str]:
        """Repacks canonical Impostor master maps for the specified preset/engine without re-baking Cycles."""
        os.makedirs(output_dir, exist_ok=True)
        resolved_preset = resolve_preset_dict(preset, target_engine)
        bit_depth = 16 if int(resolved_preset.get("bit_depth", 8)) == 16 else 8

        base_rgba = _to_rgba_u8(read_png_direct(sources.base_color_path), default_alpha=0)
        norm_rgba = (
            _to_rgba_u8(read_png_direct(sources.normal_path), default_alpha=255)
            if sources.normal_path and os.path.isfile(sources.normal_path)
            else None
        )
        orm_rgba = (
            _to_rgba_u8(read_png_direct(sources.orm_path), default_alpha=255)
            if sources.orm_path and os.path.isfile(sources.orm_path)
            else None
        )

        canonical = _extract_canonical_channels(base_rgba, norm_rgba, orm_rgba, sources.source_convention)
        _backup_colliding_canonical_masters(
            sources,
            resolved_preset,
            output_dir,
            refresh_backups=refresh_master_backups,
        )

        written: dict[str, str] = {}
        for map_def in resolved_preset.get("maps", []):
            if not isinstance(map_def, dict) or not map_def.get("export", True):
                continue
            packed = _build_map_array(map_def, canonical)
            if packed is None:
                continue

            clean_suffix = _resolve_map_suffix(map_def)
            out_fname = f"T_{sources.base_name}_Impostor{clean_suffix}.png"
            out_path = os.path.join(output_dir, out_fname)
            is_srgb = str(map_def.get("color_space", "Non-Color")).lower() == "srgb"
            map_depth = 8 if is_srgb else bit_depth
            if write_png_direct(out_path, packed, bit_depth=map_depth):
                map_key = str(map_def.get("id") or clean_suffix.lstrip("_"))
                written[map_key] = out_path

        return written


__all__ = [
    "CanonicalImpostorSources",
    "ImpostorTextureRepacker",
    "find_canonical_impostor_sources",
    "resolve_factory_preset_id_for_engine",
    "resolve_preset_dict",
]
