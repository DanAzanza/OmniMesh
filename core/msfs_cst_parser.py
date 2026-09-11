"""
MSFS Concrete Syntax Tree (CST) Parser & Serializer.
Preserves line-for-line formatting, comments, encoding (BOM), and line endings
with atomic disk writes and timestamped pre-flight backups.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import shutil
import tempfile
from typing import Optional

from .msfs_models import AircraftSpatialConfig, CFGLineRecord, SpatialPoint
from .msfs_transforms import (
    format_coordinate_float,
    msfs_to_blender,
)

logger = logging.getLogger(__name__)


class MSFSCSTParser:
    """Lossless parser and serializer for MSFS aircraft configuration files."""

    @staticmethod
    def detect_file_format(file_path: str) -> tuple[str, bool, str]:
        """
        Detects encoding, BOM presence, and newline style (\r\n vs \n).
        Returns (encoding, has_bom, newline_style).
        """
        with open(file_path, "rb") as f:
            raw_bytes = f.read(4096)

        has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
        encoding = "utf-8-sig" if has_bom else "utf-8"

        try:
            raw_bytes.decode(encoding)
        except UnicodeDecodeError:
            encoding = "cp1252"

        newline_style = "\r\n" if b"\r\n" in raw_bytes else "\n"
        return encoding, has_bom, newline_style

    @classmethod
    def parse_file(cls, file_path: str) -> AircraftSpatialConfig:
        """Parses an MSFS aircraft configuration file into an AircraftSpatialConfig instance."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        encoding, has_bom, newline_style = cls.detect_file_format(file_path)

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            lines = f.readlines()

        config = AircraftSpatialConfig(
            source_file=os.path.abspath(file_path),
            encoding=encoding,
            has_bom=has_bom,
            line_ending=newline_style,
        )

        current_section = ""
        section_pattern = re.compile(r"^\s*\[([^\]]+)\]")
        key_val_pattern = re.compile(r"^(\s*)([^=;\s]+)\s*=\s*(.*)$")

        for line_idx, line in enumerate(lines):
            stripped = line.strip()
            sec_match = section_pattern.match(stripped)
            if sec_match:
                current_section = sec_match.group(1).strip().upper()
                config.lines.append(CFGLineRecord(raw_line=line, section=current_section))
                continue

            kv_match = key_val_pattern.match(line)
            if not kv_match:
                config.lines.append(CFGLineRecord(raw_line=line, section=current_section))
                continue

            indentation = kv_match.group(1)
            key = kv_match.group(2).strip()
            rest = kv_match.group(3)

            # Split off inline comments (e.g. ; comment)
            inline_comment = ""
            if ";" in rest:
                parts = rest.split(";", 1)
                val_part = parts[0].strip()
                inline_comment = ";" + parts[1].rstrip("\r\n")
            else:
                val_part = rest.strip()

            record = CFGLineRecord(
                raw_line=line,
                section=current_section,
                key=key,
                indentation=indentation,
                inline_comment=inline_comment,
            )

            # Parse section-specific spatial records
            if current_section == "WEIGHT_AND_BALANCE":
                cls._parse_weight_and_balance_line(key, val_part, record, config, line_idx)
            elif current_section == "CONTACT_POINTS":
                cls._parse_contact_point_line(key, val_part, record, config, line_idx)
            elif current_section == "FUEL":
                cls._parse_fuel_line(key, val_part, record, config, line_idx)

            config.lines.append(record)

        # After reading all lines and datum position, calculate absolute and Blender coordinates
        cls._resolve_spatial_points(config)
        return config

    @classmethod
    def _parse_weight_and_balance_line(
        cls,
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        key_upper = key.upper()
        if key_upper in ("REFERENCE_DATUM_POSITION", "EMPTY_WEIGHT_CG_POSITION"):
            tokens = [t.strip() for t in val_part.split(",") if t.strip()]
            if len(tokens) >= 3:
                try:
                    coords = (float(tokens[0]), float(tokens[1]), float(tokens[2]))
                    record.coordinates = coords
                    record.is_spatial = True
                    if key_upper == "REFERENCE_DATUM_POSITION":
                        config.reference_datum_ft = coords
                    elif key_upper == "EMPTY_WEIGHT_CG_POSITION":
                        config.empty_weight_cg_ft = coords
                except ValueError as e:
                    logger.warning("Failed parsing coords for %s: %s", key, e)

    @classmethod
    def _parse_contact_point_line(
        cls,
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        if not key.lower().startswith("point."):
            return

        prefix_metadata = ""
        prop_str = val_part

        # Check for MSFS 2024 tags, e.g. "Name:Template_0#Properties:1, 4.0, ..."
        if "#Properties:" in val_part:
            parts = val_part.split("#Properties:", 1)
            prefix_metadata = parts[0] + "#Properties:"
            prop_str = parts[1]

        tokens = [t.strip() for t in prop_str.split(",") if t.strip()]
        if len(tokens) >= 4:
            try:
                point_class = int(float(tokens[0]))
                long_ft = float(tokens[1])
                lat_ft = float(tokens[2])
                vert_ft = float(tokens[3])
                suffix = tokens[4:]

                record.prefix_metadata = prefix_metadata
                record.coordinates = (long_ft, lat_ft, vert_ft)
                record.suffix_tokens = [tokens[0]] + suffix  # Keep class and extra tokens
                record.is_spatial = True

                # Extract name tag from prefix if present
                name_tag = ""
                name_match = re.search(r"Name:([^#;]+)", prefix_metadata)
                if name_match:
                    name_tag = name_match.group(1)

                point = SpatialPoint(
                    point_id=f"CONTACT_POINTS:{key}",
                    section="CONTACT_POINTS",
                    key=key,
                    point_type="CONTACT_POINT",
                    name_tag=name_tag or key,
                    point_class=point_class,
                    coords_msfs_rel_ft=(long_ft, lat_ft, vert_ft),
                    raw_properties=suffix,
                    line_index=line_idx,
                )
                config.points.append(point)
            except (ValueError, IndexError) as e:
                logger.warning("Failed parsing contact point %s: %s", key, e)

    @classmethod
    def _parse_fuel_line(
        cls,
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        # Non-tank keys in [FUEL]
        if key.lower() in (
            "fuel_type",
            "number_of_tank_selectors",
            "electric_pump",
            "engine_driven_pump",
            "manual_transfer_pump",
            "manual_pump",
            "anemometer_pump",
            "fuel_dump_rate",
            "default_fuel_tank_selector",
        ):
            return

        tokens = [t.strip() for t in val_part.split(",") if t.strip()]
        if len(tokens) >= 3:
            try:
                long_ft = float(tokens[0])
                lat_ft = float(tokens[1])
                vert_ft = float(tokens[2])
                suffix = tokens[3:]

                record.coordinates = (long_ft, lat_ft, vert_ft)
                record.suffix_tokens = suffix
                record.is_spatial = True

                point = SpatialPoint(
                    point_id=f"FUEL:{key}",
                    section="FUEL",
                    key=key,
                    point_type="FUEL_TANK",
                    name_tag=key,
                    coords_msfs_rel_ft=(long_ft, lat_ft, vert_ft),
                    raw_properties=suffix,
                    line_index=line_idx,
                )
                config.points.append(point)
            except (ValueError, IndexError) as e:
                logger.warning("Failed parsing fuel tank %s: %s", key, e)

    @classmethod
    def _resolve_spatial_points(cls, config: AircraftSpatialConfig) -> None:
        """Resolves absolute and Blender coordinates for all points using reference datum."""
        datum = config.reference_datum_ft

        # Add Reference Datum itself as a SpatialPoint
        datum_blender = msfs_to_blender(0.0, 0.0, 0.0, datum)
        config.points.insert(
            0,
            SpatialPoint(
                point_id="WEIGHT_AND_BALANCE:reference_datum_position",
                section="WEIGHT_AND_BALANCE",
                key="reference_datum_position",
                point_type="DATUM",
                name_tag="Reference_Datum",
                coords_msfs_rel_ft=(0.0, 0.0, 0.0),
                coords_msfs_abs_ft=datum,
                coords_blender_m=datum_blender,
            ),
        )

        # Add Empty Weight CG
        if config.empty_weight_cg_ft != (0.0, 0.0, 0.0):
            cg_rel = config.empty_weight_cg_ft
            cg_blender = msfs_to_blender(cg_rel[0], cg_rel[1], cg_rel[2], datum)
            config.points.insert(
                1,
                SpatialPoint(
                    point_id="WEIGHT_AND_BALANCE:empty_weight_CG_position",
                    section="WEIGHT_AND_BALANCE",
                    key="empty_weight_CG_position",
                    point_type="CG",
                    name_tag="Empty_Weight_CG",
                    coords_msfs_rel_ft=cg_rel,
                    coords_msfs_abs_ft=(cg_rel[0] + datum[0], cg_rel[1] + datum[1], cg_rel[2] + datum[2]),
                    coords_blender_m=cg_blender,
                ),
            )

        for p in config.points:
            if p.point_type in ("DATUM", "CG"):
                continue
            rel = p.coords_msfs_rel_ft
            p.coords_msfs_abs_ft = (rel[0] + datum[0], rel[1] + datum[1], rel[2] + datum[2])
            p.coords_blender_m = msfs_to_blender(rel[0], rel[1], rel[2], datum)

    @classmethod
    def serialize_and_save(
        cls,
        config: AircraftSpatialConfig,
        updated_points: dict[str, tuple[float, float, float]],
        target_path: Optional[str] = None,
    ) -> str:
        """
        Updates config file with modified coordinates (rel_long, rel_lat, rel_vert in feet).
        Creates a pre-flight timestamped backup and executes an atomic replacement.
        Returns the path to the backup file created.
        """
        dest_file = target_path or config.source_file
        if not dest_file:
            raise ValueError("Destination file path must be specified.")

        dest_file = os.path.abspath(dest_file)
        dest_dir = os.path.dirname(dest_file)

        # 1. Pre-flight Snapshot Backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{dest_file}.bak_{timestamp}"
        if os.path.isfile(dest_file):
            shutil.copy2(dest_file, backup_path)
            logger.info("Created MSFS spatial backup: %s", backup_path)

        # 2. Reconstruct lines with modified coordinates
        serialized_lines: list[str] = []
        nl = config.line_ending

        for record in config.lines:
            point_id = f"{record.section}:{record.key}" if record.section and record.key else ""

            if not record.is_spatial or point_id not in updated_points:
                serialized_lines.append(record.raw_line)
                continue

            new_coords = updated_points[point_id]
            s_long = format_coordinate_float(new_coords[0])
            s_lat = format_coordinate_float(new_coords[1])
            s_vert = format_coordinate_float(new_coords[2])

            comment_str = f" {record.inline_comment}" if record.inline_comment else ""

            if record.section == "CONTACT_POINTS":
                point_class = record.suffix_tokens[0] if record.suffix_tokens else "1"
                other_tokens = record.suffix_tokens[1:] if len(record.suffix_tokens) > 1 else []
                coord_segment = f"{point_class}, {s_long}, {s_lat}, {s_vert}"
                if other_tokens:
                    coord_segment += ", " + ", ".join(other_tokens)
                line_val = f"{record.prefix_metadata}{coord_segment}"
            elif record.section == "FUEL":
                coord_segment = f"{s_long}, {s_lat}, {s_vert}"
                if record.suffix_tokens:
                    coord_segment += ", " + ", ".join(record.suffix_tokens)
                line_val = coord_segment
            elif record.section == "WEIGHT_AND_BALANCE":
                line_val = f"{s_long}, {s_lat}, {s_vert}"
            else:
                line_val = f"{s_long}, {s_lat}, {s_vert}"

            new_line = f"{record.indentation}{record.key} = {line_val}{comment_str}{nl}"
            serialized_lines.append(new_line)

        # 3. Atomic Write via Temporary File
        temp_fd, temp_file_path = tempfile.mkstemp(dir=dest_dir, prefix="omnimesh_cfg_", text=False)
        try:
            with open(temp_fd, "w", encoding=config.encoding, newline="") as f:
                f.writelines(serialized_lines)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_file_path, dest_file)
            logger.info("Successfully synced spatial coordinates to %s", dest_file)
        except Exception:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            raise

        return backup_path
