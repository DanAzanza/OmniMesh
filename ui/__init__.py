"""
UI package for LOD Tool add-on.
"""

from .hud import LODViewportHUD
from .panel import register_panel, unregister_panel
from .properties import register_properties, unregister_properties
from .simulator_ops import register_simulator_ops, unregister_simulator_ops


def register_ui():
    register_properties()
    register_panel()
    register_simulator_ops()
    LODViewportHUD.register()


def unregister_ui():
    LODViewportHUD.unregister()
    unregister_simulator_ops()
    unregister_panel()
    unregister_properties()
