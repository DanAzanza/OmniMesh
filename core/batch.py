"""
OmniMesh Batch Library Ingest Engine.
Discovers and batch-processes entire 3D model asset libraries (FBX, OBJ, glTF/GLB)
with automatic LOD generation, normal reprojection, texture channel packing,
and multi-engine packaging with deterministic memory deallocation.
"""

from __future__ import annotations

import gc
import logging
import math
import os
import time
from typing import Any, Optional

try:
    import bpy
except ImportError:
    bpy = None

try:
    from .decimator import MeshDecimator
    from .materials import MaterialOptimizer
    from .metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        generate_logarithmic_screen_tiers,
    )
    from .normals import NormalManager
    from .sanitizer import MeshSanitizer
    from .textures import TextureChannelPacker
    from ..exporters.godot_export import GodotExporter
    from ..exporters.msfs_export import MSFSExporter
    from ..exporters.ue5_export import UE5Exporter
    from ..exporters.unity_export import UnityExporter
except (ImportError, ValueError):
    from core.decimator import MeshDecimator
    from core.materials import MaterialOptimizer
    from core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        generate_logarithmic_screen_tiers,
    )
    from core.normals import NormalManager
    from core.sanitizer import MeshSanitizer
    from core.textures import TextureChannelPacker
    from exporters.godot_export import GodotExporter
    from exporters.msfs_export import MSFSExporter
    from exporters.ue5_export import UE5Exporter
    from exporters.unity_export import UnityExporter

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".fbx", ".obj", ".gltf", ".glb")


class BatchProcessorEngine:
    """Core batch processing engine with high memory isolation and pipeline orchestration."""

    @staticmethod
    def discover_assets(
        source_dir: str,
        recursive: bool = True,
        extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS,
    ) -> list[str]:
        """
        Discovers all 3D asset files within source directory with Windows extended-path safety
        and junction protection (followlinks=False).
        """
        if not source_dir or not os.path.exists(source_dir):
            return []

        resolved_source = os.path.abspath(source_dir)
        discovered_files: list[str] = []

        if recursive:
            for root, _dirs, files in os.walk(resolved_source, followlinks=False):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in extensions:
                        full_p = os.path.join(root, f)
                        discovered_files.append(full_p)
        else:
            try:
                for item in os.listdir(resolved_source):
                    full_p = os.path.join(resolved_source, item)
                    if os.path.isfile(full_p):
                        ext = os.path.splitext(item)[1].lower()
                        if ext in extensions:
                            discovered_files.append(full_p)
            except OSError as exc:
                logger.error("Failed to list source directory '%s': %s", resolved_source, exc)

        return sorted(discovered_files)

    @classmethod
    def import_asset_file(cls, filepath: str) -> list[Any]:
        """Imports 3D model file and returns newly created objects."""
        if not bpy or not os.path.exists(filepath):
            return []

        existing_objs = set(bpy.data.objects.keys())
        ext = os.path.splitext(filepath)[1].lower()

        try:
            if ext == ".fbx":
                if hasattr(bpy.ops.import_scene, "fbx"):
                    bpy.ops.import_scene.fbx(filepath=filepath)
            elif ext == ".obj":
                if hasattr(bpy.ops.wm, "obj_import"):
                    bpy.ops.wm.obj_import(filepath=filepath)
                elif hasattr(bpy.ops.import_scene, "obj"):
                    bpy.ops.import_scene.obj(filepath=filepath)
            elif ext in (".gltf", ".glb"):
                if hasattr(bpy.ops.import_scene, "gltf"):
                    bpy.ops.import_scene.gltf(filepath=filepath)
        except (RuntimeError, ValueError) as exc:
            logger.error("Failed to import asset '%s': %s", filepath, exc)
            return []

        new_objs = [bpy.data.objects[k] for k in bpy.data.objects.keys() if k not in existing_objs]
        return new_objs

    @classmethod
    def process_single_asset(
        cls,
        context: Any,
        filepath: str,
        export_base_dir: str,
        target_engine: str = "UE5",
        num_lods: int = 7,
        tau_sse: float = 0.8,
        cull_screen_size_pct: float = 0.5,
    ) -> dict[str, Any]:
        """
        Executes complete LOD pipeline on a single model file with complete teardown and memory cleanup.
        """
        start_time = time.time()
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        result: dict[str, Any] = {
            "asset_name": base_name,
            "filepath": filepath,
            "success": False,
            "initial_tris": 0,
            "final_tris": 0,
            "reduction_pct": 0.0,
            "duration_sec": 0.0,
            "message": "",
        }

        if not bpy or not context:
            result["message"] = "Blender environment not available."
            return result

        imported_objs = cls.import_asset_file(filepath)
        if not imported_objs:
            result["message"] = f"Failed to import '{filepath}'"
            return result

        mesh_objs = [o for o in imported_objs if o.type == "MESH"]
        if not mesh_objs:
            cls.cleanup_imported_objects(imported_objs)
            result["message"] = f"No valid mesh geometry found in '{filepath}'"
            return result

        generated_lod_objs: list[Any] = []
        coll: Optional[Any] = None

        try:
            # Primary mesh object selection
            primary_obj = mesh_objs[0]
            context.view_layer.objects.active = primary_obj

            # 1. Sanitize Master Mesh
            initial_tris = 0
            for obj in mesh_objs:
                if obj.data and hasattr(obj.data, "polygons") and len(obj.data.polygons) > 0:
                    import bmesh

                    bm = bmesh.new()
                    bm.from_mesh(obj.data)
                    MeshSanitizer.sanitize_mesh_full(bm)
                    bm.to_mesh(obj.data)
                    bm.free()
                    initial_tris += len(obj.data.polygons)
            result["initial_tris"] = initial_tris

            # 2. Compute Metric Extents & Tiers
            coords = [primary_obj.matrix_world @ v.co for v in primary_obj.data.vertices]
            center, radius = compute_bounding_sphere(coords)
            screen_tiers = generate_logarithmic_screen_tiers(
                num_lods=num_lods, cull_screen_size_pct=cull_screen_size_pct
            )

            # Setup LOD generation collection
            coll_name = f"{base_name}_LODs"
            coll = bpy.data.collections.get(coll_name)
            if not coll:
                coll = bpy.data.collections.new(coll_name)
                context.scene.collection.children.link(coll)

            props = getattr(context.scene, "lod_tool", None)
            if props:
                props.lods.clear()

            generated_lod_objs = []
            final_lod_tris = initial_tris

            # 3. Generate LOD Tiers
            for i, screen_pct in enumerate(screen_tiers):
                tier_name = f"LOD{i}"
                s_frac = screen_pct / 100.0
                dist_m = compute_distance_from_screen_size(radius, s_frac, math.radians(60.0))
                tolerances = compute_coupled_tolerances(radius, s_frac, tau_sse)
                delta_w = tolerances["delta_world"]

                # Duplicate primary mesh for this tier
                lod_obj_name = f"{base_name}_{tier_name}"
                lod_mesh = primary_obj.data.copy()
                lod_mesh.name = f"{lod_obj_name}_Mesh"
                lod_obj = bpy.data.objects.new(lod_obj_name, lod_mesh)
                lod_obj.matrix_world = primary_obj.matrix_world.copy()
                coll.objects.link(lod_obj)
                generated_lod_objs.append(lod_obj)

                # Decimate geometry
                if i > 0:
                    import bmesh

                    bm = bmesh.new()
                    bm.from_mesh(lod_obj.data)
                    pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                    MeshDecimator.apply_planar_limited_dissolve(bm, tolerances["planar_angle_deg"] * 0.0174533)
                    MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                    bm.to_mesh(lod_obj.data)
                    bm.free()

                    MeshDecimator.execute_decimate_qem(lod_obj, tolerances["qem_ratio"], use_curvature_weight=True)
                    NormalManager.reproject_custom_split_normals(lod_obj, primary_obj, delta_world=delta_w)

                    if i >= 2 and tolerances.get("area_crit", 0.0) > 0.0:
                        MaterialOptimizer.consolidate_micro_materials(
                            lod_obj, area_crit=tolerances.get("area_crit", 0.01)
                        )
                        MaterialOptimizer.purge_unused_materials(lod_obj)

                current_tris = len(lod_obj.data.polygons)
                if i == len(screen_tiers) - 1:
                    final_lod_tris = current_tris

                if props:
                    item = props.lods.add()
                    item.name = tier_name
                    item.lod_index = i
                    item.screen_size_pct = screen_pct
                    item.distance_m = dist_m
                    item.delta_world = delta_w
                    item.target_tris = int(initial_tris * tolerances["qem_ratio"])
                    item.actual_tris = current_tris
                    item.mat_slots_count = len(lod_obj.material_slots)
                    item.generated_obj = lod_obj

            # 4. Pack PBR Textures
            asset_export_dir = os.path.join(export_base_dir, base_name)
            tex_dir = os.path.join(asset_export_dir, "Textures")
            os.makedirs(tex_dir, exist_ok=True)

            unique_mats = set()
            for o in mesh_objs:
                for slot in o.material_slots:
                    if slot.material:
                        unique_mats.add(slot.material)

            for mat in unique_mats:
                m_name = mat.name.replace(" ", "_")
                if target_engine == "UE5":
                    TextureChannelPacker.pack_orm_ue5(mat, os.path.join(tex_dir, f"T_{m_name}_ORM.png"), (2048, 2048))
                    norm_img = TextureChannelPacker.get_material_normal_image(mat)
                    if norm_img:
                        TextureChannelPacker.convert_normal_directx(
                            norm_img, os.path.join(tex_dir, f"T_{m_name}_Normal_DirectX.png"), (2048, 2048)
                        )
                elif target_engine == "UNITY_6":
                    TextureChannelPacker.pack_maskmap_unity(
                        mat, os.path.join(tex_dir, f"T_{m_name}_MaskMap.png"), (2048, 2048)
                    )
                elif target_engine == "MSFS_2024":
                    TextureChannelPacker.pack_comp_msfs(
                        mat, os.path.join(tex_dir, f"T_{m_name}_COMP.png"), (2048, 2048)
                    )
                elif target_engine == "GODOT_4":
                    TextureChannelPacker.pack_orm_godot(mat, os.path.join(tex_dir, f"T_{m_name}_ORM.png"), (2048, 2048))

            # 5. Export Multi-Engine Package
            if props:
                props.export_base_name = base_name
                props.export_directory = asset_export_dir
                props.target_engine = target_engine

            export_ok = False
            export_msg = ""
            if target_engine == "MSFS_2024":
                export_ok, export_msg = MSFSExporter.export_asset(context, asset_export_dir, base_name)
            elif target_engine == "UE5":
                export_ok, export_msg = UE5Exporter.export_asset(context, asset_export_dir, base_name)
            elif target_engine == "UNITY_6":
                export_ok, export_msg = UnityExporter.export_asset(context, asset_export_dir, base_name)
            elif target_engine == "GODOT_4":
                export_ok, export_msg = GodotExporter.export_asset(context, asset_export_dir, base_name)

            reduction = ((initial_tris - final_lod_tris) / max(1, initial_tris)) * 100.0
            result["final_tris"] = final_lod_tris
            result["reduction_pct"] = round(reduction, 2)
            result["success"] = export_ok
            result["message"] = export_msg if export_ok else f"Export failed: {export_msg}"

        except Exception as exc:
            logger.error("Error during batch processing of '%s': %s", filepath, exc, exc_info=True)
            result["message"] = f"Pipeline exception: {exc}"
        finally:
            # 6. Strict Memory & Datablock Teardown
            all_created = imported_objs + generated_lod_objs
            cls.cleanup_imported_objects(all_created)
            if coll and bpy:
                try:
                    bpy.data.collections.remove(coll)
                except (RuntimeError, ReferenceError):
                    pass

            # Purge orphan datablocks
            if bpy:
                try:
                    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=False)
                except (RuntimeError, ValueError, AttributeError) as exc:
                    logger.debug("Orphan purge bypassed: %s", exc)

            gc.collect()
            TextureChannelPacker.compact_memory()

        result["duration_sec"] = round(time.time() - start_time, 2)
        return result

    @staticmethod
    def cleanup_imported_objects(objects: list[Any]) -> None:
        """Removes objects and their mesh datablocks cleanly from Blender memory."""
        if not bpy:
            return
        meshes_to_remove = set()
        for obj in objects:
            if not obj:
                continue
            if getattr(obj, "type", "") == "MESH" and obj.data:
                meshes_to_remove.add(obj.data)
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except (RuntimeError, ReferenceError):
                pass

        for mesh in meshes_to_remove:
            try:
                bpy.data.meshes.remove(mesh, do_unlink=True)
            except (RuntimeError, ReferenceError):
                pass
