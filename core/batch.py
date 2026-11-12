"""
OmniMesh Batch Library Ingest Engine.
Discovers and batch-processes entire 3D model asset libraries (FBX, OBJ, glTF/GLB)
with automatic LOD generation, normal reprojection, texture channel packing,
and multi-engine packaging with deterministic memory deallocation.
"""

from __future__ import annotations

from .exceptions import OmniMeshError

import concurrent.futures
import ctypes
import ctypes.util
import gc
import logging
import math
import os
import sys
import time
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional, cast

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData, Collection, Context, Mesh, Object
else:
    try:
        import bpy
        from bpy.types import Collection, Context, Mesh, Object
    except ImportError:
        bpy = None
        Collection = object
        Context = object
        Mesh = object
        Object = object
    BlendData = object

from .compat import count_mesh_triangles, import_scene_asset
from .decimator import MeshDecimator
from .materials import MaterialOptimizer
from .batch_worker_process import (
    BatchWorkerProcessManager,
    WorkerProcessHandle,
    build_hierarchical_export_path,
)
from .metrics import (
    compute_bounding_sphere,
    compute_coupled_tolerances,
    compute_distance_from_screen_size,
    generate_logarithmic_screen_tiers,
)
from .normals import NormalManager
from .pbr_presets import PBRImporterPresetManager
from .sanitizer import MeshSanitizer
from .textures import TextureChannelPacker, TexturePoolManager

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".fbx", ".obj", ".gltf", ".glb")


class BatchProcessorEngine:
    """Core batch processing engine with high memory isolation and pipeline orchestration."""

    _exporters: ClassVar[dict[str, Callable[[bpy.types.Context | None, str, str], tuple[bool, str]]]] = {}

    @classmethod
    def register_exporter(
        cls,
        engine: str,
        handler: Callable[[bpy.types.Context | None, str, str], tuple[bool, str]],
    ) -> None:
        """Registers a serialization handler for a target engine."""
        cls._exporters[engine] = handler

    @classmethod
    def _get_exporter(cls, engine: str) -> Optional[Callable[[bpy.types.Context | None, str, str], tuple[bool, str]]]:
        """Resolves target engine exporter handler with lazy fallback to avoid circular imports."""
        if engine in cls._exporters:
            return cls._exporters[engine]
        try:
            if engine == "MSFS_2024":
                try:
                    from ..exporters.msfs_export import MSFSExporter
                except (ImportError, ValueError):
                    from exporters.msfs_export import MSFSExporter

                return MSFSExporter.export_asset
            elif engine == "UE5":
                try:
                    from ..exporters.ue5_export import UE5Exporter
                except (ImportError, ValueError):
                    from exporters.ue5_export import UE5Exporter

                return UE5Exporter.export_asset
            elif engine == "UNITY_6":
                try:
                    from ..exporters.unity_export import UnityExporter
                except (ImportError, ValueError):
                    from exporters.unity_export import UnityExporter

                return UnityExporter.export_asset
        except (ImportError, ValueError) as exc:
            cls._exporters.pop(engine, None)
            logger.debug("Lazy exporter load failed for engine '%s': %s", engine, exc)
        return None

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

        try:
            if recursive:
                for root, _dirs, files in os.walk(resolved_source, followlinks=False):
                    for f in files:
                        ext = os.path.splitext(f)[1].lower()
                        if ext in extensions:
                            full_p = os.path.join(root, f)
                            discovered_files.append(full_p)
            else:
                for item in os.listdir(resolved_source):
                    full_p = os.path.join(resolved_source, item)
                    if os.path.isfile(full_p):
                        ext = os.path.splitext(item)[1].lower()
                        if ext in extensions:
                            discovered_files.append(full_p)
        except OSError as exc:
            discovered_files.clear()
            logger.error("Failed during asset discovery in '%s': %s", resolved_source, exc)

        return sorted(discovered_files)

    @staticmethod
    def discover_blend_files(
        source_dir: str,
        recursive: bool = True,
        export_dir: str = "",
    ) -> list[str]:
        """Discovers valid .blend files in source directory, ignoring locks, backups,
        and excluding the export directory if nested.
        """
        if not source_dir or not os.path.exists(source_dir):
            return []

        resolved_source = os.path.normpath(os.path.abspath(source_dir))
        resolved_export = os.path.normpath(os.path.abspath(export_dir)) if export_dir else ""
        discovered_files: list[str] = []

        try:
            if recursive:
                for root, dirs, files in os.walk(resolved_source, followlinks=False):
                    # Prevent recursing into export directory or hidden folders
                    dirs[:] = [
                        d
                        for d in dirs
                        if not (
                            resolved_export
                            and os.path.normpath(os.path.abspath(os.path.join(root, d))) == resolved_export
                        )
                        and not d.startswith(".")
                    ]
                    for f in files:
                        if f.lower().endswith(".blend") and not f.startswith((".", "~", "#")):
                            discovered_files.append(os.path.join(root, f))
            else:
                for item in os.listdir(resolved_source):
                    full_p = os.path.join(resolved_source, item)
                    if os.path.isfile(full_p):
                        if item.lower().endswith(".blend") and not item.startswith((".", "~", "#")):
                            discovered_files.append(full_p)
        except OSError as exc:
            discovered_files.clear()
            logger.error("Failed during .blend discovery in '%s': %s", resolved_source, exc)

        return sorted(discovered_files)

    @staticmethod
    def compute_mirrored_export_path(
        blend_path: str,
        source_root: str,
        export_root: str,
    ) -> tuple[str, str]:
        """Calculates destination directory mirroring source folder hierarchy with sanitized names.
        Returns (target_export_dir, asset_name).
        """
        return build_hierarchical_export_path(blend_path, source_root, export_root)

    @classmethod
    def spawn_batch_worker(
        cls,
        blend_path: str,
        export_dir: str,
        preset_id: str = "",
        target_engine: str = "UE5",
        asset_name: str = "",
    ) -> WorkerProcessHandle:
        """Launches an isolated headless background Blender process to export a single .blend asset."""
        return BatchWorkerProcessManager.spawn_batch_worker(
            blend_path=blend_path,
            export_dir=export_dir,
            preset_id=preset_id,
            target_engine=target_engine,
            asset_name=asset_name,
        )

    @classmethod
    def import_asset_file(
        cls,
        filepath: str,
        *,
        blend_data: BlendData,
    ) -> list[bpy.types.Object]:
        """Imports 3D model file and returns newly created objects."""
        if not bpy or not os.path.exists(filepath):
            return []

        bdata = blend_data
        bdata_objs = bdata.objects if bdata else None
        if not bdata_objs:
            return []

        existing_objs = {o.name for o in bdata_objs}

        try:
            import_scene_asset(filepath)
        except (RuntimeError, ValueError) as exc:
            logger.error("Failed to import asset '%s': %s", filepath, exc)
            return []

        new_objs = [o for o in bdata_objs if o.name not in existing_objs]
        return new_objs

    @classmethod
    def process_single_asset(
        cls,
        context: bpy.types.Context | None,
        filepath: str,
        export_base_dir: str,
        target_engine: str = "UE5",
        num_lods: int = 7,
        tau_sse: float = 0.8,
        cull_screen_size_pct: float = 0.5,
        *,
        blend_data: BlendData,
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

        bdata = blend_data
        bdata_objs = bdata.objects if bdata else None
        bdata_cols = bdata.collections if bdata else None

        imported_objs = cls.import_asset_file(filepath, blend_data=bdata)
        if not imported_objs:
            result["message"] = f"Failed to import '{filepath}'"
            return result

        mesh_objs = [o for o in imported_objs if o.type == "MESH"]
        if not mesh_objs:
            cls.cleanup_imported_objects(imported_objs, blend_data=bdata)
            result["message"] = f"No valid mesh geometry found in '{filepath}'"
            return result

        generated_lod_objs: list[bpy.types.Object] = []
        coll: Optional[bpy.types.Collection] = None

        try:
            # Primary mesh object selection
            primary_obj = mesh_objs[0]
            if context.view_layer and context.view_layer.objects is not None:
                context.view_layer.objects.active = primary_obj

            # 1. Sanitize Master Mesh
            initial_tris = 0
            for obj in mesh_objs:
                obj_mesh = cast("bpy.types.Mesh | None", obj.data)
                if obj_mesh and obj_mesh.polygons and len(obj_mesh.polygons) > 0:
                    import bmesh

                    bm = bmesh.new()
                    try:
                        bm.from_mesh(obj_mesh)
                        MeshSanitizer.sanitize_mesh_full(bm)
                        bm.to_mesh(obj_mesh)
                    finally:
                        bm.free()
                    initial_tris += count_mesh_triangles(obj_mesh)

            result["initial_tris"] = initial_tris

            # 2. Compute Metric Extents & Tiers
            coords = []
            primary_mesh = cast("bpy.types.Mesh | None", primary_obj.data)
            if primary_mesh and primary_mesh.vertices:
                for v in primary_mesh.vertices:
                    try:
                        coords.append(primary_obj.matrix_world @ v.co)
                    except (TypeError, ValueError, AttributeError, ReferenceError):
                        coords.append(v.co)

            center, radius = compute_bounding_sphere(coords)
            screen_tiers = generate_logarithmic_screen_tiers(
                num_lods=num_lods, cull_screen_size_pct=cull_screen_size_pct
            )

            # Setup LOD generation collection
            coll_name = f"{base_name}_LODs"
            coll = bdata_cols.get(coll_name) if bdata_cols else None
            if not coll and bdata_cols:
                coll = bdata_cols.new(coll_name)
                if context.scene and context.scene.collection:
                    context.scene.collection.children.link(coll)

            props = getattr(context.scene, "lod_tool", None) if context.scene else None
            if props and props.lods is not None:
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
                if primary_mesh is None:
                    continue
                lod_obj_name = f"{base_name}_{tier_name}"
                lod_mesh = primary_mesh.copy()
                if lod_mesh is None:
                    continue
                lod_mesh.name = f"{lod_obj_name}_Mesh"
                lod_obj = bdata_objs.new(lod_obj_name, lod_mesh) if bdata_objs else None
                if lod_obj is None:
                    continue
                lod_obj.matrix_world = primary_obj.matrix_world.copy()
                if coll:
                    coll.objects.link(lod_obj)
                generated_lod_objs.append(lod_obj)

                lod_mesh = cast("bpy.types.Mesh | None", lod_obj.data)

                # Decimate geometry
                if i > 0 and lod_mesh is not None:
                    import bmesh

                    bm = bmesh.new()
                    try:
                        bm.from_mesh(lod_mesh)
                        pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                        MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
                        MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                        bm.to_mesh(lod_mesh)
                    finally:
                        bm.free()

                    MeshDecimator.execute_decimate_qem(lod_obj, tolerances["qem_ratio"], use_curvature_weight=True)
                    NormalManager.reproject_custom_split_normals(lod_obj, primary_obj, delta_world=delta_w)

                    if i >= 2 and tolerances.get("area_crit", 0.0) > 0.0:
                        MaterialOptimizer.consolidate_micro_materials(
                            lod_obj, area_crit=tolerances.get("area_crit", 0.01)
                        )
                        MaterialOptimizer.purge_unused_materials(lod_obj)

                current_tris = len(lod_mesh.polygons) if (lod_mesh is not None and lod_mesh.polygons is not None) else 0
                if i == len(screen_tiers) - 1:
                    final_lod_tris = current_tris

                if props and props.lods is not None:
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

            # Resolve active PBR preset for batch packing
            preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", "")
            if not preset_id:
                engine_map = {
                    "UE5": "unreal_engine_5",
                    "UNITY_6": "unity_hdrp_maskmap",
                    "MSFS_2024": "msfs_2024_comp",
                }
                preset_id = engine_map.get(target_engine, "unreal_engine_5")

            try:
                preset = PBRImporterPresetManager.get_preset(preset_id)
            except (KeyError, ValueError, OSError, TypeError) as exc:
                logger.warning("Could not load batch preset '%s': %s", preset_id, exc)
                preset = PBRImporterPresetManager.get_preset("unreal_engine_5")

            strategy = getattr(props, "pbr_export_texture_strategy", preset.get("strategy", "CONVERT_PNG"))
            bit_depth = int(getattr(props, "pbr_export_bit_depth", str(preset.get("bit_depth", 8))))
            naming_pattern = getattr(
                props, "pbr_export_naming_pattern", preset.get("naming_pattern", "{asset}_{material}{suffix}{udim}")
            )

            all_tex_futures: list[concurrent.futures.Future[bool]] = []
            for mat in unique_mats:
                try:
                    futs = TextureChannelPacker.pack_material_preset(
                        material=mat,
                        preset=preset,
                        export_dir=tex_dir,
                        asset_name=base_name,
                        target_size=(2048, 2048),
                        bit_depth=bit_depth,
                        strategy=strategy,
                        naming_pattern=naming_pattern,
                        context=context,
                        blend_data=bdata,
                    )
                    if futs:
                        all_tex_futures.extend(futs)
                except (RuntimeError, ValueError, OSError, AttributeError, TypeError) as exc:
                    logger.warning(
                        "Preset-based texture packing failed for '%s', using fallback: %s",
                        mat.name,
                        exc,
                    )
                    m_name = mat.name.replace(" ", "_")
                    if target_engine == "UE5":
                        f_fallback = TextureChannelPacker.pack_orm_ue5(
                            mat, os.path.join(tex_dir, f"T_{m_name}_ORM.png"), (2048, 2048)
                        )
                        if isinstance(f_fallback, concurrent.futures.Future):
                            all_tex_futures.append(f_fallback)
                    elif target_engine == "UNITY_6":
                        f_fallback = TextureChannelPacker.pack_maskmap_unity(
                            mat, os.path.join(tex_dir, f"T_{m_name}_MaskMap.png"), (2048, 2048)
                        )
                        if isinstance(f_fallback, concurrent.futures.Future):
                            all_tex_futures.append(f_fallback)
                    elif target_engine == "MSFS_2024":
                        f_fallback = TextureChannelPacker.pack_comp_msfs(
                            mat, os.path.join(tex_dir, f"T_{m_name}_COMP.png"), (2048, 2048)
                        )
                        if isinstance(f_fallback, concurrent.futures.Future):
                            all_tex_futures.append(f_fallback)

            # Join barrier: ensure all background texture compression writes finish before packaging
            if all_tex_futures:
                TexturePoolManager.wait_all(all_tex_futures, timeout=60.0)

            # 5. Export Multi-Engine Package
            if props:
                props.export_base_name = base_name
                props.export_directory = asset_export_dir
                props.target_engine = target_engine

            export_ok = False
            export_msg = ""
            exporter = cls._get_exporter(target_engine)
            if exporter:
                export_ok, export_msg = exporter(context, asset_export_dir, base_name)
            else:
                export_ok, export_msg = False, f"Unsupported engine '{target_engine}'"

            reduction = ((initial_tris - final_lod_tris) / max(1, initial_tris)) * 100.0
            result["final_tris"] = final_lod_tris
            result["reduction_pct"] = round(reduction, 2)
            result["success"] = export_ok
            result["message"] = export_msg if export_ok else f"Export failed: {export_msg}"

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
        ) as exc:
            logger.error("Error during batch processing of '%s': %s", filepath, exc, exc_info=True)
            result["message"] = f"Pipeline exception: {exc}"
        finally:
            cleanup_errors: list[str] = []
            # 6. Strict Memory & Datablock Teardown
            all_created = imported_objs + generated_lod_objs
            cls.cleanup_imported_objects(all_created, blend_data=bdata)
            if coll and bdata_cols:
                try:
                    bdata_cols.remove(coll)
                except (RuntimeError, ReferenceError, AttributeError) as exc:
                    cleanup_errors.append(f"collection remove: {exc}")
                    logger.debug("Collection cleanup failed: %s", exc)

            # Purge orphan datablocks
            if bdata is not None:
                try:
                    is_bg = bool(bpy.app.background) if (bpy and bpy.app) else False
                    bdata.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=is_bg)
                except (RuntimeError, ValueError, AttributeError) as exc:
                    cleanup_errors.append(f"orphans purge: {exc}")
                    logger.debug("Orphan purge bypassed: %s", exc)

            gc.collect()
            try:
                TextureChannelPacker.compact_memory()
            except (RuntimeError, AttributeError) as exc:
                cleanup_errors.append(f"texture pack compact: {exc}")
                logger.debug("Texture packer memory compact bypassed: %s", exc)

            if cleanup_errors:
                result["cleanup_warnings"] = cleanup_errors

        result["duration_sec"] = round(time.time() - start_time, 2)
        return result

    @staticmethod
    def cleanup_imported_objects(
        objects: list[bpy.types.Object],
        *,
        blend_data: BlendData,
    ) -> None:
        """Removes objects and their mesh datablocks cleanly from Blender memory."""
        bdata_objs = blend_data.objects if blend_data else None
        bdata_meshes = blend_data.meshes if blend_data else None

        meshes_to_remove = set()
        obj_errors = 0
        mesh_errors = 0
        for obj in objects:
            if not obj:
                continue
            if obj.type == "MESH" and obj.data:
                meshes_to_remove.add(obj.data)
            if bdata_objs:
                try:
                    bdata_objs.remove(obj, do_unlink=True)
                except (RuntimeError, ReferenceError, AttributeError) as exc:
                    obj_errors += 1
                    logger.debug("Object remove error: %s", exc)

        for mesh in meshes_to_remove:
            if bdata_meshes:
                try:
                    bdata_meshes.remove(mesh, do_unlink=True)
                except (RuntimeError, ReferenceError, AttributeError) as exc:
                    mesh_errors += 1
                    logger.debug("Mesh remove error: %s", exc)

    @classmethod
    def force_garbage_collection(cls) -> None:
        """Triggers cyclic garbage collection and releases uncommitted memory back to the OS."""
        gc.collect()
        os_errors: list[str] = []
        if sys.platform == "win32":
            try:
                ctypes.windll.kernel32.SetProcessWorkingSetSize(-1, -1, -1)
            except (OSError, AttributeError) as exc:
                os_errors.append(f"SetProcessWorkingSetSize: {exc}")
                logger.debug("Win32 SetProcessWorkingSetSize error: %s", exc)
            try:
                ctypes.cdll.msvcrt._heapmin()
            except (OSError, AttributeError) as exc:
                os_errors.append(f"_heapmin: {exc}")
                logger.debug("Win32 _heapmin error: %s", exc)
        elif sys.platform.startswith("linux"):
            try:
                libc_name = ctypes.util.find_library("c")
                if libc_name:
                    libc = ctypes.CDLL(libc_name)
                    if hasattr(libc, "malloc_trim"):
                        libc.malloc_trim(0)
            except (OSError, AttributeError) as exc:
                os_errors.append(f"malloc_trim: {exc}")
                logger.debug("Linux malloc_trim error: %s", exc)
