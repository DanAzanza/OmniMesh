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
    AerodynamicPoint,
    AircraftSpatialConfig,
    CFGLineRecord,
    EnginePoint,
    ExitPoint,
    LightPoint,
    PayloadStationPoint,
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
        """Parses Reference Datum, Empty Weight CG, and station_load.N entries."""
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
        elif key.lower().startswith("station_load."):
            # Quote-aware CSV split for names with commas/spaces
            tokens = [t.strip() for t in re.split(r",\s*(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", val_part) if t.strip()]
            if len(tokens) >= 4:
                try:
                    weight_lbs = float(tokens[0])
                    long_ft = float(tokens[1])
                    lat_ft = float(tokens[2])
                    vert_ft = float(tokens[3])
                    raw_name = tokens[4] if len(tokens) >= 5 else f"Station_{key[13:]}"
                    station_name = raw_name.strip('"').strip("'")
                    station_type = int(float(tokens[5])) if len(tokens) >= 6 else 0

                    record.coordinates = (long_ft, lat_ft, vert_ft)
                    record.prefix_tokens = [tokens[0]]
                    record.suffix_tokens = tokens[4:]
                    record.is_spatial = True

                    st_pt = PayloadStationPoint(
                        point_id=f"WEIGHT_AND_BALANCE:{key}",
                        section="WEIGHT_AND_BALANCE",
                        key=key,
                        point_type="PAYLOAD_STATION",
                        name_tag=station_name or key,
                        coords_msfs_rel_ft=(long_ft, lat_ft, vert_ft),
                        weight_lbs=weight_lbs,
                        station_name=station_name,
                        station_type=station_type,
                        raw_properties=tokens[4:],
                        line_index=line_idx,
                    )
                    config.station_loads.append(st_pt)
                except (ValueError, IndexError) as exc:
                    logger.warning("Failed parsing station_load %s: %s", key, exc)

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

    @staticmethod
    def parse_exits_line(
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        """Parses exit definitions (exit.N = open_rate, long, lat, vert, type)."""
        key_lower = key.lower()
        if not key_lower.startswith("exit."):
            return

        tokens = [t.strip() for t in val_part.split(",") if t.strip()]
        if len(tokens) >= 4:
            try:
                open_rate = float(tokens[0])
                long_ft = float(tokens[1])
                lat_ft = float(tokens[2])
                vert_ft = float(tokens[3])
                exit_type = int(float(tokens[4])) if len(tokens) >= 5 else 0
                suffix = tokens[5:]

                record.coordinates = (long_ft, lat_ft, vert_ft)
                record.prefix_tokens = [tokens[0]]
                record.suffix_tokens = tokens[4:]
                record.is_spatial = True

                exit_pt = ExitPoint(
                    point_id=f"EXITS:{key}",
                    section="EXITS",
                    key=key,
                    point_type="EXIT",
                    name_tag=f"Exit_{key[5:]}",
                    coords_msfs_rel_ft=(long_ft, lat_ft, vert_ft),
                    exit_type=exit_type,
                    open_rate=open_rate,
                    raw_properties=suffix,
                    line_index=line_idx,
                )
                config.exits.append(exit_pt)
            except (ValueError, IndexError) as exc:
                logger.warning("Failed parsing exit %s: %s", key, exc)

    @staticmethod
    def parse_engine_line(
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        """Parses engine positions (Engine.N = long, lat, vert)."""
        key_lower = key.lower()
        if not key_lower.startswith("engine."):
            return

        tokens = [t.strip() for t in val_part.split(",") if t.strip()]
        if len(tokens) >= 3:
            try:
                long_ft = float(tokens[0])
                lat_ft = float(tokens[1])
                vert_ft = float(tokens[2])
                eng_idx = int(float(key_lower.replace("engine.", "")))

                record.coordinates = (long_ft, lat_ft, vert_ft)
                record.is_spatial = True

                eng_pt = EnginePoint(
                    point_id=f"GENERALENGINEDATA:{key}",
                    section="GENERALENGINEDATA",
                    key=key,
                    point_type="ENGINE",
                    name_tag=f"Engine_{eng_idx}",
                    engine_index=eng_idx,
                    coords_msfs_rel_ft=(long_ft, lat_ft, vert_ft),
                    line_index=line_idx,
                )
                config.engines.append(eng_pt)
            except (ValueError, IndexError) as exc:
                logger.warning("Failed parsing engine %s: %s", key, exc)

    @staticmethod
    def parse_aerodynamics_line(
        key: str,
        val_part: str,
        record: CFGLineRecord,
        config: AircraftSpatialConfig,
        line_idx: int,
    ) -> None:
        """Parses wing apex or aerodynamic center coordinates."""
        key_upper = key.upper()
        if key_upper in ("WING_APEX_POS", "AERO_CENTER_LIFT"):
            tokens = [t.strip() for t in val_part.split(",") if t.strip()]
            if len(tokens) >= 3:
                try:
                    coords = (float(tokens[0]), float(tokens[1]), float(tokens[2]))
                    record.coordinates = coords
                    record.is_spatial = True

                    aero_pt = AerodynamicPoint(
                        point_id=f"AERODYNAMICS:{key}",
                        section="AERODYNAMICS",
                        key=key,
                        point_type="AERO",
                        name_tag=key,
                        coords_msfs_rel_ft=coords,
                        line_index=line_idx,
                    )
                    config.points.append(aero_pt)
                except ValueError as exc:
                    logger.warning("Failed parsing aerodynamics %s: %s", key, exc)
