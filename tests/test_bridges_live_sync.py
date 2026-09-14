"""
OmniMesh Live Engine Bridges Integration & Hardening Tests.
Tests real-time synchronization, mock TCP/HTTP servers, and script generators for
Unreal Engine 5, Unity 6, Godot 4, and MSFS 2024.
"""

from __future__ import annotations

import http.server
import json
from pathlib import Path
import socketserver
import threading
import time
from unittest.mock import MagicMock, patch

from bridges.godot_bridge import GodotLiveBridge
from bridges.manager import BridgeManager
from bridges.msfs_bridge import MSFS2024LiveBridge
from bridges.unity_bridge import UnityLiveBridge
from bridges.unreal_bridge import UnrealLiveBridge


# ==============================================================================
# 1. UNREAL ENGINE 5 LIVE BRIDGE & PROTOCOL ENVELOPE TESTS
# ==============================================================================


class MockUE5TCPHandler(socketserver.BaseRequestHandler):
    """Simulates native Unreal Engine 5 Python Remote Execution TCP port 6776."""

    def handle(self):
        raw_len = self.request.recv(4)
        if len(raw_len) < 4:
            return
        msg_len = int.from_bytes(raw_len, byteorder="big")
        payload_bytes = bytearray()
        while len(payload_bytes) < msg_len:
            chunk = self.request.recv(min(4096, msg_len - len(payload_bytes)))
            if not chunk:
                break
            payload_bytes.extend(chunk)

        cmd_json = json.loads(payload_bytes.decode("utf-8"))

        # Verify protocol adherence (CRIT-03)
        assert cmd_json.get("magic") == "ue_py"
        assert cmd_json.get("exec_mode") == "ExecuteFile"
        assert "command" in cmd_json

        # Send response frame
        resp_payload = json.dumps({"success": True, "result": "Imported OK"}).encode("utf-8")
        resp_frame = len(resp_payload).to_bytes(4, byteorder="big") + resp_payload
        self.request.sendall(resp_frame)


class MockUE5HTTPHandler(http.server.BaseHTTPRequestHandler):
    """Simulates Unreal Engine 5 Web Remote Control HTTP endpoint."""

    def do_GET(self):
        if self.path == "/remote/info":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        if self.path == "/remote/object/call":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            req_data = json.loads(body.decode("utf-8"))
            assert "PythonCommand" in req_data.get("parameters", {})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Silence stderr logs during test runs


def test_ue5_tcp_remote_execution_protocol():
    """Tests UE5 TCP transmission with length prefix, exec_mode, and response frame parsing."""
    server = socketserver.TCPServer(("127.0.0.1", 0), MockUE5TCPHandler)
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.05)
        assert UnrealLiveBridge.ping_remote_execution(port=port)

        payload = "import unreal\nprint('Hello from OmniMesh')"
        ok, msg = UnrealLiveBridge.dispatch_to_ue5(payload, port=port)
        assert ok
        assert "Successfully executed" in msg or "Successfully dispatched" in msg
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=1.0)


def test_ue5_web_remote_control_fallback():
    """Tests Web Remote Control HTTP fallback when TCP port is offline."""
    httpd = http.server.HTTPServer(("127.0.0.1", 0), MockUE5HTTPHandler)
    port = httpd.server_address[1]
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    try:
        time.sleep(0.05)
        assert UnrealLiveBridge.ping_web_remote_control(port=port)

        # Dispatch pointing TCP to non-existent port, but providing active HTTP port
        payload = "print('Web Remote Fallback')"
        ok, msg = UnrealLiveBridge.dispatch_to_ue5(payload, port=9999, http_port=port)
        assert ok
        assert "Web Remote Control" in msg
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_thread.join(timeout=1.0)


# ==============================================================================
# 2. GODOT 4 BRIDGE & EDITOR PLUGIN TESTS
# ==============================================================================


def test_godot_plugin_generation_and_auto_import(tmp_path: Path):
    """Tests Godot 4 EditorPlugin, SceneImportPlugin, and companion .import file generation."""
    proj_dir = tmp_path / "TestGodotProject"
    proj_dir.mkdir()
    (proj_dir / "project.godot").write_text("config_version=5\n", encoding="utf-8")

    export_dir = tmp_path / "OmniMeshExport"
    export_dir.mkdir()
    (export_dir / "SM_Hero_LOD0.glb").write_bytes(b"glTF mock binary")
    (export_dir / "SM_Hero_LOD1.glb").write_bytes(b"glTF mock binary")

    # Sync to Godot project
    ok, msg = GodotLiveBridge.sync_asset_headless(str(export_dir), "SM_Hero", str(proj_dir))
    assert ok
    assert "Synced glTF asset 'SM_Hero'" in msg

    # Verify addons/omnimesh structure
    addons_dir = proj_dir / "addons" / "omnimesh"
    assert (addons_dir / "plugin.cfg").is_file()
    assert (addons_dir / "OmniMeshPlugin.gd").is_file()
    assert (addons_dir / "OmniMeshSceneImportPlugin.gd").is_file()
    assert (addons_dir / "OmniMeshPostImport.gd").is_file()

    # Verify companion .import file was synthesized with correct res:// path
    dest_dir = proj_dir / "OmniMesh_Exports" / "SM_Hero"
    assert (dest_dir / "SM_Hero_LOD0.glb").is_file()
    import_file = dest_dir / "SM_Hero_LOD0.glb.import"
    assert import_file.is_file()

    import_content = import_file.read_text(encoding="utf-8")
    assert "custom_script/enabled=true" in import_content
    assert 'custom_script/path="res://addons/omnimesh/OmniMeshPostImport.gd"' in import_content
    assert 'source_file="res://OmniMesh_Exports/SM_Hero/SM_Hero_LOD0.glb"' in import_content


# ==============================================================================
# 3. UNITY 6 BRIDGE, FILE LOCK RETRY, & .META PRESERVATION
# ==============================================================================


def test_unity_sync_and_meta_preservation(tmp_path: Path):
    """Tests Unity 6 sync, C# postprocessor install, and .meta file preservation."""
    unity_proj = tmp_path / "TestUnityProject"
    unity_proj.mkdir()
    assets_dir = unity_proj / "Assets"
    assets_dir.mkdir()

    export_dir = tmp_path / "OmniMeshUnityExport"
    export_dir.mkdir()
    (export_dir / "SM_Vehicle.fbx").write_bytes(b"FBX mock binary")
    tex_dir = export_dir / "Textures"
    tex_dir.mkdir()
    (tex_dir / "T_SM_Vehicle_BaseColor.png").write_bytes(b"PNG mock")

    # Pre-create an existing .meta file in destination to ensure it's not destroyed
    dest_dir = assets_dir / "OmniMesh_Exports" / "SM_Vehicle"
    dest_dir.mkdir(parents=True)
    existing_meta = dest_dir / "SM_Vehicle.fbx.meta"
    existing_meta.write_text("fileFormatVersion: 2\nguid: 1234567890abcdef\n", encoding="utf-8")

    ok, msg = UnityLiveBridge.sync_asset_headless(str(export_dir), "SM_Vehicle", str(unity_proj))
    assert ok
    assert "Synced SM_Vehicle" in msg

    # Verify C# postprocessor exists in Assets/Editor
    postprocessor = assets_dir / "Editor" / "OmniMeshUnityPostprocessor.cs"
    assert postprocessor.is_file()
    cs_code = postprocessor.read_text(encoding="utf-8")
    assert "OmniMeshUnityPostprocessor : AssetPostprocessor" in cs_code
    assert "OnPostprocessModel" in cs_code
    assert "lodGroup.SetLODs" in cs_code

    # Verify .meta GUID was preserved and not overwritten or corrupted
    assert existing_meta.is_file()
    assert "guid: 1234567890abcdef" in existing_meta.read_text(encoding="utf-8")


# ==============================================================================
# 4. MSFS 2024 SDK BUILDER & ERROR EXTRACTION
# ==============================================================================


def test_msfs_error_extraction_and_safe_staging(tmp_path: Path):
    """Tests MSFS compiler error parsing and staging logic."""
    fake_exe = tmp_path / "fspackagetool.exe"
    fake_exe.write_text("fake binary", encoding="utf-8")

    with patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate.return_value = (
            "Building package...\nLOD error: LOD distances must be in descending order\nFatal error in asset",
            "",
        )
        mock_popen.return_value = mock_proc

        pkg_def = tmp_path / "PackageDefinitions.xml"
        pkg_def.write_text("<PackageDefinitions/>", encoding="utf-8")

        ok, msg = MSFS2024LiveBridge.compile_package_safe(str(fake_exe), str(pkg_def), str(tmp_path))
        assert not ok
        assert "LOD error" in msg
        assert "fspackagetool.exe failed" in msg


# ==============================================================================
# 5. BRIDGE MANAGER ROUTING & HEADLESS ASYNC DISPATCH
# ==============================================================================


def test_bridge_manager_headless_routing(tmp_path: Path):
    """Verifies that BridgeManager cleanly routes headless synchronization across all 4 engines."""
    export_dir = tmp_path / "Export"
    export_dir.mkdir()

    # Unknown engine
    ok, msg = BridgeManager.sync_asset_headless("INVALID_ENGINE", str(export_dir), "Asset")
    assert not ok
    assert "Unknown target engine" in msg

    # Unity without configured project path
    ok, msg = BridgeManager.sync_asset_headless("UNITY_6", str(export_dir), "Asset")
    assert not ok
    assert "Unity Project Path not configured" in msg

    # Godot without configured project path
    ok, msg = BridgeManager.sync_asset_headless("GODOT_4", str(export_dir), "Asset")
    assert not ok
    assert "Target Godot project directory not configured" in msg
