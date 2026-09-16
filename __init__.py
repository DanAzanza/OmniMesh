"""
OmniMesh - All-in-One 3D Mesh Optimization, Topology Sanitization, Skeletal Rigging, Real-Time LOD Simulation & Multi-Engine Pipeline.
Blender 5.0+ and 5.2 LTS Add-on.
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

bl_info = {
    "name": "OmniMesh",
    "author": "Daniel (DanAzanza)",
    "version": (0, 8, 1),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > OmniMesh",
    "description": "Screen-Space Error driven LOD generation, topology sanitization, occlusion culling, collision hulls, multi-mesh hierarchies, skeletal rigging, bone pruning, billboard impostors, real-time viewport simulator, and multi-engine export (MSFS 2024, UE5, Unity 6, Godot 4)",
    "category": "Mesh",
}

_OMNIMESH_RELOAD = "_OMNIMESH_INITIALIZED" in locals()
_OMNIMESH_INITIALIZED = True

if __package__:
    from . import bridges
    from . import core as core
    from . import exporters as exporters
    from . import ui as ui
    from .core import (
        animation_manager,
        animations,
        asset_scanner,
        batch,
        batch_worker,
        chunking,
        collision,
        config_presets,
        decimator,
        engine_import_presets,
        gltf_assembly,
        hierarchy,
        impostor,
        interaction_volumes,
        lod_generator,
        lod_presets,
        material_analyzer,
        material_presets,
        materials,
        metrics,
        modifiers,
        msfs,
        msfs_camera_cst,
        msfs_cst_parser,
        msfs_geometry,
        msfs_models,
        msfs_project_scanner,
        msfs_transforms,
        msfs_xml_merger,
        normals,
        occlusion,
        pbr_importer,
        pbr_presets,
        pivot,
        png_writer,
        project_detector,
        rigging,
        sanitizer,
        shader_tracer,
        simulator,
        slender,
        texture_pool,
        textures,
        topology_repair,
    )
    from .exporters import (
        base as exporter_base,
    )
    from .exporters import (
        engine_export,
        godot_export,
        msfs_export,
        ue5_export,
        unity_export,
    )
    from .exporters import (
        manager as exporter_manager,
    )
    from .ui import (
        animation_ops,
        batch_panel,
        chunk_ops,
        cleanup_ops,
        config_preset_ops,
        engine_import_ops,
        export_ops,
        hud,
        hull_impostor_ops,
        interaction_ops,
        lists,
        lod_ops,
        lod_preset_ops,
        material_preset_ops,
        msfs_camera_ops,
        msfs_ground_ops,
        msfs_lighting_ops,
        msfs_migration_ops,
        msfs_spatial_ops,
        operators,
        panel,
        pbr_ops,
        pbr_preset_ops,
        popovers,
        preset_ops,
        properties,
        simulator_ops,
        split_preview,
        utils,
    )
else:
    import bridges
    from core import (
        animation_manager,
        animations,
        asset_scanner,
        batch,
        batch_worker,
        chunking,
        collision,
        config_presets,
        decimator,
        engine_import_presets,
        gltf_assembly,
        hierarchy,
        impostor,
        interaction_volumes,
        lod_generator,
        lod_presets,
        material_analyzer,
        material_presets,
        materials,
        metrics,
        modifiers,
        msfs,
        msfs_camera_cst,
        msfs_cst_parser,
        msfs_geometry,
        msfs_models,
        msfs_project_scanner,
        msfs_transforms,
        msfs_xml_merger,
        normals,
        occlusion,
        pbr_importer,
        pbr_presets,
        pivot,
        png_writer,
        project_detector,
        rigging,
        sanitizer,
        shader_tracer,
        simulator,
        slender,
        texture_pool,
        textures,
        topology_repair,
    )
    from exporters import (
        base as exporter_base,
    )
    from exporters import (
        engine_export,
        godot_export,
        msfs_export,
        ue5_export,
        unity_export,
    )
    from exporters import (
        manager as exporter_manager,
    )
    from ui import (
        animation_ops,
        batch_panel,
        chunk_ops,
        cleanup_ops,
        config_preset_ops,
        engine_import_ops,
        export_ops,
        hud,
        hull_impostor_ops,
        interaction_ops,
        lists,
        lod_ops,
        lod_preset_ops,
        material_preset_ops,
        msfs_camera_ops,
        msfs_ground_ops,
        msfs_lighting_ops,
        msfs_migration_ops,
        msfs_spatial_ops,
        operators,
        panel,
        pbr_ops,
        pbr_preset_ops,
        popovers,
        preset_ops,
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
        topology_repair,
        sanitizer,
        occlusion,
        collision,
        impostor,
        decimator,
        chunking,
        lod_generator,
        lod_presets,
        asset_scanner,
        project_detector,
        shader_tracer,
        png_writer,
        texture_pool,
        materials,
        material_analyzer,
        pbr_importer,
        pbr_presets,
        pivot,
        slender,
        normals,
        hierarchy,
        rigging,
        textures,
        animations,
        animation_manager,
        batch,
        batch_worker,
        config_presets,
        engine_import_presets,
        gltf_assembly,
        interaction_volumes,
        material_presets,
        msfs,
        msfs_models,
        msfs_transforms,
        msfs_camera_cst,
        msfs_cst_parser,
        msfs_geometry,
        msfs_project_scanner,
        msfs_xml_merger,
        simulator,
    ):
        importlib.reload(mod)

    # 2. Exporters
    for mod in (
        exporter_base,
        msfs_export,
        ue5_export,
        unity_export,
        godot_export,
        exporter_manager,
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
        popovers,
        cleanup_ops,
        chunk_ops,
        config_preset_ops,
        material_preset_ops,
        interaction_ops,
        animation_ops,
        hull_impostor_ops,
        lod_preset_ops,
        lod_ops,
        pbr_preset_ops,
        pbr_ops,
        preset_ops,
        export_ops,
        operators,
        panel,
        simulator_ops,
        batch_panel,
        split_preview,
        hud,
        engine_import_ops,
        msfs_spatial_ops,
        msfs_ground_ops,
        msfs_lighting_ops,
        msfs_camera_ops,
        msfs_migration_ops,
    ):
        importlib.reload(mod)


def register():
    properties.register_properties()
    lists.register_lists()
    operators.register_operators()
    config_preset_ops.register()
    material_preset_ops.register()
    interaction_ops.register()
    animation_ops.register()
    engine_import_ops.register()
    msfs_spatial_ops.register()
    msfs_ground_ops.register()
    msfs_lighting_ops.register()
    msfs_camera_ops.register()
    msfs_migration_ops.register()
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
        msfs_migration_ops.unregister,
        msfs_camera_ops.unregister,
        msfs_lighting_ops.unregister,
        msfs_ground_ops.unregister,
        msfs_spatial_ops.unregister,
        engine_import_ops.unregister,
        animation_ops.unregister,
        interaction_ops.unregister,
        material_preset_ops.unregister,
        config_preset_ops.unregister,
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
