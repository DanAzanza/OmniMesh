"""
Master Pipeline Operators for OmniMesh LOD Analysis, Base Mesh Sanitization, Material Cleanup, PBR Import, Generation, and Viewport Preview.
"""

from __future__ import annotations

import math
import os
from typing import Any

try:
    import bmesh
    import bpy
    from bpy.props import CollectionProperty, StringProperty
    from bpy.types import Operator, OperatorFileListElement
except ImportError:
    bpy = None
    bmesh = None
    Operator = object
    OperatorFileListElement = object

    def StringProperty(**kwargs: Any) -> Any:
        return None

    def CollectionProperty(**kwargs: Any) -> Any:
        return None


try:
    from ..core.decimator import MeshDecimator
    from ..core.hierarchy import MeshMergeEngine
    from ..core.materials import MaterialOptimizer
    from ..core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
        generate_logarithmic_screen_tiers,
    )
    from ..core.normals import NormalManager
    from ..core.pbr_importer import BatchMaterialSlotMatcher, PBRSemanticClassifier, ShaderGraphBuilder
    from ..core.rigging import KinematicBonePruner, WeightSanitizer
    from ..core.sanitizer import MeshSanitizer
except (ImportError, ValueError):
    from core.decimator import MeshDecimator
    from core.hierarchy import MeshMergeEngine
    from core.materials import MaterialOptimizer
    from core.metrics import (
        compute_bounding_sphere,
        compute_coupled_tolerances,
        compute_distance_from_screen_size,
        compute_vertical_fov,
        generate_logarithmic_screen_tiers,
    )
    from core.normals import NormalManager
    from core.pbr_importer import BatchMaterialSlotMatcher, PBRSemanticClassifier, ShaderGraphBuilder
    from core.rigging import KinematicBonePruner, WeightSanitizer
    from core.sanitizer import MeshSanitizer


def is_object_valid(obj: Any) -> bool:
    """Safely verify object RNA validity against bpy.data.objects."""
    if obj is None:
        return False
    if bpy is None:
        return True
    try:
        return obj.name in bpy.data.objects and getattr(obj, "data", None) is not None
    except (ReferenceError, AttributeError):
        return False


def get_selected_mesh_objects(context: Any) -> list[Any]:
    """Retrieve all selected source mesh objects, filtering out derivative _LOD1..N objects."""
    if not context:
        return []
    raw_meshes = [
        obj
        for obj in getattr(context, "selected_objects", [])
        if is_object_valid(obj) and getattr(obj, "type", "") == "MESH"
    ]
    if (
        not raw_meshes
        and getattr(context, "active_object", None)
        and is_object_valid(context.active_object)
        and getattr(context.active_object, "type", "") == "MESH"
    ):
        raw_meshes = [context.active_object]

    # Prefer base source meshes over derivative LOD tiers if both are selected
    base_meshes = [obj for obj in raw_meshes if not any(f"_LOD{n}" in getattr(obj, "name", "") for n in range(1, 11))]
    return base_meshes if base_meshes else raw_meshes


def get_associated_armature(mesh_objs: list[Any]) -> Any:
    """Find armature parent or modifier attached to any of the provided mesh objects."""
    for obj in mesh_objs:
        if not is_object_valid(obj):
            continue
        if (
            getattr(obj, "parent", None)
            and is_object_valid(obj.parent)
            and getattr(obj.parent, "type", "") == "ARMATURE"
        ):
            return obj.parent
        for mod in getattr(obj, "modifiers", []):
            if getattr(mod, "type", "") == "ARMATURE" and is_object_valid(getattr(mod, "object", None)):
                return mod.object
    return None


class LOD_OT_inspect_lod0(Operator):
    """Preflight check: Inspect active mesh geometry for unapplied transforms, loose vertices, and non-manifold topology."""

    bl_idname = "lod_tool.inspect_lod0"
    bl_label = "Inspect LOD0"
    bl_description = (
        "Analyze base mesh health, check for unapplied scale, loose vertices, zero-area faces, and missing materials"
    )
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        total_loose_verts = 0
        total_degenerate_tris = 0
        has_unapplied_scale = False
        missing_mats = 0

        for obj in mesh_objs:
            # Check scale
            s = obj.scale
            if abs(s.x - 1.0) > 1e-4 or abs(s.y - 1.0) > 1e-4 or abs(s.z - 1.0) > 1e-4:
                has_unapplied_scale = True

            # Check materials
            if len(obj.material_slots) == 0 or any(slot.material is None for slot in obj.material_slots):
                missing_mats += 1

            # BMesh inspect
            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                for v in bm.verts:
                    if len(v.link_edges) == 0:
                        total_loose_verts += 1
                for f in bm.faces:
                    if f.calc_area() <= 1e-10:
                        total_degenerate_tris += 1
            finally:
                bm.free()

        props.preflight_inspected = True
        props.preflight_loose_verts = total_loose_verts
        props.preflight_degenerate_tris = total_degenerate_tris
        props.preflight_unapplied_scale = has_unapplied_scale
        props.preflight_missing_materials = missing_mats

        is_clean = (total_loose_verts == 0) and (total_degenerate_tris == 0) and (not has_unapplied_scale)
        props.preflight_is_clean = is_clean

        if is_clean:
            props.preflight_summary_text = f"✔ LOD0 Healthy ({len(mesh_objs)} mesh(es), All Transforms Applied)"
            self.report({"INFO"}, props.preflight_summary_text)
        else:
            issues = []
            if has_unapplied_scale:
                issues.append("Unapplied Scale")
            if total_loose_verts > 0:
                issues.append(f"{total_loose_verts} Loose Verts")
            if total_degenerate_tris > 0:
                issues.append(f"{total_degenerate_tris} Degenerates")
            if missing_mats > 0:
                issues.append(f"{missing_mats} Missing Mats")
            props.preflight_summary_text = f"⚠ Issues: {', '.join(issues)}"
            self.report({"WARNING"}, f"LOD0 Inspection: {', '.join(issues)}")

        return {"FINISHED"}


class LOD_OT_sanitize_base_mesh(Operator):
    """Sanitize and repair base mesh in-place: clean loose geometry, purge degenerates, merge coincident boundary vertices, and apply configured cleanup options."""

    bl_idname = "lod_tool.sanitize_base_mesh"
    bl_label = "Sanitize Base Mesh"
    bl_description = "Clean loose vertices, remove degenerate faces, repair non-manifold bowties, and weld duplicate vertices on base mesh"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        # Ensure object mode
        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        weld_dist = getattr(props, "cleanup_weld_distance", 0.0001) or getattr(props, "sanitize_merge_epsilon", 0.0001)
        enable_weld = getattr(props, "cleanup_enable_weld", False)
        enable_split_non_manifold = getattr(props, "cleanup_enable_split_non_manifold", True)
        enable_fill_holes = getattr(props, "cleanup_enable_fill_holes", False)
        hole_max_edges = getattr(props, "cleanup_hole_max_edges", 4)
        enable_triangulate_ngons = getattr(props, "cleanup_enable_triangulate_ngons", False)
        normal_policy = getattr(props, "cleanup_normal_policy", "MANIFOLD_ONLY")

        total_cleaned = 0

        for obj in mesh_objs:
            # Multi-user datablock protection: make single user if shared
            if obj.data.users > 1:
                obj.data = obj.data.copy()

            bm = bmesh.new()
            try:
                bm.from_mesh(obj.data)
                stats = MeshSanitizer.sanitize_mesh_full(
                    bm,
                    enable_weld=enable_weld,
                    epsilon_merge=weld_dist,
                    enable_split_non_manifold=enable_split_non_manifold,
                    enable_fill_holes=enable_fill_holes,
                    hole_max_edges=hole_max_edges,
                    enable_triangulate_ngons=enable_triangulate_ngons,
                    normal_recalc_policy=normal_policy,
                    world_matrix=obj.matrix_world,
                )
                bm.to_mesh(obj.data)
                obj.data.update()
                if isinstance(stats, dict):
                    total_cleaned += int(sum(v for v in stats.values() if isinstance(v, (int, float))))
                else:
                    total_cleaned += int(stats or 0)
            finally:
                bm.free()

        # Update preflight cache
        bpy.ops.lod_tool.inspect_lod0()

        self.report(
            {"INFO"}, f"Sanitized {len(mesh_objs)} mesh(es). Cleaned/repaired {total_cleaned} geometric elements."
        )
        return {"FINISHED"}


class LOD_OT_apply_transforms(Operator):
    """Apply scale and rotation transforms to selected mesh objects and ensure proper local origin."""

    bl_idname = "lod_tool.apply_transforms"
    bl_label = "Apply Transforms"
    bl_description = "Apply Scale and Rotation transforms to source meshes to prevent distortion during decimation"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        if context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

        for obj in mesh_objs:
            # If object is parented to armature, preserve rest-pose transform
            if obj.parent and obj.parent.type == "ARMATURE":
                continue
            with context.temp_override(active_object=obj, selected_editable_objects=[obj]):
                bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

        # Refresh preflight check
        bpy.ops.lod_tool.inspect_lod0()

        self.report({"INFO"}, f"Applied scale & rotation transforms to {len(mesh_objs)} mesh object(s).")
        return {"FINISHED"}


class LOD_OT_clean_and_repair_materials(Operator):
    """Execute material slot compaction, deduplication, AST hash merging, and micro-material consolidation."""

    bl_idname = "lod_tool.clean_and_repair_materials"
    bl_label = "Clean & Consolidate Materials"
    bl_description = "Clean empty slots, deduplicate materials, AST-hash merge datablocks, and fix missing textures"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bool(context and get_selected_mesh_objects(context))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        props = context.scene.lod_tool

        stats = MaterialOptimizer.clean_materials_full(
            mesh_objs=mesh_objs,
            purge_unused_slots=props.mat_cleanup_purge_unused_slots,
            deduplicate_slots=props.mat_cleanup_deduplicate_slots,
            merge_duplicate_datablocks=props.mat_cleanup_merge_duplicate_datablocks,
            remove_orphan_nodes=props.mat_cleanup_remove_orphan_nodes,
            enable_micro_consolidation=props.mat_cleanup_enable_micro_consolidation,
            micro_area_pct=props.mat_cleanup_micro_area_pct,
            repair_missing_textures=props.mat_cleanup_repair_missing_textures,
            purge_orphans_blendfile=props.mat_cleanup_purge_orphans_blendfile,
        )

        summary_msg = (
            f"Removed {stats['slots_removed']} unused/dup slots ({stats['faces_remapped']} faces remapped), "
            f"merged {stats['merged_datablocks']} duplicate materials, "
            f"cleaned {stats['orphan_nodes_removed']} dead nodes."
        )
        if stats["consolidated_slots"] > 0:
            summary_msg += f" Consolidated {stats['consolidated_slots']} micro-materials."
        if stats["repaired_textures"] > 0:
            summary_msg += f" Repaired {stats['repaired_textures']} missing textures."
        if stats["purged_orphans"] > 0:
            summary_msg += f" Purged {stats['purged_orphans']} orphan materials."

        props.last_material_cleanup_summary = summary_msg
        self.report({"INFO"}, f"✔ {summary_msg}")
        return {"FINISHED"}


class LOD_OT_import_pbr_set(Operator):
    """Import multi-selected PBR texture files and construct a complete Principled BSDF node graph."""

    bl_idname = "lod_tool.import_pbr_set"
    bl_label = "Import PBR Texture Set"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")  # type: ignore
    files: CollectionProperty(type=OperatorFileListElement)  # type: ignore

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy:
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        if not self.directory or not self.files:
            self.report({"WARNING"}, "No texture files selected.")
            return {"CANCELLED"}

        mesh_objs = get_selected_mesh_objects(context)
        active_obj = (
            context.active_object
            if context.active_object and context.active_object.type == "MESH"
            else (mesh_objs[0] if mesh_objs else None)
        )

        texture_map: dict[str, str] = {}
        sample_filename = ""
        for file_elem in self.files:
            fname = file_elem.name
            if not fname:
                continue
            full_path = os.path.join(self.directory, fname)
            sem_type = PBRSemanticClassifier.classify(fname)
            if sem_type:
                texture_map[sem_type] = full_path
                if not sample_filename:
                    sample_filename = fname

        if not texture_map:
            self.report({"WARNING"}, "Could not semantically classify any selected texture files.")
            return {"CANCELLED"}

        mat = None
        if active_obj and active_obj.active_material:
            mat = active_obj.active_material
        else:
            base_stem = PBRSemanticClassifier.clean_stem(sample_filename) or "PBR_Material"
            mat = bpy.data.materials.new(name=base_stem)
            if active_obj:
                if len(active_obj.material_slots) == 0:
                    active_obj.data.materials.append(mat)
                else:
                    active_obj.material_slots[active_obj.active_material_index].material = mat

        props = context.scene.lod_tool
        ShaderGraphBuilder.build_pbr_graph(
            material=mat,
            texture_map=texture_map,
            ao_mode=props.pbr_import_ao_mode,
            preserve_existing=props.pbr_import_preserve_existing,
        )

        summary = f"Configured '{mat.name}' with {len(texture_map)} PBR textures ({', '.join(texture_map.keys())})"
        props.last_pbr_import_summary = summary
        self.report({"INFO"}, f"✔ {summary}")
        return {"FINISHED"}


class LOD_OT_auto_match_pbr_folder(Operator):
    """Scan directory and automatically map all matching PBR texture sets to active mesh material slots."""

    bl_idname = "lod_tool.auto_match_pbr_folder"
    bl_label = "Auto-Match PBR Folder"
    bl_options = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")  # type: ignore

    def invoke(self, context: Any, event: Any) -> set[str]:
        if not bpy:
            return {"CANCELLED"}
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"FINISHED"}
        if not self.directory or not os.path.isdir(self.directory):
            self.report({"WARNING"}, "Invalid texture directory.")
            return {"CANCELLED"}

        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        matched_count = 0
        props = context.scene.lod_tool
        for obj in mesh_objs:
            mapping = BatchMaterialSlotMatcher.match_directory_to_slots(obj, self.directory)
            for slot in getattr(obj, "material_slots", []):
                if slot.material and slot.name in mapping and mapping[slot.name]:
                    ShaderGraphBuilder.build_pbr_graph(
                        material=slot.material,
                        texture_map=mapping[slot.name],
                        ao_mode=props.pbr_import_ao_mode,
                        preserve_existing=props.pbr_import_preserve_existing,
                    )
                    matched_count += 1

        summary = f"Matched and wired {matched_count} PBR material slots from '{os.path.basename(self.directory)}'"
        context.scene.lod_tool.last_pbr_import_summary = summary
        self.report({"INFO"}, f"✔ {summary}")
        return {"FINISHED"}


class LOD_OT_analyze_and_configure(Operator):
    """Analyze active mesh geometry and automatically calculate screen-space error LOD thresholds."""

    bl_idname = "lod_tool.analyze_and_configure"
    bl_label = "Auto-Configure Tiers"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bpy is not None and len(get_selected_mesh_objects(context)) > 0

    def execute(self, context: Any) -> set[str]:
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        if not mesh_objs:
            self.report({"WARNING"}, "No mesh objects selected.")
            return {"CANCELLED"}

        all_coords = []
        base_tris = 0
        total_mat_slots = 0

        for obj in mesh_objs:
            m_w = obj.matrix_world
            all_coords.extend([m_w @ v.co for v in obj.data.vertices])
            base_tris += len(obj.data.polygons)
            total_mat_slots += len(obj.material_slots)

        _, radius = compute_bounding_sphere(all_coords)

        if not props.export_base_name:
            primary_name = context.active_object.name if context.active_object else mesh_objs[0].name
            props.export_base_name = primary_name.split("_LOD")[0]

        render = context.scene.render
        aspect_ratio = render.resolution_x / max(1, render.resolution_y)
        cam = context.scene.camera
        cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
        sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
        fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

        if props.target_engine == "MSFS_2024":
            props.num_lods = 7
            screen_tiers = [100.0, 50.0, 25.0, 10.0, 5.0, 2.0, 0.5]
        else:
            screen_tiers = generate_logarithmic_screen_tiers(props.num_lods, props.cull_screen_size_pct)

        props.lods.clear()
        for i, s_pct in enumerate(screen_tiers):
            item = props.lods.add()
            item.name = f"LOD{i}"
            item.lod_index = i
            item.screen_size_pct = s_pct

            s_frac = s_pct / 100.0
            dist = compute_distance_from_screen_size(radius, s_frac, fov_v)
            tolerances = compute_coupled_tolerances(radius, s_frac, props.tau_sse, render.resolution_y)

            item.distance_m = dist
            item.delta_world = tolerances["delta_world"]
            item.target_tris = max(12, int(base_tris * tolerances["qem_ratio"]))
            item.triangle_target = item.target_tris
            item.mat_slots_count = total_mat_slots if i < 2 else max(1, total_mat_slots - (i - 1))

        props.active_lod_index = 0
        self.report(
            {"INFO"},
            f"Configured {len(props.lods)} LOD tiers for {len(mesh_objs)} meshes (Radius: {radius:.2f}m, Base Tris: {base_tris:,})",
        )
        return {"FINISHED"}


class LOD_OT_generate_all(Operator):
    """Generate all configured LOD tiers in scene collection with QEM simplification and normal reprojection."""

    bl_idname = "lod_tool.generate_all"
    bl_label = "Generate All LODs"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context: Any) -> bool:
        return bpy is not None and len(get_selected_mesh_objects(context)) > 0 and len(context.scene.lod_tool.lods) > 0

    def execute(self, context: Any) -> set[str]:
        props = context.scene.lod_tool
        mesh_objs = get_selected_mesh_objects(context)
        armature_obj = get_associated_armature(mesh_objs)

        orig_pose_pos = None
        if armature_obj and hasattr(armature_obj.data, "pose_position"):
            orig_pose_pos = armature_obj.data.pose_position
            armature_obj.data.pose_position = "REST"

        try:
            base_name = props.export_base_name or (
                context.active_object.name if context.active_object else mesh_objs[0].name
            )
            coll_name = f"{base_name}_LODs"
            target_coll = bpy.data.collections.get(coll_name)
            if not target_coll:
                target_coll = bpy.data.collections.new(coll_name)
                context.scene.collection.children.link(target_coll)

            for obj in mesh_objs:
                if not obj.parent or obj.parent.type != "ARMATURE":
                    bpy.context.view_layer.objects.active = obj
                    obj.select_set(True)
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

            all_coords = []
            for obj in mesh_objs:
                all_coords.extend([obj.matrix_world @ v.co for v in obj.data.vertices])
            _, radius = compute_bounding_sphere(all_coords)

            render = context.scene.render
            cam = context.scene.camera
            cam_angle = cam.data.angle if cam and cam.type == "CAMERA" else math.radians(60.0)
            sensor_fit = cam.data.sensor_fit if cam and cam.type == "CAMERA" else "AUTO"
            aspect_ratio = render.resolution_x / max(1, render.resolution_y)
            fov_v = compute_vertical_fov(cam_angle, aspect_ratio, sensor_fit)

            max_influences = int(props.max_bone_influences)
            generated_tier_objects = []

            for i, tier in enumerate(props.lods):
                s_frac = tier.screen_size_pct / 100.0
                tolerances = compute_coupled_tolerances(radius, s_frac, props.tau_sse, render.resolution_y)
                should_merge = props.hierarchy_mode == "MERGE_AT_TIER" and i >= props.merge_start_tier

                if should_merge and len(mesh_objs) > 1:
                    merged_name = f"{base_name}_LOD{i}"
                    existing = bpy.data.objects.get(merged_name)
                    if existing and existing not in mesh_objs:
                        bpy.data.objects.remove(existing, do_unlink=True)

                    tier_obj = MeshMergeEngine.consolidate_and_merge_meshes(mesh_objs, merged_name, armature_obj)
                    target_coll.objects.link(tier_obj)

                    bm = bmesh.new()
                    try:
                        bm.from_mesh(tier_obj.data)
                        MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])
                        pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                        MeshDecimator.apply_planar_limited_dissolve(bm, math.radians(tolerances["planar_angle_deg"]))
                        MeshDecimator.inject_curvature_weights(tier_obj, bm, pinned_verts)
                        bm.to_mesh(tier_obj.data)
                    finally:
                        bm.free()
                    tier_obj.data.update()

                    MeshDecimator.execute_decimate_qem(tier_obj, tolerances["qem_ratio"], use_curvature_weight=True)

                    if props.purge_shape_keys and i >= 2:
                        MeshDecimator.prepare_and_clean_shape_keys(tier_obj, purge=True)

                    if armature_obj and len(tier_obj.vertex_groups) > 0:
                        if props.enable_bone_pruning and i >= 2:
                            KinematicBonePruner.prune_kinematic_subtrees(
                                tier_obj,
                                armature_obj,
                                screen_distance_m=tier.distance_m,
                                fov_v_rad=fov_v,
                                resolution_y=render.resolution_y,
                                pixel_threshold=1.5,
                            )
                        WeightSanitizer.normalize_and_clamp_weights(tier_obj, max_influences=max_influences)

                    tier.actual_tris = len(tier_obj.data.polygons)
                    tier.actual_triangles = tier.actual_tris
                    tier.mat_slots_count = len(tier_obj.material_slots)
                    tier.generated_obj = tier_obj
                    generated_tier_objects.append(tier_obj)

                else:
                    tier_tris = 0
                    tier_mats = 0
                    for obj_idx, source_obj in enumerate(mesh_objs):
                        sub_name = f"{source_obj.name}_LOD{i}" if len(mesh_objs) > 1 else f"{base_name}_LOD{i}"
                        existing = bpy.data.objects.get(sub_name)
                        if existing and existing not in mesh_objs and existing != source_obj:
                            bpy.data.objects.remove(existing, do_unlink=True)

                        lod_obj = source_obj.copy()
                        lod_obj.data = source_obj.data.copy()
                        lod_obj.name = sub_name
                        lod_obj.data.name = f"{sub_name}_Mesh"
                        target_coll.objects.link(lod_obj)

                        if i == 0:
                            bm = bmesh.new()
                            try:
                                bm.from_mesh(lod_obj.data)
                                MeshSanitizer.clean_loose_and_degenerates(bm)
                                bm.to_mesh(lod_obj.data)
                            finally:
                                bm.free()
                        else:
                            if props.purge_shape_keys and i >= 2:
                                MeshDecimator.prepare_and_clean_shape_keys(lod_obj, purge=True)

                            bm = bmesh.new()
                            try:
                                bm.from_mesh(lod_obj.data)
                                MeshSanitizer.sanitize_mesh_full(bm, tolerances["epsilon_merge"], tolerances["w_crit"])
                                pinned_verts = MeshDecimator.tag_boundaries_and_uv_seams(bm)
                                MeshDecimator.apply_planar_limited_dissolve(
                                    bm, math.radians(tolerances["planar_angle_deg"])
                                )
                                MeshDecimator.inject_curvature_weights(lod_obj, bm, pinned_verts)
                                bm.to_mesh(lod_obj.data)
                            finally:
                                bm.free()
                            lod_obj.data.update()

                            MeshDecimator.execute_decimate_qem(
                                lod_obj, tolerances["qem_ratio"], use_curvature_weight=True
                            )

                            MaterialOptimizer.consolidate_micro_materials(
                                lod_obj,
                                area_crit=tolerances["area_crit"],
                                preserve_slot_indexing=props.preserve_slot_indexing,
                            )

                            NormalManager.reproject_custom_split_normals(lod_obj, source_obj, tolerances["delta_world"])

                            if armature_obj and len(lod_obj.vertex_groups) > 0:
                                if props.enable_bone_pruning and i >= 2:
                                    KinematicBonePruner.prune_kinematic_subtrees(
                                        lod_obj,
                                        armature_obj,
                                        screen_distance_m=tier.distance_m,
                                        fov_v_rad=fov_v,
                                        resolution_y=render.resolution_y,
                                        pixel_threshold=1.5,
                                    )
                                WeightSanitizer.normalize_and_clamp_weights(lod_obj, max_influences=max_influences)

                        lod_obj.data.update()
                        tier_tris += len(lod_obj.data.polygons)
                        tier_mats += len(lod_obj.material_slots)
                        if obj_idx == 0:
                            tier.generated_obj = lod_obj

                    tier.actual_tris = tier_tris
                    tier.actual_triangles = tier_tris
                    tier.mat_slots_count = tier_mats

            # Compute and record summary metrics
            if len(props.lods) > 0:
                base_tris_val = props.lods[0].actual_tris or props.lods[0].target_tris or 1
                final_tris_val = props.lods[-1].actual_tris or props.lods[-1].target_tris or 1
                reduction_pct = max(0.0, (1.0 - final_tris_val / float(base_tris_val)) * 100.0)

                props.last_generated_base_tris = base_tris_val
                props.last_generated_final_tris = final_tris_val
                props.last_generated_reduction_pct = reduction_pct
                props.last_generated_tier_count = len(props.lods)

            self.report(
                {"INFO"}, f"Generated {len(props.lods)} LOD tiers across {len(mesh_objs)} objects in '{coll_name}'"
            )
            return {"FINISHED"}
        finally:
            if armature_obj and orig_pose_pos and hasattr(armature_obj.data, "pose_position"):
                armature_obj.data.pose_position = orig_pose_pos


class LOD_OT_preview_tier(Operator):
    """Isolate and display selected LOD tier geometry in 3D Viewport."""

    bl_idname = "lod_tool.preview_tier"
    bl_label = "Preview Selected Tier"
    bl_options = {"REGISTER", "UNDO"}

    tier_index: bpy.props.IntProperty(default=0) if bpy else 0

    def execute(self, context: Any) -> set[str]:
        if not bpy:
            return {"FINISHED"}
        props = context.scene.lod_tool
        target_idx = self.tier_index
        base_name = props.export_base_name

        coll = bpy.data.collections.get(f"{base_name}_LODs")
        if coll:
            for obj in coll.objects:
                is_this_tier = f"_LOD{target_idx}" in obj.name
                obj.hide_viewport = not is_this_tier
                obj.hide_render = not is_this_tier

        props.active_lod_index = max(0, min(target_idx, len(props.lods) - 1)) if props.lods else 0
        return {"FINISHED"}


classes = (
    LOD_OT_inspect_lod0,
    LOD_OT_sanitize_base_mesh,
    LOD_OT_apply_transforms,
    LOD_OT_clean_and_repair_materials,
    LOD_OT_import_pbr_set,
    LOD_OT_auto_match_pbr_folder,
    LOD_OT_analyze_and_configure,
    LOD_OT_generate_all,
    LOD_OT_preview_tier,
)


def register_operators() -> None:
    if not bpy:
        return
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister_operators() -> None:
    if not bpy:
        return
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
