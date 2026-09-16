"""
Unit tests for MSFS model.options parsing and MSFSModelOptions domain model.
"""

from pathlib import Path
from core.msfs.project_scanner import parse_model_options


def test_parse_model_options_msfs_2024(tmp_path: Path):
    cfg = tmp_path / "model.cfg"
    cfg.write_text(
        """[model.options]
withExterior_showInterior=true
withExterior_showInterior_hideFirstLod=true
withInterior_forceFirstLod=true
withInterior_showExterior=false

[models]
exterior=Aircraft.xml
interior=Aircraft_interior.xml
""",
        encoding="utf-8",
    )

    opts = parse_model_options(cfg)
    assert opts.has_explicit_section is True
    assert opts.is_msfs_2024 is True
    assert opts.with_exterior_show_interior is True
    assert opts.with_exterior_show_interior_hide_first_lod is True
    assert opts.with_interior_force_first_lod is True
    assert opts.with_interior_show_exterior is False


def test_parse_model_options_msfs_2020_legacy(tmp_path: Path):
    cfg = tmp_path / "model.cfg"
    cfg.write_text(
        """[models]
normal=Aircraft.xml
interior=Aircraft_interior.xml
""",
        encoding="utf-8",
    )

    opts = parse_model_options(cfg)
    assert opts.has_explicit_section is False
    assert opts.is_msfs_2024 is False
