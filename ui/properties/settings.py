# pyright: reportInvalidTypeForm=none
"""
OmniMesh Central Settings PropertyGroup.
Attached to Scene (for project-wide pipeline globals) and Object (for per-asset geometry persistence).
"""

from typing import TYPE_CHECKING

from ..utils import get_asset_enum_items
from . import callbacks, enums
from .animation_properties import OMNIMESH_AnimationSettings
from .cleanup_settings import LODToolCleanupSettingsMixin
from .config_properties import OMNIMESH_ConfigPresetSettings
from .engine_settings import LODToolEngineSettingsMixin
from .interaction_properties import OMNIMESH_InteractionSettings
from .lod_properties import (
    LODLevelItem,
    LODPresetTierItem,
    on_lod_preset_property_modified,
)
from .material_properties import OMNIMESH_MaterialPresetSettings
from .msfs_cfg_properties import OMNIMESH_MSFSConfigSettings
from .pbr_properties import PBRExportMapItem, PBRMapItem

if TYPE_CHECKING:
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
else:
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
        from ..rna_helpers import mock_prop

        bpy = None
        PropertyGroup = object
        BoolProperty = CollectionProperty = EnumProperty = FloatProperty = FloatVectorProperty = IntProperty = (
            PointerProperty
        ) = StringProperty = mock_prop


class LODToolSettings(LODToolCleanupSettingsMixin, LODToolEngineSettingsMixin, PropertyGroup):
    """Central PropertyGroup holding OmniMesh configuration and state."""

    # Source Scope Architecture (Selection vs Collection Mode)
    lod_generation_source: EnumProperty(
        name="Source Scope",
        items=enums.LOD_GENERATION_SOURCE_ITEMS,
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
        default=0,
        description="Target root asset collection for LOD configuration and generation",
        update=lambda self, context: callbacks.on_active_asset_updated(self, context),
    )
    ui_active_tab: EnumProperty(
        name="Workflow Tab",
        items=enums.OMNIMESH_UI_TAB_ITEMS,
        default="MODIFY",
        description="Active OmniMesh workflow tab",
    )
    preserve_pivot_empty: BoolProperty(
        name="Preserve Pivot Empty",
        default=True,
        description="Detect and preserve Pivot/Root empty transforms across LOD collections and exports",
    )

    # Per-Object Metadata & Root Linkage
    is_configured: BoolProperty(name="Is Configured", default=False)
    is_generated_lod: BoolProperty(name="Is Generated Derivative", default=False)
    lod_root_object: PointerProperty(name="Root Master Asset", type=bpy.types.Object if bpy else None)
    lod_index: IntProperty(name="Derivative Tier Index", default=0, min=0, max=7)
    bounding_radius: FloatProperty(name="Bounding Radius", default=1.0, min=0.0)
    bounding_center: FloatVectorProperty(name="Bounding Center", size=3, default=(0.0, 0.0, 0.0))
    base_triangles: IntProperty(name="Base Triangles", default=0, min=0)
    screen_coverage_lod0: FloatProperty(name="LOD0 Screen Coverage %", default=100.0, min=0.0, max=100.0)

    # Base Mesh Hygiene Properties
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
        items=enums.TARGET_ENGINE_ITEMS,
        default="MSFS_2024",
        description="Target engine determines naming conventions, metadata hierarchy, and export formats",
        update=callbacks.on_target_engine_updated,
    )

    # Asset Category Presets
    asset_category: EnumProperty(
        name="Asset Category",
        items=enums.ASSET_CATEGORY_ITEMS,
        default="PROP",
        description="Selects default error tolerances, decimation curve exponent, and island culling factors",
    )

    # Progression Curve Mode
    progression_mode: EnumProperty(
        name="Tier Progression",
        items=enums.PROGRESSION_MODE_ITEMS,
        default="EXPONENTIAL",
        description="Mathematical curve used to compute automatic screen size and triangle budgets",
    )

    lod_count: IntProperty(name="LOD Count", default=4, min=2, max=7, description="Total LOD tiers to generate")
    num_lods: IntProperty(name="LOD Count", default=7, min=2, max=8, description="Number of LOD tiers")
    cull_screen_size_pct: FloatProperty(
        name="Cull Screen Size (%)",
        default=0.5,
        min=0.01,
        max=10.0,
        precision=2,
        subtype="PERCENTAGE",
        description="Minimum screen-size percentage below which the final LOD tier is culled",
        update=on_lod_preset_property_modified,
    )
    preserve_slot_indexing: BoolProperty(
        name="Preserve Slot Indices",
        default=True,
        description="Retain existing material slot order during LOD generation instead of compacting slots",
    )

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
        name="Preserve Silhouettes",
        default=True,
        description="Protect silhouette boundary edges during LOD simplification",
    )
    pin_uv_seams: BoolProperty(
        name="Pin UV Seams",
        default=True,
        description="Pin vertices along UV seam edges during decimation to prevent texture tearing",
        update=on_lod_preset_property_modified,
    )
    pin_material_borders: BoolProperty(
        name="Pin Material Borders",
        default=True,
        description="Pin vertices on boundaries between different material slots during decimation",
        update=on_lod_preset_property_modified,
    )

    # PBR Texture Set Importer Settings
    pbr_import_preset: EnumProperty(
        name="Import Preset",
        items=callbacks.get_pbr_import_preset_items,
        description="Active PBR texture set template matching incoming source texture conventions",
        update=callbacks.on_import_preset_updated,
    )
    pbr_active_maps: CollectionProperty(type=PBRMapItem)
    pbr_active_map_index: IntProperty(name="Active Map Index", default=0, min=0)
    pbr_active_maps_preset_id: StringProperty(name="Active Maps Preset ID", default="")
    pbr_import_directory: StringProperty(
        name="Import Directory",
        subtype="DIR_PATH",
        default="",
        options={"PATH_SUPPORTS_BLEND_RELATIVE"},
        description="Source directory containing PBR textures to import",
        update=callbacks.on_import_directory_updated,
    )
    pbr_import_path_mode: EnumProperty(
        name="Path Mode",
        items=enums.PBR_IMPORT_PATH_MODE_ITEMS,
        default="RELATIVE",
        description="Whether imported textures use relative (//) or absolute paths",
        update=callbacks.on_import_path_mode_updated,
    )
    is_state_restored: BoolProperty(name="State Restored", default=False)
    pbr_preset: EnumProperty(
        name="Preset",
        items=callbacks.get_pbr_export_preset_items,
        description="Active PBR texture set template (Legacy alias for export preset)",
        update=callbacks.on_legacy_preset_updated,
    )
    pbr_import_ao_mode: EnumProperty(
        name="AO Mode",
        items=enums.PBR_IMPORT_AO_MODE_ITEMS,
        default="MULTIPLY",
        description="How Ambient Occlusion maps are wired into the shader graph",
        update=callbacks.on_import_ao_mode_updated,
    )
    pbr_import_preserve_existing: BoolProperty(
        name="Preserve Existing Nodes",
        default=True,
        description="Preserve existing non-PBR shader nodes in material when importing texture sets",
        update=callbacks.on_import_preserve_updated,
    )

    # Billboard Impostor Generator Settings
    enable_impostor_lod: BoolProperty(
        name="Enable Impostor LOD",
        default=False,
        description="Automatically generate a billboard impostor after generating LODs",
        update=on_lod_preset_property_modified,
    )
    impostor_mode: EnumProperty(
        name="Impostor Mode",
        items=enums.IMPOSTOR_MODE_ITEMS,
        default="ORTHO_3_AXES",
        description="Billboard projection layout",
        update=on_lod_preset_property_modified,
    )
    impostor_render_underside: BoolProperty(
        name="Render Underside",
        default=False,
        description="Capture full-sphere angles including underside views (uses Full Sphere octahedral projection instead of Upper Hemisphere only)",
        update=on_lod_preset_property_modified,
    )
    impostor_grid_size: IntProperty(
        name="Frames per Axis (N×N)",
        default=8,
        min=4,
        max=32,
        description="Octahedral grid views per axis (e.g. 8 = 8×8 = 64 views, 12 = 144 views, 16 = 256 views)",
        update=on_lod_preset_property_modified,
    )
    impostor_resolution: EnumProperty(
        name="Atlas Resolution",
        items=enums.IMPOSTOR_RESOLUTION_ITEMS,
        default="2048",
        description="Impostor texture atlas width and height in pixels when Auto Resolution is disabled",
        update=on_lod_preset_property_modified,
    )
    auto_impostor_resolution: BoolProperty(
        name="Auto-Calculate Resolution",
        default=True,
        description="Automatically calculate a power-of-2 atlas resolution (256-4096 px) from the final LOD tier's screen size",
        update=on_lod_preset_property_modified,
    )
    impostor_replace_last_lod: BoolProperty(
        name="Use as Final LOD Tier",
        default=True,
        description="Mark preset preference for the impostor to act as the final LOD tier (saved in presets; not yet enforced during generation)",
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
        items=enums.COLLISION_DECOMPOSITION_MODE_ITEMS,
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
        name="Concavity Tolerance (m)",
        default=0.05,
        min=0.001,
        max=1.0,
        precision=3,
        description="Maximum allowed concavity error in meters before splitting a cluster into smaller convex hulls",
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
        items=enums.HIERARCHY_MODE_ITEMS,
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
        description="Split large environments into spatial grid chunks before generating LODs and HLOD clusters",
        update=on_lod_preset_property_modified,
    )
    chunk_cell_size: FloatProperty(
        name="Chunk Cell Size (m)",
        default=32.0,
        min=1.0,
        max=1000.0,
        unit="LENGTH",
        description="Horizontal grid cell width and depth in meters used for spatial chunk partitioning",
        update=on_lod_preset_property_modified,
    )
    chunk_split_z: BoolProperty(
        name="Split Vertical Z-Axis",
        default=False,
        description="Also partition tall geometry vertically along the Z axis using Z Cell Size",
        update=on_lod_preset_property_modified,
    )
    chunk_cell_size_z: FloatProperty(
        name="Z Cell Size (m)",
        default=32.0,
        min=1.0,
        max=1000.0,
        unit="LENGTH",
        description="Vertical grid cell height in meters when Split Vertical Z-Axis is enabled",
        update=on_lod_preset_property_modified,
    )
    chunk_partitioning_mode: EnumProperty(
        name="Partitioning Mode",
        items=enums.CHUNK_PARTITIONING_MODE_ITEMS,
        default="UNIFORM_GRID",
        description="Spatial partitioning strategy used to subdivide large meshes into chunks",
        update=on_lod_preset_property_modified,
    )
    adaptive_cluster_target_polys: IntProperty(
        name="Max Polys / Cluster",
        default=50000,
        min=1000,
        max=5000000,
        description="Maximum polygon budget per combined chunk when using Adaptive Cell Clustering",
        update=on_lod_preset_property_modified,
    )
    enable_hlod: BoolProperty(
        name="Enable HLOD Merging",
        default=True,
        description="Merge adjacent spatial chunks into Hierarchical LOD (HLOD) clusters at distant tiers",
        update=on_lod_preset_property_modified,
    )
    enable_hierarchical_hlod: BoolProperty(
        name="Hierarchical HLOD (Quadtree)",
        default=True,
        description="Build recursive 2x2 / 2x2x2 quadtree or octree HLOD clusters across distant tiers",
        update=on_lod_preset_property_modified,
    )
    hlod_start_tier: IntProperty(
        name="HLOD Start Tier",
        default=2,
        min=1,
        max=6,
        description="LOD tier index at which spatial chunks begin merging into HLOD clusters",
        update=on_lod_preset_property_modified,
    )
    hlod_proxy_remesh: BoolProperty(
        name="Terminal HLOD Voxel Wrap",
        default=False,
        description="Wrap the terminal HLOD tier in a watertight voxel shell to reduce overdraw and gaps",
        update=on_lod_preset_property_modified,
    )
    hlod_proxy_voxel_size: FloatProperty(
        name="Voxel Shell Size (m)",
        default=0.5,
        min=0.05,
        max=5.0,
        precision=2,
        unit="LENGTH",
        description="Voxel size in meters used when building the terminal HLOD watertight shell wrap",
        update=on_lod_preset_property_modified,
    )
    enable_scan_pre_remesh: BoolProperty(
        name="Pre-Process: Voxel Remesh", default=False, description="Voxel remesh cleanup for photogrammetry scans"
    )
    scan_remesh_voxel_size: FloatProperty(
        name="Remesh Voxel Size (m)",
        default=0.05,
        min=0.005,
        max=1.0,
        precision=3,
        unit="LENGTH",
        description="Voxel size in meters used by Voxel Remesh Scan Cleanup",
    )

    # Skeletal Rigging & Bone Pruning Settings
    normalize_bone_weights: BoolProperty(
        name="Normalize Bone Weights (Sum = 1.0)",
        default=True,
        description="Ensures deform weights strictly sum to 1.0",
    )
    max_bone_influences: EnumProperty(
        name="Max GPU Bone Influences",
        items=enums.MAX_BONE_INFLUENCES_ITEMS,
        default="4",
        description="Maximum number of skinning bone weights retained per vertex on generated LODs",
    )
    enable_bone_pruning: BoolProperty(
        name="Prune Sub-Pixel Bones",
        default=True,
        description="Recursively collapse sub-pixel leaf bones into parent bones on distant LODs",
    )
    purge_shape_keys: BoolProperty(
        name="Purge Shape Keys on Distance LODs",
        default=True,
        description="Strip facial blendshapes / shape keys on derivative LODs (LOD >= 1)",
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
        items=enums.TEXTURE_MAX_RESOLUTION_ITEMS,
        default="2048",
        description="Maximum texture resolution for exported PBR channel sets",
    )
    pbr_export_preset: EnumProperty(
        name="Export Profile",
        items=callbacks.get_pbr_export_preset_items,
        description="Unified engine export preset determining target engine, channel packing, and naming",
        update=callbacks.on_export_preset_updated,
    )
    pbr_export_active_maps: CollectionProperty(type=PBRExportMapItem)
    pbr_export_active_map_index: IntProperty(name="Active Export Map Index", default=0, min=0)
    pbr_export_active_maps_preset_id: StringProperty(name="Active Export Maps Preset ID", default="")
    pbr_export_texture_strategy: EnumProperty(
        name="Texture Strategy",
        items=enums.PBR_EXPORT_TEXTURE_STRATEGY_ITEMS,
        default="SMART_AUTO",
        description="PBR texture export processing pipeline strategy",
        update=callbacks.on_export_strategy_updated,
    )
    pbr_export_naming_pattern: StringProperty(
        name="Naming Pattern",
        default="{asset}_{material}{suffix}{udim}",
        description="Naming pattern for exported textures ({asset}, {material}, {suffix}, {udim})",
        update=callbacks.on_export_naming_updated,
    )
    pbr_export_bit_depth: EnumProperty(
        name="Bit Depth",
        items=enums.PBR_EXPORT_BIT_DEPTH_ITEMS,
        default="8",
        description="PNG channel depth for exported texture maps",
        update=callbacks.on_export_bit_depth_updated,
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
        items=enums.SIMULATOR_MODE_ITEMS,
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
        items=enums.SIMULATOR_CAMERA_MODE_ITEMS,
        default="VIEWPORT",
        description="Camera position reference used to calculate live switch distances",
    )
    virtual_distance_override: FloatProperty(
        name="Virtual Distance (m)",
        default=0.0,
        min=0.0,
        max=5000.0,
        precision=2,
        description="Simulated camera distance in meters for manual LOD inspection and tier scrubbing",
        update=lambda self, context: callbacks.on_virtual_distance_updated(self, context),
    )
    last_scrub_status: StringProperty(name="Scrub Status", default="")

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
        items=callbacks.get_lod_preset_items,
        description="Active LOD tier configuration template determining screen coverage and tri reduction curves",
        update=callbacks.on_lod_preset_updated,
    )
    lod_preset_budget_mode: EnumProperty(
        name="Budget Mode",
        items=enums.LOD_PRESET_BUDGET_MODE_ITEMS,
        default="PERCENTAGE",
        description="Whether target budgets are specified as relative percentages or absolute triangle counts",
        update=callbacks.on_lod_budget_mode_updated,
    )
    lod_preset_active_tiers: CollectionProperty(type=LODPresetTierItem)
    lod_preset_active_tier_index: IntProperty(name="Active Preset Tier Index", default=0, min=0)
    lod_preset_active_id: StringProperty(name="Active Preset ID", default="")
    lod_preset_is_dirty: BoolProperty(name="Preset Modified", default=False)
    lods: CollectionProperty(type=LODLevelItem)
    active_lod_index: IntProperty(
        name="Active LOD Selection",
        default=0,
        update=callbacks.on_active_lod_index_updated,
    )
    export_directory: StringProperty(
        name="Export Directory",
        subtype="DIR_PATH",
        default="",
        options={"PATH_SUPPORTS_BLEND_RELATIVE"},
        description="Destination folder for exported engine packages",
        update=callbacks.on_export_directory_updated,
    )
    export_base_name: StringProperty(name="Asset Base Name", default="")

    # Side-by-Side Viewport Alignment Inspection
    is_side_by_side_active: BoolProperty(
        name="Side-by-Side View",
        default=False,
        description="Place all LOD tiers side-by-side along the X-axis for visual inspection",
    )

    # Config Preset Subsystem (Panel 2 Modify)
    config_presets: PointerProperty(type=OMNIMESH_ConfigPresetSettings)
    material_preset: PointerProperty(type=OMNIMESH_MaterialPresetSettings)
    interaction: PointerProperty(type=OMNIMESH_InteractionSettings)
    animation_tagging: PointerProperty(type=OMNIMESH_AnimationSettings)
    msfs_configs: PointerProperty(type=OMNIMESH_MSFSConfigSettings)


__all__ = ["LODToolSettings"]
