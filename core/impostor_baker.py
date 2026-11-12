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
from typing import TYPE_CHECKING, Any, Iterable, Optional, cast

import numpy as np

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    import mathutils
    from mathutils import Matrix, Vector
else:
    try:
        import bpy
        import mathutils
        from mathutils import Matrix, Vector
    except ImportError:
        bpy = None
        mathutils = None
        Matrix = None  # type: ignore
        from .impostor_math import Vector
    BlendData = object


from .exceptions import ImpostorBakeError
from .impostor_harness import ImpostorShaderHarness
from .impostor_math import ImpostorMath
from .impostor_rig import EphemeralBakeSceneGuard, ImpostorCameraRig
from .png_writer import write_png_direct


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
    def configure_cycles_compute_device(
        cls, scene: bpy.types.Scene | None, context: bpy.types.Context | None = None
    ) -> tuple[str, list[str]]:
        """
        Automatically probes and configures the optimal compute device for Cycles baking.
        Supports NVIDIA (OptiX, CUDA), Apple Silicon (Metal), AMD (HIP), Intel (oneAPI),
        and safely falls back to CPU if no compatible GPU hardware is detected.
        """
        if not bpy:
            return "CPU", ["CPU"]

        backend_priority = ["OPTIX", "METAL", "HIP", "ONEAPI", "CUDA"]
        try:
            ctx = context
            prefs = ctx.preferences if ctx else None
            addons = prefs.addons if prefs else None
            cycles_addon = addons.get("cycles") if addons else None
            if cycles_addon and cycles_addon.preferences:
                cpref = cast(Any, cycles_addon.preferences)
                try:
                    avail = {item[0] for item in cpref.get_device_types(ctx)} if ctx else set()
                except AttributeError:
                    avail = set()
                for backend in backend_priority:
                    if backend in avail:
                        try:
                            cpref.compute_device_type = backend
                            try:
                                cpref.get_devices()
                            except AttributeError:
                                pass
                            active_devs = [d for d in (cpref.devices or ()) if d.type == backend]
                            if active_devs:
                                for d in active_devs:
                                    d.use = True
                                cycles_settings = getattr(scene, "cycles", None) if scene else None
                                if cycles_settings is not None:
                                    cycles_settings.device = "GPU"
                                dev_names = [str(d.name) for d in active_devs]
                                logger.info("Configured Cycles GPU baking: %s (%s)", backend, ", ".join(dev_names))
                                return backend, dev_names
                        except (RuntimeError, AttributeError, TypeError, ValueError) as b_err:
                            logger.debug("Cycles backend %s failed: %s", backend, b_err)
                try:
                    cpref.compute_device_type = "NONE"
                except AttributeError:
                    pass
        except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
            logger.debug("Failed configuring Cycles compute device: %s", exc)

        cycles_settings = getattr(scene, "cycles", None) if scene else None
        if cycles_settings is not None:
            cycles_settings.device = "CPU"
        return "CPU", ["CPU"]

    @classmethod
    def bake_octahedral_animation_atlas(
        cls,
        mesh_objs: list[bpy.types.Object],
        base_name: str,
        output_dir: str,
        mode: str = "OCTAHEDRAL_HEMI",
        atlas_resolution: int = 2048,
        target_engine: str = "UE5",
        dilation_iterations: int = 4,
        grid_size: int = 8,
        context: bpy.types.Context | None = None,
        *,
        blend_data: BlendData,
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

        from .impostor import resolve_impostor_export_dir

        bdata = blend_data
        output_dir = resolve_impostor_export_dir(output_dir, blend_data=bdata)
        results: dict[str, str] = {}

        all_coords: list[Vector] = []
        for obj in mesh_objs:
            obj_data = cast("bpy.types.Mesh | None", obj.data)
            if obj.bound_box:
                all_coords.extend([obj.matrix_world @ Vector(c) for c in obj.bound_box])
            elif obj_data and obj_data.vertices:
                all_coords.extend([obj.matrix_world @ v.co for v in obj_data.vertices])

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

        with EphemeralBakeSceneGuard(
            scene_name=f"{base_name}_BakeScene", context=context, blend_data=bdata
        ) as bake_scene:
            if not bake_scene:
                return {}

            for obj in mesh_objs:
                if obj.name not in bake_scene.collection.objects:
                    bake_scene.collection.objects.link(obj)

            cam_obj = ImpostorCameraRig.setup_camera(
                bake_scene, center, radius, ortho_scale, angle_rad=0.0, pitch_rad=0.0, blend_data=bdata
            )
            if not cam_obj:
                raise ImpostorBakeError("Failed to initialize bake camera.")

            # Keyframe camera orbit across frames 1..total_frames
            for frame_idx in range(1, total_frames + 1):
                col, row = (frame_idx - 1) % grid_size, (frame_idx - 1) // grid_size
                u, v = (col + 0.5) / float(grid_size), (row + 0.5) / float(grid_size)
                dir_vec = fn_vec(u, v)
                cam_obj.location = (
                    Vector((center[0], center[1], center[2])) + Vector((dir_vec[0], dir_vec[1], dir_vec[2])) * dist
                )
                right, up, forward = ImpostorMath.compute_camera_basis(dir_vec)
                basis_rows = (
                    (right.x, right.y, right.z),
                    (up.x, up.y, up.z),
                    (-forward.x, -forward.y, -forward.z),
                )
                cam_obj.rotation_euler = Matrix(basis_rows).transposed().to_euler()
                cam_obj.keyframe_insert(data_path="location", frame=frame_idx)
                cam_obj.keyframe_insert(data_path="rotation_euler", frame=frame_idx)

            bake_scene.render.resolution_x, bake_scene.render.resolution_y = tile_res, tile_res
            bake_scene.render.resolution_percentage = 100
            bake_scene.frame_start, bake_scene.frame_end = 1, total_frames

            # 4 Unlit passes: BaseColor, Normal, Depth, ORM
            passes = [("BaseColor", "BASE_COLOR"), ("Normal", "NORMAL"), ("Depth", "DEPTH"), ("ORM", "ORM")]
            raw_tiles: dict[str, dict[tuple[int, int], np.ndarray]] = {pname: {} for pname, _ in passes}

            with tempfile.TemporaryDirectory() as temp_dir:
                for chan_name, harness_layer in passes:
                    orig_materials: list[tuple[bpy.types.Object, list[bpy.types.Material | None]]] = []
                    for obj in mesh_objs:
                        obj_data = cast("bpy.types.Mesh | None", obj.data)
                        if obj_data and obj_data.materials is not None:
                            mats = list(obj_data.materials)
                            orig_materials.append((obj, mats))
                            bake_mats = mats if mats else [None]
                            override_mats = [
                                ImpostorShaderHarness.create_unlit_override_material(
                                    m,
                                    channel_layer=harness_layer,
                                    target_engine=target_engine,
                                    radius=radius,
                                    cam_distance=dist,
                                    blend_data=bdata,
                                )
                                for m in bake_mats
                            ]
                            obj_data.materials.clear()
                            for ov_m in override_mats:
                                if ov_m:
                                    obj_data.materials.append(ov_m)

                    try:
                        chan_prefix = os.path.join(temp_dir, f"{chan_name}_")
                        bake_scene.render.filepath = chan_prefix
                        bake_scene.render.image_settings.file_format, bake_scene.render.image_settings.color_mode = (
                            "PNG",
                            "RGBA",
                        )
                        if bake_scene.view_settings:
                            try:
                                cast(Any, bake_scene.view_settings).view_transform = (
                                    "Standard" if chan_name == "BaseColor" else "Raw"
                                )
                            except (TypeError, ValueError, AttributeError) as exc:
                                logger.debug("Failed setting view_transform on bake scene: %s", exc)

                        ctx = context
                        win = ctx.window if ctx else None
                        try:
                            if win and ctx:
                                try:
                                    with cast(Any, ctx).temp_override(scene=bake_scene, window=win):
                                        bpy.ops.render.render(animation=True, scene=bake_scene.name)
                                except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
                                    logger.debug("Render temp_override fallback: %s", exc)
                                    bpy.ops.render.render(animation=True, scene=bake_scene.name)
                            else:
                                bpy.ops.render.render(animation=True, scene=bake_scene.name)
                        except (RuntimeError, ValueError) as render_exc:
                            raise ImpostorBakeError(
                                f"Octahedral animation render failed for pass '{chan_name}': {render_exc}"
                            ) from render_exc

                        bdata_imgs = bdata.images if bdata else None
                        for frame_idx in range(1, total_frames + 1):
                            col, row = (frame_idx - 1) % grid_size, (frame_idx - 1) // grid_size
                            frame_file = f"{chan_prefix}{frame_idx:04d}.png"
                            if os.path.exists(frame_file) and bdata_imgs:
                                img = bdata_imgs.load(frame_file)
                                sz = list(cast("Iterable[int]", img.size))
                                w, h = int(sz[0]), int(sz[1])
                                arr = np.empty(w * h * 4, dtype=np.float32)
                                img.pixels.foreach_get(arr)
                                bdata_imgs.remove(img, do_unlink=True)
                                raw_tiles[chan_name][(col, row)] = np.ascontiguousarray(
                                    (arr.reshape((h, w, 4))[::-1] * 255.0 + 0.5).clip(0, 255).astype(np.uint8)
                                )
                    finally:
                        for obj, mats in orig_materials:
                            m_data = cast("bpy.types.Mesh | None", obj.data)
                            if m_data is not None and m_data.materials is not None:
                                m_data.materials.clear()
                                for m in mats:
                                    m_data.materials.append(m)

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
                        dilate_fn = ImpostorMath.morphological_dilate_channels
                        base_proc = dilate_fn(base_tile, opacity_mask, iterations=dilation_iterations)
                        norm_proc = dilate_fn(norm_depth, opacity_mask, iterations=dilation_iterations)
                        orm_proc = (
                            dilate_fn(orm_tile, opacity_mask, iterations=dilation_iterations)
                            if orm_tile is not None
                            else np.zeros_like(base_tile)
                        )
                    else:
                        base_proc, norm_proc = base_tile, norm_depth
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
                    atlas_u8 = cls.compose_atlas_array(
                        composed_tiles[chan_key],
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
            try:
                from ..exporters.shaders.unreal_octahedral import generate_ue5_setup_guide
            except (ImportError, ValueError):
                from exporters.shaders.unreal_octahedral import generate_ue5_setup_guide

            center_tup = (float(center.x), float(center.y), float(center.z))
            guide_text = generate_ue5_setup_guide(
                base_name=base_name, grid_size=grid_size, sphere_radius=float(radius), sphere_center=center_tup
            )
            guide_path = os.path.join(output_dir, f"README_{base_name}_UE5_SETUP.txt")
            with open(guide_path, "w", encoding="utf-8") as gf:
                gf.write(guide_text)
            results["UE5_Guide"] = guide_path
        except (OSError, UnicodeError, ImportError, ValueError) as e:
            logger.warning("Could not generate UE5 setup guide: %s", e)

        results["sphere_radius"] = str(radius)
        results["sphere_center"] = f"{center.x:.4f},{center.y:.4f},{center.z:.4f}"
        return results

    @classmethod
    def bake_impostor_textures(
        cls,
        mesh_objs: list[bpy.types.Object],
        base_name: str,
        output_dir: str,
        mode: str = "14_PLANES",
        atlas_resolution: int = 2048,
        target_engine: str = "UE5",
        dilation_iterations: int = 4,
        impostor_obj: Optional[bpy.types.Object] = None,
        context: bpy.types.Context | None = None,
        *,
        blend_data: BlendData,
    ) -> dict[str, str]:
        """
        Bakes BaseColor, Tangent Normal, and ORM (AO/Roughness/Metallic) maps using Cycles Selected-to-Active
        or 64-frame animation timeline rendering for Octahedral Impostors.
        """
        if not bpy or not mesh_objs:
            return {}

        bdata = blend_data
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
                context=context,
                blend_data=bdata,
            )

        from .impostor import resolve_impostor_export_dir

        output_dir = resolve_impostor_export_dir(output_dir, blend_data=bdata)
        results: dict[str, str] = {}

        bdata_objs = bdata.objects if bdata else None
        target_impostor = impostor_obj or (bdata_objs.get(f"{base_name}_LOD_Impostor") if bdata_objs else None)
        if not target_impostor:
            logger.warning("No target impostor object found for baking '%s'", base_name)
            return {}

        # Calculate bounding dimensions to set ray cast distance
        all_coords = []
        for obj in mesh_objs:
            obj_data = cast("bpy.types.Mesh | None", obj.data)
            if obj.bound_box:
                all_coords.extend([obj.matrix_world @ Vector(c) for c in obj.bound_box])
            elif obj_data and obj_data.vertices:
                all_coords.extend([obj.matrix_world @ v.co for v in obj_data.vertices])

        max_span = max((max(c[i] for c in all_coords) - min(c[i] for c in all_coords) for i in range(3)), default=4.0)

        ctx = context
        bdata_scenes = bdata.scenes if bdata else None
        scene = (ctx.scene if ctx else None) or (bdata_scenes[0] if bdata_scenes and len(bdata_scenes) > 0 else None)
        if not scene:
            return {}
        orig_engine = scene.render.engine
        cast(Any, scene.render).engine = "CYCLES"

        # Automatically probe and configure best compute device (NVIDIA OptiX/CUDA, Apple Metal, AMD HIP, Intel oneAPI, or CPU)
        cls.configure_cycles_compute_device(scene, context=ctx)

        is_bg = bool(bpy.app.background) if (bpy and bpy.app) else False
        cycles = getattr(scene, "cycles", None)
        if cycles:
            cycles.samples = 1 if is_bg else 16
            cycles.use_denoising = not is_bg
        scene.render.film_transparent = True

        # Ensure objects are visible in view layer
        orig_vis: list[tuple[bpy.types.Object, bool]] = []
        for o in mesh_objs + [target_impostor]:
            orig_vis.append((o, o.hide_viewport))
            o.hide_viewport = False

        # Prepare selection
        bpy.ops.object.select_all(action="DESELECT")
        for o in mesh_objs:
            o.select_set(True)
        target_impostor.select_set(True)
        vl = ctx.view_layer if ctx else None
        if not vl and scene and scene.view_layers and len(scene.view_layers) > 0:
            vl = scene.view_layers[0]
        if vl and vl.objects is not None:
            vl.objects.active = target_impostor

        # Bake configuration & temporary bake images
        bk = scene.render.bake
        bk.use_selected_to_active, bk.margin, bk.target = True, 4, "IMAGE_TEXTURES"
        bk.cage_extrusion, bk.max_ray_distance = max(1.0, max_span * 1.0), max(4.0, max_span * 2.5)
        res = atlas_resolution
        bdata_imgs = bdata.images if bdata else None
        if not bdata_imgs:
            return {}
        img_diff = bdata_imgs.new(f"__om_diff_{base_name}", width=res, height=res, alpha=True)
        img_diff.colorspace_settings.name, img_diff.generated_color = "sRGB", (0.0, 0.0, 0.0, 0.0)  # type: ignore[assignment]
        img_norm = bdata_imgs.new(f"__om_norm_{base_name}", width=res, height=res, alpha=True)
        img_norm.colorspace_settings.name, img_norm.generated_color = "Non-Color", (0.5, 0.5, 1.0, 0.0)  # type: ignore[assignment]
        img_rough = bdata_imgs.new(f"__om_rough_{base_name}", width=res, height=res, alpha=True)
        img_rough.colorspace_settings.name = "Non-Color"  # type: ignore[assignment]
        img_ao = bdata_imgs.new(f"__om_ao_{base_name}", width=res, height=res, alpha=True)
        img_ao.colorspace_settings.name = "Non-Color"  # type: ignore[assignment]

        imp_data = cast("bpy.types.Mesh | None", target_impostor.data)
        mat = imp_data.materials[0] if (imp_data and imp_data.materials) else None
        bdata_mats = bdata.materials if bdata else None
        if not mat and bdata_mats:
            mat = bdata_mats.new(name=f"M_{base_name}_Impostor")
            if imp_data and imp_data.materials is not None:
                imp_data.materials.append(mat)

        if not mat:
            raise ImpostorBakeError(f"Failed creating target impostor material for '{base_name}'.")

        mat.use_nodes = True
        if not mat.node_tree:
            raise ImpostorBakeError("Target impostor material has no node tree.")
        nodes = mat.node_tree.nodes
        bake_slot = cast("bpy.types.ShaderNodeTexImage", nodes.new("ShaderNodeTexImage"))
        nodes.active = bake_slot

        muted_unbound_nodes: list[tuple[bpy.types.Node, bool]] = []
        for n in nodes:
            if n != bake_slot and n.type == "TEX_IMAGE" and cast("bpy.types.ShaderNodeTexImage", n).image is None:
                muted_unbound_nodes.append((n, bool(n.mute)))
                n.mute = True

        try:
            # 1. Bake BaseColor (Diffuse Color pass)
            bake_slot.image = img_diff
            bk.use_pass_direct, bk.use_pass_indirect, bk.use_pass_color = False, False, True
            bpy.ops.object.bake(type="DIFFUSE")
            base_path = os.path.join(output_dir, f"T_{base_name}_Impostor_BaseColor.png")
            img_diff.filepath_raw, img_diff.file_format = base_path, "PNG"
            img_diff.save()
            results["BaseColor"] = base_path

            # 2. Bake Tangent Normal
            bake_slot.image, bk.normal_space = img_norm, "TANGENT"
            bpy.ops.object.bake(type="NORMAL")
            norm_path = os.path.join(output_dir, f"T_{base_name}_Impostor_Normal.png")
            img_norm.filepath_raw, img_norm.file_format = norm_path, "PNG"
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

            img_orm = bdata_imgs.new(f"__om_orm_{base_name}", width=res, height=res, alpha=True)
            img_orm.colorspace_settings.name = "Non-Color"  # type: ignore[assignment]
            cast(Any, img_orm.pixels).foreach_set(orm_pix.flatten())
            orm_path = os.path.join(output_dir, f"T_{base_name}_Impostor_ORM.png")
            img_orm.filepath_raw, img_orm.file_format = orm_path, "PNG"
            img_orm.save()
            results["ORM"] = orm_path

            bdata_imgs.remove(img_orm, do_unlink=True)
        except (RuntimeError, ValueError, OSError) as b_err:
            raise ImpostorBakeError(f"Selected-to-active impostor bake failed for '{base_name}': {b_err}") from b_err
        finally:
            for n, orig_mute in muted_unbound_nodes:
                try:
                    n.mute = orig_mute
                except (RuntimeError, ReferenceError, AttributeError) as exc:
                    logger.debug("Restoring node mute state failed: %s", exc)
            nodes.remove(bake_slot)
            for temp_img in [img_diff, img_norm, img_rough, img_ao]:
                try:
                    bdata_imgs.remove(temp_img, do_unlink=True)
                except (RuntimeError, ReferenceError, AttributeError) as exc:
                    logger.debug("Failed removing temp image: %s", exc)
            for o, vis in orig_vis:
                o.hide_viewport = vis
            scene.render.engine = orig_engine

        return results


__all__ = ["EphemeralBakeSceneGuard", "ImpostorCameraRig", "ImpostorShaderHarness", "ImpostorAtlasBaker"]
