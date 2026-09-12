"""
OmniMesh Engine Project Importer Operators.
Provides directory-driven one-click ingestion of engine project packages (MSFS 2024 / 2020),
including glTF LOD hierarchies, spatial markers, lighting, and cameras with neutral multi-engine naming.
"""

from __future__ import annotations

import logging
import os
import re
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
    from ..core.gltf_assembly import GLTFAssemblyEngine, bind_manifest_to_omnimesh
    from ..core.msfs_cst_parser import MSFSCSTParser
    from ..core.msfs_project_scanner import MSFSProjectScanner
    from ..core.msfs_transforms import FEET_TO_METERS, msfs_pbh_to_blender_rotation, msfs_zoom_to_blender_focal_length
    from .utils import get_or_create_engine_import_collection
except (ImportError, ValueError):
    from core.engine_import_presets import (
        DEFAULT_ENGINE_IMPORT_PRESET_ID,
        EngineImportPresetManager,
        delete_engine_import_preset,
        duplicate_engine_import_preset,
        get_engine_import_preset,
    )
    from core.gltf_assembly import GLTFAssemblyEngine, bind_manifest_to_omnimesh
    from core.msfs_cst_parser import MSFSCSTParser
    from core.msfs_project_scanner import MSFSProjectScanner
    from core.msfs_transforms import FEET_TO_METERS, msfs_pbh_to_blender_rotation, msfs_zoom_to_blender_focal_length
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
        except Exception as exc:
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
        model_target = getattr(props, "engine_import_model_target", preset.get("model_target", "EXTERIOR_ONLY"))
        use_lod0_suffix = getattr(props, "engine_import_use_lod0_suffix", preset.get("use_lod0_suffix", True))
        auto_assign_screen = getattr(
            props, "engine_import_auto_assign_screen_pct", preset.get("auto_assign_screen_pct", True)
        )
        dedup_mats = getattr(props, "engine_import_deduplicate_materials", preset.get("deduplicate_materials", True))
        reuse_rig = getattr(props, "engine_import_reuse_master_rig", preset.get("reuse_master_rig", True))

        # 2. Ensure Root Package Collection
        get_or_create_engine_import_collection(context, asset_name, "ROOT", use_lod0_suffix)

        all_imported_objects: list[Any] = []
        lod_mesh_map: dict[int, list[Any]] = {}

        # 3. Import Geometry / LODs
        if do_geo and manifest.has_geometry:
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

                    new_objs = GLTFAssemblyEngine.import_gltf_into_collection(context, lod_info.gltf_path, tier_col)
                    all_imported_objects.extend(new_objs)
                    model_imported_objects.extend(new_objs)

                    # Identify meshes
                    meshes = [o for o in new_objs if o.type == "MESH"]
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

        # 4. Ingest Spatial Markers (flight_model.cfg)
        spatial_count = 0
        datum_empty: Optional[Any] = None
        if do_spatial and manifest.flight_model_cfg_path and os.path.isfile(manifest.flight_model_cfg_path):
            spatial_col = get_or_create_engine_import_collection(context, asset_name, "SPATIAL")
            if spatial_col:
                try:
                    cfg = MSFSCSTParser.parse_file(manifest.flight_model_cfg_path)
                    datum_coords = cfg.points[0].coords_blender_m if cfg.points else (0.0, 0.0, 0.0)

                    # Datum Empty
                    datum_empty = bpy.data.objects.get("Datum") or bpy.data.objects.get("MSFS_Datum")
                    if not datum_empty:
                        datum_empty = bpy.data.objects.new("Datum", None)
                        spatial_col.objects.link(datum_empty)
                    else:
                        datum_empty.name = "Datum"
                        if datum_empty.name not in spatial_col.objects:
                            spatial_col.objects.link(datum_empty)

                    datum_empty.location = datum_coords
                    datum_empty.empty_display_type = "PLAIN_AXES"
                    datum_empty.empty_display_size = 0.5
                    datum_empty["msfs_id"] = "WEIGHT_AND_BALANCE:reference_datum_position"
                    context.view_layer.update()

                    # Relative points
                    for point in cfg.points:
                        if point.point_type == "DATUM":
                            continue

                        display_type = "PLAIN_AXES"
                        display_size = 0.25
                        if point.point_type == "CONTACT_POINT":
                            if point.point_class == 1:
                                display_type = "CIRCLE"
                                display_size = 0.35
                                clean_tag = point.name_tag or "Wheel"
                                empty_name = f"Point_{point.key.split('.')[-1]}_{clean_tag}"
                            elif point.point_class == 2:
                                display_type = "PLAIN_AXES"
                                display_size = 0.2
                                empty_name = f"Scrape_{point.name_tag or point.key.split('.')[-1]}"
                            else:
                                display_type = "PLAIN_AXES"
                                empty_name = f"Point_{point.key.split('.')[-1]}_{point.name_tag or point.point_type}"
                        elif point.point_type == "FUEL_TANK":
                            display_type = "CUBE"
                            display_size = 0.4
                            empty_name = f"Fuel_{point.name_tag or point.key}"
                        elif point.point_type == "CG":
                            display_type = "SPHERE"
                            display_size = 0.25
                            empty_name = "CG"
                        else:
                            empty_name = f"{point.name_tag or point.key}"

                        existing = None
                        for obj in spatial_col.objects:
                            if obj.get("msfs_id") == point.point_id:
                                existing = obj
                                break

                        if existing:
                            e = existing
                            e.name = empty_name
                        else:
                            e = bpy.data.objects.new(empty_name, None)
                            spatial_col.objects.link(e)

                        if datum_empty and e != datum_empty and e.parent != datum_empty:
                            e.parent = datum_empty

                        rel_ft = point.coords_msfs_rel_ft
                        e.location = (
                            rel_ft[1] * FEET_TO_METERS,
                            rel_ft[0] * FEET_TO_METERS,
                            rel_ft[2] * FEET_TO_METERS,
                        )
                        e.empty_display_type = display_type
                        e.empty_display_size = display_size
                        e["msfs_id"] = point.point_id
                        e["msfs_key"] = point.key
                        e["msfs_type"] = point.point_type
                        e["msfs_name_tag"] = point.name_tag
                        e["msfs_class"] = point.point_class
                        spatial_count += 1

                    if props:
                        props.msfs_spatial_cfg_path = str(manifest.flight_model_cfg_path)
                except Exception as exc:
                    logger.warning("Error ingesting spatial config: %s", exc)

        # 5. Ingest Lights (systems.cfg / light.cfg)
        lights_count = 0
        if do_lights and manifest.systems_cfg_path and os.path.isfile(manifest.systems_cfg_path):
            lights_col = get_or_create_engine_import_collection(context, asset_name, "LIGHTS")
            has_interior = manifest.interior_model is not None or (
                bpy
                and hasattr(bpy.data, "collections")
                and (
                    f"{asset_name}_Interior" in bpy.data.collections
                    or bpy.data.collections.get(f"{asset_name}_Interior_LOD0") is not None
                )
            )
            inte_lights_col = (
                get_or_create_engine_import_collection(context, f"{asset_name}_Interior", "LIGHTS")
                if has_interior
                else None
            )
            if lights_col:
                try:
                    from .msfs_lighting_ops import OMNIMESH_OT_import_msfs_lights

                    cfg_lights = MSFSCSTParser.parse_file(manifest.systems_cfg_path)
                    datum = datum_empty or bpy.data.objects.get("Datum") or bpy.data.objects.get("MSFS_Datum")

                    # Instantiate helper
                    light_importer = OMNIMESH_OT_import_msfs_lights()
                    for light in cfg_lights.lights:
                        target_col = (
                            inte_lights_col if (inte_lights_col and light.light_type in (4, 10)) else lights_col
                        )
                        light_importer._ensure_light_object(
                            col=target_col,
                            light=light,
                            datum_empty=datum,
                            context=context,
                        )
                        lights_count += 1

                    if props:
                        props.msfs_systems_cfg_path = str(manifest.systems_cfg_path)
                except Exception as exc:
                    logger.warning("Error ingesting lights: %s", exc)

        # 6. Ingest Cameras (cameras.cfg)
        cameras_count = 0
        if do_cameras and manifest.cameras_cfg_path and os.path.isfile(manifest.cameras_cfg_path):
            try:
                cam_cfg = MSFSCSTParser.parse_cameras_file(manifest.cameras_cfg_path)
                datum = datum_empty or bpy.data.objects.get("Datum") or bpy.data.objects.get("MSFS_Datum")

                # Check if interior model is part of this asset / scene
                has_interior = (
                    manifest.interior_model is not None
                    or f"{asset_name}_Interior" in bpy.data.collections
                    or bpy.data.collections.get(f"{asset_name}_Interior_LOD0") is not None
                )

                ext_cam_col = get_or_create_engine_import_collection(context, asset_name, "CAMERAS")
                inte_cam_col = (
                    get_or_create_engine_import_collection(context, f"{asset_name}_Interior", "CAMERAS")
                    if has_interior
                    else None
                )
                target_eye_col = inte_cam_col or ext_cam_col

                # Eyepoint
                eye_empty = bpy.data.objects.get("Eyepoint") or bpy.data.objects.get("MSFS_Eyepoint")
                if not eye_empty:
                    eye_empty = bpy.data.objects.new("Eyepoint", None)
                    if target_eye_col:
                        target_eye_col.objects.link(eye_empty)
                else:
                    eye_empty.name = "Eyepoint"
                    if target_eye_col and eye_empty.name not in target_eye_col.objects:
                        target_eye_col.objects.link(eye_empty)

                if datum and eye_empty != datum:
                    eye_empty.parent = datum

                eye_ft = cam_cfg.eyepoint_ft
                eye_empty.location = (
                    eye_ft[1] * FEET_TO_METERS,
                    eye_ft[0] * FEET_TO_METERS,
                    eye_ft[2] * FEET_TO_METERS,
                )
                eye_empty.empty_display_type = "SINGLE_ARROW"
                eye_empty.empty_display_size = 0.3
                eye_empty["msfs_id"] = "VIEWS:eyepoint"
                eye_empty["msfs_type"] = "EYEPOINT"
                context.view_layer.update()

                # Cameras
                for cam in cam_cfg.cameras:
                    clean_title = re.sub(r"[^\w]", "_", cam.title or cam.category or f"Cam_{cam.index}").strip("_")
                    cam_name = f"Cam_{cam.index}_{clean_title}"
                    is_vc = cam.origin == "Virtual Cockpit"
                    target_cam_col = inte_cam_col if is_vc and inte_cam_col else ext_cam_col
                    if not target_cam_col:
                        continue

                    cam_obj = None
                    for obj in target_cam_col.objects:
                        if obj.get("msfs_camera_guid") == cam.guid or obj.get("msfs_camera_index") == cam.index:
                            cam_obj = obj
                            break

                    if not cam_obj:
                        camera_data = bpy.data.cameras.new(name=cam_name)
                        cam_obj = bpy.data.objects.new(cam_name, camera_data)
                        target_cam_col.objects.link(cam_obj)
                    else:
                        cam_obj.name = cam_name
                        camera_data = cam_obj.data

                    camera_data.lens = msfs_zoom_to_blender_focal_length(cam.initial_zoom)
                    camera_data.clip_start = 0.05
                    camera_data.clip_end = 1000.0

                    p_deg, b_deg, h_deg = cam.initial_pbh_deg
                    cam_obj.rotation_euler = msfs_pbh_to_blender_rotation(p_deg, b_deg, h_deg)

                    init_x, init_y, init_z = cam.initial_xyz_m
                    offset_m = (init_x, init_z, init_y)
                    if is_vc and eye_empty:
                        cam_obj.parent = eye_empty
                        cam_obj.location = offset_m
                    elif datum:
                        cam_obj.parent = datum
                        cam_obj.location = offset_m
                    else:
                        cam_obj.location = offset_m

                    cam_obj["msfs_camera_index"] = cam.index
                    cam_obj["msfs_camera_guid"] = cam.guid
                    cam_obj["msfs_camera_title"] = cam.title
                    cam_obj["msfs_camera_origin"] = cam.origin
                    cam_obj["msfs_camera_category"] = cam.category
                    cameras_count += 1

                if props:
                    props.msfs_cameras_cfg_path = str(manifest.cameras_cfg_path)
            except Exception as exc:
                logger.warning("Error ingesting cameras: %s", exc)

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
            bpy.utils.register_class(cls)
        except ValueError:
            pass


def unregister():
    if not bpy:
        return
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except ValueError:
            pass
