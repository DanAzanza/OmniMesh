"""
Unit tests for MSFS 2024 ModelInfo XML generation.
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
