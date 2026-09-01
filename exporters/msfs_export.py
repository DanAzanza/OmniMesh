"""
Microsoft Flight Simulator (MSFS 2020 / 2024) Exporter.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

import re

try:
    import bpy
except ImportError:
    bpy = None


class MSFSExporter:
    @staticmethod
    def generate_model_info_xml(asset_name: str, tiers: list[dict], guid_str: str = "") -> str:
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"
        clean_guid = (
            guid_str.strip().strip("{}").upper() if guid_str and guid_str.strip() else str(uuid.uuid4()).upper()
        )
        formatted_guid = f"{{{clean_guid}}}"

        # XML attribute escaping
        escaped_asset_name = (
            clean_name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

        lines = [
            '<?xml version="1.0" encoding="utf-8" ?>',
            f'<ModelInfo version="1.1" guid="{formatted_guid}">',
            "    <LODS>",
        ]

        num_tiers = len(tiers)
        if num_tiers == 0:
            lines.append(f'        <LOD minSize="0" ModelFile="{escaped_asset_name}_LOD0.gltf"/>')
        else:
            for i, tier in enumerate(tiers):
                min_size = 0 if i == num_tiers - 1 else round(float(tier.get("screen_size_pct", 0.0)), 2)
                model_file = f"{escaped_asset_name}_LOD{i}.gltf"
                lines.append(f'        <LOD minSize="{min_size}" ModelFile="{model_file}"/>')

        lines.append("    </LODS>")
        lines.append("</ModelInfo>")
        return "\n".join(lines)

    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy module not available."

        props = getattr(context.scene, "lod_tool", None)
        if not props or len(props.lods) == 0:
            return False, "No LOD tiers configured on scene."

        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        coll = bpy.data.collections.get(f"{clean_name}_LODs") or bpy.data.collections.get(
            f"{props.export_base_name}_LODs"
        )

        tier_data: list[dict[str, Any]] = []
        exported_tiers = 0

        for i, tier in enumerate(props.lods):
            # Gather all objects belonging to this LOD tier (supports multi-mesh hierarchies)
            tier_objs: list[Any] = []
            if coll:
                for obj in coll.objects:
                    if f"_LOD{i}" in obj.name:
                        tier_objs.append(obj)

            if not tier_objs and tier.generated_obj:
                tier_objs.append(tier.generated_obj)

            if not tier_objs:
                continue

            tier_data.append({"index": i, "screen_size_pct": tier.screen_size_pct, "obj_name": tier_objs[0].name})

            # Ensure objects are visible in view layer and select them
            bpy.ops.object.select_all(action="DESELECT")
            for obj in tier_objs:
                try:
                    obj.hide_set(False, view_layer=context.view_layer)
                    obj.hide_viewport = False
                except (RuntimeError, AttributeError) as exc:
                    logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)
                obj.select_set(True)

            context.view_layer.objects.active = tier_objs[0]

            gltf_path = os.path.join(export_dir, f"{asset_name}_LOD{i}.gltf")
            try:
                bpy.ops.export_scene.gltf(
                    filepath=gltf_path, use_selection=True, export_format="GLTF_SEPARATE", export_apply=True
                )
                exported_tiers += 1
            except Exception as e:
                return False, f"Failed to export glTF for LOD{i}: {str(e)}"

        if exported_tiers == 0:
            return False, "No valid LOD objects found to export."

        xml_content = cls.generate_model_info_xml(asset_name, tier_data)
        xml_path = os.path.join(export_dir, f"{asset_name}.xml")
        try:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(xml_content)
        except OSError as e:
            return False, f"Failed to write ModelInfo XML: {str(e)}"

        return True, f"MSFS package ({exported_tiers} LOD tiers) exported to: {export_dir}"
