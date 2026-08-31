"""
Hardened Unity 6 Live Bridge with C# Postprocessor Generation and Non-Destructive LODGroup Ingest.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any, Tuple

from .base import EngineBridgeBase

logger = logging.getLogger(__name__)


class UnityLiveBridge(EngineBridgeBase):
    @classmethod
    def get_engine_name(cls) -> str:
        return "Unity 6"

    @classmethod
    def ping_engine(cls, project_dir: str = "") -> Tuple[bool, str]:
        """Checks if target project directory is a valid Unity project."""
        if not project_dir or not os.path.exists(project_dir):
            return False, "⚪ Unity Project Path not configured"
        assets_dir = os.path.join(project_dir, "Assets")
        settings_dir = os.path.join(project_dir, "ProjectSettings")
        if os.path.exists(assets_dir) and os.path.exists(settings_dir):
            postprocessor = os.path.join(assets_dir, "Editor", "OmniMeshUnityPostprocessor.cs")
            if os.path.exists(postprocessor):
                return True, "🟢 Unity Project Ready (Postprocessor Active)"
            return True, "🟡 Unity Project Found (Postprocessor pending install)"
        return False, "⚪ Invalid Unity Project (Missing Assets/ProjectSettings)"

    @classmethod
    def generate_postprocessor_csharp_code(cls) -> str:
        """Generates C# source code for Unity AssetPostprocessor."""
        lines = [
            "#if UNITY_EDITOR",
            "using System;",
            "using System.IO;",
            "using System.Linq;",
            "using UnityEditor;",
            "using UnityEngine;",
            "using UnityEngine.Rendering;",
            "",
            "public class OmniMeshUnityPostprocessor : AssetPostprocessor",
            "{",
            "    private void OnPreprocessModel()",
            "    {",
            '        if (!assetPath.Contains("OmniMesh") && !assetImporter.userData.Contains("OmniMesh"))',
            "            return;",
            "",
            "        ModelImporter modelImporter = (ModelImporter)assetImporter;",
            "        modelImporter.preserveHierarchy = true;",
            "        modelImporter.importBlendShapes = true;",
            "        modelImporter.importVisibility = true;",
            "        modelImporter.materialImportMode = ModelImporterMaterialImportMode.ImportViaMaterialDescription;",
            "        modelImporter.normalCalculationMode = ModelImporterNormalCalculationMode.Unweighted;",
            "    }",
            "",
            "    private void OnPostprocessModel(GameObject root)",
            "    {",
            '        if (!assetPath.Contains("OmniMesh") && !assetImporter.userData.Contains("OmniMesh"))',
            "            return;",
            "",
            "        var lodTransforms = root.GetComponentsInChildren<Transform>()",
            '            .Where(t => System.Text.RegularExpressions.Regex.IsMatch(t.name, @"_LOD\\d+$", System.Text.RegularExpressions.RegexOptions.IgnoreCase))',
            "            .OrderBy(t => t.name)",
            "            .ToList();",
            "",
            "        if (lodTransforms.Count <= 1) return;",
            "",
            "        LODGroup lodGroup = root.GetComponent<LODGroup>() ?? root.AddComponent<LODGroup>();",
            "        LOD[] currentLODs = new LOD[lodTransforms.Count];",
            "",
            "        for (int i = 0; i < lodTransforms.Count; i++)",
            "        {",
            "            var renderers = lodTransforms[i].GetComponentsInChildren<Renderer>();",
            "            float screenTransitionHeight = Mathf.Pow(0.5f, i + 1);",
            "            currentLODs[i] = new LOD(screenTransitionHeight, renderers);",
            "        }",
            "",
            "        lodGroup.SetLODs(currentLODs);",
            "        lodGroup.RecalculateBounds();",
            "        EditorUtility.SetDirty(root);",
            "    }",
            "",
            "    private void OnPostprocessMaterial(Material material)",
            "    {",
            "        string dir = Path.GetDirectoryName(assetPath);",
            '        string texDir = Path.Combine(dir, "Textures");',
            "        if (!Directory.Exists(texDir)) return;",
            "",
            '        string matName = material.name.Replace(" (Instance)", "").Trim();',
            "",
            "        RenderPipelineAsset currentPipeline = GraphicsSettings.currentRenderPipeline;",
            '        string pipelineType = currentPipeline != null ? currentPipeline.GetType().Name : "BuiltIn";',
            "",
            '        if (pipelineType.Contains("Universal") || pipelineType.Contains("URP"))',
            "        {",
            '            material.shader = Shader.Find("Universal Render Pipeline/Lit") ?? material.shader;',
            '            AssignTextureIfExists(material, "_BaseMap", texDir, $"T_{matName}_BaseColor.png");',
            '            AssignTextureIfExists(material, "_MetallicGlossMap", texDir, $"T_{matName}_MaskMap.png");',
            '            AssignTextureIfExists(material, "_BumpMap", texDir, $"T_{matName}_Normal.png");',
            "        }",
            '        else if (pipelineType.Contains("HighDefinition") || pipelineType.Contains("HDRP"))',
            "        {",
            '            material.shader = Shader.Find("HDRP/Lit") ?? material.shader;',
            '            AssignTextureIfExists(material, "_BaseColorMap", texDir, $"T_{matName}_BaseColor.png");',
            '            AssignTextureIfExists(material, "_MaskMap", texDir, $"T_{matName}_MaskMap.png");',
            '            AssignTextureIfExists(material, "_NormalMap", texDir, $"T_{matName}_Normal.png");',
            "        }",
            "    }",
            "",
            "    private static void AssignTextureIfExists(Material mat, string propertyName, string dir, string filename)",
            "    {",
            "        string fullPath = Path.Combine(dir, filename);",
            "        if (!File.Exists(fullPath)) return;",
            "",
            "        string relativePath = \"Assets\" + fullPath.Substring(Application.dataPath.Length).Replace('\\\\', '/');",
            "        Texture2D tex = AssetDatabase.LoadAssetAtPath<Texture2D>(relativePath);",
            "        if (tex != null && mat.HasProperty(propertyName))",
            "        {",
            "            mat.SetTexture(propertyName, tex);",
            "        }",
            "    }",
            "}",
            "#endif",
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def install_companion_scripts(cls, project_dir: str) -> Tuple[bool, str]:
        """Installs OmniMeshUnityPostprocessor.cs into Assets/Editor/."""
        if not project_dir or not os.path.exists(project_dir):
            return False, "Unity Project directory does not exist."

        editor_dir = os.path.join(project_dir, "Assets", "Editor")
        os.makedirs(editor_dir, exist_ok=True)

        target_file = os.path.join(editor_dir, "OmniMeshUnityPostprocessor.cs")
        try:
            with open(target_file, "w", encoding="utf-8") as f:
                f.write(cls.generate_postprocessor_csharp_code())
            return True, f"Installed Unity Postprocessor to {target_file}"
        except OSError as e:
            return False, f"Failed to write C# postprocessor: {str(e)}"

    @classmethod
    def sync_asset(
        cls,
        context: Any,
        export_dir: str,
        asset_name: str,
        project_dir: str = "",
    ) -> Tuple[bool, str]:
        if not project_dir or not os.path.exists(project_dir):
            return False, "Target Unity project directory not configured."

        cls.install_companion_scripts(project_dir)

        target_import_dir = os.path.join(project_dir, "Assets", "OmniMesh_Exports", asset_name)
        os.makedirs(target_import_dir, exist_ok=True)

        src_fbx = os.path.join(export_dir, f"{asset_name}.fbx")
        if os.path.exists(src_fbx):
            shutil.copy2(src_fbx, os.path.join(target_import_dir, f"{asset_name}.fbx"))

        src_tex_dir = os.path.join(export_dir, "Textures")
        if os.path.exists(src_tex_dir):
            dest_tex_dir = os.path.join(target_import_dir, "Textures")
            os.makedirs(dest_tex_dir, exist_ok=True)
            for f in os.listdir(src_tex_dir):
                shutil.copy2(os.path.join(src_tex_dir, f), os.path.join(dest_tex_dir, f))

        return True, f"Synced {asset_name} and textures to Unity project at {target_import_dir}"
