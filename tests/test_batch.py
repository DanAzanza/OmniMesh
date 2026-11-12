"""
Unit tests for OmniMesh Batch Library Ingest Engine and Blend Discovery.
Covers asset discovery, blend file filtering, mirrored hierarchy synthesis,
and UNC network path normalization.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast

from core.batch import BatchProcessorEngine
from tests.conftest import MockBlendData
from core.batch_worker_process import (
    WorkerProcessHandle,
    build_hierarchical_export_path,
    normalize_export_path_for_cli,
)


def test_batch_processor_discover_assets_empty():
    assert BatchProcessorEngine.discover_assets("") == []
    assert BatchProcessorEngine.discover_assets("non_existent_folder_xyz_123") == []


def test_batch_processor_discover_assets_filtering(tmp_path: Path):
    sub_dir = tmp_path / "Props"
    sub_dir.mkdir(parents=True, exist_ok=True)

    f1 = tmp_path / "ModelA.fbx"
    f2 = tmp_path / "ModelB.obj"
    f3 = sub_dir / "ModelC.gltf"
    f4 = sub_dir / "ModelD.glb"
    f_ignore = sub_dir / "Texture.png"
    f_ignore_txt = tmp_path / "readme.txt"

    for p in (f1, f2, f3, f4, f_ignore, f_ignore_txt):
        p.write_text("test", encoding="utf-8")

    # Recursive scan
    discovered_rec = BatchProcessorEngine.discover_assets(str(tmp_path), recursive=True)
    assert len(discovered_rec) == 4
    assert os.path.abspath(str(f1)) in discovered_rec
    assert os.path.abspath(str(f2)) in discovered_rec
    assert os.path.abspath(str(f3)) in discovered_rec
    assert os.path.abspath(str(f4)) in discovered_rec

    # Non-recursive scan
    discovered_flat = BatchProcessorEngine.discover_assets(str(tmp_path), recursive=False)
    assert len(discovered_flat) == 2
    assert os.path.abspath(str(f1)) in discovered_flat
    assert os.path.abspath(str(f2)) in discovered_flat


def test_batch_processor_single_asset_no_bpy():
    res = BatchProcessorEngine.process_single_asset(
        context=None,
        filepath="dummy_path.fbx",
        export_base_dir="dummy_export",
        blend_data=MockBlendData(),
    )
    assert res["success"] is False
    assert "Blender" in res["message"] or "not available" in res["message"]


def test_batch_processor_import_asset_file_guards():
    bdata = MockBlendData()
    assert BatchProcessorEngine.import_asset_file("", blend_data=bdata) == []
    assert BatchProcessorEngine.import_asset_file("non_existent_path.fbx", blend_data=bdata) == []


def test_batch_processor_cleanup_imported_objects():
    bdata = MockBlendData()
    # Should not throw on empty/None
    BatchProcessorEngine.cleanup_imported_objects([], blend_data=bdata)
    empty_obj = type("MockEmpty", (), {"name": "EmptyObj", "type": "EMPTY", "data": None})()
    BatchProcessorEngine.cleanup_imported_objects(cast(Any, [None, empty_obj]), blend_data=bdata)

    # Test explicit BlendData dependency injection cleanup
    bdata = MockBlendData()
    mesh_data = type("MockMeshData", (), {"name": "CubeMesh"})()
    bdata.meshes._items["CubeMesh"] = mesh_data

    obj = type("MockObj", (), {"name": "CubeObj", "type": "MESH", "data": mesh_data})()
    bdata.objects._items["CubeObj"] = obj

    BatchProcessorEngine.cleanup_imported_objects(cast(Any, [obj]), blend_data=bdata)
    assert "CubeObj" not in bdata.objects
    assert "CubeMesh" not in bdata.meshes


def test_discover_blend_files_recursive(tmp_path: Path):
    source_dir = tmp_path / "Source"
    source_dir.mkdir(parents=True)

    # Create nested blend files
    prop_dir = source_dir / "Props" / "Chairs"
    prop_dir.mkdir(parents=True)
    (prop_dir / "chair1.blend").write_text("", encoding="utf-8")
    (prop_dir / "chair2.blend").write_text("", encoding="utf-8")

    veh_dir = source_dir / "Vehicles"
    veh_dir.mkdir(parents=True)
    (veh_dir / "car.blend").write_text("", encoding="utf-8")

    # Create lock/backup files that MUST be ignored
    (prop_dir / "chair1.blend1").write_text("", encoding="utf-8")
    (prop_dir / "chair1.blend2").write_text("", encoding="utf-8")
    (prop_dir / ".~chair1.blend").write_text("", encoding="utf-8")
    (veh_dir / ".car.blend").write_text("", encoding="utf-8")
    (veh_dir / "car.blend@").write_text("", encoding="utf-8")
    (veh_dir / "car.fbx").write_text("", encoding="utf-8")

    files = BatchProcessorEngine.discover_blend_files(str(source_dir), recursive=True)
    assert len(files) == 3
    basenames = sorted(os.path.basename(f) for f in files)
    assert basenames == ["car.blend", "chair1.blend", "chair2.blend"]


def test_discover_ignores_export_folder_if_nested(tmp_path: Path):
    source_dir = tmp_path / "Source"
    source_dir.mkdir(parents=True)

    nested_export = source_dir / "Exported_Packages"
    nested_export.mkdir(parents=True)
    (nested_export / "exported_asset.blend").write_text("", encoding="utf-8")

    real_asset = source_dir / "model.blend"
    real_asset.write_text("", encoding="utf-8")

    files = BatchProcessorEngine.discover_blend_files(str(source_dir), recursive=True, export_dir=str(nested_export))
    assert len(files) == 1
    assert os.path.basename(files[0]) == "model.blend"


def test_compute_mirrored_export_path(tmp_path: Path):
    source_dir = tmp_path / "Source"
    export_dir = tmp_path / "Export"
    source_dir.mkdir(parents=True)
    export_dir.mkdir(parents=True)

    blend_file = source_dir / "Characters" / "Hero (Armor)" / "warrior.blend"
    blend_file.parent.mkdir(parents=True)
    blend_file.write_text("", encoding="utf-8")

    target_dir, asset_name = BatchProcessorEngine.compute_mirrored_export_path(
        str(blend_file), str(source_dir), str(export_dir)
    )

    expected_sub = os.path.join("Characters", "Hero__Armor_")
    assert target_dir.endswith(expected_sub) or target_dir.endswith(expected_sub.replace("/", "\\"))
    assert asset_name == "warrior"


def test_compute_mirrored_export_path_root_file(tmp_path: Path):
    source_dir = tmp_path / "Source"
    export_dir = tmp_path / "Export"
    source_dir.mkdir(parents=True)
    export_dir.mkdir(parents=True)

    blend_file = source_dir / "single_prop.blend"
    blend_file.write_text("", encoding="utf-8")

    target_dir, asset_name = BatchProcessorEngine.compute_mirrored_export_path(
        str(blend_file), str(source_dir), str(export_dir)
    )

    assert os.path.normpath(target_dir) == os.path.normpath(str(export_dir))
    assert asset_name == "single_prop"


def test_batch_worker_script_exists():
    """Verify scripts/batch_worker.py exists and can be located."""
    repo_root = Path(__file__).parent.parent
    script_path = repo_root / "scripts" / "batch_worker.py"
    assert script_path.is_file(), f"scripts/batch_worker.py must exist, found at: {script_path}"


def test_batch_worker_unc_path_normalization():
    """Verify that normalize_export_path_for_cli preserves Windows UNC double backslash prefixes."""
    # Windows UNC network path
    unc_path = r"\\storage_server\omnimesh\exports"
    normalized_unc = normalize_export_path_for_cli(unc_path)
    assert normalized_unc.startswith(r"\\"), f"UNC path must retain leading double backslash, got {normalized_unc}"
    assert not normalized_unc.startswith("//"), "UNC path must not be converted to Blender blend-relative '//'"

    # Standard drive path
    drive_path = r"C:\OmniMesh\Exports\Asset1"
    normalized_drive = normalize_export_path_for_cli(drive_path)
    assert normalized_drive == "C:/OmniMesh/Exports/Asset1"


def test_batch_hierarchical_export_path():
    """Verify build_hierarchical_export_path mirrors directory hierarchy and sanitizes asset names across OS path styles."""
    # Windows-style path test
    source_root_win = r"C:\Projects\Assets"
    blend_path_win = r"C:\Projects\Assets\Props\Hero Asset 01.blend"
    export_root_win = r"D:\Build\GameAssets"

    target_dir_w, asset_name_w = build_hierarchical_export_path(blend_path_win, source_root_win, export_root_win)
    assert asset_name_w == "Hero_Asset_01"
    assert "Props" in target_dir_w

    # POSIX-style path test
    source_root_posix = "/projects/assets"
    blend_path_posix = "/projects/assets/Props/Hero Asset 01.blend"
    export_root_posix = "/build/gameassets"

    target_dir_p, asset_name_p = build_hierarchical_export_path(blend_path_posix, source_root_posix, export_root_posix)
    assert asset_name_p == "Hero_Asset_01"
    assert "Props" in target_dir_p


class DummyPopen:
    """Mock process object satisfying subprocess.Popen interface for worker tests."""

    def __init__(self, pid: int = 4242, returncode: int | None = None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.killed = False
        self.terminated = False
        self.waited_timeout: float | None = None
        self.stderr = None
        self.stdout = None

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.waited_timeout = timeout
        return self.returncode or 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def test_worker_process_handle_lifecycle(tmp_path: Path):
    """Verify WorkerProcessHandle forwards lifecycle commands and safely manages log handles."""
    log_file_path = tmp_path / "worker_test.log"
    log_file_path.write_text("Line 1\nLine 2\nCritical error details\n", encoding="utf-8")

    f = open(log_file_path, "a", encoding="utf-8")
    dummy_proc = DummyPopen(pid=9999, returncode=None)

    handle = WorkerProcessHandle(
        proc=cast(Any, dummy_proc),
        log_file=f,
        log_path=str(log_file_path),
    )

    assert handle.pid == 9999
    assert handle.returncode is None
    assert handle.poll() is None
    assert handle._om_log_file is f
    assert handle._om_log_path == str(log_file_path)

    # Tail reading
    tail = handle.read_log_tail(max_lines=2)
    assert "Critical error details" in tail

    # Termination
    handle.terminate()
    assert dummy_proc.terminated is True
    assert handle.returncode == -15

    # Safe log closure
    assert not f.closed
    handle.close_log()
    assert f.closed
    assert handle.log_file is None

    # Idempotent close
    handle.close_log()


def test_worker_process_handle_edge_cases(tmp_path: Path):
    """Verify WorkerProcessHandle behavior when log file is None or missing."""
    dummy_proc = DummyPopen(pid=1234, returncode=0)
    handle = WorkerProcessHandle(
        proc=cast(Any, dummy_proc),
        log_file=None,
        log_path=str(tmp_path / "non_existent.log"),
    )

    assert handle.poll() == 0
    assert handle.wait(timeout=2.0) == 0
    assert dummy_proc.waited_timeout == 2.0
    assert handle.read_log_tail() == ""

    # close_log with None file
    handle.close_log()
    assert handle.log_file is None


def test_batch_processor_get_exporter_lazy_load_and_fallback(monkeypatch):
    """Verify _get_exporter pops failed engine and returns None on ImportError."""
    from unittest.mock import MagicMock
    import builtins

    orig_import = builtins.__import__

    def faulty_import(name, *args, **kwargs):
        if "exporters" in name:
            raise ImportError(f"Simulated missing exporter module: {name}")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", faulty_import)

    # Pre-populate with dummy to verify pop works on failure
    BatchProcessorEngine._exporters["MSFS_2024"] = MagicMock()
    del BatchProcessorEngine._exporters["MSFS_2024"]

    exporter = BatchProcessorEngine._get_exporter("MSFS_2024")
    assert exporter is None
    assert "MSFS_2024" not in BatchProcessorEngine._exporters
