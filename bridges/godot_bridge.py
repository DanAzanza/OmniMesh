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
        """Generates Godot 4 EditorScenePostImport GDScript."""
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
            '        regex.compile("_lod(\\\\d+)$")',
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
            return False, f"Export directory not found: {export_dir}"

        cls.install_companion_scripts(project_dir)

        target_import_dir = os.path.join(project_dir, "OmniMesh_Exports", asset_name)
        os.makedirs(target_import_dir, exist_ok=True)

        copied_models = 0
        for f in os.listdir(export_dir):
            if f.endswith((".gltf", ".glb", ".bin")):
                shutil.copy2(os.path.join(export_dir, f), os.path.join(target_import_dir, f))
                if f.endswith((".gltf", ".glb")):
                    copied_models += 1

        if copied_models == 0:
            return False, f"No glTF/GLB models found in export directory: {export_dir}"

        src_tex = os.path.join(export_dir, "Textures")
        if os.path.exists(src_tex):
            dest_tex = os.path.join(target_import_dir, "Textures")
            os.makedirs(dest_tex, exist_ok=True)
            for f in os.listdir(src_tex):
                shutil.copy2(os.path.join(src_tex, f), os.path.join(dest_tex, f))

        return True, f"Synced glTF asset ({copied_models} models) and textures to Godot project at {target_import_dir}"
