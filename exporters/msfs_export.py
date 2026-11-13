"""
Microsoft Flight Simulator (MSFS 2020 / 2024) Exporter.
Architected for Blender 5.0+ & Blender 5.2 LTS.
Features:
- Descending minSize ModelInfo.xml generation: minSize(LOD_i) = Screen_pct(LOD_{i+1}), last tier = 0.
- Collection-based and Object-based glTF export.
- Modular SimObject component structure.
"""

from __future__ import annotations

try:
    from ..core.exceptions import OmniMeshError
except (ImportError, ValueError):
    from core.exceptions import OmniMeshError

import logging
import os
import re
import uuid
from typing import TYPE_CHECKING, Any, Protocol, Sequence, cast

logger = logging.getLogger(__name__)


class MSFSExportTierProtocol(Protocol):
    """Structural protocol for an individual LOD tier during MSFS export."""

    screen_size_pct: float


class MSFSExportSettingsProtocol(Protocol):
    """Structural protocol for OmniMesh scene settings during MSFS export."""

    lods: Sequence[MSFSExportTierProtocol]
    cull_screen_size_pct: float
    msfs_target_version: str
    asset_category: str
    msfs_with_exterior_show_interior: bool
    msfs_with_exterior_show_interior_hide_first_lod: bool
    msfs_with_interior_force_first_lod: bool
    msfs_with_interior_show_exterior: bool


if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
    from .base import EngineExporterBase, scoped_export_visibility
    from .engine_export import AssetMeshResolver
else:
    try:
        import bpy
    except ImportError:
        bpy = None
    BlendData = object

    from .base import EngineExporterBase, scoped_export_visibility
    from .engine_export import AssetMeshResolver

try:
    from ..core.msfs.project_scanner import MSFSModelOptions
    from ..core.msfs.xml_merger import ModelXMLMerger
except (ImportError, ValueError):
    try:
        from core.msfs.project_scanner import MSFSModelOptions
        from core.msfs.xml_merger import ModelXMLMerger
    except (ImportError, ValueError):
        ModelXMLMerger = None  # type: ignore
        MSFSModelOptions = None  # type: ignore


def _get_msfs_props(scene: bpy.types.Scene | None) -> MSFSExportSettingsProtocol | None:
    """Extracts OmniMesh scene properties typed for MSFS export."""
    return cast("MSFSExportSettingsProtocol | None", getattr(scene, "lod_tool", None)) if scene else None


class MSFSExporter(EngineExporterBase):
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
                        step = 0.1 if last_min_size > 0.1 else 0.01
                        min_floor = round((num_tiers - 1 - i) * 0.01, 2)
                        raw_val = max(min_floor, round(last_min_size - step, 2))
                    last_min_size = raw_val
                    min_size_str = str(int(raw_val)) if raw_val == int(raw_val) else str(raw_val)
                else:
                    cull_val = round(cull_screen_size_pct, 2) if cull_screen_size_pct > 0 else 0.0
                    if cull_val >= last_min_size:
                        step = 0.1 if last_min_size > 0.1 else 0.01
                        cull_val = max(0.0, round(last_min_size - step, 2))
                    last_min_size = cull_val
                    min_size_str = str(int(cull_val)) if cull_val == int(cull_val) else str(cull_val)

                model_file = f"{escaped_asset_name}_LOD{i}.gltf"
                lines.append(f'        <LOD minSize="{min_size_str}" ModelFile="{model_file}"/>')

        lines.append("    </LODS>")
        lines.append("</ModelInfo>")
        return "\n".join(lines)

    @classmethod
    def export_asset(
        cls,
        context: bpy.types.Context | None,
        export_dir: str,
        asset_name: str,
        **kwargs: object,
    ) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        props = _get_msfs_props(context.scene)
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        bdata_in = kwargs.get("blend_data")
        bdata: BlendData | None = (
            bdata_in if (bdata_in is not None and isinstance(bdata_in, BlendData)) else context.blend_data
        )
        payload = (
            AssetMeshResolver.resolve_payload(context, clean_name, blend_data=bdata) if AssetMeshResolver else None
        )

        if not payload or not payload.lod_tiers:
            return False, f"No valid LOD objects found to export for '{clean_name}'."

        prep_warnings: list[str] = []
        cleanup_warnings: list[str] = []

        if context.mode != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except (RuntimeError, AttributeError, TypeError) as exc:
                prep_warnings.append(f"mode_set: {exc}")
                logger.debug("Mode set to OBJECT skipped: %s", exc)

        vl = context.view_layer
        orig_active = vl.objects.active if (vl and vl.objects is not None) else None
        orig_selected = list(context.selected_objects or ())
        visibility_targets: list[bpy.types.Object] = []
        for tier_objs in payload.lod_tiers.values():
            visibility_targets.extend(o for o in tier_objs if o)
        if payload.attachment_nodes:
            visibility_targets.extend(n for n in payload.attachment_nodes if n)

        tier_data: list[dict[str, Any]] = []
        exported_tiers = 0

        try:
            with scoped_export_visibility(context, visibility_targets, warnings=prep_warnings):
                for i, tier_objs in sorted(payload.lod_tiers.items()):
                    if not tier_objs:
                        continue
                    s_pct = 50.0
                    if props and i < len(props.lods):
                        s_pct = float(props.lods[i].screen_size_pct)
                    elif payload.has_impostor_tier and i == max(payload.lod_tiers.keys()):
                        s_pct = float(props.cull_screen_size_pct) if props else 0.5

                    tier_data.append({"index": i, "screen_size_pct": s_pct, "obj_name": tier_objs[0].name})
                    err = cls._export_single_lod_tier_gltf(
                        context=context,
                        tier_idx=i,
                        tier_objs=tier_objs,
                        attachment_nodes=payload.attachment_nodes if i == 0 else (),
                        export_dir=export_dir,
                        clean_name=clean_name,
                        is_skeletal=payload.is_skeletal,
                    )
                    if err:
                        return False, err
                    exported_tiers += 1

            if exported_tiers == 0:
                return False, "No valid LOD objects found to export."

            cull_pct = float(props.cull_screen_size_pct) if props else 0.5
            xml_path = os.path.join(export_dir, f"{clean_name}.xml")

            # Format tier payload for ModelXMLMerger
            merger_tiers: list[dict[str, Any]] = []
            for item in tier_data:
                merger_tiers.append(
                    {
                        "min_size": item.get("screen_size_pct", 0.0),
                        "model_file": f"{clean_name}_LOD{item.get('index', 0)}.gltf",
                    }
                )

            # Surgical merge if file exists or write new
            if ModelXMLMerger:
                merged_ok = ModelXMLMerger.merge_lods_file(xml_path, merger_tiers)
                if not merged_ok:
                    return False, f"Failed to write/merge ModelInfo XML at '{xml_path}'"
            else:
                xml_content = cls.generate_model_info_xml(clean_name, tier_data, cull_screen_size_pct=cull_pct)
                try:
                    with open(xml_path, "w", encoding="utf-8") as f:
                        f.write(xml_content)
                except OSError as e:
                    return False, f"Failed to write ModelInfo XML: {str(e)}"

            return True, f"MSFS package ({exported_tiers} LOD tiers) exported to: {export_dir}"
        finally:
            # Restore original selection and active object
            if bpy:
                try:
                    bpy.ops.object.select_all(action="DESELECT")
                    for o in orig_selected:
                        o.select_set(True)
                    if vl and vl.objects is not None and orig_active:
                        vl.objects.active = orig_active
                except (RuntimeError, AttributeError, ReferenceError) as exc:
                    cleanup_warnings.append(f"selection: {exc}")
                    logger.debug("Could not restore selection state: %s", exc)

            if prep_warnings:
                cleanup_warnings.extend(prep_warnings)
            if cleanup_warnings:
                logger.warning(
                    "MSFS export cleanup finished with %d warning(s): %s",
                    len(cleanup_warnings),
                    "; ".join(cleanup_warnings),
                )

    @classmethod
    def _export_single_lod_tier_gltf(
        cls,
        *,
        context: bpy.types.Context,
        tier_idx: int,
        tier_objs: Sequence[bpy.types.Object],
        attachment_nodes: Sequence[bpy.types.Object],
        export_dir: str,
        clean_name: str,
        is_skeletal: bool,
    ) -> str | None:
        """Selects visible tier objects (plus LOD0 attachment nodes) and writes one glTF file."""
        if not bpy:
            return "Blender bpy module not available."
        bpy.ops.object.select_all(action="DESELECT")
        for obj in tier_objs:
            obj.select_set(True)
        for att_node in attachment_nodes:
            att_node.select_set(True)

        vl = context.view_layer
        if vl and vl.objects is not None:
            vl.objects.active = tier_objs[0]

        gltf_path = os.path.join(export_dir, f"{clean_name}_LOD{tier_idx}.gltf")
        try:
            bpy.ops.export_scene.gltf(
                filepath=gltf_path,
                use_selection=True,
                export_format="GLTF_SEPARATE",
                export_apply=not is_skeletal,
                export_tangents=True,
                export_animations=True,
            )
        except (
            OmniMeshError,
            RuntimeError,
            ValueError,
            TypeError,
            AttributeError,
            LookupError,
            OSError,
            ReferenceError,
            ZeroDivisionError,
        ) as e:
            return f"Failed to export glTF for LOD{tier_idx}: {str(e)}"
        return None

    @classmethod
    def export_project_package(
        cls,
        context: bpy.types.Context | None,
        export_dir: str,
        base_asset_name: str,
        **kwargs: object,
    ) -> tuple[bool, str]:
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
        ok, msg = cls.export_asset(context, model_dir, clean_base, **kwargs)
        if not ok:
            return False, f"Exterior export failed: {msg}"
        exported_count += 1

        # 2. Export Interior if present
        bdata_in = kwargs.get("blend_data")
        bdata = bdata_in if bdata_in is not None else (context.blend_data if context else None)
        bdata_cols = cast("BlendData", bdata).collections if bdata else None

        interior_name = f"{clean_base}_Interior"
        has_interior = False
        if bdata_cols and (bdata_cols.get(interior_name) or bdata_cols.get(f"{interior_name}_LOD0")):
            ok_int, msg_int = cls.export_asset(context, model_dir, interior_name, **kwargs)
            if ok_int:
                exported_count += 1
                has_interior = True
            else:
                logger.warning("Interior export notice: %s", msg_int)

        # 3. Write / Update model/model.cfg
        model_cfg_path = os.path.join(model_dir, "model.cfg")
        props = _get_msfs_props(context.scene if context else None)
        target_version = props.msfs_target_version if props else "2024"

        is_scenery = False
        if props and props.asset_category in (
            "BUILDING",
            "PROP",
            "FOLIAGE",
            "MICRO_DEBRIS",
        ):
            is_scenery = True
        if clean_base.lower().startswith("scenery_") or clean_base.lower().startswith("prop_"):
            is_scenery = True

        cfg_lines: list[str] = []
        # Serialize [model.options] strictly when targeting MSFS 2024 for aircraft (suppressed for scenery)
        if target_version == "2024" and not is_scenery:
            cfg_lines.append("[model.options]")
            with_ext_show_int = "true" if (props.msfs_with_exterior_show_interior if props else True) else "false"
            with_ext_hide_first = (
                "true" if (props.msfs_with_exterior_show_interior_hide_first_lod if props else False) else "false"
            )
            with_int_force_first = "true" if (props.msfs_with_interior_force_first_lod if props else False) else "false"
            with_int_show_ext = "true" if (props.msfs_with_interior_show_exterior if props else True) else "false"

            cfg_lines.append(f"withExterior_showInterior={with_ext_show_int}")
            cfg_lines.append(f"withExterior_showInterior_hideFirstLod={with_ext_hide_first}")
            cfg_lines.append(f"withInterior_forceFirstLod={with_int_force_first}")
            cfg_lines.append(f"withInterior_showExterior={with_int_show_ext}")
            cfg_lines.append("")

        cfg_lines.extend(["[models]", f"normal={clean_base}.xml"])
        if has_interior and not is_scenery:
            cfg_lines.append(f"interior={interior_name}.xml")
        cfg_lines.append("")
        try:
            with open(model_cfg_path, "w", encoding="utf-8") as f:
                f.write("\n".join(cfg_lines))
        except OSError as exc:
            logger.warning("Could not write model.cfg: %s", exc)
            return False, f"Failed writing model.cfg for package '{clean_base}': {exc}"

        # 4. Export Variants if present
        if bdata_cols:
            for coll in bdata_cols:
                c_name = coll.name
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
                        "_Config",
                        "_Helpers",
                        "_Attachments",
                        "_Submodel_Previews",
                        "_Mesh",
                        "_HighPoly",
                        "_HP",
                        "_LowPoly",
                        "_LP",
                        "_Bake",
                        "_Rig",
                        "_Armature",
                        "_Collision",
                        "_Physics",
                    )
                ):
                    raw_suffix = c_name[len(clean_base) + 1 :].strip()
                    var_id = re.sub(r'[\s<>:"/\\|?*]+', "_", raw_suffix).lower().strip("_")
                    if not var_id:
                        continue
                    pkg_root = os.path.dirname(model_dir.rstrip("/\\"))
                    variant_dir = os.path.join(pkg_root, f"model.{var_id}")
                    os.makedirs(variant_dir, exist_ok=True)
                    ok_var, msg_var = cls.export_asset(context, variant_dir, c_name, **kwargs)
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
                            return False, f"Failed writing variant model.cfg for '{c_name}': {exc}"

        if exported_count == 0:
            return False, f"No model geometry found to export for package '{clean_base}'."

        return True, f"MSFS package ({exported_count} model(s) & configs) exported to: {export_dir}"
