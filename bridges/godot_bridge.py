"""
Hardened Godot 4 Live Bridge with GDScript Post-Import Generation and Visibility Range Configuration.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any, Tuple

from .base import EngineBridgeBase

logger = logging.getLogger(__name__)


class GodotLiveBridge(EngineBridgeBase):
    @classmethod
    def get_engine_name(cls) -> str:
        return "Godot 4"

    @classmethod
    def ping_engine(cls, project_dir: str = "") -> Tuple[bool, str]:
        if not project_dir or not os.path.exists(project_dir):
            return False, "⚪ Godot Project Path not configured"
        project_godot = os.path.join(project_dir, "project.godot")
        if os.path.exists(project_godot):
            script_path = os.path.join(project_dir, "addons", "omnimesh", "OmniMeshPostImport.gd")
            if os.path.exists(script_path):
                return True, "🟢 Godot Project Ready (Post-Import Active)"
            return True, "🟡 Godot Project Found (Post-Import pending install)"
        return False, "⚪ Invalid Godot Project (Missing project.godot)"

    @classmethod
    def generate_post_import_gdscript(cls) -> str:
        """Generates Godot 4 EditorScenePostImport GDScript with Impostor Material routing."""
        lines = [
            "@tool",
            "extends EditorScenePostImport",
            "",
            "const FADE_MARGIN_METERS: float = 2.5",
            "",
            "func _post_import(scene: Node) -> Object:",
            "    _process_lod_nodes(scene)",
            "    return scene",
            "",
            "func _process_lod_nodes(node: Node) -> void:",
            "    if node is MeshInstance3D:",
            "        var node_name: String = node.name.to_lower()",
            "        var regex = RegEx.new()",
            '        regex.compile("(_lod(\\\\d+)$|_impostor)")',
            "        var result = regex.search(node_name)",
            "",
            "        if result:",
            '            var dist_begin: float = node.get_meta("visibility_range_begin", 0.0)',
            '            var dist_end: float = node.get_meta("visibility_range_end", 0.0)',
            "",
            "            if dist_end > 0.0:",
            "                node.visibility_range_begin = dist_begin",
            "                node.visibility_range_end = dist_end",
            "                node.visibility_range_fade_mode = GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF",
            "                node.visibility_range_begin_margin = FADE_MARGIN_METERS",
            "                node.visibility_range_end_margin = FADE_MARGIN_METERS",
            "",
            '        if "impostor" in node_name:',
            "            var mesh_res = node.mesh",
            "            if mesh_res:",
            "                for surf_idx in range(mesh_res.get_surface_count()):",
            "                    var mat = mesh_res.surface_get_material(surf_idx)",
            "                    if mat is StandardMaterial3D or mat is ORMMaterial3D:",
            "                        mat.cull_mode = BaseMaterial3D.CULL_DISABLED",
            "                        mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA_SCISSOR",
            "                        mat.alpha_scissor_threshold = 0.33",
            "                        mat.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS",
            "",
            "    for child in node.get_children():",
            "        _process_lod_nodes(child)",
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def install_companion_scripts(cls, project_dir: str) -> Tuple[bool, str]:
        """Installs addons/omnimesh/OmniMeshPostImport.gd into Godot project."""
        if not project_dir or not os.path.exists(project_dir):
            return False, "Godot Project directory does not exist."

        addons_dir = os.path.join(project_dir, "addons", "omnimesh")
        os.makedirs(addons_dir, exist_ok=True)

        target_file = os.path.join(addons_dir, "OmniMeshPostImport.gd")
        try:
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(cls.generate_post_import_gdscript())
            return True, f"Installed Godot Post-Import script to {target_file}"
        except OSError as e:
            return False, f"Failed to write GDScript post-import: {str(e)}"

    @classmethod
    def sync_asset(
        cls,
        context: Any,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
    ) -> Tuple[bool, str]:
        if not project_dir or not os.path.exists(project_dir):
            return False, "Target Godot project directory not configured."

        if not export_dir or not os.path.exists(export_dir):
            return False, f"Export directory not found: '{export_dir}'"

        gltf_files = [f for f in os.listdir(export_dir) if f.lower().endswith((".gltf", ".glb"))]
        if not gltf_files:
            return False, f"No glTF/GLB models found in export directory: '{export_dir}'"

        import re

        clean_name = os.path.basename(str(asset_name))
        clean_asset = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean_name).strip() or "SM_Asset"
        resolved_proj = os.path.abspath(project_dir)
        target_dir = os.path.abspath(os.path.join(resolved_proj, "OmniMesh_Exports", clean_asset))
        if not target_dir.startswith(resolved_proj):
            return False, "Directory traversal detected in asset name."

        try:
            os.makedirs(target_dir, exist_ok=True)
            copied = 0
            for item in os.listdir(export_dir):
                s = os.path.join(export_dir, item)
                d = os.path.join(target_dir, item)
                if os.path.isdir(s):
                    if os.path.exists(d):
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                    copied += 1
                else:
                    shutil.copy2(s, d)
                    copied += 1
        except (OSError, shutil.Error) as exc:
            return False, f"Failed copying asset files to Godot project: {exc}"

        cls.install_companion_scripts(project_dir)
        return (
            True,
            f"Synced glTF asset '{clean_asset}' ({copied} files) to Godot: res://OmniMesh_Exports/{clean_asset}/",
        )
