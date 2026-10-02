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
import tempfile
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
    try:
        from .impostor_math import Vector
    except (ImportError, ValueError):
        from core.impostor_math import Vector


try:
    from .impostor_harness import ImpostorShaderHarness
    from .impostor_math import ImpostorMath
    from .metrics import compute_bounding_sphere
    from .png_writer import write_png_direct
except (ImportError, ValueError):
    from core.impostor_harness import ImpostorShaderHarness
    from core.impostor_math import ImpostorMath
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

        # Prefer Cycles for headless rendering to avoid Mesa llvmpipe overhead, or EEVEE in GUI
        is_bg = getattr(bpy.app, "background", False) if bpy else False
        preferred = (
            ("CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
            if is_bg
            else ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES")
        )

        for eng in preferred:
            try:
                self.bake_scene.render.engine = eng
                if self.bake_scene.render.engine == eng:
                    if eng == "CYCLES" and hasattr(self.bake_scene, "cycles"):
                        self.bake_scene.cycles.samples = 1
                        self.bake_scene.cycles.max_bounces = 0
                        self.bake_scene.cycles.diffuse_bounces = 0
                        self.bake_scene.cycles.glossy_bounces = 0
                        self.bake_scene.cycles.device = "CPU"
                    elif hasattr(self.bake_scene, "eevee") and hasattr(self.bake_scene.eevee, "taa_render_samples"):
                        self.bake_scene.eevee.taa_render_samples = 1
                    break
            except Exception as eng_err:
                logger.debug("Render engine %s not available: %s", eng, eng_err)

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

        cp = math.cos(pitch_rad)
        offset = Vector((dist * cp * math.sin(angle_rad), -dist * cp * math.cos(angle_rad), dist * math.sin(pitch_rad)))
        cam_obj.location = Vector(center) + offset
        dir_vec = Vector(center) - Vector(cam_obj.location)
        if dir_vec.length > 1e-6:
            rot_quat = dir_vec.to_track_quat("-Z", "Y")
            cam_obj.rotation_euler = rot_quat.to_euler()

        return cam_obj


# ImpostorShaderHarness is imported from core.impostor_harness for clean modularization


class ImpostorAtlasBaker:
    """
    Orchestrates the Impostor atlas generation pipeline.
    Bakes BaseColor, Camera-Space Tangent Normal, and ORM maps across required views,
    applies tile-local morphological dilation, packs the atlas, and writes PNG files.
    """

    @classmethod
    def get_view_angles_for_mode(cls, mode: str) -> list[tuple[float, float, tuple[int, int]]]:
        angles: list[tuple[float, float, tuple[int, int]]] = []

        if mode in {"STAR_QUADS", "ORTHO_3_AXES"}:
            return [(0.0, 0.0, (0, 0)), (math.radians(90.0), 0.0, (1, 0)), (0.0, math.radians(90.0), (0, 1))]
        if mode not in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
            return [(0.0, 0.0, (0, 0)), (math.radians(90.0), 0.0, (1, 0))]

        grid_n = 8
        fn = (
            ImpostorMath.hemi_octahedral_to_vector
            if mode == "OCTAHEDRAL_HEMI"
            else ImpostorMath.full_octahedral_to_vector
        )
        for row in range(grid_n):
            for col in range(grid_n):
                vec = fn((col + 0.5) / float(grid_n), (row + 0.5) / float(grid_n))
                angles.append(
                    (math.atan2(vec[0], -vec[1]), math.atan2(vec[2], max(1e-6, math.hypot(vec[0], vec[1]))), (col, row))
                )
        return angles

    @classmethod
    def get_grid_dimensions(cls, mode: str) -> tuple[int, int]:
        if mode in {"STAR_QUADS", "ORTHO_3_AXES"}:
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
    def configure_cycles_compute_device(cls, scene: Any) -> tuple[str, list[str]]:
        """
        Automatically probes and configures the optimal compute device for Cycles baking.
        Supports NVIDIA (OptiX, CUDA), Apple Silicon (Metal), AMD (HIP), Intel (oneAPI),
        and safely falls back to CPU if no compatible GPU hardware is detected.
        """
        if not bpy:
            return "CPU", ["CPU"]

        backend_priority = ["OPTIX", "METAL", "HIP", "ONEAPI", "CUDA"]
        try:
            cycles_addon = bpy.context.preferences.addons.get("cycles")
            if cycles_addon and hasattr(cycles_addon, "preferences"):
                cpref = cycles_addon.preferences
                avail = (
                    {item[0] for item in cpref.get_device_types(bpy.context)}
                    if hasattr(cpref, "get_device_types")
                    else set()
                )
                for backend in backend_priority:
                    if backend in avail:
                        try:
                            cpref.compute_device_type = backend
                            if hasattr(cpref, "get_devices"):
                                cpref.get_devices()
                            active_devs = [
                                d for d in getattr(cpref, "devices", []) if getattr(d, "type", "") == backend
                            ]
                            if active_devs:
                                for d in active_devs:
                                    d.use = True
                                if hasattr(scene, "cycles"):
                                    scene.cycles.device = "GPU"
                                dev_names = [getattr(d, "name", backend) for d in active_devs]
                                logger.info("Configured Cycles GPU baking: %s (%s)", backend, ", ".join(dev_names))
                                return backend, dev_names
                        except Exception as b_err:
                            logger.debug("Cycles backend %s failed: %s", backend, b_err)
                if hasattr(cpref, "compute_device_type"):
                    cpref.compute_device_type = "NONE"
        except Exception as exc:
            logger.debug("Failed configuring Cycles compute device: %s", exc)

        if hasattr(scene, "cycles"):
            scene.cycles.device = "CPU"
        return "CPU", ["CPU"]

    @classmethod
    def bake_octahedral_animation_atlas(
        cls,
        mesh_objs: list[Any],
        base_name: str,
        output_dir: str,
        mode: str = "OCTAHEDRAL_HEMI",
        atlas_resolution: int = 2048,
        target_engine: str = "UE5",
        dilation_iterations: int = 4,
        grid_size: int = 8,
    ) -> dict[str, str]:
        """
        Bakes an NxN Octahedral Impostor atlas using an ephemeral animation timeline render.
        Executes 4 unlit passes: BaseColor, Normal, Depth, and ORM.
        Packs normalized planar Z-depth into Normal.Alpha for UE5 Pixel Depth Offset (PDO).
        Applies BaseColor-mask-driven morphological dilation across all channels.
        Exports companion UE5 integration guide (README_UE5_SETUP.txt).
        """
        if not bpy or not mesh_objs:
            return {}

        try:
            from .impostor import resolve_impostor_export_dir
        except (ImportError, ValueError):
            from core.impostor import resolve_impostor_export_dir

        output_dir = resolve_impostor_export_dir(output_dir)
        results: dict[str, str] = {}

        all_coords: list[Any] = []
        for obj in mesh_objs:
            if hasattr(obj, "bound_box") and obj.bound_box:
                all_coords.extend([obj.matrix_world @ Vector(c) for c in obj.bound_box])
            elif hasattr(obj, "data") and hasattr(obj.data, "vertices"):
                all_coords.extend([obj.matrix_world @ v.co for v in obj.data.vertices])

        if not all_coords:
            all_coords = [Vector((-1.0, -1.0, -1.0)), Vector((1.0, 1.0, 1.0))]

        center, radius, ortho_scale = ImpostorCameraRig.compute_rig_parameters(all_coords)
        tile_res = max(32, atlas_resolution // grid_size)
        total_frames = grid_size * grid_size
        dist = radius * 2.5

        fn_vec = (
            ImpostorMath.hemi_octahedral_to_vector
            if mode == "OCTAHEDRAL_HEMI"
            else ImpostorMath.full_octahedral_to_vector
        )

        with EphemeralBakeSceneGuard() as bake_scene:
            if not bake_scene:
                return {}

            for obj in mesh_objs:
                if obj.name not in bake_scene.collection.objects:
                    bake_scene.collection.objects.link(obj)

            cam_obj = ImpostorCameraRig.setup_camera(
                bake_scene, center, radius, ortho_scale, angle_rad=0.0, pitch_rad=0.0
            )

            # Keyframe camera orbit across frames 1..total_frames
            for frame_idx in range(1, total_frames + 1):
                col = (frame_idx - 1) % grid_size
                row = (frame_idx - 1) // grid_size
                u = (col + 0.5) / float(grid_size)
                v = (row + 0.5) / float(grid_size)

                dir_vec = fn_vec(u, v)
                cam_pos = Vector(center) + Vector(dir_vec) * dist
                cam_obj.location = cam_pos

                right, up, forward = ImpostorMath.compute_camera_basis(dir_vec)
                rot_mat = Matrix((right, up, -forward)).transposed()
                cam_obj.rotation_euler = rot_mat.to_euler()

                cam_obj.keyframe_insert(data_path="location", frame=frame_idx)
                cam_obj.keyframe_insert(data_path="rotation_euler", frame=frame_idx)

            bake_scene.render.resolution_x = tile_res
            bake_scene.render.resolution_y = tile_res
            bake_scene.render.resolution_percentage = 100
            bake_scene.frame_start = 1
            bake_scene.frame_end = total_frames

            # 4 Unlit passes: BaseColor, Normal, Depth, ORM
            passes = [
                ("BaseColor", "BASE_COLOR"),
                ("Normal", "NORMAL"),
                ("Depth", "DEPTH"),
                ("ORM", "ORM"),
            ]

            raw_tiles: dict[str, dict[tuple[int, int], np.ndarray]] = {pname: {} for pname, _ in passes}

            with tempfile.TemporaryDirectory() as temp_dir:
                for chan_name, harness_layer in passes:
                    orig_materials: list[tuple[Any, list[Any]]] = []
                    for obj in mesh_objs:
                        if hasattr(obj, "data") and hasattr(obj.data, "materials"):
                            mats = list(obj.data.materials)
                            orig_materials.append((obj, mats))
                            override_mats = [
                                ImpostorShaderHarness.create_unlit_override_material(
                                    m,
                                    channel_layer=harness_layer,
                                    target_engine=target_engine,
                                    radius=radius,
                                    cam_distance=dist,
                                )
                                for m in mats
                            ]
                            obj.data.materials.clear()
                            for ov_m in override_mats:
                                if ov_m:
                                    obj.data.materials.append(ov_m)

                    try:
                        chan_prefix = os.path.join(temp_dir, f"{chan_name}_")
                        bake_scene.render.filepath = chan_prefix
                        bake_scene.render.image_settings.file_format = "PNG"
                        bake_scene.render.image_settings.color_mode = "RGBA"

                        bpy.ops.render.render(animation=True, scene=bake_scene.name)

                        for frame_idx in range(1, total_frames + 1):
                            col = (frame_idx - 1) % grid_size
                            row = (frame_idx - 1) // grid_size
                            frame_file = f"{chan_prefix}{frame_idx:04d}.png"
                            if os.path.exists(frame_file):
                                img = bpy.data.images.load(frame_file)
                                w, h = img.size
                                arr = np.empty(w * h * 4, dtype=np.float32)
                                img.pixels.foreach_get(arr)
                                bpy.data.images.remove(img, do_unlink=True)
                                tile_u8 = (arr.reshape((h, w, 4)) * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
                                raw_tiles[chan_name][(col, row)] = tile_u8
                    finally:
                        for obj, mats in orig_materials:
                            if hasattr(obj, "data") and hasattr(obj.data, "materials"):
                                obj.data.materials.clear()
                                for m in mats:
                                    obj.data.materials.append(m)

                # Process, merge Depth into Normal.A, dilate using BaseColor opacity mask
                composed_tiles: dict[str, list[tuple[np.ndarray, tuple[int, int]]]] = {
                    "BaseColor": [],
                    "Normal": [],
                    "ORM": [],
                }

                for frame_idx in range(1, total_frames + 1):
                    col = (frame_idx - 1) % grid_size
                    row = (frame_idx - 1) // grid_size
                    coord = (col, row)

                    base_tile = raw_tiles["BaseColor"].get(coord)
                    norm_tile = raw_tiles["Normal"].get(coord)
                    depth_tile = raw_tiles["Depth"].get(coord)
                    orm_tile = raw_tiles["ORM"].get(coord)

                    if base_tile is None or norm_tile is None:
                        continue

                    # Mask derived strictly from BaseColor cutout alpha
                    opacity_mask = base_tile[:, :, 3] > 12

                    # Pack Normal (RGB) + Depth (A)
                    if depth_tile is not None:
                        depth_ch = depth_tile[:, :, 0]
                        norm_depth = np.dstack([norm_tile[:, :, :3], depth_ch])
                        # Far boundary fallback for empty background
                        norm_depth[~opacity_mask, 3] = 255
                    else:
                        norm_depth = norm_tile

                    if dilation_iterations > 0:
                        base_proc = ImpostorMath.morphological_dilate_channels(
                            base_tile, opacity_mask, iterations=dilation_iterations
                        )
                        norm_proc = ImpostorMath.morphological_dilate_channels(
                            norm_depth, opacity_mask, iterations=dilation_iterations
                        )
                        orm_proc = (
                            ImpostorMath.morphological_dilate_channels(
                                orm_tile, opacity_mask, iterations=dilation_iterations
                            )
                            if orm_tile is not None
                            else np.zeros_like(base_tile)
                        )
                    else:
                        base_proc = base_tile
                        norm_proc = norm_depth
                        orm_proc = orm_tile if orm_tile is not None else np.zeros_like(base_tile)

                    composed_tiles["BaseColor"].append((base_proc, coord))
                    composed_tiles["Normal"].append((norm_proc, coord))
                    composed_tiles["ORM"].append((orm_proc, coord))

                output_maps = [
                    ("BaseColor", f"T_{base_name}_Impostor_BaseColor.png"),
                    ("Normal", f"T_{base_name}_Impostor_Normal.png"),
                    ("ORM", f"T_{base_name}_Impostor_ORM.png"),
                ]

                for chan_key, out_fname in output_maps:
                    tiles = composed_tiles[chan_key]
                    atlas_u8 = cls.compose_atlas_array(
                        tiles,
                        grid_cols=grid_size,
                        grid_rows=grid_size,
                        tile_w=tile_res,
                        tile_h=tile_res,
                        dilation_iterations=0,
                    )
                    out_path = os.path.join(output_dir, out_fname)
                    write_png_direct(out_path, atlas_u8)
                    results[chan_key] = out_path

        # Export companion Unreal Engine 5 setup guide
        try:
            from exporters.shaders.unreal_octahedral import generate_ue5_setup_guide

            center_tup = (float(center.x), float(center.y), float(center.z))
            guide_text = generate_ue5_setup_guide(
                base_name=base_name,
                grid_size=grid_size,
                sphere_radius=float(radius),
                sphere_center=center_tup,
            )
            guide_path = os.path.join(output_dir, f"README_{base_name}_UE5_SETUP.txt")
            with open(guide_path, "w", encoding="utf-8") as gf:
                gf.write(guide_text)
            results["UE5_Guide"] = guide_path
        except Exception as e:
            logger.warning("Could not generate UE5 setup guide: %s", e)

        results["sphere_radius"] = str(radius)
        results["sphere_center"] = f"{center.x:.4f},{center.y:.4f},{center.z:.4f}"
        return results

    @classmethod
    def bake_impostor_textures(
        cls,
        mesh_objs: list[Any],
        base_name: str,
        output_dir: str,
        mode: str = "14_PLANES",
        atlas_resolution: int = 2048,
        target_engine: str = "UE5",
        dilation_iterations: int = 4,
        impostor_obj: Optional[Any] = None,
    ) -> dict[str, str]:
        """
        Bakes BaseColor, Tangent Normal, and ORM (AO/Roughness/Metallic) maps using Cycles Selected-to-Active
        or 64-frame animation timeline rendering for Octahedral Impostors.
        """
        if not bpy or not mesh_objs:
            return {}

        if mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
            return cls.bake_octahedral_animation_atlas(
                mesh_objs=mesh_objs,
                base_name=base_name,
                output_dir=output_dir,
                mode=mode,
                atlas_resolution=atlas_resolution,
                target_engine=target_engine,
                dilation_iterations=dilation_iterations,
                grid_size=8,
            )

        try:
            from .impostor import resolve_impostor_export_dir
        except (ImportError, ValueError):
            from core.impostor import resolve_impostor_export_dir

        output_dir = resolve_impostor_export_dir(output_dir)
        results: dict[str, str] = {}

        target_impostor = impostor_obj or bpy.data.objects.get(f"{base_name}_LOD_Impostor")
        if not target_impostor:
            logger.warning("No target impostor object found for baking '%s'", base_name)
            return {}

        # Calculate bounding dimensions to set ray cast distance
        all_coords = []
        for obj in mesh_objs:
            if hasattr(obj, "bound_box") and obj.bound_box:
                all_coords.extend([obj.matrix_world @ Vector(c) for c in obj.bound_box])
            elif hasattr(obj, "data") and hasattr(obj.data, "vertices"):
                all_coords.extend([obj.matrix_world @ v.co for v in obj.data.vertices])

        max_span = max((max(c[i] for c in all_coords) - min(c[i] for c in all_coords) for i in range(3)), default=4.0)

        scene = bpy.context.scene
        orig_engine = scene.render.engine
        scene.render.engine = "CYCLES"

        # Automatically probe and configure best compute device (NVIDIA OptiX/CUDA, Apple Metal, AMD HIP, Intel oneAPI, or CPU)
        cls.configure_cycles_compute_device(scene)

        is_bg = getattr(bpy.app, "background", False) if bpy else False
        scene.cycles.samples = 1 if is_bg else 16
        scene.cycles.use_denoising = not is_bg
        scene.render.film_transparent = True

        # Ensure objects are visible in view layer
        orig_vis: list[tuple[Any, bool]] = []
        for o in mesh_objs + [target_impostor]:
            if hasattr(o, "hide_viewport"):
                orig_vis.append((o, o.hide_viewport))
                o.hide_viewport = False

        # Prepare selection
        bpy.ops.object.select_all(action="DESELECT")
        for o in mesh_objs:
            o.select_set(True)
        target_impostor.select_set(True)
        bpy.context.view_layer.objects.active = target_impostor

        # Bake configuration
        scene.render.bake.use_selected_to_active = True
        scene.render.bake.cage_extrusion = max(1.0, max_span * 1.0)
        scene.render.bake.max_ray_distance = max(4.0, max_span * 2.5)
        scene.render.bake.margin = 4
        scene.render.bake.target = "IMAGE_TEXTURES"

        # Create temporary bake images
        res = atlas_resolution
        img_diff = bpy.data.images.new(f"__om_diff_{base_name}", width=res, height=res, alpha=True)
        img_diff.colorspace_settings.name = "sRGB"
        img_diff.generated_color = (0.0, 0.0, 0.0, 0.0)

        img_norm = bpy.data.images.new(f"__om_norm_{base_name}", width=res, height=res, alpha=True)
        img_norm.colorspace_settings.name = "Non-Color"
        img_norm.generated_color = (0.5, 0.5, 1.0, 0.0)

        img_rough = bpy.data.images.new(f"__om_rough_{base_name}", width=res, height=res, alpha=True)
        img_rough.colorspace_settings.name = "Non-Color"

        img_ao = bpy.data.images.new(f"__om_ao_{base_name}", width=res, height=res, alpha=True)
        img_ao.colorspace_settings.name = "Non-Color"

        mat = (
            target_impostor.data.materials[0]
            if (hasattr(target_impostor.data, "materials") and target_impostor.data.materials)
            else None
        )
        if not mat:
            mat = bpy.data.materials.new(name=f"M_{base_name}_Impostor")
            target_impostor.data.materials.append(mat)

        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bake_slot = nodes.new("ShaderNodeTexImage")
        nodes.active = bake_slot

        try:
            # 1. Bake BaseColor (Diffuse Color pass)
            bake_slot.image = img_diff
            scene.render.bake.use_pass_direct = False
            scene.render.bake.use_pass_indirect = False
            scene.render.bake.use_pass_color = True
            bpy.ops.object.bake(type="DIFFUSE")
            base_path = os.path.join(output_dir, f"T_{base_name}_Impostor_BaseColor.png")
            img_diff.filepath_raw = base_path
            img_diff.file_format = "PNG"
            img_diff.save()
            results["BaseColor"] = base_path

            # 2. Bake Tangent Normal
            bake_slot.image = img_norm
            scene.render.bake.normal_space = "TANGENT"
            bpy.ops.object.bake(type="NORMAL")
            norm_path = os.path.join(output_dir, f"T_{base_name}_Impostor_Normal.png")
            img_norm.filepath_raw = norm_path
            img_norm.file_format = "PNG"
            img_norm.save()
            results["Normal"] = norm_path

            # 3. Bake Roughness
            bake_slot.image = img_rough
            bpy.ops.object.bake(type="ROUGHNESS")

            # 4. Bake AO
            bake_slot.image = img_ao
            bpy.ops.object.bake(type="AO")

            # 5. Pack ORM (AO=Red, Roughness=Green, Metallic=Blue, Alpha=Alpha)
            base_pix, rough_pix, ao_pix = (np.empty(res * res * 4, dtype=np.float32) for _ in range(3))
            img_diff.pixels.foreach_get(base_pix)
            img_rough.pixels.foreach_get(rough_pix)
            img_ao.pixels.foreach_get(ao_pix)

            orm_pix = np.zeros((res, res, 4), dtype=np.float32)
            orm_pix[:, :, 0] = ao_pix.reshape((res, res, 4))[:, :, 0]
            orm_pix[:, :, 1] = rough_pix.reshape((res, res, 4))[:, :, 0]
            orm_pix[:, :, 3] = base_pix.reshape((res, res, 4))[:, :, 3]

            img_orm = bpy.data.images.new(f"__om_orm_{base_name}", width=res, height=res, alpha=True)
            img_orm.colorspace_settings.name = "Non-Color"
            img_orm.pixels.foreach_set(orm_pix.flatten())
            orm_path = os.path.join(output_dir, f"T_{base_name}_Impostor_ORM.png")
            img_orm.filepath_raw = orm_path
            img_orm.file_format = "PNG"
            img_orm.save()
            results["ORM"] = orm_path

            bpy.data.images.remove(img_orm, do_unlink=True)
        finally:
            nodes.remove(bake_slot)
            for temp_img in [img_diff, img_norm, img_rough, img_ao]:
                try:
                    bpy.data.images.remove(temp_img, do_unlink=True)
                except Exception as exc:
                    logger.debug("Failed removing temp image: %s", exc)
            for o, vis in orig_vis:
                if hasattr(o, "hide_viewport"):
                    o.hide_viewport = vis
            scene.render.engine = orig_engine

        return results


__all__ = [
    "EphemeralBakeSceneGuard",
    "ImpostorCameraRig",
    "ImpostorShaderHarness",
    "ImpostorAtlasBaker",
]
