"""
Unreal Engine 5 (UE5) Exporter for Static & Skeletal LOD Meshes and UCX Collision Hulls.
"""

from __future__ import annotations

try:
    from ..core.exceptions import OmniMeshError
    from ..core.io_utils import atomic_write_text, sanitize_filename
except (ImportError, ValueError):
    from core.exceptions import OmniMeshError
    from core.io_utils import atomic_write_text, sanitize_filename

from dataclasses import dataclass
import logging
import os
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    import mathutils
    from .base import EngineExporterBase, scoped_export_visibility, scoped_object_mode_and_selection
    from .engine_export import AssetMeshResolver
else:
    try:
        import bpy
        import mathutils
    except ImportError:
        bpy = None
        mathutils = None
    BlendData = object

    from .base import EngineExporterBase, scoped_export_visibility, scoped_object_mode_and_selection
    from .engine_export import AssetMeshResolver


@dataclass(frozen=True)
class _ReusedEmptyState:
    empty_obj: bpy.types.Object
    hide_viewport: bool
    had_fbx_type: bool
    orig_fbx_type: object
    matrix_world: mathutils.Matrix | None


class UE5Exporter(EngineExporterBase):
    @staticmethod
    def generate_import_script_py(asset_name: str, is_skeletal: bool = False) -> str:
        """Generates an Unreal Engine 5 Editor Python script to import FBX and packed PBR textures."""
        safe_name = sanitize_filename(asset_name, fallback="SM_Asset")
        return f"""# OmniMesh Unreal Engine 5 Import Helper
import os
import unreal

ASSET_NAME = {safe_name!r}
IS_SKELETAL = {is_skeletal!r}
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEST_PATH = f"/Game/OmniMesh/{{ASSET_NAME}}"


def import_omnimesh_asset():
    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    fbx_path = os.path.join(BASE_DIR, f"{{ASSET_NAME}}.fbx")

    options = unreal.FbxImportUI()
    options.set_editor_property("import_mesh", True)
    options.set_editor_property("import_as_skeletal", IS_SKELETAL)
    options.set_editor_property(
        "mesh_type_to_import",
        unreal.FBXImportType.FBXIT_SKELETAL_MESH if IS_SKELETAL else unreal.FBXImportType.FBXIT_STATIC_MESH,
    )
    options.set_editor_property("import_materials", True)
    options.set_editor_property("import_textures", True)
    if not IS_SKELETAL:
        sm_data = options.get_editor_property("static_mesh_import_data")
        sm_data.set_editor_property("import_mesh_lo_ds", True)
        sm_data.set_editor_property("auto_generate_collision", False)
        sm_data.set_editor_property("combine_meshes", False)

    fbx_task = unreal.AssetImportTask()
    fbx_task.filename = fbx_path
    fbx_task.destination_path = DEST_PATH
    fbx_task.destination_name = ASSET_NAME
    fbx_task.replace_existing = True
    fbx_task.automated = True
    fbx_task.save = True
    fbx_task.options = options

    tasks = [fbx_task]
    tex_dir = os.path.join(BASE_DIR, "Textures")
    if os.path.isdir(tex_dir):
        for fname in sorted(os.listdir(tex_dir)):
            if fname.lower().endswith((".png", ".tga", ".exr")):
                t_task = unreal.AssetImportTask()
                t_task.filename = os.path.join(tex_dir, fname)
                t_task.destination_path = f"{{DEST_PATH}}/Textures"
                t_task.replace_existing = True
                t_task.automated = True
                t_task.save = True
                tasks.append(t_task)

    asset_tools.import_asset_tasks(tasks)

    # Apply linear compression settings on ORM and preserve Depth alpha on Impostor normals
    for task in tasks[1:]:
        for obj_path in task.imported_object_paths:
            tex = unreal.EditorAssetLibrary.load_asset(obj_path)
            if not isinstance(tex, unreal.Texture2D):
                continue
            low = obj_path.lower()
            if "_orm" in low or "_comp" in low:
                tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
                tex.set_editor_property("srgb", False)
            elif "_impostor_normal" in low:
                tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_DEFAULT)
                tex.set_editor_property("srgb", False)
            elif "_normal" in low or "_norm" in low:
                tex.set_editor_property("compression_settings", unreal.TextureCompressionSettings.TC_NORMALMAP)
                tex.set_editor_property("srgb", False)
            unreal.EditorAssetLibrary.save_loaded_asset(tex)


if __name__ == "__main__":
    import_omnimesh_asset()
"""

    @classmethod
    def _write_ue5_import_script(
        cls,
        export_dir: str,
        clean_name: str,
        is_skeletal: bool,
        warnings: list[str],
    ) -> None:
        """Writes {clean_name}_ue5_import.py alongside the exported FBX."""
        script_path = os.path.join(export_dir, f"{clean_name}_ue5_import.py")
        try:
            atomic_write_text(
                script_path,
                cls.generate_import_script_py(clean_name, is_skeletal=is_skeletal),
                encoding="utf-8",
                prefix="omnimesh_ue5_",
            )
        except OSError as exc:
            warnings.append(f"ue5_import_script: {exc}")
            logger.warning("Could not write UE5 import script '%s': %s", script_path, exc)

    @classmethod
    def _acquire_lod_group_empty(
        cls,
        context: bpy.types.Context,
        bdata: BlendData | None,
        clean_name: str,
        prep_warnings: list[str],
    ) -> tuple[bpy.types.Object | None, bpy.types.Object | None, _ReusedEmptyState | None]:
        """Retrieves or creates ``LODGroup_<name>`` empty, capturing rollback state if pre-existing."""
        empty_name = f"LODGroup_{clean_name}"
        scene_col = context.scene.collection if context.scene else None
        bdata_objs = bdata.objects if bdata else None
        lod_group_empty = bdata_objs.get(empty_name) if bdata_objs else None
        created_empty = None
        reused_state: _ReusedEmptyState | None = None

        if not lod_group_empty and bdata_objs and scene_col is not None:
            lod_group_empty = bdata_objs.new(empty_name, None)
            lod_group_empty.empty_display_type = "PLAIN_AXES"
            scene_col.objects.link(lod_group_empty)
            created_empty = lod_group_empty
        elif lod_group_empty is not None:
            reused_state = _ReusedEmptyState(
                empty_obj=lod_group_empty,
                hide_viewport=lod_group_empty.hide_viewport,
                had_fbx_type="fbx_type" in lod_group_empty,
                orig_fbx_type=lod_group_empty.get("fbx_type"),
                matrix_world=lod_group_empty.matrix_world.copy() if lod_group_empty.matrix_world is not None else None,
            )
            if scene_col is not None and lod_group_empty.name not in scene_col.objects:
                try:
                    scene_col.objects.link(lod_group_empty)
                except RuntimeError as exc:
                    prep_warnings.append(f"link empty: {exc}")
                    logger.debug("LODGroup empty already linked: %s", exc)

        return lod_group_empty, created_empty, reused_state

    @classmethod
    def export_asset(
        cls,
        context: bpy.types.Context | None,
        export_dir: str,
        asset_name: str,
        **kwargs: object,
    ) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        clean_name = sanitize_filename(asset_name, fallback="SM_Asset")

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        bdata_in = kwargs.get("blend_data")
        bdata: BlendData | None = (
            bdata_in if (bdata_in is not None and isinstance(bdata_in, BlendData)) else context.blend_data
        )
        bdata_objs = bdata.objects if bdata else None
        payload = (
            AssetMeshResolver.resolve_payload(context, clean_name, blend_data=bdata) if AssetMeshResolver else None
        )
        if not payload or not payload.lod_tiers:
            return False, f"No generated LOD objects found for '{asset_name}'"

        prep_warnings: list[str] = []
        cleanup_warnings: list[str] = []
        export_objects: list[bpy.types.Object] = []
        for tier_idx in sorted(payload.lod_tiers.keys()):
            for obj in payload.lod_tiers[tier_idx]:
                if obj not in export_objects:
                    export_objects.append(obj)

        if not export_objects:
            return False, f"No generated LOD objects found for '{asset_name}'"

        collider_objects = list(payload.collider_objects)
        armature_obj = payload.armature_obj
        all_export_items = export_objects + collider_objects + ([armature_obj] if armature_obj else [])

        orig_collider_names: dict[bpy.types.Object, str] = {}
        orig_imp_names: dict[bpy.types.Object, str] = {}
        orig_parents: dict[bpy.types.Object, bpy.types.Object | None] = {obj: obj.parent for obj in export_objects}
        orig_collider_parents: dict[bpy.types.Object, bpy.types.Object | None] = {c: c.parent for c in collider_objects}
        is_chunked_asset = any(len(objs) > 1 for objs in payload.lod_tiers.values())
        orig_matrices: dict[bpy.types.Object, mathutils.Matrix] = (
            {obj: obj.matrix_world.copy() for obj in export_objects + collider_objects if obj.matrix_world is not None}
            if (not armature_obj and not is_chunked_asset)
            else {}
        )
        created_empty = None
        lod_group_empty = None
        reused_empty_state: _ReusedEmptyState | None = None
        vl = context.view_layer

        try:
            with scoped_object_mode_and_selection(
                context,
                prep_warnings,
                mode_set_fn=bpy.ops.object.mode_set if (bpy and context.mode != "OBJECT") else None,
                select_all_fn=bpy.ops.object.select_all if bpy else None,
            ):
                try:
                    with scoped_export_visibility(context, all_export_items, warnings=prep_warnings):
                        if payload.has_impostor_tier:
                            imp_tier_idx = max(payload.lod_tiers.keys())
                            for obj in payload.lod_tiers[imp_tier_idx]:
                                orig_imp_names[obj] = obj.name
                                obj.name = f"{clean_name}_LOD{imp_tier_idx}"

                        for idx, c_obj in enumerate(collider_objects, start=1):
                            orig_collider_names[c_obj] = c_obj.name
                            c_obj.name = f"UCX_{clean_name}_{idx:02d}"

                        bpy.ops.object.select_all(action="DESELECT")

                        if armature_obj:
                            armature_obj.select_set(True)
                            for obj in export_objects + collider_objects:
                                obj.select_set(True)
                            if vl and vl.objects is not None:
                                vl.objects.active = armature_obj
                        elif is_chunked_asset:
                            for obj in export_objects + collider_objects:
                                obj.select_set(True)
                            if vl and vl.objects is not None:
                                vl.objects.active = export_objects[0]
                        else:
                            lod_group_empty, created_empty, reused_empty_state = cls._acquire_lod_group_empty(
                                context, bdata, clean_name, prep_warnings
                            )
                            if lod_group_empty is None:
                                return False, f"Could not create or retrieve LODGroup empty for '{clean_name}'."

                            try:
                                if vl is not None:
                                    lod_group_empty.hide_set(False, view_layer=vl)
                                lod_group_empty.hide_viewport = False
                            except (RuntimeError, AttributeError) as exc:
                                prep_warnings.append(f"unhide empty: {exc}")
                                logger.debug("Could not unhide lod_group_empty: %s", exc)

                            lod_group_empty["fbx_type"] = "LodGroup"
                            if mathutils:
                                lod_group_empty.matrix_world = mathutils.Matrix.Identity(4)

                            for obj in export_objects:
                                if obj.parent != lod_group_empty:
                                    obj.parent = lod_group_empty
                                    if obj in orig_matrices:
                                        obj.matrix_world = orig_matrices[obj]

                            for c_obj in collider_objects:
                                if c_obj.parent == lod_group_empty or c_obj.parent is not None:
                                    c_obj.parent = None
                                    if c_obj in orig_matrices:
                                        c_obj.matrix_world = orig_matrices[c_obj]

                            lod_group_empty.select_set(True)
                            for obj in export_objects + collider_objects:
                                obj.select_set(True)
                            if vl and vl.objects is not None:
                                vl.objects.active = lod_group_empty

                        fbx_path = os.path.join(export_dir, f"{clean_name}.fbx")
                        bpy.ops.export_scene.fbx(
                            filepath=fbx_path,
                            use_selection=True,
                            apply_unit_scale=True,
                            apply_scale_options="FBX_SCALE_ALL",
                            bake_space_transform=False if (armature_obj or lod_group_empty) else True,
                            object_types={"ARMATURE", "MESH", "EMPTY"} if armature_obj else {"MESH", "EMPTY"},
                            mesh_smooth_type="FACE",
                            add_leaf_bones=False if armature_obj else True,
                            primary_bone_axis="Y",
                            secondary_bone_axis="X",
                            armature_nodetype="NULL",
                        )
                        cls._write_ue5_import_script(
                            export_dir, clean_name, is_skeletal=bool(armature_obj), warnings=cleanup_warnings
                        )
                        return True, f"UE5 FBX package exported to: {fbx_path}"
                except (
                    OmniMeshError,
                    RuntimeError,
                    ValueError,
                    TypeError,
                    AttributeError,
                    LookupError,
                    OSError,
                    ReferenceError,
                    ZeroDivisionError,
                ) as e:
                    return False, f"Failed to export UE5 FBX: {str(e)}"
                finally:
                    for obj, orig_parent in orig_parents.items():
                        try:
                            obj.parent = orig_parent
                            if obj in orig_matrices:
                                obj.matrix_world = orig_matrices[obj]
                        except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                            cleanup_warnings.append(f"parent restore: {exc}")
                            logger.debug("Restoring object parent failed: %s", exc)
                    for c_obj, orig_parent in orig_collider_parents.items():
                        try:
                            c_obj.parent = orig_parent
                            if c_obj in orig_matrices:
                                c_obj.matrix_world = orig_matrices[c_obj]
                        except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                            cleanup_warnings.append(f"collider parent restore: {exc}")
                            logger.debug("Restoring collider parent failed: %s", exc)

                    if created_empty and bdata_objs and created_empty.name in bdata_objs:
                        try:
                            bdata_objs.remove(created_empty, do_unlink=True)
                        except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                            cleanup_warnings.append(f"remove empty: {exc}")
                            logger.debug("Removing temporary LODGroup empty failed: %s", exc)
                    elif reused_empty_state is not None:
                        r_empty = reused_empty_state.empty_obj
                        try:
                            r_empty.hide_viewport = reused_empty_state.hide_viewport
                            if reused_empty_state.had_fbx_type:
                                r_empty["fbx_type"] = reused_empty_state.orig_fbx_type
                            elif "fbx_type" in r_empty:
                                del r_empty["fbx_type"]
                            if reused_empty_state.matrix_world is not None:
                                r_empty.matrix_world = reused_empty_state.matrix_world
                        except (RuntimeError, AttributeError, ReferenceError, TypeError, KeyError) as exc:
                            cleanup_warnings.append(f"restore reused empty: {exc}")

                    for c_obj, orig_name in orig_collider_names.items():
                        try:
                            c_obj.name = orig_name
                        except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                            cleanup_warnings.append(f"collider name restore: {exc}")
                            logger.debug("Restoring collider name failed: %s", exc)

                    for imp_obj, orig_name in orig_imp_names.items():
                        try:
                            imp_obj.name = orig_name
                        except (RuntimeError, AttributeError, ReferenceError, TypeError) as exc:
                            cleanup_warnings.append(f"impostor name restore: {exc}")
                            logger.debug("Restoring impostor name failed: %s", exc)
        finally:
            if prep_warnings:
                cleanup_warnings.extend(prep_warnings)
            if cleanup_warnings:
                logger.warning(
                    "UE5 export cleanup finished with %d warning(s): %s",
                    len(cleanup_warnings),
                    "; ".join(cleanup_warnings),
                )
