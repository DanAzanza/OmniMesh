"""
OmniMesh Scene Setup & Asset Initialization Operators.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- OMNIMESH_OT_initialize_asset: 1-Click interactive setup creating standard collections and routing meshes/armatures.
- OMNIMESH_OT_quick_scene_setup: 1-Click game engine scene and viewport configuration without modifying collections.
- OMNIMESH_OT_toggle_viewport_overlay: Fast viewport inspection toggles (Face Normals, Cavity, Stats).
- Resilient C-RNA enum cache handling and headless CI compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import bpy
    from bpy.props import BoolProperty, EnumProperty, StringProperty
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

    def StringProperty(**kwargs: Any) -> Any:
        return ""

    def BoolProperty(**kwargs: Any) -> Any:
        return True

    def EnumProperty(**kwargs: Any) -> Any:
        return ""


try:
    from ..core.scene_setup import (
        assign_objects_to_asset_hierarchy,
        configure_game_scene_settings,
        sanitize_asset_name,
        setup_asset_collections,
    )
    from .properties import project_preset_tiers
except (ImportError, ValueError):
    from core.scene_setup import (
        assign_objects_to_asset_hierarchy,
        configure_game_scene_settings,
        sanitize_asset_name,
        setup_asset_collections,
    )

    try:
        from ui.properties import project_preset_tiers
    except (ImportError, ValueError):
        project_preset_tiers = None

logger = logging.getLogger(__name__)


class OMNIMESH_OT_initialize_asset(Operator):
    """Initializes a game-ready asset hierarchy from selected objects and configures scene settings."""

    bl_idname = "omnimesh.initialize_asset"
    bl_label = "Initialize Asset from Selection"
    bl_description = (
        "Creates a standardized OmniMesh collection hierarchy ({AssetName} -> _LOD0, _Colliders, _Helpers), "
        "routes selected meshes to LOD0, and configures game engine scene units and viewport settings"
    )
    bl_options = {"REGISTER", "UNDO"}

    asset_name: StringProperty(
        name="Asset Name",
        description="Canonical name of the root asset collection",
        default="",
    )

    configure_scene: BoolProperty(
        name="Configure Game Scene Settings",
        description="Apply Metric 1.0, 60 FPS, optimized clipping (0.05m - 1000m), stats, and cavity shading",
        default=True,
    )

    apply_color_tags: BoolProperty(
        name="Apply Outliner Color Tags",
        description="Assign Blender 4.x/5.x native Outliner color tags to collections (LOD0: Green, Colliders: Orange, Helpers: Yellow)",
        default=True,
    )

    move_selected: BoolProperty(
        name="Move Selected Objects",
        description="Route selected meshes to _LOD0, armatures to root, and empties to helpers",
        default=True,
    )

    create_colliders: BoolProperty(
        name="Create Colliders Collection",
        description="Include {AssetName}_Colliders sub-collection",
        default=True,
    )

    create_helpers: BoolProperty(
        name="Create Helpers Collection",
        description="Include {AssetName}_Helpers sub-collection for pivots and empties",
        default=True,
    )

    create_config: BoolProperty(
        name="Create Config Collection",
        description="Include {AssetName}_Config sub-collection for engine markers, cameras, and lights",
        default=False,
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        # Determine best default asset name from active or selected objects
        default_name = ""
        active_obj = getattr(context, "active_object", None)
        if active_obj and getattr(active_obj, "name", ""):
            default_name = sanitize_asset_name(active_obj.name)

        if not default_name or default_name == "Asset":
            sel_objs = getattr(context, "selected_objects", []) or []
            mesh_objs = [o for o in sel_objs if getattr(o, "type", "") == "MESH"]
            if mesh_objs:
                default_name = sanitize_asset_name(mesh_objs[0].name)

        self.asset_name = default_name or "NewAsset"
        return context.window_manager.invoke_props_dialog(self, width=380)

    def draw(self, context: Any) -> None:
        if not bpy or not context:
            return
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "asset_name", text="Asset Name")

        clean_name = sanitize_asset_name(self.asset_name)
        existing_col = bpy.data.collections.get(clean_name) if hasattr(bpy.data, "collections") else None
        if existing_col:
            box_warn = layout.box()
            box_warn.use_property_split = False
            row_w = box_warn.row(align=True)
            row_w.label(text=f"'{clean_name}' exists: selection will be merged into LOD0", icon="INFO")

        layout.separator()
        box_opts = layout.box()
        box_opts.label(text="Initialization Options", icon="PREFERENCES")
        box_opts.prop(self, "configure_scene", text="Game Scene Settings")
        box_opts.prop(self, "move_selected", text="Move Selected Objects")
        box_opts.prop(self, "apply_color_tags", text="Outliner Color Tags")

        layout.separator()
        box_colls = layout.box()
        box_colls.label(text="Sub-Collections", icon="OUTLINER_COLLECTION")
        box_colls.prop(self, "create_colliders", text="Colliders (_Colliders)")
        box_colls.prop(self, "create_helpers", text="Helpers (_Helpers)")
        box_colls.prop(self, "create_config", text="Engine Config (_Config)")

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        clean_name = sanitize_asset_name(self.asset_name)
        if not clean_name:
            self.report({"ERROR"}, "Asset name cannot be empty or invalid.")
            return {"CANCELLED"}

        # 1. Game Scene Configuration
        if self.configure_scene and hasattr(context, "scene"):
            configure_game_scene_settings(context.scene, context=context)

        # 2. Setup Standard Collections
        colls = setup_asset_collections(
            context,
            clean_name,
            create_lod0=True,
            create_colliders=self.create_colliders,
            create_helpers=self.create_helpers,
            create_config=self.create_config,
            apply_color_tags=self.apply_color_tags,
        )

        if not colls or "root" not in colls:
            self.report({"ERROR"}, f"Could not create collection hierarchy for '{clean_name}'.")
            return {"CANCELLED"}

        # 3. Object Classification & Routing
        mesh_count = 0
        if self.move_selected:
            selected_objs = list(getattr(context, "selected_objects", []))
            summary = assign_objects_to_asset_hierarchy(
                selected_objs,
                colls,
                scene=getattr(context, "scene", None),
            )
            mesh_count = len(summary.get("moved_to_lod0", []))

            if summary.get("skipped_library"):
                self.report(
                    {"WARNING"},
                    f"Skipped {len(summary['skipped_library'])} library-linked datablocks.",
                )

        # 4. Set Active Layer Collection in ViewLayer to LOD0 for ergonomic Outliner focus
        vl = getattr(context, "view_layer", None)
        lod0_col = colls.get("lod0")
        if vl and lod0_col and hasattr(vl, "layer_collection"):

            def _find_layer_collection(layer_col: Any, target: Any) -> Any | None:
                if getattr(layer_col, "collection", None) == target:
                    return layer_col
                for child in getattr(layer_col, "children", []):
                    found = _find_layer_collection(child, target)
                    if found:
                        return found
                return None

            active_lc = _find_layer_collection(vl.layer_collection, lod0_col)
            if active_lc:
                try:
                    vl.active_layer_collection = active_lc
                except Exception as exc:
                    logger.debug("Could not set active_layer_collection: %s", exc)

        # 5. Invalidate dynamic C-RNA enum cache and register active asset
        try:
            from . import utils as ui_utils

            ui_utils._CACHED_ASSET_ITEMS = None
        except (ImportError, AttributeError) as exc:
            logger.debug("Could not invalidate _CACHED_ASSET_ITEMS: %s", exc)

        props = getattr(getattr(context, "scene", None), "lod_tool", None)
        if props:
            try:
                props.export_base_name = clean_name
            except Exception as exc:
                logger.debug("Could not set export_base_name: %s", exc)

            try:
                props.active_asset = clean_name
            except Exception as exc:
                logger.debug("Immediate active_asset enum set deferred: %s", exc)

                def _deferred_set_active_asset() -> None:
                    try:
                        props.active_asset = clean_name
                    except Exception as defer_exc:
                        logger.debug("Deferred active_asset set failed: %s", defer_exc)
                    return None

                if hasattr(bpy.app, "timers"):
                    bpy.app.timers.register(_deferred_set_active_asset, first_interval=0.01)

            if project_preset_tiers:
                try:
                    project_preset_tiers(props, context, asset_name=clean_name)
                except Exception as exc:
                    logger.debug("Could not project preset tiers: %s", exc)

        if hasattr(context, "view_layer") and hasattr(context.view_layer, "update"):
            try:
                context.view_layer.update()
            except Exception as exc:
                logger.debug("Could not update view layer: %s", exc)

        self.report(
            {"INFO"},
            f"Asset '{clean_name}' initialized ({mesh_count} meshes in LOD0).",
        )
        return {"FINISHED"}


class OMNIMESH_OT_quick_scene_setup(Operator):
    """Applies game engine standards to the active scene and 3D viewports without altering collections."""

    bl_idname = "omnimesh.quick_scene_setup"
    bl_label = "Quick Game Scene Setup"
    bl_description = (
        "Configures Metric 1.0 units, 60 FPS, optimized camera clipping (0.05m - 1000m), "
        "statistics overlay, cavity shading, and backface culling"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        scene = getattr(context, "scene", None)
        if not scene:
            self.report({"ERROR"}, "No active scene.")
            return {"CANCELLED"}

        res = configure_game_scene_settings(scene, context=context)
        viewports_count = res.get("viewports_updated", 0)

        self.report(
            {"INFO"},
            f"Scene configured: Metric 1.0, 60 FPS, {viewports_count} viewport(s) updated.",
        )
        return {"FINISHED"}


class OMNIMESH_OT_toggle_viewport_overlay(Operator):
    """Toggles specific viewport overlays and shading modes across active 3D viewports."""

    bl_idname = "omnimesh.toggle_viewport_overlay"
    bl_label = "Toggle Viewport Overlay"
    bl_description = "Quick toggle for Face Orientation, Cavity Shading, or Scene Statistics"
    bl_options = {"REGISTER"}

    mode: EnumProperty(
        name="Mode",
        items=[
            ("FACE_ORIENTATION", "Face Orientation", "Toggle inverted normal detection (red/blue)"),
            ("CAVITY", "Cavity Shading", "Toggle silhouette and ridge cavity shading"),
            ("STATS", "Statistics", "Toggle viewport vertex/triangle count HUD"),
            ("BACKFACE", "Backface Culling", "Toggle game-engine backface culling"),
        ],
        default="STATS",
    )

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        wm = getattr(context, "window_manager", None)
        if not wm or not hasattr(wm, "windows"):
            return {"CANCELLED"}

        toggled_state: bool = False
        state_determined: bool = False

        for window in getattr(wm, "windows", []):
            screen = getattr(window, "screen", None)
            if not screen or not hasattr(screen, "areas"):
                continue
            for area in getattr(screen, "areas", []):
                if getattr(area, "type", "") == "VIEW_3D":
                    for space in getattr(area, "spaces", []):
                        if getattr(space, "type", "") == "VIEW_3D":
                            overlay = getattr(space, "overlay", None)
                            shading = getattr(space, "shading", None)

                            if self.mode == "FACE_ORIENTATION" and overlay:
                                if not state_determined:
                                    toggled_state = not getattr(overlay, "show_face_orientation", False)
                                    state_determined = True
                                overlay.show_face_orientation = toggled_state

                            elif self.mode == "STATS" and overlay:
                                if not state_determined:
                                    toggled_state = not getattr(overlay, "show_stats", False)
                                    state_determined = True
                                overlay.show_stats = toggled_state

                            elif self.mode == "CAVITY" and shading:
                                if not state_determined:
                                    toggled_state = not getattr(shading, "show_cavity", False)
                                    state_determined = True
                                shading.show_cavity = toggled_state
                                if toggled_state and hasattr(shading, "cavity_type"):
                                    shading.cavity_type = "BOTH"

                            elif self.mode == "BACKFACE" and shading:
                                if not state_determined:
                                    toggled_state = not getattr(shading, "show_backface_culling", False)
                                    state_determined = True
                                shading.show_backface_culling = toggled_state

        status_text = "enabled" if toggled_state else "disabled"
        self.report({"INFO"}, f"{self.mode.title()}: {status_text}.")
        return {"FINISHED"}


OPERATOR_CLASSES = (
    OMNIMESH_OT_initialize_asset,
    OMNIMESH_OT_quick_scene_setup,
    OMNIMESH_OT_toggle_viewport_overlay,
)


def register() -> None:
    if not bpy:
        return
    for cls in OPERATOR_CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.warning("Could not register %s: %s", cls.__name__, exc)


def unregister() -> None:
    if not bpy:
        return
    for cls in reversed(OPERATOR_CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Could not unregister %s: %s", cls.__name__, exc)
