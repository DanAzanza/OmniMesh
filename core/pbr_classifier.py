"""
PBR Texture Semantic Classifier for OmniMesh.
Identifies texture map roles (Albedo, ORM, Normal, etc.) using tokenized regexes,
UDIM stripping, resolution filtering, and dynamic JSON preset definitions.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

try:
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImporterPresetManager,
    )
except (ImportError, ValueError):
    from .pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImporterPresetManager,
    )

logger = logging.getLogger(__name__)


class PBRSemanticClassifier:
    """
    Dynamic semantic texture classifier supporting JSON preset templates,
    UDIM stripping, resolution filtering, and token-bounded regex matching.
    """

    STRIP_PATTERNS = [
        re.compile(r"[._-](?:10\d{2}|u\d+_v\d+)(?=\.[^.]+$|$)", re.IGNORECASE),
        re.compile(r"[._-](?:[1-8]k|1024|2048|4096|8192)(?=\.[^.]+$|$)", re.IGNORECASE),
        re.compile(r"[._-](?:lod[0-4]|proxy|high|low)(?=\.[^.]+$|$)", re.IGNORECASE),
        re.compile(r"\.\d{3}$", re.IGNORECASE),
    ]

    @classmethod
    def clean_stem(cls, filename: str) -> str:
        """Strips path, extension, UDIMs, and resolution tags from filename."""
        stem = os.path.splitext(os.path.basename(filename))[0]
        for pattern in cls.STRIP_PATTERNS:
            stem = pattern.sub("", stem)
        return stem

    @classmethod
    def classify_with_preset(cls, filename: str, preset: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
        """
        Classifies filename against a preset's map definitions.
        Sorts all candidate suffixes by length descending to ensure longer tokens
        match before shorter prefixes.
        Returns (map_id, map_dict) or None.
        """
        clean = cls.clean_stem(filename)
        maps = preset.get("maps", [])

        candidates: list[tuple[str, str, dict[str, Any]]] = []
        for m in maps:
            map_id = m.get("id", "")
            for s in m.get("suffixes", []):
                candidates.append((s, map_id, m))

        candidates.sort(key=lambda x: len(x[0]), reverse=True)

        for suffix, map_id, map_def in candidates:
            s_clean = suffix.lstrip("._-")
            pattern = re.compile(rf"(?:^|[._-]){re.escape(s_clean)}(?:[._-]|$)", re.IGNORECASE)
            if pattern.search(clean):
                return map_id, map_def

        return None

    @classmethod
    def classify(cls, filename: str) -> Optional[str]:
        """Backward-compatible fallback classification using default preset."""
        preset = PBRImporterPresetManager.get_preset(DEFAULT_PRESET_ID)
        res = cls.classify_with_preset(filename, preset)
        if res:
            map_id = res[0].upper()
            if map_id == "BASE_COLOR":
                return "BASE_COLOR"
            if map_id == "ORM":
                return "PACKED_ORM"
            if map_id == "NORMAL":
                normal_fmt = res[1].get("normal_format", "OPENGL")
                return "NORMAL_DIRECTX" if normal_fmt == "DIRECTX" else "NORMAL_OPENGL"
            return map_id
        return None
