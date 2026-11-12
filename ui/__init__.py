"""
UI package for OmniMesh add-on with modular subpanel hierarchy.
"""

from __future__ import annotations

from .config_preset_ops import register as register_config_presets, unregister as unregister_config_presets
from .engine_import_ops import register as register_engine_import, unregister as unregister_engine_import
from .interaction_ops import register as register_interaction_ops, unregister as unregister_interaction_ops
from .lists import register_lists, unregister_lists
from .operators import register_operators, unregister_operators
from .panel import register_panel, unregister_panel
from .properties import register_properties, unregister_properties
from .setup_ops import register as register_setup_ops, unregister as unregister_setup_ops
from .simulator_ops import register_simulator_ops, unregister_simulator_ops
from .vehicle_attachment_ops import (
    register as register_vehicle_attachments,
    unregister as unregister_vehicle_attachments,
)
from .vehicle_camera_ops import register as register_vehicle_cameras, unregister as unregister_vehicle_cameras
from .vehicle_ground_ops import register as register_vehicle_ground, unregister as unregister_vehicle_ground
from .vehicle_lighting_ops import register as register_vehicle_lighting, unregister as unregister_vehicle_lighting
from .vehicle_spatial_ops import register as register_vehicle_spatial, unregister as unregister_vehicle_spatial


def register_ui() -> None:
    register_properties()
    register_lists()
    register_operators()
    register_setup_ops()
    register_config_presets()
    register_interaction_ops()
    register_engine_import()
    register_vehicle_spatial()
    register_vehicle_ground()
    register_vehicle_lighting()
    register_vehicle_cameras()
    register_vehicle_attachments()
    register_panel()

    register_simulator_ops()


def unregister_ui() -> None:
    unregister_simulator_ops()
    unregister_panel()
    unregister_vehicle_attachments()
    unregister_vehicle_cameras()
    unregister_vehicle_lighting()
    unregister_vehicle_ground()
    unregister_vehicle_spatial()

    unregister_engine_import()
    unregister_interaction_ops()
    unregister_config_presets()
    unregister_setup_ops()
    unregister_operators()
    unregister_lists()
    unregister_properties()
