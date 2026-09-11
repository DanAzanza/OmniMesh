"""
OmniMesh - All-in-One 3D Mesh Optimization, Topology Sanitization, Skeletal Rigging, Real-Time LOD Simulation & Multi-Engine Pipeline.
Blender 4.2+ and 5.2 LTS Add-on.
"""

from __future__ import annotations

import importlib
import logging

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

_OMNIMESH_RELOAD = "_OMNIMESH_INITIALIZED" in locals()
_OMNIMESH_INITIALIZED = True

if __package__:
    from . import bridges
    from .core import (
        animations,
        batch,
        chunking,
        collision,
        decimator,
        hierarchy,
        impostor,
        materials,
        metrics,
        modifiers,
        normals,
        occlusion,
        pbr_importer,
        pbr_presets,
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
        chunk_ops,
        cleanup_ops,
        hud,
        hull_impostor_ops,
        lists,
        lod_ops,
        msfs_spatial_ops,
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
        chunking,
        collision,
        decimator,
        hierarchy,
        impostor,
        materials,
        metrics,
        modifiers,
        normals,
        occlusion,
        pbr_importer,
        pbr_presets,
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
        chunk_ops,
        cleanup_ops,
        hud,
        hull_impostor_ops,
        lists,
        lod_ops,
        msfs_spatial_ops,
        operators,
        panel,
        pbr_ops,
        properties,
        simulator_ops,
        split_preview,
        utils,
    )

# Dynamic reloading for live development sessions
if _OMNIMESH_RELOAD:
    try:
        unreg = globals().get("unregister")
        if callable(unreg):
            unreg()
    except Exception as exc:
        logger.debug("Pre-reload unregister exception: %s", exc)

    # 1. Core modules
    for mod in (
        metrics,
        modifiers,
        sanitizer,
        occlusion,
        collision,
        impostor,
        decimator,
        chunking,
        materials,
        pbr_importer,
        pbr_presets,
        pivot,
        slender,
        normals,
        hierarchy,
        rigging,
        textures,
        animations,
        batch,
        simulator,
    ):
        importlib.reload(mod)

    # 2. Exporters
    for mod in (
        msfs_export,
        ue5_export,
        unity_export,
        godot_export,
        engine_export,
    ):
        importlib.reload(mod)

    # 3. Bridges
    importlib.reload(bridges)

    # 4. UI Layer
    for mod in (
        properties,
        lists,
        utils,
        cleanup_ops,
        chunk_ops,
        hull_impostor_ops,
        lod_ops,
        pbr_ops,
        operators,
        panel,
        simulator_ops,
        batch_panel,
        split_preview,
        hud,
        msfs_spatial_ops,
    ):
        importlib.reload(mod)


def register():
    properties.register_properties()
    lists.register_lists()
    operators.register_operators()
    msfs_spatial_ops.register()
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
        msfs_spatial_ops.unregister,
        operators.unregister_operators,
        lists.unregister_lists,
        properties.unregister_properties,
    ):
        try:
            fn()
        except Exception as exc:
            logger.debug("Failed unregistering %s: %s", getattr(fn, "__name__", "fn"), exc)

    try:
        textures.TexturePoolManager.shutdown()
    except Exception as exc:
        logger.debug("Texture pool shutdown exception: %s", exc)


if __name__ == "__main__":
    register()
