"""
UI PropertyGroups for LOD Tool with Rigging, Hierarchy & Live Simulator Settings.
"""

from __future__ import annotations

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

    def StringProperty(**kw):
        return None

    def BoolProperty(**kw):
        return None

    def IntProperty(**kw):
        return None

    def FloatProperty(**kw):
        return None

    def EnumProperty(**kw):
        return None

    def CollectionProperty(**kw):
        return None

    def PointerProperty(**kw):
        return None


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
    )
    asset_category: EnumProperty(
        name="Asset Role",
        items=[
            ("SCENERY", "Scenery / Large Structure", "Airports, buildings, bridges, large props"),
            ("VEHICLE_AIRFRAME", "Aircraft / Vehicle Exterior", "Fuselage, wings, hull, exterior mechanical parts"),
            ("CHARACTER_RIGGED", "Character / Rigged Asset", "Skeletal skinned meshes, creatures, characters"),
            ("INTERIOR", "Cockpit / Interior", "Detailed instruments, cabin seating, controls"),
            ("PROP_CLUTTER", "Prop / Airport Clutter", "Cargo carts, luggage, signs, small props"),
            ("FOLIAGE", "Vegetation / Foliage", "Trees, shrubs, grass clusters"),
        ],
        default="SCENERY",
    )
    tau_sse: FloatProperty(name="Visual Stability (SSE)", default=0.8, min=0.2, max=3.0, precision=2)
    cull_screen_size_pct: FloatProperty(
        name="Cull Screen Size (%)", default=0.5, min=0.01, max=10.0, precision=2, subtype="PERCENTAGE"
    )
    num_lods: IntProperty(name="LOD Count", default=7, min=2, max=8)
    preserve_slot_indexing: BoolProperty(name="Preserve Slot Indices", default=True)

    # Multi-Object & Hierarchy Settings
    hierarchy_mode: EnumProperty(
        name="Hierarchy Mode",
        items=[
            ("PRESERVE_HIERARCHY", "Preserve Hierarchy", "Keep all submesh objects separate across all LOD tiers"),
            (
                "MERGE_AT_TIER",
                "Merge Distant Tiers",
                "Consolidate compatible submeshes into a single draw call at distant tiers",
            ),
        ],
        default="PRESERVE_HIERARCHY",
    )
    merge_start_tier: IntProperty(
        name="Merge Start Tier",
        default=3,
        min=1,
        max=6,
        description="LOD tier index from which compatible meshes are merged into a single draw call",
    )

    # Rigging & Skinning Optimization
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

    # Real-Time LOD Simulator Controls
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
    is_simulator_running: BoolProperty(name="Simulator Running", default=False)

    is_preview_active: BoolProperty(name="Live Viewport Preview", default=False)
    preview_screen_pct: FloatProperty(
        name="Preview Screen %", default=100.0, min=0.01, max=100.0, subtype="PERCENTAGE", precision=1
    )
    forced_lod_index: IntProperty(name="Force LOD Tier", default=0, min=0, max=7)
    lods: CollectionProperty(type=LODLevelItem)
    active_lod_index: IntProperty(name="Active LOD Selection", default=0)
    export_directory: StringProperty(name="Export Directory", subtype="DIR_PATH", default="//Export/")
    export_base_name: StringProperty(name="Asset Base Name", default="")


def register_properties():
    if not bpy:
        return
    bpy.utils.register_class(LODLevelItem)
    bpy.utils.register_class(LODPipelineProperties)
    bpy.types.Scene.lod_tool = PointerProperty(type=LODPipelineProperties)


def unregister_properties():
    if not bpy:
        return
    if hasattr(bpy.types.Scene, "lod_tool"):
        del bpy.types.Scene.lod_tool
    bpy.utils.unregister_class(LODPipelineProperties)
    bpy.utils.unregister_class(LODLevelItem)
