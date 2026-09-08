"""
OmniMesh Headless Batch Worker Script (Forwarder).

Relocated to scripts/batch_worker.py per AGENTS.md clean architecture guidelines.
This stub maintains backward compatibility for existing external scripts and CLI invocations.
"""

from __future__ import annotations

import os
import runpy
import sys

_scripts_worker = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "batch_worker.py"
)

if __name__ == "__main__":
    if os.path.exists(_scripts_worker):
        runpy.run_path(_scripts_worker, run_name="__main__")
    else:
        sys.exit(1)
