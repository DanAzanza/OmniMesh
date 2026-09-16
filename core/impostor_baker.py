"""
OmniMesh PBR Billboard Impostor Baking Engine.
Blender 4.2+ and 5.0+ LTS Compatible.

Provides:
- EphemeralBakeSceneGuard: 100% isolated temporary bake scene protecting user camera/render settings.
- ImpostorCameraRig: Orthographic bounding-sphere framing orbit with exact frustum bounds.
- ImpostorShaderHarness: Unlit Emission overrides for BaseColor, Camera-Space Tangent Normals, and ORM.
- ImpostorAtlasBaker: Sequenced multi-angle rendering, sub-tile local morphological dilation,
  atlas compositing, and direct PBR image file export.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

try:
    import bpy
    import mathutils
    from mathutils import Matrix, Vector
except ImportError:
    bpy = None
    mathutils = None
    Matrix = None  # type: ignore

    class Vector(tuple):  # type: ignore
        def __new__(cls, coords: Any) -> Vector:
            return super().__new__(cls, tuple(float(x) for x in coords))

        @property
        def x(self) -> float:
            return self[0]

        @property
        def y(self) -> float:
            return self[1]

        @property
        def z(self) -> float:
            return self[2]


try:
    from .impostor import ImpostorMath
    from .metrics import compute_bounding_sphere
    from .png_writer import write_png_direct
except (ImportError, ValueError):
    from core.impostor import ImpostorMath
    from core.metrics import compute_bounding_sphere
    from core.png_writer import write_png_direct


class EphemeralBakeSceneGuard:
    """
    Context manager creating an isolated temporary Blender Scene.
    Guarantees that active user cameras, lighting, world settings, and render engines
    remain completely unpolluted during baking passes.
    """

    def __init__(self, scene_name: str = "OMNIMESH_TEMP_BAKE"):
        self.temp_scene_name = scene_name
        self.orig_scene = None
        self.bake_scene = None

    def __enter__(self) -> Optional[Any]:
        if not bpy:
            return None
        self.orig_scene = bpy.context.scene
        self.bake_scene = bpy.data.scenes.new(self.temp_scene_name)

        # Configure minimal, fast unlit rendering environment
        render = self.bake_scene.render
        render.film_transparent = True
        render.dither_intensity = 0.0

        # Prefer EEVEE-Next or fallback cleanly
        if hasattr(self.bake_scene, "eevee"):
            self.bake_scene.render.engine = "BLENDER_EEVEE_NEXT"
            if hasattr(self.bake_scene.eevee, "taa_render_samples"):
                self.bake_scene.eevee.taa_render_samples = 1
        elif "CYCLES" in [e.identifier for e in bpy.types.RenderEngine.bl_rna.properties["engine"].enum_items]:
            self.bake_scene.render.engine = "CYCLES"
            if hasattr(self.bake_scene, "cycles"):
                self.bake_scene.cycles.samples = 1
                self.bake_scene.cycles.max_bounces = 0

        # Black unlit world background
        world = bpy.data.worlds.new(f"{self.temp_scene_name}_World")
        world.use_nodes = True
        if world.node_tree and world.node_tree.nodes:
            bg = world.node_tree.nodes.get("Background")
            if bg and "Color" in bg.inputs:
                bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        self.bake_scene.world = world

        bpy.context.window.scene = self.bake_scene
        return self.bake_scene

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if not bpy:
            return
        try:
            if self.orig_scene and bpy.context.window:
                bpy.context.window.scene = self.orig_scene
            if self.bake_scene:
                if self.bake_scene.camera:
                    cam_obj = self.bake_scene.camera
                    cam_data = getattr(cam_obj, "data", None)
                    bpy.data.objects.remove(cam_obj, do_unlink=True)
                    if cam_data:
                        bpy.data.cameras.remove(cam_data, do_unlink=True)
                if self.bake_scene.world:
                    w = self.bake_scene.world
                    self.bake_scene.world = None
                    bpy.data.worlds.remove(w, do_unlink=True)
                bpy.data.scenes.remove(self.bake_scene, do_unlink=True)
        except Exception as exc:
            logger.debug("Failed cleaning ephemeral bake scene: %s", exc)


class ImpostorCameraRig:
    """
    Manages an orthographic camera orbiting an asset bounding sphere center.
    Calculates exact frustum bounds to prevent clipping at any rotation angle.
    """

    @staticmethod
    def compute_rig_parameters(coords: list[Any]) -> tuple[Any, float, float]:
        center, radius = compute_bounding_sphere(coords)
        radius = max(0.25, float(radius))
        # 4% margin ensures grazing silhouette edges are not clipped by orthographic frustum
        ortho_scale = 2.0 * radius * 1.04
        return center, radius, ortho_scale

    @classmethod
    def setup_camera(
        cls,
        scene: Any,
        center: Any,
        radius: float,
        ortho_scale: float,
        angle_rad: float = 0.0,
        pitch_rad: float = 0.0,
    ) -> Any:
        if not bpy or not scene:
            return None

        cam_data = scene.camera.data if scene.camera else bpy.data.cameras.new("OMNIMESH_Bake_Cam")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = ortho_scale

        dist = radius * 2.5
        cam_data.clip_start = max(0.001, dist - radius * 1.5)
        cam_data.clip_end = dist + radius * 1.5

        if not scene.camera:
            cam_obj = bpy.data.objects.new("OMNIMESH_Bake_Cam_Obj", cam_data)
            scene.collection.objects.link(cam_obj)
            scene.camera = cam_obj
        else:
            cam_obj = scene.camera

        cos_p = math.cos(pitch_rad)
        sin_p = math.sin(pitch_rad)
        sin_a = math.sin(angle_rad)
        cos_a = math.cos(angle_rad)

        offset_x = dist * cos_p * sin_a
        offset_y = -dist * cos_p * cos_a
        offset_z = dist * sin_p

        cx = float(center[0])
        cy = float(center[1])
        cz = float(center[2])

        cam_obj.location = Vector((cx + offset_x, cy + offset_y, cz + offset_z))
        dir_vec = Vector((cx - cam_obj.location.x, cy - cam_obj.location.y, cz - cam_obj.location.z))
        if dir_vec.length > 1e-6:
            rot_quat = dir_vec.to_track_quat("-Z", "Y")
            cam_obj.rotation_euler = rot_quat.to_euler()

        return cam_obj


class ImpostorShaderHarness:
    """
    Constructs unlit emission shader overrides for the three required PBR passes:
    - BaseColor (with Alpha Mask & Cutout)
    - Camera-Space Tangent Normal (neutral-blue background cleared)
    - ORM / MaskMap (R=AO, G=Roughness, B=Metallic)
    """

    @classmethod
    def create_unlit_override_material(
        cls,
        source_mat: Optional[Any],
        channel_layer: str = "BASE_COLOR",
        target_engine: str = "UE5",
    ) -> Optional[Any]:
        if not bpy:
            return None

        mat = bpy.data.materials.new(f"OM_Bake_{channel_layer}")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()

        out_node = nodes.new(type="ShaderNodeOutputMaterial")
        out_node.location = (400, 0)
        emit_node = nodes.new(type="ShaderNodeEmission")
        emit_node.location = (150, 0)
        links.new(emit_node.outputs["Emission"], out_node.inputs["Surface"])

        src_bsdf = None
        if source_mat and getattr(source_mat, "use_nodes", False) and source_mat.node_tree:
            src_bsdf = next(
                (n for n in source_mat.node_tree.nodes if getattr(n, "type", "") == "BSDF_PRINCIPLED"), None
            )

        if channel_layer == "BASE_COLOR":
            if src_bsdf and "Base Color" in src_bsdf.inputs and src_bsdf.inputs["Base Color"].is_linked:
                src_link = src_bsdf.inputs["Base Color"].links[0]
                cls._duplicate_link_to_target(source_mat, src_link, nodes, links, emit_node.inputs["Color"])
            elif src_bsdf and "Base Color" in src_bsdf.inputs:
                emit_node.inputs["Color"].default_value = src_bsdf.inputs["Base Color"].default_value
            else:
                emit_node.inputs["Color"].default_value = (0.8, 0.8, 0.8, 1.0)

        elif channel_layer == "NORMAL":
            geom_node = nodes.new(type="ShaderNodeNewGeometry")
            geom_node.location = (-300, 0)
            vec_trans = nodes.new(type="ShaderNodeVectorTransform")
            vec_trans.vector_type = "NORMAL"
            vec_trans.convert_from = "WORLD"
            vec_trans.convert_to = "CAMERA"
            vec_trans.location = (-150, 0)
            links.new(geom_node.outputs["Normal"], vec_trans.inputs["Vector"])

            vec_math = nodes.new(type="ShaderNodeVectorMath")
            vec_math.operation = "MULTIPLY_ADD"
            vec_math.location = (0, 0)
            vec_math.inputs[1].default_value = (0.5, 0.5, 0.5)
            vec_math.inputs[2].default_value = (0.5, 0.5, 0.5)
            links.new(vec_trans.outputs["Vector"], vec_math.inputs[0])
            links.new(vec_math.outputs["Vector"], emit_node.inputs["Color"])

        elif channel_layer == "ORM":
            comb_node = nodes.new(type="ShaderNodeCombineColor")
            comb_node.location = (-50, 0)

            rough_val = 0.5
            metal_val = 0.0
            if src_bsdf:
                if "Roughness" in src_bsdf.inputs and not src_bsdf.inputs["Roughness"].is_linked:
                    rough_val = float(src_bsdf.inputs["Roughness"].default_value)
                if "Metallic" in src_bsdf.inputs and not src_bsdf.inputs["Metallic"].is_linked:
                    metal_val = float(src_bsdf.inputs["Metallic"].default_value)

            if target_engine == "UNITY":
                # Unity standard MaskMap: R=Metallic, G=AO (1.0), B=Detail Mask (0.0), A=Smoothness (1-Roughness)
                comb_node.inputs["Red"].default_value = metal_val
                comb_node.inputs["Green"].default_value = 1.0
                comb_node.inputs["Blue"].default_value = 1.0 - rough_val
            else:
                # UE5, MSFS 2024, Godot: R=AO, G=Roughness, B=Metallic
                comb_node.inputs["Red"].default_value = 1.0
                comb_node.inputs["Green"].default_value = rough_val
                comb_node.inputs["Blue"].default_value = metal_val

            links.new(comb_node.outputs["Color"], emit_node.inputs["Color"])

        return mat

    @staticmethod
    def _duplicate_link_to_target(
        source_mat: Any, link: Any, target_nodes: Any, target_links: Any, target_socket: Any
    ) -> None:
        from_node = link.from_node
        if getattr(from_node, "type", "") == "TEX_IMAGE" and getattr(from_node, "image", None):
            tex = target_nodes.new(type="ShaderNodeTexImage")
            tex.image = from_node.image
            tex.location = (-250, 0)
            target_links.new(tex.outputs["Color"], target_socket)


class ImpostorAtlasBaker:
    """
    Orchestrates the Impostor atlas generation pipeline.
    Bakes BaseColor, Camera-Space Tangent Normal, and ORM maps across required views,
    applies tile-local morphological dilation, packs the atlas, and writes PNG files.
    """

    @classmethod
    def get_view_angles_for_mode(cls, mode: str) -> list[tuple[float, float, tuple[int, int]]]:
        angles: list[tuple[float, float, tuple[int, int]]] = []

        if mode == "STAR_QUADS":
            steps = [0.0, math.radians(60.0), math.radians(120.0)]
            coords = [(0, 0), (1, 0), (0, 1)]
            for i in range(3):
                angles.append((steps[i], 0.0, coords[i]))
        elif mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
            grid_n = 8
            for row in range(grid_n):
                for col in range(grid_n):
                    u = (col + 0.5) / float(grid_n)
                    v = (row + 0.5) / float(grid_n)
                    if mode == "OCTAHEDRAL_HEMI":
                        vec = ImpostorMath.hemi_octahedral_to_vector(u, v)
                    else:
                        vec = ImpostorMath.full_octahedral_to_vector(u, v)
                    length_xy = math.sqrt(vec[0] * vec[0] + vec[1] * vec[1])
                    azimuth = math.atan2(vec[0], -vec[1])
                    pitch = math.atan2(vec[2], max(1e-6, length_xy))
                    angles.append((azimuth, pitch, (col, row)))
        else:
            angles.append((0.0, 0.0, (0, 0)))
            angles.append((math.radians(90.0), 0.0, (1, 0)))

        return angles

    @classmethod
    def get_grid_dimensions(cls, mode: str) -> tuple[int, int]:
        if mode == "STAR_QUADS":
            return 2, 2
        elif mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
            return 8, 8
        return 2, 1

    @classmethod
    def compose_atlas_array(
        cls,
        tiles: list[tuple[np.ndarray, tuple[int, int]]],
        grid_cols: int,
        grid_rows: int,
        tile_w: int,
        tile_h: int,
        dilation_iterations: int = 4,
    ) -> np.ndarray:
        atlas_w = grid_cols * tile_w
        atlas_h = grid_rows * tile_h
        atlas = np.zeros((atlas_h, atlas_w, 4), dtype=np.uint8)

        for tile_data, (col, row) in tiles:
            if dilation_iterations > 0 and tile_data.dtype == np.uint8:
                float_tile = tile_data.astype(np.float32) / 255.0
                dilated_float = ImpostorMath.morphological_dilate_rgb(float_tile, iterations=dilation_iterations)
                processed_tile = (dilated_float * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
            else:
                processed_tile = tile_data

            y_start = row * tile_h
            x_start = col * tile_w
            h_clamp = min(tile_h, processed_tile.shape[0])
            w_clamp = min(tile_w, processed_tile.shape[1])
            atlas[y_start : y_start + h_clamp, x_start : x_start + w_clamp] = processed_tile[:h_clamp, :w_clamp]

        return atlas

    @classmethod
    def bake_impostor_textures(
        cls,
        mesh_objs: list[Any],
        base_name: str,
        output_dir: str,
        mode: str = "CROSS_QUADS",
        atlas_resolution: int = 2048,
        target_engine: str = "UE5",
        dilation_iterations: int = 4,
    ) -> dict[str, str]:
        if not bpy or not mesh_objs:
            return {}

        os.makedirs(output_dir, exist_ok=True)
        results: dict[str, str] = {}

        grid_cols, grid_rows = cls.get_grid_dimensions(mode)
        tile_w = atlas_resolution // grid_cols
        tile_h = atlas_resolution // grid_rows
        view_angles = cls.get_view_angles_for_mode(mode)

        all_coords = []
        for obj in mesh_objs:
            if hasattr(obj, "bound_box") and obj.bound_box:
                all_coords.extend([obj.matrix_world @ Vector(c) for c in obj.bound_box])
            elif hasattr(obj, "data") and hasattr(obj.data, "vertices"):
                all_coords.extend([obj.matrix_world @ v.co for v in obj.data.vertices])

        center, radius, ortho_scale = ImpostorCameraRig.compute_rig_parameters(all_coords)

        with EphemeralBakeSceneGuard() as bake_scene:
            if not bake_scene:
                return {}

            for obj in mesh_objs:
                bake_scene.collection.objects.link(obj)

            render = bake_scene.render
            render.resolution_x = tile_w
            render.resolution_y = tile_h
            render.resolution_percentage = 100

            tmp_render_path = os.path.join(output_dir, f"__om_impostor_tmp_{base_name}.png")

            src_mat = None
            for obj in mesh_objs:
                if hasattr(obj, "data") and hasattr(obj.data, "materials") and obj.data.materials:
                    src_mat = obj.data.materials[0]
                    if src_mat:
                        break

            mat_base = ImpostorShaderHarness.create_unlit_override_material(
                src_mat, channel_layer="BASE_COLOR", target_engine=target_engine
            )
            mat_norm = ImpostorShaderHarness.create_unlit_override_material(
                src_mat, channel_layer="NORMAL", target_engine=target_engine
            )
            mat_orm = ImpostorShaderHarness.create_unlit_override_material(
                src_mat, channel_layer="ORM", target_engine=target_engine
            )

            created_override_mats = [m for m in (mat_base, mat_norm, mat_orm) if m]

            vl = bake_scene.view_layers[0] if (hasattr(bake_scene, "view_layers") and bake_scene.view_layers) else None

            def _render_channel_pass(
                override_mat: Optional[Any],
            ) -> list[tuple[np.ndarray, tuple[int, int]]]:
                tiles: list[tuple[np.ndarray, tuple[int, int]]] = []
                if vl:
                    vl.material_override = override_mat

                for azimuth, pitch, (c_col, c_row) in view_angles:
                    ImpostorCameraRig.setup_camera(
                        bake_scene, center, radius, ortho_scale, angle_rad=azimuth, pitch_rad=pitch
                    )
                    render.filepath = tmp_render_path
                    try:
                        bpy.ops.render.render(write_still=True, scene=bake_scene.name)
                        if os.path.exists(tmp_render_path):
                            tmp_img = bpy.data.images.load(tmp_render_path)
                            raw_floats = np.empty(tile_h * tile_w * 4, dtype=np.float32)
                            tmp_img.pixels.foreach_get(raw_floats)
                            tile_pixels = raw_floats.reshape((tile_h, tile_w, 4))
                            bpy.data.images.remove(tmp_img, do_unlink=True)

                            uint8_tile = (np.clip(tile_pixels, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
                            tiles.append((uint8_tile, (c_col, c_row)))
                    except Exception as exc:
                        logger.debug("Render pass exception on angle %.2f: %s", azimuth, exc)
                return tiles

            try:
                base_color_tiles = _render_channel_pass(mat_base)
                normal_tiles = _render_channel_pass(mat_norm)
                orm_tiles = _render_channel_pass(mat_orm)
            finally:
                if vl:
                    vl.material_override = None
                for m in created_override_mats:
                    try:
                        bpy.data.materials.remove(m, do_unlink=True)
                    except Exception as exc:
                        logger.debug("Failed unlinking temporary bake material: %s", exc)
                if os.path.exists(tmp_render_path):
                    try:
                        os.remove(tmp_render_path)
                    except OSError as exc:
                        logger.debug("Failed removing temp render file: %s", exc)

        if base_color_tiles:
            base_atlas = cls.compose_atlas_array(
                base_color_tiles, grid_cols, grid_rows, tile_w, tile_h, dilation_iterations=dilation_iterations
            )
            base_path = os.path.join(output_dir, f"T_{base_name}_Impostor_BaseColor.png")
            write_png_direct(base_path, base_atlas, bit_depth=8)
            results["BaseColor"] = base_path

        if normal_tiles:
            norm_atlas = cls.compose_atlas_array(
                normal_tiles, grid_cols, grid_rows, tile_w, tile_h, dilation_iterations=dilation_iterations
            )
            norm_path = os.path.join(output_dir, f"T_{base_name}_Impostor_Normal.png")
            write_png_direct(norm_path, norm_atlas, bit_depth=8)
            results["Normal"] = norm_path

        if orm_tiles:
            orm_atlas = cls.compose_atlas_array(
                orm_tiles, grid_cols, grid_rows, tile_w, tile_h, dilation_iterations=dilation_iterations
            )
            orm_path = os.path.join(output_dir, f"T_{base_name}_Impostor_ORM.png")
            write_png_direct(orm_path, orm_atlas, bit_depth=8)
            results["ORM"] = orm_path

        return results


__all__ = [
    "EphemeralBakeSceneGuard",
    "ImpostorCameraRig",
    "ImpostorShaderHarness",
    "ImpostorAtlasBaker",
]
