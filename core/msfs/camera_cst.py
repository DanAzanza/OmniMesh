"""
MSFS Camera Configuration Concrete Syntax Tree (CST) Parser and Serializer.
Handles parsing and gapless re-indexing of [CAMERADEFINITION.N] and [VIEWS]
in cameras.cfg with comment, GUID, and attribute preservation.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import tempfile
import time
from typing import Optional

from .models import CameraConfigFile, CameraDefinition
from .transforms import format_coordinate_float

logger = logging.getLogger(__name__)


def detect_file_format(file_path: str) -> tuple[str, bool, str]:
    """Detects encoding, BOM presence, and newline style (\\r\\n vs \\n).

    Returns (encoding, has_bom, newline_style).
    """
    with open(file_path, "rb") as f:
        raw_bytes = f.read(65536)

    has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
    encoding = "utf-8-sig" if has_bom else "utf-8"

    try:
        raw_bytes.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp1252"

    newline_style = "\r\n" if b"\r\n" in raw_bytes else "\n"
    return encoding, has_bom, newline_style


class MSFSCameraCST:
    """Concrete Syntax Tree parser and serializer for MSFS cameras.cfg files."""

    @classmethod
    def parse_cameras_file(cls, file_path: str) -> CameraConfigFile:
        """Parses an MSFS cameras.cfg file into a CameraConfigFile instance.

        Extracts [VIEWS] eyepoint and all [CAMERADEFINITION.N] sections with full
        property preservation (order, comments, and values).
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"cameras.cfg file not found: {file_path}")

        encoding, has_bom, newline_style = detect_file_format(file_path)
        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            lines = f.readlines()

        config = CameraConfigFile(
            source_file=file_path,
            encoding=encoding,
            has_bom=has_bom,
            line_ending=newline_style,
        )

        current_cam: Optional[CameraDefinition] = None
        current_section = ""
        in_cameras = False

        for raw_line in lines:
            line_str = raw_line.strip()

            # Section header
            if line_str.startswith("[") and "]" in line_str:
                header_content = line_str[1 : line_str.index("]")].strip()
                sec_upper = header_content.upper()

                if sec_upper.startswith("CAMERADEFINITION"):
                    in_cameras = True
                    # Finish previous camera if open
                    if current_cam is not None:
                        config.cameras.append(current_cam)

                    # Extract camera index
                    idx = 0
                    if "." in header_content:
                        try:
                            idx = int(header_content.split(".", 1)[1])
                        except ValueError:
                            idx = len(config.cameras)
                    else:
                        idx = len(config.cameras)

                    current_cam = CameraDefinition(
                        index=idx,
                        header_raw=line_str,
                    )
                    current_section = sec_upper
                    continue
                else:
                    current_section = sec_upper
                    if current_cam is not None:
                        config.cameras.append(current_cam)
                        current_cam = None

            if not in_cameras:
                config.preamble_lines.append(raw_line)
                # Parse [VIEWS] eyepoint if encountered
                if current_section == "VIEWS" and "=" in line_str:
                    k, v_part = line_str.split("=", 1)
                    if k.strip().lower() == "eyepoint":
                        comment = ""
                        if ";" in v_part:
                            v_part, comment = v_part.split(";", 1)
                        tokens = [t.strip() for t in v_part.split(",") if t.strip()]
                        if len(tokens) >= 3:
                            try:
                                config.eyepoint_ft = (
                                    float(tokens[0]),
                                    float(tokens[1]),
                                    float(tokens[2]),
                                )
                                config.eyepoint_comment = comment.strip()
                            except ValueError:
                                pass
                continue

            # Parsing properties inside a [CAMERADEFINITION.N] section
            if current_cam is not None and "=" in line_str:
                k_part, v_part = line_str.split("=", 1)
                key = k_part.strip()
                comment = ""
                if ";" in v_part:
                    v_part, comment = v_part.split(";", 1)
                val = v_part.strip()

                current_cam.properties[key] = val
                current_cam.property_order.append(key)
                if comment:
                    current_cam.property_comments[key] = comment.strip()

                k_lower = key.lower()
                if k_lower == "title":
                    current_cam.title = val.strip("\"'")
                elif k_lower == "guid":
                    current_cam.guid = val.strip("\"'")
                elif k_lower == "origin":
                    current_cam.origin = val.strip("\"'")
                elif k_lower == "category":
                    current_cam.category = val.strip("\"'")
                elif k_lower == "subcategory":
                    current_cam.subcategory = val.strip("\"'")
                elif k_lower == "subcategoryitem":
                    current_cam.subcategory_item = val.strip("\"'")
                elif k_lower == "initialzoom":
                    try:
                        current_cam.initial_zoom = float(val)
                    except ValueError:
                        pass
                elif k_lower == "initialxyz":
                    tokens = [t.strip() for t in val.split(",") if t.strip()]
                    if len(tokens) >= 3:
                        try:
                            current_cam.initial_xyz_m = (
                                float(tokens[0]),
                                float(tokens[1]),
                                float(tokens[2]),
                            )
                        except ValueError:
                            pass
                elif k_lower == "initialpbh":
                    tokens = [t.strip() for t in val.split(",") if t.strip()]
                    if len(tokens) >= 3:
                        try:
                            current_cam.initial_pbh_deg = (
                                float(tokens[0]),
                                float(tokens[1]),
                                float(tokens[2]),
                            )
                        except ValueError:
                            pass

        if current_cam is not None:
            config.cameras.append(current_cam)

        return config

    @classmethod
    def serialize_and_save_cameras(
        cls,
        config: CameraConfigFile,
        updated_cameras: Optional[dict[str, CameraDefinition]] = None,
        updated_eyepoint_ft: Optional[tuple[float, float, float]] = None,
        target_path: Optional[str] = None,
    ) -> str:
        """Serializes cameras back to cameras.cfg with gapless contiguous indexing (0..N-1).

        Preserves all existing comments, key ordering, and unknown attributes.
        Creates pre-flight timestamped backup and performs atomic replacement.
        """
        dest_file = target_path or config.source_file
        if not dest_file:
            raise ValueError("Target file path must be specified.")

        dest_file = os.path.abspath(dest_file)
        dest_dir = os.path.dirname(dest_file)
        os.makedirs(dest_dir, exist_ok=True)

        # 1. Pre-flight Backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{dest_file}.bak_{timestamp}"
        if os.path.isfile(dest_file):
            shutil.copy2(dest_file, backup_path)
            logger.info("Created cameras backup: %s", backup_path)

        nl = config.line_ending
        serialized_lines: list[str] = []

        # 2. Reconstruct Preamble (and update eyepoint if given)
        in_views = False

        for raw_line in config.preamble_lines:
            line_str = raw_line.strip()
            if line_str.startswith("[") and "]" in line_str:
                sec = line_str[1 : line_str.index("]")].strip().upper()
                in_views = sec == "VIEWS"
                serialized_lines.append(raw_line)
                continue

            if in_views and "=" in line_str and updated_eyepoint_ft:
                k, _ = line_str.split("=", 1)
                if k.strip().lower() == "eyepoint":
                    cmt = f" ; {config.eyepoint_comment}" if config.eyepoint_comment else ""
                    s_long = format_coordinate_float(updated_eyepoint_ft[0])
                    s_lat = format_coordinate_float(updated_eyepoint_ft[1])
                    s_vert = format_coordinate_float(updated_eyepoint_ft[2])
                    serialized_lines.append(f"eyepoint = {s_long}, {s_lat}, {s_vert}{cmt}{nl}")
                    continue

            serialized_lines.append(raw_line)

        # 3. Assemble camera list (ordered, contiguous 0..N-1)
        cams = list(config.cameras)
        if updated_cameras:
            # Map existing by title or guid
            for i, cam in enumerate(cams):
                ident = cam.guid or cam.title or f"Camera_{cam.index}"
                if ident in updated_cameras:
                    cams[i] = updated_cameras[ident]

        # 4. Serialize Cameras with contiguous gapless indices
        for seq_idx, cam in enumerate(cams):
            cam.index = seq_idx
            serialized_lines.append(f"[CAMERADEFINITION.{seq_idx}]{nl}")

            # Prepare properties
            props = dict(cam.properties)

            # Ensure core attributes are updated in props dictionary
            if cam.title:
                props["Title"] = f'"{cam.title}"' if not cam.title.startswith('"') else cam.title
            if cam.guid:
                props["Guid"] = f'"{cam.guid}"' if not cam.guid.startswith('"') else cam.guid
            if cam.origin:
                props["Origin"] = f'"{cam.origin}"' if not cam.origin.startswith('"') else cam.origin
            if cam.category:
                props["Category"] = f'"{cam.category}"' if not cam.category.startswith('"') else cam.category
            if cam.subcategory:
                props["SubCategory"] = (
                    f'"{cam.subcategory}"' if not cam.subcategory.startswith('"') else cam.subcategory
                )

            props["InitialZoom"] = f"{cam.initial_zoom:.2f}"
            props["InitialXyz"] = (
                f"{format_coordinate_float(cam.initial_xyz_m[0])}, "
                f"{format_coordinate_float(cam.initial_xyz_m[1])}, "
                f"{format_coordinate_float(cam.initial_xyz_m[2])}"
            )
            props["InitialPbh"] = (
                f"{format_coordinate_float(cam.initial_pbh_deg[0])}, "
                f"{format_coordinate_float(cam.initial_pbh_deg[1])}, "
                f"{format_coordinate_float(cam.initial_pbh_deg[2])}"
            )

            # Determine key ordering
            ordered_keys = [k for k in cam.property_order if k in props]
            for k in props:
                if k not in ordered_keys:
                    ordered_keys.append(k)

            for k in ordered_keys:
                val = props[k]
                cmt = f" ; {cam.property_comments[k]}" if k in cam.property_comments else ""
                serialized_lines.append(f"{k} = {val}{cmt}{nl}")

            serialized_lines.append(nl)

        # 5. Atomic Write via Temporary File with Windows retry
        temp_fd, temp_file_path = tempfile.mkstemp(dir=dest_dir, prefix="omnimesh_cam_", text=False)
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

            logger.info("Successfully serialized %d cameras to %s", len(cams), dest_file)
        except Exception:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass
            raise

        return backup_path
