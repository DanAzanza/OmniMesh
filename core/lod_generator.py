"""
OmniMesh Core LOD Generation Engine.
Implements the multi-stage geometry decimation, collection cloning,
modifier evaluation, topological repair, and bone pruning pipeline.
"""

from __future__ import annotations

from .exceptions import OmniMeshError

import logging
import math
from typing import TYPE_CHECKING, Any, Protocol, Sequence, cast


class LODTierProtocol(Protocol):
    """Structural protocol for an individual LOD tier."""

    screen_size_pct: float
    target_tris_pct: float
    distance_m: float
    last_baked_target_pct: float
    last_baked_screen_pct: float
    actual_tris: int
    actual_triangles: int
    mat_slots_count: int
    generated_obj: bpy.types.Object | None
    state: str
    target_tris: int


class LODSettingsProtocol(Protocol):
    """Structural protocol for LOD tool settings across UI properties and headless doubles."""

    enable_slender_culling: bool
    tau_sse: float
    enable_occlusion_culling: bool
    occlusion_lod_start: int
    occlusion_ray_density: int
    occlusion_evaluate_alpha: bool
    pin_uv_seams: bool
    pin_material_borders: bool
    msfs_preserve_decals: bool
    purge_shape_keys: bool
    preserve_slot_indexing: bool
    enable_bone_pruning: bool
    max_bone_influences: int
    hierarchy_mode: str
    consolidate_hierarchy: bool
    merge_start_tier: int
    enable_impostor_lod: bool
    lods: Sequence[LODTierProtocol]
    last_culled_slender_count: int
    last_generated_base_tris: int
    last_generated_final_tris: int
    last_generated_reduction_pct: float
    last_generated_tier_count: int


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bmesh
    import bpy
    from bpy.types import BlendData
    from mathutils import Vector
else:
    try:
        import bmesh
        import bpy
        from mathutils import Vector
    except ImportError:
        bpy = None
        bmesh = None
        Vector = None
    BlendData = object

from .decimator import MeshDecimator
from .exceptions import DecimationError
from .hierarchy import CollectionCloneDAG, LayerCollectionGuard, MeshMergeEngine
from .material_analyzer import MSFSMaterialAnalyzer, MSFSMaterialKind
from .materials import MaterialOptimizer
from .metrics import (
    compute_bounding_sphere,
    compute_coupled_tolerances,
    compute_vertical_fov,
)
from .modifiers import ModifierManager
from .normals import NormalManager
from .occlusion import HardenedOcclusionCuller
from .pivot import PivotPreservationEngine
from .rigging import KinematicBonePruner, WeightSanitizer
from .sanitizer import MeshSanitizer, SanitizeOptions
from .slender import SlenderFeatureCuller


def _count_triangles(mesh_data: bpy.types.Mesh | bmesh.types.BMesh | object | None) -> int:
    """Computes true triangle count in O(1) via loop-poly invariant with safe fallback."""
    if not mesh_data:
        return 0
    try:
        loops = mesh_data.loops  # type: ignore[union-attr]
        polys = mesh_data.polygons  # type: ignore[union-attr]
        if loops is not None and polys is not None:
            n_loops = len(loops)
            n_polys = len(polys)
            return max(0, n_loops - 2 * n_polys) if n_polys > 0 else 0
        if polys is not None:
            return sum(max(0, len(cast("Sequence[int]", p.vertices)) - 2) for p in polys)
    except (AttributeError, TypeError):
        pass
    try:
        faces = mesh_data.faces  # type: ignore[union-attr]
        if faces is not None:
            return len(faces)
    except (AttributeError, TypeError):
        pass
    return 0


def _compute_lod0_stats(mesh_objs: list[bpy.types.Object]) -> tuple[int, int]:
    """Calculates initial triangle count and material slot count for LOD0."""
    tier_tris = 0
    tier_mats = sum(len(obj.material_slots) for obj in mesh_objs)
    for obj in mesh_objs:
        if ModifierManager.has_unapplied_modifiers(obj):
            eval_mesh, eval_obj = ModifierManager.get_evaluated_mesh(obj, preserve_armature=True)
            if eval_mesh:
                try:
                    tier_tris += _count_triangles(eval_mesh)
                finally:
                    if eval_obj:
                        eval_obj.to_mesh_clear()
            else:
                tier_tris += _count_triangles(obj.data)
        else:
            tier_tris += _count_triangles(obj.data)
    return tier_tris, tier_mats


def _process_merged_tier(
    tier_coll: bpy.types.Collection | None,
    tier_in: LODTierProtocol,
    tier_idx: int,
    base_name: str,
    mesh_objs: list[bpy.types.Object],
    armature_obj: bpy.types.Object | None,
    tier_pivot: bpy.types.Object | None,
    tolerances: dict[str, Any],
    props_in: LODSettingsProtocol,
    render_in: bpy.types.RenderSettings | object,
    radius: float,
    fov_v: float,
    max_influences: int,
    ref_merged_obj: bpy.types.Object | None = None,
    context: bpy.types.Context | None = None,
    *,
    blend_data: BlendData,
) -> tuple[int, int, int, bpy.types.Object | None]:
    """Processes a merged LOD tier, combining meshes and applying decimation pipeline."""
    tier = tier_in
    props = props_in
    render = cast("bpy.types.RenderSettings", render_in)
    bdata = blend_data
    bdata_objs = bdata.objects if bdata else None
    merged_name = f"{base_name}_LOD{tier_idx}"
    existing = bdata_objs.get(merged_name) if bdata_objs else None
    if existing and existing not in mesh_objs and bdata_objs:
        old_mesh = cast("bpy.types.Mesh | None", existing.data)
        bdata_objs.remove(existing, do_unlink=True)
        bdata_meshes = bdata.meshes if bdata else None
        if old_mesh and old_mesh.users == 0 and bdata_meshes:
            try:
                bdata_meshes.remove(old_mesh)
            except (RuntimeError, ReferenceError, AttributeError) as exc:
                logger.debug("Failed deallocating orphan mesh %s: %s", old_mesh.name, exc)
    tier_obj = MeshMergeEngine.consolidate_and_merge_meshes(
        mesh_objs, merged_name, armature_obj=armature_obj, pivot_obj=tier_pivot, blend_data=bdata
    )
    if not tier_obj:
        raise DecimationError(f"Mesh consolidation failed for {merged_name}.")
    if tier_coll and tier_obj.name not in tier_coll.objects:
        tier_coll.objects.link(tier_obj)

    tier_mesh = cast("bpy.types.Mesh", tier_obj.data)
    culled_slender_count = 0
    bm = bmesh.new()
    try:
        bm.from_mesh(tier_mesh)
        MeshSanitizer.sanitize_mesh_full(
            bm,
            options=SanitizeOptions(
                epsilon_merge=tolerances["epsilon_merge"],
                w_crit=tolerances["w_crit"],
            ),
        )

        if bool(props.enable_slender_culling):
            res_slender = SlenderFeatureCuller.cull_slender_features(
                bm,
                screen_size_pct=float(tier.screen_size_pct),
                resolution_y=render.resolution_y,
                root_radius_m=radius,
                tau_sse=float(props.tau_sse),
            )
            culled_slender_count += res_slender.get("culled_islands", 0)

        if bool(props.enable_occlusion_culling) and tier_idx >= int(props.occlusion_lod_start):
            HardenedOcclusionCuller.cull_interior_faces(
                tier_obj,
                bm,
                ray_density=int(props.occlusion_ray_density),
                evaluate_alpha=bool(props.occlusion_evaluate_alpha),
                delta_world=tolerances["delta_world"],
            )

        MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
        pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(
            bm,
            pin_uv_seams=bool(props.pin_uv_seams),
            pin_material_borders=bool(props.pin_material_borders),
        )

        # Decal vertex protection: pin vertices belonging to decal materials to protect planar fidelity
        if bool(props.msfs_preserve_decals) and MSFSMaterialAnalyzer:
            mat_slots = tier_obj.material_slots
            for f in bm.faces:
                mat_idx = f.material_index
                if 0 <= mat_idx < len(mat_slots):
                    mat = mat_slots[mat_idx].material
                    if mat and MSFSMaterialAnalyzer.classify_material(mat).kind == MSFSMaterialKind.DECAL:
                        for v in f.verts:
                            pinned_verts.add(v.index)

        MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
        bm.to_mesh(tier_mesh)
    finally:
        bm.free()

    if bool(props.purge_shape_keys) and tier_idx >= 1:
        MeshDecimator.purge_all_shape_keys(tier_obj, context=context)

    target_tris_pct = float(tier.target_tris_pct)
    qem_ratio = target_tris_pct / 100.0 if target_tris_pct > 0.0 else tolerances["qem_ratio"]
    MeshDecimator.execute_decimate_qem(
        tier_obj, min(1.0, max(0.001, qem_ratio)), use_curvature_weight=True, context=context
    )

    tier_mesh.update()
    MaterialOptimizer.consolidate_micro_materials(
        tier_obj,
        area_crit=tolerances["area_crit"],
        preserve_slot_indexing=bool(props.preserve_slot_indexing),
    )

    # Reproject custom split normals against consolidated source geometry
    target_ref = ref_merged_obj
    owned_ref = False
    try:
        if not target_ref:
            ref_merged_name = f"__OM_Ref_Merged_LOD0_{tier_idx}__"
            target_ref = MeshMergeEngine.consolidate_and_merge_meshes(
                mesh_objs, ref_merged_name, armature_obj=armature_obj, pivot_obj=tier_pivot, blend_data=bdata
            )
            owned_ref = True
        NormalManager.reproject_custom_split_normals(tier_obj, target_ref, tolerances["delta_world"], context=context)
    except (RuntimeError, ValueError, AttributeError) as exc:
        logger.warning(
            "Merged custom split normal reprojection failed for '%s' (LOD%d): %s; attempting single-mesh fallback",
            tier_obj.name,
            tier_idx,
            exc,
        )
        if mesh_objs:
            try:
                NormalManager.reproject_custom_split_normals(
                    tier_obj, mesh_objs[0], tolerances["delta_world"], context=context
                )
            except (RuntimeError, ValueError, AttributeError) as fb_exc:
                logger.warning(
                    "Fallback single-mesh normal reprojection also failed for '%s': %s",
                    tier_obj.name,
                    fb_exc,
                )
    finally:
        bdata_objs = bdata.objects if bdata else None
        if owned_ref and target_ref and bdata_objs:
            ref_mesh = cast("bpy.types.Mesh | None", target_ref.data)
            try:
                bdata_objs.remove(target_ref, do_unlink=True)
                bdata_meshes = bdata.meshes if bdata else None
                if ref_mesh and ref_mesh.users == 0 and bdata_meshes:
                    bdata_meshes.remove(ref_mesh)
            except (RuntimeError, ReferenceError, AttributeError) as exc:
                logger.debug("Cleanup ref_merged_obj exception: %s", exc)

    if armature_obj and len(tier_obj.vertex_groups) > 0:
        if bool(props.enable_bone_pruning) and tier_idx >= 2:
            KinematicBonePruner.prune_kinematic_subtrees(
                tier_obj,
                armature_obj,
                screen_distance_m=float(tier.distance_m),
                fov_v_rad=fov_v,
                resolution_y=render.resolution_y,
                pixel_threshold=1.5,
            )
        WeightSanitizer.normalize_and_clamp_weights(tier_obj, max_influences=max_influences)

    tier_mesh.update()
    actual_tris = _count_triangles(tier_mesh)
    actual_mats = len(tier_obj.material_slots)
    lod_tool_meta = getattr(tier_obj, "lod_tool", None)
    if lod_tool_meta is not None:
        lod_tool_meta.lod_root_object = mesh_objs[0] if mesh_objs else None
        lod_tool_meta.is_generated_lod = True
        lod_tool_meta.lod_index = tier_idx

    return actual_tris, actual_mats, culled_slender_count, tier_obj


def _process_unmerged_tier(
    tier_coll: bpy.types.Collection | None,
    tier_in: LODTierProtocol,
    tier_idx: int,
    base_name: str,
    mesh_objs: list[bpy.types.Object],
    armature_obj: bpy.types.Object | None,
    tier_pivot: bpy.types.Object | None,
    root_pivot: bpy.types.Object | None,
    tolerances: dict[str, Any],
    props_in: LODSettingsProtocol,
    render_in: bpy.types.RenderSettings | object,
    radius: float,
    fov_v: float,
    max_influences: int,
    context: bpy.types.Context | None = None,
    *,
    blend_data: BlendData,
) -> tuple[int, int, int, bpy.types.Object | None]:
    """Processes an unmerged multi-mesh LOD tier, decimating each object individually."""
    tier = tier_in
    props = props_in
    render = cast("bpy.types.RenderSettings", render_in)
    tier_tris = 0
    tier_mats = 0
    culled_slender_count = 0
    first_generated_obj = None

    bdata = blend_data
    bdata_objs = bdata.objects if bdata else None
    bdata_meshes = bdata.meshes if bdata else None

    for obj_idx, source_obj in enumerate(mesh_objs):
        sub_name = f"{source_obj.name}_LOD{tier_idx}" if len(mesh_objs) > 1 else f"{base_name}_LOD{tier_idx}"
        existing = bdata_objs.get(sub_name) if bdata_objs else None
        if existing and existing not in mesh_objs and existing != source_obj and bdata_objs:
            old_mesh = cast("bpy.types.Mesh | None", existing.data)
            bdata_objs.remove(existing, do_unlink=True)
            if old_mesh and old_mesh.users == 0 and bdata_meshes:
                try:
                    bdata_meshes.remove(old_mesh)
                except (RuntimeError, ReferenceError, AttributeError) as exc:
                    logger.debug("Failed deallocating orphan mesh %s: %s", old_mesh.name, exc)

        lod_obj = source_obj.copy()
        if lod_obj is None:
            continue
        src_data = cast("bpy.types.Mesh | None", source_obj.data)
        lod_mesh = cast("bpy.types.Mesh", src_data.copy() if src_data else src_data)
        lod_obj.data = lod_mesh
        lod_obj.name = sub_name
        if lod_obj.data:
            lod_obj.data.name = f"{sub_name}_Mesh"
        if tier_coll:
            tier_coll.objects.link(lod_obj)

        if bool(props.purge_shape_keys) and tier_idx >= 1:
            MeshDecimator.purge_all_shape_keys(lod_obj, context=context)

        ModifierManager.apply_all_modifiers_in_place(lod_obj, preserve_armature=True)

        if tier_pivot:
            lod_parent = lod_obj.parent
            is_parent_pivot = (
                lod_parent is None
                or (root_pivot is not None and lod_parent == root_pivot)
                or (root_pivot is not None and lod_parent is not None and lod_parent.name == root_pivot.name)
                or (lod_parent is not None and "pivot" in lod_parent.name.lower())
            )
            if is_parent_pivot:
                lod_obj.parent = tier_pivot
                lod_obj.matrix_parent_inverse = source_obj.matrix_parent_inverse.copy()

        bm = bmesh.new()
        try:
            bm.from_mesh(lod_mesh)
            MeshSanitizer.sanitize_mesh_full(
                bm,
                options=SanitizeOptions(
                    epsilon_merge=tolerances["epsilon_merge"],
                    w_crit=tolerances["w_crit"],
                ),
            )

            if bool(props.enable_slender_culling):
                res_slender = SlenderFeatureCuller.cull_slender_features(
                    bm,
                    screen_size_pct=float(tier.screen_size_pct),
                    resolution_y=render.resolution_y,
                    root_radius_m=radius,
                    tau_sse=float(props.tau_sse),
                )
                culled_slender_count += res_slender.get("culled_islands", 0)

            if bool(props.enable_occlusion_culling) and tier_idx >= int(props.occlusion_lod_start):
                HardenedOcclusionCuller.cull_interior_faces(
                    lod_obj,
                    bm,
                    ray_density=int(props.occlusion_ray_density),
                    evaluate_alpha=bool(props.occlusion_evaluate_alpha),
                    delta_world=tolerances["delta_world"],
                )

            MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
            pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(
                bm,
                pin_uv_seams=bool(props.pin_uv_seams),
                pin_material_borders=bool(props.pin_material_borders),
            )
            MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
            bm.to_mesh(lod_mesh)
        finally:
            bm.free()
        lod_mesh.update()

        is_decal = False
        if MSFSMaterialAnalyzer:
            is_decal = MSFSMaterialAnalyzer.is_decal_mesh(source_obj)

        target_tris_pct = float(tier.target_tris_pct)
        qem_ratio = target_tris_pct / 100.0 if target_tris_pct > 0.0 else tolerances["qem_ratio"]
        if is_decal and bool(props.msfs_preserve_decals):
            qem_ratio = max(qem_ratio, 0.75 if tier_idx <= 2 else 0.5)

        MeshDecimator.execute_decimate_qem(
            lod_obj, min(1.0, max(0.001, qem_ratio)), use_curvature_weight=True, context=context
        )

        MaterialOptimizer.consolidate_micro_materials(
            lod_obj,
            area_crit=tolerances["area_crit"],
            preserve_slot_indexing=bool(props.preserve_slot_indexing),
        )

        NormalManager.reproject_custom_split_normals(lod_obj, source_obj, tolerances["delta_world"], context=context)

        if armature_obj and len(lod_obj.vertex_groups) > 0:
            if bool(props.enable_bone_pruning) and tier_idx >= 2:
                KinematicBonePruner.prune_kinematic_subtrees(
                    lod_obj,
                    armature_obj,
                    screen_distance_m=float(tier.distance_m),
                    fov_v_rad=fov_v,
                    resolution_y=render.resolution_y,
                    pixel_threshold=1.5,
                )
            WeightSanitizer.normalize_and_clamp_weights(lod_obj, max_influences=max_influences)

        lod_mesh.update()
        tier_tris += _count_triangles(lod_mesh)
        tier_mats += len(lod_obj.material_slots)
        lod_tool_meta = getattr(lod_obj, "lod_tool", None)
        if lod_tool_meta is not None:
            lod_tool_meta.lod_root_object = source_obj
            lod_tool_meta.is_generated_lod = True
            lod_tool_meta.lod_index = tier_idx
        if obj_idx == 0:
            first_generated_obj = lod_obj

    return tier_tris, tier_mats, culled_slender_count, first_generated_obj


def generate_all_lods(
    context: bpy.types.Context | None,
    props: LODSettingsProtocol | None,
    mesh_objs: list[bpy.types.Object],
    armature_obj: bpy.types.Object | None = None,
    base_name: str = "",
    only_out_of_sync: bool = False,
    *,
    blend_data: BlendData,
) -> tuple[bool, str]:
    """
    Execute the full multi-tier LOD generation pipeline across selected meshes.

    Performs modifier evaluation, bounding sphere calculation, hierarchical sibling
    collection cloning, mesh merging, geometry sanitization, slender feature culling,
    occlusion face culling, QEM decimation, material slot consolidation, normal
    reprojection, and kinematic bone pruning.

    Args:
        context: Active Blender execution context.
        props: LODToolSettings instance for active asset or scene.
        mesh_objs: List of source LOD0 mesh objects to decimate.
        armature_obj: Optional associated armature object.
        base_name: Resolved base name for the asset.
        only_out_of_sync: When True, skips already baked in-sync tiers.

    Returns:
        tuple[bool, str]: (Success status, descriptive user-facing message).
    """
    if not bpy or not context:
        return True, "Blender context not available."

    if not mesh_objs:
        return False, f"No mesh objects found for asset '{base_name}'."

    if not props:
        return False, "LOD tool settings not provided."

    orig_pose_pos = None
    arm_data = cast("bpy.types.Armature | None", armature_obj.data if armature_obj else None)
    if arm_data:
        orig_pose_pos = arm_data.pose_position
        arm_data.pose_position = "REST"

    bdata = blend_data
    shared_ref_merged_obj = None
    try:
        base_name = base_name.split("_LOD")[0]

        # 1. Resolve Root Collection or Auto-Wrap Loose Objects
        src_coll = None
        if (
            context.collection
            and context.collection != context.scene.collection
            and context.collection.name == base_name
        ):
            src_coll = context.collection
        elif mesh_objs and mesh_objs[0].users_collection:
            for c in mesh_objs[0].users_collection:
                if c.name in (base_name, f"{base_name}_LOD0") and c != context.scene.collection:
                    src_coll = c
                    break

        if not src_coll or src_coll.name not in (base_name, f"{base_name}_LOD0"):
            wrap_objs = list(mesh_objs)
            if armature_obj and armature_obj not in wrap_objs:
                wrap_objs.append(armature_obj)
            src_coll, root_pivot = CollectionCloneDAG.wrap_loose_objects_into_root_collection(
                wrap_objs, base_name, scene=context.scene, context=context, blend_data=bdata
            )
        else:
            root_pivot, _, _, _ = PivotPreservationEngine.identify_pivots_and_sockets(src_coll)

        all_coords = []
        for obj in mesh_objs:
            obj_data = cast("bpy.types.Mesh | None", obj.data)
            if obj.bound_box and Vector is not None:
                all_coords.extend([obj.matrix_world @ Vector(b) for b in obj.bound_box])
            elif obj_data and obj_data.vertices:
                all_coords.extend([obj.matrix_world @ v.co for v in obj_data.vertices])
        _, radius = compute_bounding_sphere(all_coords)

        render = context.scene.render
        cam = context.scene.camera
        cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
        sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
        aspect_ratio = render.resolution_x / max(1, render.resolution_y)
        fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

        lods_list = list(props.lods)
        max_influences = int(props.max_bone_influences)

        # Build Sibling Collections list
        all_tier_collections: list[bpy.types.Collection | None] = [src_coll]
        for i in range(1, len(lods_list)):
            tier_c = CollectionCloneDAG.get_or_create_sibling_collection(
                src_coll, i, base_name, scene=context.scene, blend_data=bdata
            )
            all_tier_collections.append(tier_c)

        updated_tier_count = 0
        valid_tier_collections = [c for c in all_tier_collections if c is not None]

        # Safe View Layer Scoper
        with LayerCollectionGuard(context.view_layer, valid_tier_collections):
            for i, tier in enumerate(lods_list):
                if i == 0:
                    tier_tris, tier_mats = _compute_lod0_stats(mesh_objs)
                    tier.actual_tris = tier_tris
                    tier.actual_triangles = tier_tris
                    tier.mat_slots_count = tier_mats
                    tier.generated_obj = mesh_objs[0] if mesh_objs else None
                    tier.state = "SOURCE"
                    continue

                # Check if tier is already baked and in sync when only_out_of_sync is requested
                last_target = float(tier.last_baked_target_pct)
                tier_coll = all_tier_collections[i]
                has_mesh_in_scene = bool(tier_coll and tier_coll.objects)
                is_in_sync = has_mesh_in_scene and last_target > 0.0 and abs(tier.target_tris_pct - last_target) <= 0.01
                if only_out_of_sync and is_in_sync:
                    continue

                updated_tier_count += 1

                # Sibling Collection Tier (LOD1..k)
                dag_info = CollectionCloneDAG.clone_collection_hierarchy(
                    src_coll,
                    tier_coll,
                    i,
                    base_name,
                    armature_obj=armature_obj,
                    pivot_obj=root_pivot,
                    context=context,
                    blend_data=bdata,
                )
                tier_pivot = dag_info.get("pivot")

                s_frac = tier.screen_size_pct / 100.0
                tolerances = compute_coupled_tolerances(radius, s_frac, float(props.tau_sse), render.resolution_y)
                hierarchy_mode = str(props.hierarchy_mode)
                should_merge = i >= 1 and (
                    bool(props.consolidate_hierarchy)
                    or hierarchy_mode == "MERGE_ALL"
                    or (hierarchy_mode == "MERGE_AT_TIER" and i >= int(props.merge_start_tier))
                )

                if should_merge and len(mesh_objs) > 1:
                    if shared_ref_merged_obj is None:
                        try:
                            shared_ref_merged_name = "__OM_Ref_Merged_LOD0_Shared__"
                            shared_ref_merged_obj = MeshMergeEngine.consolidate_and_merge_meshes(
                                mesh_objs,
                                shared_ref_merged_name,
                                armature_obj=armature_obj,
                                pivot_obj=root_pivot,
                                blend_data=bdata,
                            )
                        except (RuntimeError, ValueError, AttributeError) as exc:
                            logger.debug("Failed creating shared ref_merged_obj: %s", exc)
                            shared_ref_merged_obj = None

                    tris, mats, slender_cull, gen_obj = _process_merged_tier(
                        tier_coll=tier_coll,
                        tier_in=tier,
                        tier_idx=i,
                        base_name=base_name,
                        mesh_objs=mesh_objs,
                        armature_obj=armature_obj,
                        tier_pivot=tier_pivot,
                        tolerances=tolerances,
                        props_in=props,
                        render_in=render,
                        radius=radius,
                        fov_v=fov_v,
                        max_influences=max_influences,
                        ref_merged_obj=shared_ref_merged_obj,
                        context=context,
                        blend_data=bdata,
                    )
                else:
                    tris, mats, slender_cull, gen_obj = _process_unmerged_tier(
                        tier_coll=tier_coll,
                        tier_in=tier,
                        tier_idx=i,
                        base_name=base_name,
                        mesh_objs=mesh_objs,
                        armature_obj=armature_obj,
                        tier_pivot=tier_pivot,
                        root_pivot=root_pivot,
                        tolerances=tolerances,
                        props_in=props,
                        render_in=render,
                        radius=radius,
                        fov_v=fov_v,
                        max_influences=max_influences,
                        context=context,
                        blend_data=bdata,
                    )

                if props is not None:
                    props.last_culled_slender_count = int(props.last_culled_slender_count) + slender_cull
                tier.actual_tris = tris
                tier.actual_triangles = tris
                tier.mat_slots_count = mats
                tier.generated_obj = gen_obj
                tier.last_baked_target_pct = tier.target_tris_pct
                tier.last_baked_screen_pct = tier.screen_size_pct
                tier.state = "BAKED"

        if len(lods_list) > 0 and props is not None:
            base_tris_val = lods_list[0].actual_tris or lods_list[0].target_tris or 1
            final_tris_val = lods_list[-1].actual_tris or lods_list[-1].target_tris or 1
            reduction_pct = max(0.0, (1.0 - final_tris_val / float(base_tris_val)) * 100.0)

            props.last_generated_base_tris = base_tris_val
            props.last_generated_final_tris = final_tris_val
            props.last_generated_reduction_pct = reduction_pct
            props.last_generated_tier_count = len(lods_list)

        if bool(props.enable_impostor_lod):
            try:
                ops = getattr(bpy, "ops", None)
                lod_ops = getattr(ops, "lod_tool", None) if ops else None
                if lod_ops and hasattr(lod_ops, "generate_impostor"):
                    lod_ops.generate_impostor()
            except (RuntimeError, AttributeError, TypeError) as exc:
                logger.debug("Automatic impostor generation skipped: %s", exc)

        if only_out_of_sync:
            msg = f"Successfully updated {updated_tier_count} out-of-sync LOD tier(s) for '{base_name}'"
        else:
            msg = f"Successfully generated {len(lods_list)} Sibling LOD Collections for '{base_name}'"
        return True, msg

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
        logger.error("LOD generation failed: %s", exc, exc_info=True)
        return False, f"LOD generation failed: {exc}"

    finally:
        bdata_objs = bdata.objects if bdata else None
        if shared_ref_merged_obj and bdata_objs:
            ref_mesh = cast("bpy.types.Mesh | None", shared_ref_merged_obj.data)
            try:
                bdata_objs.remove(shared_ref_merged_obj, do_unlink=True)
                bdata_meshes = bdata.meshes if bdata else None
                if ref_mesh and ref_mesh.users == 0 and bdata_meshes:
                    bdata_meshes.remove(ref_mesh)
            except (RuntimeError, ReferenceError, AttributeError) as exc:
                logger.debug("Cleanup shared_ref_merged_obj exception: %s", exc)

        if arm_data and orig_pose_pos and hasattr(arm_data, "pose_position"):
            arm_data.pose_position = orig_pose_pos


__all__ = ["generate_all_lods"]
