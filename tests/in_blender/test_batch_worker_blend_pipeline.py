"""In-Blender Integration Tests for Batch Mesh Iteration, Worker Processes, and .blend File Discovery."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import TYPE_CHECKING, Any, cast
import unittest

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import bpy
    from tests.in_blender.fixtures import in_blender_sandbox
else:
    try:
        import bpy
        from tests.in_blender.fixtures import in_blender_sandbox
    except ImportError:
        bpy = None
        in_blender_sandbox = None  # type: ignore

try:
    from core.batch import BatchProcessorEngine
    from core.batch_iterator import BatchMeshIterator, BatchProgress
    from core.batch_worker_process import (
        WorkerProcessHandle,
        build_hierarchical_export_path,
        normalize_export_path_for_cli,
    )
except (ImportError, ValueError):
    from core.batch import BatchProcessorEngine
    from core.batch_iterator import BatchMeshIterator, BatchProgress
    from core.batch_worker_process import (
        WorkerProcessHandle,
        build_hierarchical_export_path,
        normalize_export_path_for_cli,
    )


class TestBatchWorkerBlendPipeline(unittest.TestCase):
    """Verify batch iteration across mesh objects, blend file discovery, and worker process lifecycle."""

    def setUp(self) -> None:
        if not bpy:
            self.skipTest("Blender bpy runtime not available.")

    def test_batch_mesh_iterator_execution(self) -> None:
        """Verify BatchMeshIterator simplifies objects iteratively and yields progress snapshots."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            import bmesh

            # Create 3 test mesh objects with distinct densities
            test_objs = []
            for i in range(3):
                mesh = bpy.data.meshes.new(f"BatchMesh_{i}")
                obj = bpy.data.objects.new(f"BatchObj_{i}", mesh)
                scene.collection.objects.link(obj)

                bm = bmesh.new()
                # Create icosphere for sufficient polygons to decimate
                bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
                bm.to_mesh(mesh)
                bm.free()
                mesh.update()
                test_objs.append(obj)

            iterator = BatchMeshIterator(
                objects=test_objs,
                target_ratio=0.5,
                preserve_boundaries=True,
                planar_dissolve=False,
            )

            progress_steps: list[BatchProgress] = []
            for step in iterator.iterate(context=bpy.context, blend_data=bpy.data):
                progress_steps.append(step)

            self.assertEqual(len(progress_steps), 3)
            for step in progress_steps:
                self.assertTrue(step.success, f"Step failed: {step.error_message}")
                self.assertGreater(step.initial_tris, 0)
                self.assertLessEqual(step.final_tris, step.initial_tris)

    def test_discover_blend_files_in_directory(self) -> None:
        """Verify BatchProcessorEngine.discover_blend_files ignores locks, backups, and nested export dirs."""
        with in_blender_sandbox() as scene:
            if scene is None or bpy is None:
                return

            with tempfile.TemporaryDirectory() as tmp_dir:
                root_path = Path(tmp_dir)
                export_path = root_path / "Exports"
                export_path.mkdir()

                # Create valid .blend, backup .blend1, and lock .blend@ files
                valid_1 = root_path / "Prop_AssetA.blend"
                valid_2 = root_path / "Subfolder" / "Prop_AssetB.blend"
                valid_2.parent.mkdir()
                backup_file = root_path / "Prop_AssetA.blend1"
                lock_file = root_path / "Prop_AssetA.blend@"
                nested_export_blend = export_path / "IgnoredExport.blend"

                for f in (valid_1, valid_2, backup_file, lock_file, nested_export_blend):
                    f.write_text("DummyBlendHeader", encoding="utf-8")

                discovered = BatchProcessorEngine.discover_blend_files(
                    str(root_path),
                    recursive=True,
                    export_dir=str(export_path),
                )

                norm_discovered = [os.path.normpath(p) for p in discovered]
                self.assertIn(os.path.normpath(str(valid_1)), norm_discovered)
                self.assertIn(os.path.normpath(str(valid_2)), norm_discovered)
                self.assertNotIn(os.path.normpath(str(backup_file)), norm_discovered)
                self.assertNotIn(os.path.normpath(str(lock_file)), norm_discovered)
                self.assertNotIn(os.path.normpath(str(nested_export_blend)), norm_discovered)

    def test_batch_worker_path_normalization_and_hierarchy(self) -> None:
        """Verify path normalization preserves UNC shares and derives subfolder hierarchies."""
        # Test UNC normalization
        unc_path = r"\\TerminalServer\Projects\Aircraft\LODs"
        norm_unc = normalize_export_path_for_cli(unc_path)
        self.assertTrue(norm_unc.startswith(r"\\TerminalServer"))

        # Test standard path normalization
        std_path = r"C:\Work\Games\Prop"
        norm_std = normalize_export_path_for_cli(std_path)
        self.assertIn("/", norm_std)

        # Test hierarchical export path derivation
        source_root = r"C:/Projects/Game/Assets"
        blend_file = r"C:/Projects/Game/Assets/Props/Vehicles/Truck.blend"
        export_root = r"D:/Export"

        target_dir, asset_name = build_hierarchical_export_path(blend_file, source_root, export_root)
        self.assertEqual(asset_name, "Truck")
        self.assertIn("Props", target_dir)
        self.assertIn("Vehicles", target_dir)

    def test_worker_process_handle_lifecycle_simulation(self) -> None:
        """Verify WorkerProcessHandle correctly tracks state, PID, return code, and streams."""
        # Spawn a brief echo process to verify WorkerProcessHandle contract
        dummy_proc = subprocess.Popen(
            [sys.executable, "-c", "print('OmniMeshWorkerStarted')"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        with tempfile.NamedTemporaryFile("w+", delete=False) as log_f:
            log_path = log_f.name
            handle = WorkerProcessHandle(
                proc=dummy_proc,
                log_file=cast(Any, log_f),
                log_path=log_path,
            )

            self.assertGreater(handle.pid, 0)
            ret = handle.wait(timeout=5.0)
            self.assertEqual(ret, 0)
            self.assertEqual(handle.returncode, 0)
            self.assertEqual(handle._om_log_path, log_path)

        try:
            os.remove(log_path)
        except OSError:
            pass
