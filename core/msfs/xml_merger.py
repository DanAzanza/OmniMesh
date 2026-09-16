"""
OmniMesh MSFS ModelInfo XML Surgical Merger.
Provides non-destructive, block-level XML merging for MSFS 2020 / 2024 ModelInfo files.

Unlike DOM parsers (e.g. xml.etree.ElementTree) which discard XML comments, strip CDATA,
and alter RPN script logic (<Code>) inside <CompileBehaviors>, this merger performs
surgical slice replacements of the <LODS> section while preserving existing formatting,
line endings (CRLF vs LF), and 100% of existing behavior and animation code.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any

logger = logging.getLogger(__name__)


class ModelXMLMerger:
    """Surgically updates or injects <LODS> into existing MSFS ModelInfo XML documents."""

    _LODS_REGEX = re.compile(
        r"([ \t]*)<LODS(?:\s+[^>]*)?>.*?</LODS>",
        re.DOTALL | re.IGNORECASE,
    )
    _MODEL_INFO_OPEN_REGEX = re.compile(
        r"(<ModelInfo(?:\s+[^>]*)?>)",
        re.IGNORECASE,
    )

    @classmethod
    def format_lods_block(
        cls,
        tiers: list[dict[str, Any]],
        base_indent: str = "    ",
        line_ending: str = "\n",
    ) -> str:
        """Formats the <LODS> block cleanly with consistent indentation.

        Each tier is expected to have 'min_size' (or 'screen_size_pct') and 'model_file'.
        """
        inner_indent = base_indent + "    "
        lines = [f"{base_indent}<LODS>"]

        for tier in tiers:
            min_size = tier.get("min_size", tier.get("screen_size_pct", 0.0))
            # Format minSize cleanly (strip trailing zeroes if integer)
            size_str = f"{min_size:.4f}".rstrip("0").rstrip(".") if min_size != int(min_size) else str(int(min_size))
            model_file = tier.get("model_file", "")
            lines.append(f'{inner_indent}<LOD minSize="{size_str}" ModelFile="{model_file}"/>')

        lines.append(f"{base_indent}</LODS>")
        return line_ending.join(lines)

    @classmethod
    def merge_lods_into_xml_content(
        cls,
        xml_content: str,
        tiers: list[dict[str, Any]],
    ) -> str:
        """Replaces or injects the <LODS> section into existing XML string without touching other tags."""
        # Detect line endings in the source document
        line_ending = "\r\n" if "\r\n" in xml_content else "\n"

        # Check if an existing <LODS> block is present
        match = cls._LODS_REGEX.search(xml_content)
        if match:
            base_indent = match.group(1) or "    "
            new_lods = cls.format_lods_block(tiers, base_indent=base_indent, line_ending=line_ending)
            start, end = match.span()
            return xml_content[:start] + new_lods + xml_content[end:]

        # If no <LODS> block, search for <ModelInfo ...> opening tag and inject right after it
        model_info_match = cls._MODEL_INFO_OPEN_REGEX.search(xml_content)
        if model_info_match:
            insert_pos = model_info_match.end()
            new_lods = cls.format_lods_block(tiers, base_indent="    ", line_ending=line_ending)
            injection = f"{line_ending}{new_lods}{line_ending}"
            return xml_content[:insert_pos] + injection + xml_content[insert_pos:]

        # Fallback: if no <ModelInfo> tag found, construct a minimal complete document
        new_lods = cls.format_lods_block(tiers, base_indent="    ", line_ending=line_ending)
        return (
            f'<?xml version="1.0" encoding="utf-8"?>{line_ending}'
            f"<ModelInfo>{line_ending}"
            f"{new_lods}{line_ending}"
            f"</ModelInfo>{line_ending}"
        )

    @classmethod
    def merge_lods_file(
        cls,
        target_xml_path: Path | str,
        tiers: list[dict[str, Any]],
    ) -> bool:
        """Reads existing target_xml_path if present, merges the new LODS block, and writes it back atomically."""
        path = Path(target_xml_path).resolve()
        has_bom = False

        if path.is_file():
            try:
                raw_bytes = path.read_bytes()
                has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
                if has_bom:
                    raw_bytes = raw_bytes[3:]
                try:
                    xml_str = raw_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    xml_str = raw_bytes.decode("cp1252", errors="replace")
            except OSError as exc:
                logger.warning("Could not read existing ModelInfo XML '%s': %s", path, exc)
                xml_str = ""
        else:
            xml_str = ""

        merged = cls.merge_lods_into_xml_content(xml_str, tiers)

        # Atomic write
        temp_file = path.with_suffix(".tmp_xml")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            encoded = merged.encode("utf-8")
            if has_bom:
                encoded = b"\xef\xbb\xbf" + encoded
            temp_file.write_bytes(encoded)
            temp_file.replace(path)
            return True
        except OSError as exc:
            logger.error("Failed atomically writing merged XML '%s': %s", path, exc)
            if temp_file.is_file():
                try:
                    temp_file.unlink()
                except OSError:
                    pass
            return False
