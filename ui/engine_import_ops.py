"""
OmniMesh Engine Project Importer Operators.
Provides directory-driven one-click ingestion of engine project packages (MSFS 2024 / 2020),
including glTF LOD hierarchies, spatial markers, lighting, and cameras with neutral multi-engine naming.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

try:
    import bpy
    from bpy.props import BoolProperty, StringProperty
    from bpy.types import Operator
except ImportError:
    bpy = None
    Operator = object

    def StringProperty(**kwargs: Any) -> Any:
        return ""

    def BoolProperty(**kwargs: Any) -> Any:
        return True


try:
    from ..core.engine_import_presets import (
        DEFAULT_ENGINE_IMPORT_PRESET_ID,
        EngineImportPresetManager,
        delete_engine_import_preset,
        duplicate_engine_import_preset,
        get_engine_import_preset,
    )
    from ..core.gltf_assembly import (
        GLTFAssemblyEngine,
        bind_manifest_to_omnimesh,
        classify_imported_mesh_node,
    )
    from ..core.msfs.project_scanner import MSFSProjectScanner
    from .engine_import_helpers import (
        import_attachments,
        import_cameras,
        import_lighting_points,
        import_spatial_points,
    )
    from .utils import get_or_create_engine_import_collection
except (ImportError, ValueError):
    from core.engine_import_presets import (
        DEFAULT_ENGINE_IMPORT_PRESET_ID,
        EngineImportPresetManager,
        delete_engine_import_preset,
        duplicate_engine_import_preset,
        get_engine_import_preset,
    )
    from core.gltf_assembly import (
        GLTFAssemblyEngine,
        bind_manifest_to_omnimesh,
        classify_imported_mesh_node,
    )
    from core.msfs.project_scanner import MSFSProjectScanner
    from ui.engine_import_helpers import (
        import_attachments,
        import_cameras,
        import_lighting_points,
        import_spatial_points,
    )
    from ui.utils import get_or_create_engine_import_collection

logger = logging.getLogger(__name__)


class OMNIMESH_OT_import_engine_project(Operator):
    """Selects an engine/aircraft project folder to ingest LOD meshes, spatial markers, lighting, and cameras."""

    bl_idname = "omnimesh.import_engine_project"
    bl_label = "Import Engine Project"
    bl_description = (
        "Select an aircraft/engine project folder to ingest geometry LODs, spatial markers, lights, and cameras"
    )
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(
        name="Project Folder",
        description="Path to engine project package or aircraft root folder",
        subtype="DIR_PATH",
        default="",
    )

    filter_folder: BoolProperty(
        default=True,
        options={"HIDDEN"},
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        if props and props.engine_import_directory and os.path.isdir(props.engine_import_directory):
            self.directory = props.engine_import_directory
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def _import_geometry_models(
        self,
        context: Any,
        manifest: Any,
        asset_name: str,
        props: Any,
        preset: dict[str, Any],
    ) -> tuple[list[Any], dict[int, list[Any]]]:
        """Ingests exterior, interior, and variant glTF LODs and binds to scene tiers."""
        all_imported_objects: list[Any] = []
        lod_mesh_map: dict[int, list[Any]] = {}

        model_target = getattr(props, "engine_import_model_target", preset.get("model_target", "EXTERIOR_ONLY"))
        use_lod0_suffix = getattr(props, "engine_import_use_lod0_suffix", preset.get("use_lod0_suffix", True))
        auto_assign_screen = getattr(
            props, "engine_import_auto_assign_screen_pct", preset.get("auto_assign_screen_pct", True)
        )
        dedup_mats = getattr(props, "engine_import_deduplicate_materials", preset.get("deduplicate_materials", True))
        reuse_rig = getattr(props, "engine_import_reuse_master_rig", preset.get("reuse_master_rig", True))

        target_models = []
        if model_target in ("EXTERIOR_ONLY", "BOTH_SEPARATE"):
            ext = manifest.exterior_model
            if ext and ext.lods:
                target_models.append(("exterior", ext))
        if model_target in ("INTERIOR_ONLY", "BOTH_SEPARATE"):
            inte = manifest.interior_model
            if inte and inte.lods:
                target_models.append(("interior", inte))
        # Include geometry variants (e.g. Floats, Skis, Cargo)
        if model_target in ("EXTERIOR_ONLY", "BOTH_SEPARATE") and manifest.variants:
            for var_name, var_info in manifest.variants.items():
                if var_info.lods:
                    target_models.append((var_name, var_info))

        # Fallback if no target matched but models exist
        if not target_models and manifest.models:
            first_model = next(iter(manifest.models.values()))
            target_models.append(("exterior", first_model))

        primary_model_name = target_models[0][0] if target_models else "exterior"
        for model_name, model_info in target_models:
            tag_lower = model_name.lower()
            is_exterior = tag_lower in ("exterior", "normal", "base")
            if is_exterior:
                sub_asset = asset_name
            elif tag_lower in ("interior", "cockpit"):
                sub_asset = f"{asset_name}_Interior"
            else:
                sub_asset = f"{asset_name}_{model_name.capitalize()}"

            model_imported_objects: list[Any] = []
            model_master_armature: Optional[Any] = None

            for lod_info in model_info.lods:
                if not lod_info.exists:
                    logger.warning("LOD glTF does not exist: %s", lod_info.gltf_path)
                    continue

                lod_role = f"LOD{lod_info.index}"
                tier_col = get_or_create_engine_import_collection(context, sub_asset, lod_role, use_lod0_suffix)
                if not tier_col:
                    continue

                new_objs = GLTFAssemblyEngine.import_gltf_into_collection(
                    context, lod_info.gltf_path, tier_col, asset_name=sub_asset, is_interior=(not is_exterior)
                )
                all_imported_objects.extend(new_objs)
                model_imported_objects.extend(new_objs)

                # Identify meshes (strictly exclude colliders and interaction clickspots from visual tiers)
                meshes = [
                    o
                    for o in new_objs
                    if o.type == "MESH"
                    and classify_imported_mesh_node(o, is_interior=(not is_exterior)) == "RENDER_MESH"
                ]
                if is_exterior or model_name == primary_model_name:
                    lod_mesh_map[lod_info.index] = meshes

                # Capture LOD0 Armature as Master Rig for this specific model
                if lod_info.index == 0 and not model_master_armature:
                    model_master_armature = next((o for o in new_objs if o.type == "ARMATURE"), None)

            # Master Rig Retargeting scoped strictly to this model's objects
            if reuse_rig and model_master_armature and model_imported_objects:
                mods_retargeted = GLTFAssemblyEngine.retarget_armatures_to_master(
                    model_master_armature, model_imported_objects
                )
                logger.info("Retargeted %d armature modifiers to master rig for '%s'", mods_retargeted, sub_asset)

        # Deduplicate materials across LODs
        if dedup_mats and all_imported_objects:
            mats_remapped = GLTFAssemblyEngine.deduplicate_materials(all_imported_objects)
            logger.info("Deduplicated %d material slots across LODs", mats_remapped)

        # Bind to OmniMesh Scene LOD Tiers
        if auto_assign_screen:
            bind_manifest_to_omnimesh(context, manifest, lod_mesh_map)

        return all_imported_objects, lod_mesh_map

    def _import_spatial_points(
        self,
        context: Any,
        manifest: Any,
        asset_name: str,
        props: Any,
    ) -> tuple[int, Optional[Any]]:
        return import_spatial_points(context, manifest, asset_name, props)

    def _import_lighting_points(
        self,
        context: Any,
        manifest: Any,
        asset_name: str,
        datum_empty: Optional[Any],
        props: Any,
    ) -> int:
        return import_lighting_points(context, manifest, asset_name, datum_empty, props)

    def _import_cameras(
        self,
        context: Any,
        manifest: Any,
        asset_name: str,
        datum_empty: Optional[Any],
        props: Any,
    ) -> int:
        return import_cameras(context, manifest, asset_name, datum_empty, props)

    def _import_attachments(self, context: Any, manifest: Any) -> int:
        return import_attachments(context, manifest)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        folder = self.directory.strip()
        if not folder or not os.path.isdir(folder):
            self.report({"ERROR"}, "Please select a valid directory.")
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        if props:
            props.engine_import_directory = folder

        preset_id = getattr(props, "engine_import_preset", "") or DEFAULT_ENGINE_IMPORT_PRESET_ID
        preset = get_engine_import_preset(preset_id)

        # 1. Scan the project
        try:
            manifest = MSFSProjectScanner.scan(folder)
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.exception("Project scan failed: %s", exc)
            self.report({"ERROR"}, f"Failed scanning project directory: {exc}")
            return {"CANCELLED"}

        asset_name = manifest.asset_name or "Asset"
        if props:
            props.export_base_name = asset_name

        # Determine feature toggles (settings override preset)
        do_geo = getattr(props, "engine_import_geometry", preset.get("import_geometry", True))
        do_spatial = getattr(props, "engine_import_spatial", preset.get("import_spatial", True))
        do_lights = getattr(props, "engine_import_lights", preset.get("import_lights", True))
        do_cameras = getattr(props, "engine_import_cameras", preset.get("import_cameras", True))
        use_lod0_suffix = getattr(props, "engine_import_use_lod0_suffix", preset.get("use_lod0_suffix", True))

        # 2. Ensure Root Package and Helpers Collections
        get_or_create_engine_import_collection(context, asset_name, "ROOT", use_lod0_suffix)
        get_or_create_engine_import_collection(context, asset_name, "HELPERS")

        # 3. Import Geometry / LODs
        lod_mesh_map: dict[int, list[Any]] = {}
        if do_geo and manifest.has_geometry:
            _, lod_mesh_map = self._import_geometry_models(context, manifest, asset_name, props, preset)

        # 4. Ingest Spatial Markers (flight_model.cfg)
        spatial_count = 0
        datum_empty: Optional[Any] = None
        if do_spatial:
            spatial_count, datum_empty = self._import_spatial_points(context, manifest, asset_name, props)

        # 5. Ingest Lights (systems.cfg / light.cfg)
        lights_count = 0
        if do_lights:
            lights_count = self._import_lighting_points(context, manifest, asset_name, datum_empty, props)

        # 6. Ingest Cameras (cameras.cfg)
        cameras_count = 0
        if do_cameras:
            cameras_count = self._import_cameras(context, manifest, asset_name, datum_empty, props)

        # 7. Ingest Modular Attachments (attached_objects.cfg)
        attachments_count = 0
        if do_spatial:
            attachments_count = self._import_attachments(context, manifest)

        # Summary report
        summary_parts = []
        if lod_mesh_map:
            summary_parts.append(f"{len(lod_mesh_map)} LODs")
        if spatial_count:
            summary_parts.append(f"{spatial_count} markers")
        if lights_count:
            summary_parts.append(f"{lights_count} lights")
        if cameras_count:
            summary_parts.append(f"{cameras_count} cameras")
        if attachments_count:
            summary_parts.append(f"{attachments_count} attachments")

        summary_text = f"Imported {asset_name} ({', '.join(summary_parts) if summary_parts else 'Complete'})"
        if props:
            props.last_engine_import_summary = summary_text
            props.msfs_spatial_status = summary_text

        self.report({"INFO"}, summary_text)
        return {"FINISHED"}


class OMNIMESH_OT_duplicate_engine_import_preset(Operator):
    """Duplicates the currently active engine import preset into a custom user preset."""

    bl_idname = "omnimesh.duplicate_engine_import_preset"
    bl_label = "Duplicate Preset"
    bl_description = "Duplicate active engine import preset into a user-customizable copy"
    bl_options = {"REGISTER", "UNDO"}

    new_name: StringProperty(
        name="Preset Name",
        description="Name for the duplicated preset",
        default="",
    )

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        active_id = getattr(props, "engine_import_preset", "") or DEFAULT_ENGINE_IMPORT_PRESET_ID
        preset = get_engine_import_preset(active_id)
        self.new_name = f"{preset.get('name', active_id)} (Copy)"
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        active_id = getattr(props, "engine_import_preset", "") or DEFAULT_ENGINE_IMPORT_PRESET_ID
        try:
            new_id = duplicate_engine_import_preset(active_id, new_name=self.new_name)
            if props:
                props.engine_import_preset = new_id
            self.report({"INFO"}, f"Created custom preset '{self.new_name}'")
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Failed duplicating preset: {exc}")
            return {"CANCELLED"}


class OMNIMESH_OT_delete_engine_import_preset(Operator):
    """Deletes the selected custom engine import preset."""

    bl_idname = "omnimesh.delete_engine_import_preset"
    bl_label = "Delete Custom Preset"
    bl_description = "Permanently deletes the selected user engine import preset"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        props = getattr(context.scene, "lod_tool", None)
        active_id = getattr(props, "engine_import_preset", "")
        return not EngineImportPresetManager.is_builtin(active_id)

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}
        props = getattr(context.scene, "lod_tool", None)
        active_id = getattr(props, "engine_import_preset", "")
        if EngineImportPresetManager.is_builtin(active_id):
            self.report({"WARNING"}, "Cannot delete built-in factory preset.")
            return {"CANCELLED"}

        deleted = delete_engine_import_preset(active_id)
        if deleted:
            if props:
                props.engine_import_preset = DEFAULT_ENGINE_IMPORT_PRESET_ID
            self.report({"INFO"}, f"Deleted preset '{active_id}'")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, f"Failed deleting preset '{active_id}'")
            return {"CANCELLED"}


classes = (
    OMNIMESH_OT_import_engine_project,
    OMNIMESH_OT_duplicate_engine_import_preset,
    OMNIMESH_OT_delete_engine_import_preset,
)


def register():
    if not bpy:
        return
    for cls in classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
        try:
            bpy.utils.register_class(cls)
        except ValueError as exc:
            logger.debug("Register skipped %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister():
    if not bpy:
        return
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except ValueError as exc:
            logger.debug("Unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
