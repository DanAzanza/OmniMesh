"""
OmniMesh - All-in-One 3D Mesh Optimization, Topology Sanitization, Skeletal Rigging, Real-Time LOD Simulation & Multi-Engine Pipeline.
Blender 4.2+ and 5.2 LTS Add-on.
"""

from __future__ import annotations

import importlib
import logging
import sys

logger = logging.getLogger(__name__)

bl_info = {
    "name": "OmniMesh",
    "author": "Daniel (DanAzanza)",
    "version": (1, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > OmniMesh",
    "description": "Screen-Space Error driven LOD generation, topology sanitization, occlusion culling, collision hulls, multi-mesh hierarchies, skeletal rigging, bone pruning, billboard impostors, real-time viewport simulator, and multi-engine export (MSFS 2024, UE5, Unity 6, Godot 4)",
    "category": "Mesh",
}

if __package__:
    from . import bridges
    from .core import (
        animations,
        batch,
        collision,
        decimator,
        hierarchy,
        impostor,
        materials,
        metrics,
        normals,
        occlusion,
        pbr_importer,
        pivot,
        rigging,
        sanitizer,
        simulator,
        slender,
        textures,
    )
    from .exporters import engine_export, godot_export, msfs_export, ue5_export, unity_export
    from .ui import (
        batch_panel,
        cleanup_ops,
        hud,
        hull_impostor_ops,
        lists,
        lod_ops,
        operators,
        panel,
        pbr_ops,
        properties,
        simulator_ops,
        split_preview,
        utils,
    )
else:
    import bridges
    from core import (
        animations,
        batch,
        collision,
        decimator,
        hierarchy,
        impostor,
        materials,
        metrics,
        normals,
        occlusion,
        pbr_importer,
        pivot,
        rigging,
        sanitizer,
        simulator,
        slender,
        textures,
    )
    from exporters import engine_export, godot_export, msfs_export, ue5_export, unity_export
    from ui import (
        batch_panel,
        cleanup_ops,
        hud,
        hull_impostor_ops,
        lists,
        lod_ops,
        operators,
        panel,
        pbr_ops,
        properties,
        simulator_ops,
        split_preview,
        utils,
    )

# Dynamic reloading for live development sessions
if "bpy" in locals() and "bpy" in sys.modules:
    importlib.reload(metrics)
    importlib.reload(sanitizer)
    importlib.reload(occlusion)
    importlib.reload(collision)
    importlib.reload(impostor)
    importlib.reload(decimator)
    importlib.reload(materials)
    importlib.reload(pbr_importer)
    importlib.reload(pivot)
    importlib.reload(slender)
    importlib.reload(normals)
    importlib.reload(hierarchy)
    importlib.reload(rigging)
    importlib.reload(textures)
    importlib.reload(animations)
    importlib.reload(batch)
    importlib.reload(bridges)
    importlib.reload(simulator)
    importlib.reload(properties)
    importlib.reload(lists)
    importlib.reload(utils)
    importlib.reload(cleanup_ops)
    importlib.reload(hull_impostor_ops)
    importlib.reload(lod_ops)
    importlib.reload(pbr_ops)
    importlib.reload(operators)
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
    lists.register_lists()
    operators.register_operators()
    panel.register_panel()
    simulator_ops.register_simulator_ops()
    batch_panel.register_batch_ops()
    split_preview.register_split_ops()
    engine_export.register_exporters()
    hud.LODViewportHUD.register()


def unregister():
    for fn in (
        hud.LODViewportHUD.unregister,
        engine_export.unregister_exporters,
        split_preview.unregister_split_ops,
        batch_panel.unregister_batch_ops,
        simulator_ops.unregister_simulator_ops,
        panel.unregister_panel,
        operators.unregister_operators,
        lists.unregister_lists,
        properties.unregister_properties,
    ):
        try:
            fn()
        except Exception as exc:
            logger.debug("Failed unregistering %s: %s", getattr(fn, "__name__", "fn"), exc)


if __name__ == "__main__":
    register()
