"""
OmniMesh Companion Shader Generators.
Provides engine-specific shader generation for modern Octahedral Impostors.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .godot_octahedral import generate_godot_octahedral_shader
from .unity_octahedral import generate_unity_octahedral_hlsl
from .unreal_octahedral import generate_unreal_octahedral_hlsl

logger = logging.getLogger(__name__)


def export_companion_shaders(
    base_name: str,
    output_dir: str,
    target_engine: str = "ALL",
    grid_size: int = 8,
    alpha_scissor: float = 0.5,
    custom_params: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    """
    Generates and saves companion shader files for the specified engine(s).
    Supported engines: 'GODOT', 'UNITY', 'UE5', 'ALL'.
    Returns dictionary mapping engine to generated shader filepath.
    """
    shader_dir = os.path.join(output_dir, "shaders")
    os.makedirs(shader_dir, exist_ok=True)
    results: dict[str, str] = {}

    engine_upper = target_engine.upper()

    if engine_upper in {"GODOT", "ALL"}:
        godot_code = generate_godot_octahedral_shader(
            base_name=base_name,
            grid_size=grid_size,
            alpha_scissor=alpha_scissor,
            custom_params=custom_params,
        )
        godot_path = os.path.join(shader_dir, f"{base_name}_Octahedral.gdshader")
        with open(godot_path, "w", encoding="utf-8") as f:
            f.write(godot_code)
        results["GODOT"] = godot_path
        logger.info("Exported Godot companion shader: %s", godot_path)

    if engine_upper in {"UNITY", "ALL"}:
        unity_code = generate_unity_octahedral_hlsl(
            base_name=base_name,
            grid_size=grid_size,
            custom_params=custom_params,
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
        )
        unreal_path = os.path.join(shader_dir, f"{base_name}_Octahedral_UE5.hlsl")
        with open(unreal_path, "w", encoding="utf-8") as f:
            f.write(unreal_code)
        results["UE5"] = unreal_path
        logger.info("Exported Unreal Engine companion shader: %s", unreal_path)

    return results


__all__ = [
    "generate_godot_octahedral_shader",
    "generate_unity_octahedral_hlsl",
    "generate_unreal_octahedral_hlsl",
    "export_companion_shaders",
]
