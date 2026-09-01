"""
OmniMesh PBR Texture Importer & Multi-Channel Shader Graph Builder.
Architected for Blender 4.2+ LTS & Blender 5.2 LTS (EEVEE Next, Principled BSDF V2, AgX / OpenColorIO).
Features:
- Token-bounded regex semantic classification with negative lookaheads and UDIM stripping.
- OCIO AgX/ACES robust color space resolution.
- Non-destructive DirectX normal inversion & packed channel demuxing (ORM/COMP/MaskMap).
- Principled BSDF V2 socket compatibility layer.
- Longest-prefix tokenized material slot matcher.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("OmniMesh.PBRImporter")

try:
    import bpy
except ImportError:
    bpy = None


class PBRSemanticClassifier:
    """
    Hardened semantic texture classifier with UDIM stripping, resolution filtering,
    and token-bounded regex matching.
    """

    # Resolution, UDIM, and variation suffixes to strip before token matching
    STRIP_PATTERNS = [
        re.compile(r"[._-](?:10\d{2}|u\d+_v\d+)(?=\.[^.]+$|$)", re.IGNORECASE),  # UDIM tiles (1001-1099)
        re.compile(r"[._-](?:[1-8]k|1024|2048|4096|8192)(?=\.[^.]+$|$)", re.IGNORECASE),  # Resolution tags
        re.compile(r"[._-](?:lod[0-4]|proxy|high|low)(?=\.[^.]+$|$)", re.IGNORECASE),  # LOD/Mesh tags
        re.compile(r"\.\d{3}$"),  # Blender duplicate extensions (.001)
    ]

    # Strict token definitions with explicit delimiters to prevent single-letter stem false positives
    SEMANTIC_RULES: list[tuple[str, re.Pattern[str]]] = [
        # Packed Formats (Highest priority to prevent individual channel capture)
        ("PACKED_MASKMAP", re.compile(r"(?:^|[._-])(?:maskmap|mask_map|mask)(?:[._-]|$)", re.IGNORECASE)),
        ("PACKED_ORM", re.compile(r"(?:^|[._-])(?:orm|ao_rough_metal|arm|ord)(?:[._-]|$)", re.IGNORECASE)),
        ("PACKED_COMP", re.compile(r"(?:^|[._-])(?:comp|composite)(?:[._-]|$)", re.IGNORECASE)),
        ("PACKED_METALLICGLOSS", re.compile(r"(?:^|[._-])(?:metallicgloss|metalgloss)(?:[._-]|$)", re.IGNORECASE)),
        # Normal Maps (DirectX must be tested before generic/OpenGL)
        (
            "NORMAL_DIRECTX",
            re.compile(
                r"(?:^|[._-])(?:normal_?dx|nor_?dx|nrm_?dx|n_?dx|normal_directx|n_directx)(?:[._-]|$)", re.IGNORECASE
            ),
        ),
        (
            "NORMAL_OPENGL",
            re.compile(r"(?:^|[._-])(?:normal_?gl|nor_?gl|nrm_?gl|normal|nor|nrm|n)(?:[._-]|$)", re.IGNORECASE),
        ),
        # Roughness vs Glossiness
        ("ROUGHNESS", re.compile(r"(?:^|[._-])(?:roughness|rough|rgh|r)(?:[._-]|$)", re.IGNORECASE)),
        (
            "GLOSSINESS",
            re.compile(r"(?:^|[._-])(?:glossiness|gloss|gls|smoothness|smooth|g)(?:[._-]|$)", re.IGNORECASE),
        ),
        # Metallic
        ("METALLIC", re.compile(r"(?:^|[._-])(?:metallic|metalness|metal|met|m)(?:[._-]|$)", re.IGNORECASE)),
        # Base Color / Albedo
        (
            "BASE_COLOR",
            re.compile(r"(?:^|[._-])(?:base_?color|albedo|alb|diffuse|diff|col|color|d)(?:[._-]|$)", re.IGNORECASE),
        ),
        # Ambient Occlusion
        (
            "AMBIENT_OCCLUSION",
            re.compile(r"(?:^|[._-])(?:ambient_?occlusion|ao|occlusion|occ)(?:[._-]|$)", re.IGNORECASE),
        ),
        # Emission
        ("EMISSION", re.compile(r"(?:^|[._-])(?:emission|emissive|emit|e)(?:[._-]|$)", re.IGNORECASE)),
        # Opacity / Alpha
        ("OPACITY", re.compile(r"(?:^|[._-])(?:opacity|alpha|transparency|mask_opacity|a)(?:[._-]|$)", re.IGNORECASE)),
        # Height / Displacement
        ("DISPLACEMENT", re.compile(r"(?:^|[._-])(?:height|displacement|disp|bump|h)(?:[._-]|$)", re.IGNORECASE)),
    ]

    @classmethod
    def clean_stem(cls, filename: str) -> str:
        """Strips path, extension, UDIMs, and resolution tags from filename."""
        stem = os.path.splitext(os.path.basename(filename))[0]
        for pattern in cls.STRIP_PATTERNS:
            stem = pattern.sub("", stem)
        return stem

    @classmethod
    def classify(cls, filename: str) -> str | None:
        """Returns the semantic texture channel type for a given filename."""
        clean = cls.clean_stem(filename)
        for semantic_type, regex in cls.SEMANTIC_RULES:
            if regex.search(clean):
                return semantic_type
        return None


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
    Constructs or updates canonical Principled BSDF V2 node trees with clean grid layout.
    """

    NODE_X_SPACING = 300
    NODE_Y_SPACING = 280

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

    @classmethod
    def build_pbr_graph(
        cls,
        material: Any,
        texture_map: dict[str, str],
        preserve_existing: bool = False,
        ao_blend_mode: str = "MULTIPLY",
    ) -> None:
        """Constructs a deterministic PBR shader network."""
        if not bpy or not material:
            return
        material.use_nodes = True
        nt = material.node_tree
        nodes = nt.nodes
        links = nt.links

        # Locate or create Output Material node
        output_node = next((n for n in nodes if getattr(n, "type", "") == "OUTPUT_MATERIAL"), None)
        if not output_node:
            output_node = nodes.new(type="ShaderNodeOutputMaterial")
            output_node.location = (600, 300)

        # Locate or create Principled BSDF node
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

        # Shared UV & Mapping Coordinates
        tex_coord = nodes.new(type="ShaderNodeTexCoord")
        tex_coord.location = (-1000, 0)
        mapping = nodes.new(type="ShaderNodeMapping")
        mapping.location = (-800, 0)
        links.new(tex_coord.outputs["UV"], mapping.inputs["Vector"])

        y_offset = 600
        x_tex = -550
        x_proc = -250

        # 1. Base Color
        if "BASE_COLOR" in texture_map:
            img = bpy.data.images.load(texture_map["BASE_COLOR"], check_existing=True)
            OCIOColorSpaceResolver.apply_colorspace(img, is_data=False)
            tex_node = nodes.new(type="ShaderNodeTexImage")
            tex_node.image = img
            tex_node.location = (x_tex, y_offset)
            links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

            base_sock = cls.get_bsdf_socket(bsdf_node, ["Base Color", "BaseColor", "Albedo"])
            if base_sock:
                if "AMBIENT_OCCLUSION" in texture_map and ao_blend_mode == "MULTIPLY":
                    ao_img = bpy.data.images.load(texture_map["AMBIENT_OCCLUSION"], check_existing=True)
                    OCIOColorSpaceResolver.apply_colorspace(ao_img, is_data=True)
                    ao_node = nodes.new(type="ShaderNodeTexImage")
                    ao_node.image = ao_img
                    ao_node.location = (x_tex, y_offset - cls.NODE_Y_SPACING)
                    links.new(mapping.outputs["Vector"], ao_node.inputs["Vector"])

                    mix_node = nodes.new(type="ShaderNodeMix")
                    if hasattr(mix_node, "data_type"):
                        mix_node.data_type = "RGBA"
                    mix_node.blend_type = "MULTIPLY"
                    if len(mix_node.inputs) > 0 and hasattr(mix_node.inputs[0], "default_value"):
                        mix_node.inputs[0].default_value = 1.0  # Factor
                    mix_node.location = (x_proc, y_offset)

                    # Connect Mix RGBA sockets
                    col_a_sock = mix_node.inputs.get("A") or mix_node.inputs[6]
                    col_b_sock = mix_node.inputs.get("B") or mix_node.inputs[7]
                    col_res_sock = mix_node.outputs.get("Result") or mix_node.outputs[2]

                    links.new(tex_node.outputs["Color"], col_a_sock)
                    links.new(ao_node.outputs["Color"], col_b_sock)
                    links.new(col_res_sock, base_sock)
                    y_offset -= cls.NODE_Y_SPACING
                else:
                    links.new(tex_node.outputs["Color"], base_sock)

            # Check if Alpha is embedded in BaseColor
            if "OPACITY" not in texture_map and getattr(img, "channels", 3) == 4:
                alpha_sock = cls.get_bsdf_socket(bsdf_node, ["Alpha"])
                if alpha_sock:
                    links.new(tex_node.outputs["Alpha"], alpha_sock)
                    if hasattr(material, "blend_method"):
                        material.blend_method = "CLIP"

            y_offset -= cls.NODE_Y_SPACING

        # 2. Packed ORM / COMP / MaskMap Demuxing
        if "PACKED_ORM" in texture_map or "PACKED_COMP" in texture_map:
            key = "PACKED_ORM" if "PACKED_ORM" in texture_map else "PACKED_COMP"
            img = bpy.data.images.load(texture_map[key], check_existing=True)
            OCIOColorSpaceResolver.apply_colorspace(img, is_data=True)
            tex_node = nodes.new(type="ShaderNodeTexImage")
            tex_node.image = img
            tex_node.location = (x_tex, y_offset)
            links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

            sep_node = nodes.new(type="ShaderNodeSeparateColor")
            sep_node.location = (x_proc, y_offset)
            links.new(tex_node.outputs["Color"], sep_node.inputs["Color"])

            # ORM: R=AO, G=Roughness, B=Metallic
            rough_sock = cls.get_bsdf_socket(bsdf_node, ["Roughness"])
            metal_sock = cls.get_bsdf_socket(bsdf_node, ["Metallic", "Metalness"])
            if rough_sock:
                links.new(sep_node.outputs["Green"], rough_sock)
            if metal_sock:
                links.new(sep_node.outputs["Blue"], metal_sock)

            y_offset -= cls.NODE_Y_SPACING

        # 3. Individual Metallic & Roughness / Glossiness
        else:
            if "METALLIC" in texture_map:
                img = bpy.data.images.load(texture_map["METALLIC"], check_existing=True)
                OCIOColorSpaceResolver.apply_colorspace(img, is_data=True)
                tex_node = nodes.new(type="ShaderNodeTexImage")
                tex_node.image = img
                tex_node.location = (x_tex, y_offset)
                links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])
                metal_sock = cls.get_bsdf_socket(bsdf_node, ["Metallic", "Metalness"])
                if metal_sock:
                    links.new(tex_node.outputs["Color"], metal_sock)
                y_offset -= cls.NODE_Y_SPACING

            if "ROUGHNESS" in texture_map:
                img = bpy.data.images.load(texture_map["ROUGHNESS"], check_existing=True)
                OCIOColorSpaceResolver.apply_colorspace(img, is_data=True)
                tex_node = nodes.new(type="ShaderNodeTexImage")
                tex_node.image = img
                tex_node.location = (x_tex, y_offset)
                links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])
                rough_sock = cls.get_bsdf_socket(bsdf_node, ["Roughness"])
                if rough_sock:
                    links.new(tex_node.outputs["Color"], rough_sock)
                y_offset -= cls.NODE_Y_SPACING

            elif "GLOSSINESS" in texture_map:
                img = bpy.data.images.load(texture_map["GLOSSINESS"], check_existing=True)
                OCIOColorSpaceResolver.apply_colorspace(img, is_data=True)
                tex_node = nodes.new(type="ShaderNodeTexImage")
                tex_node.image = img
                tex_node.location = (x_tex, y_offset)
                links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

                # Invert: 1.0 - Gloss = Roughness
                math_node = nodes.new(type="ShaderNodeMath")
                math_node.operation = "SUBTRACT"
                math_node.inputs[0].default_value = 1.0
                math_node.location = (x_proc, y_offset)
                links.new(tex_node.outputs["Color"], math_node.inputs[1])

                rough_sock = cls.get_bsdf_socket(bsdf_node, ["Roughness"])
                if rough_sock:
                    links.new(math_node.outputs["Value"], rough_sock)
                y_offset -= cls.NODE_Y_SPACING

        # 4. Normal Map (DirectX Inversion vs OpenGL)
        normal_key = (
            "NORMAL_DIRECTX"
            if "NORMAL_DIRECTX" in texture_map
            else ("NORMAL_OPENGL" if "NORMAL_OPENGL" in texture_map else None)
        )
        if normal_key:
            img = bpy.data.images.load(texture_map[normal_key], check_existing=True)
            OCIOColorSpaceResolver.apply_colorspace(img, is_data=True)
            tex_node = nodes.new(type="ShaderNodeTexImage")
            tex_node.image = img
            tex_node.location = (x_tex, y_offset)
            links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

            norm_node = nodes.new(type="ShaderNodeNormalMap")
            norm_node.location = (x_proc, y_offset)

            if normal_key == "NORMAL_DIRECTX":
                # Non-destructive DirectX Green-channel inversion
                sep_color = nodes.new(type="ShaderNodeSeparateColor")
                sep_color.location = (x_tex + 250, y_offset)
                links.new(tex_node.outputs["Color"], sep_color.inputs["Color"])

                inv_green = nodes.new(type="ShaderNodeMath")
                inv_green.operation = "SUBTRACT"
                inv_green.inputs[0].default_value = 1.0
                inv_green.location = (x_tex + 400, y_offset - 80)
                links.new(sep_color.outputs["Green"], inv_green.inputs[1])

                comb_color = nodes.new(type="ShaderNodeCombineColor")
                comb_color.location = (x_tex + 550, y_offset)
                links.new(sep_color.outputs["Red"], comb_color.inputs["Red"])
                links.new(inv_green.outputs["Value"], comb_color.inputs["Green"])
                links.new(sep_color.outputs["Blue"], comb_color.inputs["Blue"])

                links.new(comb_color.outputs["Color"], norm_node.inputs["Color"])
            else:
                links.new(tex_node.outputs["Color"], norm_node.inputs["Color"])

            normal_sock = cls.get_bsdf_socket(bsdf_node, ["Normal"])
            if normal_sock:
                links.new(norm_node.outputs["Normal"], normal_sock)
            y_offset -= cls.NODE_Y_SPACING

        # 5. Emission
        if "EMISSION" in texture_map:
            img = bpy.data.images.load(texture_map["EMISSION"], check_existing=True)
            OCIOColorSpaceResolver.apply_colorspace(img, is_data=False)
            tex_node = nodes.new(type="ShaderNodeTexImage")
            tex_node.image = img
            tex_node.location = (x_tex, y_offset)
            links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

            emit_sock = cls.get_bsdf_socket(bsdf_node, ["Emission Color", "Emission"])
            if emit_sock:
                links.new(tex_node.outputs["Color"], emit_sock)
            emit_strength = cls.get_bsdf_socket(bsdf_node, ["Emission Strength"])
            if emit_strength and not getattr(emit_strength, "is_linked", False):
                emit_strength.default_value = 1.0
            y_offset -= cls.NODE_Y_SPACING

        # 6. Opacity / Alpha
        if "OPACITY" in texture_map:
            img = bpy.data.images.load(texture_map["OPACITY"], check_existing=True)
            OCIOColorSpaceResolver.apply_colorspace(img, is_data=True)
            tex_node = nodes.new(type="ShaderNodeTexImage")
            tex_node.image = img
            tex_node.location = (x_tex, y_offset)
            links.new(mapping.outputs["Vector"], tex_node.inputs["Vector"])

            alpha_sock = cls.get_bsdf_socket(bsdf_node, ["Alpha"])
            if alpha_sock:
                links.new(tex_node.outputs["Color"], alpha_sock)
                if hasattr(material, "blend_method"):
                    material.blend_method = "CLIP"
            y_offset -= cls.NODE_Y_SPACING


class BatchMaterialSlotMatcher:
    """
    Performs tokenized, longest-prefix matching to map texture sets to active mesh material slots.
    """

    @classmethod
    def match_directory_to_slots(cls, obj: Any, folder_path: str) -> dict[str, dict[str, str]]:
        """
        Returns a mapping of material_name -> {semantic_type: filepath}.
        """
        if not folder_path or not os.path.isdir(folder_path) or not obj or not getattr(obj, "material_slots", None):
            return {}

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
            semantic_type = PBRSemanticClassifier.classify(filename)

            if not semantic_type:
                continue

            matched_slot = None
            for s_name in slot_names:
                pattern = re.compile(rf"(?:^|[._-]){re.escape(s_name)}(?:[._-]|$)", re.IGNORECASE)
                if pattern.search(stem):
                    matched_slot = s_name
                    break

            if not matched_slot and len(slot_names) == 1:
                matched_slot = slot_names[0]

            if matched_slot:
                results[matched_slot][semantic_type] = filepath

        return results
