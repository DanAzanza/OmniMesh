"""
OmniMesh Ephemeral Bake Scene Guard & Orthographic Camera Rig for Impostor Baking.
Blender 4.2+ and 5.0+ LTS Compatible.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Optional, Sequence, cast

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData, Camera, Context, Object, Scene, World
    from mathutils import Vector
else:
    try:
        import bpy
        from bpy.types import Camera, Context, Object, Scene, World
        from mathutils import Vector
    except ImportError:
        bpy = None
        Camera = object
        Context = object
        Object = object
        Scene = object
        World = object
        from .impostor_math import Vector
    BlendData = object

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
        *,
        blend_data: BlendData | None = None,
    ):
        self.temp_scene_name = scene_name
        self.context = context
        self.orig_scene = orig_scene
        self.bake_scene: Optional[bpy.types.Scene] = None
        self.blend_data = blend_data

    def __enter__(self) -> Optional[bpy.types.Scene]:
        ctx = self.context
        bdata = self.blend_data
        if not bdata and not bpy:
            return None

        if not self.orig_scene:
            bdata_scenes = getattr(bdata, "scenes", None) if bdata else None
            self.orig_scene = getattr(ctx, "scene", None) or (
                bdata_scenes[0] if bdata_scenes and len(bdata_scenes) > 0 else None
            )

        bdata_scenes = getattr(bdata, "scenes", None) if bdata else None
        if not bdata_scenes:
            return None

        self.bake_scene = bdata_scenes.new(self.temp_scene_name)
        if not self.bake_scene:
            return None

        # Configure minimal, fast unlit rendering environment
        render = getattr(self.bake_scene, "render", None)
        if render:
            render.film_transparent = True
            render.dither_intensity = 0.0
            is_bg = getattr(getattr(bpy, "app", None), "background", False) if bpy else False
            preferred = (
                ("CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")
                if is_bg
                else ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "CYCLES")
            )
            cycles = getattr(self.bake_scene, "cycles", None)
            eevee = getattr(self.bake_scene, "eevee", None)
            for eng in preferred:
                try:
                    render.engine = eng  # type: ignore[assignment]
                    if render.engine == eng:
                        if eng == "CYCLES" and cycles is not None:
                            for attr, val in (
                                ("samples", 1),
                                ("max_bounces", 0),
                                ("diffuse_bounces", 0),
                                ("glossy_bounces", 0),
                                ("device", "CPU"),
                            ):
                                setattr(cycles, attr, val)
                        elif eevee is not None and hasattr(eevee, "taa_render_samples"):
                            eevee.taa_render_samples = 1
                        break
                except (TypeError, ValueError, AttributeError) as eng_err:
                    logger.debug("Render engine %s not available: %s", eng, eng_err)

        # Black unlit world background
        bdata_worlds = getattr(bdata, "worlds", None) if bdata else None
        if bdata_worlds:
            world = bdata_worlds.new(f"{self.temp_scene_name}_World")
            world.use_nodes = True
            if getattr(world, "node_tree", None) and getattr(world.node_tree, "nodes", None):
                bg = world.node_tree.nodes.get("Background")
                if bg and "Color" in bg.inputs:
                    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            self.bake_scene.world = world

        win = getattr(ctx, "window", None)
        if win:
            win.scene = self.bake_scene
        return self.bake_scene

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        ctx = self.context
        bdata = self.blend_data
        if not bdata and not bpy:
            return

        bdata_objs = getattr(bdata, "objects", None) if bdata else None
        bdata_cams = getattr(bdata, "cameras", None) if bdata else None
        bdata_worlds = getattr(bdata, "worlds", None) if bdata else None
        bdata_scenes = getattr(bdata, "scenes", None) if bdata else None

        try:
            win = getattr(ctx, "window", None)
            if self.orig_scene and win:
                win.scene = self.orig_scene
            if self.bake_scene:
                if getattr(self.bake_scene, "camera", None):
                    cam_obj = self.bake_scene.camera
                    cam_data = getattr(cam_obj, "data", None)
                    if bdata_objs:
                        bdata_objs.remove(cam_obj, do_unlink=True)
                    if cam_data and bdata_cams:
                        bdata_cams.remove(cam_data, do_unlink=True)
                if getattr(self.bake_scene, "world", None):
                    w = self.bake_scene.world
                    self.bake_scene.world = None
                    if bdata_worlds and w:
                        bdata_worlds.remove(w, do_unlink=True)
                if bdata_scenes:
                    bdata_scenes.remove(self.bake_scene, do_unlink=True)
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
        *,
        blend_data: BlendData | None = None,
    ) -> bpy.types.Object | None:
        if not scene:
            return None

        bdata = blend_data
        bdata_cams = getattr(bdata, "cameras", None) if bdata else None
        bdata_objs = getattr(bdata, "objects", None) if bdata else None

        if scene.camera is not None and getattr(scene.camera, "data", None) is not None:
            cam_data = cast("bpy.types.Camera", scene.camera.data)
        elif bdata_cams:
            cam_data = cast("bpy.types.Camera", bdata_cams.new("OMNIMESH_Bake_Cam"))
        else:
            return None

        cam_data.type = "ORTHO"
        cam_data.ortho_scale = ortho_scale

        dist = radius * 2.5
        cam_data.clip_start = max(0.001, dist - radius * 1.5)
        cam_data.clip_end = dist + radius * 1.5

        if not getattr(scene, "camera", None):
            if not bdata_objs:
                return None
            cam_obj = bdata_objs.new("OMNIMESH_Bake_Cam_Obj", cam_data)
            coll = getattr(scene, "collection", None)
            if coll and hasattr(coll, "objects"):
                coll.objects.link(cam_obj)
            scene.camera = cam_obj
        else:
            cam_obj = scene.camera

        if cam_obj is None:
            return None

        cp = math.cos(pitch_rad)
        center_v = Vector((center[0], center[1], center[2]))
        offset = Vector((dist * cp * math.sin(angle_rad), -dist * cp * math.cos(angle_rad), dist * math.sin(pitch_rad)))
        cam_obj.location = center_v + offset
        dir_vec = center_v - cam_obj.location
        if getattr(dir_vec, "length", 0.0) > 1e-6 and hasattr(dir_vec, "to_track_quat"):
            rot_quat = dir_vec.to_track_quat("-Z", "Y")
            cam_obj.rotation_euler = rot_quat.to_euler()

        return cam_obj


__all__ = ["EphemeralBakeSceneGuard", "ImpostorCameraRig"]
