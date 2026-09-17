"""
OmniMesh Godot 4 Octahedral Impostor Shader Generator.
Generates native .gdshader files for Godot 4.x with:
- Camera-facing billboarding in the vertex stage
- 3-frame barycentric octahedral interpolation (smooth rotation, zero popping)
- Camera-space tangent normal unpacking and re-normalization
- ORM channel routing (R=AO, G=Roughness, B=Metallic)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def generate_godot_octahedral_shader(
    base_name: str,
    grid_size: int = 8,
    alpha_scissor: float = 0.5,
    custom_params: Optional[dict[str, Any]] = None,
) -> str:
    """
    Generates a complete Godot 4 Spatial .gdshader file for an 8x8 octahedral impostor.
    """
    shader_code = f"""// OmniMesh Generated Octahedral Impostor Shader for Godot 4.x
// Asset: {base_name} | Grid: {grid_size}x{grid_size}
shader_type spatial;
render_mode depth_draw_opaque, cull_disabled;

uniform sampler2D impostor_base_color : source_color, filter_linear_mipmap;
uniform sampler2D impostor_normal : hint_normal, filter_linear_mipmap;
uniform sampler2D impostor_orm : hint_default_white, filter_linear_mipmap;

uniform vec2 grid_size = vec2({float(grid_size)}, {float(grid_size)});
uniform float alpha_scissor_threshold : hint_range(0.0, 1.0) = {alpha_scissor:.2f};
uniform vec3 bounds_center = vec3(0.0, 0.0, 0.0);

varying vec3 v_local_view_dir;
varying vec2 v_card_uv;

void vertex() {{
    v_card_uv = UV;

    // Camera-facing billboarding around bounds_center
    vec3 cam_right = normalize(INV_VIEW_MATRIX[0].xyz);
    vec3 cam_up = normalize(INV_VIEW_MATRIX[1].xyz);
    vec3 offset = VERTEX - bounds_center;

    // Project quad to always face the active camera
    vec3 scale = vec3(
        length(MODEL_MATRIX[0].xyz),
        length(MODEL_MATRIX[1].xyz),
        length(MODEL_MATRIX[2].xyz)
    );
    VERTEX = bounds_center + (cam_right * offset.x + cam_up * offset.y) / max(scale, vec3(0.0001));

    // Calculate view vector in asset local space
    vec3 world_pos = (MODEL_MATRIX * vec4(bounds_center, 1.0)).xyz;
    vec3 world_view_dir = normalize(CAMERA_POSITION_WORLD - world_pos);
    v_local_view_dir = normalize((inverse(MODEL_MATRIX) * vec4(world_view_dir, 0.0)).xyz);
}}

vec2 dir_to_hemi_octa(vec3 dir) {{
    vec3 d = normalize(dir);
    // Upper hemisphere (Z-up in asset local space, or Y-up in Godot native)
    // Guard against nadir singularity
    float l1 = abs(d.x) + abs(d.z) + max(0.0, d.y);
    if (l1 < 1e-6) {{
        return vec2(0.5, 0.5);
    }}
    vec2 oct = vec2(d.x, d.z) / l1;
    return vec2((oct.x + oct.y) * 0.5 + 0.5, (oct.x - oct.y) * 0.5 + 0.5);
}}

vec2 get_tile_uv(vec2 base_uv, vec2 grid_coord) {{
    vec2 tile_uv = clamp(base_uv, 0.0, 1.0);
    return (grid_coord + tile_uv) / grid_size;
}}

void fragment() {{
    // 3-Frame Barycentric Octahedral Sampling
    vec2 octa_uv = dir_to_hemi_octa(v_local_view_dir);
    vec2 grid_pos = octa_uv * grid_size - vec2(0.5);
    vec2 cell = floor(grid_pos);
    vec2 f = fract(grid_pos);

    // Split cell into two triangles for 3-tap barycentric blending
    vec2 p0 = cell;
    vec2 p1;
    vec2 p2 = cell + vec2(1.0);
    vec3 weights;

    if (f.x > f.y) {{
        p1 = cell + vec2(1.0, 0.0);
        weights = vec3(1.0 - f.x, f.x - f.y, f.y);
    }} else {{
        p1 = cell + vec2(0.0, 1.0);
        weights = vec3(1.0 - f.y, f.y - f.x, f.x);
    }}

    // Clamp tile coordinates within grid bounds
    p0 = clamp(p0, vec2(0.0), grid_size - vec2(1.0));
    p1 = clamp(p1, vec2(0.0), grid_size - vec2(1.0));
    p2 = clamp(p2, vec2(0.0), grid_size - vec2(1.0));

    vec2 uv0 = get_tile_uv(v_card_uv, p0);
    vec2 uv1 = get_tile_uv(v_card_uv, p1);
    vec2 uv2 = get_tile_uv(v_card_uv, p2);

    vec4 col0 = texture(impostor_base_color, uv0);
    vec4 col1 = texture(impostor_base_color, uv1);
    vec4 col2 = texture(impostor_base_color, uv2);
    vec4 blended_col = weights.x * col0 + weights.y * col1 + weights.z * col2;

    ALPHA = blended_col.a;
    ALPHA_SCISSOR_THRESHOLD = alpha_scissor_threshold;
    ALBEDO = blended_col.rgb;

    // Tangent Normal Blending & Re-normalization
    vec3 n0 = texture(impostor_normal, uv0).rgb * 2.0 - 1.0;
    vec3 n1 = texture(impostor_normal, uv1).rgb * 2.0 - 1.0;
    vec3 n2 = texture(impostor_normal, uv2).rgb * 2.0 - 1.0;
    vec3 blended_normal = normalize(weights.x * n0 + weights.y * n1 + weights.z * n2);
    NORMAL_MAP = blended_normal * 0.5 + 0.5;

    // ORM Blending (R=AO, G=Roughness, B=Metallic)
    vec4 orm0 = texture(impostor_orm, uv0);
    vec4 orm1 = texture(impostor_orm, uv1);
    vec4 orm2 = texture(impostor_orm, uv2);
    vec4 blended_orm = weights.x * orm0 + weights.y * orm1 + weights.z * orm2;

    AO = blended_orm.r;
    ROUGHNESS = blended_orm.g;
    METALLIC = blended_orm.b;
}}
"""
    return shader_code.strip()
