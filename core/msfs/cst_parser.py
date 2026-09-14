"""
MSFS Concrete Syntax Tree (CST) Parser & Serializer.
Preserves line-for-line formatting, comments, encoding (BOM), and line endings
with atomic disk writes, section record insertion, and timestamped pre-flight backups.
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import shutil
import tempfile
import time
from typing import Optional

from .models import (
    AircraftSpatialConfig,
    AttachmentsConfigFile,
    CFGLineRecord,
    CameraConfigFile,
    CameraDefinition,
    SpatialPoint,
)
from .transforms import (
    FEET_TO_METERS,
    format_coordinate_float,
    msfs_to_blender,
)
from .camera_cst import MSFSCameraCST, detect_file_format
from .attachments_cst import MSFSAttachmentsCST
from .spatial_parsers import MSFSSpatialParsers


logger = logging.getLogger(__name__)


class MSFSCSTParser:
    """Lossless parser and serializer for MSFS aircraft configuration files."""

    detect_file_format = staticmethod(detect_file_format)

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
        key_val_pattern = re.compile(r"^(\s*)([^=;]+?)\s*=\s*(.*)$")

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
            elif current_section == "LIGHTS":
                cls._parse_lights_line(key, val_part, record, config, line_idx)
            elif current_section == "EXITS":
                cls._parse_exits_line(key, val_part, record, config, line_idx)
            elif current_section in ("GENERALENGINEDATA", "TURBINE_ENGINE", "PISTON_ENGINE"):
                cls._parse_engine_line(key, val_part, record, config, line_idx)
            elif current_section == "AERODYNAMICS":
                cls._parse_aerodynamics_line(key, val_part, record, config, line_idx)

            config.lines.append(record)

        # After reading all lines and datum position, calculate absolute and Blender coordinates
        cls._resolve_spatial_points(config)
        return config

    _parse_weight_and_balance_line = staticmethod(MSFSSpatialParsers.parse_weight_and_balance_line)
    _parse_contact_point_line = staticmethod(MSFSSpatialParsers.parse_contact_point_line)
    _parse_fuel_line = staticmethod(MSFSSpatialParsers.parse_fuel_line)
    _parse_lights_line = staticmethod(MSFSSpatialParsers.parse_lights_line)
    _parse_exits_line = staticmethod(MSFSSpatialParsers.parse_exits_line)
    _parse_engine_line = staticmethod(MSFSSpatialParsers.parse_engine_line)
    _parse_aerodynamics_line = staticmethod(MSFSSpatialParsers.parse_aerodynamics_line)

    @classmethod
    def _resolve_spatial_points(cls, config: AircraftSpatialConfig) -> None:
        """Resolves absolute and Blender coordinates for all points using reference datum."""
        datum = config.reference_datum_ft

        # Add Reference Datum itself as a SpatialPoint if in flight_model.cfg
        if config.reference_datum_ft != (0.0, 0.0, 0.0) or any(
            p.section == "WEIGHT_AND_BALANCE" for p in config.points
        ):
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

        # Resolve exits and engine coordinates
        for ex in config.exits:
            rel = ex.coords_msfs_rel_ft
            ex.coords_msfs_abs_ft = (rel[0] + datum[0], rel[1] + datum[1], rel[2] + datum[2])
            ex.coords_blender_m = msfs_to_blender(rel[0], rel[1], rel[2], datum)

        for eng in config.engines:
            rel = eng.coords_msfs_rel_ft
            eng.coords_msfs_abs_ft = (rel[0] + datum[0], rel[1] + datum[1], rel[2] + datum[2])
            eng.coords_blender_m = msfs_to_blender(rel[0], rel[1], rel[2], datum)

        for st in config.station_loads:
            rel = st.coords_msfs_rel_ft
            st.coords_msfs_abs_ft = (rel[0] + datum[0], rel[1] + datum[1], rel[2] + datum[2])
            st.coords_blender_m = msfs_to_blender(rel[0], rel[1], rel[2], datum)

        # Resolve light coordinates
        for lt in config.lights:
            rel = lt.coords_msfs_rel_ft
            if lt.is_node_relative:
                # Node relative: coordinates are local to EmMesh object, not airframe datum
                lt.coords_msfs_abs_ft = rel
                lt.coords_blender_m = (
                    rel[1] * FEET_TO_METERS,
                    rel[0] * FEET_TO_METERS,
                    rel[2] * FEET_TO_METERS,
                )
            else:
                lt.coords_msfs_abs_ft = (rel[0] + datum[0], rel[1] + datum[1], rel[2] + datum[2])
                lt.coords_blender_m = msfs_to_blender(rel[0], rel[1], rel[2], datum)

    @classmethod
    def insert_record_into_section(
        cls,
        config: AircraftSpatialConfig,
        section: str,
        record: CFGLineRecord,
        after_key: Optional[str] = None,
    ) -> int:
        """
        Inserts a new CFGLineRecord into the specified section.
        If after_key is specified, inserts right after that key's line.
        Otherwise, inserts right before the next section header [...] or at EOF.
        Returns the index where the record was inserted in config.lines.
        """
        target_sec = section.strip().upper()
        record.section = target_sec

        insert_idx = -1
        in_target_section = False

        for i, r in enumerate(config.lines):
            if r.section == target_sec:
                in_target_section = True
                if after_key and r.key.lower() == after_key.lower():
                    insert_idx = i + 1
                    break
            elif in_target_section and r.section != target_sec:
                # Next section started
                insert_idx = i
                break

        if insert_idx == -1:
            # Append at end of file if section was last
            insert_idx = len(config.lines)

        config.lines.insert(insert_idx, record)
        return insert_idx

    @classmethod
    def serialize_and_save(
        cls,
        config: AircraftSpatialConfig,
        updated_points: dict[str, tuple[float, float, float]],
        updated_rotations: Optional[dict[str, tuple[float, float, float]]] = None,
        target_path: Optional[str] = None,
    ) -> str:
        """
        Updates config file with modified coordinates (rel_long, rel_lat, rel_vert in feet)
        and optional rotations (pitch, bank, heading in degrees).
        Creates a pre-flight timestamped backup and executes an atomic replacement with Windows retry.
        Returns the path to the backup file created.
        """
        dest_file = target_path or config.source_file
        if not dest_file:
            raise ValueError("Destination file path must be specified.")

        dest_file = os.path.abspath(dest_file)
        dest_dir = os.path.dirname(dest_file)
        rotations = updated_rotations or {}

        # 1. Pre-flight Snapshot Backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{dest_file}.bak_{timestamp}"
        if os.path.isfile(dest_file):
            shutil.copy2(dest_file, backup_path)
            logger.info("Created MSFS spatial backup: %s", backup_path)

        # 2. Reconstruct lines with modified coordinates
        serialized_lines: list[str] = []
        nl = config.line_ending

        # Case-insensitive lookup dictionary for modified coordinates and rotations
        pts_lower = {k.lower(): v for k, v in updated_points.items()}
        rots_lower = {k.lower(): v for k, v in rotations.items()}

        for record in config.lines:
            point_id = f"{record.section}:{record.key}".lower() if record.section and record.key else ""

            if not record.is_spatial or point_id not in pts_lower:
                serialized_lines.append(record.raw_line)
                continue

            new_coords = pts_lower[point_id]
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
            elif record.section == "LIGHTS":
                if record.raw_tags:
                    # Tagged format: update LocalPosition and LocalRotation tags
                    tags = dict(record.raw_tags)
                    tags["LocalPosition"] = f"{s_long},{s_lat},{s_vert}"
                    if point_id in rots_lower:
                        r = rots_lower[point_id]
                        tags["LocalRotation"] = (
                            f"{format_coordinate_float(r[0])},"
                            f"{format_coordinate_float(r[1])},"
                            f"{format_coordinate_float(r[2])}"
                        )
                    line_val = "#".join(f"{k}:{v}" for k, v in tags.items())
                else:
                    # Classic format: light.N = type, long, lat, vert, effect
                    light_type = record.suffix_tokens[0] if record.suffix_tokens else "3"
                    other_tokens = record.suffix_tokens[1:] if len(record.suffix_tokens) > 1 else []
                    coord_segment = f"{light_type}, {s_long}, {s_lat}, {s_vert}"
                    if other_tokens:
                        coord_segment += ", " + ", ".join(other_tokens)
                    line_val = coord_segment
            elif record.section == "EXITS":
                open_rate = record.prefix_tokens[0] if record.prefix_tokens else "0.5"
                coord_segment = f"{open_rate}, {s_long}, {s_lat}, {s_vert}"
                if record.suffix_tokens:
                    coord_segment += ", " + ", ".join(record.suffix_tokens)
                line_val = coord_segment
            elif record.section == "WEIGHT_AND_BALANCE":
                if record.key.lower().startswith("station_load."):
                    weight = record.prefix_tokens[0] if record.prefix_tokens else "170"
                    coord_segment = f"{weight}, {s_long}, {s_lat}, {s_vert}"
                    if record.suffix_tokens:
                        coord_segment += ", " + ", ".join(record.suffix_tokens)
                    line_val = coord_segment
                else:
                    line_val = f"{s_long}, {s_lat}, {s_vert}"
            elif record.section in ("GENERALENGINEDATA", "AERODYNAMICS"):
                line_val = f"{s_long}, {s_lat}, {s_vert}"
            else:
                line_val = f"{s_long}, {s_lat}, {s_vert}"

            new_line = f"{record.indentation}{record.key} = {line_val}{comment_str}{nl}"
            serialized_lines.append(new_line)

        # 3. Atomic Write via Temporary File with Windows retry
        temp_fd, temp_file_path = tempfile.mkstemp(dir=dest_dir, prefix="omnimesh_cfg_", text=False)
        try:
            with open(temp_fd, "w", encoding=config.encoding, newline="") as f:
                f.writelines(serialized_lines)
                f.flush()
                os.fsync(f.fileno())

            # Retry loop for transient Windows file lock contention
            for attempt in range(4):
                try:
                    os.replace(temp_file_path, dest_file)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05 * (2**attempt))

            logger.info("Successfully synced spatial coordinates to %s", dest_file)
        except Exception:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            raise

        return backup_path

    @classmethod
    def update_scalar_param(
        cls,
        config: AircraftSpatialConfig,
        section: str,
        key: str,
        value_str: str,
        output_path: Optional[str] = None,
    ) -> str:
        """Update a single scalar parameter in the configuration file losslessly.

        Safely modifies or appends scalar values (such as static_cg_height = 4.45)
        without perturbing spatial coordinate vectors, formatting, or comments.

        Args:
            config: AircraftSpatialConfig holding parsed CST line records.
            section: Section name (e.g. "CONTACT_POINTS").
            key: Key name (e.g. "static_cg_height").
            value_str: String representation of the scalar value.
            output_path: Target file path. If None, overwrites config.source_file.

        Returns:
            Path string to the pre-flight backup file created before writing.
        """
        dest_file = str(output_path or config.source_file)
        if not dest_file:
            raise ValueError("No output path specified and config.source_file is None.")

        dest_file = os.path.abspath(dest_file)
        dest_dir = os.path.dirname(dest_file)
        os.makedirs(dest_dir, exist_ok=True)

        # 1. Pre-flight Snapshot Backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{dest_file}.bak_{timestamp}"
        if os.path.isfile(dest_file):
            shutil.copy2(dest_file, backup_path)
            logger.info("Created MSFS spatial backup: %s", backup_path)

        # 2. Look for existing record matching section and key
        target_section = section.strip().upper()
        target_key = key.strip().lower()

        found = False
        serialized_lines: list[str] = []
        nl = config.line_ending

        for record in config.lines:
            if record.section.strip().upper() == target_section and record.key.strip().lower() == target_key:
                found = True
                comment_str = f" {record.inline_comment}" if record.inline_comment else ""
                new_line = f"{record.indentation}{record.key} = {value_str}{comment_str}{nl}"
                serialized_lines.append(new_line)
            else:
                serialized_lines.append(record.raw_line)

        # 3. If not found, insert into section
        if not found:
            new_record = CFGLineRecord(
                raw_line=f"{key} = {value_str}{nl}",
                section=target_section,
                key=key,
                indentation="",
            )
            cls.insert_record_into_section(config, target_section, new_record)
            # Re-serialize completely from config.lines
            serialized_lines = []
            for record in config.lines:
                if record.section.strip().upper() == target_section and record.key.strip().lower() == target_key:
                    comment_str = f" {record.inline_comment}" if record.inline_comment else ""
                    new_line = f"{record.indentation}{record.key} = {value_str}{comment_str}{nl}"
                    serialized_lines.append(new_line)
                else:
                    serialized_lines.append(record.raw_line)

        # 4. Atomic Write via Temporary File
        temp_fd, temp_file_path = tempfile.mkstemp(dir=dest_dir, prefix="omnimesh_scalar_", text=False)
        try:
            with open(temp_fd, "w", encoding=config.encoding, newline="") as f:
                f.writelines(serialized_lines)
                f.flush()
                os.fsync(f.fileno())

            for attempt in range(4):
                try:
                    os.replace(temp_file_path, dest_file)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.05 * (2**attempt))

            logger.info("Successfully updated scalar param %s.%s = %s in %s", section, key, value_str, dest_file)
        except Exception:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            raise

        return backup_path

    @classmethod
    def parse_cameras_file(cls, file_path: str) -> CameraConfigFile:
        """Parses an MSFS cameras.cfg file into a CameraConfigFile instance."""
        return MSFSCameraCST.parse_cameras_file(file_path)

    @classmethod
    def serialize_and_save_cameras(
        cls,
        config: CameraConfigFile,
        updated_cameras: Optional[dict[str, CameraDefinition]] = None,
        updated_eyepoint_ft: Optional[tuple[float, float, float]] = None,
        target_path: Optional[str] = None,
    ) -> str:
        """Serializes cameras back to cameras.cfg with gapless contiguous indexing (0..N-1)."""
        return MSFSCameraCST.serialize_and_save_cameras(config, updated_cameras, updated_eyepoint_ft, target_path)

    @classmethod
    def parse_attachments_file(cls, file_path: str) -> AttachmentsConfigFile:
        """Parses an MSFS 2024 attached_objects.cfg file into an AttachmentsConfigFile instance."""
        return MSFSAttachmentsCST.parse_attachments_file(file_path)

    @classmethod
    def serialize_and_save_attachments(
        cls,
        config: AttachmentsConfigFile,
        updated_points: Optional[dict[str, tuple[float, float, float]]] = None,
        updated_rotations: Optional[dict[str, tuple[float, float, float]]] = None,
        target_path: Optional[str] = None,
    ) -> str:
        """Serializes updated attachment offsets back to attached_objects.cfg atomically."""
        return MSFSAttachmentsCST.serialize_and_save(config, updated_points, updated_rotations, target_path)
