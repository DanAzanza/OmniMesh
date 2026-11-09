"""
OmniMesh PBR Texture Resolver & Material Inspection Engine.
Provides LOD0-scoped shader node tree traversal, semantic socket tracing,
preset-based pattern matching (AssetName_MaterialName_TextureType_UDIM),
and automatic relinking of broken or external texture paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Sequence, cast

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData, Material, Node, NodeSocket, NodeTree, Object, ShaderNodeTexImage
else:
    try:
        import bpy
        from bpy.types import Material, Node, NodeSocket, NodeTree, Object, ShaderNodeTexImage
    except ImportError:
        bpy = None
        BlendData = object
        Material = object
        Node = object
        NodeSocket = object
        NodeTree = object
        Object = object
        ShaderNodeTexImage = object

from .texture_relinker import ProjectTextureRelinker

logger = logging.getLogger(__name__)

# Map semantic map types to candidate filename tokens
SEMANTIC_MAP_TOKENS: dict[str, tuple[str, ...]] = {
    "NORMAL": ("norm", "normal", "nrm"),
    "ALBEDO": ("albd", "albedo", "basecolor", "base_color", "diffuse", "col", "color"),
    "COMP": ("comp", "orm", "arm", "occlusionroughnessmetallic", "mra", "packed"),
    "ROUGHNESS": ("rough", "roughness", "rgh"),
    "METALLIC": ("metal", "metallic", "met"),
    "OCCLUSION": ("ao", "ambientocclusion", "occ", "occlusion"),
    "EMISSIVE": ("emis", "emissive", "emission"),
    "HEIGHT": ("height", "disp", "displacement"),
    "ALPHA": ("alpha", "mask", "opacity"),
}


@dataclass(frozen=True)
class UnresolvedTexture:
    """Descriptor for a texture node that could not be resolved against project files."""

    material_name: str
    node_name: str
    expected_type: str
    original_filepath: str


@dataclass(frozen=True)
class TextureResolutionSummary:
    """Summary of PBR texture resolution and verification across materials."""

    total_nodes_checked: int = 0
    already_valid: int = 0
    relinked: int = 0
    unresolved: tuple[UnresolvedTexture, ...] = ()
    relinked_pairs: tuple[tuple[str, str], ...] = ()

    @property
    def has_errors(self) -> bool:
        return len(self.unresolved) > 0


class PBRTextureResolver:
    """Inspects material shader trees and resolves texture files matching preset naming conventions."""

    @staticmethod
    def sanitize_material_name(mat_name: str) -> str:
        """Strips common engine prefixes (M_, MAT_, MI_) and Blender duplicate suffixes (.001)."""
        clean = re.sub(r"\.\d{3,}$", "", mat_name.strip())
        for prefix in ("M_", "MAT_", "MI_", "m_", "mat_", "mi_"):
            if clean.startswith(prefix) and len(clean) > len(prefix):
                clean = clean[len(prefix) :]
                break
        return clean.strip("_")

    @staticmethod
    def deduce_texture_type_from_sockets(node: bpy.types.Node) -> str:
        """Traces downstream node sockets to infer the semantic texture map type."""
        for out_sock in node.outputs if node and node.outputs else ():
            for link in out_sock.links if out_sock and out_sock.links else ():
                to_sock = link.to_socket
                sock_name = to_sock.name.lower() if to_sock else ""
                to_node = link.to_node
                node_type = to_node.type if to_node else ""

                if "base color" in sock_name or "color" in sock_name:
                    return "ALBEDO"
                if "normal" in sock_name or node_type == "NORMAL_MAP":
                    return "NORMAL"
                if "roughness" in sock_name or "metallic" in sock_name:
                    return "COMP"
                if "emission" in sock_name or "emissive" in sock_name:
                    return "EMISSIVE"
                if "occlusion" in sock_name or "ao" in sock_name:
                    return "OCCLUSION"
        return "UNKNOWN"

    @classmethod
    def deduce_texture_type(cls, node: bpy.types.Node, original_filepath: str) -> str:
        """Determines semantic texture type from filename, node label/name, or socket links."""
        # 1. From original filename or node label/name
        fname = (os.path.basename(original_filepath) or node.label or node.name or "").lower()
        fname_tokens = set(re.split(r"[\s_\-.]+", fname))
        for sem_type, tokens in SEMANTIC_MAP_TOKENS.items():
            for tok in tokens:
                if tok in fname_tokens or any(p.startswith(tok) or p.endswith(tok) for p in fname_tokens):
                    return sem_type

        # 2. Downstream socket tracing fallback
        return cls.deduce_texture_type_from_sockets(node)

    @staticmethod
    def extract_all_texture_nodes(
        node_tree: bpy.types.NodeTree | None,
        visited_trees: set[int] | None = None,
    ) -> list[bpy.types.ShaderNodeTexImage]:
        """Recursively traverses a node tree and any nested node groups to find all image nodes."""
        if not node_tree:
            return []

        if visited_trees is None:
            visited_trees = set()

        tree_id = id(node_tree)
        if tree_id in visited_trees:
            return []
        visited_trees.add(tree_id)

        results: list[bpy.types.ShaderNodeTexImage] = []
        for node in node_tree.nodes if node_tree and node_tree.nodes else ():
            if node.type == "TEX_IMAGE":
                results.append(node)  # type: ignore[arg-type]
            elif node.type == "GROUP":
                nested_tree = cast("bpy.types.ShaderNodeGroup", node).node_tree
                if nested_tree:
                    results.extend(PBRTextureResolver.extract_all_texture_nodes(nested_tree, visited_trees))

        return results

    @staticmethod
    def _matches_semantic_map_id(texture_type: str, map_id: str) -> bool:
        """Checks if a preset map ID corresponds to a semantic texture type."""
        m_id = map_id.upper()
        if m_id == texture_type:
            return True
        if texture_type == "ALBEDO":
            return m_id in ("ALBEDO", "BASE_COLOR", "BASE_MAP", "DIFFUSE", "COLOR")
        if texture_type == "NORMAL":
            return "NORM" in m_id or "BUMP" in m_id
        if texture_type == "COMP":
            return m_id in ("COMP", "ORM", "ARM", "MASKMAP", "METALLIC", "ROUGHNESS")
        if texture_type == "EMISSIVE":
            return "EMIS" in m_id
        if texture_type == "OCCLUSION":
            return "AO" in m_id or "OCCLUSION" in m_id
        if texture_type == "ROUGHNESS":
            return "ROUGH" in m_id
        if texture_type == "METALLIC":
            return "METAL" in m_id
        if texture_type == "HEIGHT":
            return "HEIGHT" in m_id or "DISP" in m_id
        if texture_type == "ALPHA":
            return "ALPHA" in m_id or "OPAC" in m_id
        return False

    @classmethod
    def find_texture_by_preset_pattern(
        cls,
        asset_name: str,
        material_name: str,
        texture_type: str,
        texture_index: dict[str, list[Path]],
        preset: dict[str, object] | None = None,
    ) -> Path | None:
        """Finds candidate file matching AssetName_MaterialName_TextureType_UDIM pattern in the index."""
        clean_mat = cls.sanitize_material_name(material_name).lower()
        clean_asset = asset_name.strip().lower()
        tokens = set(SEMANTIC_MAP_TOKENS.get(texture_type, ()))

        # Also pull any custom suffixes from active preset
        maps_raw = preset.get("maps") if isinstance(preset, dict) else None
        if isinstance(maps_raw, list):
            for m in maps_raw:
                if not isinstance(m, dict):
                    continue
                m_id = str(m.get("id", ""))
                if not cls._matches_semantic_map_id(texture_type, m_id):
                    continue
                suffixes_raw = m.get("suffixes")
                if not isinstance(suffixes_raw, (list, tuple)):
                    continue
                for s in suffixes_raw:
                    if not isinstance(s, str):
                        continue
                    s_tok = re.sub(r"^[._\-]+", "", s).lower()
                    if s_tok:
                        tokens.add(s_tok)

        fallback_match: Path | None = None

        # Search index keys for matching patterns
        for key, paths in texture_index.items():
            if not paths:
                continue

            # Must contain material name
            if clean_mat not in key:
                continue

            # Must contain at least one recognized token for this texture type
            if tokens and not any(tok in key for tok in tokens):
                continue

            # If asset name is specified, prioritize matches containing asset name
            if clean_asset and clean_asset in key:
                return paths[0]

            if fallback_match is None:
                fallback_match = paths[0]

        return fallback_match

    @classmethod
    def resolve_material_textures(
        cls,
        materials: Sequence[bpy.types.Material],
        search_roots: Sequence[Path | str],
        asset_name: str = "",
        preset: dict[str, object] | None = None,
        blend_filepath: str | None = None,
        make_relative: bool = True,
        max_depth: int = 5,
        *,
        blend_data: BlendData,
    ) -> TextureResolutionSummary:
        """Audits all ShaderNodeTexImage nodes in materials and resolves missing textures from search roots."""
        if not materials or not search_roots:
            return TextureResolutionSummary()

        # Build single-pass texture index
        texture_index = ProjectTextureRelinker.build_texture_index(search_roots, max_depth=max_depth)

        total_checked = 0
        already_valid = 0
        relinked_count = 0
        unresolved_list: list[UnresolvedTexture] = []
        relinked_pairs: list[tuple[str, str]] = []

        # Deduplicate materials
        unique_materials: list[bpy.types.Material] = []
        seen_mats: set[str] = set()
        for mat in materials:
            if not mat:
                continue
            mat_name = mat.name
            if mat_name not in seen_mats:
                seen_mats.add(mat_name)
                unique_materials.append(mat)

        for mat in unique_materials:
            if not mat.use_nodes or not mat.node_tree:
                continue

            mat_name = mat.name or "Unnamed_Material"
            tex_nodes = cls.extract_all_texture_nodes(mat.node_tree)

            for node in tex_nodes:
                img = node.image

                # 1. Path already valid?
                if img is not None and ProjectTextureRelinker.is_image_valid(
                    img, blend_filepath, blend_data=blend_data
                ):
                    total_checked += 1
                    already_valid += 1
                    continue

                raw_path = img.filepath if img else ""
                fname = os.path.basename(raw_path) if raw_path else (img.name if img else "")
                sem_type = cls.deduce_texture_type(node, raw_path)

                matched_path: Path | None = None

                # 2. Try matching by exact filename or extension alias (.dds <-> .png)
                if fname:
                    matched_path = ProjectTextureRelinker.find_matching_file(fname, raw_path, texture_index)

                # 3. Try matching by Preset Pattern: AssetName_MaterialName_TextureType_UDIM
                if matched_path is None:
                    matched_path = cls.find_texture_by_preset_pattern(
                        asset_name=asset_name,
                        material_name=mat_name,
                        texture_type=sem_type,
                        texture_index=texture_index,
                        preset=preset,
                    )

                if matched_path is not None:
                    total_checked += 1
                    # Apply resolved texture
                    new_path_str = (
                        ProjectTextureRelinker.make_relative_path(matched_path, blend_filepath)
                        if make_relative
                        else str(matched_path)
                    )

                    try:
                        if img is None and bpy:
                            # Load newly discovered image via injected blend_data
                            bdata_imgs = blend_data.images if blend_data else None
                            if bdata_imgs is not None:
                                img = bdata_imgs.load(str(matched_path))
                                node.image = img
                        elif img is not None:
                            img.filepath = new_path_str
                            try:
                                img.reload()
                            except (RuntimeError, AttributeError) as exc:
                                logger.warning("Could not reload image buffer '%s': %s", img.name, exc)

                        relinked_count += 1
                        node_name = node.name or "TexImage"
                        relinked_pairs.append((f"{mat_name}::{node_name}", new_path_str))
                    except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
                        logger.warning("Failed assigning image to material '%s' node: %s", mat_name, exc)
                        unresolved_list.append(
                            UnresolvedTexture(
                                material_name=mat_name,
                                node_name=node.name or "TexImage",
                                expected_type=sem_type,
                                original_filepath=raw_path,
                            )
                        )
                else:
                    # Only flag as unresolved if the node actually had an assigned image or filepath.
                    # Unassigned optional template slots (e.g. MSFS detail/emissive slots with image=None)
                    # are valid in PBR shaders and must not trigger false-positive missing texture errors.
                    if img is not None:
                        total_checked += 1
                        unresolved_list.append(
                            UnresolvedTexture(
                                material_name=mat_name,
                                node_name=node.name or "TexImage",
                                expected_type=sem_type,
                                original_filepath=raw_path,
                            )
                        )

        return TextureResolutionSummary(
            total_nodes_checked=total_checked,
            already_valid=already_valid,
            relinked=relinked_count,
            unresolved=tuple(unresolved_list),
            relinked_pairs=tuple(relinked_pairs),
        )

    @staticmethod
    def extract_unique_materials_from_objects(
        objects: Sequence[bpy.types.Object],
    ) -> list[bpy.types.Material]:
        """Collects unique, valid materials assigned to material slots across objects."""
        mats: list[bpy.types.Material] = []
        seen: set[str] = set()

        for obj in objects:
            if not obj or obj.type != "MESH":
                continue
            for slot in obj.material_slots if obj and obj.material_slots else ():
                mat = slot.material
                if mat is not None:
                    mat_name = mat.name
                    if mat_name and mat_name not in seen:
                        seen.add(mat_name)
                        mats.append(mat)
        return mats
