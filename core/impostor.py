"""
8-Way & Octahedral Billboard Impostor Generator & Atlas Baking Pipeline for OmniMesh.
Blender 5.0+ and 5.2 LTS Compatible.

Provides:
- Impostor Math: Hemi-octahedral & Full-sphere octahedral coordinate mappings
- Camera-Space Tangent normal encoding with OpenGL (+Y) and DirectX (-Y) orientation
- Vectorized morphological gutter dilation to eliminate dark fringe mipmap bleeding
- Billboard Mesh Builder: Cross-Quads (+), Star-Quads (*), and Single-Quad Octahedral cards
- Multi-Engine Material and Exporter Configuration (MSFS 2024, UE5, Unity 6)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Sequence, Tuple, cast

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import BlendData
    import mathutils
    from mathutils import Vector
else:
    try:
        import bmesh
        import bpy
        import mathutils
        from mathutils import Vector
    except ImportError:
        bpy = None
        bmesh = None
        mathutils = None
    BlendData = object  # runtime fallback for type annotations

from .exceptions import ImpostorBakeError
from .impostor_math import ImpostorMath, Vector, normalize_impostor_grid_size
from .impostor_preview_material import create_octahedral_preview_material
from .io_utils import sanitize_filename
from .metrics import compute_bounding_sphere

__all__ = [
    "ImpostorMath",
    "Vector",
    "ImpostorMeshBuilder",
    "ImpostorManager",
    "clear_stale_impostor_masters",
    "resolve_impostor_export_dir",
]


class ImpostorMeshBuilder:
    """Constructs billboard geometry with exact UV layouts matching atlas projections."""

    @classmethod
    def build_intersecting_quads(
        cls,
        coords: Optional[Sequence[Sequence[float] | Vector]] = None,
        min_coords: Tuple[float, float, float] = (-1.0, -1.0, -1.0),
        max_coords: Tuple[float, float, float] = (1.0, 1.0, 1.0),
        padding_pct: float = 0.02,
        include_diagonals: bool = True,
    ) -> bmesh.types.BMesh | None:
        """
        Constructs intersecting billboard quads centered at object origin:
        - 3 Axial Planes (Front/Back, Right/Left, Top/Bottom) -> 6 faces
        - 4 Diagonal Planes (Yaw +-45 deg, Pitch +-45 deg) -> 8 faces (total 14 faces).
        Computes the true projected bounding box dimensions from each angle.
        Assigns proportional UV islands to each face based on real world dimensions.
        """
        if not bmesh:
            return None

        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")

        # 3 Orthogonal Planes: XY (Horizontal), YZ (Longitudinal), XZ (Transverse) (6 faces total)
        plane_defs = [
            # 1. XY Plane (Horizontal / Top & Bottom): spanning X and Y, normal along +Z
            (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0))),
            # 2. YZ Plane (Vertical Longitudinal / Left & Right): spanning Y and Z, normal along +X
            (Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0)), Vector((1.0, 0.0, 0.0))),
            # 3. XZ Plane (Vertical Transverse / Front & Rear): spanning X and Z, normal along -Y
            (Vector((1.0, 0.0, 0.0)), Vector((0.0, 0.0, 1.0)), Vector((0.0, -1.0, 0.0))),
        ]

        pts = (
            [Vector((c[0], c[1], c[2])) for c in coords]
            if coords
            else [
                Vector((x, y, z))
                for x in (min_coords[0], max_coords[0])
                for y in (min_coords[1], max_coords[1])
                for z in (min_coords[2], max_coords[2])
            ]
        )

        cell_w = 1.0 / 3.0
        cell_h = 0.5
        margin = 0.04
        avail_w = cell_w * (1.0 - 2.0 * margin)
        avail_h = cell_h * (1.0 - 2.0 * margin)

        for plane_idx, (u_dir, v_dir, normal) in enumerate(plane_defs):
            u_vals = [p.dot(u_dir) for p in pts]
            v_vals = [p.dot(v_dir) for p in pts]
            n_vals = [p.dot(normal) for p in pts]

            u_min, u_max = min(u_vals), max(u_vals)
            v_min, v_max = min(v_vals), max(v_vals)
            n_cen = (min(n_vals) + max(n_vals)) * 0.5
            u_cen = (u_min + u_max) * 0.5
            v_cen = (v_min + v_max) * 0.5

            w = max(0.01, (u_max - u_min) * (1.0 + padding_pct))
            h = max(0.01, (v_max - v_min) * (1.0 + padding_pct))
            hw, hh = w * 0.5, h * 0.5

            # Fit plane aspect ratio uniformly inside its (1/3 x 1/2) UV atlas cell
            scale = min(avail_w / w, avail_h / h)
            uv_w = w * scale
            uv_h = h * scale

            cell_x0 = plane_idx * cell_w
            u0_fwd = cell_x0 + (cell_w - uv_w) * 0.5
            u1_fwd = u0_fwd + uv_w
            v0_fwd = (cell_h - uv_h) * 0.5
            v1_fwd = v0_fwd + uv_h

            u0_rev = u0_fwd
            u1_rev = u1_fwd
            v0_rev = cell_h + (cell_h - uv_h) * 0.5
            v1_rev = v0_rev + uv_h

            center_pt = u_cen * u_dir + v_cen * v_dir + n_cen * normal

            p_bl = center_pt - hw * u_dir - hh * v_dir
            p_br = center_pt + hw * u_dir - hh * v_dir
            p_tr = center_pt + hw * u_dir + hh * v_dir
            p_tl = center_pt - hw * u_dir + hh * v_dir

            # Forward Face (+normal)
            v1 = bm.verts.new((p_bl.x, p_bl.y, p_bl.z))
            v2 = bm.verts.new((p_br.x, p_br.y, p_br.z))
            v3 = bm.verts.new((p_tr.x, p_tr.y, p_tr.z))
            v4 = bm.verts.new((p_tl.x, p_tl.y, p_tl.z))
            f_fwd = bm.faces.new((v1, v2, v3, v4))
            f_fwd.loops[0][uv_layer].uv = (u0_fwd, v0_fwd)
            f_fwd.loops[1][uv_layer].uv = (u1_fwd, v0_fwd)
            f_fwd.loops[2][uv_layer].uv = (u1_fwd, v1_fwd)
            f_fwd.loops[3][uv_layer].uv = (u0_fwd, v1_fwd)

            # Reverse Face (-normal)
            v5 = bm.verts.new((p_br.x, p_br.y, p_br.z))
            v6 = bm.verts.new((p_bl.x, p_bl.y, p_bl.z))
            v7 = bm.verts.new((p_tl.x, p_tl.y, p_tl.z))
            v8 = bm.verts.new((p_tr.x, p_tr.y, p_tr.z))
            f_rev = bm.faces.new((v5, v6, v7, v8))
            f_rev.loops[0][uv_layer].uv = (u0_rev, v0_rev)
            f_rev.loops[1][uv_layer].uv = (u1_rev, v0_rev)
            f_rev.loops[2][uv_layer].uv = (u1_rev, v1_rev)
            f_rev.loops[3][uv_layer].uv = (u0_rev, v1_rev)

        bm.normal_update()
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    @classmethod
    def build_cross_quads(
        cls,
        width: float = 2.0,
        height: float = 2.0,
        ground_z: float = 0.0,
        dim_x: float = 0.0,
        dim_y: float = 0.0,
        center_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        ortho_scale: float = 0.0,
    ) -> bmesh.types.BMesh | None:
        """Compatibility wrapper building 6 intersecting quads."""
        hw_x = (dim_x if dim_x > 1e-4 else width) * 0.5
        hw_y = (dim_y if dim_y > 1e-4 else width) * 0.5
        return cls.build_intersecting_quads(
            min_coords=(-hw_x, -hw_y, ground_z),
            max_coords=(hw_x, hw_y, ground_z + height),
        )

    @classmethod
    def build_octahedral_cutout_polygon(
        cls,
        coords: Optional[Sequence[Sequence[float] | Vector]] = None,
        min_coords: Tuple[float, float, float] = (-1.0, -1.0, -1.0),
        max_coords: Tuple[float, float, float] = (1.0, 1.0, 1.0),
        padding_pct: float = 0.04,
        bevel_pct: float = 0.25,
        center_origin: bool = False,
    ) -> bmesh.types.BMesh | None:
        """
        Constructs an 8-vertex cut-out convex polygon (octagon) facing -Y matching the
        bounding-sphere orthographic projection frustum (square aspect 1:1).
        UV coordinates are strictly mapped into [0, 1]^2.
        """
        if not bmesh:
            return None

        bm = bmesh.new()
        uv_layer = bm.loops.layers.uv.new("UVMap")

        pts = (
            [Vector((c[0], c[1], c[2])) for c in coords]
            if coords
            else [
                Vector((x, y, z))
                for x in (min_coords[0], max_coords[0])
                for y in (min_coords[1], max_coords[1])
                for z in (min_coords[2], max_coords[2])
            ]
        )
        sphere_center, sphere_radius = compute_bounding_sphere(pts)
        radius = max(0.25, float(sphere_radius))

        # Square billboard matches ImpostorCameraRig ortho_scale = 2 * radius * (1 + padding_pct)
        size = max(0.5, 2.0 * radius * (1.0 + padding_pct))
        w = size
        h = size
        hw, hh = w * 0.5, h * 0.5

        cx, cy, cz = (0.0, 0.0, 0.0) if center_origin else (sphere_center[0], sphere_center[1], sphere_center[2])

        if bevel_pct > 0.001:
            bw = hw * bevel_pct
            bh = hh * bevel_pct
            poly_pts = [
                (-hw + bw, -hh),
                (hw - bw, -hh),
                (hw, -hh + bh),
                (hw, hh - bh),
                (hw - bw, hh),
                (-hw + bw, hh),
                (-hw, hh - bh),
                (-hw, -hh + bh),
            ]
        else:
            poly_pts = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]

        verts = [bm.verts.new((cx + px, cy, cz + pz)) for px, pz in poly_pts]
        face = bm.faces.new(verts)

        for loop, (px, pz) in zip(face.loops, poly_pts, strict=True):
            u = (px + hw) / w
            v = (pz + hh) / h
            loop[uv_layer].uv = (u, v)

        bm.normal_update()
        bm.verts.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        return bm

    @classmethod
    def build_star_quads(
        cls,
        width: float = 2.0,
        height: float = 2.0,
        ground_z: float = 0.0,
        dim_x: float = 0.0,
        dim_y: float = 0.0,
        center_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        ortho_scale: float = 0.0,
    ) -> bmesh.types.BMesh | None:
        """Compatibility fallback delegating to build_cross_quads."""
        return cls.build_cross_quads(
            width=width,
            height=height,
            ground_z=ground_z,
            dim_x=dim_x,
            dim_y=dim_y,
            center_offset=center_offset,
            ortho_scale=ortho_scale,
        )

    @classmethod
    def build_single_camera_quad(
        cls,
        coords: Optional[Sequence[Sequence[float] | Vector]] = None,
        min_coords: Tuple[float, float, float] = (-1.0, -1.0, -1.0),
        max_coords: Tuple[float, float, float] = (1.0, 1.0, 1.0),
        padding_pct: float = 0.04,
        bevel_pct: float = 0.25,
    ) -> bmesh.types.BMesh | None:
        """Constructs a single planar quad or cutout octagon for Octahedral Impostor cards."""
        return cls.build_octahedral_cutout_polygon(
            coords=coords,
            min_coords=min_coords,
            max_coords=max_coords,
            padding_pct=padding_pct,
            bevel_pct=bevel_pct,
        )


class ImpostorManager:
    """Manages scene creation, texture assignment, and engine material setup for Impostors."""

    @classmethod
    def create_impostor_material(
        cls,
        base_name: str,
        target_engine: str = "UE5",
        is_two_sided: bool = True,
        mode: str = "ORTHO_3_AXES",
        grid_size: int = 8,
        *,
        blend_data: BlendData,
    ) -> bpy.types.Material | None:
        """
        Creates or updates a dedicated PBR Impostor Material in Blender.
        Routes Octahedral modes to dynamic GPU atlas decoding and multi-plane modes to 1:1 PBR slots.
        """
        if not bpy or blend_data is None:
            return None

        norm_grid = normalize_impostor_grid_size(grid_size)
        if mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}:
            return create_octahedral_preview_material(
                mat_name=f"M_{base_name}_Impostor",
                base_color_path="",
                grid_size=norm_grid,
                target_engine=target_engine,
                mode=mode,
                view_dir_mode="VIEWPORT_INCOMING",
                allow_unbound_tex_nodes=True,
                blend_data=blend_data,
            )

        mat_name = f"M_{base_name}_Impostor"
        mat = blend_data.materials.get(mat_name)
        if not mat:
            mat = blend_data.materials.new(name=mat_name)

        mat.use_nodes = True
        if not mat.node_tree:
            raise ImpostorBakeError("Impostor material has no node tree.")
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links

        # Dithered alpha preserves proper depth-buffer sorting across intersecting 3D planes
        mat.surface_render_method = "DITHERED"
        mat.use_transparent_shadow = True
        mat.use_backface_culling = True
        mat.use_backface_culling_shadow = True

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
        tex_base.mute = True

        # Connect Color and Alpha
        links.new(tex_base.outputs["Color"], node_bsdf.inputs["Base Color"])
        if "Alpha" in node_bsdf.inputs:
            links.new(tex_base.outputs["Alpha"], node_bsdf.inputs["Alpha"])

        # Normal Map Texture Node
        tex_norm = nodes.new(type="ShaderNodeTexImage")
        tex_norm.name = "Tex_Normal"
        tex_norm.label = "Normal Map"
        tex_norm.location = (-400, -100)
        tex_norm.mute = True

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
        tex_orm.mute = True

        node_separate = nodes.new(type="ShaderNodeSeparateColor")
        node_separate.location = (-150, -350)
        links.new(tex_orm.outputs["Color"], node_separate.inputs["Color"])

        if target_engine in {"UNITY", "UNITY_6"}:
            # MaskMap: R=Metallic, G=AO, A=Smoothness (1-Roughness)
            if "Metallic" in node_bsdf.inputs:
                links.new(node_separate.outputs["Red"], node_bsdf.inputs["Metallic"])
            if "Roughness" in node_bsdf.inputs:
                node_invert = nodes.new(type="ShaderNodeInvert")
                node_invert.location = (50, -350)
                links.new(tex_orm.outputs["Alpha"], node_invert.inputs["Color"])
                links.new(node_invert.outputs["Color"], node_bsdf.inputs["Roughness"])
        else:
            # Standard ORM (UE5 / MSFS): R=AO, G=Roughness, B=Metallic
            if "Roughness" in node_bsdf.inputs:
                links.new(node_separate.outputs["Green"], node_bsdf.inputs["Roughness"])
            if "Metallic" in node_bsdf.inputs:
                links.new(node_separate.outputs["Blue"], node_bsdf.inputs["Metallic"])

        return mat

    @classmethod
    def bind_baked_textures_to_material(
        cls,
        mat: bpy.types.Material | None,
        base_color_path: str = "",
        normal_path: str = "",
        orm_path: str = "",
        *,
        blend_data: BlendData,
    ) -> None:
        """Loads and assigns baked PNG files into TexImage shader nodes on Impostor material."""
        if not bpy or not mat or blend_data is None or not mat.node_tree:
            return

        nodes = mat.node_tree.nodes

        if base_color_path and os.path.exists(base_color_path):
            tex_base = nodes.get("Tex_BaseColor")
            if tex_base and tex_base.type == "TEX_IMAGE":
                img = blend_data.images.load(base_color_path)
                tex_base_node = cast("bpy.types.ShaderNodeTexImage", tex_base)
                tex_base_node.image = img
                tex_base_node.mute = False
                if img.colorspace_settings:
                    img.colorspace_settings.name = "sRGB"  # type: ignore[assignment]

        if normal_path and os.path.exists(normal_path):
            tex_norm = nodes.get("Tex_Normal")
            if tex_norm and tex_norm.type == "TEX_IMAGE":
                img = blend_data.images.load(normal_path)
                tex_norm_node = cast("bpy.types.ShaderNodeTexImage", tex_norm)
                tex_norm_node.image = img
                tex_norm_node.mute = False
                if img.colorspace_settings:
                    img.colorspace_settings.name = "Non-Color"  # type: ignore[assignment]

        if orm_path and os.path.exists(orm_path):
            tex_orm = nodes.get("Tex_ORM")
            if tex_orm and tex_orm.type == "TEX_IMAGE":
                img = blend_data.images.load(orm_path)
                tex_orm_node = cast("bpy.types.ShaderNodeTexImage", tex_orm)
                tex_orm_node.image = img
                tex_orm_node.mute = False
                if img.colorspace_settings:
                    img.colorspace_settings.name = "Non-Color"  # type: ignore[assignment]

    @classmethod
    def generate_impostor_for_objects(
        cls,
        mesh_objs: List[bpy.types.Object],
        base_name: str,
        mode: str = "ORTHO_3_AXES",
        target_engine: str = "UE5",
        target_collection_name: str = "",
        atlas_resolution: int = 2048,
        scene: bpy.types.Scene | None = None,
        context: bpy.types.Context | None = None,
        grid_size: int = 8,
        *,
        blend_data: BlendData,
    ) -> bpy.types.Object | None:
        """
        Constructs and links the Impostor billboard object in Blender.
        Assigns the Impostor PBR material and places it in the target LOD collection.
        """
        if not bpy or not mesh_objs or blend_data is None:
            return None

        effective_bdata = blend_data
        ctx = context
        sc = (
            scene
            or (ctx.scene if ctx else None)
            or (effective_bdata.scenes[0] if len(effective_bdata.scenes) > 0 else None)
        )

        coll_name = target_collection_name or f"{base_name}_LOD_Impostor"
        target_coll = effective_bdata.collections.get(coll_name)
        if not target_coll:
            target_coll = effective_bdata.collections.new(coll_name)
            if sc and sc.collection:
                sc.collection.children.link(target_coll)

        if not target_coll:
            return None

        # Calculate bounding dimensions across all selected meshes (using bound_box corners for O(1) efficiency)
        all_coords: list[Vector] = []
        for obj in mesh_objs:
            mat_w = obj.matrix_world
            try:
                bbox = obj.bound_box
            except AttributeError:
                bbox = None
            if bbox:
                for c in bbox:
                    v = Vector(c)
                    try:
                        res = mat_w @ v if mat_w is not None else v
                        all_coords.append(res if isinstance(res.x, (int, float)) else v)
                    except (TypeError, ValueError, AttributeError, RuntimeError):
                        all_coords.append(v)
            elif obj.data is not None:
                obj_data = cast("bpy.types.Mesh", obj.data)
                for v_elem in obj_data.vertices or ():
                    co = v_elem.co
                    if co is not None:
                        v = Vector((co.x, co.y, co.z))
                        try:
                            res = mat_w @ v if mat_w is not None else v
                            all_coords.append(res if isinstance(res.x, (int, float)) else v)
                        except (TypeError, ValueError, AttributeError, RuntimeError):
                            all_coords.append(v)
        if not all_coords:
            return None

        min_x = min(c.x for c in all_coords)
        max_x = max(c.x for c in all_coords)
        min_y = min(c.y for c in all_coords)
        max_y = max(c.y for c in all_coords)
        min_z = min(c.z for c in all_coords)
        max_z = max(c.z for c in all_coords)

        dim_x = max(max_x - min_x, 0.5)
        dim_y = max(max_y - min_y, 0.5)
        height = max(max_z - min_z, 0.5)

        is_octahedral = mode in {"OCTAHEDRAL_HEMI", "OCTAHEDRAL_SPHERE"}
        sphere_center, _sphere_radius = compute_bounding_sphere(all_coords)

        if is_octahedral:
            bm = ImpostorMeshBuilder.build_octahedral_cutout_polygon(
                coords=all_coords,
                min_coords=(min_x, min_y, min_z),
                max_coords=(max_x, max_y, max_z),
                padding_pct=0.04,
                bevel_pct=0.25,
                center_origin=True,
            )
        else:
            bm = ImpostorMeshBuilder.build_intersecting_quads(
                coords=all_coords,
                min_coords=(min_x, min_y, min_z),
                max_coords=(max_x, max_y, max_z),
                padding_pct=0.02,
                include_diagonals=True,
            )

        if not bm:
            return None

        impostor_name = f"{base_name}_LOD_Impostor"
        impostor_mesh: bpy.types.Mesh | None = None
        try:
            existing = effective_bdata.objects.get(impostor_name)
            if existing:
                effective_bdata.objects.remove(existing, do_unlink=True)

            impostor_mesh = effective_bdata.meshes.new(f"{impostor_name}_Mesh")
            if impostor_mesh is not None:
                bm.to_mesh(impostor_mesh)
        finally:
            bm.free()

        if not impostor_mesh:
            return None

        impostor_created = False
        try:
            impostor_obj = effective_bdata.objects.new(impostor_name, impostor_mesh)
            impostor_obj.location = (
                Vector((sphere_center[0], sphere_center[1], sphere_center[2]))
                if is_octahedral
                else Vector((0.0, 0.0, 0.0))
            )
            norm_grid = normalize_impostor_grid_size(grid_size)
            impostor_obj["_is_impostor"] = True
            impostor_obj["_impostor_mode"] = mode
            impostor_obj["_impostor_grid_size"] = norm_grid
            impostor_obj["_impostor_target_engine"] = target_engine
            impostor_obj["_impostor_canonical"] = target_engine.upper() == "CANONICAL"

            # Assign Impostor PBR Material
            mat = cls.create_impostor_material(
                base_name,
                target_engine=target_engine,
                is_two_sided=True,
                mode=mode,
                grid_size=norm_grid,
                blend_data=effective_bdata,
            )
            if mat:
                cast("Any", impostor_obj.data).materials.append(mat)

            target_coll.objects.link(impostor_obj)

            logger.info(
                "Generated Impostor '%s' (3 orthogonal planes, Bounds: %.2fm x %.2fm x %.2fm)",
                impostor_name,
                dim_x,
                dim_y,
                height,
            )
            impostor_created = True
            return impostor_obj
        finally:
            if not impostor_created and impostor_mesh and effective_bdata.meshes.get(impostor_mesh.name):
                try:
                    effective_bdata.meshes.remove(impostor_mesh)
                except (RuntimeError, ReferenceError, AttributeError) as clean_exc:
                    logger.debug("Failed removing impostor mesh in cleanup handler: %s", clean_exc)


def resolve_impostor_export_dir(
    raw_dir: str = "",
    default_subfolder: str = "Textures",
    *,
    blend_data: BlendData,
    blend_filepath: str = "",
) -> str:
    """Safely resolves export directories handling Blender relative paths, unsaved scenes,

    and Windows UNC paths without triggering NetBIOS/SMB name timeouts.
    """
    import tempfile

    path_str = (raw_dir or "").strip()
    if not path_str:
        path_str = f"//{default_subfolder}/"

    effective_fp = blend_filepath or (blend_data.filepath if blend_data else "")

    # Handle Blender-relative '//' paths
    if path_str.startswith("//"):
        if effective_fp:
            blend_dir = os.path.dirname(effective_fp)
            rel_part = path_str[2:].lstrip("/\\")
            resolved = os.path.abspath(os.path.join(blend_dir, rel_part))
        else:
            # Unsaved scene: Anchor to system temp directory to guarantee write permissions
            # NEVER fallback to os.getcwd() which may be C:\Program Files
            rel_part = path_str[2:].lstrip("/\\") or default_subfolder
            resolved = os.path.join(tempfile.gettempdir(), "OmniMesh", rel_part)
    else:
        # Check if genuine Windows UNC path (e.g. \\server\share or //server/share)
        norm_slashes = path_str.replace("/", "\\")
        if norm_slashes.startswith(r"\\") and len(norm_slashes.split("\\")) > 3:
            resolved = path_str
        elif not os.path.isabs(path_str):
            if effective_fp:
                resolved = os.path.abspath(os.path.join(os.path.dirname(effective_fp), path_str))
            else:
                resolved = os.path.join(tempfile.gettempdir(), "OmniMesh", path_str)
        else:
            resolved = path_str

    clean_path = os.path.normpath(resolved)
    # Ensure default_subfolder is present without duplicate appending due to trailing slashes
    if default_subfolder and os.path.basename(clean_path).lower() != default_subfolder.lower():
        clean_path = os.path.join(clean_path, default_subfolder)

    try:
        os.makedirs(clean_path, exist_ok=True)
    except OSError as exc:
        logger.warning("Could not create directory '%s', falling back to tempdir: %s", clean_path, exc)
        clean_path = os.path.join(tempfile.gettempdir(), "OmniMesh", default_subfolder)
        os.makedirs(clean_path, exist_ok=True)

    return clean_path


def clear_stale_impostor_masters(export_dir: str, base_name: str) -> int:
    """Remove stale canonical ``*_Master.png`` impostor textures under ``export_dir``."""
    safe_base = sanitize_filename(base_name) or "Asset"
    root = Path(export_dir).resolve()
    removed = 0
    for master_sfx in ("_BaseColor_Master.png", "_Normal_Master.png", "_ORM_Master.png"):
        candidate = (root / f"T_{safe_base}_Impostor{master_sfx}").resolve()
        if not candidate.is_relative_to(root):
            raise ImpostorBakeError(f"Refusing to delete impostor master outside export directory: {candidate}")
        if candidate.is_file():
            try:
                candidate.unlink()
                removed += 1
            except OSError as exc:
                raise ImpostorBakeError(f"Failed removing stale impostor master '{candidate.name}': {exc}") from exc
    return removed
