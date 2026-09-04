"""
Blender PropertyGroups and Scene Settings for OmniMesh.
Maintains data models for LOD tiers, screen metrics, collision hulls, rigging, PBR textures,
engine presets, mesh cleanup, material cleanup, impostors, PBR importer, live simulation, and live engine bridges.
Supports both Scene-Level project globals, Per-Object persistent geometric configurations, and Collection-Based LOD hierarchies.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
    from bpy.props import (
        BoolProperty,
        CollectionProperty,
        EnumProperty,
        FloatProperty,
        FloatVectorProperty,
        IntProperty,
        PointerProperty,
        StringProperty,
    )
    from bpy.types import PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def BoolProperty(**kwargs: Any) -> Any:
        return None

    def CollectionProperty(**kwargs: Any) -> Any:
        return None

    def EnumProperty(**kwargs: Any) -> Any:
        return None

    def FloatProperty(**kwargs: Any) -> Any:
        return None

    def FloatVectorProperty(**kwargs: Any) -> Any:
        return None

    def IntProperty(**kwargs: Any) -> Any:
        return None

    def PointerProperty(**kwargs: Any) -> Any:
        return None

    def StringProperty(**kwargs: Any) -> Any:
        return None


class LODLevelItem(PropertyGroup):
    """Data model representing a single generated or configured LOD tier."""

    name: StringProperty(name="Tier Name", default="LOD0")
    level_index: IntProperty(name="Level Index", default=0, min=0, max=7)
    lod_index: IntProperty(name="LOD Index", default=0, min=0, max=7)
    screen_size_pct: FloatProperty(
        name="Screen Size %",
        default=100.0,
        min=0.01,
        max=100.0,
        subtype="PERCENTAGE",
        precision=1,
        description="On-screen coverage percentage before transitioning to the next tier",
    )
    distance_m: FloatProperty(
        name="Switch Distance (m)",
        default=0.0,
        min=0.0,
        precision=2,
        description="Calculated camera distance for this tier transition",
    )
    triangle_target: IntProperty(name="Target Tris", default=0, min=0)
    target_tris: IntProperty(name="Target Tris", default=0, min=0)
    actual_triangles: IntProperty(name="Actual Tris", default=0, min=0)
    actual_tris: IntProperty(name="Actual Tris", default=0, min=0)
    reduction_pct: FloatProperty(name="Reduction %", default=0.0, precision=1)
    mat_slots_count: IntProperty(name="Material Slots", default=0, min=0)
    delta_world: FloatProperty(name="Allowed Error (m)", default=0.0, min=0.0, precision=4)
    generated_obj: PointerProperty(name="Mesh Object", type=bpy.types.Object if bpy else object)


def update_bridge_status_cached(self: Any, context: Any) -> None:
    """Non-blocking status update hook for project directory changes."""
    if not context or not hasattr(context, "scene"):
        return
    try:
        if __package__:
            from ..bridges.manager import BridgeManager
        else:
            from bridges.manager import BridgeManager

        props = context.scene.lod_tool
        engine = props.target_engine
        proj_dir = props.engine_project_path
        if not proj_dir:
            props.bridge_status_text = "Project Path not set"
            return

        is_ready, msg = BridgeManager.ping_engine(engine, proj_dir)
        props.bridge_status_text = msg if is_ready else f"Not Ready: {msg}"
    except Exception as exc:
        logger.debug("Bridge status refresh: %s", exc)


class LODToolSettings(PropertyGroup):
    """
    Central PropertyGroup holding OmniMesh configuration and state.
    Attached to both Scene (for project-wide pipeline globals) and Object (for per-asset geometry persistence).
    """

    # Source Scope Architecture (Selection vs Collection Mode)
    lod_generation_source: EnumProperty(
        name="Source Scope",
        items=[
            ("SELECTION", "Selected Objects", "Generate LODs from selected mesh objects"),
            (
                "COLLECTION",
                "Collection Hierarchy",
                "Generate LODs from entire active collection hierarchy (e.g. Model, Fuselage)",
            ),
        ],
        default="SELECTION",
        description="Whether to generate LODs from active selection or an entire collection hierarchy",
    )
    source_collection_name: StringProperty(
        name="Source Collection",
        default="",
        description="Name of the root LOD0 collection to process in Collection Mode",
    )
    preserve_pivot_empty: BoolProperty(
        name="Preserve Pivot Empty",
        default=True,
        description="Detect and preserve Pivot/Root empty transforms across LOD collections and exports",
    )

    # Per-Object Metadata & Root Linkage
    is_configured: BoolProperty(name="Is Configured", default=False)
    is_generated_lod: BoolProperty(name="Is Generated Derivative", default=False)
    lod_root_object: PointerProperty(name="Root Master Asset", type=bpy.types.Object if bpy else object)
    lod_index: IntProperty(name="Derivative Tier Index", default=0, min=0, max=7)
    bounding_radius: FloatProperty(name="Bounding Radius", default=1.0, min=0.0)
    bounding_center: FloatVectorProperty(name="Bounding Center", size=3, default=(0.0, 0.0, 0.0))
    base_triangles: IntProperty(name="Base Triangles", default=0, min=0)
    screen_coverage_lod0: FloatProperty(name="LOD0 Screen Coverage %", default=100.0, min=0.0, max=100.0)

    # Preflight Inspection & Base Mesh Hygiene Properties
    preflight_inspected: BoolProperty(name="Preflight Inspected", default=False)
    preflight_summary_text: StringProperty(name="Preflight Summary", default="Not Inspected")
    preflight_loose_verts: IntProperty(name="Loose Vertices", default=0)
    preflight_degenerate_tris: IntProperty(name="Degenerate Triangles", default=0)
    preflight_unapplied_scale: BoolProperty(name="Unapplied Scale Detected", default=False)
    preflight_missing_materials: IntProperty(name="Missing Material Slots", default=0)
    preflight_is_clean: BoolProperty(name="Mesh Clean", default=False)
    sanitize_merge_epsilon: FloatProperty(
        name="Merge Tolerance (m)",
        default=0.0001,
        min=0.00001,
        max=0.01,
        precision=5,
        description="Maximum distance between coincident vertices to merge during base mesh sanitization",
    )

    # Target Engine Presets
    target_engine: EnumProperty(
        name="Target Engine",
        items=[
            ("MSFS_2024", "MSFS 2024 (glTF + XML)", "Microsoft Flight Simulator 2024 glTF and ModelInfo XML standard"),
            ("UE5", "Unreal Engine 5 (FBX)", "Epic Games Unreal Engine 5 LODGroup FBX hierarchy"),
            ("UNITY_6", "Unity 6 (FBX)", "Unity Technologies LOD Group FBX naming standard"),
            ("GODOT_4", "Godot 4 (glTF)", "Godot Engine 4.x visibility range glTF metadata standard"),
        ],
        default="MSFS_2024",
        description="Target engine determines naming conventions, metadata hierarchy, texture packing, and export file formats",
        update=update_bridge_status_cached,
    )

    # Asset Category Presets
    asset_category: EnumProperty(
        name="Asset Category",
        items=[
            ("HERO_CHARACTER", "Hero Character / Aircraft", "Dense primary focus asset (Up to 6 LODs)"),
            ("PROP", "General Prop / Machinery", "Standard environment prop (Up to 4 LODs)"),
            ("FOLIAGE", "Foliage & Nature", "Aggressive planar simplification and alpha preserve (Up to 5 LODs)"),
            (
                "BUILDING",
                "Building & Architecture",
                "Planar dissolve with structural silhouette locking (Up to 4 LODs)",
            ),
            ("MICRO_DEBRIS", "Micro-Debris / Clutter", "Rapid decimation down to dissolution (Up to 2 LODs)"),
        ],
        default="PROP",
        description="Selects default error tolerances, decimation curve exponent, and island culling factors",
    )

    # Progression Curve Mode
    progression_mode: EnumProperty(
        name="Tier Progression",
        items=[
            ("EXPONENTIAL", "Exponential (Geometric)", "Standard engine curve (100% -> 50% -> 25% -> 12.5%)"),
            ("LOGARITHMIC", "Logarithmic (Smooth)", "Preserves closer fidelity longer before rapid decay"),
            ("AGGRESSIVE", "Aggressive (Performance)", "Rapid reduction for mobile, VR, or dense sim crowds"),
            ("LINEAR", "Linear (Uniform)", "Uniform step distribution"),
        ],
        default="EXPONENTIAL",
        description="Mathematical curve used to compute automatic screen size and triangle budgets",
    )

    lod_count: IntProperty(
        name="LOD Count",
        default=4,
        min=2,
        max=7,
        description="Total number of LOD tiers to generate (including base LOD0)",
    )
    num_lods: IntProperty(
        name="LOD Count",
        default=7,
        min=2,
        max=8,
        description="Number of LOD tiers",
    )
    cull_screen_size_pct: FloatProperty(
        name="Cull Screen Size (%)",
        default=0.5,
        min=0.01,
        max=10.0,
        precision=2,
        subtype="PERCENTAGE",
    )
    preserve_slot_indexing: BoolProperty(name="Preserve Slot Indices", default=True)

    # Error Metrics and Screen Parameters
    tau_sse: FloatProperty(
        name="Error Bound Factor",
        default=0.8,
        min=0.1,
        max=5.0,
        precision=2,
        description="Screen-Space Error tolerance multiplier",
    )
    preserve_silhouette: BoolProperty(
        name="Preserve Silhouettes",
        default=True,
        description="Weight decimation to protect high-curvature silhouette and boundary edges",
    )
    pin_uv_seams: BoolProperty(
        name="Pin UV Seams",
        default=True,
        description="Locks UV boundary edges from collapsing to eliminate texture seam popping",
    )
    pin_material_borders: BoolProperty(
        name="Pin Material Borders",
        default=True,
        description="Prevents edges on material slot transitions from warping",
    )

    # Mesh Cleanup & Topology Repair Settings
    auto_sanitize_before_lod: BoolProperty(
        name="Auto-Sanitize Before LOD",
        default=True,
        description="Automatically run safe Tier 0 geometric hygiene before generating LOD tiers",
    )
    cleanup_apply_modifiers: BoolProperty(
        name="Apply Modifiers (Bake Viewport)",
        default=False,
        description="Bake procedural modifier stacks using Viewport settings into base geometry before topology repair (Opt-In)",
    )
    cleanup_sync_viewport_settings: BoolProperty(
        name="Sync Viewport to Render Settings",
        default=True,
        description="Synchronize modifier render settings (e.g. render_levels) to viewport settings before applying",
    )
    cleanup_enable_weld: BoolProperty(
        name="Merge Close Vertices",
        default=False,
        description="Weld coincident vertices within tolerance (Disabled by default to protect intentional panel seams)",
    )
    cleanup_weld_distance: FloatProperty(
        name="Weld Distance",
        default=0.0005,
        min=0.00001,
        max=0.05,
        precision=5,
        unit="LENGTH",
        description="Maximum distance between merged vertices",
    )
    cleanup_enable_split_non_manifold: BoolProperty(
        name="Repair Non-Manifold & Bowties",
        default=True,
        description="Split non-manifold bowtie pinch points and edges with >2 linked faces",
    )
    cleanup_enable_fill_holes: BoolProperty(
        name="Fill Small Holes",
        default=False,
        description="Detect and seal open boundary loops with <= Max Edges (with mandatory local beauty triangulation)",
    )
    cleanup_hole_max_edges: IntProperty(
        name="Max Hole Edges",
        default=4,
        min=3,
        max=16,
        description="Maximum edge count of open loops to fill",
    )
    cleanup_enable_triangulate_ngons: BoolProperty(
        name="Triangulate N-Gons",
        default=False,
        description="Triangulate polygons with >4 vertices during cleanup (Note: N-gons are automatically triangulated on engine export)",
    )
    cleanup_normal_policy: EnumProperty(
        name="Normal Alignment",
        items=[
            (
                "MANIFOLD_ONLY",
                "Manifold Shells Only (Safe)",
                "Recalculate outward normals only on closed 2-manifold volumes (Safe for foliage/cards)",
            ),
            ("FORCE_ALL", "Force All Outward (Destructive)", "Force flood-fill recalculation across entire mesh"),
            (
                "OFF",
                "Keep Intact (Safe for CAD)",
                "Do not alter face normal winding (Safe for CAD custom split normals)",
            ),
        ],
        default="MANIFOLD_ONLY",
        description="Face normal orientation policy",
    )
    last_cleanup_summary: StringProperty(name="Cleanup Summary", default="")

    # Material Cleanup & Slot Consolidation Settings
    mat_cleanup_purge_unused_slots: BoolProperty(
        name="Purge Empty & Unused Slots",
        default=True,
        description="Remove slots with no material assigned or zero polygon references (Safe)",
    )
    mat_cleanup_deduplicate_slots: BoolProperty(
        name="Deduplicate Repeated Slots",
        default=True,
        description="Merge duplicate slots pointing to identical materials on the same mesh (Safe)",
    )
    mat_cleanup_merge_duplicate_datablocks: BoolProperty(
        name="Merge Duplicate Materials (AST Hash)",
        default=True,
        description="Merge identical material datablocks (e.g. Mat.001) using deep SHA-256 node graph hashing (Safe)",
    )
    mat_cleanup_remove_orphan_nodes: BoolProperty(
        name="Remove Dead Shader Nodes",
        default=True,
        description="Remove disconnected and unused image texture nodes in material graphs (Safe)",
    )
    mat_cleanup_enable_micro_consolidation: BoolProperty(
        name="Consolidate Micro-Materials",
        default=False,
        description="Reassign surfaces < threshold % into dominant material (Exempts Emissive, Glass, Decals)",
    )
    mat_cleanup_micro_area_pct: FloatProperty(
        name="Micro Threshold %",
        default=0.5,
        min=0.01,
        max=5.0,
        precision=2,
        description="Surface area threshold percentage for micro-material consolidation",
    )
    mat_cleanup_repair_missing_textures: BoolProperty(
        name="Repair Missing Textures",
        default=False,
        description="Replace missing/broken image filepaths with safe procedural PBR defaults (Critical)",
    )
    mat_cleanup_purge_orphans_blendfile: BoolProperty(
        name="Purge Orphan Materials from .blend",
        default=False,
        description="Permanently delete unused zero-user materials from the Blender file (Critical)",
    )
    last_material_cleanup_summary: StringProperty(name="Material Cleanup Summary", default="")

    # PBR Texture Set Importer Settings
    pbr_import_ao_mode: EnumProperty(
        name="AO Mode",
        items=[
            ("MULTIPLY", "Multiply into Base Color (EEVEE/Cycles)", "Multiply AO map directly into Base Color texture"),
            (
                "SEPARATE",
                "Keep Separate (Game Engine Ready)",
                "Do not blend AO into Base Color (preserves glTF/FBX parity)",
            ),
        ],
        default="MULTIPLY",
        description="How Ambient Occlusion maps are wired into the shader graph",
    )
    pbr_import_preserve_existing: BoolProperty(
        name="Preserve Existing Nodes",
        default=False,
        description="Preserve existing non-PBR shader nodes in material when importing texture sets",
    )
    last_pbr_import_summary: StringProperty(name="PBR Import Summary", default="")

    # Billboard Impostor Generator Settings
    impostor_mode: EnumProperty(
        name="Impostor Mode",
        items=[
            (
                "CROSS_QUADS",
                "Cross-Quads (2-Plane '+', 4 Tris)",
                "Universal zero-shader billboard standard for all engines (MSFS, UE5, Unity, Godot)",
            ),
            (
                "STAR_QUADS",
                "Star-Quads (3-Plane '*', 6 Tris)",
                "High-fidelity 3D volume for dense trees and round props",
            ),
            (
                "OCTAHEDRAL_HEMI",
                "Octahedral (Upper Hemisphere)",
                "1 Quad camera billboard with 8x8 / 12x12 upper-hemisphere atlas",
            ),
            (
                "OCTAHEDRAL_SPHERE",
                "Octahedral (Full Sphere)",
                "1 Quad camera billboard with 8x8 / 12x12 full 360 degree sphere atlas",
            ),
        ],
        default="CROSS_QUADS",
        description="Billboard geometry type and multi-angle projection layout",
    )
    impostor_resolution: EnumProperty(
        name="Atlas Resolution",
        items=[
            ("1024", "1024 x 1024 (1K)", "1024px square atlas"),
            ("2048", "2048 x 2048 (2K)", "2048px square atlas"),
            ("4096", "4096 x 4096 (4K)", "4096px square atlas"),
        ],
        default="2048",
        description="Texture resolution for baked Impostor PBR atlas maps",
    )
    impostor_replace_last_lod: BoolProperty(
        name="Use as Final LOD Tier",
        default=True,
        description="Automatically assign the generated Impostor billboard as the final LOD tier in the scene",
    )
    last_impostor_status: StringProperty(name="Last Impostor Status", default="")

    # Interior & Occlusion Geometry Removal Settings
    enable_occlusion_culling: BoolProperty(
        name="Cull Interior Geometry",
        default=True,
        description="Automatically detect and delete non-visible internal polygons (cockpit innards, unseen machinery)",
    )
    occlusion_lod_start: IntProperty(
        name="Cull From LOD",
        default=1,
        min=1,
        max=6,
        description="LOD tier at which interior occlusion removal begins (LOD0 is strictly preserved)",
    )
    occlusion_ray_density: IntProperty(
        name="Ray Samples",
        default=16,
        min=4,
        max=64,
        description="Number of stratified ingress and egress raycast samples per surface cluster",
    )
    occlusion_evaluate_alpha: BoolProperty(
        name="Evaluate Transparency",
        default=True,
        description="Analyze glass shaders and alpha-cutout textures to allow rays to penetrate windows and see interiors",
    )
    last_culled_faces_count: IntProperty(name="Last Culled Faces", default=0)
    last_culled_islands_count: IntProperty(name="Last Culled Islands", default=0)

    # Sub-Pixel Slender & Thin Feature Culling Settings (Directly coupled to SSE Error Bound)
    enable_slender_culling: BoolProperty(
        name="Cull Sub-Pixel Cables & Railings",
        default=True,
        description="Automatically remove sub-pixel thin cables, railings, and wires using the LOD Screen-Space Error Bound",
    )
    last_culled_slender_count: IntProperty(name="Last Culled Slender Features", default=0)

    # Multi-Convex Collision Hull Generator Settings
    collision_decomposition_mode: EnumProperty(
        name="Decomposition Mode",
        items=[
            (
                "PER_OBJECT",
                "Per-Object Area Weighted",
                "Decomposes each selected object with budget weighted by surface area",
            ),
            (
                "CONSOLIDATED",
                "Consolidated Assembly",
                "Decomposes entire selection assembly into a unified convex hull cluster",
            ),
        ],
        default="PER_OBJECT",
        description="How multi-mesh selections are decomposed into collision hulls",
    )
    collision_hull_count: IntProperty(
        name="Hull Count",
        default=4,
        min=1,
        max=16,
        description="Target number of convex collision hulls to generate for concave assets",
    )
    collision_max_verts_per_hull: IntProperty(
        name="Max Verts / Hull",
        default=32,
        min=8,
        max=64,
        description="Clamps maximum vertices per convex hull for sub-millisecond physics ticks (PhysX/Jolt)",
    )
    collision_concavity_threshold: FloatProperty(
        name="Concavity Tolerance (m)",
        default=0.05,
        min=0.001,
        max=1.0,
        precision=3,
        description="Surface distance threshold to stop bisecting already convex sub-regions",
    )
    last_generated_collider_count: IntProperty(name="Last Collider Count", default=0)

    # Multi-Object Hierarchy & Merging Settings
    hierarchy_mode: EnumProperty(
        name="Hierarchy Mode",
        items=[
            ("PRESERVE", "Preserve Sub-Meshes", "Each selected object generates individual LOD copies"),
            (
                "MERGE_AT_TIER",
                "Merge at Distant Tiers",
                "Joins compatible sub-meshes into a single draw-call mesh at lower LODs",
            ),
        ],
        default="PRESERVE",
        description="How multi-mesh hierarchies and accessories are structured across LOD tiers",
    )
    merge_start_tier: IntProperty(
        name="Merge Start Tier",
        default=3,
        min=1,
        max=6,
        description="LOD tier at which compatible submeshes are merged into single draw-call meshes",
    )
    merge_lod_start: IntProperty(
        name="Merge From LOD",
        default=2,
        min=1,
        max=6,
        description="LOD tier at which compatible submeshes are merged into single draw-call meshes",
    )

    # Spatial Chunking & HLOD Settings (Large Assets / Scans / Terrains)
    enable_spatial_chunking: BoolProperty(
        name="Enable Spatial Chunking (Tiling)",
        default=False,
        description="Spatially partitions massive assets (terrains, buildings, scans) into 2.5D AABB grid tiles",
    )
    chunk_cell_size: FloatProperty(
        name="Chunk Cell Size (m)",
        default=32.0,
        min=1.0,
        max=1000.0,
        unit="LENGTH",
        description="Size of spatial partitioning grid cells in meters",
    )
    chunk_split_z: BoolProperty(
        name="Split Vertical Z-Axis",
        default=False,
        description="Splits geometry along vertical Z planes for high-rise buildings and cliffs",
    )
    chunk_cell_size_z: FloatProperty(
        name="Z Cell Size (m)",
        default=32.0,
        min=1.0,
        max=1000.0,
        unit="LENGTH",
        description="Vertical height of spatial grid cells in meters",
    )
    chunk_partitioning_mode: EnumProperty(
        name="Partitioning Mode",
        items=[
            ("UNIFORM_GRID", "Uniform 2.5D Grid", "Equal-sized spatial cells across the bounding box"),
            (
                "ADAPTIVE_CLUSTERING",
                "Adaptive Cell Clustering",
                "Clusters sparse adjacent cells into larger chunks to balance polycount without T-junctions",
            ),
        ],
        default="UNIFORM_GRID",
        description="Spatial chunk tiling strategy",
    )
    adaptive_cluster_target_polys: IntProperty(
        name="Max Polys / Cluster",
        default=50000,
        min=1000,
        max=5000000,
        description="Target maximum polygon budget per clustered chunk in adaptive mode",
    )
    enable_hlod: BoolProperty(
        name="Enable HLOD Merging",
        default=True,
        description="Merges tiles into a single unified mesh at distant LOD tiers, eliminating seams and draw calls",
    )

    hlod_start_tier: IntProperty(
        name="HLOD Start Tier",
        default=2,
        min=1,
        max=6,
        description="LOD tier at which chunk tiles are merged into unified HLOD mesh",
    )
    enable_scan_pre_remesh: BoolProperty(
        name="Pre-Process: Voxel Remesh",
        default=False,
        description="Optional voxel remesh cleanup for non-manifold photogrammetry scans (Destructive to UVs)",
    )
    scan_remesh_voxel_size: FloatProperty(
        name="Remesh Voxel Size (m)",
        default=0.05,
        min=0.005,
        max=1.0,
        precision=3,
        unit="LENGTH",
        description="Voxel grid resolution for surface reconstruction",
    )

    # Skeletal Rigging & Bone Pruning Settings
    normalize_bone_weights: BoolProperty(
        name="Normalize Bone Weights (Sum = 1.0)",
        default=True,
        description="Ensures all vertex deform weights strictly sum to 1.0",
    )
    max_bone_influences: EnumProperty(
        name="Max GPU Bone Influences",
        items=[
            ("4", "4 Influences (Standard GPU)", "Standard GPU vertex shader register limit (glTF, Mobile, Unity)"),
            ("8", "8 Influences (High-End)", "Unreal Engine 5 high-precision skinning"),
        ],
        default="4",
    )
    enable_bone_pruning: BoolProperty(
        name="Prune Sub-Pixel Bones",
        default=True,
        description="Recursively collapse sub-pixel leaf bones (fingers, facial bones) into parent bones on distant LODs",
    )
    purge_shape_keys: BoolProperty(
        name="Purge Shape Keys on Distance LODs",
        default=True,
        description="Strip facial blendshapes / shape keys on LOD >= 2 to save GPU memory and prevent mesh tearing",
    )
    prune_micro_weights: BoolProperty(
        name="Prune Micro-Weights (< 0.01)",
        default=True,
        description="Removes negligible bone influences to reduce GPU shader register bloat",
    )
    enable_leaf_bone_pruning: BoolProperty(
        name="Screen-Space Leaf-Bone Pruning",
        default=True,
        description="Reassigns sub-pixel leaf bone weights to parent bones on distant LODs",
    )
    leaf_bone_lod_start: IntProperty(
        name="Prune Bones From LOD",
        default=2,
        min=1,
        max=6,
        description="LOD tier from which leaf bone pruning begins",
    )
    purge_distant_shape_keys: BoolProperty(
        name="Purge Shape Keys on Distant LODs",
        default=True,
        description="Removes shape keys / morph targets on lower LODs to prevent decimation tearing",
    )

    # PBR Texture Channel Packing & Animation Baking Settings
    export_packed_textures: BoolProperty(
        name="Pack Engine PBR Textures",
        default=True,
        description="Extracts and packs PBR texture channels (_ORM for UE5/Godot, _MaskMap for Unity, _COMP for MSFS)",
    )
    texture_max_resolution: EnumProperty(
        name="Max Resolution",
        items=[
            ("4096", "4K (4096x4096)", "4K texture resolution"),
            ("2048", "2K (2048x2048)", "2K texture resolution"),
            ("1024", "1K (1024x1024)", "1K texture resolution"),
        ],
        default="2048",
        description="Maximum texture resolution for exported PBR channel sets",
    )
    bake_animations: BoolProperty(
        name="Bake Deform Rig Animations",
        default=True,
        description="Evaluates constraints and bakes deform bone matrices via depsgraph for engine export",
    )

    # Live Viewport LOD Simulator Settings
    is_simulator_running: BoolProperty(name="Simulator Running", default=False)
    is_simulator_active: BoolProperty(
        name="Live Distance Simulator",
        default=False,
        description="Real-time automatic LOD switching based on viewport and scene camera distance",
    )
    simulator_mode: EnumProperty(
        name="Simulator Mode",
        items=[
            ("LIVE_ORBIT", "Live Viewport Orbit", "Evaluate LOD distances dynamically as you orbit/zoom in Viewport"),
            (
                "VIRTUAL_SLIDER",
                "Virtual Distance Slider",
                "Interactive Unity-style distance/screen size slider override",
            ),
            ("CAMERA_LOCKED", "Lock to Scene Camera", "Evaluate LOD distances strictly from active Scene Camera"),
        ],
        default="LIVE_ORBIT",
    )
    virtual_preview_dist_m: FloatProperty(
        name="Virtual Distance (m)", default=10.0, min=0.1, max=5000.0, precision=1, subtype="DISTANCE"
    )
    virtual_screen_size_pct: FloatProperty(
        name="Virtual Screen Size (%)", default=100.0, min=0.01, max=100.0, precision=1, subtype="PERCENTAGE"
    )
    simulator_camera_mode: EnumProperty(
        name="Camera Source",
        items=[
            ("VIEWPORT", "3D Viewport Camera", "Tracks active 3D Viewport orbit/fly navigation camera"),
            ("ACTIVE_SCENE", "Active Scene Camera", "Tracks scene camera (bpy.context.scene.camera)"),
        ],
        default="VIEWPORT",
        description="Camera position reference used to calculate live switch distances",
    )
    virtual_distance_override: FloatProperty(
        name="Virtual Distance (m)",
        default=0.0,
        min=0.0,
        max=5000.0,
        precision=2,
        description="Interactive distance slider to preview LOD transitions without moving the camera",
    )
    show_viewport_hud: BoolProperty(
        name="Show Viewport HUD",
        default=True,
        description="Display real-time statistics HUD overlay in 3D Viewport",
    )

    # Post-Generation Summary Metrics
    last_generated_base_tris: IntProperty(name="Base Tris", default=0)
    last_generated_final_tris: IntProperty(name="Final Tris", default=0)
    last_generated_reduction_pct: FloatProperty(name="Reduction %", default=0.0, precision=1)
    last_generated_tier_count: IntProperty(name="Tier Count", default=0)

    is_preview_active: BoolProperty(name="Live Viewport Preview", default=False)
    preview_screen_pct: FloatProperty(
        name="Preview Screen %", default=100.0, min=0.01, max=100.0, subtype="PERCENTAGE", precision=1
    )
    forced_lod_index: IntProperty(name="Force LOD Tier", default=0, min=0, max=7)
    lods: CollectionProperty(type=LODLevelItem)
    active_lod_index: IntProperty(name="Active LOD Selection", default=0)
    export_directory: StringProperty(name="Export Directory", subtype="DIR_PATH", default="//Export/")
    export_base_name: StringProperty(name="Asset Base Name", default="")

    # Live Engine Bridge Properties
    engine_project_path: StringProperty(
        name="Engine Project Path",
        subtype="DIR_PATH",
        default="",
        description="Root path to active Unreal, Unity, MSFS Community, or Godot project folder",
        update=update_bridge_status_cached,
    )
    enable_live_sync: BoolProperty(
        name="Live Sync on Export",
        default=True,
        description="Automatically trigger engine re-import or compile package upon export",
    )
    bridge_status_text: StringProperty(
        name="Bridge Status",
        default="Bridge Ready",
        description="Cached status report from engine bridge connection handshake",
    )

    # A/B Split-Screen Comparison Preview Properties
    is_split_active: BoolProperty(
        name="Split View Active",
        default=False,
        description="Toggle dual-tier visual comparison overlay in 3D Viewport",
    )
    split_ratio: FloatProperty(
        name="Divider Ratio",
        default=0.5,
        min=0.05,
        max=0.95,
        subtype="FACTOR",
        precision=2,
        description="Horizontal screen split position (0.0 = Left only, 1.0 = Right only)",
    )
    split_compare_tier: IntProperty(
        name="Compare Tier",
        default=3,
        min=1,
        max=7,
        description="LOD tier index to compare against LOD0 Master",
    )

    # Batch Processing Properties
    batch_source_directory: StringProperty(
        name="Source Folder",
        subtype="DIR_PATH",
        default="",
        description="Directory containing 3D assets to process in batch",
    )
    batch_export_directory: StringProperty(
        name="Export Folder",
        subtype="DIR_PATH",
        default="",
        description="Destination folder for exported engine packages",
    )
    batch_recursive_scan: BoolProperty(
        name="Recursive Subfolders",
        default=True,
        description="Scan nested subdirectories for 3D asset files",
    )
    batch_file_formats: EnumProperty(
        name="Formats",
        items=[
            ("ALL", "All Supported (*.fbx, *.gltf, *.glb, *.obj, *.blend)", "Process all 3D formats"),
            ("FBX", "FBX (*.fbx)", "Process FBX files only"),
            ("GLTF", "glTF / GLB (*.gltf, *.glb)", "Process glTF/GLB files only"),
            ("BLEND", "Blender (*.blend)", "Process .blend files only"),
        ],
        default="ALL",
    )
    batch_status_text: StringProperty(name="Batch Status", default="Batch Ready")
    is_batch_running: BoolProperty(name="Batch Running", default=False)
    batch_total_count: IntProperty(name="Total Assets", default=0)
    batch_processed_count: IntProperty(name="Processed Assets", default=0)
    batch_current_asset: StringProperty(name="Current Asset", default="")


CLASSES = (
    LODLevelItem,
    LODToolSettings,
)


def register_properties() -> None:
    if not bpy:
        return
    for cls in CLASSES:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Safe unregister skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Safe register skipped %s: %s", getattr(cls, "__name__", "cls"), exc)
    try:
        bpy.types.Scene.lod_tool = PointerProperty(type=LODToolSettings)
        bpy.types.Object.lod_tool = PointerProperty(type=LODToolSettings)
    except Exception as exc:
        logger.debug("PointerProperty assignment exception: %s", exc)


def unregister_properties() -> None:
    if not bpy:
        return
    if hasattr(bpy.types.Scene, "lod_tool"):
        del bpy.types.Scene.lod_tool
    if hasattr(bpy.types.Object, "lod_tool"):
        del bpy.types.Object.lod_tool
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
