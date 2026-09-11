"""
OmniMesh Central Settings PropertyGroup.
Attached to Scene (for project-wide pipeline globals) and Object (for per-asset geometry persistence).
"""

from typing import Any

from .callbacks import (
    get_engine_import_preset_items,
    get_lod_preset_items,
    get_pbr_export_preset_items,
    get_pbr_import_preset_items,
    on_batch_mode_updated,
    on_batch_source_updated,
    on_enable_live_sync_updated,
    on_engine_import_directory_updated,
    on_engine_import_preset_updated,
    on_engine_project_path_updated,
    on_export_bit_depth_updated,
    on_export_directory_updated,
    on_export_naming_updated,
    on_export_preset_updated,
    on_export_strategy_updated,
    on_import_ao_mode_updated,
    on_import_directory_updated,
    on_import_path_mode_updated,
    on_import_preserve_updated,
    on_import_preset_updated,
    on_active_asset_updated,
    on_legacy_preset_updated,
    on_lod_budget_mode_updated,
    on_lod_preset_updated,
    on_target_engine_updated,
)
from .enums import (
    ASSET_CATEGORY_ITEMS,
    BATCH_FILE_FORMATS_ITEMS,
    CHUNK_PARTITIONING_MODE_ITEMS,
    CLEANUP_NORMAL_POLICY_ITEMS,
    COLLISION_DECOMPOSITION_MODE_ITEMS,
    ENGINE_IMPORT_MODEL_TARGET_ITEMS,
    HIERARCHY_MODE_ITEMS,
    IMPOSTOR_MODE_ITEMS,
    IMPOSTOR_RESOLUTION_ITEMS,
    LOD_GENERATION_SOURCE_ITEMS,
    LOD_PRESET_BUDGET_MODE_ITEMS,
    MAX_BONE_INFLUENCES_ITEMS,
    MSFS_GEAR_STATE_ITEMS,
    PBR_EXPORT_BIT_DEPTH_ITEMS,
    PBR_EXPORT_TEXTURE_STRATEGY_ITEMS,
    PBR_IMPORT_AO_MODE_ITEMS,
    PBR_IMPORT_PATH_MODE_ITEMS,
    PROGRESSION_MODE_ITEMS,
    SIMULATOR_CAMERA_MODE_ITEMS,
    SIMULATOR_MODE_ITEMS,
    TARGET_ENGINE_ITEMS,
    TEXTURE_MAX_RESOLUTION_ITEMS,
)
from .lod_properties import (
    LODLevelItem,
    LODPresetTierItem,
    on_lod_preset_property_modified,
    on_split_preview_updated,
)
from .pbr_properties import PBRExportMapItem, PBRMapItem

try:
    from ..utils import get_asset_enum_items
except (ImportError, ValueError):
    from ui.utils import get_asset_enum_items

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

    def _mock_prop(**kwargs: Any) -> Any:
        return None

    BoolProperty = CollectionProperty = EnumProperty = _mock_prop
    FloatProperty = FloatVectorProperty = IntProperty = PointerProperty = StringProperty = _mock_prop


class LODToolSettings(PropertyGroup):
    """
    Central PropertyGroup holding OmniMesh configuration and state.
    Attached to both Scene (for project-wide pipeline globals) and Object (for per-asset geometry persistence).
    """

    # Source Scope Architecture (Selection vs Collection Mode)
    lod_generation_source: EnumProperty(
        name="Source Scope",
        items=LOD_GENERATION_SOURCE_ITEMS,
        default="SELECTION",
        description="Whether to generate LODs from active selection or an entire collection hierarchy",
    )
    source_collection_name: StringProperty(
        name="Source Collection",
        default="",
        description="Name of the root LOD0 collection to process in Collection Mode",
    )
    active_asset: EnumProperty(
        name="Asset Collection",
        items=get_asset_enum_items,
        description="Target root asset collection for LOD configuration and generation",
        update=lambda self, context: on_active_asset_updated(self, context),
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
    preflight_loose_edges: IntProperty(name="Loose Edges", default=0)
    preflight_non_manifold_edges: IntProperty(name="Non-Manifold Edges", default=0)
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
        items=TARGET_ENGINE_ITEMS,
        default="MSFS_2024",
        description="Target engine determines naming conventions, metadata hierarchy, and export formats",
        update=on_target_engine_updated,
    )

    # Asset Category Presets
    asset_category: EnumProperty(
        name="Asset Category",
        items=ASSET_CATEGORY_ITEMS,
        default="PROP",
        description="Selects default error tolerances, decimation curve exponent, and island culling factors",
    )

    # Progression Curve Mode
    progression_mode: EnumProperty(
        name="Tier Progression",
        items=PROGRESSION_MODE_ITEMS,
        default="EXPONENTIAL",
        description="Mathematical curve used to compute automatic screen size and triangle budgets",
    )

    lod_count: IntProperty(name="LOD Count", default=4, min=2, max=7, description="Total LOD tiers to generate")
    num_lods: IntProperty(name="LOD Count", default=7, min=2, max=8, description="Number of LOD tiers")
    cull_screen_size_pct: FloatProperty(
        name="Cull Screen Size (%)", default=0.5, min=0.01, max=10.0, precision=2, subtype="PERCENTAGE"
    )
    preserve_slot_indexing: BoolProperty(name="Preserve Slot Indices", default=True)

    # Error Metrics and Screen Parameters
    tau_sse: FloatProperty(
        name="Visual Stability (SSE)",
        default=0.08,
        min=0.01,
        max=2.0,
        precision=2,
        subtype="PERCENTAGE",
        description="Screen-Space Error bound in percentage of screen height",
        update=on_lod_preset_property_modified,
    )
    preserve_silhouette: BoolProperty(
        name="Preserve Silhouettes", default=True, description="Legacy silhouette protection (deprecated)"
    )
    pin_uv_seams: BoolProperty(
        name="Pin UV Seams",
        default=True,
        description="Locks UV boundary edges from collapsing (always active)",
    )
    pin_material_borders: BoolProperty(
        name="Pin Material Borders",
        default=True,
        description="Prevents edges on material slot transitions from warping (always active)",
    )

    # Mesh Cleanup & Topology Repair Settings
    auto_sanitize_before_lod: BoolProperty(
        name="Auto-Sanitize Before LOD", default=True, description="Run safe Tier 0 hygiene before generating LOD tiers"
    )
    cleanup_auto_apply_transforms: BoolProperty(
        name="Auto-Apply Scale & Rotation",
        default=False,
        description="Apply scale and rotation transforms before mesh sanitization",
    )
    cleanup_apply_modifiers: BoolProperty(
        name="Apply Modifiers (Bake Viewport)",
        default=False,
        description="Bake procedural modifier stacks using Viewport settings into base geometry",
    )
    cleanup_sync_viewport_settings: BoolProperty(
        name="Sync Viewport to Render Settings",
        default=True,
        description="Synchronize modifier render settings to viewport settings before applying",
    )
    cleanup_enable_weld: BoolProperty(
        name="Merge Close Vertices", default=False, description="Weld coincident vertices within tolerance"
    )
    cleanup_weld_distance: FloatProperty(
        name="Weld Distance", default=0.0005, min=0.00001, max=0.05, precision=5, unit="LENGTH"
    )
    cleanup_enable_split_non_manifold: BoolProperty(
        name="Repair Non-Manifold & Bowties", default=True, description="Split non-manifold bowtie pinch points"
    )
    cleanup_enable_fill_holes: BoolProperty(
        name="Fill Small Holes", default=False, description="Detect and seal open boundary loops with <= Max Edges"
    )
    cleanup_hole_max_edges: IntProperty(
        name="Max Hole Edges", default=4, min=3, max=16, description="Maximum edge count of open loops to fill"
    )
    cleanup_enable_triangulate_ngons: BoolProperty(
        name="Triangulate N-Gons", default=False, description="Triangulate polygons with >4 vertices during cleanup"
    )
    cleanup_normal_policy: EnumProperty(
        name="Normal Alignment",
        items=CLEANUP_NORMAL_POLICY_ITEMS,
        default="MANIFOLD_ONLY",
        description="Face normal orientation policy",
    )
    last_cleanup_summary: StringProperty(name="Cleanup Summary", default="")

    # Material Cleanup & Slot Consolidation Settings
    mat_cleanup_purge_unused_slots: BoolProperty(
        name="Purge Empty & Unused Slots", default=True, description="Remove slots with no material assigned"
    )
    mat_cleanup_deduplicate_slots: BoolProperty(
        name="Deduplicate Repeated Slots",
        default=True,
        description="Merge duplicate slots pointing to identical materials",
    )
    mat_cleanup_merge_duplicate_datablocks: BoolProperty(
        name="Merge Duplicate Materials (AST Hash)",
        default=True,
        description="Merge identical material datablocks using deep SHA-256 node graph hashing",
    )
    mat_cleanup_remove_orphan_nodes: BoolProperty(
        name="Remove Dead Shader Nodes", default=True, description="Remove disconnected and unused image texture nodes"
    )
    mat_cleanup_enable_micro_consolidation: BoolProperty(
        name="Consolidate Micro-Materials",
        default=False,
        description="Reassign surfaces < threshold % into dominant material",
    )
    mat_cleanup_micro_area_pct: FloatProperty(name="Micro Threshold %", default=0.5, min=0.01, max=5.0, precision=2)
    mat_cleanup_repair_missing_textures: BoolProperty(
        name="Repair Missing Textures",
        default=False,
        description="Replace broken filepaths with safe procedural PBR defaults",
    )
    mat_cleanup_purge_orphans_blendfile: BoolProperty(
        name="Purge Orphan Materials from .blend",
        default=False,
        description="Permanently delete unused zero-user materials from the Blender file",
    )
    last_material_cleanup_summary: StringProperty(name="Material Cleanup Summary", default="")

    # PBR Texture Set Importer Settings
    pbr_import_preset: EnumProperty(
        name="Import Preset",
        items=get_pbr_import_preset_items,
        description="Active PBR texture set template matching incoming source texture conventions",
        update=on_import_preset_updated,
    )
    pbr_active_maps: CollectionProperty(type=PBRMapItem)
    pbr_active_map_index: IntProperty(name="Active Map Index", default=0, min=0)
    pbr_active_maps_preset_id: StringProperty(name="Active Maps Preset ID", default="")
    pbr_import_directory: StringProperty(
        name="Import Directory",
        subtype="DIR_PATH",
        default="//Textures/",
        description="Source directory containing PBR textures to import",
        update=on_import_directory_updated,
    )
    pbr_import_path_mode: EnumProperty(
        name="Path Mode",
        items=PBR_IMPORT_PATH_MODE_ITEMS,
        default="RELATIVE",
        description="Whether imported textures use relative (//) or absolute paths",
        update=on_import_path_mode_updated,
    )
    is_state_restored: BoolProperty(name="State Restored", default=False)
    pbr_preset: EnumProperty(
        name="Preset",
        items=get_pbr_export_preset_items,
        description="Active PBR texture set template (Legacy alias for export preset)",
        update=on_legacy_preset_updated,
    )
    pbr_import_ao_mode: EnumProperty(
        name="AO Mode",
        items=PBR_IMPORT_AO_MODE_ITEMS,
        default="MULTIPLY",
        description="How Ambient Occlusion maps are wired into the shader graph",
        update=on_import_ao_mode_updated,
    )
    pbr_import_preserve_existing: BoolProperty(
        name="Preserve Existing Nodes",
        default=False,
        description="Preserve existing non-PBR shader nodes in material when importing texture sets",
        update=on_import_preserve_updated,
    )
    last_pbr_import_summary: StringProperty(name="PBR Import Summary", default="")

    # Billboard Impostor Generator Settings
    enable_impostor_lod: BoolProperty(
        name="Enable Impostor LOD",
        default=False,
        description="Generate distant camera billboard impostor for this asset",
        update=on_lod_preset_property_modified,
    )
    impostor_mode: EnumProperty(
        name="Impostor Mode",
        items=IMPOSTOR_MODE_ITEMS,
        default="CROSS_QUADS",
        description="Billboard geometry type and multi-angle projection layout",
        update=on_lod_preset_property_modified,
    )
    impostor_resolution: EnumProperty(
        name="Atlas Resolution",
        items=IMPOSTOR_RESOLUTION_ITEMS,
        default="2048",
        description="Texture resolution for baked Impostor PBR atlas maps",
        update=on_lod_preset_property_modified,
    )
    auto_impostor_resolution: BoolProperty(
        name="Auto-Calculate Resolution",
        default=True,
        description="Automatically derive atlas resolution from switching screen size",
        update=on_lod_preset_property_modified,
    )
    impostor_replace_last_lod: BoolProperty(
        name="Use as Final LOD Tier",
        default=True,
        description="Automatically assign the generated Impostor billboard as the final LOD tier in the scene",
        update=on_lod_preset_property_modified,
    )
    last_impostor_status: StringProperty(name="Last Impostor Status", default="")

    # Interior & Occlusion Geometry Removal Settings
    enable_occlusion_culling: BoolProperty(
        name="Cull Interior Geometry",
        default=True,
        description="Automatically detect and delete non-visible internal polygons",
        update=on_lod_preset_property_modified,
    )
    occlusion_lod_start: IntProperty(
        name="Cull From LOD",
        default=1,
        min=1,
        max=6,
        description="LOD tier at which interior occlusion removal begins",
        update=on_lod_preset_property_modified,
    )
    occlusion_ray_density: IntProperty(
        name="Ray Samples",
        default=16,
        min=4,
        max=64,
        description="Number of stratified ingress and egress raycast samples per surface cluster",
        update=on_lod_preset_property_modified,
    )
    occlusion_evaluate_alpha: BoolProperty(
        name="Evaluate Transparency",
        default=True,
        description="Analyze glass shaders and alpha-cutout textures to allow rays to penetrate windows",
        update=on_lod_preset_property_modified,
    )
    last_culled_faces_count: IntProperty(name="Last Culled Faces", default=0)
    last_culled_islands_count: IntProperty(name="Last Culled Islands", default=0)

    # Sub-Pixel Slender & Thin Feature Culling Settings
    enable_slender_culling: BoolProperty(
        name="Cull Sub-Pixel Cables & Railings",
        default=True,
        description="Automatically remove sub-pixel thin cables, railings, and wires",
        update=on_lod_preset_property_modified,
    )
    last_culled_slender_count: IntProperty(name="Last Culled Slender Features", default=0)

    # Multi-Convex Collision Hull Generator Settings
    collision_decomposition_mode: EnumProperty(
        name="Decomposition Mode",
        items=COLLISION_DECOMPOSITION_MODE_ITEMS,
        default="PER_OBJECT",
        description="How multi-mesh selections are decomposed into collision hulls",
    )
    collision_hull_count: IntProperty(
        name="Hull Count", default=4, min=1, max=16, description="Target number of convex collision hulls"
    )
    collision_max_verts_per_hull: IntProperty(
        name="Max Verts / Hull", default=32, min=8, max=64, description="Clamps max vertices per convex hull"
    )
    collision_concavity_threshold: FloatProperty(
        name="Concavity Tolerance (m)", default=0.05, min=0.001, max=1.0, precision=3
    )
    last_generated_collider_count: IntProperty(name="Last Collider Count", default=0)

    # Multi-Object Hierarchy & Merging Settings
    consolidate_hierarchy: BoolProperty(
        name="Consolidate Hierarchy (Merge LOD1+)",
        default=False,
        description="Merge multi-mesh accessories into single consolidated mesh at distant LODs (saves draw calls)",
        update=on_lod_preset_property_modified,
    )
    hierarchy_mode: EnumProperty(
        name="Hierarchy Mode",
        items=HIERARCHY_MODE_ITEMS,
        default="PRESERVE",
        description="How multi-mesh hierarchies and accessories are structured across LOD tiers",
    )
    merge_start_tier: IntProperty(
        name="Merge Start Tier", default=3, min=1, max=6, description="LOD tier at which submeshes are merged"
    )
    merge_lod_start: IntProperty(
        name="Merge From LOD", default=2, min=1, max=6, description="LOD tier at which submeshes are merged"
    )

    # Spatial Chunking & HLOD Settings
    enable_spatial_chunking: BoolProperty(
        name="Enable Spatial Chunking (Tiling)",
        default=False,
        description="Spatially partitions massive assets into 2.5D AABB grid tiles",
    )
    chunk_cell_size: FloatProperty(name="Chunk Cell Size (m)", default=32.0, min=1.0, max=1000.0, unit="LENGTH")
    chunk_split_z: BoolProperty(
        name="Split Vertical Z-Axis", default=False, description="Splits geometry along vertical Z planes"
    )
    chunk_cell_size_z: FloatProperty(name="Z Cell Size (m)", default=32.0, min=1.0, max=1000.0, unit="LENGTH")
    chunk_partitioning_mode: EnumProperty(
        name="Partitioning Mode",
        items=CHUNK_PARTITIONING_MODE_ITEMS,
        default="UNIFORM_GRID",
        description="Spatial chunk tiling strategy",
    )
    adaptive_cluster_target_polys: IntProperty(name="Max Polys / Cluster", default=50000, min=1000, max=5000000)
    enable_hlod: BoolProperty(
        name="Enable HLOD Merging", default=True, description="Merges tiles into unified mesh at distant LOD tiers"
    )
    hlod_start_tier: IntProperty(
        name="HLOD Start Tier", default=2, min=1, max=6, description="LOD tier at which chunk tiles are merged"
    )
    enable_scan_pre_remesh: BoolProperty(
        name="Pre-Process: Voxel Remesh", default=False, description="Voxel remesh cleanup for photogrammetry scans"
    )
    scan_remesh_voxel_size: FloatProperty(
        name="Remesh Voxel Size (m)", default=0.05, min=0.005, max=1.0, precision=3, unit="LENGTH"
    )

    # Skeletal Rigging & Bone Pruning Settings
    normalize_bone_weights: BoolProperty(
        name="Normalize Bone Weights (Sum = 1.0)",
        default=True,
        description="Ensures deform weights strictly sum to 1.0",
    )
    max_bone_influences: EnumProperty(
        name="Max GPU Bone Influences",
        items=MAX_BONE_INFLUENCES_ITEMS,
        default="4",
    )
    enable_bone_pruning: BoolProperty(
        name="Prune Sub-Pixel Bones",
        default=True,
        description="Recursively collapse sub-pixel leaf bones into parent bones on distant LODs",
    )
    purge_shape_keys: BoolProperty(
        name="Purge Shape Keys on Distance LODs",
        default=True,
        description="Strip facial blendshapes / shape keys on LOD >= 2",
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
        name="Prune Bones From LOD", default=2, min=1, max=6, description="LOD tier from which bone pruning begins"
    )
    purge_distant_shape_keys: BoolProperty(
        name="Purge Shape Keys on Distant LODs",
        default=True,
        description="Removes shape keys on lower LODs to prevent decimation tearing",
    )

    # PBR Texture Channel Packing & Animation Baking Settings
    export_packed_textures: BoolProperty(
        name="Pack Engine PBR Textures", default=True, description="Extracts and packs PBR texture channels"
    )
    texture_max_resolution: EnumProperty(
        name="Max Resolution",
        items=TEXTURE_MAX_RESOLUTION_ITEMS,
        default="2048",
        description="Maximum texture resolution for exported PBR channel sets",
    )
    pbr_export_preset: EnumProperty(
        name="Export Profile",
        items=get_pbr_export_preset_items,
        description="Unified engine export preset determining target engine, channel packing, and naming",
        update=on_export_preset_updated,
    )
    pbr_export_active_maps: CollectionProperty(type=PBRExportMapItem)
    pbr_export_active_map_index: IntProperty(name="Active Export Map Index", default=0, min=0)
    pbr_export_active_maps_preset_id: StringProperty(name="Active Export Maps Preset ID", default="")
    pbr_export_texture_strategy: EnumProperty(
        name="Texture Strategy",
        items=PBR_EXPORT_TEXTURE_STRATEGY_ITEMS,
        default="SMART_AUTO",
        description="PBR texture export processing pipeline strategy",
        update=on_export_strategy_updated,
    )
    pbr_export_naming_pattern: StringProperty(
        name="Naming Pattern",
        default="{material}{suffix}",
        description="Naming pattern for exported textures ({asset}, {material}, {suffix})",
        update=on_export_naming_updated,
    )
    pbr_export_bit_depth: EnumProperty(
        name="Bit Depth",
        items=PBR_EXPORT_BIT_DEPTH_ITEMS,
        default="8",
        description="PNG channel depth for exported texture maps",
        update=on_export_bit_depth_updated,
    )
    bake_animations: BoolProperty(
        name="Bake Deform Rig Animations",
        default=True,
        description="Evaluates constraints and bakes deform bone matrices",
    )

    # Live Viewport LOD Simulator Settings
    is_simulator_running: BoolProperty(name="Simulator Running", default=False)
    is_simulator_active: BoolProperty(
        name="Live Distance Simulator", default=False, description="Real-time automatic LOD switching based on distance"
    )
    simulator_mode: EnumProperty(
        name="Simulator Mode",
        items=SIMULATOR_MODE_ITEMS,
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
        items=SIMULATOR_CAMERA_MODE_ITEMS,
        default="VIEWPORT",
        description="Camera position reference used to calculate live switch distances",
    )
    virtual_distance_override: FloatProperty(name="Virtual Distance (m)", default=0.0, min=0.0, max=5000.0, precision=2)
    show_viewport_hud: BoolProperty(
        name="Show Viewport HUD", default=True, description="Display real-time statistics HUD overlay in 3D Viewport"
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
    lod_preset: EnumProperty(
        name="LOD Preset",
        items=get_lod_preset_items,
        description="Active LOD tier configuration template determining screen coverage and tri reduction curves",
        update=on_lod_preset_updated,
    )
    lod_preset_budget_mode: EnumProperty(
        name="Budget Mode",
        items=LOD_PRESET_BUDGET_MODE_ITEMS,
        default="PERCENTAGE",
        description="Whether target budgets are specified as relative percentages or absolute triangle counts",
        update=on_lod_budget_mode_updated,
    )
    lod_preset_active_tiers: CollectionProperty(type=LODPresetTierItem)
    lod_preset_active_tier_index: IntProperty(name="Active Preset Tier Index", default=0, min=0)
    lod_preset_active_id: StringProperty(name="Active Preset ID", default="")
    lod_preset_is_dirty: BoolProperty(name="Preset Modified", default=False)
    lods: CollectionProperty(type=LODLevelItem)
    active_lod_index: IntProperty(name="Active LOD Selection", default=0)
    export_directory: StringProperty(
        name="Export Directory",
        subtype="DIR_PATH",
        default="//Export/",
        description="Destination folder for exported engine packages",
        update=on_export_directory_updated,
    )
    export_base_name: StringProperty(name="Asset Base Name", default="")

    # Live Engine Bridge Properties
    engine_project_path: StringProperty(
        name="Engine Project Path",
        subtype="DIR_PATH",
        default="",
        description="Root path to active Unreal, Unity, MSFS Community, or Godot project folder",
        update=on_engine_project_path_updated,
    )
    enable_live_sync: BoolProperty(
        name="Live Sync on Export",
        default=True,
        description="Automatically trigger engine re-import or compile package upon export",
        update=on_enable_live_sync_updated,
    )
    bridge_status_text: StringProperty(
        name="Bridge Status", default="Bridge Ready", description="Cached status report from engine bridge"
    )
    bridge_connected: BoolProperty(
        name="Bridge Connected", default=False, description="Cached active connection handshake status with bridge"
    )

    # A/B Split-Screen Comparison Preview Properties
    is_split_active: BoolProperty(
        name="Split View Active", default=False, description="Toggle dual-tier visual comparison overlay in Viewport"
    )
    split_ratio: FloatProperty(
        name="Divider Ratio",
        default=0.5,
        min=0.05,
        max=0.95,
        subtype="FACTOR",
        precision=2,
        update=on_split_preview_updated,
    )
    split_compare_tier: IntProperty(name="Compare Tier", default=3, min=1, max=7, update=on_split_preview_updated)

    # Batch Processing Properties
    batch_mode: BoolProperty(
        name="Batch Export (.blend files)",
        default=False,
        description="Batch-process all .blend files in a source directory with mirrored folder hierarchy",
        update=on_batch_mode_updated,
    )
    batch_source_directory: StringProperty(
        name="Source Folder",
        subtype="DIR_PATH",
        default="",
        description="Directory containing .blend assets to process in batch",
        update=on_batch_source_updated,
    )
    batch_export_directory: StringProperty(
        name="Export Folder",
        subtype="DIR_PATH",
        default="",
        description="Destination folder for exported engine packages",
    )
    batch_recursive_scan: BoolProperty(
        name="Recursive Subfolders", default=True, description="Scan nested subdirectories for 3D asset files"
    )
    batch_file_formats: EnumProperty(
        name="Formats",
        items=BATCH_FILE_FORMATS_ITEMS,
        default="ALL",
    )
    batch_status_text: StringProperty(name="Batch Status", default="Batch Ready")
    is_batch_running: BoolProperty(name="Batch Running", default=False)
    batch_total_count: IntProperty(name="Total Assets", default=0)
    batch_processed_count: IntProperty(name="Processed Assets", default=0)
    batch_current_asset: StringProperty(name="Current Asset", default="")

    # MSFS Spatial Configuration
    msfs_spatial_cfg_path: StringProperty(
        name="MSFS Flight Model File",
        subtype="FILE_PATH",
        default="",
        description="Path to target flight_model.cfg for spatial configuration synchronization",
    )
    msfs_systems_cfg_path: StringProperty(
        name="MSFS Systems / Lights File",
        subtype="FILE_PATH",
        default="",
        description="Path to target systems.cfg or light.cfg for lighting synchronization",
    )
    msfs_spatial_status: StringProperty(
        name="MSFS Spatial Status",
        default="Ready",
        description="Current status or last synchronized backup file",
    )
    msfs_scrape_margin_m: FloatProperty(
        name="Scrape Margin (m)",
        default=0.0,
        min=-0.5,
        max=0.5,
        description="Outward offset margin applied to scrape points (m)",
    )
    msfs_gear_state: EnumProperty(
        name="Gear State in Model",
        items=MSFS_GEAR_STATE_ITEMS,
        default="STATIC_COMPRESSED",
        description="Strut compression state",
    )
    msfs_gear_compression_m: FloatProperty(
        name="Strut Compression (m)",
        default=0.12,
        min=0.0,
        max=1.0,
        description="Expected oleo strut compression in meters",
    )
    msfs_calculated_cg_height_ft: FloatProperty(
        name="Calculated Static CG Height (ft)",
        default=0.0,
        precision=3,
        description="Computed static_cg_height in feet",
    )
    msfs_cameras_cfg_path: StringProperty(
        name="MSFS Cameras File", subtype="FILE_PATH", default="", description="Path to target cameras.cfg"
    )

    # Engine / Project Importer Properties
    engine_import_preset: EnumProperty(
        name="Engine Import Preset",
        items=get_engine_import_preset_items,
        description="Active import template",
        update=on_engine_import_preset_updated,
    )
    engine_import_directory: StringProperty(
        name="Engine Project Path",
        subtype="DIR_PATH",
        default="",
        description="Root folder of project to ingest",
        update=on_engine_import_directory_updated,
    )
    engine_import_geometry: BoolProperty(
        name="Import Geometry & LODs", default=True, description="Import glTF LOD meshes into tier collections"
    )
    engine_import_spatial: BoolProperty(
        name="Import Spatial Markers", default=True, description="Import datum, CG, wheels, scrape points, fuel tanks"
    )
    engine_import_lights: BoolProperty(
        name="Import Lights", default=True, description="Import aviation lights from systems.cfg or light.cfg"
    )
    engine_import_cameras: BoolProperty(
        name="Import Cameras", default=True, description="Import cockpit eyepoint and cameras from cameras.cfg"
    )
    engine_import_model_target: EnumProperty(
        name="Model Target",
        items=ENGINE_IMPORT_MODEL_TARGET_ITEMS,
        default="EXTERIOR_ONLY",
        description="Target model to ingest",
    )
    engine_import_use_lod0_suffix: BoolProperty(
        name="Use LOD0 Suffix",
        default=True,
        description="Whether to name LOD0 collection '{Asset}_LOD0' or omit suffix",
    )
    engine_import_auto_assign_screen_pct: BoolProperty(
        name="Auto-Assign Screen %",
        default=True,
        description="Map minSize screen coverage values directly to LOD tiers",
    )
    engine_import_deduplicate_materials: BoolProperty(
        name="Deduplicate Materials",
        default=True,
        description="Remap duplicate materials across LODs to base materials",
    )
    engine_import_reuse_master_rig: BoolProperty(
        name="Reuse Master Armature", default=True, description="Retarget LOD1..N armatures to LOD0 Master Rig"
    )
    last_engine_import_summary: StringProperty(
        name="Last Import Summary", default="", description="Summary of the last completed engine project import"
    )


__all__ = ["LODToolSettings"]
