"""
Material Optimization, Cleanup & Slot Consolidation Subsystem for OmniMesh.
Features zero-bpy.ops headless slot compaction, cryptographic AST shader hashing,
semantic missing texture fallback routing, and guarded micro-material consolidation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any, cast

from .compat import ensure_unique_mesh_data, get_socket_default_value, set_socket_default_value
from .io_utils import resolve_blender_path

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import BlendData, Material, Node, Object
else:
    try:
        import bmesh
        import bpy
        from bpy.types import Material, Node, Object
    except ImportError:
        bpy = None
        bmesh = None
        Material = object
        Node = object
        Object = object
    BlendData = object


class DeepMaterialHasher:
    """
    Cryptographic AST-Style Shader Node Graph Hasher.
    Computes a deterministic SHA-256 hash of a material's functional shading pipeline.
    Ignores cosmetic UI layout coordinates, localized node labels, and window states.
    """

    @classmethod
    def hash_material(cls, mat: bpy.types.Material | None) -> str:
        if not mat or not mat.node_tree:
            diffuse = (
                cast("Iterable[float]", mat.diffuse_color)
                if (mat and mat.diffuse_color is not None)
                else (0.8, 0.8, 0.8, 1.0)
            )
            try:
                diff_list = [round(float(c), 4) for c in list(diffuse)[:4]]
            except (TypeError, IndexError, ValueError):
                diff_list = [0.8, 0.8, 0.8, 1.0]
            return hashlib.sha256(f"NON_NODES:{diff_list}".encode("utf-8")).hexdigest()

        nodes = mat.node_tree.nodes

        # Find active output material node
        output_node = None
        for n in nodes:
            if n.type == "OUTPUT_MATERIAL" and cast("bpy.types.ShaderNodeOutputMaterial", n).is_active_output:
                output_node = n
                break

        if not output_node:
            for n in nodes:
                if n.type == "OUTPUT_MATERIAL":
                    output_node = n
                    break

        if not output_node:
            return hashlib.sha256("EMPTY_OR_INVALID_OUTPUT".encode("utf-8")).hexdigest()

        # Traverse reachable nodes from output backwards
        visited_nodes: set[str] = set()
        queue: list[bpy.types.Node] = [output_node]
        canonical_nodes: list[dict[str, Any]] = []
        canonical_links: list[dict[str, Any]] = []

        while queue:
            curr = queue.pop(0)
            node_name = str(curr.name)
            if node_name in visited_nodes:
                continue
            visited_nodes.add(node_name)

            node_data: dict[str, Any] = {
                "type": str(curr.type),
            }

            # Capture node-specific internal properties
            for prop_key in ("operation", "blend_type", "color_space"):
                prop_val = getattr(curr, prop_key, None)
                if prop_val is not None:
                    node_data[prop_key] = str(prop_val)
            if curr.type == "TEX_IMAGE":
                curr_img = cast("bpy.types.ShaderNodeTexImage", curr).image
                if curr_img is not None:
                    img = curr_img
                    filepath = img.filepath
                    if filepath:
                        resolved_fp = resolve_blender_path(
                            filepath,
                            abspath_fn=bpy.path.abspath if bpy else None,
                            fallback_raw_on_unsaved=True,
                        )
                        if resolved_fp:
                            filepath = resolved_fp
                    node_data["image_filepath"] = filepath or img.name
                    sz = list(cast("Iterable[int]", img.size)) if img.size is not None else [0, 0]
                    node_data["image_size"] = [int(sz[0]), int(sz[1])]
                    if img.colorspace_settings:
                        node_data["image_colorspace"] = img.colorspace_settings.name

            # Capture unlinked input default values
            input_defaults: dict[str, Any] = {}
            for sock in curr.inputs:
                if not sock.is_linked:
                    val = get_socket_default_value(sock)
                    if isinstance(val, Iterable) and not isinstance(val, (str, bytes)):
                        try:
                            input_defaults[str(sock.name)] = [round(float(v), 5) for v in val]
                        except (ValueError, TypeError):
                            input_defaults[str(sock.name)] = str(val)
                    elif isinstance(val, (int, float)):
                        input_defaults[str(sock.name)] = round(float(val), 5)
                    elif isinstance(val, str):
                        input_defaults[str(sock.name)] = val
            node_data["input_defaults"] = input_defaults
            canonical_nodes.append(node_data)

            # Trace incoming links
            for sock in curr.inputs:
                for link in sock.links or ():
                    from_node = link.from_node
                    if not from_node:
                        continue
                    from_name = str(from_node.name)
                    canonical_links.append(
                        {
                            "from_type": str(from_node.type),
                            "from_socket": str(link.from_socket.name if link.from_socket else ""),
                            "to_type": str(curr.type),
                            "to_socket": str(sock.name),
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
            "use_backface_culling": bool(mat.use_backface_culling),
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
        obj: bpy.types.Object | None,
        purge_empty: bool = True,
        deduplicate_identical: bool = True,
    ) -> dict[str, int]:
        """
        Compacts material slots, removes unassigned/empty slots, deduplicates repeated material slots,
        and atomically remaps polygon material indices in-place.
        """
        if not obj or not obj.data:
            return {"slots_removed": 0, "faces_remapped": 0}
        ensure_unique_mesh_data(obj)
        mesh = cast("bpy.types.Mesh", obj.data)
        if mesh.polygons is None or obj.material_slots is None:
            return {"slots_removed": 0, "faces_remapped": 0}

        num_slots = len(obj.material_slots)
        if num_slots == 0:
            return {"slots_removed": 0, "faces_remapped": 0}

        # 1. Tally polygon material references
        used_indices: set[int] = set()
        for poly in mesh.polygons:
            idx = poly.material_index
            if 0 <= idx < num_slots:
                used_indices.add(idx)

        # 2. Build deterministic compaction & deduplication map
        new_materials: list[bpy.types.Material | None] = []
        mat_to_new_index: dict[bpy.types.Material, int] = {}
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

        # 3. Remap mesh polygon indices in-place (vectorized numpy with fallback)
        faces_remapped = 0
        poly_count = len(mesh.polygons)
        if poly_count > 0:
            try:
                import numpy as np

                orig_indices = np.empty(poly_count, dtype=np.int32)
                mesh.polygons.foreach_get("material_index", orig_indices)
                remapped_indices = orig_indices.copy()
                for old_idx, new_idx in slot_remap.items():
                    if old_idx != new_idx:
                        remapped_indices[orig_indices == old_idx] = new_idx
                faces_remapped = int(np.count_nonzero(remapped_indices != orig_indices))
                if faces_remapped > 0:
                    mesh.polygons.foreach_set("material_index", remapped_indices)
            except (AttributeError, ImportError, TypeError):
                for poly in mesh.polygons:
                    old_i = poly.material_index
                    new_i = slot_remap.get(old_i, 0)
                    if new_i != old_i:
                        poly.material_index = new_i
                        faces_remapped += 1

        # 4. In-place update of material slots and pop trailing excess
        if obj.material_slots is not None and mesh.materials is not None:
            for i, mat in enumerate(new_materials):
                if i < len(obj.material_slots):
                    obj.material_slots[i].material = mat
                else:
                    mesh.materials.append(mat)
            while len(mesh.materials) > len(new_materials):
                idx_to_pop = len(mesh.materials) - 1
                try:
                    # Blender IDMaterials RNA collection accepts index kwarg: pop(index=idx)
                    mesh.materials.pop(index=idx_to_pop)
                except TypeError:
                    # Standard Python list accepts positional argument: pop(idx)
                    mesh.materials.pop(idx_to_pop)  # type: ignore[call-arg]
        elif mesh.materials is not None:
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
    def is_image_valid(cls, img: bpy.types.Image | None) -> bool:
        if not img:
            return False
        if img.packed_file is not None:
            return True
        if img.has_data:
            return True
        if img.source == "GENERATED":
            return True
        filepath = img.filepath
        if not filepath:
            return False
        abs_path = resolve_blender_path(
            filepath,
            abspath_fn=bpy.path.abspath if bpy else None,
            fallback_raw_on_unsaved=False,
        )
        if not abs_path:
            return False
        return os.path.exists(abs_path)

    @classmethod
    def repair_missing_textures_in_material(cls, mat: bpy.types.Material | None) -> int:
        """
        Audits image texture nodes in the material. If an image is broken or missing,
        replaces it with safe socket-specific defaults without corrupting normal vectors.
        """
        if not mat or not mat.node_tree:
            return 0

        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        repaired_nodes = 0

        for node in list(nodes):
            if node.type == "TEX_IMAGE":
                img = cast("bpy.types.ShaderNodeTexImage", node).image
                if not cls.is_image_valid(img):
                    # Trace downstream connections (including through demux/mix/math nodes)
                    def resolve_downstream_targets(
                        start_node: bpy.types.Node, visited: set[int]
                    ) -> list[tuple[bpy.types.NodeLink, bpy.types.NodeSocket | None, bpy.types.Node | None]]:
                        resolved = []
                        for out_s in start_node.outputs:
                            out_links = out_s.links
                            if not out_links:
                                continue
                            for lnk in list(out_links):
                                t_node = lnk.to_node
                                t_sock = lnk.to_socket
                                n_type = t_node.type if t_node else ""
                                if t_node is not None and n_type in (
                                    "SEPARATE_COLOR",
                                    "COMBINE_COLOR",
                                    "MIX",
                                    "MATH",
                                    "NORMAL_MAP",
                                ):
                                    if id(t_node) not in visited:
                                        visited.add(id(t_node))
                                        resolved.extend(resolve_downstream_targets(t_node, visited))
                                resolved.append((lnk, t_sock, t_node))
                        return resolved

                    downstream = resolve_downstream_targets(node, {id(node)})
                    removed_link_ids: set[int] = set()
                    for link, target_sock, target_node in downstream:
                        sock_name = str(target_sock.name if target_sock else "").lower()
                        node_type = target_node.type if target_node else ""

                        if "normal" not in sock_name and node_type != "NORMAL_MAP" and target_sock is not None:
                            if "roughness" in sock_name:
                                set_socket_default_value(target_sock, 0.5)
                            elif "metallic" in sock_name:
                                set_socket_default_value(target_sock, 0.0)
                            elif "base color" in sock_name or "color" in sock_name:
                                set_socket_default_value(target_sock, (0.8, 0.8, 0.8, 1.0))

                        link_id = id(link)
                        if link_id not in removed_link_ids and any(existing == link for existing in links):
                            links.remove(link)
                            removed_link_ids.add(link_id)

                    nodes.remove(node)
                    repaired_nodes += 1

        return repaired_nodes

    @classmethod
    def remove_orphan_texture_nodes(cls, mat: bpy.types.Material | None) -> int:
        """Removes dead/disconnected texture image nodes (0 outputs connected)."""
        if not mat or not mat.node_tree:
            return 0
        nodes = mat.node_tree.nodes
        removed = 0
        for node in list(nodes):
            if node.type == "TEX_IMAGE":
                is_used = any(
                    (len(cast("Any", out.links)) > 0) if out.links is not None else bool(out.is_linked)
                    for out in node.outputs
                )
                if not is_used:
                    nodes.remove(node)
                    removed += 1
        return removed


@dataclass(slots=True)
class MaterialCleanOptions:
    """Configuration options for the unified material optimization pipeline."""

    purge_unused_slots: bool = True
    deduplicate_slots: bool = True
    merge_duplicate_datablocks: bool = True
    remove_orphan_nodes: bool = True
    enable_micro_consolidation: bool = False
    micro_area_pct: float = 0.5
    repair_missing_textures: bool = False
    purge_orphans_blendfile: bool = False


class MaterialOptimizer:
    """
    Unified Material Optimization, Cleanup and Consolidation Engine.
    """

    PROTECTED_KEYWORDS = ("emissive", "emission", "glass", "decal", "light", "eye", "lamp")

    @classmethod
    def calculate_material_areas(cls, obj: bpy.types.Object | None) -> dict[int, float]:
        """Calculates cumulative surface area per material slot index, scaled by matrix_world if available."""
        if not obj or not obj.data:
            return {}
        mesh = cast("bpy.types.Mesh", obj.data)
        if mesh.polygons is None or obj.material_slots is None:
            return {}

        num_slots = len(obj.material_slots)
        if num_slots == 0:
            return {}

        # Compute surface area scale factor from matrix_world if present
        area_scale = 1.0
        if obj.matrix_world is not None:
            try:
                scale = obj.matrix_world.to_scale()
                area_scale = abs(float(scale.x) * float(scale.y) * float(scale.z)) ** (2.0 / 3.0)
            except (ValueError, AttributeError, TypeError, ReferenceError):
                area_scale = 1.0

        areas: dict[int, float] = dict.fromkeys(range(num_slots), 0.0)
        for poly in mesh.polygons:
            idx = poly.material_index
            area = poly.area * area_scale
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
    def is_material_protected(cls, mat: bpy.types.Material | None) -> bool:
        """Determines if a material is semantically protected (e.g. lights, decals, glass)."""
        if not mat:
            return False
        name = mat.name.lower() if mat.name else ""
        if any(kw in name for kw in cls.PROTECTED_KEYWORDS):
            return True

        if mat.node_tree:
            nodes = mat.node_tree.nodes or []
            for node in nodes:
                ntype = node.type
                if ntype in ("EMISSION", "BSDF_GLASS", "BSDF_TRANSPARENT", "BSDF_TRANSLUCENT"):
                    return True
                if ntype == "BSDF_PRINCIPLED":
                    # Check emission strength
                    for sock in node.inputs or ():
                        val = get_socket_default_value(sock)
                        if sock.name == "Emission Strength" and isinstance(val, (int, float)) and val > 0.001:
                            return True
        return False

    @classmethod
    def consolidate_micro_materials(
        cls,
        obj: bpy.types.Object | None,
        area_threshold_pct: float = 0.5,
        protect_semantic_materials: bool = True,
        area_crit: float = 0.0,
        *,
        preserve_slot_indexing: bool = True,
    ) -> dict[str, Any]:
        """
        Reassigns surface regions occupying < area_threshold_pct of total surface area
        (or absolute area < area_crit in m²) to the dominant material slot,
        preserving semantically protected shaders.
        """
        if not bpy or not bmesh or not obj or not obj.material_slots or len(obj.material_slots) <= 1:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        areas = cls.calculate_material_areas(obj)
        total_area = sum(areas.values())
        if total_area < 1e-6:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        # Select dominant material excluding protected materials when protection is enabled
        candidate_areas = {}
        for slot_idx, area in areas.items():
            mat = obj.material_slots[slot_idx].material
            if protect_semantic_materials and cls.is_material_protected(mat):
                continue
            candidate_areas[slot_idx] = area

        if not candidate_areas:
            # All materials on mesh are protected; do not consolidate
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        dominant_idx = max(candidate_areas.items(), key=lambda item: item[1])[0]
        reassigned_slots: set[int] = set()

        # Handle absolute area threshold (area_crit) if provided
        if area_crit > 0.0:
            effective_threshold_frac = max(0.0001, area_crit / total_area)
        else:
            effective_threshold_frac = max(0.0001, area_threshold_pct / 100.0)

        for slot_idx, area in areas.items():
            if slot_idx == dominant_idx:
                continue
            mat = obj.material_slots[slot_idx].material
            if protect_semantic_materials and cls.is_material_protected(mat):
                continue
            if (area / total_area) < effective_threshold_frac:
                reassigned_slots.add(slot_idx)

        if not reassigned_slots:
            return {"consolidated_slots": 0, "faces_reassigned": 0}

        ensure_unique_mesh_data(obj)
        mesh_data = cast("bpy.types.Mesh", obj.data)
        bm = bmesh.new()
        faces_reassigned = 0
        try:
            bm.from_mesh(mesh_data)
            bm.faces.ensure_lookup_table()
            for face in bm.faces:
                if face.material_index in reassigned_slots:
                    face.material_index = dominant_idx
                    faces_reassigned += 1
            bm.to_mesh(mesh_data)
        finally:
            bm.free()

        mesh_data.update()
        if not preserve_slot_indexing:
            HeadlessSlotCompactor.compact_slots(obj, purge_empty=True, deduplicate_identical=False)
        return {"consolidated_slots": len(reassigned_slots), "faces_reassigned": faces_reassigned}

    @classmethod
    def purge_unused_materials(cls, obj: bpy.types.Object | None) -> dict[str, int]:
        """
        Compacts and removes unassigned/empty material slots from the target object.
        """
        return HeadlessSlotCompactor.compact_slots(obj, purge_empty=True, deduplicate_identical=False)

    @classmethod
    def merge_duplicate_materials_scene(cls, *, blend_data: BlendData) -> int:
        """
        Scans all scene materials, computes SHA-256 AST hashes via DeepMaterialHasher,
        and merges true duplicates into the canonical master material datablock.
        """
        bdata_mats = blend_data.materials if blend_data else None
        bdata_objs = blend_data.objects if blend_data else None
        if not bdata_mats:
            return 0

        hash_to_materials: dict[str, list[Any]] = {}
        for mat in bdata_mats:
            h = DeepMaterialHasher.hash_material(mat)
            hash_to_materials.setdefault(h, []).append(mat)

        mat_remap: dict[bpy.types.Material, bpy.types.Material] = {}
        merged_count = 0

        for cluster in hash_to_materials.values():
            if len(cluster) <= 1:
                continue
            # Prefer root name without dot suffix, then shorter name, then alphabetical
            cluster.sort(key=lambda m: ("." in m.name, len(m.name), m.name))
            master_mat = cluster[0]
            for dup_mat in cluster[1:]:
                mat_remap[dup_mat] = master_mat
                merged_count += 1

        if not mat_remap:
            return 0

        # Remap across all mesh objects
        for obj in bdata_objs or []:
            if obj.type == "MESH":
                for slot in obj.material_slots:
                    if slot.material in mat_remap:
                        slot.material = mat_remap[slot.material]

        # Purge remapped duplicates
        for dup_mat in mat_remap.keys():
            try:
                bdata_mats.remove(dup_mat, do_unlink=True)
            except (RuntimeError, ReferenceError, AttributeError) as exc:
                logger.debug("Duplicate material remove exception: %s", exc)

        return merged_count

    @classmethod
    def purge_orphan_materials(cls, *, blend_data: BlendData) -> int:
        """Purges zero-user material datablocks from .blend file."""
        bdata_mats = blend_data.materials if blend_data else None
        if not bdata_mats:
            return 0
        orphans = [m for m in bdata_mats if m.users == 0]
        for m in orphans:
            try:
                bdata_mats.remove(m, do_unlink=True)
            except (RuntimeError, ReferenceError, AttributeError) as exc:
                logger.debug("Orphan material remove exception: %s", exc)
        return len(orphans)

    @classmethod
    def clean_orphan_shader_nodes(
        cls,
        mat: bpy.types.Material | None = None,
        *,
        blend_data: BlendData,
    ) -> int:
        """Removes disconnected or orphan texture nodes from target material or all scene materials."""
        if mat is not None:
            return SemanticTextureAuditor.remove_orphan_texture_nodes(mat)
        bdata_mats = blend_data.materials if blend_data else None
        if not bdata_mats:
            return 0
        total = 0
        for m in bdata_mats:
            total += SemanticTextureAuditor.remove_orphan_texture_nodes(m)
        return total

    @classmethod
    def clean_materials_full(
        cls,
        mesh_objs: list[bpy.types.Object],
        options: MaterialCleanOptions | None = None,
        *,
        blend_data: BlendData,
    ) -> dict[str, Any]:
        """
        Executes unified material cleanup pipeline across selected mesh objects.
        """
        opts = options or MaterialCleanOptions()
        total_slots_removed = 0
        total_faces_remapped = 0
        total_consolidated_slots = 0
        total_repaired_textures = 0
        total_orphan_nodes = 0

        # Step 1: Missing texture audit and orphan node cleanup
        seen_materials: set[bpy.types.Material] = set()
        for obj in mesh_objs:
            for slot in obj.material_slots:
                mat = slot.material
                if mat and mat not in seen_materials:
                    seen_materials.add(mat)
                    if opts.repair_missing_textures:
                        total_repaired_textures += SemanticTextureAuditor.repair_missing_textures_in_material(mat)
                    if opts.remove_orphan_nodes:
                        total_orphan_nodes += SemanticTextureAuditor.remove_orphan_texture_nodes(mat)

        # Step 2: Micro-material consolidation (Critical Opt-In)
        if opts.enable_micro_consolidation:
            for obj in mesh_objs:
                res = cls.consolidate_micro_materials(obj, area_threshold_pct=opts.micro_area_pct)
                total_consolidated_slots += res.get("consolidated_slots", 0)

        # Step 3: Headless Slot Compaction & Deduplication (Safe Default)
        for obj in mesh_objs:
            res = HeadlessSlotCompactor.compact_slots(
                obj,
                purge_empty=opts.purge_unused_slots,
                deduplicate_identical=opts.deduplicate_slots,
            )
            total_slots_removed += res.get("slots_removed", 0)
            total_faces_remapped += res.get("faces_remapped", 0)

        # Step 4: Scene-wide Duplicate Material Datablock Merge
        merged_datablocks = 0
        if opts.merge_duplicate_datablocks:
            merged_datablocks = cls.merge_duplicate_materials_scene(blend_data=blend_data)

        # Step 5: Purge Orphan Materials from .blend (Critical Opt-In)
        purged_orphans = 0
        if opts.purge_orphans_blendfile:
            purged_orphans = cls.purge_orphan_materials(blend_data=blend_data)

        return {
            "slots_removed": total_slots_removed,
            "faces_remapped": total_faces_remapped,
            "consolidated_slots": total_consolidated_slots,
            "repaired_textures": total_repaired_textures,
            "orphan_nodes_removed": total_orphan_nodes,
            "merged_datablocks": merged_datablocks,
            "purged_orphans": purged_orphans,
        }
