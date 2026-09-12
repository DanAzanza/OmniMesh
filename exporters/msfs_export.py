"""
Microsoft Flight Simulator (MSFS 2020 / 2024) Exporter.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS.
Features:
- Descending minSize ModelInfo.xml generation: minSize(LOD_i) = Screen_pct(LOD_{i+1}), last tier = 0.
- Collection-based and Object-based glTF export.
- Modular SimObject component structure.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

try:
    import bpy
except ImportError:
    bpy = None


try:
    from .engine_export import AssetMeshResolver
except (ImportError, ValueError):
    try:
        from exporters.engine_export import AssetMeshResolver
    except (ImportError, ValueError):
        AssetMeshResolver = None  # type: ignore


class MSFSExporter:
    @staticmethod
    def generate_model_info_xml(
        asset_name: str,
        tiers: list[dict[str, Any]],
        guid_str: str = "",
        cull_screen_size_pct: float = 0.0,
    ) -> str:
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

        # Ensure descending sort by screen_size_pct
        sorted_tiers = sorted(tiers, key=lambda t: float(t.get("screen_size_pct", 0.0)), reverse=True)
        num_tiers = len(sorted_tiers)

        if num_tiers == 0:
            min_cull = str(round(cull_screen_size_pct, 2)) if cull_screen_size_pct > 0 else "0"
            lines.append(f'        <LOD minSize="{min_cull}" ModelFile="{escaped_asset_name}_LOD0.gltf"/>')
        elif num_tiers == 1:
            min_cull = str(round(cull_screen_size_pct, 2)) if cull_screen_size_pct > 0 else "0"
            lines.append(f'        <LOD minSize="{min_cull}" ModelFile="{escaped_asset_name}_LOD0.gltf"/>')
        else:
            last_min_size = float("inf")
            for i in range(num_tiers):
                # Descending minSize: minSize for LOD_i is the screen percentage of the NEXT tier
                if i < num_tiers - 1:
                    raw_val = round(float(sorted_tiers[i + 1].get("screen_size_pct", 0.0)), 2)
                    if raw_val >= last_min_size:
                        raw_val = max(0.0, round(last_min_size - 0.1, 2))
                    last_min_size = raw_val
                    min_size_str = str(int(raw_val)) if raw_val == int(raw_val) else str(raw_val)
                else:
                    cull_val = round(cull_screen_size_pct, 2) if cull_screen_size_pct > 0 else 0.0
                    min_size_str = str(int(cull_val)) if cull_val == int(cull_val) else str(cull_val)

                model_file = f"{escaped_asset_name}_LOD{i}.gltf"
                lines.append(f'        <LOD minSize="{min_size_str}" ModelFile="{model_file}"/>')

        lines.append("    </LODS>")
        lines.append("</ModelInfo>")
        return "\n".join(lines)

    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy module not available."

        props = getattr(context.scene, "lod_tool", None)
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        payload = AssetMeshResolver.resolve_payload(context, clean_name) if AssetMeshResolver else None

        if not payload or not payload.lod_tiers:
            return False, f"No valid LOD objects found to export for '{clean_name}'."

        if hasattr(bpy.ops.object, "mode_set") and getattr(context, "mode", "") != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception as exc:
                logger.debug("Mode set to OBJECT skipped: %s", exc)

        tier_data: list[dict[str, Any]] = []
        exported_tiers = 0

        for i, tier_objs in sorted(payload.lod_tiers.items()):
            if not tier_objs:
                continue

            s_pct = 50.0
            if props and i < len(props.lods):
                s_pct = float(props.lods[i].screen_size_pct)
            elif payload.has_impostor_tier and i == max(payload.lod_tiers.keys()):
                s_pct = float(getattr(props, "cull_screen_size_pct", 0.5)) if props else 0.5

            tier_data.append({"index": i, "screen_size_pct": s_pct, "obj_name": tier_objs[0].name})

            # Ensure objects are visible in view layer and select strictly pure meshes
            bpy.ops.object.select_all(action="DESELECT")
            for obj in tier_objs:
                try:
                    obj.hide_set(False, view_layer=context.view_layer)
                    obj.hide_viewport = False
                except (RuntimeError, AttributeError) as exc:
                    logger.debug("Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc)
                obj.select_set(True)

            context.view_layer.objects.active = tier_objs[0]

            gltf_path = os.path.join(export_dir, f"{clean_name}_LOD{i}.gltf")
            try:
                bpy.ops.export_scene.gltf(
                    filepath=gltf_path, use_selection=True, export_format="GLTF_SEPARATE", export_apply=True
                )
                exported_tiers += 1
            except Exception as e:
                return False, f"Failed to export glTF for LOD{i}: {str(e)}"

        if exported_tiers == 0:
            return False, "No valid LOD objects found to export."

        cull_pct = float(getattr(props, "cull_screen_size_pct", 0.5)) if props else 0.5
        xml_content = cls.generate_model_info_xml(clean_name, tier_data, cull_screen_size_pct=cull_pct)
        xml_path = os.path.join(export_dir, f"{clean_name}.xml")
        try:
            with open(xml_path, "w", encoding="utf-8") as f:
                f.write(xml_content)
        except OSError as e:
            return False, f"Failed to write ModelInfo XML: {str(e)}"

        return True, f"MSFS package ({exported_tiers} LOD tiers) exported to: {export_dir}"

    @classmethod
    def export_project_package(cls, context: Any, export_dir: str, base_asset_name: str) -> tuple[bool, str]:
        """Exports a complete multi-model aircraft package adhering to MSFS SDK layout."""
        if not bpy or not context:
            return False, "Blender bpy module not available."

        clean_base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(base_asset_name)).strip() or "SM_Asset"
        clean_base = clean_base.split("_Interior")[0]

        os.makedirs(export_dir, exist_ok=True)
        model_dir = (
            export_dir if export_dir.rstrip("/\\").endswith(("model", "model.")) else os.path.join(export_dir, "model")
        )
        os.makedirs(model_dir, exist_ok=True)

        exported_count = 0
        # 1. Export Exterior
        ok, msg = cls.export_asset(context, model_dir, clean_base)
        if ok:
            exported_count += 1
        else:
            logger.warning("Exterior export notice: %s", msg)

        # 2. Export Interior if present
        interior_name = f"{clean_base}_Interior"
        has_interior = False
        if hasattr(bpy.data, "collections") and (
            bpy.data.collections.get(interior_name) or bpy.data.collections.get(f"{interior_name}_LOD0")
        ):
            ok_int, msg_int = cls.export_asset(context, model_dir, interior_name)
            if ok_int:
                exported_count += 1
                has_interior = True
            else:
                logger.warning("Interior export notice: %s", msg_int)

        # 3. Write / Update model/model.cfg
        model_cfg_path = os.path.join(model_dir, "model.cfg")
        cfg_lines = ["[models]", f"normal={clean_base}.xml"]
        if has_interior:
            cfg_lines.append(f"interior={interior_name}.xml")
        cfg_lines.append("")
        try:
            with open(model_cfg_path, "w", encoding="utf-8") as f:
                f.write("\n".join(cfg_lines))
        except OSError as exc:
            logger.warning("Could not write model.cfg: %s", exc)

        # 4. Export Variants if present
        if hasattr(bpy.data, "collections"):
            for coll in bpy.data.collections:
                c_name = getattr(coll, "name", "")
                if c_name.startswith(f"{clean_base}_") and not any(
                    c_name.endswith(sfx)
                    for sfx in (
                        "_LOD0",
                        "_LOD1",
                        "_LOD2",
                        "_LOD3",
                        "_LOD4",
                        "_LOD5",
                        "_LOD6",
                        "_LOD7",
                        "_LOD8",
                        "_LOD9",
                        "_LOD10",
                        "_Spatial",
                        "_Lights",
                        "_Cameras",
                        "_Colliders",
                        "_Impostor",
                        "_Chunks",
                        "_HLOD",
                        "_Interior",
                    )
                ):
                    var_id = c_name[len(clean_base) + 1 :].lower()
                    pkg_root = os.path.dirname(model_dir.rstrip("/\\"))
                    variant_dir = os.path.join(pkg_root, f"model.{var_id}")
                    os.makedirs(variant_dir, exist_ok=True)
                    ok_var, msg_var = cls.export_asset(context, variant_dir, c_name)
                    if ok_var:
                        exported_count += 1
                        var_cfg_path = os.path.join(variant_dir, "model.cfg")
                        var_cfg_lines = ["[models]", f"normal={c_name}.xml"]
                        if has_interior:
                            var_cfg_lines.append(f"interior=../model/{interior_name}.xml")
                        var_cfg_lines.append("")
                        try:
                            with open(var_cfg_path, "w", encoding="utf-8") as vf:
                                vf.write("\n".join(var_cfg_lines))
                        except OSError as exc:
                            logger.warning("Could not write variant model.cfg: %s", exc)

        if exported_count == 0:
            return False, f"No model geometry found to export for package '{clean_base}'."

        return True, f"MSFS package ({exported_count} model(s) & configs) exported to: {export_dir}"
