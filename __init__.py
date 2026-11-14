"""
OmniMesh - All-in-One 3D Mesh Optimization, Topology Sanitization, Skeletal Rigging, Real-Time LOD Simulation & Multi-Engine Pipeline.
Blender 5.0+ and 5.2 LTS Add-on.
"""

from __future__ import annotations

import importlib
import logging
from types import ModuleType

logger = logging.getLogger(__name__)

bl_info = {
    "name": "OmniMesh",
    "author": "Daniel (DanAzanza)",
    "version": (0, 8, 5),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > OmniMesh",
    "description": "Screen-Space Error driven LOD generation, topology sanitization, occlusion culling, collision hulls, multi-mesh hierarchies, skeletal rigging, bone pruning, billboard impostors, real-time viewport simulator, and multi-engine export (MSFS 2024, UE5, Unity 6)",
    "category": "Mesh",
}

_OMNIMESH_RELOAD = "_OMNIMESH_INITIALIZED" in locals()
_OMNIMESH_INITIALIZED = True

# Topologically ordered leaf-to-package submodule list so live reload updates every module cleanly.
_SUBMODULE_NAMES: tuple[str, ...] = (
    # 1. Core foundation & pure domain utilities
    "core.exceptions",
    "core.io_utils",
    "core.lod_protocols",
    "core.compat",
    "core.metrics",
    "core.png_writer",
    "core.modifiers",
    "core.lod_stats",
    "core.topology_repair",
    "core.normals",
    "core.pivot",
    # 2. Core mesh processing & optimization
    "core.decimator",
    "core.sanitizer",
    "core.occlusion",
    "core.collision",
    "core.collision_decomposer",
    "core.slender",
    "core.recursive_hlod",
    "core.chunking",
    "core.chunk_merger",
    "core.mesh_merge",
    "core.scene_setup",
    "core.hierarchy",
    "core.asset_scanner",
    # 3. Core textures & materials
    "core.pbr_classifier",
    "core.texture_pool",
    "core.texture_resolver",
    "core.texture_relinker",
    "core.textures",
    "core.shader_tracer",
    "core.material_analyzer",
    "core.materials",
    "core.material_presets",
    "core.pbr_presets",
    "core.pbr_importer",
    # 4. Core impostors
    "core.impostor_math",
    "core.impostor_rig",
    "core.impostor_harness",
    "core.impostor_ortho_baker",
    "core.impostor_repacker",
    "core.impostor_preview_material",
    "core.impostor_preview",
    "core.impostor_baker",
    "core.impostor",
    # 5. Core MSFS subsystem
    "core.msfs.models",
    "core.msfs.transforms",
    "core.msfs.spatial_parsers",
    "core.msfs.camera_cst",
    "core.msfs.attachments_cst",
    "core.msfs.cst_parser",
    "core.msfs.project_scanner",
    "core.msfs.xml_merger",
    "core.msfs",
    # 6. Core orchestration, presets & rigging
    "core.animations",
    "core.animation_manager",
    "core.gltf_assembly",
    "core.rigging",
    "core.interaction_volumes",
    "core.vehicle_geometry",
    "core.preset_anchor",
    "core.preset_spawner",
    "core.config_presets",
    "core.engine_import_presets",
    "core.lod_presets",
    "core.lod_generator",
    "core.simulator",
    "core",
    # 7. Exporters
    "exporters.shaders.unity_octahedral",
    "exporters.shaders.unreal_octahedral",
    "exporters.shaders",
    "exporters.base",
    "exporters.engine_export",
    "exporters.msfs_export",
    "exporters.ue5_export",
    "exporters.unity_export",
    "exporters.manager",
    "exporters",
    # 8. UI properties (leaves before ui.properties package)
    "ui.properties.guards",
    "ui.rna_helpers",
    "ui.properties.enums",
    "ui.properties.callbacks",
    "ui.properties.settings",
    "ui.properties.cleanup_settings",
    "ui.properties.engine_settings",
    "ui.properties.animation_properties",
    "ui.properties.interaction_properties",
    "ui.properties.lod_properties",
    "ui.properties.material_properties",
    "ui.properties.pbr_properties",
    "ui.properties.config_properties",
    "ui.properties.msfs_cfg_properties",
    "ui.properties",
    # 9. UI helpers, operators & panels
    "ui.utils",
    "ui.lists",
    "ui.popover_presets",
    "ui.popovers",
    "ui.panel_helpers",
    "ui.cleanup_ops",
    "ui.chunk_ops",
    "ui.config_preset_ops",
    "ui.interaction_ops",
    "ui.hull_impostor_ops",
    "ui.impostor_viewport_ops",
    "ui.lod_preset_ops",
    "ui.lod_ops",
    "ui.pbr_map_ops",
    "ui.pbr_preset_ops",
    "ui.pbr_ops",
    "ui.preset_ops",
    "ui.export_ops",
    "ui.engine_import_helpers",
    "ui.engine_import_ops",
    "ui.vehicle_spatial_ops",
    "ui.vehicle_ground_ops",
    "ui.vehicle_lighting_ops",
    "ui.vehicle_camera_ops",
    "ui.vehicle_attachment_ops",
    "ui.setup_ops",
    "ui.simulator_ops",
    "ui.operators",
    "ui.panel",
    "ui",
)


def _import_submodule(dotted_name: str) -> ModuleType:
    """Imports an add-on submodule cleanly whether loaded as a package or top-level."""
    if __package__:
        return importlib.import_module(f".{dotted_name}", package=__package__)
    return importlib.import_module(dotted_name)


_LOADED_SUBMODULES: list[ModuleType] = [_import_submodule(name) for name in _SUBMODULE_NAMES]

# Dynamic reloading for live development sessions
if _OMNIMESH_RELOAD:
    try:
        unreg = globals().get("unregister")
        if callable(unreg):
            unreg()
    except Exception as exc:
        logger.debug("Pre-reload unregister exception: %s", exc)

    _LOADED_SUBMODULES = [importlib.reload(mod) for mod in _LOADED_SUBMODULES]

if __package__:
    from .core import textures as textures
    from .exporters import engine_export as engine_export
    from .ui import (
        config_preset_ops,
        engine_import_ops,
        interaction_ops,
        lists,
        operators,
        panel,
        properties,
        setup_ops,
        simulator_ops,
        vehicle_attachment_ops,
        vehicle_camera_ops,
        vehicle_ground_ops,
        vehicle_lighting_ops,
        vehicle_spatial_ops,
    )
else:
    from core import textures as textures
    from exporters import engine_export as engine_export
    from ui import (
        config_preset_ops,
        engine_import_ops,
        interaction_ops,
        lists,
        operators,
        panel,
        properties,
        setup_ops,
        simulator_ops,
        vehicle_attachment_ops,
        vehicle_camera_ops,
        vehicle_ground_ops,
        vehicle_lighting_ops,
        vehicle_spatial_ops,
    )


def register():
    properties.register_properties()
    lists.register_lists()
    operators.register_operators()
    config_preset_ops.register()
    interaction_ops.register()
    engine_import_ops.register()
    vehicle_spatial_ops.register()
    vehicle_ground_ops.register()
    vehicle_lighting_ops.register()
    vehicle_camera_ops.register()
    vehicle_attachment_ops.register()
    setup_ops.register()
    panel.register_panel()
    simulator_ops.register_simulator_ops()
    engine_export.register_exporters()


def unregister():
    for fn in (
        engine_export.unregister_exporters,
        simulator_ops.unregister_simulator_ops,
        panel.unregister_panel,
        setup_ops.unregister,
        vehicle_attachment_ops.unregister,
        vehicle_camera_ops.unregister,
        vehicle_lighting_ops.unregister,
        vehicle_ground_ops.unregister,
        vehicle_spatial_ops.unregister,
        engine_import_ops.unregister,
        interaction_ops.unregister,
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
