"""
8-Way & Octahedral Billboard Impostor Generator & Atlas Baking Pipeline for OmniMesh.
Blender 4.2+ and 5.2 LTS Compatible.

Provides:
- Impostor Math: Hemi-octahedral & Full-sphere octahedral coordinate mappings
- Camera-Space Tangent normal encoding with OpenGL (+Y) and DirectX (-Y) orientation
- Vectorized morphological gutter dilation to eliminate dark fringe mipmap bleeding
- Billboard Mesh Builder: Cross-Quads (+), Star-Quads (*), and Single-Quad Octahedral cards
- Multi-Engine Material and Exporter Configuration (MSFS 2024, UE5, Unity 6, Godot 4)
"""

from __future__ import annotations

import logging
import math
from typing import Any, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import bmesh
    import bpy
    import mathutils
    from mathutils import Vector
except ImportError:
    bpy = None
    bmesh = None
    mathutils = None

    class Vector(tuple):  # type: ignore
        """Fallback Vector for headless testing."""

        def __new__(cls, coords: Any) -> Vector:
            return super().__new__(cls, tuple(float(x) for x in coords))

        @property
        def x(self) -> float:
            return self[0]

        @property
        def y(self) -> float:
            return self[1]

        @property
        def z(self) -> float:
            return self[2]

        @property
        def length(self) -> float:
            return math.sqrt(self[0] * self[0] + self[1] * self[1] + self[2] * self[2])

        def normalized(self) -> Vector:
            l_val = self.length
            if l_val < 1e-9:
                return Vector((0.0, 0.0, 0.0))
            return Vector((self[0] / l_val, self[1] / l_val, self[2] / l_val))

        def dot(self, other: Any) -> float:
            return self[0] * other[0] + self[1] * other[1] + self[2] * other[2]

        def __sub__(self, other: Any) -> Vector:
            return Vector((self[0] - other[0], self[1] - other[1], self[2] - other[2]))

        def __add__(self, other: Any) -> Vector:
            return Vector((self[0] + other[0], self[1] + other[1], self[2] + other[2]))


class ImpostorMath:
    """Mathematical foundations for spherical/octahedral directional mappings."""

    @staticmethod
    def hemi_octahedral_to_vector(u: float, v: float) -> Any:
        """
        Maps 2D normalized UV coords [0, 1]^2 to upper-hemisphere 3D unit direction vector (Z >= 0).
        """
        # Map [0, 1] to [-1, 1]
        nx = u * 2.0 - 1.0
        ny = v * 2.0 - 1.0

        # Inverse Hemi-Octahedral mapping
        x = (nx + ny) * 0.5
        y = (nx - ny) * 0.5
        z = max(0.0, 1.0 - abs(x) - abs(y))

        vec = Vector((x, y, z))
        return vec.normalized()

    @staticmethod
    def vector_to_hemi_octahedral(vec: Any) -> Tuple[float, float]:
        """
        Projects 3D unit direction vector (Z >= 0) to 2D normalized UV coords [0, 1]^2.
        """
        x, y, z = float(vec[0]), float(vec[1]), max(0.0, float(vec[2]))
        denom = max(1e-9, abs(x) + abs(y) + z)
        nx = x / denom
        ny = y / denom

        u = (nx + ny) * 0.5 + 0.5
        v = (nx - ny) * 0.5 + 0.5
        return max(0.0, min(1.0, u)), max(0.0, min(1.0, v))

    @staticmethod
    def full_octahedral_to_vector(u: float, v: float) -> Any:
        """
        Maps 2D normalized UV coords [0, 1]^2 to full 3D sphere unit direction vector.
        """
        px = u * 2.0 - 1.0
        py = v * 2.0 - 1.0

        x = px
        y = py
        z = 1.0 - abs(px) - abs(py)

        if z < 0.0:
            x_sign = 1.0 if px >= 0.0 else -1.0
            y_sign = 1.0 if py >= 0.0 else -1.0
            x = (1.0 - abs(py)) * x_sign
            y = (1.0 - abs(px)) * y_sign

        vec = Vector((x, y, z))
        return vec.normalized()

    @staticmethod
    def compute_camera_space_tangent_normal(
        n_world: Any,
        cam_right: Any,
        cam_up: Any,
        cam_forward: Any,
        flip_green: bool = False,
    ) -> Tuple[float, float, float]:
        """
        Transforms world-space normal vector into Camera-Space Tangent coordinates.
        Guarantees that a surface facing directly toward the camera encodes to standard flat blue (0, 0, 1).
        """
        nx = (
            float(n_world[0]) * float(cam_right[0])
            + float(n_world[1]) * float(cam_right[1])
            + float(n_world[2]) * float(cam_right[2])
        )
        ny = (
            float(n_world[0]) * float(cam_up[0])
            + float(n_world[1]) * float(cam_up[1])
            + float(n_world[2]) * float(cam_up[2])
        )
        nz = -(
            float(n_world[0]) * float(cam_forward[0])
            + float(n_world[1]) * float(cam_forward[1])
            + float(n_world[2]) * float(cam_forward[2])
        )

        l_val = math.sqrt(nx * nx + ny * ny + nz * nz)
        if l_val > 1e-9:
            nx /= l_val
            ny /= l_val
            nz /= l_val
        else:
            nx, ny, nz = 0.0, 0.0, 1.0

        if flip_green:
            ny = -ny

        return nx, ny, nz

    @staticmethod
    def morphological_dilate_rgb(image_data: np.ndarray, iterations: int = 4) -> np.ndarray:
        """
        Vectorized push-pull morphological dilation to bleed RGB colors into transparent (Alpha=0) pixels.
        Prevents dark fringe mipmap bleeding at tile borders.
        """
        if image_data.ndim != 3 or image_data.shape[2] < 4:
            return image_data

        result = image_data.copy()
        rgb = result[:, :, :3]
        alpha = result[:, :, 3]
        valid_mask = alpha > 0.01

        for _ in range(iterations):
            invalid_mask = ~valid_mask
            if not np.any(invalid_mask):
                break

            shifted_sum = np.zeros_like(rgb, dtype=np.float32)
            shifted_count = np.zeros(alpha.shape, dtype=np.float32)

            for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                s_rgb = np.roll(np.roll(rgb, dy, axis=0), dx, axis=1)
                s_valid = np.roll(np.roll(valid_mask, dy, axis=0), dx, axis=1)

                shifted_sum += s_rgb * s_valid[:, :, None]
                shifted_count += s_valid

            fill_mask = invalid_mask & (shifted_count > 0)
            if not np.any(fill_mask):
                break

            rgb[fill_mask] = shifted_sum[fill_mask] / shifted_count[fill_mask, None]
            valid_mask = valid_mask | fill_mask

        result[:, :, :3] = rgb
        return result


class ImpostorMeshBuilder:
    """Constructs billboard geometry with exact UV layouts matching atlas projections."""

    @classmethod
    def build_cross_quads(cls, width: float = 2.0, height: float = 2.0, ground_z: float = 0.0) -> Any:
        """
        Constructs 2 intersecting vertical perpendicular rectangular quads (Cross '+', 4 tris, 8 verts).
        Plane A: Front-Facing (along X axis, normal +Y).
        Plane B: Side-Facing (along Y axis, normal +X).
        """
        if not bmesh:
            return None

        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")

        hw = width * 0.5
        z_min = ground_z
        z_max = ground_z + height

        # Plane A: X-aligned (Front view, UV u in [0.0, 0.5])
        v1 = bm.verts.new((-hw, 0.0, z_min))
        v2 = bm.verts.new((hw, 0.0, z_min))
        v3 = bm.verts.new((hw, 0.0, z_max))
        v4 = bm.verts.new((-hw, 0.0, z_max))
        f_a = bm.faces.new((v1, v2, v3, v4))

        # UV coordinates for Plane A (Left half of atlas: [0.0, 0.5])
        f_a.loops[0][uv_layer].uv = (0.0, 0.0)
        f_a.loops[1][uv_layer].uv = (0.5, 0.0)
        f_a.loops[2][uv_layer].uv = (0.5, 1.0)
        f_a.loops[3][uv_layer].uv = (0.0, 1.0)

        # Plane B: Y-aligned (Side view, UV u in [0.5, 1.0])
        v5 = bm.verts.new((0.0, -hw, z_min))
        v6 = bm.verts.new((0.0, hw, z_min))
        v7 = bm.verts.new((0.0, hw, z_max))
        v8 = bm.verts.new((0.0, -hw, z_max))
        f_b = bm.faces.new((v5, v6, v7, v8))

        f_b.loops[0][uv_layer].uv = (0.5, 0.0)
        f_b.loops[1][uv_layer].uv = (1.0, 0.0)
        f_b.loops[2][uv_layer].uv = (1.0, 1.0)
        f_b.loops[3][uv_layer].uv = (0.5, 1.0)

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    @classmethod
    def build_star_quads(cls, width: float = 2.0, height: float = 2.0, ground_z: float = 0.0) -> Any:
        """
        Constructs 3 intersecting vertical quads at 60 degree intervals (Star '*', 6 tris, 12 verts).
        """
        if not bmesh:
            return None

        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")

        hw = width * 0.5
        z_min = ground_z
        z_max = ground_z + height
        angles = [0.0, math.radians(60.0), math.radians(120.0)]

        for i, angle in enumerate(angles):
            dx = hw * math.cos(angle)
            dy = hw * math.sin(angle)

            v1 = bm.verts.new((-dx, -dy, z_min))
            v2 = bm.verts.new((dx, dy, z_min))
            v3 = bm.verts.new((dx, dy, z_max))
            v4 = bm.verts.new((-dx, -dy, z_max))
            face = bm.faces.new((v1, v2, v3, v4))

            u_start = i / 3.0
            u_end = (i + 1) / 3.0
            face.loops[0][uv_layer].uv = (u_start, 0.0)
            face.loops[1][uv_layer].uv = (u_end, 0.0)
            face.loops[2][uv_layer].uv = (u_end, 1.0)
            face.loops[3][uv_layer].uv = (u_start, 1.0)

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    @classmethod
    def build_single_camera_quad(cls, width: float = 2.0, height: float = 2.0, ground_z: float = 0.0) -> Any:
        """
        Constructs a single vertical camera-facing quad (2 tris, 4 verts) spanning [0, 1]^2 UVs.
        """
        if not bmesh:
            return None

        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")

        hw = width * 0.5
        z_min = ground_z
        z_max = ground_z + height

        v1 = bm.verts.new((-hw, 0.0, z_min))
        v2 = bm.verts.new((hw, 0.0, z_min))
        v3 = bm.verts.new((hw, 0.0, z_max))
        v4 = bm.verts.new((-hw, 0.0, z_max))
        face = bm.faces.new((v1, v2, v3, v4))

        face.loops[0][uv_layer].uv = (0.0, 0.0)
        face.loops[1][uv_layer].uv = (1.0, 0.0)
        face.loops[2][uv_layer].uv = (1.0, 1.0)
        face.loops[3][uv_layer].uv = (0.0, 1.0)

        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm


class ImpostorManager:
    """Manages scene creation, texture assignment, and engine material setup for Impostors."""

    @classmethod
    def create_impostor_material(
        cls,
        base_name: str,
        target_engine: str = "UE5",
        is_two_sided: bool = True,
    ) -> Any:
        """
        Creates or updates a dedicated PBR Impostor Material in Blender.
        Configures Alpha Clip transparency, two-sided shading, and texture slot nodes.
        """
        if not bpy:
            return None

        mat_name = f"M_{base_name}_Impostor"
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            mat = bpy.data.materials.new(name=mat_name)

        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Configure material transparency & two-sided
        if hasattr(mat, "blend_method"):
            try:
                mat.blend_method = "CLIP"
            except Exception as exc:
                logger.debug("Could not set blend_method: %s", exc)
        if hasattr(mat, "shadow_method"):
            try:
                mat.shadow_method = "CLIP"
            except Exception as exc:
                logger.debug("Could not set shadow_method: %s", exc)
        if hasattr(mat, "use_backface_culling"):
            mat.use_backface_culling = not is_two_sided

        nodes.clear()

        # Principled BSDF & Output
        node_output = nodes.new(type="ShaderNodeOutputMaterial")
        node_output.location = (400, 0)
        node_bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
        node_bsdf.location = (0, 0)
        links.new(node_bsdf.outputs["BSDF"], node_output.inputs["Surface"])

        # BaseColor Texture Node
        tex_base = nodes.new(type="ShaderNodeTexImage")
        tex_base.name = "Tex_BaseColor"
        tex_base.label = "Base Color & Alpha"
        tex_base.location = (-400, 200)

        # Connect Color and Alpha
        links.new(tex_base.outputs["Color"], node_bsdf.inputs["Base Color"])
        if "Alpha" in node_bsdf.inputs:
            links.new(tex_base.outputs["Alpha"], node_bsdf.inputs["Alpha"])

        # Normal Map Texture Node
        tex_norm = nodes.new(type="ShaderNodeTexImage")
        tex_norm.name = "Tex_Normal"
        tex_norm.label = "Normal Map"
        tex_norm.location = (-400, -100)
        if hasattr(tex_norm, "image") and tex_norm.image:
            tex_norm.image.colorspace_settings.name = "Non-Color"

        node_norm_map = nodes.new(type="ShaderNodeNormalMap")
        node_norm_map.location = (-150, -100)
        links.new(tex_norm.outputs["Color"], node_norm_map.inputs["Color"])
        if "Normal" in node_bsdf.inputs:
            links.new(node_norm_map.outputs["Normal"], node_bsdf.inputs["Normal"])

        # ORM / MaskMap Texture Node
        tex_orm = nodes.new(type="ShaderNodeTexImage")
        tex_orm.name = "Tex_ORM"
        tex_orm.label = "ORM / MaskMap"
        tex_orm.location = (-400, -350)
        if hasattr(tex_orm, "image") and tex_orm.image:
            tex_orm.image.colorspace_settings.name = "Non-Color"

        node_separate = nodes.new(type="ShaderNodeSeparateColor")
        node_separate.location = (-150, -350)
        links.new(tex_orm.outputs["Color"], node_separate.inputs["Color"])

        if target_engine == "UNITY_6":
            # MaskMap: R=Metallic, G=AO, A=Smoothness (1-Roughness)
            if "Metallic" in node_bsdf.inputs:
                links.new(node_separate.outputs["Red"], node_bsdf.inputs["Metallic"])
            if "Roughness" in node_bsdf.inputs:
                node_invert = nodes.new(type="ShaderNodeInvert")
                node_invert.location = (50, -350)
                links.new(tex_orm.outputs["Alpha"], node_invert.inputs["Color"])
                links.new(node_invert.outputs["Color"], node_bsdf.inputs["Roughness"])
        else:
            # Standard ORM (UE5 / Godot / MSFS): R=AO, G=Roughness, B=Metallic
            if "Roughness" in node_bsdf.inputs:
                links.new(node_separate.outputs["Green"], node_bsdf.inputs["Roughness"])
            if "Metallic" in node_bsdf.inputs:
                links.new(node_separate.outputs["Blue"], node_bsdf.inputs["Metallic"])

        return mat

    @classmethod
    def generate_impostor_for_objects(
        cls,
        mesh_objs: List[Any],
        base_name: str,
        mode: str = "CROSS_QUADS",
        target_engine: str = "UE5",
        target_collection_name: str = "",
    ) -> Any:
        """
        Constructs and links the Impostor billboard object in Blender.
        Assigns the Impostor PBR material and places it in the target LOD collection.
        """
        if not bpy or not mesh_objs:
            return None

        coll_name = target_collection_name or f"{base_name}_LOD_Impostor"
        target_coll = bpy.data.collections.get(coll_name)
        if not target_coll:
            target_coll = bpy.data.collections.new(coll_name)
            bpy.context.scene.collection.children.link(target_coll)

        # Calculate bounding dimensions across all selected meshes
        all_coords = [obj.matrix_world @ v.co for obj in mesh_objs for v in obj.data.vertices]
        if not all_coords:
            return None

        min_x = min(c.x for c in all_coords)
        max_x = max(c.x for c in all_coords)
        min_y = min(c.y for c in all_coords)
        max_y = max(c.y for c in all_coords)
        min_z = min(c.z for c in all_coords)
        max_z = max(c.z for c in all_coords)

        width = max(max_x - min_x, max_y - min_y, 0.5)
        height = max(max_z - min_z, 0.5)
        ground_z = min_z

        # Center XY
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5

        # Construct BMesh geometry
        if mode == "STAR_QUADS":
            bm = ImpostorMeshBuilder.build_star_quads(width=width, height=height, ground_z=ground_z)
        elif mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
            bm = ImpostorMeshBuilder.build_single_camera_quad(width=width, height=height, ground_z=ground_z)
        else:  # CROSS_QUADS default
            bm = ImpostorMeshBuilder.build_cross_quads(width=width, height=height, ground_z=ground_z)

        if not bm:
            return None

        # Create Blender Mesh & Object
        impostor_name = f"{base_name}_LOD_Impostor"
        existing = bpy.data.objects.get(impostor_name)
        if existing:
            bpy.data.objects.remove(existing, do_unlink=True)

        impostor_mesh = bpy.data.meshes.new(f"{impostor_name}_Mesh")
        bm.to_mesh(impostor_mesh)
        bm.free()

        impostor_obj = bpy.data.objects.new(impostor_name, impostor_mesh)
        impostor_obj.location = (center_x, center_y, 0.0)
        impostor_obj["_is_impostor"] = True
        impostor_obj["_impostor_mode"] = mode

        # Assign Impostor PBR Material
        mat = cls.create_impostor_material(base_name, target_engine=target_engine, is_two_sided=True)
        if mat:
            impostor_obj.data.materials.append(mat)

        target_coll.objects.link(impostor_obj)
        logger.info(
            "Generated Impostor '%s' (Mode: %s, Width: %.2fm, Height: %.2fm)", impostor_name, mode, width, height
        )
        return impostor_obj
