"""
OmniMesh Companion Shader Generators.
Provides engine-specific shader generation for modern Octahedral Impostors.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import os
from typing import Any, Optional

from .unity_octahedral import generate_unity_octahedral_hlsl
from .unreal_octahedral import generate_ue5_setup_guide, generate_unreal_octahedral_hlsl

logger = logging.getLogger(__name__)


def export_companion_shaders(
    base_name: str,
    output_dir: str,
    target_engine: str = "ALL",
    grid_size: int = 8,
    alpha_scissor: float = 0.5,
    custom_params: Optional[dict[str, Any]] = None,
    mode: str = "OCTAHEDRAL_HEMI",
) -> dict[str, str]:
    """
    Generates and saves companion shader files for the specified engine(s).
    Supported engines: 'UNITY', 'UE5', 'ALL'.
    Returns dictionary mapping engine to generated shader filepath.
    """
    shader_dir = os.path.join(output_dir, "shaders")
    os.makedirs(shader_dir, exist_ok=True)
    results: dict[str, str] = {}

    engine_upper = target_engine.upper()

    if engine_upper in {"UNITY", "ALL"}:
        unity_code = generate_unity_octahedral_hlsl(
            base_name=base_name,
            grid_size=grid_size,
            custom_params=custom_params,
            mode=mode,
        )
        unity_path = os.path.join(shader_dir, f"{base_name}_Octahedral.hlsl")
        with open(unity_path, "w", encoding="utf-8") as f:
            f.write(unity_code)
        results["UNITY"] = unity_path
        logger.info("Exported Unity companion shader: %s", unity_path)

    if engine_upper in {"UE5", "ALL"}:
        unreal_code = generate_unreal_octahedral_hlsl(
            base_name=base_name,
            grid_size=grid_size,
            custom_params=custom_params,
            mode=mode,
        )
        unreal_path = os.path.join(shader_dir, f"{base_name}_Octahedral_UE5.hlsl")
        with open(unreal_path, "w", encoding="utf-8") as f:
            f.write(unreal_code)
        results["UE5"] = unreal_path
        logger.info("Exported Unreal Engine companion shader: %s", unreal_path)

    return results


def resolve_shader_engine_for_preset(preset_id: str, target_engine: str) -> str:
    """Maps an active PBR preset identifier and target engine into a companion shader target ('UE5', 'UNITY', 'ALL')."""
    pid_lower = (preset_id or "").lower()
    if "unity" in pid_lower:
        return "UNITY"
    if "unreal" in pid_lower or "ue5" in pid_lower:
        return "UE5"
    eng_upper = (target_engine or "UE5").upper()
    if eng_upper in {"UNITY", "UNITY_6"}:
        return "UNITY"
    return eng_upper


def _pick_repacked_filename(packed_maps: Mapping[str, str] | None, candidate_keys: tuple[str, ...]) -> str:
    if not packed_maps:
        return ""
    for key in candidate_keys:
        val = packed_maps.get(key)
        if val:
            return os.path.basename(val)
    return ""


def export_octahedral_companion_bundle(
    base_name: str,
    output_dir: str,
    target_engine: str = "ALL",
    grid_size: int = 8,
    sphere_radius: float = 1.0,
    sphere_center: tuple[float, float, float] = (0.0, 0.0, 0.0),
    mode: str = "OCTAHEDRAL_HEMI",
    packed_maps: Mapping[str, str] | None = None,
    alpha_scissor: float = 0.5,
    shader_exporter: Optional[Callable[..., dict[str, str]]] = None,
    write_guide: bool = True,
) -> dict[str, str]:
    """Exports companion octahedral HLSL shaders and, for UE5 targets, a filename-accurate setup guide."""
    exporter_fn = shader_exporter or export_companion_shaders
    results: dict[str, str] = {}
    if exporter_fn:
        shader_res = exporter_fn(
            base_name=base_name,
            output_dir=output_dir,
            target_engine=target_engine,
            grid_size=grid_size,
            alpha_scissor=alpha_scissor,
            mode=mode,
        )
        if isinstance(shader_res, dict):
            results.update(shader_res)

    if write_guide and target_engine.upper() in {"UE5", "ALL"} and mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
        os.makedirs(output_dir, exist_ok=True)
        guide_text = generate_ue5_setup_guide(
            base_name=base_name,
            grid_size=grid_size,
            sphere_radius=float(sphere_radius),
            sphere_center=sphere_center,
            mode=mode,
            normal_filename=_pick_repacked_filename(packed_maps, ("normal", "norm", "Normal")),
            orm_filename=_pick_repacked_filename(packed_maps, ("orm", "ORM", "comp")),
        )
        guide_path = os.path.join(output_dir, f"README_{base_name}_UE5_SETUP.txt")
        with open(guide_path, "w", encoding="utf-8") as gf:
            gf.write(guide_text)
        results["UE5_Guide"] = guide_path
        logger.info("Exported UE5 octahedral setup guide: %s", guide_path)

    return results


__all__ = [
    "generate_unity_octahedral_hlsl",
    "generate_unreal_octahedral_hlsl",
    "generate_ue5_setup_guide",
    "export_companion_shaders",
    "export_octahedral_companion_bundle",
    "resolve_shader_engine_for_preset",
]
