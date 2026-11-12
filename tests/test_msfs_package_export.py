"""
Unit tests for MSFSExporter.export_package.
Validates multi-LOD packaging, aircraft vs. scenery options, variant export,
and negative boundary error handling during model.cfg serialization.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from exporters.msfs_export import MSFSExporter


def test_msfs_export_package_model_cfg_write_failure(tmp_path: Path):
    """Negative boundary: OSError during base model.cfg write returns False and error message."""
    mock_context = MagicMock()
    mock_blend_data = MagicMock()
    mock_blend_data.collections = []
    mock_bpy = MagicMock()

    export_dir = str(tmp_path / "Package")

    with (
        patch("exporters.msfs_export.bpy", mock_bpy),
        patch.object(MSFSExporter, "export_asset", return_value=(True, "Exported geometry")),
        patch("builtins.open", side_effect=OSError("Disk full / permission denied")),
    ):
        ok, msg = MSFSExporter.export_project_package(
            mock_context,
            export_dir=export_dir,
            base_asset_name="Airframe",
            blend_data=mock_blend_data,
        )

    assert ok is False
    assert "Failed writing model.cfg for package 'Airframe'" in msg
    assert "Disk full" in msg


def test_msfs_export_package_variant_model_cfg_write_failure(tmp_path: Path):
    """Negative boundary: OSError during variant model.cfg write returns False and error message."""
    mock_context = MagicMock()
    variant_coll = MagicMock()
    variant_coll.name = "Airframe_Floats"
    mock_blend_data = MagicMock()
    mock_blend_data.collections.get.return_value = None
    mock_blend_data.collections.__iter__.return_value = iter([variant_coll])
    mock_bpy = MagicMock()

    export_dir = str(tmp_path / "Package")

    # Base export succeeds and writes base model.cfg cleanly, but variant model.cfg write fails
    real_open = open

    def selective_open(file, *args, **kwargs):
        if "model.floats" in str(file) and "model.cfg" in str(file):
            raise OSError("Variant disk write failed")
        return real_open(file, *args, **kwargs)

    with (
        patch("exporters.msfs_export.bpy", mock_bpy),
        patch.object(MSFSExporter, "export_asset", return_value=(True, "Exported geometry")),
        patch("builtins.open", side_effect=selective_open),
    ):
        ok, msg = MSFSExporter.export_project_package(
            mock_context,
            export_dir=export_dir,
            base_asset_name="Airframe",
            blend_data=mock_blend_data,
        )

    assert ok is False
    assert "Failed writing variant model.cfg for 'Airframe_Floats'" in msg
    assert "Variant disk write failed" in msg


def test_msfs_export_package_happy_path(tmp_path: Path):
    """Happy path: base package and variants are written and structured correctly."""
    mock_context = MagicMock()
    variant_coll = MagicMock()
    variant_coll.name = "Airframe_Skis"
    mock_blend_data = MagicMock()
    mock_blend_data.collections.get.return_value = None
    mock_blend_data.collections.__iter__.return_value = iter([variant_coll])
    mock_bpy = MagicMock()

    export_dir = str(tmp_path / "Package_Happy")

    with (
        patch("exporters.msfs_export.bpy", mock_bpy),
        patch.object(MSFSExporter, "export_asset", return_value=(True, "Exported geometry")),
    ):
        ok, msg = MSFSExporter.export_project_package(
            mock_context,
            export_dir=export_dir,
            base_asset_name="Airframe",
            blend_data=mock_blend_data,
        )

    assert ok is True
    assert "MSFS package (2 model(s) & configs) exported" in msg

    base_cfg = Path(export_dir) / "model" / "model.cfg"
    assert base_cfg.exists()
    assert "normal=Airframe.xml" in base_cfg.read_text(encoding="utf-8")

    var_cfg = Path(export_dir) / "model.skis" / "model.cfg"
    assert var_cfg.exists()
    assert "normal=Airframe_Skis.xml" in var_cfg.read_text(encoding="utf-8")
