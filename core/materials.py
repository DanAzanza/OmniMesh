"""
Material Optimization, Cleanup & Slot Consolidation Subsystem for OmniMesh.
Features zero-bpy.ops headless slot compaction, cryptographic AST shader hashing,
semantic missing texture fallback routing, and guarded micro-material consolidation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
except ImportError:
    bpy = None
    bmesh = None


class DeepMaterialHasher:
    """
    Cryptographic AST-Style Shader Node Graph Hasher.
    Computes a deterministic SHA-256 hash of a material's functional shading pipeline.
    Ignores cosmetic UI layout coordinates, localized node labels, and window states.
    """

    @classmethod
    def hash_material(cls, mat: Any) -> str:
        if not mat or not hasattr(mat, "node_tree") or not mat.node_tree:
            diffuse = getattr(mat, "diffuse_color", (0.8, 0.8, 0.8, 1.0))
            if hasattr(diffuse, "__iter__"):
                diff_list = [round(float(v), 4) for v in diffuse]
            else:
                diff_list = [0.8, 0.8, 0.8, 1.0]
            return hashlib.sha256(f"NON_NODES:{diff_list}".encode("utf-8")).hexdigest()

        nodes = mat.node_tree.nodes

        # Find active output material node
        output_node = None
        for n in nodes:
            if getattr(n, "type", "") == "OUTPUT_MATERIAL" and getattr(n, "is_active_output", True):
                output_node = n
                break

        if not output_node:
            for n in nodes:
                if getattr(n, "type", "") == "OUTPUT_MATERIAL":
                    output_node = n
                    break

        if not output_node:
            return hashlib.sha256("EMPTY_OR_INVALID_OUTPUT".encode("utf-8")).hexdigest()

        # Traverse reachable nodes from output backwards
        visited_nodes: set[str] = set()
        queue: list[Any] = [output_node]
        canonical_nodes: list[dict[str, Any]] = []
        canonical_links: list[dict[str, Any]] = []

        while queue:
            curr = queue.pop(0)
            node_name = str(getattr(curr, "name", id(curr)))
            if node_name in visited_nodes:
                continue
            visited_nodes.add(node_name)

            node_data: dict[str, Any] = {
                "type": str(getattr(curr, "type", "")),
            }

            # Capture node-specific internal properties
            if hasattr(curr, "operation"):
                node_data["operation"] = str(curr.operation)
            if hasattr(curr, "blend_type"):
                node_data["blend_type"] = str(curr.blend_type)
            if hasattr(curr, "color_space"):
                node_data["color_space"] = str(curr.color_space)
            if hasattr(curr, "image") and curr.image:
                img = curr.image
                node_data["image_name"] = os.path.basename(getattr(img, "filepath", "") or getattr(img, "name", ""))
                node_data["image_size"] = list(getattr(img, "size", [0, 0]))

            # Capture unlinked input default values
            input_defaults: dict[str, Any] = {}
            for sock in getattr(curr, "inputs", []):
                if not getattr(sock, "is_linked", False) and hasattr(sock, "default_value"):
                    val = sock.default_value
                    if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
                        try:
                            input_defaults[str(sock.name)] = [round(float(v), 5) for v in val]
                        except Exception:
                            input_defaults[str(sock.name)] = str(val)
                    elif isinstance(val, (int, float)):
                        input_defaults[str(sock.name)] = round(float(val), 5)
                    elif isinstance(val, str):
                        input_defaults[str(sock.name)] = val
            node_data["input_defaults"] = input_defaults
            canonical_nodes.append(node_data)

            # Trace incoming links
            for sock in getattr(curr, "inputs", []):
                for link in getattr(sock, "links", []):
                    from_node = link.from_node
                    from_name = str(getattr(from_node, "name", id(from_node)))
                    canonical_links.append(
                        {
                            "from_type": str(getattr(from_node, "type", "")),
                            "from_socket": str(getattr(link.from_socket, "name", "")),
                            "to_type": str(getattr(curr, "type", "")),
                            "to_socket": str(getattr(sock, "name", "")),
                        }
                    )
                    if from_name not in visited_nodes:
                        queue.append(from_node)

        # Sort canonically for deterministic serialization
        canonical_nodes.sort(key=lambda x: (x.get("type", ""), str(x.get("input_defaults", ""))))
        canonical_links.sort(key=lambda x: (x.get("from_type", ""), x.get("to_type", ""), x.get("to_socket", "")))

        payload = {
            "nodes": canonical_nodes,
            "links": canonical_links,
            "blend_method": str(getattr(mat, "blend_method", "OPAQUE")),
            "use_backface_culling": bool(getattr(mat, "use_backface_culling", False)),
        }
        serialized = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class HeadlessSlotCompactor:
    """
    Pure Low-Level Python Data-API Material Slot Compactor & Deduplicator.
    Eliminates all bpy.ops calls to ensure 100% headless CI and background CLI safety.
    """

    @classmethod
    def compact_slots(
        cls,
        obj: Any,
        purge_empty: bool = True,
        deduplicate_identical: bool = True,
    ) -> dict[str, int]:
        """
        Compacts material slots, removes unassigned/empty slots, deduplicates repeated material slots,
        and atomically remaps polygon material indices in-place.
        """
        if not obj or not hasattr(obj, "data") or not obj.data:
            return {"slots_removed": 0, "faces_remapped": 0}
        mesh = obj.data
        if not hasattr(mesh, "polygons") or not hasattr(obj, "material_slots"):
            return {"slots_removed": 0, "faces_remapped": 0}

        num_slots = len(obj.material_slots)
        if num_slots == 0:
            return {"slots_removed": 0, "faces_remapped": 0}

        # 1. Tally polygon material references
        used_indices: set[int] = set()
        for poly in mesh.polygons:
            idx = getattr(poly, "material_index", 0)
            if 0 <= idx < num_slots:
                used_indices.add(idx)

        # 2. Build deterministic compaction & deduplication map
        new_materials: list[Any] = []
        mat_to_new_index: dict[Any, int] = {}
        slot_remap: dict[int, int] = {}

        for old_idx in range(num_slots):
            slot = obj.material_slots[old_idx]
            mat = slot.material

            if purge_empty and (mat is None or old_idx not in used_indices):
                continue

            if deduplicate_identical and mat in mat_to_new_index:
                # Rebind to existing slot index of identical material
                slot_remap[old_idx] = mat_to_new_index[mat]
            else:
                new_idx = len(new_materials)
                new_materials.append(mat)
                if mat is not None:
                    mat_to_new_index[mat] = new_idx
                slot_remap[old_idx] = new_idx

        # If no slot structure changed, return early
        if len(new_materials) == num_slots and all(slot_remap.get(i, i) == i for i in range(num_slots)):
            return {"slots_removed": 0, "faces_remapped": 0}

        # 3. Remap mesh polygon indices in-place
        faces_remapped = 0
        for poly in mesh.polygons:
            old_i = getattr(poly, "material_index", 0)
            new_i = slot_remap.get(old_i, 0)
            if new_i != old_i:
                poly.material_index = new_i
                faces_remapped += 1

        # 4. Atomic replacement of mesh materials array
        if hasattr(mesh, "materials"):
            mesh.materials.clear()
            for mat in new_materials:
                mesh.materials.append(mat)

        slots_removed = num_slots - len(new_materials)
        return {"slots_removed": slots_removed, "faces_remapped": faces_remapped}


class SemanticTextureAuditor:
    """
    Detects broken/missing image files while respecting packed textures, UDIMs, and generated images.
    Provides semantic socket tracing to inject safe PBR procedural fallbacks (e.g. flat tangent normal).
    """

    @classmethod
    def is_image_valid(cls, img: Any) -> bool:
        if not img:
            return False
        if getattr(img, "packed_file", None) is not None:
            return True
        if getattr(img, "has_data", False):
            return True
        if getattr(img, "source", "") == "GENERATED":
            return True
        filepath = getattr(img, "filepath", "")
        if not filepath:
            return False
        if bpy:
            try:
                abs_path = bpy.path.abspath(filepath)
                return os.path.exists(abs_path)
            except Exception:
                return os.path.exists(filepath)
        return os.path.exists(filepath)

    @classmethod
    def repair_missing_textures_in_material(cls, mat: Any) -> int:
        """
        Audits image texture nodes in the material. If an image is broken or missing,
        replaces it with safe socket-specific defaults without corrupting normal vectors.
        """
        if not mat or not hasattr(mat, "node_tree") or not mat.node_tree:
            return 0

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        repaired_nodes = 0

        for node in list(nodes):
            if getattr(node, "type", "") == "TEX_IMAGE":
                img = getattr(node, "image", None)
                if not cls.is_image_valid(img):
                    # Trace downstream connections to inject semantic default
                    for out_sock in getattr(node, "outputs", []):
                        for link in list(getattr(out_sock, "links", [])):
                            target_sock = link.to_socket
                            target_node = link.to_node

                            # Check target socket semantics
                            sock_name = str(getattr(target_sock, "name", "")).lower()
                            node_type = getattr(target_node, "type", "")

                            if "normal" in sock_name or node_type == "NORMAL_MAP":
                                # Safely unlink normal map to restore unperturbed surface normal
                                links.remove(link)
                            elif "roughness" in sock_name:
                                if hasattr(target_sock, "default_value"):
                                    target_sock.default_value = 0.5
                                links.remove(link)
                            elif "metallic" in sock_name:
                                if hasattr(target_sock, "default_value"):
                                    target_sock.default_value = 0.0
                                links.remove(link)
                            elif "base color" in sock_name or "color" in sock_name:
                                if hasattr(target_sock, "default_value"):
                                    target_sock.default_value = (0.8, 0.8, 0.8, 1.0)
                                links.remove(link)
                            else:
                                links.remove(link)

                    nodes.remove(node)
                    repaired_nodes += 1

        return repaired_nodes

    @classmethod
    def remove_orphan_texture_nodes(cls, mat: Any) -> int:
        """Removes dead/disconnected texture image nodes (0 outputs connected)."""
        if not mat or not hasattr(mat, "node_tree") or not mat.node_tree:
            return 0
        nodes = mat.node_tree.nodes
        removed = 0
        for node in list(nodes):
            if getattr(node, "type", "") == "TEX_IMAGE":
                is_used = any(len(out.links) > 0 for out in getattr(node, "outputs", []))
                if not is_used:
                    nodes.remove(node)
                    removed += 1
        return removed


class MaterialOptimizer:
    """
    Unified Material Optimization, Cleanup and Consolidation Engine.
    """

    PROTECTED_KEYWORDS = ("emissive", "emission", "glass", "decal", "light", "eye", "lamp")

    @classmethod
    def calculate_material_areas(cls, obj: Any) -> dict[int, float]:
        """Calculates cumulative surface area per material slot index."""
        if not obj or not hasattr(obj, "data") or not obj.data:
            return {}
        mesh = obj.data
        if not hasattr(mesh, "polygons") or not hasattr(obj, "material_slots"):
            return {}

        num_slots = len(obj.material_slots)
        if num_slots == 0:
            return {}

        areas: dict[int, float] = {i: 0.0 for i in range(num_slots)}
        for poly in mesh.polygons:
            idx = getattr(poly, "material_index", 0)
            area = getattr(poly, "area", 0.0)
            if idx in areas:
                areas[idx] += area
            elif len(areas) > 0:
                areas[0] += area
        return areas

    @classmethod
    def get_dominant_material_index(cls, areas: dict[int, float]) -> int:
        if not areas:
            return 0
        return max(areas.items(), key=lambda item: item[1])[0]

    @classmethod
    def is_material_protected(cls, mat: Any) -> bool:
        """Determines if a material is semantically protected (e.g. lights, decals, glass)."""
        if not mat:
            return False
        name = getattr(mat, "name", "").lower()
        if any(kw in name for kw in cls.PROTECTED_KEYWORDS):
            return True

        if hasattr(mat, "node_tree") and mat.node_tree:
            for node in mat.node_tree.nodes:
                ntype = getattr(node, "type", "")
                if ntype in ("EMISSION", "BSDF_GLASS", "BSDF_TRANSPARENT", "BSDF_TRANSLUCENT"):
                    return True
                if ntype == "BSDF_PRINCIPLED":
                    # Check emission strength
                    for sock in getattr(node, "inputs", []):
                        if sock.name == "Emission Strength" and getattr(sock, "default_value", 0.0) > 0.001:
                            return True
        return False

    @classmethod
    def consolidate_micro_materials(
        cls,
        obj: Any,
        area_threshold_pct: float = 0.5,
        protect_semantic_materials: bool = True,
    ) -> dict[str, Any]:
        """
        Reassigns surface regions occupying < area_threshold_pct of total surface area
        to the dominant material slot, preserving semantically protected shaders.
        """
        if not bpy or not bmesh or not obj or len(obj.material_slots) <= 1:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        areas = cls.calculate_material_areas(obj)
        total_area = sum(areas.values())
        if total_area < 1e-6:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        dominant_idx = cls.get_dominant_material_index(areas)
        reassigned_slots: set[int] = set()
        threshold_frac = max(0.0001, area_threshold_pct / 100.0)

        for slot_idx, area in areas.items():
            if slot_idx == dominant_idx:
                continue
            mat = obj.material_slots[slot_idx].material
            if protect_semantic_materials and cls.is_material_protected(mat):
                continue
            if (area / total_area) < threshold_frac:
                reassigned_slots.add(slot_idx)

        if not reassigned_slots:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        bm = bmesh.new()
        faces_reassigned = 0
        try:
            bm.from_mesh(obj.data)
            bm.faces.ensure_lookup_table()
            for face in bm.faces:
                if face.material_index in reassigned_slots:
                    face.material_index = dominant_idx
                    faces_reassigned += 1
            bm.to_mesh(obj.data)
        finally:
            bm.free()

        obj.data.update()
        return {"consolidated_slots": len(reassigned_slots), "faces_reassigned": faces_reassigned}

    @classmethod
    def merge_duplicate_materials_scene(cls) -> int:
        """
        Scans all scene materials, computes SHA-256 AST hashes via DeepMaterialHasher,
        and merges true duplicates into the canonical master material datablock.
        """
        if not bpy:
            return 0

        hash_to_master: dict[str, Any] = {}
        mat_remap: dict[Any, Any] = {}
        merged_count = 0

        for mat in bpy.data.materials:
            h = DeepMaterialHasher.hash_material(mat)
            if h in hash_to_master:
                master_mat = hash_to_master[h]
                if master_mat != mat:
                    mat_remap[mat] = master_mat
                    merged_count += 1
            else:
                hash_to_master[h] = mat

        if not mat_remap:
            return 0

        # Remap across all mesh objects
        for obj in bpy.data.objects:
            if getattr(obj, "type", "") == "MESH":
                for slot in getattr(obj, "material_slots", []):
                    if slot.material in mat_remap:
                        slot.material = mat_remap[slot.material]

        # Purge remapped duplicates
        for dup_mat in mat_remap.keys():
            try:
                bpy.data.materials.remove(dup_mat, do_unlink=True)
            except Exception as exc:
                logger.debug("Duplicate material remove exception: %s", exc)

        return merged_count

    @classmethod
    def purge_orphan_materials(cls) -> int:
        """Purges zero-user material datablocks from .blend file."""
        if not bpy:
            return 0
        orphans = [m for m in bpy.data.materials if getattr(m, "users", 0) == 0]
        for m in orphans:
            try:
                bpy.data.materials.remove(m, do_unlink=True)
            except Exception as exc:
                logger.debug("Orphan material remove exception: %s", exc)
        return len(orphans)

    @classmethod
    def clean_materials_full(
        cls,
        mesh_objs: list[Any],
        purge_unused_slots: bool = True,
        deduplicate_slots: bool = True,
        merge_duplicate_datablocks: bool = True,
        remove_orphan_nodes: bool = True,
        enable_micro_consolidation: bool = False,
        micro_area_pct: float = 0.5,
        repair_missing_textures: bool = False,
        purge_orphans_blendfile: bool = False,
    ) -> dict[str, Any]:
        """
        Executes unified material cleanup pipeline across selected mesh objects.
        """
        total_slots_removed = 0
        total_faces_remapped = 0
        total_consolidated_slots = 0
        total_repaired_textures = 0
        total_orphan_nodes = 0

        # Step 1: Missing texture audit and orphan node cleanup
        seen_materials: set[Any] = set()
        for obj in mesh_objs:
            for slot in getattr(obj, "material_slots", []):
                mat = slot.material
                if mat and mat not in seen_materials:
                    seen_materials.add(mat)
                    if repair_missing_textures:
                        total_repaired_textures += SemanticTextureAuditor.repair_missing_textures_in_material(mat)
                    if remove_orphan_nodes:
                        total_orphan_nodes += SemanticTextureAuditor.remove_orphan_texture_nodes(mat)

        # Step 2: Micro-material consolidation (Critical Opt-In)
        if enable_micro_consolidation:
            for obj in mesh_objs:
                res = cls.consolidate_micro_materials(obj, area_threshold_pct=micro_area_pct)
                total_consolidated_slots += res.get("consolidated_slots", 0)

        # Step 3: Headless Slot Compaction & Deduplication (Safe Default)
        for obj in mesh_objs:
            res = HeadlessSlotCompactor.compact_slots(
                obj,
                purge_empty=purge_unused_slots,
                deduplicate_identical=deduplicate_slots,
            )
            total_slots_removed += res.get("slots_removed", 0)
            total_faces_remapped += res.get("faces_remapped", 0)

        # Step 4: Scene-wide Duplicate Material Datablock Merge
        merged_datablocks = 0
        if merge_duplicate_datablocks:
            merged_datablocks = cls.merge_duplicate_materials_scene()

        # Step 5: Purge Orphan Materials from .blend (Critical Opt-In)
        purged_orphans = 0
        if purge_orphans_blendfile:
            purged_orphans = cls.purge_orphan_materials()

        return {
            "slots_removed": total_slots_removed,
            "faces_remapped": total_faces_remapped,
            "consolidated_slots": total_consolidated_slots,
            "repaired_textures": total_repaired_textures,
            "orphan_nodes_removed": total_orphan_nodes,
            "merged_datablocks": merged_datablocks,
            "purged_orphans": purged_orphans,
        }
