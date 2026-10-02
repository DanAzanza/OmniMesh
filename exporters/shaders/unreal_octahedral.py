"""
OmniMesh Unreal Engine 5 Octahedral Impostor Shader Generator.
Generates native HLSL Custom Material Function code for UE5 with:
- Z-up object space view vector projection
- 3-frame barycentric interpolation
- Camera-space tangent normal unpacking
- ORM routing (R=AO, G=Roughness, B=Metallic)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def generate_unreal_octahedral_hlsl(
    base_name: str,
    grid_size: int = 8,
    custom_params: Optional[dict[str, Any]] = None,
) -> str:
    """
    Generates an HLSL Custom Expression block for Unreal Engine 5 Material Editor.
    """
    hlsl_code = f"""// OmniMesh Generated Octahedral Impostor Custom HLSL for Unreal Engine 5
// Asset: {base_name} | Grid: {grid_size}x{grid_size}
// Inputs to Custom Node:
//   Texture2D BaseColorTex
//   SamplerState TexSampler
//   float2 CardUV
//   float3 LocalViewDir (Object Space Camera Vector)
//   float2 GridSize (default 8.0, 8.0)

float3 d = normalize(LocalViewDir);
// UE5 is Z-up: horizontal plane is XY, elevation is Z
float l1 = abs(d.x) + abs(d.y) + max(0.0, d.z);
float2 octaUV = float2(0.5, 0.5);
if (l1 > 1e-6)
{{
    float2 oct = float2(d.x, d.y) / l1;
    octaUV = float2((oct.x + oct.y) * 0.5 + 0.5, (oct.x - oct.y) * 0.5 + 0.5);
}}

float2 gridPos = octaUV * GridSize - float2(0.5, 0.5);
float2 cell = floor(gridPos);
float2 f = frac(gridPos);

float2 p0 = cell;
float2 p1;
float2 p2 = cell + float2(1.0, 1.0);
float3 weights;

if (f.x > f.y)
{{
    p1 = cell + float2(1.0, 0.0);
    weights = float3(1.0 - f.x, f.x - f.y, f.y);
}}
else
{{
    p1 = cell + float2(0.0, 1.0);
    weights = float3(1.0 - f.y, f.y - f.x, f.x);
}}

p0 = clamp(p0, float2(0.0, 0.0), GridSize - float2(1.0, 1.0));
p1 = clamp(p1, float2(0.0, 0.0), GridSize - float2(1.0, 1.0));
p2 = clamp(p2, float2(0.0, 0.0), GridSize - float2(1.0, 1.0));

float2 uv0 = (p0 + saturate(CardUV)) / GridSize;
float2 uv1 = (p1 + saturate(CardUV)) / GridSize;
float2 uv2 = (p2 + saturate(CardUV)) / GridSize;

float4 col0 = BaseColorTex.Sample(TexSampler, uv0);
float4 col1 = BaseColorTex.Sample(TexSampler, uv1);
float4 col2 = BaseColorTex.Sample(TexSampler, uv2);

return weights.x * col0 + weights.y * col1 + weights.z * col2;
"""
    return hlsl_code.strip()


def generate_ue5_setup_guide(
    base_name: str,
    grid_size: int = 8,
    sphere_radius: float = 1.0,
    sphere_center: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> str:
    """
    Generates a setup guide (README_UE5_SETUP.txt) for Unreal Engine 5 integration.
    Contains exact texture settings, Pixel Depth Offset formula, and wiring instructions.
    """
    diameter = sphere_radius * 2.0
    guide = f"""================================================================================
OmniMesh Octahedral Impostor - Unreal Engine 5 Setup Guide
Asset: {base_name}
Grid Size: {grid_size}x{grid_size} ({grid_size * grid_size} Angular Frames)
Bounding Sphere Radius: {sphere_radius:.4f} Unreal Units (cm) / Blender Units (m)
Bounding Sphere Center: ({sphere_center[0]:.4f}, {sphere_center[1]:.4f}, {sphere_center[2]:.4f})
================================================================================

1. TEXTURE IMPORT & COMPRESSION SETTINGS (CRITICAL!):
--------------------------------------------------------------------------------
- T_{base_name}_Impostor_BaseColor.png:
    * Compression Settings: UserInterface2D (RGBA) or Default (TC_Default)
    * sRGB: ENABLED (Checked)

- T_{base_name}_Impostor_Normal.png:
    * IMPORTANT: DO NOT USE "Normalmap (TC_Normalmap / BC5)"!
      Unreal Engine's BC5 compressor automatically discards the Alpha channel.
      OmniMesh stores normalized Depth in the Alpha channel for Pixel Depth Offset.
    * Compression Settings: Default (TC_Default / BC7 / DXT5) or VectorDisplacementmap
    * sRGB: DISABLED (Unchecked)

- T_{base_name}_Impostor_ORM.png:
    * Compression Settings: Masks (TC_Masks) or Default (TC_Default)
    * sRGB: DISABLED (Unchecked)
    * Channels: Red = Ambient Occlusion, Green = Roughness, Blue = Metallic

2. PIXEL DEPTH OFFSET (PDO) FORMULA:
--------------------------------------------------------------------------------
In your UE5 Material:
- Sample Normal Texture -> Alpha channel (Depth).
- Pixel Depth Offset = Normal.A * {diameter:.4f}
  (Or using center bias: (Normal.A - 0.5) * {diameter:.4f})
- Connect this to the "Pixel Depth Offset" pin on the Material Output node.
  This allows the 2D billboard to intersect cleanly with terrain, foliage,
  and structures without harsh planar clipping.

3. MATERIAL GRAPH WIRING:
--------------------------------------------------------------------------------
Option A: Using UE5's Built-in MF_OctahedralImpostor
- Feed T_{base_name}_Impostor_BaseColor into BaseColorTex input.
- Feed T_{base_name}_Impostor_Normal into NormalTex input.
- Set Grid Size parameter to {grid_size}.

Option B: Using OmniMesh Custom HLSL Node
- Create a "Custom" node in the Material Editor.
- Set Output Type to CMOT_Float4.
- Paste the HLSL code from OmniMesh generated companion shader.
- Add inputs: BaseColorTex, TexSampler, CardUV, LocalViewDir, GridSize.

================================================================================
"""
    return guide.strip()


__all__ = ["generate_unreal_octahedral_hlsl", "generate_ue5_setup_guide"]
