"""
OmniMesh glTF Ingestion & Assembly Engine.
Provides isolated multi-LOD glTF importation, collection redirection,
material deduplication, master armature retargeting, and OmniMesh LOD tier binding.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Collection, LayerCollection, Material, Object
except ImportError:
    bpy = None
    Collection = object
    LayerCollection = object
    Material = object
    Object = object

from .msfs_project_scanner import MSFSProjectManifest


def find_layer_collection(layer_coll: Any, target_coll: Any) -> Optional[Any]:
    """Recursively traverses the LayerCollection hierarchy to find the one matching target_coll."""
    if layer_coll.collection == target_coll:
        return layer_coll
    for child in layer_coll.children:
        found = find_layer_collection(child, target_coll)
        if found:
            return found
    return None


class GLTFAssemblyEngine:
    """Handles isolated importation of glTF LODs and post-import pipeline optimizations."""

    @classmethod
    def import_gltf_into_collection(
        cls,
        context: Any,
        gltf_path: Path | str,
        target_collection: Any,
    ) -> list[Any]:
        """Imports a glTF file into target_collection while strictly isolating created objects.

        Unlinks imported objects from any unwanted default collections and redirects them.
        """
        if not bpy or not context:
            return []

        path = Path(gltf_path).resolve()
        if not path.is_file():
            logger.warning("glTF file not found: %s", path)
            return []

        # Find target layer collection to set active
        vl = context.view_layer
        target_lc = find_layer_collection(vl.layer_collection, target_collection)
        prev_active_lc = vl.active_layer_collection
        if target_lc:
            vl.active_layer_collection = target_lc

        # Snapshot existing objects
        existing_objects = set(bpy.data.objects)
        existing_collections = set(bpy.data.collections)

        try:
            # Execute Blender's glTF importer
            bpy.ops.import_scene.gltf(filepath=str(path))
        except Exception as exc:
            logger.error("Failed importing glTF '%s': %s", path, exc)
            return []
        finally:
            if prev_active_lc:
                try:
                    vl.active_layer_collection = prev_active_lc
                except Exception as exc:
                    logger.debug("Failed restoring previous active layer collection: %s", exc)

        # Identify newly created objects
        new_objects = [obj for obj in bpy.data.objects if obj not in existing_objects]

        # Isolate new objects: ensure they are in target_collection and unlinked elsewhere
        for obj in new_objects:
            if obj.name not in target_collection.objects:
                target_collection.objects.link(obj)

            # Unlink from other collections (e.g. scene collection or importer dummy collections)
            for coll in list(obj.users_collection):
                if coll != target_collection:
                    try:
                        coll.objects.unlink(obj)
                    except Exception as exc:
                        logger.debug("Could not unlink %s from %s: %s", obj.name, coll.name, exc)

        # Cleanup dummy collections created by glTF importer if they are now empty
        new_collections = [c for c in bpy.data.collections if c not in existing_collections]
        for coll in new_collections:
            if coll != target_collection and len(coll.objects) == 0 and len(coll.children) == 0:
                try:
                    bpy.data.collections.remove(coll)
                except Exception as exc:
                    logger.debug("Failed removing empty collection %s: %s", coll.name, exc)

        return new_objects

    @classmethod
    def deduplicate_materials(cls, objects: list[Any]) -> int:
        """Detects duplicated material datablocks (e.g. Fuselage.001) across imported objects,

        remaps them to canonical base materials (Fuselage), and cleans up unreferenced duplicates.
        Returns the number of material slots remapped.
        """
        if not bpy:
            return 0

        remapped_count = 0
        materials_to_check: set[Material] = set()

        for obj in objects:
            if not hasattr(obj, "material_slots"):
                continue
            for slot in obj.material_slots:
                mat = slot.material
                if not mat:
                    continue

                # Check if name ends with .001, .002, etc.
                match = re.search(r"^(.*?)\.\d{3}$", mat.name)
                if match:
                    base_name = match.group(1)
                    if base_name in bpy.data.materials:
                        canonical_mat = bpy.data.materials[base_name]
                        if canonical_mat != mat:
                            slot.material = canonical_mat
                            materials_to_check.add(mat)
                            remapped_count += 1

        # Purge unreferenced duplicate materials
        for dup_mat in materials_to_check:
            if dup_mat.users == 0:
                try:
                    bpy.data.materials.remove(dup_mat, do_unlink=True)
                except Exception as exc:
                    logger.debug("Failed removing unreferenced duplicate material %s: %s", dup_mat.name, exc)

        return remapped_count

    @classmethod
    def retarget_armatures_to_master(
        cls,
        master_armature: Optional[Any],
        lod_objects: list[Any],
    ) -> int:
        """Retargets ARMATURE modifiers on LOD mesh objects to the Master Rig (LOD0 Armature)

        and purges redundant duplicate armature objects. Returns number of modifiers retargeted.
        """
        if not bpy or not master_armature:
            return 0

        retargeted_count = 0
        redundant_armatures: set[Any] = set()

        for obj in lod_objects:
            if obj.type == "ARMATURE" and obj != master_armature:
                redundant_armatures.add(obj)
                continue

            if obj.type == "MESH" and hasattr(obj, "modifiers"):
                for mod in obj.modifiers:
                    if mod.type == "ARMATURE" and mod.object and mod.object != master_armature:
                        redundant_armatures.add(mod.object)
                        mod.object = master_armature
                        retargeted_count += 1

        # Safely remove redundant armatures
        for arm_obj in redundant_armatures:
            if arm_obj != master_armature and arm_obj.users <= 1:
                try:
                    bpy.data.objects.remove(arm_obj, do_unlink=True)
                except Exception as exc:
                    logger.debug("Failed removing redundant armature %s: %s", arm_obj.name, exc)

        return retargeted_count


def count_mesh_triangles(mesh_obj: Any) -> int:
    """Calculates total triangle count for a mesh object."""
    if not mesh_obj or mesh_obj.type != "MESH" or not hasattr(mesh_obj, "data"):
        return 0
    try:
        mesh = mesh_obj.data
        if hasattr(mesh, "calc_loop_triangles"):
            mesh.calc_loop_triangles()
            return len(mesh.loop_triangles)
        return len(mesh.polygons)
    except Exception:
        return 0


def bind_manifest_to_omnimesh(
    context: Any,
    manifest: MSFSProjectManifest,
    lod_mesh_map: dict[int, list[Any]],
) -> None:
    """Binds imported LOD meshes and screen sizes to OmniMesh's scene LOD properties."""
    if not bpy or not context or not hasattr(context.scene, "lod_tool"):
        return

    props = context.scene.lod_tool
    props.export_base_name = manifest.asset_name
    props.is_configured = True

    # Retrieve LOD info from manifest
    model_info = manifest.exterior_model or next(iter(manifest.models.values()), None)
    lod_infos = model_info.lods if model_info else []

    props.lods.clear()
    total_tiers = max(len(lod_infos), len(lod_mesh_map))

    base_tris = 0
    if 0 in lod_mesh_map and lod_mesh_map[0]:
        base_tris = sum(count_mesh_triangles(m) for m in lod_mesh_map[0] if m.type == "MESH")
        props.base_triangles = base_tris

    for i in range(total_tiers):
        item = props.lods.add()
        item.name = f"LOD{i}"
        item.lod_index = i
        item.level_index = i

        # Screen coverage % from MSFS minSize
        screen_pct = 100.0 if i == 0 else 50.0
        if i < len(lod_infos):
            screen_pct = max(0.01, min(100.0, lod_infos[i].min_size))
        item.screen_size_pct = screen_pct

        # Meshes
        tier_meshes = lod_mesh_map.get(i, [])
        primary_mesh = next((m for m in tier_meshes if m.type == "MESH"), None)
        if primary_mesh:
            item.generated_obj = primary_mesh
            tier_tris = sum(count_mesh_triangles(m) for m in tier_meshes if m.type == "MESH")
            item.actual_tris = tier_tris
            item.actual_triangles = tier_tris
            item.last_baked_screen_pct = screen_pct
            item.state = "SOURCE" if i == 0 else "BAKED"
        else:
            item.state = "PLANNED"

    props.active_lod_index = 0
