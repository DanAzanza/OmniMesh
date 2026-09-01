"""
UI PropertyGroups for LOD Tool with Rigging, Hierarchy, Texture, Live Simulator, Collision, Occlusion & Engine Bridge Settings.
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

    PropertyGroup = bpy.types.PropertyGroup
except ImportError:
    bpy = None
    PropertyGroup = object

    def StringProperty(**kw: Any) -> Any:
        return None

    def BoolProperty(**kw: Any) -> Any:
        return None

    def IntProperty(**kw: Any) -> Any:
        return None

    def FloatProperty(**kw: Any) -> Any:
        return None

    def EnumProperty(**kw: Any) -> Any:
        return None

    def CollectionProperty(**kw: Any) -> Any:
        return None

    def PointerProperty(**kw: Any) -> Any:
        return None


def update_bridge_status_cached(self: Any, context: Any) -> None:
    """Asynchronously update bridge status text without running blocking I/O inside draw()."""
    if not bpy or not context:
        return
    try:
        from ..bridges.manager import BridgeManager
    except (ImportError, ValueError):
        try:
            from bridges.manager import BridgeManager
        except (ImportError, ValueError):
            return

    engine_path = bpy.path.abspath(self.engine_project_path) if self.engine_project_path else ""
    _, status_msg = BridgeManager.ping_engine(self.target_engine, engine_path)
    self.bridge_status_text = status_msg


class LODLevelItem(PropertyGroup):
    name: StringProperty(name="LOD Name", default="LOD0")
    lod_index: IntProperty(name="LOD Index", default=0, min=0, max=10)
    screen_size_pct: FloatProperty(
        name="Screen Size (%)", default=100.0, min=0.01, max=100.0, subtype="PERCENTAGE", precision=2
    )
    target_tris: IntProperty(name="Target Tris", default=0, min=0)
    actual_tris: IntProperty(name="Actual Tris", default=0, min=0)
    distance_m: FloatProperty(name="Switch Distance (m)", default=0.0, min=0.0, precision=2)
    delta_world: FloatProperty(name="Allowed Error (m)", default=0.0, min=0.0, precision=4)
    mat_slots_count: IntProperty(name="Material Slots", default=1, min=0)
    generated_obj: PointerProperty(name="Mesh Object", type=bpy.types.Object if bpy else object)


class LODPipelineProperties(PropertyGroup):
    target_engine: EnumProperty(
        name="Target Engine",
        items=[
            ("MSFS_2024", "MSFS 2024 (Strict SDK)", "Microsoft Flight Simulator 2020/2024 glTF + ModelInfo XML"),
            ("UE5", "Unreal Engine 5.x", "Unreal Engine 5 FBX with LODGroup / Skeletal Hierarchy"),
            ("UNITY_6", "Unity 6", "Unity FBX with _LOD0..N naming hierarchy"),
            ("GODOT_4", "Godot 4.x", "Godot 4 glTF with visibility ranges"),
        ],
        default="MSFS_2024",
        update=update_bridge_status_cached,
    )
    asset_category: EnumProperty(
        name="Asset Role",
        items=[
            ("SCENERY", "Scenery / Large Structure", "Airports, buildings, bridges, large props"),
            ("VEHICLE_AIRFRAME", "Aircraft / Vehicle Exterior", "Fuselage, wings, hull, exterior mechanical parts"),
            ("CHARACTER_RIGGED", "Character / Rigged Asset", "Skeletal skinned meshes, creatures, characters"),
            ("INTERIOR", "Cockpit / Interior", "Detailed instruments, cabin seating, controls"),
        ],
        default="SCENERY",
    )
    lod_count: IntProperty(
        name="LOD Count",
        default=5,
        min=2,
        max=8,
        description="Number of LOD levels to generate (LOD0 to LOD_N)",
    )
    progression_mode: EnumProperty(
        name="Curve Profile",
        items=[
            ("LOGARITHMIC", "Logarithmic (Smooth Game Falloff)", "Exponential screen size progression"),
            ("LINEAR", "Linear (Even Steps)", "Uniform distance steps across LOD stages"),
            ("CUSTOM", "Custom Thresholds", "Manually configured screen percentage thresholds"),
        ],
        default="LOGARITHMIC",
    )
    protect_silhouettes: BoolProperty(
        name="Protect Silhouettes & Outer Edges",
        default=True,
        description="Injects high dihedral boundary weights to retain outer contours at low screen sizes",
    )
    protect_uv_seams: BoolProperty(
        name="Protect UV Seams & Texture Borders",
        default=True,
        description="Prevents UV seam vertex collapse and eliminates texture border tearing",
    )
    cull_subpixel_islands: BoolProperty(
        name="Dissolve Sub-Pixel Mesh Islands",
        default=True,
        description="Automatically drops tiny disconnected geometry islands below projected screen threshold",
    )
    reproject_normals: BoolProperty(
        name="Reproject Weighted Split Normals",
        default=True,
        description="Transfers custom CAD split normals from LOD0 to lower LOD tiers via Data Transfer modifier",
    )
    consolidate_materials: BoolProperty(
        name="Consolidate Micro-Material Slots",
        default=True,
        description="Merges negligible surface material slots (< 0.5% total area) into the dominant material slot",
    )

    # Occlusion & Interior Geometry Removal Settings
    enable_occlusion_culling: BoolProperty(
        name="Cull Interior Geometry",
        default=True,
        description="Detect and delete interior/occluded polygons not visible from the exterior",
    )
    occlusion_lod_start: IntProperty(
        name="Cull From LOD",
        default=1,
        min=1,
        max=6,
        description="LOD tier from which occlusion culling begins (LOD0 is always preserved)",
    )
    occlusion_ray_density: IntProperty(
        name="Ray Samples",
        default=16,
        min=4,
        max=64,
        description="Visibility ray sampling density (higher = more accurate, lower = faster)",
    )
    occlusion_evaluate_alpha: BoolProperty(
        name="Evaluate Transparency",
        default=True,
        description="Evaluate material transparency and alpha cutouts to protect geometry visible through glass/windows",
    )
    last_culled_faces_count: IntProperty(name="Last Culled Faces", default=0)
    last_culled_islands_count: IntProperty(name="Last Culled Islands", default=0)

    # Multi-Convex Collision Hull Generator Settings
    collision_decomposition_mode: EnumProperty(
        name="Decomposition Mode",
        items=[
            ("PER_OBJECT", "Per-Object (Area Weighted)", "Decomposes each selected submesh proportionally"),
            ("CONSOLIDATED", "Consolidated Single Hull Set", "Merges selected objects into unified collision set"),
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
    )

    # Batch Library Processor Properties
    batch_source_directory: StringProperty(
        name="Source Assets Folder",
        subtype="DIR_PATH",
        default="",
        description="Directory containing .fbx, .obj, .gltf, or .glb assets to batch-process",
    )
    batch_export_directory: StringProperty(
        name="Batch Output Folder",
        subtype="DIR_PATH",
        default="",
        description="Destination folder for exported LOD packages and textures",
    )
    batch_recursive_scan: BoolProperty(
        name="Recursive Subfolders",
        default=True,
        description="Scan nested subdirectories for 3D model files",
    )
    is_batch_running: BoolProperty(name="Batch Running", default=False)
    batch_total_count: IntProperty(name="Total Assets", default=0)
    batch_processed_count: IntProperty(name="Processed Assets", default=0)
    batch_current_asset: StringProperty(name="Current Asset", default="")
    batch_status_text: StringProperty(name="Batch Status", default="Batch Ingest Ready")

    # Visual A/B Split-Screen Viewport Comparison Properties
    is_split_active: BoolProperty(name="Split Screen Active", default=False)
    split_ratio: FloatProperty(
        name="Split Divider",
        default=0.5,
        min=0.05,
        max=0.95,
        subtype="FACTOR",
        precision=2,
        description="Position of the A/B comparison divider line",
    )
    split_compare_tier: IntProperty(
        name="Compare Tier",
        default=3,
        min=1,
        max=7,
        description="LOD tier index to compare against LOD0 Master",
    )


def register_properties() -> None:
    if not bpy:
        return
    bpy.utils.register_class(LODLevelItem)
    bpy.utils.register_class(LODPipelineProperties)
    bpy.types.Scene.lod_tool = PointerProperty(type=LODPipelineProperties)


def unregister_properties() -> None:
    if not bpy:
        return
    if hasattr(bpy.types.Scene, "lod_tool"):
        del bpy.types.Scene.lod_tool
    bpy.utils.unregister_class(LODPipelineProperties)
    bpy.utils.unregister_class(LODLevelItem)
