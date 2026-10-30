"""
OmniMesh Ephemeral Bake Scene Guard & Orthographic Camera Rig for Impostor Baking.
Blender 4.2+ and 5.0+ LTS Compatible.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Optional, Sequence

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from mathutils import Vector
else:
    try:
        import bpy
        from mathutils import Vector
    except ImportError:
        bpy = None
        try:
            from .impostor_math import Vector
        except (ImportError, ValueError):
            from core.impostor_math import Vector

from .metrics import compute_bounding_sphere


class EphemeralBakeSceneGuard:
    """
    Context manager creating an isolated temporary Blender Scene.
    Guarantees that active user cameras, lighting, world settings, and render engines
    remain completely unpolluted during baking passes.
    """

    def __init__(
        self,
        scene_name: str = "OMNIMESH_TEMP_BAKE",
        orig_scene: bpy.types.Scene | None = None,
        context: bpy.types.Context | None = None,
    ):
        self.temp_scene_name, self.context, self.orig_scene, self.bake_scene = scene_name, context, orig_scene, None

    def __enter__(self) -> Optional[bpy.types.Scene]:
        if not bpy:
            return None
        ctx = self.context
        if not self.orig_scene:
            self.orig_scene = getattr(ctx, "scene", None) or (
                bpy.data.scenes[0] if bpy and getattr(bpy.data, "scenes", None) else None
            )
        self.bake_scene = bpy.data.scenes.new(self.temp_scene_name)

        # Configure minimal, fast unlit rendering environment
        render: Any = self.bake_scene.render
        render.film_transparent, render.dither_intensity = True, 0.0
        is_bg = getattr(bpy.app, "background", False) if bpy else False
        preferred = (
            ("CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
            if is_bg
            else ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES")
        )
        cycles: Any = getattr(self.bake_scene, "cycles", None)
        eevee: Any = getattr(self.bake_scene, "eevee", None)
        for eng in preferred:
            try:
                render.engine = eng
                if render.engine == eng:
                    if eng == "CYCLES" and cycles:
                        cycles.samples, cycles.max_bounces, cycles.diffuse_bounces, cycles.glossy_bounces = 1, 0, 0, 0
                        cycles.device = "CPU"
                    elif eevee and hasattr(eevee, "taa_render_samples"):
                        eevee.taa_render_samples = 1
                    break
            except (TypeError, ValueError, AttributeError) as eng_err:
                logger.debug("Render engine %s not available: %s", eng, eng_err)

        # Black unlit world background
        world = bpy.data.worlds.new(f"{self.temp_scene_name}_World")
        world.use_nodes = True
        if world.node_tree and world.node_tree.nodes:
            bg = world.node_tree.nodes.get("Background")
            if bg and "Color" in bg.inputs:
                bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        self.bake_scene.world = world

        win = getattr(ctx, "window", None)
        if win:
            win.scene = self.bake_scene
        return self.bake_scene

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        if not bpy:
            return
        try:
            ctx = self.context
            win = getattr(ctx, "window", None)
            if self.orig_scene and win:
                win.scene = self.orig_scene
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
        except (RuntimeError, ReferenceError, AttributeError) as exc:
            logger.debug("Failed cleaning ephemeral bake scene: %s", exc)


class ImpostorCameraRig:
    """
    Manages an orthographic camera orbiting an asset bounding sphere center.
    Calculates exact frustum bounds to prevent clipping at any rotation angle.
    """

    @staticmethod
    def compute_rig_parameters(coords: Sequence[Sequence[float] | Vector]) -> tuple[Vector, float, float]:
        center, radius = compute_bounding_sphere(coords)
        radius = max(0.25, float(radius))
        # 4% margin ensures grazing silhouette edges are not clipped by orthographic frustum
        ortho_scale = 2.0 * radius * 1.04
        return Vector((center[0], center[1], center[2])), radius, ortho_scale

    @classmethod
    def setup_camera(
        cls,
        scene: bpy.types.Scene | None,
        center: Sequence[float] | Vector,
        radius: float,
        ortho_scale: float,
        angle_rad: float = 0.0,
        pitch_rad: float = 0.0,
    ) -> bpy.types.Object | None:
        if not bpy or not scene:
            return None

        cam_data: Any = scene.camera.data if scene.camera else bpy.data.cameras.new("OMNIMESH_Bake_Cam")
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
        center_v = Vector((center[0], center[1], center[2]))
        offset = Vector((dist * cp * math.sin(angle_rad), -dist * cp * math.cos(angle_rad), dist * math.sin(pitch_rad)))
        cam_obj.location = center_v + offset
        dir_vec = center_v - cam_obj.location
        if dir_vec.length > 1e-6:
            rot_quat = dir_vec.to_track_quat("-Z", "Y")
            cam_obj.rotation_euler = rot_quat.to_euler()

        return cam_obj


__all__ = ["EphemeralBakeSceneGuard", "ImpostorCameraRig"]
