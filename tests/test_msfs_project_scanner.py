"""
Unit tests for MSFS Project Scanner Subsystem.
Verifies case-insensitive path resolution, folder heuristics, model.cfg/XML parsing,
and manifest extraction for MSFS 2020 / 2024 aircraft packages.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from core.msfs_project_scanner import (
    MSFSProjectScanner,
    parse_model_cfg,
    parse_model_xml,
    resolve_path_ci,
    sanitize_asset_name,
)

SAMPLE_MODEL_CFG = """
; Sample model.cfg
[models]
normal = TestModel.xml
interior = TestModel_interior.xml
"""

SAMPLE_MODEL_XML = """<?xml version="1.0" encoding="utf-8" ?>
<ModelInfo>
    <LODS>
        <LOD minSize="50" ModelFile="TestModel_LOD0.gltf"/>
        <LOD minSize="20" ModelFile="TestModel_LOD1.gltf"/>
        <LOD minSize="5" ModelFile="TestModel_LOD2.gltf"/>
    </LODS>
</ModelInfo>
"""


def test_sanitize_asset_name():
    assert sanitize_asset_name("MyCompany_Simple_Aircraft") == "Simple_Aircraft"
    assert sanitize_asset_name("asobo-aircraft-c172") == "aircraft_c172"
    assert sanitize_asset_name("123_Airplane") == "Asset_123_Airplane"
    assert sanitize_asset_name("  !Special @ Plane #  ") == "Special_Plane"


def test_resolve_path_ci(tmp_path: Path):
    sub = tmp_path / "Common" / "Model"
    sub.mkdir(parents=True)
    target_file = sub / "TestFile.XML"
    target_file.write_text("<root/>", encoding="utf-8")

    resolved = resolve_path_ci(tmp_path, "common", "model", "testfile.xml")
    assert resolved is not None
    assert resolved.samefile(target_file)

    # Non-existent
    assert resolve_path_ci(tmp_path, "common", "missing", "test.xml") is None


def test_parse_model_cfg_and_xml(tmp_path: Path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    cfg_file = model_dir / "model.cfg"
    cfg_file.write_text(SAMPLE_MODEL_CFG, encoding="utf-8")

    xml_file = model_dir / "TestModel.xml"
    xml_file.write_text(SAMPLE_MODEL_XML, encoding="utf-8")

    # Create dummy gltfs
    (model_dir / "TestModel_LOD0.gltf").write_text("{}", encoding="utf-8")
    (model_dir / "TestModel_LOD1.gltf").write_text("{}", encoding="utf-8")
    # LOD2 gltf intentionally omitted to test exists=False

    models = parse_model_cfg(cfg_file)
    assert models == {"normal": "TestModel.xml", "interior": "TestModel_interior.xml"}

    lods = parse_model_xml(xml_file)
    assert len(lods) == 3
    assert lods[0].index == 0
    assert lods[0].min_size == 50.0
    assert lods[0].exists is True
    assert lods[1].index == 1
    assert lods[1].min_size == 20.0
    assert lods[1].exists is True
    assert lods[2].index == 2
    assert lods[2].min_size == 5.0
    assert lods[2].exists is False  # Omitted file


def test_scanner_on_synthetic_package(tmp_path: Path):
    pkg = tmp_path / "MyCompany_FastJet"
    common = pkg / "common"
    model_dir = common / "model"
    config_dir = common / "config"
    model_dir.mkdir(parents=True)
    config_dir.mkdir(parents=True)

    (model_dir / "model.cfg").write_text(SAMPLE_MODEL_CFG, encoding="utf-8")
    (model_dir / "TestModel.xml").write_text(SAMPLE_MODEL_XML, encoding="utf-8")
    (model_dir / "TestModel_LOD0.gltf").write_text("{}", encoding="utf-8")

    (config_dir / "flight_model.cfg").write_text("[WEIGHT_AND_BALANCE]\n", encoding="utf-8")
    (config_dir / "systems.cfg").write_text("[LIGHTS]\n", encoding="utf-8")
    (config_dir / "cameras.cfg").write_text("[VIEWS]\n", encoding="utf-8")

    # 1. Scan root
    manifest = MSFSProjectScanner.scan(pkg)
    assert manifest.asset_name == "FastJet"
    assert manifest.has_geometry is True
    assert manifest.model_cfg_path is not None
    assert manifest.flight_model_cfg_path is not None
    assert manifest.systems_cfg_path is not None
    assert manifest.cameras_cfg_path is not None
    assert "normal" in manifest.models
    assert len(manifest.models["normal"].lods) == 3

    # 2. Scan from child subfolder (e.g. user selected common/config)
    manifest_from_child = MSFSProjectScanner.scan(config_dir)
    assert manifest_from_child.package_root.samefile(pkg)
    assert manifest_from_child.asset_name == "FastJet"
    assert manifest_from_child.has_geometry is True


def test_scanner_on_real_simpleaircraft_sdk():
    sdk_sample = Path(
        r"C:\MSFS 2024 SDK\Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft"
        r"\PackageSources\SimObjects\Airplanes\MyCompany_Simple_Aircraft"
    )
    if not sdk_sample.is_dir():
        pytest.skip("MSFS 2024 SDK SimpleAircraft sample not found on local drive")

    manifest = MSFSProjectScanner.scan(sdk_sample)
    assert manifest.asset_name == "Simple_Aircraft"
    assert manifest.has_geometry is True
    assert manifest.model_cfg_path is not None
    assert manifest.flight_model_cfg_path is not None
    assert manifest.systems_cfg_path is not None
    assert manifest.cameras_cfg_path is not None

    exterior = manifest.exterior_model
    assert exterior is not None
    assert len(exterior.lods) == 5  # LOD00 through LOD04
    for lod in exterior.lods:
        assert lod.exists is True
        assert lod.gltf_path.suffix.lower() == ".gltf"


def test_resolve_path_ci_parent_and_backslashes(tmp_path: Path):
    """Verifies resolve_path_ci handles .. traversal and Windows backslashes."""
    common_model = tmp_path / "common" / "model"
    common_model.mkdir(parents=True)
    shared_int = common_model / "Interior.xml"
    shared_int.write_text("<ModelInfo><LODS/></ModelInfo>", encoding="utf-8")

    variant_model = tmp_path / "model.floats"
    variant_model.mkdir(parents=True)

    # Relative traversal from model.floats to common/model/Interior.xml
    resolved = resolve_path_ci(variant_model, r"..\common\model\Interior.xml")
    assert resolved is not None
    assert resolved.samefile(shared_int)

    # Multiple ..
    deep_sub = tmp_path / "a" / "b" / "c"
    deep_sub.mkdir(parents=True)
    resolved_deep = resolve_path_ci(deep_sub, r"..\..\..\common\model\Interior.xml")
    assert resolved_deep is not None
    assert resolved_deep.samefile(shared_int)


def test_scanner_with_interior_and_variants(tmp_path: Path):
    """Verifies scanner discovers both exterior, interior, and variant models."""
    pkg = tmp_path / "MyCompany_TwinEngine"
    model_dir = pkg / "common" / "model"
    model_dir.mkdir(parents=True)

    # Exterior XML & glTF
    (model_dir / "Twin_LOD0.gltf").write_text("{}", encoding="utf-8")
    ext_xml = model_dir / "Twin.xml"
    ext_xml.write_text(
        '<ModelInfo><LODS><LOD minSize="50" ModelFile="Twin_LOD0.gltf"/></LODS></ModelInfo>', encoding="utf-8"
    )

    # Interior XML & glTF
    (model_dir / "Twin_Interior_LOD0.gltf").write_text("{}", encoding="utf-8")
    int_xml = model_dir / "Twin_Interior.xml"
    int_xml.write_text(
        '<ModelInfo><LODS><LOD minSize="80" ModelFile="Twin_Interior_LOD0.gltf"/></LODS></ModelInfo>', encoding="utf-8"
    )

    # Base model.cfg
    (model_dir / "model.cfg").write_text("[models]\nexterior=Twin.xml\ninterior=Twin_Interior.xml\n", encoding="utf-8")

    # Floats variant
    floats_dir = pkg / "common" / "model.floats"
    floats_dir.mkdir(parents=True)
    (floats_dir / "Twin_Floats_LOD0.gltf").write_text("{}", encoding="utf-8")
    floats_xml = floats_dir / "Twin_Floats.xml"
    floats_xml.write_text(
        '<ModelInfo><LODS><LOD minSize="50" ModelFile="Twin_Floats_LOD0.gltf"/></LODS></ModelInfo>', encoding="utf-8"
    )
    (floats_dir / "model.cfg").write_text(
        "[models]\nnormal=Twin_Floats.xml\ninterior=..\\model\\Twin_Interior.xml\n", encoding="utf-8"
    )

    manifest = MSFSProjectScanner.scan(pkg)
    assert manifest.asset_name == "TwinEngine"
    assert manifest.has_geometry is True
    assert manifest.exterior_model is not None
    assert len(manifest.exterior_model.lods) == 1
    assert manifest.interior_model is not None
    assert len(manifest.interior_model.lods) == 1

    # Check variant
    assert "floats" in manifest.variants
    variant_floats = manifest.variants["floats"]
    assert len(variant_floats.lods) == 1
    assert variant_floats.lods[0].gltf_path.name == "Twin_Floats_LOD0.gltf"
