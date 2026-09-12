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
    CFGLineRecord,
    CameraConfigFile,
    CameraDefinition,
    LightPoint,
    SpatialPoint,
)
from .transforms import (
    FEET_TO_METERS,
    format_coordinate_float,
    msfs_to_blender,
)
from .camera_cst import MSFSCameraCST, detect_file_format

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
            elif current_section == "LIGHTS":
                cls._parse_lights_line(key, val_part, record, config, line_idx)

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
    def _parse_lights_line(
        cls,
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        key_lower = key.lower()
        if not (key_lower.startswith("lightdef.") or key_lower.startswith("light.")):
            return

        # Tagged format: Type:3#Index:0#LocalPosition:-2,16.4,0.2#LocalRotation:0,0,0...
        if "#" in val_part:
            tags: dict[str, str] = {}
            for token in val_part.split("#"):
                token = token.strip()
                if not token:
                    continue
                if ":" in token:
                    tag_name, tag_val = token.split(":", 1)
                    tags[tag_name.strip()] = tag_val.strip()

            record.raw_tags = tags
            pos_str = tags.get("LocalPosition", "")
            rot_str = tags.get("LocalRotation", "")
            type_str = tags.get("Type", "0")
            idx_str = tags.get("Index", "0")
            effect_file = tags.get("EffectFile", "")
            em_mesh = tags.get("EmMesh", "")

            coords: Optional[tuple[float, float, float]] = None
            if pos_str:
                pos_tokens = [t.strip() for t in pos_str.split(",") if t.strip()]
                if len(pos_tokens) >= 3:
                    try:
                        coords = (float(pos_tokens[0]), float(pos_tokens[1]), float(pos_tokens[2]))
                        record.coordinates = coords
                    except ValueError:
                        pass

            rotation: Optional[tuple[float, float, float]] = None
            if rot_str:
                rot_tokens = [t.strip() for t in rot_str.split(",") if t.strip()]
                if len(rot_tokens) >= 3:
                    try:
                        rotation = (float(rot_tokens[0]), float(rot_tokens[1]), float(rot_tokens[2]))
                        record.rotation = rotation
                    except ValueError:
                        pass

            if coords is not None:
                record.is_spatial = True
                try:
                    light_type = int(float(type_str))
                except ValueError:
                    light_type = 0
                try:
                    light_idx = int(float(idx_str))
                except ValueError:
                    light_idx = 0

                light = LightPoint(
                    point_id=f"LIGHTS:{key}",
                    section="LIGHTS",
                    key=key,
                    point_type="LIGHT",
                    name_tag=em_mesh or f"Light_{light_type}_{light_idx}",
                    light_type=light_type,
                    light_index=light_idx,
                    rotation_pbh_deg=rotation or (0.0, 0.0, 0.0),
                    effect_file=effect_file,
                    em_mesh=em_mesh,
                    is_node_relative=bool(em_mesh),
                    coords_msfs_rel_ft=coords,
                    raw_tags=tags,
                    line_index=line_idx,
                )
                config.lights.append(light)
        else:
            # Classic MSFS 2020 format: light.N = type, long, lat, vert, effect_name
            tokens = [t.strip() for t in val_part.split(",") if t.strip()]
            if len(tokens) >= 4:
                try:
                    light_type = int(float(tokens[0]))
                    long_ft = float(tokens[1])
                    lat_ft = float(tokens[2])
                    vert_ft = float(tokens[3])
                    suffix = tokens[4:]

                    record.coordinates = (long_ft, lat_ft, vert_ft)
                    record.suffix_tokens = [tokens[0]] + suffix
                    record.is_spatial = True

                    light = LightPoint(
                        point_id=f"LIGHTS:{key}",
                        section="LIGHTS",
                        key=key,
                        point_type="LIGHT",
                        name_tag=f"Light_{light_type}",
                        light_type=light_type,
                        coords_msfs_rel_ft=(long_ft, lat_ft, vert_ft),
                        raw_properties=suffix,
                        line_index=line_idx,
                    )
                    config.lights.append(light)
                except (ValueError, IndexError):
                    pass

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
            elif record.section == "LIGHTS":
                if record.raw_tags:
                    # Tagged format: update LocalPosition and LocalRotation tags
                    tags = dict(record.raw_tags)
                    tags["LocalPosition"] = f"{s_long},{s_lat},{s_vert}"
                    if point_id in rotations:
                        r = rotations[point_id]
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
            elif record.section == "WEIGHT_AND_BALANCE":
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
