"""
MSFS Concrete Syntax Tree (CST) Spatial Line Parsers.
Contains section-specific line parsing routines for [WEIGHT_AND_BALANCE],
[CONTACT_POINTS], [FUEL], and [LIGHTS] configuration blocks.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .models import (
    AircraftSpatialConfig,
    CFGLineRecord,
    LightPoint,
    SpatialPoint,
)

logger = logging.getLogger(__name__)


class MSFSSpatialParsers:
    """Specialized parsers for spatial entries in MSFS aircraft config files."""

    @staticmethod
    def parse_weight_and_balance_line(
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        """Parses Reference Datum Position or Empty Weight CG coordinates."""
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

    @staticmethod
    def parse_contact_point_line(
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        """Parses contact points (point.N) supporting MSFS 2020 & 2024 #Properties format."""
        if not key.lower().startswith("point."):
            return

        prefix_metadata = ""
        prop_str = val_part

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
                record.suffix_tokens = [tokens[0]] + suffix
                record.is_spatial = True

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

    @staticmethod
    def parse_fuel_line(
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        """Parses fuel tank locations."""
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

    @staticmethod
    def parse_lights_line(
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        """Parses light definitions in both MSFS 2020 classic and MSFS 2024 tagged format."""
        key_lower = key.lower()
        if not (key_lower.startswith("lightdef.") or key_lower.startswith("light.")):
            return

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
