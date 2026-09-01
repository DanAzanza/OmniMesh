"""
Blender PropertyGroups and Scene Settings for OmniMesh.
Maintains data models for LOD tiers, screen metrics, collision hulls, rigging, PBR textures,
engine presets, mesh cleanup, impostors, live simulation, and live engine bridges.
Supports both Scene-Level project globals and Per-Object persistent geometric configurations.
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
    actual_triangles: IntProperty(name="Actual Tris", default=0, min=0)
    reduction_pct: FloatProperty(name="Reduction %", default=0.0, precision=1)
    mat_slots_count: IntProperty(name="Material Slots", default=0, min=0)
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

    # Per-Object Metadata & Root Linkage
    is_configured: BoolProperty(name="Is Configured", default=False)
    is_generated_lod: BoolProperty(name="Is Generated Derivative", default=False)
    lod_root_object: PointerProperty(name="Root Master Asset", type=bpy.types.Object if bpy else object)
    lod_index: IntProperty(name="Derivative Tier Index", default=0, min=0, max=7)

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

    # Error Metrics and Screen Parameters
    tau_sse: FloatProperty(
        name="Error Bound Factor",
        default=1.0,
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
    cleanup_enable_cull_micro_islands: BoolProperty(
        name="Cull Floating Micro-Islands",
        default=False,
        description="Remove tiny disconnected floating mesh pieces in world space",
    )
    cleanup_island_size_threshold: FloatProperty(
        name="Island Size Threshold",
        default=0.005,
        min=0.0001,
        max=0.5,
        precision=4,
        description="Bounding diagonal threshold in meters for culling small islands",
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
                "MERGE_DISTANT",
                "Merge at Distant Tiers",
                "Joins compatible sub-meshes into a single draw-call mesh at lower LODs",
            ),
        ],
        default="PRESERVE",
        description="How multi-mesh hierarchies and accessories are structured across LOD tiers",
    )
    merge_lod_start: IntProperty(
        name="Merge From LOD",
        default=2,
        min=1,
        max=6,
        description="LOD tier at which compatible submeshes are merged into single draw-call meshes",
    )

    # Skeletal Rigging & Bone Pruning Settings
    normalize_bone_weights: BoolProperty(
        name="Normalize Bone Weights (Sum = 1.0)",
        default=True,
        description="Ensures all vertex deform weights strictly sum to 1.0",
    )
    max_bone_influences: IntProperty(
        name="Max Influences / Vertex",
        default=4,
        min=1,
        max=8,
        description="Clamps maximum active bone influences per vertex (4 for standard game engines)",
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
            ("ORIGINAL", "Original Source Res", "Keep original texture dimensions"),
            ("4096", "4096 x 4096 (4K)", "Clamp maximum resolution to 4K"),
            ("2048", "2048 x 2048 (2K)", "Clamp maximum resolution to 2K"),
            ("1024", "1024 x 1024 (1K)", "Clamp maximum resolution to 1K"),
            ("512", "512 x 512", "Clamp maximum resolution to 512px"),
        ],
        default="ORIGINAL",
        description="Maximum texture resolution for exported PBR channel sets",
    )
    bake_animations: BoolProperty(
        name="Bake Deform Rig Animations",
        default=True,
        description="Evaluates constraints and bakes deform bone matrices via depsgraph for engine export",
    )

    # Live Viewport LOD Simulator Settings
    is_simulator_active: BoolProperty(
        name="Live Distance Simulator",
        default=False,
        description="Real-time automatic LOD switching based on viewport and scene camera distance",
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
        min=0.0,
        max=1.0,
        subtype="PERCENTAGE",
        precision=2,
        description="Horizontal screen split position (0.0 = Left only, 1.0 = Right only)",
    )
    split_compare_tier: EnumProperty(
        name="Compare Tier",
        items=[
            ("LOD1", "LOD1", "Compare LOD0 against LOD1"),
            ("LOD2", "LOD2", "Compare LOD0 against LOD2"),
            ("LOD3", "LOD3", "Compare LOD0 against LOD3"),
            ("LOD4", "LOD4", "Compare LOD0 against LOD4"),
            ("LOD5", "LOD5", "Compare LOD0 against LOD5"),
            ("LOD6", "LOD6", "Compare LOD0 against LOD6"),
        ],
        default="LOD1",
        description="Which simplified LOD tier to show on the right side of the split screen",
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


CLASSES = (
    LODLevelItem,
    LODToolSettings,
)


def register_properties() -> None:
    if not bpy:
        return
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.lod_tool = PointerProperty(type=LODToolSettings)
    bpy.types.Object.lod_tool = PointerProperty(type=LODToolSettings)


def unregister_properties() -> None:
    if not bpy:
        return
    if hasattr(bpy.types.Scene, "lod_tool"):
        del bpy.types.Scene.lod_tool
    if hasattr(bpy.types.Object, "lod_tool"):
        del bpy.types.Object.lod_tool
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
