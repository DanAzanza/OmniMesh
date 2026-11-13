"""
Cycles Multi-View Orthographic Camera Atlas Baker for Multi-Plane Impostors (ORTHO_3_AXES / STAR_QUADS).

Replaces Selected-to-Active first-hit raycasting with genuine Cycles orthographic camera
rendering per billboard face so semi-transparent materials (propellers, glass canopies)
composite cleanly over geometry behind them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
import logging
import math
import os
import tempfile
from typing import TYPE_CHECKING, cast

import numpy as np

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    from mathutils import Matrix, Vector
else:
    try:
        import bpy
        from mathutils import Matrix, Vector
    except ImportError:
        bpy = None
        Matrix = None  # type: ignore
        from .compat import Vector  # type: ignore
    BlendData = object

from .exceptions import ImpostorBakeError
from .impostor_harness import ImpostorShaderHarness
from .impostor_math import ImpostorMath
from .impostor_rig import EphemeralBakeSceneGuard
from .png_writer import write_png_direct

logger = logging.getLogger(__name__)


class _OrthoFaceSpec:
    """Describes one billboard face's world-space camera frustum and atlas pixel rect."""

    def __init__(
        self,
        cam_loc: Vector,
        cam_rot_euler: object,
        ortho_scale: float,
        rect: tuple[int, int, int, int],
    ) -> None:
        self.cam_loc = cam_loc
        self.cam_rot_euler = cam_rot_euler
        self.ortho_scale = ortho_scale
        self.rect = rect


def _extract_face_specs(
    target_impostor: bpy.types.Object,
    res: int,
    cam_distance: float,
) -> list[_OrthoFaceSpec]:
    """Extracts 1:1 world-space orthographic camera specs and atlas rects from a 6-face billboard mesh."""
    mesh_data = cast("bpy.types.Mesh | None", target_impostor.data)
    if mesh_data is None or mesh_data.polygons is None or mesh_data.uv_layers is None or len(mesh_data.uv_layers) == 0:
        return []

    uv_layer = mesh_data.uv_layers.active or mesh_data.uv_layers[0]
    mat_w = target_impostor.matrix_world
    specs: list[_OrthoFaceSpec] = []

    for poly in mesh_data.polygons:
        loop_indices = list(poly.loop_indices)
        if len(loop_indices) < 4:
            continue

        v0 = mesh_data.loops[loop_indices[0]].vertex_index
        v1 = mesh_data.loops[loop_indices[1]].vertex_index
        v2 = mesh_data.loops[loop_indices[2]].vertex_index
        v3 = mesh_data.loops[loop_indices[3]].vertex_index

        p0 = mat_w @ mesh_data.vertices[v0].co
        p1 = mat_w @ mesh_data.vertices[v1].co
        p2 = mat_w @ mesh_data.vertices[v2].co
        p3 = mat_w @ mesh_data.vertices[v3].co

        right_vec = p1 - p0
        up_vec = p3 - p0
        plane_w = max(0.01, float(right_vec.length))
        plane_h = max(0.01, float(up_vec.length))

        cam_right = right_vec.normalized()
        cam_up = up_vec.normalized()
        face_normal = cam_right.cross(cam_up).normalized()
        cam_forward = -face_normal

        face_center = (p0 + p2) * 0.5
        cam_loc = face_center + face_normal * cam_distance
        basis_rows = (
            (cam_right.x, cam_right.y, cam_right.z),
            (cam_up.x, cam_up.y, cam_up.z),
            (-cam_forward.x, -cam_forward.y, -cam_forward.z),
        )
        cam_rot = Matrix(basis_rows).transposed().to_euler()

        us = [float(uv_layer.data[idx].uv[0]) for idx in loop_indices]
        vs = [float(uv_layer.data[idx].uv[1]) for idx in loop_indices]
        u_min, u_max = max(0.0, min(us)), min(1.0, max(us))
        v_min, v_max = max(0.0, min(vs)), min(1.0, max(vs))

        x0 = max(0, min(res - 1, int(math.floor(u_min * res))))
        x1 = max(x0 + 1, min(res, int(math.ceil(u_max * res))))
        y0 = max(0, min(res - 1, int(math.floor((1.0 - v_max) * res))))
        y1 = max(y0 + 1, min(res, int(math.ceil((1.0 - v_min) * res))))

        # Expand ortho_scale symmetrically if rounded pixel aspect differs slightly from plane aspect
        tile_w = x1 - x0
        tile_h = y1 - y0
        scale_by_h = plane_h * (float(tile_w) / float(max(1, tile_h)))
        ortho_scale = max(plane_w, scale_by_h)

        specs.append(
            _OrthoFaceSpec(cam_loc=cam_loc, cam_rot_euler=cam_rot, ortho_scale=ortho_scale, rect=(x0, y0, x1, y1))
        )

    return specs


def apply_override_materials(
    mesh_objs: Sequence[bpy.types.Object],
    channel_layer: str,
    target_engine: str,
    radius: float,
    cam_distance: float,
    blend_data: BlendData,
) -> list[tuple[bpy.types.Mesh, list[bpy.types.Material | None], list[bpy.types.Material]]]:
    """Swaps materials once per unique Mesh datablock to unlit pass shaders, returning originals and overrides."""
    seen_meshes: set[int] = set()
    saved_state: list[tuple[bpy.types.Mesh, list[bpy.types.Material | None], list[bpy.types.Material]]] = []
    for obj in mesh_objs:
        obj_data = cast("bpy.types.Mesh | None", obj.data)
        if obj_data is None or obj_data.materials is None or id(obj_data) in seen_meshes:
            continue
        seen_meshes.add(id(obj_data))
        mats = list(obj_data.materials)
        bake_mats = mats if mats else [None]
        override_mats: list[bpy.types.Material] = []
        for m in bake_mats:
            ov_m = ImpostorShaderHarness.create_unlit_override_material(
                m,
                channel_layer=channel_layer,
                target_engine=target_engine,
                radius=radius,
                cam_distance=cam_distance,
                blend_data=blend_data,
            )
            if ov_m is not None:
                override_mats.append(ov_m)
        saved_state.append((obj_data, mats, override_mats))
        obj_data.materials.clear()
        for ov_m in override_mats:
            obj_data.materials.append(ov_m)
    return saved_state


def restore_override_materials(
    saved_state: list[tuple[bpy.types.Mesh, list[bpy.types.Material | None], list[bpy.types.Material]]],
    blend_data: BlendData,
) -> None:
    """Restores original mesh materials saved before an unlit render pass and removes override datablocks."""
    override_mats_to_remove: list[bpy.types.Material] = []
    for mesh_data, mats, override_mats in saved_state:
        if mesh_data.materials is not None:
            mesh_data.materials.clear()
            for m in mats:
                mesh_data.materials.append(m)
        override_mats_to_remove.extend(override_mats)

    bdata_mats = blend_data.materials if blend_data is not None else None
    if bdata_mats is not None:
        seen_ids: set[int] = set()
        for ov_mat in override_mats_to_remove:
            if id(ov_mat) in seen_ids:
                continue
            seen_ids.add(id(ov_mat))
            if ov_mat.name in bdata_mats:
                bdata_mats.remove(ov_mat, do_unlink=True)


def load_rendered_tile_u8(filepath: str, bdata_imgs: bpy.types.BlendDataImages | None) -> np.ndarray | None:
    """Reads a rendered RGBA PNG from disk into a top-down uint8 NumPy array and always unlinks datablock."""
    if bdata_imgs is None or not os.path.exists(filepath):
        return None
    img = bdata_imgs.load(filepath)
    if img is None:
        return None
    try:
        sz = list(cast("Iterable[int]", img.size))
        if len(sz) < 2:
            return None
        w, h = int(sz[0]), int(sz[1])
        if w <= 0 or h <= 0:
            return None
        arr = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(arr)
        return np.ascontiguousarray((arr.reshape((h, w, 4))[::-1] * 255.0 + 0.5).clip(0, 255).astype(np.uint8))
    finally:
        bdata_imgs.remove(img, do_unlink=True)


def finalize_orm_tile(
    orm_tile: np.ndarray,
    opacity_mask: np.ndarray,
    target_engine: str,
    dilation_iterations: int,
) -> np.ndarray:
    """Packs Unity MaskMap smoothness (B->A) or UE5/MSFS ORM, fills background, and dilates channels."""
    proc = np.array(orm_tile, copy=True)
    is_unity = target_engine in {"UNITY", "UNITY_6"}
    if is_unity:
        proc[:, :, 3] = proc[:, :, 2]
        proc[:, :, 2] = 0
        proc[~opacity_mask] = (0, 255, 0, 128)
    else:
        proc[~opacity_mask] = (255, 128, 0, 255)
        proc[:, :, 3] = 255

    if dilation_iterations > 0:
        proc = ImpostorMath.morphological_dilate_channels(proc, opacity_mask, iterations=dilation_iterations)
        if not is_unity:
            proc[:, :, 3] = 255
    return proc


def bake_ortho_quads_atlas(
    *,
    mesh_objs: list[bpy.types.Object],
    target_impostor: bpy.types.Object,
    base_name: str,
    output_dir: str,
    res: int,
    max_span: float,
    target_engine: str,
    dilation_iterations: int,
    configure_cycles_fn: Callable[[bpy.types.Scene | None, bpy.types.Context | None], tuple[str, list[str]]],
    set_view_transform_fn: Callable[[bpy.types.Scene, str], None],
    render_still_fn: Callable[[bpy.types.Scene, bpy.types.Context | None], None],
    context: bpy.types.Context | None,
    blend_data: BlendData,
) -> dict[str, str]:
    """
    Bakes BaseColor, Tangent Normal, and ORM atlases for ORTHO_3_AXES via Cycles orthographic
    camera rendering aligned strictly to each billboard face, preserving semi-transparency.
    """
    if not bpy or Matrix is None or blend_data is None:
        return {}

    cam_distance = max(2.0, max_span * 2.5)
    face_specs = _extract_face_specs(target_impostor, res, cam_distance)
    if not face_specs:
        return {}

    results: dict[str, str] = {}
    with EphemeralBakeSceneGuard(
        scene_name=f"{base_name}_OrthoBake", context=context, blend_data=blend_data
    ) as bake_scene:
        if bake_scene is None:
            return {}

        configure_cycles_fn(bake_scene, context)
        for obj in mesh_objs:
            if obj.name not in bake_scene.collection.objects:
                bake_scene.collection.objects.link(obj)

        bdata_cams = blend_data.cameras
        bdata_objs = blend_data.objects
        bdata_imgs = blend_data.images
        if bdata_cams is None or bdata_objs is None or bdata_imgs is None:
            return {}

        cam_data = cast("bpy.types.Camera", bdata_cams.new(f"{base_name}_OrthoCamData"))
        cam_data.type = "ORTHO"
        cam_data.sensor_fit = "HORIZONTAL"
        cam_data.clip_start = 0.05
        cam_data.clip_end = cam_distance * 4.0 + 10.0

        cam_obj = bdata_objs.new(f"{base_name}_OrthoCam", cam_data)
        bake_scene.collection.objects.link(cam_obj)
        bake_scene.camera = cam_obj
        bake_scene.render.resolution_percentage = 100
        bake_scene.render.image_settings.file_format = "PNG"
        bake_scene.render.image_settings.color_mode = "RGBA"

        passes = [("BaseColor", "BASE_COLOR"), ("Normal", "NORMAL"), ("ORM", "ORM")]
        raw_tiles: dict[str, list[np.ndarray | None]] = {name: [] for name, _ in passes}

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                for chan_name, harness_layer in passes:
                    set_view_transform_fn(bake_scene, "Standard" if chan_name == "BaseColor" else "Raw")
                    saved_materials = apply_override_materials(
                        mesh_objs, harness_layer, target_engine, max_span * 0.5, cam_distance, blend_data
                    )
                    try:
                        for idx, spec in enumerate(face_specs):
                            x0, y0, x1, y1 = spec.rect
                            bake_scene.render.resolution_x = x1 - x0
                            bake_scene.render.resolution_y = y1 - y0
                            cam_data.ortho_scale = spec.ortho_scale
                            cam_obj.location = spec.cam_loc
                            cam_obj.rotation_euler = spec.cam_rot_euler  # type: ignore[assignment]

                            out_tile_path = os.path.join(temp_dir, f"{chan_name}_face_{idx}.png")
                            bake_scene.render.filepath = out_tile_path
                            try:
                                render_still_fn(bake_scene, context)
                            except (RuntimeError, ValueError) as exc:
                                raise ImpostorBakeError(
                                    f"Orthographic Cycles bake failed on pass '{chan_name}' face {idx}: {exc}"
                                ) from exc
                            raw_tiles[chan_name].append(load_rendered_tile_u8(out_tile_path, bdata_imgs))
                    finally:
                        restore_override_materials(saved_materials, blend_data)
        finally:
            bdata_objs.remove(cam_obj, do_unlink=True)
            bdata_cams.remove(cam_data, do_unlink=True)

        is_unity = target_engine in {"UNITY", "UNITY_6"}
        atlas_base = np.zeros((res, res, 4), dtype=np.uint8)
        atlas_norm = np.zeros((res, res, 4), dtype=np.uint8)
        atlas_norm[:, :, :4] = (128, 128, 255, 255)
        atlas_orm = np.zeros((res, res, 4), dtype=np.uint8)
        atlas_orm[:, :, :4] = (0, 255, 0, 128) if is_unity else (255, 128, 0, 255)

        for idx, spec in enumerate(face_specs):
            base_tile = raw_tiles["BaseColor"][idx]
            norm_tile = raw_tiles["Normal"][idx]
            orm_tile = raw_tiles["ORM"][idx]
            if base_tile is None:
                continue

            opacity_mask = base_tile[:, :, 3] > 2
            x0, y0, x1, y1 = spec.rect
            expected_shape = (y1 - y0, x1 - x0)
            if base_tile.shape[:2] != expected_shape:
                continue

            if dilation_iterations > 0:
                dilate_fn = ImpostorMath.morphological_dilate_channels
                base_rgb = dilate_fn(base_tile[:, :, :3], opacity_mask, iterations=dilation_iterations)
                base_tile = np.dstack([base_rgb, base_tile[:, :, 3]])
                if norm_tile is not None:
                    norm_tile = dilate_fn(norm_tile, opacity_mask, iterations=dilation_iterations)

            atlas_base[y0:y1, x0:x1] = base_tile
            if norm_tile is not None and norm_tile.shape[:2] == expected_shape:
                norm_empty = norm_tile[:, :, 3] == 0
                norm_tile[norm_empty, :3] = (128, 128, 255)
                norm_tile[:, :, 3] = 255
                atlas_norm[y0:y1, x0:x1] = norm_tile
            if orm_tile is not None and orm_tile.shape[:2] == expected_shape:
                atlas_orm[y0:y1, x0:x1] = finalize_orm_tile(orm_tile, opacity_mask, target_engine, dilation_iterations)

        for chan_key, atlas_arr in (("BaseColor", atlas_base), ("Normal", atlas_norm), ("ORM", atlas_orm)):
            out_path = os.path.join(output_dir, f"T_{base_name}_Impostor_{chan_key}.png")
            write_png_direct(out_path, atlas_arr)
            results[chan_key] = out_path

    return results
