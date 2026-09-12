"""
Godot 4.x glTF Exporter for LOD Meshes and -convcol Collision Shapes.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

import re

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


class GodotExporter:
    @classmethod
    def export_asset(cls, context: Any, export_dir: str, asset_name: str) -> tuple[bool, str]:
        if not bpy or not context:
            return False, "Blender bpy not available."
        props = getattr(context.scene, "lod_tool", None)
        clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(asset_name)).strip() or "SM_Asset"

        try:
            os.makedirs(export_dir, exist_ok=True)
        except OSError as exc:
            return False, f"Failed creating export directory '{export_dir}': {exc}"

        payload = AssetMeshResolver.resolve_payload(context, clean_name) if AssetMeshResolver else None
        if not payload or not payload.lod_tiers:
            return False, "No generated LOD objects found to export."

        if hasattr(bpy.ops.object, "mode_set") and getattr(context, "mode", "") != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception as exc:
                logger.debug("Mode set to OBJECT skipped: %s", exc)

        all_objs: list[Any] = []
        for tier_idx in sorted(payload.lod_tiers.keys()):
            for obj in payload.lod_tiers[tier_idx]:
                if obj not in all_objs:
                    all_objs.append(obj)

        if not all_objs:
            return False, "No generated LOD objects found to export."

        collider_objects = list(payload.collider_objects)

        bpy.ops.object.select_all(action="DESELECT")

        orig_prop_states: dict[Any, dict[str, Any]] = {}
        orig_collider_names: dict[Any, str] = {}
        gltf_path = os.path.join(export_dir, f"{clean_name}.gltf")

        try:
            for tier_idx, tier_objs in sorted(payload.lod_tiers.items()):
                is_impostor_obj = payload.has_impostor_tier and tier_idx == max(payload.lod_tiers.keys())

                dist_begin = 0.0
                dist_end = 100.0
                if props and len(props.lods) > 0:
                    cull_pct = max(0.01, float(getattr(props, "cull_screen_size_pct", 0.5)))
                    last_tier = props.lods[-1]
                    last_dist = float(getattr(last_tier, "distance_m", 50.0) or 50.0)
                    last_screen_pct = float(getattr(last_tier, "screen_size_pct", 50.0) or 50.0)
                    cull_dist = max(last_dist * 1.5, last_dist * (last_screen_pct / cull_pct))

                    if is_impostor_obj:
                        dist_begin = last_dist
                        dist_end = cull_dist
                    else:
                        if tier_idx == 0:
                            dist_begin = 0.0
                        else:
                            prev_tier = props.lods[min(tier_idx - 1, len(props.lods) - 1)]
                            dist_begin = float(getattr(prev_tier, "distance_m", 10.0) or 10.0)

                        if tier_idx >= len(props.lods) - 1:
                            dist_end = cull_dist
                        else:
                            cur_tier = props.lods[min(tier_idx, len(props.lods) - 1)]
                            dist_end = float(getattr(cur_tier, "distance_m", 50.0) or 50.0)

                for obj in tier_objs:
                    try:
                        obj.hide_set(False, view_layer=context.view_layer)
                        obj.hide_viewport = False
                    except (RuntimeError, AttributeError) as exc:
                        logger.debug(
                            "Could not unhide object %s in view layer: %s", getattr(obj, "name", "unknown"), exc
                        )

                    orig_prop_states[obj] = {
                        "visibility_range_begin": obj.get("visibility_range_begin"),
                        "visibility_range_end": obj.get("visibility_range_end"),
                    }
                    obj["visibility_range_begin"] = dist_begin
                    obj["visibility_range_end"] = dist_end
                    obj.select_set(True)

            # Prepare and select collider objects with -convcol suffix
            for idx, c_obj in enumerate(collider_objects, start=1):
                try:
                    c_obj.hide_set(False, view_layer=context.view_layer)
                    c_obj.hide_viewport = False
                    orig_collider_names[c_obj] = c_obj.name
                    if not c_obj.name.endswith("-convcol"):
                        c_obj.name = f"{clean_name}_Collider_{idx:02d}-convcol"
                    c_obj.select_set(True)
                except (RuntimeError, AttributeError) as exc:
                    logger.debug("Could not prepare collider %s: %s", getattr(c_obj, "name", "unknown"), exc)

            context.view_layer.objects.active = all_objs[0]

            bpy.ops.export_scene.gltf(
                filepath=gltf_path,
                use_selection=True,
                export_format="GLTF_SEPARATE",
                export_extras=True,
                export_apply=True,
            )
            return True, f"Godot 4 glTF exported to: {gltf_path}"
        except Exception as e:
            return False, f"Failed to export Godot glTF: {str(e)}"
        finally:
            # Restore original collider names
            for c_obj, orig_name in orig_collider_names.items():
                try:
                    c_obj.name = orig_name
                except Exception as exc:
                    logger.debug("Restoring collider name failed: %s", exc)
            # Restore original property states
            for obj, state in orig_prop_states.items():
                for k, v in state.items():
                    if v is None and k in obj:
                        try:
                            del obj[k]
                        except Exception as exc:
                            logger.debug("Could not remove property %s: %s", k, exc)
                    elif v is not None:
                        try:
                            obj[k] = v
                        except Exception as exc:
                            logger.debug("Could not restore property %s: %s", k, exc)
