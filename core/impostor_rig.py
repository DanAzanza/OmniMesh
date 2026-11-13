"""
OmniMesh Ephemeral Bake Scene Guard & Orthographic Camera Rig for Impostor Baking.
Blender 5.0+ & 5.2 LTS Compatible.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import logging
import math
from typing import TYPE_CHECKING, Optional, cast

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

from .compat import run_cleanup_step
from .metrics import compute_bounding_sphere


def _configure_bake_render_engine(bake_scene: bpy.types.Scene, is_bg: bool) -> None:
    """Selects Cycles for accurate multi-layer transparency compositing, falling back to EEVEE only if unavailable."""
    render = bake_scene.render
    if not render:
        return
    render.film_transparent = True
    render.dither_intensity = 0.0
    render.use_persistent_data = True
    cycles = getattr(bake_scene, "cycles", None)
    eevee = getattr(bake_scene, "eevee", None)
    sample_count = 4 if is_bg else 8
    for eng in ("CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            render.engine = eng  # type: ignore[assignment]
            if render.engine != eng:
                continue
            if eng == "CYCLES" and cycles is not None:
                for attr, val in (
                    ("samples", sample_count),
                    ("use_adaptive_sampling", False),
                    ("use_denoising", False),
                    ("max_bounces", 0),
                    ("diffuse_bounces", 0),
                    ("glossy_bounces", 0),
                    ("transmission_bounces", 0),
                    ("volume_bounces", 0),
                    ("transparent_max_bounces", 16),
                    ("device", "CPU"),
                ):
                    setattr(cycles, attr, val)
            elif eevee is not None:
                eevee.taa_render_samples = 1
            return
        except (TypeError, ValueError, AttributeError) as eng_err:
            logger.debug("Render engine %s not available: %s", eng, eng_err)


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
        blend_data: BlendData,
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
            bdata_scenes = bdata.scenes if bdata else None
            self.orig_scene = (ctx.scene if ctx else None) or (
                bdata_scenes[0] if bdata_scenes and len(bdata_scenes) > 0 else None
            )

        bdata_scenes = bdata.scenes if bdata else None
        if not bdata_scenes:
            return None

        self.bake_scene = bdata_scenes.new(self.temp_scene_name)
        if not self.bake_scene:
            return None

        # Configure minimal, fast unlit Cycles rendering environment
        is_bg = bool(bpy.app.background) if bpy else False
        _configure_bake_render_engine(self.bake_scene, is_bg)

        # Black unlit world background
        bdata_worlds = bdata.worlds if bdata else None
        if bdata_worlds:
            world = bdata_worlds.new(f"{self.temp_scene_name}_World")
            world.use_nodes = True
            if world.node_tree and world.node_tree.nodes:
                bg = world.node_tree.nodes.get("Background")
                if bg and "Color" in bg.inputs:
                    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
            self.bake_scene.world = world

        win = ctx.window if ctx else None
        if win:
            win.scene = self.bake_scene
        return self.bake_scene

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: object) -> None:
        ctx = self.context
        bdata = self.blend_data
        if not bdata and not bpy:
            return

        bdata_objs = bdata.objects if bdata else None
        bdata_cams = bdata.cameras if bdata else None
        bdata_worlds = bdata.worlds if bdata else None
        bdata_scenes = bdata.scenes if bdata else None

        try:
            win = ctx.window if ctx else None
            if self.orig_scene and win:
                win.scene = self.orig_scene
            if self.bake_scene:
                if self.bake_scene.camera is not None:
                    cam_obj = self.bake_scene.camera
                    cam_data = cast("bpy.types.Camera", cam_obj.data) if cam_obj else None
                    if bdata_objs:
                        bdata_objs.remove(cam_obj, do_unlink=True)
                    if cam_data and bdata_cams:
                        bdata_cams.remove(cam_data, do_unlink=True)
                if self.bake_scene.world is not None:
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
        blend_data: BlendData,
    ) -> bpy.types.Object | None:
        if not scene:
            return None

        bdata = blend_data
        bdata_cams = bdata.cameras if bdata else None
        bdata_objs = bdata.objects if bdata else None

        if scene.camera is not None and scene.camera.data is not None:
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

        if not scene.camera:
            if not bdata_objs:
                return None
            cam_obj = bdata_objs.new("OMNIMESH_Bake_Cam_Obj", cam_data)
            coll = scene.collection
            if coll and coll.objects is not None:
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
        if dir_vec.length > 1e-6:
            rot_quat = dir_vec.to_track_quat("-Z", "Y")
            cam_obj.rotation_euler = rot_quat.to_euler()

        return cam_obj


def _restore_impostor_bake_state(
    *,
    muted_unbound_nodes: list[tuple[bpy.types.Node, bool]],
    nodes: bpy.types.Nodes | None,
    bake_slot: bpy.types.Node | None,
    orig_active_node: bpy.types.Node | None,
    temp_images: list[bpy.types.Image],
    bdata_imgs: bpy.types.BlendDataImages,
    orig_vis: list[tuple[bpy.types.Object, bool]],
    vl: bpy.types.ViewLayer | None,
    scene: bpy.types.Scene,
    orig_selected: list[bpy.types.Object],
    orig_active_obj: bpy.types.Object | None,
    restore_render_fn: Callable[[], object],
) -> None:
    """Restores scene, view-layer selection, material, and image state after impostor bake."""
    warnings: list[str] = []

    for n, orig_mute in muted_unbound_nodes:
        run_cleanup_step(warnings, "node_mute", lambda node=n, val=orig_mute: setattr(node, "mute", val))

    if nodes is not None:
        if bake_slot is not None:
            run_cleanup_step(warnings, "bake_slot", lambda: nodes.remove(bake_slot))
        run_cleanup_step(warnings, "active_node", lambda: setattr(nodes, "active", orig_active_node))

    for temp_img in temp_images:
        run_cleanup_step(warnings, "temp_image", lambda img=temp_img: bdata_imgs.remove(img, do_unlink=True))

    for o, vis in orig_vis:
        run_cleanup_step(warnings, "hide_viewport", lambda obj=o, val=vis: setattr(obj, "hide_viewport", val))

    if vl is not None:
        orig_sel_set = set(orig_selected)
        for o in scene.objects:
            run_cleanup_step(warnings, "select", lambda obj=o: obj.select_set(obj in orig_sel_set, view_layer=vl))
        if vl.objects is not None:
            run_cleanup_step(warnings, "active_obj", lambda: setattr(vl.objects, "active", orig_active_obj))

    run_cleanup_step(warnings, "render_state", restore_render_fn)
    if warnings:
        logger.warning("Impostor bake cleanup warnings (%d): %s", len(warnings), "; ".join(warnings))


__all__ = ["EphemeralBakeSceneGuard", "ImpostorCameraRig", "_restore_impostor_bake_state"]
