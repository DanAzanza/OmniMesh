"""
OmniMesh - All-in-One 3D Mesh Optimization, Topology Sanitization, Skeletal Rigging, Real-Time LOD Simulation & Multi-Engine Pipeline.
Blender 4.2+ and 5.2 LTS Add-on.
"""

from __future__ import annotations

import importlib
import sys

bl_info = {
    "name": "OmniMesh",
    "author": "Daniel (DanAzanza)",
    "version": (1, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > OmniMesh",
    "description": "Screen-Space Error driven LOD generation, topology sanitization, multi-mesh hierarchies, skeletal rigging, bone pruning, real-time viewport simulator, and multi-engine export (MSFS 2024, UE5, Unity 6, Godot 4)",
    "category": "Mesh",
}

if __package__:
    from . import bridges
    from .core import (
        animations,
        batch,
        decimator,
        hierarchy,
        materials,
        metrics,
        normals,
        rigging,
        sanitizer,
        simulator,
        textures,
    )
    from .exporters import engine_export, godot_export, msfs_export, ue5_export, unity_export
    from .ui import batch_panel, hud, panel, properties, simulator_ops, split_preview
else:
    import bridges
    from core import (
        animations,
        batch,
        decimator,
        hierarchy,
        materials,
        metrics,
        normals,
        rigging,
        sanitizer,
        simulator,
        textures,
    )
    from exporters import engine_export, godot_export, msfs_export, ue5_export, unity_export
    from ui import batch_panel, hud, panel, properties, simulator_ops, split_preview

# Dynamic reloading for live development sessions
if "bpy" in locals() and "bpy" in sys.modules:
    importlib.reload(metrics)
    importlib.reload(sanitizer)
    importlib.reload(decimator)
    importlib.reload(materials)
    importlib.reload(normals)
    importlib.reload(hierarchy)
    importlib.reload(rigging)
    importlib.reload(textures)
    importlib.reload(animations)
    importlib.reload(batch)
    importlib.reload(bridges)
    importlib.reload(simulator)
    importlib.reload(properties)
    importlib.reload(panel)
    importlib.reload(simulator_ops)
    importlib.reload(batch_panel)
    importlib.reload(split_preview)
    importlib.reload(hud)
    importlib.reload(msfs_export)
    importlib.reload(ue5_export)
    importlib.reload(unity_export)
    importlib.reload(godot_export)
    importlib.reload(engine_export)


def register():
    properties.register_properties()
    panel.register_panel()
    simulator_ops.register_simulator_ops()
    batch_panel.register_batch_ops()
    split_preview.register_split_ops()
    engine_export.register_exporters()
    hud.LODViewportHUD.register()


def unregister():
    hud.LODViewportHUD.unregister()
    engine_export.unregister_exporters()
    split_preview.unregister_split_ops()
    batch_panel.unregister_batch_ops()
    simulator_ops.unregister_simulator_ops()
    panel.unregister_panel()
    properties.unregister_properties()
