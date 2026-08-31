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
    from .core import decimator, hierarchy, materials, metrics, normals, rigging, sanitizer, simulator
    from .exporters import engine_export, godot_export, msfs_export, ue5_export, unity_export
    from .ui import hud, panel, properties, simulator_ops
else:
    from core import decimator, hierarchy, materials, metrics, normals, rigging, sanitizer, simulator
    from exporters import engine_export, godot_export, msfs_export, ue5_export, unity_export
    from ui import hud, panel, properties, simulator_ops

# Dynamic reloading for live development sessions
if "bpy" in locals() and "bpy" in sys.modules:
    importlib.reload(metrics)
    importlib.reload(sanitizer)
    importlib.reload(decimator)
    importlib.reload(materials)
    importlib.reload(normals)
    importlib.reload(hierarchy)
    importlib.reload(rigging)
    importlib.reload(simulator)
    importlib.reload(properties)
    importlib.reload(panel)
    importlib.reload(simulator_ops)
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
    engine_export.register_exporters()
    hud.LODViewportHUD.register()


def unregister():
    hud.LODViewportHUD.unregister()
    engine_export.unregister_exporters()
    simulator_ops.unregister_simulator_ops()
    panel.unregister_panel()
    properties.unregister_properties()


if __name__ == "__main__":
    register()
