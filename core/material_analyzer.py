"""
OmniMesh MSFS Material & Shader Analyzer.
Provides pure Python and Blender-aware classification of materials used in MSFS aircraft.
Identifies Asobo standard material types (Decal, Windshield, Invisible, Collision, Props)
to guide geometry decimation, prevent Z-fighting, and preserve interaction meshes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MSFSMaterialKind(Enum):
    """Categorized functional role of an MSFS material."""

    STANDARD = "STANDARD"  # Type 1: Standard airframe/interior PBR
    DECAL = "DECAL"  # Type 2: Floating geometric decals (rivets, warnings, dirt)
    WEATHER = "WEATHER"  # Type 3, 17: Frost, Mud, Insects, Rain overlay
    WINDSHIELD = "WINDSHIELD"  # Type 4: Glass with wiper lines and raindrops
    LIVERY = "LIVERY"  # Type 7: Livery custom colorable layers
    ANISOTROPIC = "ANISOTROPIC"  # Type 9: Brushed metal, brakes, engine blades
    INVISIBLE = "INVISIBLE"  # Type 12: Clickspots, cockpit mouse interaction, collision
    PROPELLER = "PROPELLER"  # Type 19: Blurred propeller disc / rotor


@dataclass(frozen=True)
class MaterialProfile:
    """Classified functional profile for a material slot."""

    material_name: str
    kind: MSFSMaterialKind
    msfs_type_id: int = 1
    requires_planar_protection: bool = False
    requires_boundary_protection: bool = False
    should_cull_distant_lods: bool = False


class MSFSMaterialAnalyzer:
    """Analyzes materials and meshes to determine appropriate LOD processing constraints."""

    # Official Asobo Blender Addon msfs_material_type integer mapping
    TYPE_ID_MAP: dict[int, MSFSMaterialKind] = {
        1: MSFSMaterialKind.STANDARD,
        2: MSFSMaterialKind.DECAL,
        3: MSFSMaterialKind.WEATHER,
        4: MSFSMaterialKind.WINDSHIELD,
        7: MSFSMaterialKind.LIVERY,
        9: MSFSMaterialKind.ANISOTROPIC,
        12: MSFSMaterialKind.INVISIBLE,
        17: MSFSMaterialKind.WEATHER,
        19: MSFSMaterialKind.PROPELLER,
    }

    @classmethod
    def classify_material(cls, mat: Any) -> MaterialProfile:
        """Classifies a Blender Material or mock object into a typed MaterialProfile."""
        mat_name = getattr(mat, "name", "") or "Material"
        name_lower = mat_name.lower()

        # 1. Check custom property msfs_material_type (Asobo addon standard)
        type_id = 1
        if hasattr(mat, "get"):
            raw_type = mat.get("msfs_material_type")
            if raw_type is not None:
                try:
                    type_id = int(raw_type)
                except (ValueError, TypeError):
                    type_id = 1

        if type_id in cls.TYPE_ID_MAP and type_id != 1:
            kind = cls.TYPE_ID_MAP[type_id]
        else:
            # 2. Heuristic fallback based on material name
            if "decal" in name_lower or "rivet" in name_lower:
                kind = MSFSMaterialKind.DECAL
                type_id = 2
            elif "windshield" in name_lower or "windscreen" in name_lower or "cockpit_glass" in name_lower:
                kind = MSFSMaterialKind.WINDSHIELD
                type_id = 4
            elif "collision" in name_lower or "invisible" in name_lower or "clickspot" in name_lower:
                kind = MSFSMaterialKind.INVISIBLE
                type_id = 12
            elif "frost" in name_lower or "mud" in name_lower or "insects" in name_lower:
                kind = MSFSMaterialKind.WEATHER
                type_id = 3
            elif "prop" in name_lower and ("blur" in name_lower or "slow" in name_lower or "still" in name_lower):
                kind = MSFSMaterialKind.PROPELLER
                type_id = 19
            else:
                kind = MSFSMaterialKind.STANDARD
                type_id = 1

        # Determine protection flags
        requires_planar = kind == MSFSMaterialKind.DECAL
        requires_boundary = kind in (MSFSMaterialKind.WINDSHIELD, MSFSMaterialKind.DECAL)
        should_cull = kind == MSFSMaterialKind.INVISIBLE and ("click" in name_lower or "interact" in name_lower)

        return MaterialProfile(
            material_name=mat_name,
            kind=kind,
            msfs_type_id=type_id,
            requires_planar_protection=requires_planar,
            requires_boundary_protection=requires_boundary,
            should_cull_distant_lods=should_cull,
        )

    @classmethod
    def analyze_mesh_object(cls, obj: Any) -> list[MaterialProfile]:
        """Inspects all material slots on a mesh object and returns their profiles."""
        if not obj or getattr(obj, "type", "") != "MESH":
            return []

        slots = getattr(obj, "material_slots", [])
        profiles: list[MaterialProfile] = []
        for slot in slots:
            mat = getattr(slot, "material", None)
            if mat:
                profiles.append(cls.classify_material(mat))

        # If no material slots found, return default profile
        if not profiles:
            profiles.append(MaterialProfile(material_name="Default", kind=MSFSMaterialKind.STANDARD))

        return profiles

    @classmethod
    def is_decal_mesh(cls, obj: Any) -> bool:
        """Returns True if the object's primary material is classified as DECAL."""
        profiles = cls.analyze_mesh_object(obj)
        return any(p.kind == MSFSMaterialKind.DECAL for p in profiles)

    @classmethod
    def is_windshield_mesh(cls, obj: Any) -> bool:
        """Returns True if the object's primary material is classified as WINDSHIELD."""
        profiles = cls.analyze_mesh_object(obj)
        return any(p.kind == MSFSMaterialKind.WINDSHIELD for p in profiles)
