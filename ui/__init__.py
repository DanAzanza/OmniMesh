"""
UI package for OmniMesh add-on with modular subpanel hierarchy.
"""

from __future__ import annotations

from .batch_panel import register_batch_ops, unregister_batch_ops
from .hud import LODViewportHUD
from .lists import register_lists, unregister_lists
from .operators import register_operators, unregister_operators
from .panel import register_panel, unregister_panel
from .properties import register_properties, unregister_properties
from .simulator_ops import register_simulator_ops, unregister_simulator_ops
from .split_preview import register_split_ops, unregister_split_ops


def register_ui() -> None:
    register_properties()
    register_lists()
    register_operators()
    register_panel()
    register_simulator_ops()
    register_batch_ops()
    register_split_ops()
    LODViewportHUD.register()


def unregister_ui() -> None:
    LODViewportHUD.unregister()
    unregister_split_ops()
    unregister_batch_ops()
    unregister_simulator_ops()
    unregister_panel()
    unregister_operators()
    unregister_lists()
    unregister_properties()
