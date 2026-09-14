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
            '        if node.has_meta("visibility_range_end"):',
            '            var dist_begin: float = float(node.get_meta("visibility_range_begin", 0.0))',
            '            var dist_end: float = float(node.get_meta("visibility_range_end", 0.0))',
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
    def generate_plugin_cfg(cls) -> str:
        """Generates Godot 4 plugin.cfg manifest."""
        return (
            "[plugin]\n\n"
            'name="OmniMesh Importer"\n'
            'description="Automated LOD visibility range and material setup for OmniMesh models"\n'
            'author="OmniMesh"\n'
            'version="0.8.0"\n'
            'script="OmniMeshPlugin.gd"\n'
        )

    @classmethod
    def generate_editor_plugin_gdscript(cls) -> str:
        """Generates Godot 4 EditorPlugin registering EditorScenePostImportPlugin."""
        lines = [
            "@tool",
            "extends EditorPlugin",
            "",
            "var import_plugin = null",
            "",
            "func _enter_tree() -> void:",
            '    var script = load("res://addons/omnimesh/OmniMeshSceneImportPlugin.gd")',
            "    if script:",
            "        import_plugin = script.new()",
            "        add_scene_post_import_plugin(import_plugin)",
            "",
            "func _exit_tree() -> void:",
            "    if import_plugin:",
            "        remove_scene_post_import_plugin(import_plugin)",
            "        import_plugin = null",
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def generate_scene_import_plugin_gdscript(cls) -> str:
        """Generates EditorScenePostImportPlugin intercepting OmniMesh scenes."""
        lines = [
            "@tool",
            "extends EditorScenePostImportPlugin",
            "",
            "const FADE_MARGIN_METERS: float = 2.5",
            "",
            "func _post_process(scene: Node) -> void:",
            "    _process_lod_nodes(scene)",
            "",
            "func _process_lod_nodes(node: Node) -> void:",
            "    if node is MeshInstance3D:",
            "        var node_name: String = node.name.to_lower()",
            '        if node.has_meta("visibility_range_end"):',
            '            var dist_begin: float = float(node.get_meta("visibility_range_begin", 0.0))',
            '            var dist_end: float = float(node.get_meta("visibility_range_end", 0.0))',
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
    def generate_asset_import_file(cls, rel_gltf_path: str) -> str:
        """Generates standard Godot 4 .import config targeting OmniMeshPostImport.gd."""
        posix_path = str(rel_gltf_path).replace("\\", "/")
        lines = [
            "[remap]",
            "",
            'importer="scene"',
            "importer_version=1",
            'type="PackedScene"',
            f'uid="uid://omnimesh_{abs(hash(posix_path))}"',
            "valid=false",
            "",
            "[deps]",
            "",
            f'source_file="res://{posix_path}"',
            f'dest_files=["res://.godot/imported/{os.path.basename(posix_path)}-omnimesh.scn"]',
            "",
            "[params]",
            "",
            "_subresources={}",
            "custom_script/enabled=true",
            'custom_script/path="res://addons/omnimesh/OmniMeshPostImport.gd"',
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def install_companion_scripts(cls, project_dir: str) -> Tuple[bool, str]:
        """Installs addons/omnimesh/ suite (plugin.cfg, EditorPlugin, SceneImportPlugin, PostImport) into Godot project."""
        if not project_dir or not os.path.exists(project_dir):
            return False, "Godot Project directory does not exist."

        addons_dir = os.path.join(project_dir, "addons", "omnimesh")
        os.makedirs(addons_dir, exist_ok=True)

        files_to_write = [
            ("plugin.cfg", cls.generate_plugin_cfg()),
            ("OmniMeshPlugin.gd", cls.generate_editor_plugin_gdscript()),
            ("OmniMeshSceneImportPlugin.gd", cls.generate_scene_import_plugin_gdscript()),
            ("OmniMeshPostImport.gd", cls.generate_post_import_gdscript()),
        ]

        try:
            for fname, content in files_to_write:
                fpath = os.path.join(addons_dir, fname)
                with open(fpath, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            return True, f"Installed Godot OmniMesh companion plugin suite to {addons_dir}"
        except OSError as e:
            return False, f"Failed to write Godot scripts: {str(e)}"

    @classmethod
    def sync_asset_headless(
        cls,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
        extra_options: Any = None,
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
        try:
            if os.path.commonpath([resolved_proj, target_dir]) != resolved_proj:
                return False, "Directory traversal detected in asset name."
        except ValueError:
            return False, "Directory traversal detected in asset name."

        import stat

        def _safe_copy(src: str, dst: str) -> None:
            try:
                shutil.copy2(src, dst)
            except PermissionError:
                if os.path.exists(dst):
                    try:
                        os.chmod(dst, stat.S_IWRITE)
                        shutil.copy2(src, dst)
                    except Exception:
                        raise
                else:
                    raise

        try:
            os.makedirs(target_dir, exist_ok=True)
            copied = 0
            for item in os.listdir(export_dir):
                s = os.path.join(export_dir, item)
                d = os.path.join(target_dir, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, dirs_exist_ok=True, copy_function=_safe_copy)
                    copied += 1
                else:
                    _safe_copy(s, d)
                    copied += 1
                    # If this is a gltf or glb file, write companion .import file
                    if item.lower().endswith((".gltf", ".glb")):
                        rel_path = f"OmniMesh_Exports/{clean_asset}/{item}"
                        import_path = f"{d}.import"
                        if not os.path.exists(import_path):
                            try:
                                with open(import_path, "w", encoding="utf-8", newline="\n") as f_imp:
                                    f_imp.write(cls.generate_asset_import_file(rel_path))
                            except OSError:
                                pass
        except (OSError, shutil.Error) as exc:
            return False, f"Failed copying asset files to Godot project: {exc}"

        cls.install_companion_scripts(project_dir)
        return (
            True,
            f"Synced glTF asset '{clean_asset}' ({copied} files) to Godot: res://OmniMesh_Exports/{clean_asset}/",
        )

    @classmethod
    def sync_asset(
        cls,
        context: Any,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
    ) -> Tuple[bool, str]:
        return cls.sync_asset_headless(export_dir, asset_name, project_dir)
