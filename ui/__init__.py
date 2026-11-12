"""
UI package for OmniMesh add-on with modular subpanel hierarchy.
"""

from __future__ import annotations

from .batch_panel import register_batch_ops, unregister_batch_ops
from .config_preset_ops import register as register_config_presets, unregister as unregister_config_presets
from .engine_import_ops import register as register_engine_import, unregister as unregister_engine_import
from .hud import LODViewportHUD
from .interaction_ops import register as register_interaction_ops, unregister as unregister_interaction_ops
from .lists import register_lists, unregister_lists
from .msfs_camera_ops import register as register_msfs_cameras, unregister as unregister_msfs_cameras
from .msfs_ground_ops import register as register_msfs_ground, unregister as unregister_msfs_ground
from .msfs_lighting_ops import register as register_msfs_lighting, unregister as unregister_msfs_lighting
from .msfs_spatial_ops import register as register_msfs_spatial, unregister as unregister_msfs_spatial
from .msfs_attachment_ops import register as register_msfs_attachments, unregister as unregister_msfs_attachments
from .operators import register_operators, unregister_operators
from .panel import register_panel, unregister_panel
from .properties import register_properties, unregister_properties
from .setup_ops import register as register_setup_ops, unregister as unregister_setup_ops
from .simulator_ops import register_simulator_ops, unregister_simulator_ops


def register_ui() -> None:
    register_properties()
    register_lists()
    register_operators()
    register_setup_ops()
    register_config_presets()
    register_interaction_ops()
    register_engine_import()
    register_msfs_spatial()
    register_msfs_ground()
    register_msfs_lighting()
    register_msfs_cameras()
    register_msfs_attachments()
    register_panel()

    register_simulator_ops()
    register_batch_ops()
    LODViewportHUD.register()


def unregister_ui() -> None:
    LODViewportHUD.unregister()
    unregister_batch_ops()
    unregister_simulator_ops()
    unregister_panel()
    unregister_msfs_attachments()
    unregister_msfs_cameras()
    unregister_msfs_lighting()
    unregister_msfs_ground()
    unregister_msfs_spatial()

    unregister_engine_import()
    unregister_interaction_ops()
    unregister_config_presets()
    unregister_setup_ops()
    unregister_operators()
    unregister_lists()
    unregister_properties()
