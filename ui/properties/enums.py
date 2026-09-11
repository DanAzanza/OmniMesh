"""
Static enum items, labels, and tooltips for OmniMesh RNA properties.
"""

LOD_GENERATION_SOURCE_ITEMS: list[tuple[str, str, str]] = [
    ("SELECTION", "Selected Objects", "Generate LODs from selected mesh objects"),
    (
        "COLLECTION",
        "Collection Hierarchy",
        "Generate LODs from entire active collection hierarchy (e.g. Model, Fuselage)",
    ),
]

TARGET_ENGINE_ITEMS: list[tuple[str, str, str]] = [
    ("MSFS_2024", "MSFS 2024 (glTF + XML)", "Microsoft Flight Simulator 2024 glTF and ModelInfo XML standard"),
    ("UE5", "Unreal Engine 5 (FBX)", "Epic Games Unreal Engine 5 LODGroup FBX hierarchy"),
    ("UNITY_6", "Unity 6 (FBX)", "Unity Technologies LOD Group FBX naming standard"),
    ("GODOT_4", "Godot 4 (glTF)", "Godot Engine 4.x visibility range glTF metadata standard"),
]

ASSET_CATEGORY_ITEMS: list[tuple[str, str, str]] = [
    ("HERO_CHARACTER", "Hero Character / Aircraft", "Dense primary focus asset (Up to 6 LODs)"),
    ("PROP", "General Prop / Machinery", "Standard environment prop (Up to 4 LODs)"),
    ("FOLIAGE", "Foliage & Nature", "Aggressive planar simplification and alpha preserve (Up to 5 LODs)"),
    (
        "BUILDING",
        "Building & Architecture",
        "Planar dissolve with structural silhouette locking (Up to 4 LODs)",
    ),
    ("MICRO_DEBRIS", "Micro-Debris / Clutter", "Rapid decimation down to dissolution (Up to 2 LODs)"),
]

PROGRESSION_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("EXPONENTIAL", "Exponential (Geometric)", "Standard engine curve (100% -> 50% -> 25% -> 12.5%)"),
    ("LOGARITHMIC", "Logarithmic (Smooth)", "Preserves closer fidelity longer before rapid decay"),
    ("AGGRESSIVE", "Aggressive (Performance)", "Rapid reduction for mobile, VR, or dense sim crowds"),
    ("LINEAR", "Linear (Uniform)", "Uniform step distribution"),
]

CLEANUP_NORMAL_POLICY_ITEMS: list[tuple[str, str, str]] = [
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
]

PBR_IMPORT_PATH_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("RELATIVE", "Relative (//)", "Store image paths relative to .blend file (//) if saved"),
    ("ABSOLUTE", "Absolute", "Store full absolute system paths to textures"),
]

PBR_IMPORT_AO_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("MULTIPLY", "Multiply into Base Color (EEVEE/Cycles)", "Multiply AO map directly into Base Color texture"),
    (
        "SEPARATE",
        "Keep Separate (Game Engine Ready)",
        "Do not blend AO into Base Color (preserves glTF/FBX parity)",
    ),
]

IMPOSTOR_MODE_ITEMS: list[tuple[str, str, str]] = [
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
]

IMPOSTOR_RESOLUTION_ITEMS: list[tuple[str, str, str]] = [
    ("512", "512 x 512 (Low/Mobile)", "512px square atlas"),
    ("1024", "1024 x 1024 (1K)", "1024px square atlas"),
    ("2048", "2048 x 2048 (2K)", "2048px square atlas"),
    ("4096", "4096 x 4096 (4K)", "4096px square atlas"),
]

COLLISION_DECOMPOSITION_MODE_ITEMS: list[tuple[str, str, str]] = [
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
]

HIERARCHY_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("PRESERVE", "Preserve Sub-Meshes", "Each selected object generates individual LOD copies"),
    (
        "MERGE_AT_TIER",
        "Merge at Distant Tiers",
        "Joins compatible sub-meshes into a single draw-call mesh at lower LODs",
    ),
]

CHUNK_PARTITIONING_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("UNIFORM_GRID", "Uniform 2.5D Grid", "Equal-sized spatial cells across the bounding box"),
    (
        "ADAPTIVE_CLUSTERING",
        "Adaptive Cell Clustering",
        "Clusters sparse adjacent cells into larger chunks to balance polycount without T-junctions",
    ),
]

MAX_BONE_INFLUENCES_ITEMS: list[tuple[str, str, str]] = [
    ("4", "4 Influences (Standard GPU)", "Standard GPU vertex shader register limit (glTF, Mobile, Unity)"),
    ("8", "8 Influences (High-End)", "Unreal Engine 5 high-precision skinning"),
]

TEXTURE_MAX_RESOLUTION_ITEMS: list[tuple[str, str, str]] = [
    ("4096", "4K (4096x4096)", "4K texture resolution"),
    ("2048", "2K (2048x2048)", "2K texture resolution"),
    ("1024", "1K (1024x1024)", "1K texture resolution"),
]

PBR_EXPORT_TEXTURE_STRATEGY_ITEMS: list[tuple[str, str, str]] = [
    (
        "SMART_AUTO",
        "Smart Auto (Zero-Copy or Bake)",
        "Direct channel extraction for images, automatic Cycles bake only for procedural/unlinked nodes",
    ),
    (
        "PASSTHROUGH",
        "Direct Passthrough / Zero-Copy",
        "Direct channel extraction only, fills unlinked channels with defaults, never bakes",
    ),
    ("BAKE", "Force Cycles Bake", "Forces full Cycles bake for all material channels to target resolution"),
    (
        "CONVERT_PNG",
        "Convert & Pack (Legacy)",
        "Re-encode all textures to standard PNG matching preset bit depth",
    ),
]

PBR_EXPORT_BIT_DEPTH_ITEMS: list[tuple[str, str, str]] = [
    ("8", "8-Bit PNG", "Standard 8-bit per channel PNG format"),
    ("16", "16-Bit PNG", "High dynamic range 16-bit per channel PNG format"),
]

SIMULATOR_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("LIVE_ORBIT", "Live Viewport Orbit", "Evaluate LOD distances dynamically as you orbit/zoom in Viewport"),
    (
        "VIRTUAL_SLIDER",
        "Virtual Distance Slider",
        "Interactive Unity-style distance/screen size slider override",
    ),
    ("CAMERA_LOCKED", "Lock to Scene Camera", "Evaluate LOD distances strictly from active Scene Camera"),
]

SIMULATOR_CAMERA_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("VIEWPORT", "3D Viewport Camera", "Tracks active 3D Viewport orbit/fly navigation camera"),
    ("ACTIVE_SCENE", "Active Scene Camera", "Tracks scene camera (bpy.context.scene.camera)"),
]

LOD_PRESET_BUDGET_MODE_ITEMS: list[tuple[str, str, str]] = [
    ("PERCENTAGE", "Percentage", "Relative triangle reduction percentage across tiers"),
    ("ABSOLUTE", "Absolute Tris", "Explicit absolute triangle budget per tier"),
]

BATCH_FILE_FORMATS_ITEMS: list[tuple[str, str, str]] = [
    ("ALL", "All Supported (*.fbx, *.gltf, *.glb, *.obj, *.blend)", "Process all 3D formats"),
    ("FBX", "FBX (*.fbx)", "Process FBX files only"),
    ("GLTF", "glTF / GLB (*.gltf, *.glb)", "Process glTF/GLB files only"),
    ("BLEND", "Blender (*.blend)", "Process .blend files only"),
]

ENGINE_IMPORT_MODEL_TARGET_ITEMS: list[tuple[str, str, str]] = [
    ("EXTERIOR_ONLY", "Exterior Only", "Import exterior airframe LODs (normal model)"),
    ("INTERIOR_ONLY", "Interior Only", "Import interior / cockpit flight deck LODs"),
    (
        "BOTH_SEPARATE",
        "Both (Separate Collections)",
        "Import both exterior and interior into dedicated sibling collections",
    ),
]

MSFS_GEAR_STATE_ITEMS: list[tuple[str, str, str]] = [
    ("STATIC_COMPRESSED", "Static (Compressed)", "Landing gear in model is compressed under aircraft weight"),
    ("UNCOMPRESSED_EXTENDED", "Uncompressed (Extended)", "Landing gear in model is fully extended without load"),
]
