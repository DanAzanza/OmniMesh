"""
MSFS 2024 Modular Attachments & Submodels CST Subsystem.
Provides lossless parsing, Blender coordinate transformation, and serialization
for MSFS 2024 attached_objects.cfg files.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import tempfile
import time
from typing import Optional

from .camera_cst import detect_file_format
from .models import (
    AttachmentsConfigFile,
    CFGLineRecord,
    SimAttachmentPoint,
)
from .transforms import (
    format_coordinate_float,
    msfs_to_blender,
)

logger = logging.getLogger(__name__)


class MSFSAttachmentsCST:
    """Lossless CST Parser & Serializer for MSFS 2024 attached_objects.cfg."""

    detect_file_format = staticmethod(detect_file_format)

    @classmethod
    def parse_attachments_file(cls, file_path: str) -> AttachmentsConfigFile:
        """Parses an attached_objects.cfg file into an AttachmentsConfigFile instance."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Attachments config file not found: {file_path}")

        encoding, has_bom, newline_style = cls.detect_file_format(file_path)

        with open(file_path, "r", encoding=encoding, errors="replace") as f:
            lines = f.readlines()

        config = AttachmentsConfigFile(
            source_file=os.path.abspath(file_path),
            encoding=encoding,
            has_bom=has_bom,
            line_ending=newline_style,
        )

        current_section = ""
        current_attachment: Optional[SimAttachmentPoint] = None
        current_merge: Optional[dict[str, str]] = None

        for idx, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            indentation = raw_line[: len(raw_line) - len(raw_line.lstrip())]

            inline_comment = ""
            line_code = stripped
            if ";" in line_code:
                parts = line_code.split(";", 1)
                line_code = parts[0].strip()
                inline_comment = ";" + parts[1]

            record = CFGLineRecord(
                raw_line=raw_line,
                section=current_section,
                inline_comment=inline_comment,
                indentation=indentation,
            )

            # Section headers [section_name]
            if line_code.startswith("[") and line_code.endswith("]"):
                current_section = line_code[1:-1].strip()
                record.section = current_section
                record.key = ""
                config.lines.append(record)

                sec_lower = current_section.lower()
                if sec_lower.startswith("sim_attachment."):
                    if current_attachment:
                        config.attachments.append(current_attachment)
                    current_attachment = SimAttachmentPoint(
                        point_id=f"ATTACHMENTS:{current_section}",
                        section=current_section,
                        key=current_section,
                        point_type="ATTACHMENT",
                        name_tag=current_section,
                        line_index=idx,
                    )
                elif sec_lower.startswith("merge_model."):
                    if current_merge:
                        config.merge_models.append(current_merge)
                    current_merge = {}
                continue

            # Key-Value pairs
            if "=" in line_code:
                key, val = line_code.split("=", 1)
                key = key.strip()
                val_clean = val.strip().strip('"')
                record.key = key
                record.raw_line = raw_line

                sec_lower = current_section.lower()
                if sec_lower == "version":
                    if key.lower() == "major":
                        try:
                            config.version_major = int(val_clean)
                        except ValueError:
                            pass
                    elif key.lower() == "minor":
                        try:
                            config.version_minor = int(val_clean)
                        except ValueError:
                            pass

                elif sec_lower.startswith("merge_model.") and current_merge is not None:
                    current_merge[key.lower()] = val_clean

                elif sec_lower.startswith("sim_attachment.") and current_attachment is not None:
                    k_lower = key.lower()
                    if k_lower in ("attachment", "attachment_file"):
                        current_attachment.attachment_path = val_clean
                    elif k_lower == "attachment_root":
                        current_attachment.attachment_root = val_clean
                    elif k_lower == "attach_to_model":
                        current_attachment.attach_to_model = val_clean
                    elif k_lower == "attach_to_node":
                        current_attachment.attach_to_node = val_clean
                        current_attachment.name_tag = val_clean
                    elif k_lower == "alias":
                        current_attachment.alias = val_clean
                    elif k_lower == "attach_scale":
                        try:
                            current_attachment.attach_scale = float(val_clean)
                        except ValueError:
                            pass
                    elif k_lower == "attach_offset":
                        tokens = [t.strip() for t in val_clean.split(",") if t.strip()]
                        if len(tokens) >= 3:
                            try:
                                coords = (float(tokens[0]), float(tokens[1]), float(tokens[2]))
                                current_attachment.attach_offset_ft = coords
                                current_attachment.coords_msfs_rel_ft = coords
                                current_attachment.coords_blender_m = msfs_to_blender(*coords)
                                record.coordinates = coords
                                record.is_spatial = True
                            except ValueError:
                                pass
                    elif k_lower == "attach_pbh":
                        tokens = [t.strip() for t in val_clean.split(",") if t.strip()]
                        if len(tokens) >= 3:
                            try:
                                rot = (float(tokens[0]), float(tokens[1]), float(tokens[2]))
                                current_attachment.attach_pbh_deg = rot
                                record.rotation = rot
                            except ValueError:
                                pass

            config.lines.append(record)

        if current_attachment:
            config.attachments.append(current_attachment)
        if current_merge:
            config.merge_models.append(current_merge)

        return config

    @classmethod
    def build_new_config(
        cls,
        attachments: list[SimAttachmentPoint],
        merge_models: Optional[list[dict[str, str]]] = None,
        version_major: int = 1,
        version_minor: int = 0,
        line_ending: str = "\r\n",
        encoding: str = "utf-8",
    ) -> AttachmentsConfigFile:
        """Synthesizes a fresh AttachmentsConfigFile instance and its CST lines from scratch."""
        config = AttachmentsConfigFile(
            encoding=encoding,
            line_ending=line_ending,
            version_major=version_major,
            version_minor=version_minor,
            merge_models=list(merge_models or []),
            attachments=list(attachments),
        )

        nl = line_ending
        lines: list[CFGLineRecord] = []

        # [VERSION]
        lines.append(CFGLineRecord(raw_line=f"[VERSION]{nl}", section="VERSION"))
        lines.append(CFGLineRecord(raw_line=f"major = {version_major}{nl}", section="VERSION", key="major"))
        lines.append(CFGLineRecord(raw_line=f"minor = {version_minor}{nl}", section="VERSION", key="minor"))
        lines.append(CFGLineRecord(raw_line=nl, section=""))

        # [merge_model.N]
        for idx, merge in enumerate(config.merge_models):
            sec = f"merge_model.{idx}"
            lines.append(CFGLineRecord(raw_line=f"[{sec}]{nl}", section=sec))
            for k, v in merge.items():
                lines.append(CFGLineRecord(raw_line=f'{k} = "{v}"{nl}', section=sec, key=k))
            lines.append(CFGLineRecord(raw_line=nl, section=""))

        # [sim_attachment.N]
        for idx, att in enumerate(config.attachments):
            sec = f"sim_attachment.{idx}"
            lines.append(CFGLineRecord(raw_line=f"[{sec}]{nl}", section=sec))
            if att.attachment_root:
                lines.append(
                    CFGLineRecord(
                        raw_line=f'attachment_root = "{att.attachment_root}"{nl}', section=sec, key="attachment_root"
                    )
                )
            if att.attachment_path:
                lines.append(
                    CFGLineRecord(raw_line=f'attachment = "{att.attachment_path}"{nl}', section=sec, key="attachment")
                )
            if att.attach_to_model:
                lines.append(
                    CFGLineRecord(
                        raw_line=f'attach_to_model = "{att.attach_to_model}"{nl}', section=sec, key="attach_to_model"
                    )
                )
            if att.attach_to_node:
                lines.append(
                    CFGLineRecord(
                        raw_line=f'attach_to_node = "{att.attach_to_node}"{nl}', section=sec, key="attach_to_node"
                    )
                )
            if att.alias:
                lines.append(CFGLineRecord(raw_line=f'alias = "{att.alias}"{nl}', section=sec, key="alias"))
            if abs(att.attach_scale - 1.0) > 1e-4:
                lines.append(
                    CFGLineRecord(
                        raw_line=f"attach_scale = {format_coordinate_float(att.attach_scale)}{nl}",
                        section=sec,
                        key="attach_scale",
                    )
                )

            s_long = format_coordinate_float(att.attach_offset_ft[0])
            s_lat = format_coordinate_float(att.attach_offset_ft[1])
            s_vert = format_coordinate_float(att.attach_offset_ft[2])
            lines.append(
                CFGLineRecord(
                    raw_line=f"attach_offset = {s_long}, {s_lat}, {s_vert}{nl}",
                    section=sec,
                    key="attach_offset",
                    coordinates=att.attach_offset_ft,
                    is_spatial=True,
                )
            )

            s_p = format_coordinate_float(att.attach_pbh_deg[0])
            s_b = format_coordinate_float(att.attach_pbh_deg[1])
            s_h = format_coordinate_float(att.attach_pbh_deg[2])
            lines.append(
                CFGLineRecord(
                    raw_line=f"attach_pbh = {s_p}, {s_b}, {s_h}{nl}",
                    section=sec,
                    key="attach_pbh",
                    rotation=att.attach_pbh_deg,
                )
            )
            lines.append(CFGLineRecord(raw_line=nl, section=""))

        config.lines = lines
        return config

    @classmethod
    def serialize_and_save(
        cls,
        config: AttachmentsConfigFile,
        updated_points: Optional[dict[str, tuple[float, float, float]]] = None,
        updated_rotations: Optional[dict[str, tuple[float, float, float]]] = None,
        target_path: Optional[str] = None,
    ) -> str:
        """Serializes updated attachment offsets back to attached_objects.cfg atomically."""
        dest_file = target_path or config.source_file
        if not dest_file:
            raise ValueError("Destination file path must be specified.")

        dest_file = os.path.abspath(dest_file)
        dest_dir = os.path.dirname(dest_file)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        if not config.lines and config.attachments:
            config = cls.build_new_config(
                attachments=config.attachments,
                merge_models=config.merge_models,
                version_major=config.version_major,
                version_minor=config.version_minor,
                line_ending=config.line_ending,
                encoding=config.encoding,
            )

        pts = updated_points or {}
        rots = updated_rotations or {}

        pts_lower = {k.lower(): v for k, v in pts.items()}
        rots_lower = {k.lower(): v for k, v in rots.items()}

        # 1. Pre-flight Backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{dest_file}.bak_{timestamp}"
        if os.path.isfile(dest_file):
            shutil.copy2(dest_file, backup_path)
            logger.info("Created attached_objects.cfg backup: %s", backup_path)

        # 2. Serialize lines
        serialized_lines: list[str] = []
        nl = config.line_ending

        for record in config.lines:
            k_lower = record.key.lower()

            point_id = f"ATTACHMENTS:{record.section}"
            alt_id = record.section

            target_point = pts_lower.get(point_id.lower()) or pts_lower.get(alt_id.lower())
            target_rot = rots_lower.get(point_id.lower()) or rots_lower.get(alt_id.lower())

            if k_lower == "attach_offset" and target_point is not None:
                s_long = format_coordinate_float(target_point[0])
                s_lat = format_coordinate_float(target_point[1])
                s_vert = format_coordinate_float(target_point[2])
                val_str = f"{s_long}, {s_lat}, {s_vert}"
                comment_str = f" {record.inline_comment}" if record.inline_comment else ""
                new_line = f"{record.indentation}{record.key} = {val_str}{comment_str}{nl}"
                serialized_lines.append(new_line)
            elif k_lower == "attach_pbh" and target_rot is not None:
                s_p = format_coordinate_float(target_rot[0])
                s_b = format_coordinate_float(target_rot[1])
                s_h = format_coordinate_float(target_rot[2])
                val_str = f"{s_p}, {s_b}, {s_h}"
                comment_str = f" {record.inline_comment}" if record.inline_comment else ""
                new_line = f"{record.indentation}{record.key} = {val_str}{comment_str}{nl}"
                serialized_lines.append(new_line)
            else:
                serialized_lines.append(record.raw_line)

        # 3. Atomic write
        temp_fd, temp_file_path = tempfile.mkstemp(dir=dest_dir, prefix="omnimesh_attach_", text=False)
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
            logger.info("Successfully serialized attached_objects.cfg to %s", dest_file)
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass

        return backup_path
