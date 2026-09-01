"""
Unit tests for MSFS 2024 ModelInfo XML generation and edge cases.
"""

import xml.etree.ElementTree as ET

from exporters.msfs_export import MSFSExporter


def test_msfs_model_info_xml_generation():
    tiers = [
        {"screen_size_pct": 100.0},
        {"screen_size_pct": 50.0},
        {"screen_size_pct": 25.0},
        {"screen_size_pct": 10.0},
        {"screen_size_pct": 5.0},
        {"screen_size_pct": 2.0},
        {"screen_size_pct": 0.5},
    ]
    asset_name = "SM_Hangar_01"
    guid = "12345678-1234-4234-8234-123456789ABC"

    xml_text = MSFSExporter.generate_model_info_xml(asset_name, tiers, guid)
    root = ET.fromstring(xml_text)

    assert root.tag == "ModelInfo"
    assert root.attrib["guid"] == f"{{{guid}}}"

    lods = root.find("LODS")
    assert lods is not None
    lod_elements = lods.findall("LOD")
    assert len(lod_elements) == 7

    # Check minSize descending and last is 0
    assert lod_elements[0].attrib["minSize"] == "100.0"
    assert lod_elements[0].attrib["ModelFile"] == "SM_Hangar_01_LOD0.gltf"
    assert lod_elements[-1].attrib["minSize"] == "0"
    assert lod_elements[-1].attrib["ModelFile"] == "SM_Hangar_01_LOD6.gltf"


def test_msfs_xml_special_character_escaping():
    tiers = [{"screen_size_pct": 100.0}, {"screen_size_pct": 20.0}]
    asset_name = "Building & \"Hangar\" <Tower> 'Radar'"
    guid = "{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}"

    xml_text = MSFSExporter.generate_model_info_xml(asset_name, tiers, guid)
    # Must be valid XML parsable by ElementTree
    root = ET.fromstring(xml_text)

    assert root.tag == "ModelInfo"
    assert root.attrib["guid"] == "{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}"

    lods = root.find("LODS")
    assert lods is not None
    lod_elements = lods.findall("LOD")
    assert len(lod_elements) == 2
    assert lod_elements[0].attrib["ModelFile"] == "Building & _Hangar_ _Tower_ 'Radar'_LOD0.gltf"
    assert lod_elements[1].attrib["minSize"] == "0"


def test_msfs_xml_guid_normalization():
    # Without braces
    xml1 = MSFSExporter.generate_model_info_xml("Test", [{"screen_size_pct": 100.0}], "1234-5678")
    root1 = ET.fromstring(xml1)
    assert root1.attrib["guid"] == "{1234-5678}"

    # With braces
    xml2 = MSFSExporter.generate_model_info_xml("Test", [{"screen_size_pct": 100.0}], "{1234-5678}")
    root2 = ET.fromstring(xml2)
    assert root2.attrib["guid"] == "{1234-5678}"

    # Empty GUID should generate valid UUID with braces
    xml3 = MSFSExporter.generate_model_info_xml("Test", [{"screen_size_pct": 100.0}], "")
    root3 = ET.fromstring(xml3)
    assert root3.attrib["guid"].startswith("{") and root3.attrib["guid"].endswith("}")
    assert len(root3.attrib["guid"]) == 38


def test_msfs_xml_empty_and_single_tier():
    # Empty tiers
    xml_empty = MSFSExporter.generate_model_info_xml("EmptyAsset", [])
    root_empty = ET.fromstring(xml_empty)
    lods_empty = root_empty.find("LODS")
    assert lods_empty is not None
    assert len(lods_empty.findall("LOD")) == 1
    assert lods_empty.find("LOD").attrib["minSize"] == "0"

    # Single tier
    xml_single = MSFSExporter.generate_model_info_xml("SingleAsset", [{"screen_size_pct": 100.0}])
    root_single = ET.fromstring(xml_single)
    lods_single = root_single.find("LODS")
    assert lods_single is not None
    assert len(lods_single.findall("LOD")) == 1
    assert lods_single.find("LOD").attrib["minSize"] == "0"
