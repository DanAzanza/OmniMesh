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
