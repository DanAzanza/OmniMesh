"""
MSFS 2024 Modular Attachments & Submodels Viewport Operators.
Provides operators for importing, representing, and synchronizing
MSFS 2024 attached_objects.cfg attachment hotspots and submodels.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

try:
    import bpy
    from bpy.props import FloatProperty, FloatVectorProperty, StringProperty
    from bpy.types import Collection, Object, Operator
except ImportError:
    bpy = None
    Collection = object
    Object = object
    Operator = object

    def _mock_prop(**kwargs: Any) -> Any:
        return None

    FloatProperty = FloatVectorProperty = StringProperty = _mock_prop

try:
    from ..core.msfs.attachments_cst import MSFSAttachmentsCST
    from ..core.msfs.models import SimAttachmentPoint
    from ..core.msfs.transforms import (
        FEET_TO_METERS,
        METERS_TO_FEET,
        blender_empty_rotation_to_msfs_pbh,
        msfs_pbh_to_blender_empty_rotation,
    )
    from .utils import get_or_create_engine_import_collection, resolve_effective_asset_name
except (ImportError, ValueError):
    from core.msfs.attachments_cst import MSFSAttachmentsCST
    from core.msfs.models import SimAttachmentPoint
    from core.msfs.transforms import (
        FEET_TO_METERS,
        METERS_TO_FEET,
        blender_empty_rotation_to_msfs_pbh,
        msfs_pbh_to_blender_empty_rotation,
    )
    from ui.utils import get_or_create_engine_import_collection, resolve_effective_asset_name

logger = logging.getLogger(__name__)


def find_attachments_collection(context: Any, asset_name: str = "", is_interior: bool = False) -> Optional[Collection]:
    """Finds existing attachments collection scoped by asset name and role."""
    if not bpy:
        return None
    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    target_asset = asset_name or resolve_effective_asset_name(context, props)
    if is_interior and not target_asset.endswith("_Interior"):
        target_asset = f"{target_asset}_Interior"

    cfg_col = bpy.data.collections.get(f"{target_asset}_Config")
    if cfg_col and hasattr(cfg_col, "children"):
        att = cfg_col.children.get(f"{target_asset}_Attachments")
        if att:
            return att

    return bpy.data.collections.get(f"{target_asset}_Attachments")


def get_or_create_attachments_collection(
    context: Any, asset_name: str = "", is_interior: bool = False
) -> Optional[Collection]:
    """Ensures dedicated attachments collection exists under {AssetName}_Config."""
    if not bpy or not context:
        return None
    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    target_asset = asset_name or resolve_effective_asset_name(context, props)
    if is_interior and not target_asset.endswith("_Interior"):
        target_asset = f"{target_asset}_Interior"

    return get_or_create_engine_import_collection(context, target_asset, "ATTACHMENTS")


def find_mounting_socket_node(
    context: Any, socket_name: str, asset_name: str = ""
) -> tuple[Optional[Object], Optional[str]]:
    """
    Searches for an attachment socket node (Empty or Armature Bone) by name.
    Returns (parent_object, bone_name_if_armature).
    """
    if not bpy or not socket_name:
        return None, None

    clean_socket = socket_name.strip()

    # 1. Direct object search (case-insensitive fallback)
    obj = bpy.data.objects.get(clean_socket)
    if not obj:
        clean_lower = clean_socket.lower()
        for o in bpy.data.objects:
            if o.name.lower() == clean_lower:
                obj = o
                break

    if obj:
        if obj.type == "ARMATURE":
            # If target node matches armature itself
            return obj, None
        return obj, None

    # 2. Bone search across all Armatures in the scene or asset
    for o in bpy.data.objects:
        if o.type == "ARMATURE" and hasattr(o, "data") and hasattr(o.data, "bones"):
            bone = o.data.bones.get(clean_socket)
            if not bone:
                clean_lower = clean_socket.lower()
                for b in o.data.bones:
                    if b.name.lower() == clean_lower:
                        bone = b
                        break
            if bone:
                return o, bone.name

    return None, None


class OMNIMESH_OT_import_msfs_attachments(Operator):
    """Parses attached_objects.cfg and creates visual empties for MSFS modular attachment hotspots."""

    bl_idname = "omnimesh.import_msfs_attachments"
    bl_label = "Import Attachments"
    bl_description = "Parse attached_objects.cfg and spawn attachment hotspot empties parented to mounting sockets"
    bl_options = {"REGISTER", "UNDO"}

    filepath: StringProperty(name="attached_objects.cfg Path", subtype="FILE_PATH", default="")

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        props = getattr(context.scene, "lod_tool", None)
        msfs_cfg = getattr(props, "msfs_configs", None) if props else None
        p = getattr(msfs_cfg, "attached_objects_cfg_path", "")
        return bool(p and os.path.isfile(p))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        msfs_cfg = getattr(props, "msfs_configs", None) if props else None
        cfg_path = self.filepath or getattr(msfs_cfg, "attached_objects_cfg_path", "")

        if not cfg_path or not os.path.isfile(cfg_path):
            self.report({"ERROR"}, "Valid attached_objects.cfg file not specified.")
            return {"CANCELLED"}

        try:
            config = MSFSAttachmentsCST.parse_attachments_file(cfg_path)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to parse attached_objects.cfg: {exc}")
            return {"CANCELLED"}

        asset_name = resolve_effective_asset_name(context, props)
        ext_col = get_or_create_attachments_collection(context, asset_name, is_interior=False)
        inte_col = get_or_create_attachments_collection(context, asset_name, is_interior=True)

        imported_count = 0
        auto_parent = getattr(msfs_cfg, "auto_parent_to_socket", True)

        for att in config.attachments:
            is_interior = att.attach_to_model.lower() == "interior"
            target_col = inte_col if (is_interior and inte_col) else ext_col
            if not target_col:
                continue

            node_name = att.attach_to_node or att.alias or f"Attachment_{imported_count}"
            empty_name = f"ATT_{node_name}"

            # Check existing empty by msfs_id or name
            existing = None
            for o in target_col.objects:
                if o.get("msfs_id") == att.point_id or o.name == empty_name:
                    existing = o
                    break

            if existing:
                empty = existing
                empty.name = empty_name
            else:
                empty = bpy.data.objects.new(empty_name, None)
                target_col.objects.link(empty)

            empty.empty_display_type = "ARROWS"
            empty.empty_display_size = 0.15

            # Local transform relative to socket node
            # attach_offset: (long, lat, vert in feet) -> local Blender (X=lat*0.3048, Y=long*0.3048, Z=vert*0.3048)
            off_ft = att.attach_offset_ft
            local_pos_m = (
                off_ft[1] * FEET_TO_METERS,
                off_ft[0] * FEET_TO_METERS,
                off_ft[2] * FEET_TO_METERS,
            )
            pbh = att.attach_pbh_deg
            local_rot_rad = msfs_pbh_to_blender_empty_rotation(pbh[0], pbh[1], pbh[2])

            parent_obj, parent_bone = (None, None)
            if auto_parent and att.attach_to_node:
                parent_obj, parent_bone = find_mounting_socket_node(context, att.attach_to_node, asset_name)

            if parent_obj and empty != parent_obj:
                empty.parent = parent_obj
                if parent_bone:
                    empty.parent_type = "BONE"
                    empty.parent_bone = parent_bone

            empty.location = local_pos_m
            empty.rotation_euler = local_rot_rad
            if abs(att.attach_scale - 1.0) > 1e-4:
                empty.scale = (att.attach_scale, att.attach_scale, att.attach_scale)

            # Metadata custom properties
            empty["msfs_id"] = att.point_id
            empty["msfs_type"] = "ATTACHMENT"
            empty["msfs_section"] = att.section
            empty["msfs_attachment_root"] = att.attachment_root
            empty["msfs_attachment_path"] = att.attachment_path
            empty["msfs_attach_to_model"] = att.attach_to_model
            empty["msfs_attach_to_node"] = att.attach_to_node
            empty["msfs_alias"] = att.alias
            empty["msfs_attach_scale"] = att.attach_scale

            imported_count += 1

        if msfs_cfg:
            msfs_cfg.attached_objects_cfg_path = cfg_path
            msfs_cfg.attachment_status = f"Imported {imported_count} attachments"

        self.report(
            {"INFO"}, f"Successfully imported {imported_count} modular attachments from {os.path.basename(cfg_path)}"
        )
        return {"FINISHED"}


class OMNIMESH_OT_export_msfs_attachments(Operator):
    """Syncs modified Blender attachment hotspot transforms back to attached_objects.cfg."""

    bl_idname = "omnimesh.export_msfs_attachments"
    bl_label = "Sync Attachments to CFG"
    bl_description = "Sync modified Blender attachment transforms back into attached_objects.cfg with automatic backup"
    bl_options = {"REGISTER"}

    filepath: StringProperty(name="Destination CFG Path", subtype="FILE_PATH", default="")

    @classmethod
    def poll(cls, context: Any) -> bool:
        if not bpy or not context:
            return False
        props = getattr(context.scene, "lod_tool", None)
        msfs_cfg = getattr(props, "msfs_configs", None) if props else None
        p = getattr(msfs_cfg, "attached_objects_cfg_path", "")
        return bool(p and os.path.isfile(p))

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        msfs_cfg = getattr(props, "msfs_configs", None) if props else None
        cfg_path = self.filepath or getattr(msfs_cfg, "attached_objects_cfg_path", "")

        if not cfg_path:
            self.report({"ERROR"}, "No target attached_objects.cfg path specified.")
            return {"CANCELLED"}

        # Gather attachment empties
        asset_name = resolve_effective_asset_name(context, props)
        ext_col = find_attachments_collection(context, asset_name, is_interior=False)
        inte_col = find_attachments_collection(context, asset_name, is_interior=True)

        candidate_objs: list[Object] = []
        if ext_col:
            candidate_objs.extend([o for o in ext_col.objects if o.get("msfs_type") == "ATTACHMENT"])
        if inte_col:
            candidate_objs.extend([o for o in inte_col.objects if o.get("msfs_type") == "ATTACHMENT"])

        if not candidate_objs:
            # Fallback: scan all objects for msfs_type == "ATTACHMENT"
            candidate_objs = [o for o in bpy.data.objects if o.get("msfs_type") == "ATTACHMENT"]

        if not candidate_objs:
            self.report({"WARNING"}, "No attachment hotspot empties found in scene to synchronize.")
            return {"CANCELLED"}

        depsgraph = context.evaluated_depsgraph_get()
        updated_points: dict[str, tuple[float, float, float]] = {}
        updated_rotations: dict[str, tuple[float, float, float]] = {}
        synthesized_attachments: list[SimAttachmentPoint] = []

        for obj in candidate_objs:
            point_id = obj.get("msfs_id") or f"ATTACHMENTS:[sim_attachment.{len(synthesized_attachments)}]"
            section = obj.get("msfs_section") or f"sim_attachment.{len(synthesized_attachments)}"

            # Calculate transform relative to parent mounting socket (CRITICAL-2)
            eval_obj = obj.evaluated_get(depsgraph)
            if obj.parent:
                eval_parent = obj.parent.evaluated_get(depsgraph)
                m_local = eval_parent.matrix_world.inverted() @ eval_obj.matrix_world
            else:
                m_local = eval_obj.matrix_world

            local_trans = m_local.to_translation()
            local_rot_euler = m_local.to_euler("XYZ")

            # Blender local meters (X=lat, Y=long, Z=vert) -> MSFS feet (long, lat, vert)
            rel_long_ft = local_trans.y * METERS_TO_FEET
            rel_lat_ft = local_trans.x * METERS_TO_FEET
            rel_vert_ft = local_trans.z * METERS_TO_FEET

            updated_points[point_id] = (rel_long_ft, rel_lat_ft, rel_vert_ft)
            updated_points[section] = (rel_long_ft, rel_lat_ft, rel_vert_ft)

            pbh_deg = blender_empty_rotation_to_msfs_pbh(local_rot_euler.x, local_rot_euler.y, local_rot_euler.z)
            updated_rotations[point_id] = pbh_deg
            updated_rotations[section] = pbh_deg

            # Also build attachment point for synthesis if file doesn't exist yet
            att_pt = SimAttachmentPoint(
                point_id=point_id,
                section=section,
                key=section,
                point_type="ATTACHMENT",
                name_tag=str(obj.get("msfs_attach_to_node") or obj.name),
                attachment_path=str(obj.get("msfs_attachment_path") or ""),
                attachment_root=str(obj.get("msfs_attachment_root") or ""),
                attach_to_model=str(obj.get("msfs_attach_to_model") or "Interior"),
                attach_to_node=str(obj.get("msfs_attach_to_node") or ""),
                alias=str(obj.get("msfs_alias") or ""),
                attach_scale=float(obj.get("msfs_attach_scale") or 1.0),
                attach_offset_ft=(rel_long_ft, rel_lat_ft, rel_vert_ft),
                attach_pbh_deg=pbh_deg,
            )
            synthesized_attachments.append(att_pt)

        # Parse or build config
        if os.path.isfile(cfg_path):
            try:
                config = MSFSAttachmentsCST.parse_attachments_file(cfg_path)
            except Exception as exc:
                self.report({"ERROR"}, f"Could not parse existing CFG: {exc}")
                return {"CANCELLED"}
        else:
            config = MSFSAttachmentsCST.build_new_config(attachments=synthesized_attachments)

        try:
            backup_file = MSFSAttachmentsCST.serialize_and_save(
                config=config,
                updated_points=updated_points,
                updated_rotations=updated_rotations,
                target_path=cfg_path,
            )
            msg = f"Synchronized {len(candidate_objs)} attachments to {os.path.basename(cfg_path)}"
            if backup_file:
                msg += f" (Backup: {os.path.basename(backup_file)})"
            if msfs_cfg:
                msfs_cfg.attachment_status = msg
            self.report({"INFO"}, msg)
            return {"FINISHED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Failed writing attached_objects.cfg: {exc}")
            return {"CANCELLED"}


class OMNIMESH_OT_add_msfs_attachment(Operator):
    """Spawns a new modular attachment hotspot Empty at 3D cursor or active socket node."""

    bl_idname = "omnimesh.add_msfs_attachment"
    bl_label = "Add Attachment Hotspot"
    bl_description = "Spawn a new attachment Empty with standard MSFS 2024 modular attachment properties"
    bl_options = {"REGISTER", "UNDO"}

    alias: StringProperty(name="Alias", default="Instrument")
    attachment_path: StringProperty(name="Submodel XML", default="")
    attach_to_model: StringProperty(name="Target Model", default="Interior")

    def execute(self, context: Any) -> set[str]:
        if not bpy or not context:
            return {"CANCELLED"}

        props = getattr(context.scene, "lod_tool", None)
        asset_name = resolve_effective_asset_name(context, props)
        is_interior = self.attach_to_model.lower() == "interior"
        target_col = get_or_create_attachments_collection(context, asset_name, is_interior=is_interior)
        if not target_col:
            self.report({"ERROR"}, "Could not resolve target attachments collection.")
            return {"CANCELLED"}

        active_obj = getattr(context, "active_object", None)
        socket_name = ""
        parent_bone = ""
        parent_obj = None

        if active_obj:
            o_name = active_obj.name
            if o_name.upper().startswith("ATTACH_") or "ATTACH_POINT" in o_name.upper():
                socket_name = o_name
                parent_obj = active_obj
            elif active_obj.type == "ARMATURE" and getattr(context, "active_pose_bone", None):
                socket_name = context.active_pose_bone.name
                parent_bone = socket_name
                parent_obj = active_obj

        empty_name = f"ATT_{self.alias}"
        empty = bpy.data.objects.new(empty_name, None)
        target_col.objects.link(empty)

        empty.empty_display_type = "ARROWS"
        empty.empty_display_size = 0.15

        if parent_obj:
            empty.parent = parent_obj
            if parent_bone:
                empty.parent_type = "BONE"
                empty.parent_bone = parent_bone
            empty.location = (0.0, 0.0, 0.0)
            empty.rotation_euler = (0.0, 0.0, 0.0)
        else:
            empty.location = context.scene.cursor.location

        empty["msfs_id"] = f"ATTACHMENTS:[sim_attachment.{self.alias}]"
        empty["msfs_type"] = "ATTACHMENT"
        empty["msfs_section"] = f"sim_attachment.{self.alias}"
        empty["msfs_attachment_root"] = ""
        empty["msfs_attachment_path"] = self.attachment_path
        empty["msfs_attach_to_model"] = self.attach_to_model
        empty["msfs_attach_to_node"] = socket_name
        empty["msfs_alias"] = self.alias
        empty["msfs_attach_scale"] = 1.0

        # Select new empty
        bpy.ops.object.select_all(action="DESELECT")
        empty.select_set(True)
        context.view_layer.objects.active = empty

        self.report({"INFO"}, f"Created attachment hotspot {empty.name}")
        return {"FINISHED"}


classes = (
    OMNIMESH_OT_import_msfs_attachments,
    OMNIMESH_OT_export_msfs_attachments,
    OMNIMESH_OT_add_msfs_attachment,
)


def register():
    if not bpy:
        return
    for cls in classes:
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Previous class unregister skipped for %s: %s", cls, exc)
        try:
            bpy.utils.register_class(cls)
        except Exception as exc:
            logger.debug("Register skipped %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister():
    if not bpy:
        return
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as exc:
            logger.debug("Unregister skipped for %s: %s", cls, exc)


__all__ = [
    "OMNIMESH_OT_import_msfs_attachments",
    "OMNIMESH_OT_export_msfs_attachments",
    "OMNIMESH_OT_add_msfs_attachment",
    "find_attachments_collection",
    "get_or_create_attachments_collection",
    "register",
    "unregister",
]
