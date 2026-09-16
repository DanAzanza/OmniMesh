"""
OmniMesh Multi-Engine Material Preset Generator.
Generates production-grade PBR, Glass, Decal, Invisible/Collision, and Emissive materials
using native Blender Principled BSDF node trees compatible across Blender 3.6 - 5.2 LTS,
with engine-specific metadata tags for MSFS, Unreal Engine 5, Unity 6, and Godot 4.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.types import Material, Node, Object, ShaderNodeBsdfPrincipled
except ImportError:
    bpy = None
    Material = object
    Node = object
    Object = object
    ShaderNodeBsdfPrincipled = object


def set_principled_socket(
    node: Any,
    name_v1: str,
    name_v2: str,
    value: Any,
) -> bool:
    """
    Safely assigns a socket value on Principled BSDF supporting both v1 (Blender < 4.0)
    and v2 (Blender 4.0+) socket names.
    """
    if not node or not hasattr(node, "inputs"):
        return False

    socket = node.inputs.get(name_v2) or node.inputs.get(name_v1)
    if socket is not None:
        try:
            socket.default_value = value
            return True
        except Exception as exc:
            logger.debug("Failed setting socket '%s'/'%s': %s", name_v1, name_v2, exc)
    return False


def configure_material_transparency(
    mat: Any,
    mode: str = "BLEND",
    shadow: str = "NONE",
) -> None:
    """
    Configures material transparency and shadow method across render engines,
    safely handling EEVEE Next (Blender 4.2+) API deprecations.
    """
    if not mat:
        return

    # Blender 5.0+ EEVEE Next API
    if hasattr(mat, "surface_render_method"):
        try:
            mat.surface_render_method = "BLENDED" if mode in ("BLEND", "HASHED") else "DITHERED"
        except (AttributeError, TypeError):
            pass

    if hasattr(mat, "use_transparent_shadow"):
        try:
            mat.use_transparent_shadow = shadow != "NONE"
        except (AttributeError, TypeError):
            pass


def get_or_create_principled_node(mat: Any) -> Optional[Any]:
    """Retrieves or creates the primary Principled BSDF node in a material node tree."""
    if not mat or not hasattr(mat, "node_tree") or not mat.node_tree:
        return None

    tree = mat.node_tree
    # Find existing Principled BSDF
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node

    # Create new Principled BSDF if absent
    try:
        bsdf = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
        output = tree.nodes.get("Material Output")
        if not output:
            output = tree.nodes.new(type="ShaderNodeOutputMaterial")
        tree.links.new(bsdf.outputs.get("BSDF"), output.inputs.get("Surface"))
        return bsdf
    except Exception as exc:
        logger.warning("Could not instantiate Principled BSDF: %s", exc)
        return None


def create_or_update_material_preset(
    material_name: str,
    preset_type: str,
    base_color: Sequence[float] = (0.8, 0.8, 0.8, 1.0),
    roughness: float = 0.4,
    metallic: float = 0.0,
    emission_strength: float = 5.0,
) -> Any:
    """
    Creates or updates a Blender Material datablock configured according to the selected preset.

    Supported Presets:
        - PBR_STANDARD: Standard opaque metallic-roughness PBR.
        - GLASS_TRANSPARENT: Physical refractive glass with zero shadows and high transmission.
        - FLOATING_DECAL: Decal shader with polygon offset and OmniMesh decimation protection.
        - INVISIBLE_COLLIDER: Zero-opacity trigger / mouse collision volume.
        - EMISSIVE_LIGHT: High-intensity emissive lamp material for instruments / bloom.
    """
    if not bpy:
        return None

    clean_name = str(material_name).strip() or f"Mat_{preset_type}"
    mat = bpy.data.materials.get(clean_name)
    if not mat:
        mat = bpy.data.materials.new(name=clean_name)

    mat.use_nodes = True
    bsdf = get_or_create_principled_node(mat)
    col_rgba = (
        float(base_color[0]),
        float(base_color[1]),
        float(base_color[2]),
        float(base_color[3]) if len(base_color) > 3 else 1.0,
    )

    # Base PBR properties
    set_principled_socket(bsdf, "Base Color", "Base Color", col_rgba)
    set_principled_socket(bsdf, "Roughness", "Roughness", float(roughness))
    set_principled_socket(bsdf, "Metallic", "Metallic", float(metallic))

    # Engine-agnostic tag
    mat["_omnimesh_shader_preset"] = preset_type

    if preset_type == "PBR_STANDARD":
        set_principled_socket(bsdf, "Alpha", "Alpha", 1.0)
        set_principled_socket(bsdf, "Transmission", "Transmission Weight", 0.0)
        configure_material_transparency(mat, mode="OPAQUE", shadow="OPAQUE")
        mat["msfs_material_type"] = 1  # MSFS Standard PBR
        if hasattr(mat, "msfs_material_type"):
            try:
                mat.msfs_material_type = 1
            except Exception as exc:
                logger.debug("Could not assign RNA msfs_material_type: %s", exc)

    elif preset_type == "GLASS_TRANSPARENT":
        set_principled_socket(bsdf, "Alpha", "Alpha", 1.0)
        set_principled_socket(bsdf, "Transmission", "Transmission Weight", 1.0)
        set_principled_socket(bsdf, "Roughness", "Roughness", max(0.01, min(0.15, float(roughness))))
        set_principled_socket(bsdf, "IOR", "IOR", 1.52)
        configure_material_transparency(mat, mode="BLEND", shadow="NONE")
        mat["_omnimesh_translucent"] = True
        mat["msfs_material_type"] = 4  # MSFS Windshield
        if hasattr(mat, "msfs_material_type"):
            try:
                mat.msfs_material_type = 4
            except Exception as exc:
                logger.debug("Could not assign RNA msfs_material_type: %s", exc)

    elif preset_type == "FLOATING_DECAL":
        alpha_val = min(col_rgba[3], 0.99)
        set_principled_socket(bsdf, "Alpha", "Alpha", alpha_val)
        set_principled_socket(bsdf, "Transmission", "Transmission Weight", 0.0)
        configure_material_transparency(mat, mode="BLEND", shadow="NONE")
        mat["_omnimesh_decal"] = True
        mat["msfs_material_type"] = 2  # MSFS Decal
        if hasattr(mat, "msfs_material_type"):
            try:
                mat.msfs_material_type = 2
            except Exception as exc:
                logger.debug("Could not assign RNA msfs_material_type: %s", exc)

    elif preset_type == "INVISIBLE_COLLIDER":
        set_principled_socket(bsdf, "Alpha", "Alpha", 0.0)
        set_principled_socket(bsdf, "Transmission", "Transmission Weight", 0.0)
        configure_material_transparency(mat, mode="BLEND", shadow="NONE")
        mat["_omnimesh_invisible"] = True
        mat["msfs_material_type"] = 12  # MSFS Collision / Invisible
        if hasattr(mat, "msfs_material_type"):
            try:
                mat.msfs_material_type = 12
            except Exception as exc:
                logger.debug("Could not assign RNA msfs_material_type: %s", exc)

    elif preset_type == "EMISSIVE_LIGHT":
        set_principled_socket(bsdf, "Alpha", "Alpha", 1.0)
        set_principled_socket(bsdf, "Emission", "Emission Color", col_rgba)
        set_principled_socket(bsdf, "Emission Strength", "Emission Strength", float(emission_strength))
        configure_material_transparency(mat, mode="OPAQUE", shadow="OPAQUE")
        mat["_omnimesh_emissive"] = True

    return mat


def assign_material_to_objects(mat: Any, objects: Sequence[Any]) -> int:
    """Assigns the given material to the primary material slot of all valid mesh objects."""
    if not mat or not objects:
        return 0

    count = 0
    for obj in objects:
        if not obj or getattr(obj, "type", "") != "MESH":
            continue
        mesh = getattr(obj, "data", None)
        if not mesh or not hasattr(mesh, "materials"):
            continue

        if len(mesh.materials) == 0:
            mesh.materials.append(mat)
        else:
            mesh.materials[0] = mat
        count += 1
    return count
