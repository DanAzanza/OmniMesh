"""
Unit tests for OmniMesh Multi-Engine Live Bridge Subsystem.
"""

from __future__ import annotations

import os
import tempfile
from bridges.godot_bridge import GodotLiveBridge
from bridges.manager import BridgeManager
from bridges.msfs_bridge import MSFS2024LiveBridge
from bridges.unity_bridge import UnityLiveBridge
from bridges.unreal_bridge import UnrealLiveBridge


def test_bridge_manager_registry():
    assert BridgeManager.get_bridge("UE5") is UnrealLiveBridge
    assert BridgeManager.get_bridge("UNITY_6") is UnityLiveBridge
    assert BridgeManager.get_bridge("MSFS_2024") is MSFS2024LiveBridge
    assert BridgeManager.get_bridge("GODOT_4") is GodotLiveBridge
    assert BridgeManager.get_bridge("UNKNOWN_ENGINE") is None


def test_unreal_payload_generation_posix_paths():
    fbx_win_path = r"C:\Users\Artist\MyProject\Export\SM_HeroAsset.fbx"
    tex_dict = {
        "ORMMap": r"C:\Users\Artist\MyProject\Export\Textures\T_Hero_ORM.png",
        "NormalMap": r"C:\Users\Artist\MyProject\Export\Textures\T_Hero_Normal_DirectX.png",
    }
    payload = UnrealLiveBridge.build_non_destructive_ingest_payload(
        fbx_win_path, "/Game/Vehicles", "SM_HeroAsset", texture_dict=tex_dict
    )

    # Must contain POSIX forward slashes only (no backslash syntax traps)
    assert "C:/Users/Artist/MyProject/Export/SM_HeroAsset.fbx" in payload
    assert "options.import_materials = False" in payload
    assert "options.create_physics_asset = False" in payload
    assert "options.static_mesh_import_data.auto_generate_collision = False" in payload
    assert "MI_SM_HeroAsset" in payload
    assert "M_OmniMesh_Master" in payload


def test_unreal_ping_offline():
    # Pinging offline port should gracefully return False without exception
    is_live = UnrealLiveBridge.ping_remote_execution(port=59999, timeout_sec=0.1)
    assert is_live is False
    status, msg = UnrealLiveBridge.ping_engine()
    assert isinstance(status, bool)
    assert isinstance(msg, str)


def test_unity_csharp_postprocessor_generation():
    cs_code = UnityLiveBridge.generate_postprocessor_csharp_code()
    assert "class OmniMeshUnityPostprocessor : AssetPostprocessor" in cs_code
    assert "LODGroup" in cs_code
    assert "Universal Render Pipeline/Lit" in cs_code
    assert "HDRP/Lit" in cs_code
    assert "_MaskMap" in cs_code


def test_unity_install_companion_scripts():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Valid Unity project structure
        os.makedirs(os.path.join(tmpdir, "Assets"))
        os.makedirs(os.path.join(tmpdir, "ProjectSettings"))

        ok, msg = UnityLiveBridge.install_companion_scripts(tmpdir)
        assert ok is True

        cs_path = os.path.join(tmpdir, "Assets", "Editor", "OmniMeshUnityPostprocessor.cs")
        assert os.path.exists(cs_path)

        ping_ok, ping_msg = UnityLiveBridge.ping_engine(tmpdir)
        assert ping_ok is True
        assert "Active" in ping_msg


def test_godot_gdscript_post_import_generation():
    gd_code = GodotLiveBridge.generate_post_import_gdscript()
    assert "@tool" in gd_code
    assert "extends EditorScenePostImport" in gd_code
    assert "visibility_range_begin" in gd_code
    assert "visibility_range_end" in gd_code
    assert "VISIBILITY_RANGE_FADE_SELF" in gd_code


def test_godot_install_companion_scripts():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create project.godot
        with open(os.path.join(tmpdir, "project.godot"), "w", encoding="utf-8") as f:
            f.write("; Godot project configuration\n")

        ok, msg = GodotLiveBridge.install_companion_scripts(tmpdir)
        assert ok is True

        gd_path = os.path.join(tmpdir, "addons", "omnimesh", "OmniMeshPostImport.gd")
        assert os.path.exists(gd_path)

        ping_ok, ping_msg = GodotLiveBridge.ping_engine(tmpdir)
        assert ping_ok is True
        assert "Active" in ping_msg


def test_msfs_locate_tool():
    # Resolving tool should return None or path string without crashing
    exe = MSFS2024LiveBridge.locate_fspackagetool()
    assert exe is None or isinstance(exe, str)


def test_msfs_locate_tool_env_var(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_bin_dir = os.path.join(tmpdir, "Tools", "bin")
        os.makedirs(fake_bin_dir)
        fake_exe = os.path.join(fake_bin_dir, "fspackagetool.exe")
        with open(fake_exe, "w", encoding="utf-8") as f:
            f.write("mock")

        monkeypatch.setenv("MSFS2024_SDK", tmpdir)
        found = MSFS2024LiveBridge.locate_fspackagetool()
        assert found == fake_exe

        ping_ok, ping_msg = MSFS2024LiveBridge.ping_engine()
        assert ping_ok is True
        assert "Found" in ping_msg


def test_bridge_manager_unknown_engine():
    assert BridgeManager.ping_engine("NON_EXISTENT")[0] is False
    assert BridgeManager.install_companion_scripts("NON_EXISTENT", "/tmp")[0] is False
    assert BridgeManager.sync_asset(None, "NON_EXISTENT", "/tmp", "Asset")[0] is False


def test_unity_sync_asset_validation():
    # Missing project dir
    ok, msg = UnityLiveBridge.sync_asset(None, "/fake/export", "SM_Test", "")
    assert ok is False
    assert "not configured" in msg

    # Missing export dir
    with tempfile.TemporaryDirectory() as proj_dir:
        os.makedirs(os.path.join(proj_dir, "Assets"))
        ok, msg = UnityLiveBridge.sync_asset(None, "/fake/nonexistent/export", "SM_Test", proj_dir)
        assert ok is False
        assert "not found" in msg

    # Missing FBX in export dir
    with tempfile.TemporaryDirectory() as proj_dir:
        with tempfile.TemporaryDirectory() as exp_dir:
            os.makedirs(os.path.join(proj_dir, "Assets"))
            ok, msg = UnityLiveBridge.sync_asset(None, exp_dir, "SM_Test", proj_dir)
            assert ok is False
            assert "Exported FBX not found" in msg

    # Full success sync
    with tempfile.TemporaryDirectory() as proj_dir:
        with tempfile.TemporaryDirectory() as exp_dir:
            os.makedirs(os.path.join(proj_dir, "Assets"))
            fbx_path = os.path.join(exp_dir, "SM_Test.fbx")
            with open(fbx_path, "wb") as f:
                f.write(b"FBXDATA")

            tex_dir = os.path.join(exp_dir, "Textures")
            os.makedirs(tex_dir)
            with open(os.path.join(tex_dir, "T_SM_Test_MaskMap.png"), "wb") as f:
                f.write(b"PNGDATA")

            ok, msg = UnityLiveBridge.sync_asset(None, exp_dir, "SM_Test", proj_dir)
            assert ok is True
            assert "Synced SM_Test" in msg
            dest_fbx = os.path.join(proj_dir, "Assets", "OmniMesh_Exports", "SM_Test", "SM_Test.fbx")
            assert os.path.exists(dest_fbx)
            dest_tex = os.path.join(
                proj_dir, "Assets", "OmniMesh_Exports", "SM_Test", "Textures", "T_SM_Test_MaskMap.png"
            )
            assert os.path.exists(dest_tex)


def test_godot_sync_asset_validation():
    # Missing project dir
    ok, msg = GodotLiveBridge.sync_asset(None, "/fake/export", "SM_Godot", "")
    assert ok is False
    assert "not configured" in msg

    # Missing export dir
    with tempfile.TemporaryDirectory() as proj_dir:
        ok, msg = GodotLiveBridge.sync_asset(None, "/fake/nonexistent", "SM_Godot", proj_dir)
        assert ok is False
        assert "not found" in msg

    # No glTF in export dir
    with tempfile.TemporaryDirectory() as proj_dir:
        with tempfile.TemporaryDirectory() as exp_dir:
            ok, msg = GodotLiveBridge.sync_asset(None, exp_dir, "SM_Godot", proj_dir)
            assert ok is False
            assert "No glTF/GLB models found" in msg

    # Successful sync
    with tempfile.TemporaryDirectory() as proj_dir:
        with tempfile.TemporaryDirectory() as exp_dir:
            gltf_file = os.path.join(exp_dir, "SM_Godot.gltf")
            with open(gltf_file, "w", encoding="utf-8") as f:
                f.write('{"asset": {}}')

            ok, msg = GodotLiveBridge.sync_asset(None, exp_dir, "SM_Godot", proj_dir)
            assert ok is True
            assert "Synced glTF asset" in msg
            dest_gltf = os.path.join(proj_dir, "OmniMesh_Exports", "SM_Godot", "SM_Godot.gltf")
            assert os.path.exists(dest_gltf)
            dest_script = os.path.join(proj_dir, "addons", "omnimesh", "OmniMeshPostImport.gd")
            assert os.path.exists(dest_script)
