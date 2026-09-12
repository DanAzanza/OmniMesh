"""
OmniMesh Batch Library Ingest Engine.
Discovers and batch-processes entire 3D model asset libraries (FBX, OBJ, glTF/GLB)
with automatic LOD generation, normal reprojection, texture channel packing,
and multi-engine packaging with deterministic memory deallocation.
"""

from __future__ import annotations

import concurrent.futures
import gc
import logging
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, ClassVar, Optional

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
    from .pbr_presets import PBRImporterPresetManager
    from .sanitizer import MeshSanitizer
    from .textures import TextureChannelPacker, TexturePoolManager
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
    from core.pbr_presets import PBRImporterPresetManager
    from core.sanitizer import MeshSanitizer
    from core.textures import TextureChannelPacker, TexturePoolManager

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".fbx", ".obj", ".gltf", ".glb")


class BatchProcessorEngine:
    """Core batch processing engine with high memory isolation and pipeline orchestration."""

    _exporters: ClassVar[dict[str, Callable[[Any, str, str], tuple[bool, str]]]] = {}

    @classmethod
    def register_exporter(cls, engine: str, handler: Callable[[Any, str, str], tuple[bool, str]]) -> None:
        """Registers a serialization handler for a target engine."""
        cls._exporters[engine] = handler

    @classmethod
    def _get_exporter(cls, engine: str) -> Optional[Callable[[Any, str, str], tuple[bool, str]]]:
        """Resolves target engine exporter handler with lazy fallback to avoid circular imports."""
        if engine in cls._exporters:
            return cls._exporters[engine]
        try:
            if engine == "MSFS_2024":
                try:
                    from exporters.msfs_export import MSFSExporter
                except (ImportError, ValueError):
                    from ..exporters.msfs_export import MSFSExporter

                return MSFSExporter.export_asset
            elif engine == "UE5":
                try:
                    from exporters.ue5_export import UE5Exporter
                except (ImportError, ValueError):
                    from ..exporters.ue5_export import UE5Exporter

                return UE5Exporter.export_asset
            elif engine == "UNITY_6":
                try:
                    from exporters.unity_export import UnityExporter
                except (ImportError, ValueError):
                    from ..exporters.unity_export import UnityExporter

                return UnityExporter.export_asset
            elif engine == "GODOT_4":
                try:
                    from exporters.godot_export import GodotExporter
                except (ImportError, ValueError):
                    from ..exporters.godot_export import GodotExporter

                return GodotExporter.export_asset
        except (ImportError, ValueError) as exc:
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
        norm_source = os.path.normpath(os.path.abspath(source_root))
        norm_blend = os.path.normpath(os.path.abspath(blend_path))
        norm_export = os.path.normpath(os.path.abspath(export_root))

        try:
            rel_path = os.path.relpath(norm_blend, norm_source)
        except ValueError:
            rel_path = os.path.basename(norm_blend)

        rel_dir = os.path.dirname(rel_path)

        clean_parts = [re.sub(r"[^\w\-]", "_", part) for part in Path(rel_dir).parts if part and part != "."]

        target_dir = os.path.join(norm_export, *clean_parts) if clean_parts else norm_export
        stem = Path(norm_blend).stem
        asset_name = re.sub(r"[^\w\-]", "_", stem)

        return os.path.normpath(target_dir), asset_name

    @classmethod
    def spawn_batch_worker(
        cls,
        blend_path: str,
        export_dir: str,
        preset_id: str = "",
        target_engine: str = "UE5",
        asset_name: str = "",
    ) -> subprocess.Popen:
        """Launches an isolated headless background Blender process to export a single .blend asset."""
        blender_exe = bpy.app.binary_path if bpy else "blender"
        addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        scripts_worker = os.path.join(addon_dir, "scripts", "batch_worker.py")
        worker_script = (
            scripts_worker
            if os.path.exists(scripts_worker)
            else os.path.join(os.path.dirname(__file__), "batch_worker.py")
        )

        cmd = [
            blender_exe,
            "-b",
            blend_path,
            "--factory-startup",
            "--disable-autoexec",
            "--python",
            worker_script,
            "--",
            "--export-dir",
            export_dir,
            "--engine",
            target_engine,
        ]
        if preset_id:
            cmd.extend(["--preset", preset_id])
        if asset_name:
            cmd.extend(["--asset-name", asset_name])

        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        return subprocess.Popen(cmd, **popen_kwargs)

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

        mesh_objs = [o for o in imported_objs if getattr(o, "type", "") == "MESH"]
        if not mesh_objs:
            cls.cleanup_imported_objects(imported_objs)
            result["message"] = f"No valid mesh geometry found in '{filepath}'"
            return result

        generated_lod_objs: list[Any] = []
        coll: Optional[Any] = None

        try:
            # Primary mesh object selection
            primary_obj = mesh_objs[0]
            if hasattr(context, "view_layer") and hasattr(context.view_layer, "objects"):
                context.view_layer.objects.active = primary_obj

            # 1. Sanitize Master Mesh
            initial_tris = 0
            for obj in mesh_objs:
                if obj.data and hasattr(obj.data, "polygons") and len(obj.data.polygons) > 0:
                    import bmesh

                    bm = bmesh.new()
                    try:
                        bm.from_mesh(obj.data)
                        MeshSanitizer.sanitize_mesh_full(bm)
                        bm.to_mesh(obj.data)
                    finally:
                        bm.free()
                    polys = getattr(obj.data, "polygons", [])
                    if polys and hasattr(polys[0], "vertices"):
                        initial_tris += sum(max(1, len(p.vertices) - 2) for p in polys)
                    else:
                        initial_tris += len(polys)
            result["initial_tris"] = initial_tris

            # 2. Compute Metric Extents & Tiers
            coords = []
            if hasattr(primary_obj.data, "vertices"):
                for v in primary_obj.data.vertices:
                    try:
                        coords.append(
                            primary_obj.matrix_world @ v.co if hasattr(primary_obj.matrix_world, "__matmul__") else v.co
                        )
                    except Exception:
                        coords.append(v.co)

            center, radius = compute_bounding_sphere(coords)
            screen_tiers = generate_logarithmic_screen_tiers(
                num_lods=num_lods, cull_screen_size_pct=cull_screen_size_pct
            )

            # Setup LOD generation collection
            coll_name = f"{base_name}_LODs"
            coll = bpy.data.collections.get(coll_name)
            if not coll:
                coll = bpy.data.collections.new(coll_name)
                if hasattr(context, "scene") and hasattr(context.scene, "collection"):
                    context.scene.collection.children.link(coll)

            props = getattr(getattr(context, "scene", None), "lod_tool", None)
            if props and hasattr(props, "lods"):
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
                if coll:
                    coll.objects.link(lod_obj)
                generated_lod_objs.append(lod_obj)

                # Decimate geometry
                if i > 0:
                    import bmesh

                    bm = bmesh.new()
                    try:
                        bm.from_mesh(lod_obj.data)
                        pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                        MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
                        MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                        bm.to_mesh(lod_obj.data)
                    finally:
                        bm.free()

                    MeshDecimator.execute_decimate_qem(lod_obj, tolerances["qem_ratio"], use_curvature_weight=True)
                    NormalManager.reproject_custom_split_normals(lod_obj, primary_obj, delta_world=delta_w)

                    if i >= 2 and tolerances.get("area_crit", 0.0) > 0.0:
                        MaterialOptimizer.consolidate_micro_materials(
                            lod_obj, area_crit=tolerances.get("area_crit", 0.01)
                        )
                        MaterialOptimizer.purge_unused_materials(lod_obj)

                current_tris = (
                    len(lod_obj.data.polygons)
                    if (hasattr(lod_obj, "data") and hasattr(lod_obj.data, "polygons"))
                    else 0
                )
                if i == len(screen_tiers) - 1:
                    final_lod_tris = current_tris

                if props and hasattr(props, "lods"):
                    item = props.lods.add()
                    item.name = tier_name
                    item.lod_index = i
                    item.screen_size_pct = screen_pct
                    item.distance_m = dist_m
                    item.delta_world = delta_w
                    item.target_tris = int(initial_tris * tolerances["qem_ratio"])
                    item.actual_tris = current_tris
                    item.mat_slots_count = len(getattr(lod_obj, "material_slots", []))
                    item.generated_obj = lod_obj

            # 4. Pack PBR Textures
            asset_export_dir = os.path.join(export_base_dir, base_name)
            tex_dir = os.path.join(asset_export_dir, "Textures")
            os.makedirs(tex_dir, exist_ok=True)

            unique_mats = set()
            for o in mesh_objs:
                for slot in getattr(o, "material_slots", []):
                    if slot.material:
                        unique_mats.add(slot.material)

            # Resolve active PBR preset for batch packing
            preset_id = getattr(props, "pbr_export_preset", "") or getattr(props, "pbr_preset", "")
            if not preset_id:
                engine_map = {
                    "UE5": "unreal_engine_5",
                    "UNITY_6": "unity_hdrp_maskmap",
                    "MSFS_2024": "msfs_2024_comp",
                    "GODOT_4": "godot_4_orm",
                }
                preset_id = engine_map.get(target_engine, "unreal_engine_5")

            try:
                preset = PBRImporterPresetManager.get_preset(preset_id)
            except Exception as exc:
                logger.warning("Could not load batch preset '%s': %s", preset_id, exc)
                preset = PBRImporterPresetManager.get_preset("unreal_engine_5")

            strategy = getattr(props, "pbr_export_texture_strategy", preset.get("strategy", "CONVERT_PNG"))
            bit_depth = int(getattr(props, "pbr_export_bit_depth", str(preset.get("bit_depth", 8))))
            naming_pattern = getattr(
                props, "pbr_export_naming_pattern", preset.get("naming_pattern", "{material}{suffix}")
            )

            all_tex_futures: list[Any] = []
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
                    )
                    if futs:
                        all_tex_futures.extend(futs)
                except Exception as exc:
                    logger.warning(
                        "Preset-based texture packing failed for '%s', using fallback: %s",
                        getattr(mat, "name", "Mat"),
                        exc,
                    )
                    m_name = getattr(mat, "name", "Mat").replace(" ", "_")
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
                    elif target_engine == "GODOT_4":
                        f_fallback = TextureChannelPacker.pack_orm_godot(
                            mat, os.path.join(tex_dir, f"T_{m_name}_ORM.png"), (2048, 2048)
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
                except (RuntimeError, ReferenceError, Exception) as exc:
                    logger.debug("Collection cleanup failed: %s", exc)

            # Purge orphan datablocks
            if bpy:
                try:
                    bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=False, do_recursive=False)
                except (RuntimeError, ValueError, AttributeError, Exception) as exc:
                    logger.debug("Orphan purge bypassed: %s", exc)

            gc.collect()
            try:
                TextureChannelPacker.compact_memory()
            except Exception as exc:
                logger.debug("Texture packer memory compact bypassed: %s", exc)

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
            if getattr(obj, "type", "") == "MESH" and getattr(obj, "data", None):
                meshes_to_remove.add(obj.data)
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
            except (RuntimeError, ReferenceError, Exception) as exc:
                logger.debug("Object remove error: %s", exc)

        for mesh in meshes_to_remove:
            try:
                bpy.data.meshes.remove(mesh, do_unlink=True)
            except (RuntimeError, ReferenceError, Exception) as exc:
                logger.debug("Mesh remove error: %s", exc)
