"""
MSFS CST Parser Re-export Facade.
Provides backward compatibility while delegating to the unified core.msfs package.
"""

from __future__ import annotations

from core.msfs.cst_parser import *  # noqa: F403
from core.msfs.cst_parser import MSFSCSTParser

__all__ = [
    "MSFSCSTParser",
]
