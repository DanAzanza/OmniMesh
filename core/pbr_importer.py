"""
OmniMesh PBR Texture Importer & Multi-Channel Shader Graph Builder.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS (EEVEE Next, Principled BSDF V2, AgX / OpenColorIO).
Features:
- Dynamic JSON preset-driven semantic classification with UDIM and tag stripping.
- Priority-based socket conflict arbitration.
- Hardened channel demuxing (RGB, R, G, B via SeparateColor, Alpha tapped directly).
- Anti-chrome mirror guard on missing alpha.
- Type-safe ShaderNodeMix RGBA socket resolution across Blender 4.2+ & 5.2 LTS.
- Non-destructive DirectX normal map green-channel inversion.
- Longest-prefix tokenized material slot matcher.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, ClassVar, Optional

try:
    import bpy
except ImportError:
    bpy = None

try:
    from .pbr_classifier import PBRSemanticClassifier
    from .pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImportPresetManager,
        PBRImporterPresetManager,
    )
except (ImportError, ValueError):
    from core.pbr_classifier import PBRSemanticClassifier
    from core.pbr_presets import (
        DEFAULT_PRESET_ID,
        PBRImportPresetManager,
        PBRImporterPresetManager,
    )

logger = logging.getLogger(__name__)


class OCIOColorSpaceResolver:
    """
    Dynamically resolves valid OpenColorIO color spaces across AgX, Filmic, ACES,
    and Standard configs without raising runtime exceptions.
    """

    COLOR_FALLBACKS = ["sRGB", "sRGB - Texture", "Utility - sRGB - Texture", "sRGB Encoded", "colorspace_srgb"]
    LINEAR_FALLBACKS = ["Linear Rec.709", "Linear", "Linear CIE-XYZ", "ACEScg", "Utility - Linear - sRGB"]
    DATA_FALLBACKS = ["Non-Color", "Raw", "Generic Data", "Utility - Raw", "Linear Rec.709"]

    @classmethod
    def apply_colorspace(cls, image: Any, is_data: bool, is_float: bool = False) -> None:
        """Safely assigns the color space to a Blender image datablock."""
        if not image or not hasattr(image, "colorspace_settings"):
            return

        available_spaces = set()
        try:
            prop = getattr(getattr(image.colorspace_settings, "bl_rna", None), "properties", {}).get("name")
            if prop and hasattr(prop, "enum_items"):
                available_spaces = {item.identifier for item in prop.enum_items}
        except Exception as exc:
            logger.debug("OCIO enum query: %s", exc)

        target_chain = cls.DATA_FALLBACKS if is_data else (cls.LINEAR_FALLBACKS if is_float else cls.COLOR_FALLBACKS)

        for candidate in target_chain:
            if not available_spaces or candidate in available_spaces:
                try:
                    image.colorspace_settings.name = candidate
                    return
                except (TypeError, ValueError):
                    continue

        logger.warning(
            "Failed to resolve OCIO color space for image '%s'. Preserving default.", getattr(image, "name", "unknown")
        )


class ShaderGraphBuilder:
    """
    Constructs or updates canonical Principled BSDF V2 node trees with clean grid layout,
    arbitrary channel demuxing, type-safe mix nodes, and conflict arbitration.
    """

    NODE_X_SPACING = 300
    NODE_Y_SPACING = 280

    BSDF_SOCKET_ALIASES: ClassVar[dict[str, list[str]]] = {
        "Base Color": ["Base Color", "BaseColor", "Albedo"],
        "Roughness": ["Roughness"],
        "Metallic": ["Metallic", "Metalness"],
        "Specular": ["Specular IOR Level", "Specular"],
        "Specular Tint": ["Specular Tint"],
        "Transmission": ["Transmission Weight", "Transmission"],
        "Subsurface": ["Subsurface Weight", "Subsurface"],
        "Subsurface Radius": ["Subsurface Radius"],
        "Subsurface Scale": ["Subsurface Scale"],
        "Clearcoat": ["Coat Weight", "Clearcoat", "Coat"],
        "Coat": ["Coat Weight", "Coat", "Clearcoat"],
        "Clearcoat Roughness": ["Coat Roughness", "Clearcoat Roughness"],
        "Coat Roughness": ["Coat Roughness", "Clearcoat Roughness"],
        "Sheen": ["Sheen Weight", "Sheen"],
        "Sheen Tint": ["Sheen Tint"],
        "Emission": ["Emission Color", "Emission"],
        "Emission Color": ["Emission Color", "Emission"],
        "Emission Strength": ["Emission Strength"],
        "Alpha": ["Alpha", "Opacity"],
        "Normal": ["Normal"],
        "IOR": ["IOR"],
        "Anisotropic": ["Anisotropic"],
        "Anisotropic Rotation": ["Anisotropic Rotation"],
    }

    @classmethod
    def resolve_bsdf_socket(cls, bsdf: Any, target: str) -> Any:
        """Resolves target socket across Blender 3.x, 4.x, and 5.2 LTS Principled BSDF v2 aliases."""
        aliases = cls.BSDF_SOCKET_ALIASES.get(target, [target])
        return cls.get_bsdf_socket(bsdf, aliases)

    @staticmethod
    def get_bsdf_socket(bsdf: Any, aliases: list[str]) -> Any:
        """Safely queries Principled BSDF inputs across Blender 3.x, 4.x, and 5.x."""
        if not bsdf or not hasattr(bsdf, "inputs"):
            return None
        for alias in aliases:
            sock = bsdf.inputs.get(alias)
            if sock:
                return sock
        return None

    @staticmethod
    def get_mix_rgba_socket(mix_node: Any, identifier: str, is_output: bool = False) -> Any:
        """
        Type-safe RGBA socket resolver for ShaderNodeMix across Blender 4.2+ and 5.2 LTS.
        Guards against duplicate socket names where inputs.get('A') returns the Float socket!
        """
        sockets = mix_node.outputs if is_output else mix_node.inputs
        for s in sockets:
            if getattr(s, "name", "") == identifier and getattr(s, "type", "") == "RGBA":
                return s

        candidates = [s for s in sockets if getattr(s, "type", "") == "RGBA"]
        if identifier == "A" and len(candidates) >= 1:
            return candidates[0]
        if identifier == "B" and len(candidates) >= 2:
            return candidates[1]
        if identifier == "Result" and len(candidates) >= 1:
            return candidates[0]

        # Final index fallback if names and types cannot be determined
        if is_output and len(mix_node.outputs) > 2:
            return mix_node.outputs[2]
        if not is_output and len(mix_node.inputs) > 7:
            return mix_node.inputs[6] if identifier == "A" else mix_node.inputs[7]

        return None

    @classmethod
    def resolve_texture_path(cls, raw_path: str, mode: str = "RELATIVE") -> tuple[str, bool]:
        """
        Resolves a texture path according to requested mode ('RELATIVE' vs 'ABSOLUTE').
        Returns (resolved_path, is_relative).
        Guards against unsaved files and Windows cross-drive boundaries.
        """
        if not raw_path or not bpy:
            return raw_path, False

        # First expand Blender's relative path syntax '//' to real absolute path
        abs_path = os.path.abspath(bpy.path.abspath(raw_path)).replace("\\", "/")

        if mode == "ABSOLUTE":
            return abs_path, False

        # If RELATIVE requested:
        if not getattr(bpy.data, "is_saved", False) or not getattr(bpy.data, "filepath", ""):
            return abs_path, False

        blend_dir = os.path.dirname(bpy.path.abspath(bpy.data.filepath))

        # Check cross-drive boundary on Windows
        abs_drive, _ = os.path.splitdrive(abs_path)
        blend_drive, _ = os.path.splitdrive(blend_dir)
        if abs_drive.lower() != blend_drive.lower():
            return abs_path, False

        try:
            rel = bpy.path.relpath(abs_path).replace("\\", "/")
            return rel, True
        except (ValueError, RuntimeError, OSError):
            return abs_path, False

    @classmethod
    def build_pbr_graph(
        cls,
        material: Any,
        texture_map: dict[str, str],
        preset: Optional[dict[str, Any]] = None,
        preserve_existing: bool = False,
        ao_blend_mode: str = "MULTIPLY",
        path_mode: str = "RELATIVE",
    ) -> bool:
        """
        Constructs a deterministic PBR shader network driven by the active preset.
        Handles arbitrary channel demuxing, invert math, type-safe AO mix, and normal map conversions.
        """
        if not bpy or not material or not texture_map:
            return False

        if preset is None:
            preset = PBRImportPresetManager.get_preset(DEFAULT_PRESET_ID)

        material.use_nodes = True
        nt = material.node_tree
        nodes = nt.nodes
        links = nt.links

        # 1. Locate or create Output Material node
        output_node = next((n for n in nodes if getattr(n, "type", "") == "OUTPUT_MATERIAL"), None)
        if not output_node:
            output_node = nodes.new(type="ShaderNodeOutputMaterial")
            output_node.location = (600, 300)

        # 2. Locate or create Principled BSDF node
        bsdf_node = next((n for n in nodes if getattr(n, "type", "") == "BSDF_PRINCIPLED"), None)
        if not bsdf_node:
            bsdf_node = nodes.new(type="ShaderNodeBsdfPrincipled")
            bsdf_node.location = (200, 300)
            if "BSDF" in bsdf_node.outputs and "Surface" in output_node.inputs:
                links.new(bsdf_node.outputs["BSDF"], output_node.inputs["Surface"])

        if not preserve_existing:
            keep_nodes = {bsdf_node, output_node}
            for node in list(nodes):
                if node not in keep_nodes:
                    nodes.remove(node)

        # 3. Coordinate Mapping
        tex_coord = nodes.new(type="ShaderNodeTexCoord")
        tex_coord.location = (-1200, 0)
        mapping = nodes.new(type="ShaderNodeMapping")
        mapping.location = (-1000, 0)
        links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])

        # 4. Conflict Arbitration & Route Plan
        # Resolve map definitions for active files
        maps_by_id = {m.get("id"): m for m in preset.get("maps", [])}
        active_routes: list[dict[str, Any]] = []

        for key, filepath in texture_map.items():
            map_def = maps_by_id.get(key)
            if not map_def:
                # Try case-insensitive lookup
                map_def = next((m for m in preset.get("maps", []) if m.get("id", "").lower() == key.lower()), None)
            if not map_def:
                continue

            priority = int(map_def.get("priority", 10))
            channels = map_def.get("channels", {})
            for ch_key, ch_info in channels.items():
                target = ch_info.get("target", "")
                invert = bool(ch_info.get("invert", False))
                active_routes.append(
                    {
                        "map_id": map_def.get("id"),
                        "priority": priority,
                        "filepath": filepath,
                        "color_space": map_def.get("color_space", "Non-Color"),
                        "normal_format": map_def.get("normal_format", "NONE"),
                        "channel": ch_key.lower(),
                        "target": target,
                        "invert": invert,
                    }
                )

        if not active_routes:
            return False

        # Sort routes by priority ascending so highest priority overrides lower
        active_routes.sort(key=lambda x: x["priority"])
        target_winners: dict[str, dict[str, Any]] = {}
        for r in active_routes:
            target_winners[r["target"]] = r

        # 5. Node Placement State
        y_cursor = 600
        x_tex = -750
        x_proc = -450
        x_post = -150

        loaded_tex_nodes: dict[str, Any] = {}
        loaded_sep_nodes: dict[str, Any] = {}

        def get_or_create_tex_node(filepath: str, color_space: str) -> Any:
            nonlocal y_cursor
            if filepath in loaded_tex_nodes:
                return loaded_tex_nodes[filepath]

            final_path, is_rel = cls.resolve_texture_path(filepath, mode=path_mode)
            abs_disk_path = bpy.path.abspath(final_path)
            try:
                img = bpy.data.images.load(abs_disk_path, check_existing=True)
            except (RuntimeError, OSError) as exc:
                logger.warning("Failed to load image '%s': %s", abs_disk_path, exc)
                return None

            if not img:
                return None

            if is_rel and hasattr(img, "filepath"):
                img.filepath = final_path

            is_data = color_space != "sRGB"
            OCIOColorSpaceResolver.apply_colorspace(img, is_data=is_data)

            t_node = nodes.new(type="ShaderNodeTexImage")
            t_node.image = img
            t_node.location = (x_tex, y_cursor)
            links.new(mapping.outputs["Vector"], t_node.inputs["Vector"])
            loaded_tex_nodes[filepath] = t_node
            y_cursor -= cls.NODE_Y_SPACING
            return t_node

        def get_or_create_sep_node(tex_node: Any, y_loc: float) -> Any:
            if tex_node in loaded_sep_nodes:
                return loaded_sep_nodes[tex_node]
            s_node = nodes.new(type="ShaderNodeSeparateColor")
            s_node.location = (x_proc, y_loc)
            links.new(tex_node.outputs["Color"], s_node.inputs["Color"])
            loaded_sep_nodes[tex_node] = s_node
            return s_node

        # Cache resolved sockets for Base Color and AO to handle multiplicative mixing
        base_color_source = None
        ao_source = None
        has_any_link = False

        # 6. Execute Channel Routing for Resolved Winners
        for target, route in target_winners.items():
            filepath = route["filepath"]
            ch = route["channel"]
            invert = route["invert"]
            t_node = get_or_create_tex_node(filepath, route["color_space"])
            if not t_node or not getattr(t_node, "image", None):
                continue
            img = getattr(t_node, "image", None)

            # Resolve source output socket
            source_sock = None
            if ch == "rgb":
                source_sock = t_node.outputs.get("Color")
            elif ch == "a":
                # Guard against 100% mirror chrome on missing alpha channel
                num_channels = getattr(img, "channels", 4)
                if invert and num_channels < 4:
                    logger.warning(
                        "Image '%s' has %s channels (no Alpha). Skipping inverted Alpha routing.",
                        getattr(img, "name", "unknown"),
                        num_channels,
                    )
                    continue
                source_sock = t_node.outputs.get("Alpha")
            elif ch in {"r", "g", "b"}:
                sep_node = get_or_create_sep_node(t_node, t_node.location.y)
                sock_name = {"r": "Red", "g": "Green", "b": "Blue"}[ch]
                source_sock = sep_node.outputs.get(sock_name)

            if not source_sock:
                continue

            # Invert handler (1.0 - x)
            if invert:
                inv_node = nodes.new(type="ShaderNodeMath")
                inv_node.operation = "SUBTRACT"
                inv_node.inputs[0].default_value = 1.0
                inv_node.location = (x_post, t_node.location.y)
                links.new(source_sock, inv_node.inputs[1])
                source_sock = inv_node.outputs.get("Value")

            # Route to target socket
            if target == "Base Color":
                base_color_source = source_sock
            elif target == "Ambient Occlusion":
                ao_source = source_sock
            elif target == "Normal":
                norm_fmt = route.get("normal_format", "OPENGL")
                norm_node = nodes.new(type="ShaderNodeNormalMap")
                norm_node.location = (x_post, t_node.location.y)

                if norm_fmt == "DIRECTX":
                    # Invert Green channel non-destructively
                    sep_norm = nodes.new(type="ShaderNodeSeparateColor")
                    sep_norm.location = (x_proc, t_node.location.y)
                    links.new(source_sock, sep_norm.inputs["Color"])

                    inv_green = nodes.new(type="ShaderNodeMath")
                    inv_green.operation = "SUBTRACT"
                    inv_green.inputs[0].default_value = 1.0
                    inv_green.location = (x_proc + 180, t_node.location.y - 60)
                    links.new(sep_norm.outputs["Green"], inv_green.inputs[1])

                    comb_norm = nodes.new(type="ShaderNodeCombineColor")
                    comb_norm.location = (x_proc + 360, t_node.location.y)
                    links.new(sep_norm.outputs["Red"], comb_norm.inputs["Red"])
                    links.new(inv_green.outputs["Value"], comb_norm.inputs["Green"])
                    links.new(sep_norm.outputs["Blue"], comb_norm.inputs["Blue"])

                    links.new(comb_norm.outputs["Color"], norm_node.inputs["Color"])
                else:
                    links.new(source_sock, norm_node.inputs["Color"])

                dest_sock = cls.resolve_bsdf_socket(bsdf_node, "Normal")
                if dest_sock:
                    links.new(norm_node.outputs["Normal"], dest_sock)
                    has_any_link = True
            else:
                dest_sock = None
                if target in {"Emission Color", "Emission"}:
                    dest_sock = cls.resolve_bsdf_socket(bsdf_node, target)
                    strength_sock = cls.resolve_bsdf_socket(bsdf_node, "Emission Strength")
                    if strength_sock and not strength_sock.is_linked:
                        strength_sock.default_value = 1.0
                elif target in {"Alpha", "Opacity"}:
                    dest_sock = cls.resolve_bsdf_socket(bsdf_node, target)
                    if hasattr(material, "surface_render_method"):
                        material.surface_render_method = "DITHERED"
                elif target in {"Displacement", "Height"}:
                    # Connect to Material Output Displacement via Displacement node
                    disp_node = nodes.new(type="ShaderNodeDisplacement")
                    disp_node.location = (300, 100)
                    links.new(source_sock, disp_node.inputs["Height"])
                    if "Displacement" in output_node.inputs:
                        links.new(disp_node.outputs["Displacement"], output_node.inputs["Displacement"])
                        has_any_link = True
                else:
                    dest_sock = cls.resolve_bsdf_socket(bsdf_node, target)

                if dest_sock:
                    links.new(source_sock, dest_sock)
                    has_any_link = True

        # 7. AO Multiplicative Blending into Base Color
        bsdf_base = cls.resolve_bsdf_socket(bsdf_node, "Base Color")
        if bsdf_base:
            if base_color_source and ao_source and ao_blend_mode == "MULTIPLY":
                mix_node = nodes.new(type="ShaderNodeMix")
                if hasattr(mix_node, "data_type"):
                    mix_node.data_type = "RGBA"
                mix_node.blend_type = "MULTIPLY"
                if hasattr(mix_node, "clamp_result"):
                    mix_node.clamp_result = True
                mix_node.location = (x_post, 600)

                # Set Factor to 1.0 on Value socket
                for in_s in mix_node.inputs:
                    if getattr(in_s, "name", "") == "Factor" and getattr(in_s, "type", "") == "VALUE":
                        in_s.default_value = 1.0
                        break

                col_a = cls.get_mix_rgba_socket(mix_node, "A", is_output=False)
                col_b = cls.get_mix_rgba_socket(mix_node, "B", is_output=False)
                res_sock = cls.get_mix_rgba_socket(mix_node, "Result", is_output=True)

                if col_a and col_b and res_sock:
                    links.new(base_color_source, col_a)
                    links.new(ao_source, col_b)
                    links.new(res_sock, bsdf_base)
                    has_any_link = True
                else:
                    links.new(base_color_source, bsdf_base)
                    has_any_link = True
            elif base_color_source:
                links.new(base_color_source, bsdf_base)
                has_any_link = True

        # 8. Clean up orphan images if not preserving
        if not preserve_existing and bpy and hasattr(bpy, "data") and hasattr(bpy.data, "images"):
            for img in list(bpy.data.images):
                if getattr(img, "users", 0) == 0:
                    try:
                        bpy.data.images.remove(img)
                    except Exception as exc:
                        logger.debug("Orphan image removal skipped: %s", exc)

        return has_any_link


class BatchMaterialSlotMatcher:
    """
    Performs tokenized, longest-prefix matching to map texture sets to active mesh material slots
    using the active preset's map rules.
    """

    @classmethod
    def match_directory_to_slots(
        cls, obj: Any, folder_path: str, preset: Optional[dict[str, Any]] = None
    ) -> dict[str, dict[str, str]]:
        """
        Returns a mapping of material_name -> {map_id: filepath} using active preset.
        """
        if not folder_path or not os.path.isdir(folder_path) or not obj or not getattr(obj, "material_slots", None):
            return {}

        if preset is None:
            preset = PBRImporterPresetManager.get_preset(DEFAULT_PRESET_ID)

        valid_exts = {".png", ".jpg", ".jpeg", ".tga", ".exr", ".tif", ".tiff", ".webp", ".dds"}
        try:
            all_files = [
                os.path.join(folder_path, f)
                for f in os.listdir(folder_path)
                if os.path.splitext(f)[1].lower() in valid_exts
            ]
        except OSError:
            return {}

        slot_names = [slot.name for slot in obj.material_slots if getattr(slot, "name", None)]
        slot_names.sort(key=len, reverse=True)

        results: dict[str, dict[str, str]] = {name: {} for name in slot_names}

        for filepath in all_files:
            filename = os.path.basename(filepath)
            stem = PBRSemanticClassifier.clean_stem(filename)
            res = PBRSemanticClassifier.classify_with_preset(filename, preset)

            if not res:
                continue
            map_id = res[0]

            matched_slot = None
            for s_name in slot_names:
                pattern = re.compile(rf"(?:^|[._-]){re.escape(s_name)}(?:[._-]|$)", re.IGNORECASE)
                if pattern.search(stem):
                    matched_slot = s_name
                    break

            if not matched_slot and len(slot_names) == 1:
                matched_slot = slot_names[0]

            if matched_slot:
                existing = results[matched_slot].get(map_id)
                if existing:
                    is_aux = any(k in filename.lower() for k in ("billboard", "proxy", "preview", "thumbnail"))
                    existing_is_aux = any(
                        k in os.path.basename(existing).lower() for k in ("billboard", "proxy", "preview", "thumbnail")
                    )
                    slot_is_aux = any(k in matched_slot.lower() for k in ("billboard", "proxy", "preview", "thumbnail"))

                    if not slot_is_aux:
                        if is_aux and not existing_is_aux:
                            continue
                        if not is_aux and existing_is_aux:
                            results[matched_slot][map_id] = filepath
                            continue

                results[matched_slot][map_id] = filepath

        return results
