"""
Microsoft Flight Simulator (MSFS 2020 / 2024) Exporter.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

try:
    import bpy
except ImportError:
    bpy = None


class MSFSExporter:
    @staticmethod
    def generate_model_info_xml(asset_name: str, tiers: list[dict], guid_str: str = "") -> str:
        if not guid_str:
            guid_str = f"{{{str(uuid.uuid4()).upper()}}}"
        elif not guid_str.startswith("{"):
            guid_str = f"{{{guid_str}}}"

        lines = [
            '<?xml version="1.0" encoding="utf-8" ?>',
            f'<ModelInfo version="1.1" guid="{guid_str}">',
            "    <LODS>",
        ]

        num_tiers = len(tiers)
        for i, tier in enumerate(tiers):
            min_size = 0 if i == num_tiers - 1 else round(tier["screen_size_pct"], 2)
            model_file = f"{asset_name}_LOD{i}.gltf"
            lines.append(f'        <LOD minSize="{min_size}" ModelFile="{model_file}"/>')

        lines.append("    </LODS>")
        lines.append("</ModelInfo>")
        return "\n".join(lines)

    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy:
            return False, "Blender bpy module not available."

        props = context.scene.lod_tool
        os.makedirs(export_dir, exist_ok=True)

        tier_data = []
        for i, tier in enumerate(props.lods):
            if not tier.generated_obj:
                continue

            obj = tier.generated_obj
            tier_data.append({"index": i, "screen_size_pct": tier.screen_size_pct, "obj_name": obj.name})

            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            context.view_layer.objects.active = obj

            gltf_path = os.path.join(export_dir, f"{asset_name}_LOD{i}.gltf")
            try:
                bpy.ops.export_scene.gltf(
                    filepath=gltf_path, use_selection=True, export_format="GLTF_SEPARATE", export_apply=True
                )
            except Exception as e:
                return False, f"Failed to export glTF for LOD{i}: {str(e)}"

        xml_content = cls.generate_model_info_xml(asset_name, tier_data)
        xml_path = os.path.join(export_dir, f"{asset_name}.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml_content)

        return True, f"MSFS package exported to: {export_dir}"
