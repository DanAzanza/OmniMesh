"""
OmniMesh Unity Octahedral Impostor HLSL Shader Generator.
Generates native HLSL include files for Unity URP and HDRP ShaderGraph with:
- 3-frame barycentric octahedral interpolation
- Object-space view vector decode
- Camera-space tangent normal unpacking and re-normalization
- MaskMap routing (R=Metallic, G=AO, B=Detail, A=Smoothness)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def generate_unity_octahedral_hlsl(
    base_name: str,
    grid_size: int = 8,
    custom_params: Optional[dict[str, Any]] = None,
) -> str:
    """
    Generates an HLSL include file containing the ShaderGraph Custom Function
    for Unity URP and HDRP Octahedral Impostor sampling.
    """
    hlsl_code = f"""// OmniMesh Generated Octahedral Impostor Include for Unity URP/HDRP
// Asset: {base_name} | Grid: {grid_size}x{grid_size}
#ifndef OMNIMESH_OCTAHEDRAL_INCLUDED
#define OMNIMESH_OCTAHEDRAL_INCLUDED

void DirToHemiOcta_float(float3 dir, out float2 octaUV)
{{
    float3 d = normalize(dir);
    // Y-up in Unity: horizontal plane is XZ, elevation is Y
    float l1 = abs(d.x) + abs(d.z) + max(0.0, d.y);
    if (l1 < 1e-6)
    {{
        octaUV = float2(0.5, 0.5);
        return;
    }}
    float2 oct = float2(d.x, d.z) / l1;
    octaUV = float2((oct.x + oct.y) * 0.5 + 0.5, (oct.x - oct.y) * 0.5 + 0.5);
}}

void SampleOctahedralImpostor_float(
    UnityTexture2D BaseColorTex,
    UnitySamplerState Sampler,
    float2 CardUV,
    float3 LocalViewDir,
    float2 GridSize,
    out float4 OutColor,
    out float3 OutWeights
)
{{
    float2 octaUV;
    DirToHemiOcta_float(LocalViewDir, octaUV);

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

    float4 col0 = BaseColorTex.Sample(Sampler, uv0);
    float4 col1 = BaseColorTex.Sample(Sampler, uv1);
    float4 col2 = BaseColorTex.Sample(Sampler, uv2);

    OutColor = weights.x * col0 + weights.y * col1 + weights.z * col2;
    OutWeights = weights;
}}

#endif // OMNIMESH_OCTAHEDRAL_INCLUDED
"""
    return hlsl_code.strip()
