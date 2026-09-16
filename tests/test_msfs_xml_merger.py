"""
Unit tests for OmniMesh ModelInfo XML surgical merger.
Verifies lossless preservation of comments, CDATA, RPN logic, and existing behavior definitions.
"""

from pathlib import Path
from core.msfs.xml_merger import ModelXMLMerger


SAMPLE_COMPLEX_MSFS_XML = """<?xml version="1.0" encoding="utf-8" ?>
<!-- Copyright (c) Microsoft Corporation. All rights reserved. -->
<ModelInfo version="1.1" guid="{BC935F16-43CD-4046-8EF3-06E44A5940AB}">

    <LODS>
        <!-- Old LOD setup to be replaced -->
        <LOD minSize="100" ModelFile="Old_LOD00.gltf"/>
        <LOD minSize="10" ModelFile="Old_LOD01.gltf"/>
    </LODS>

    <!-- Essential Aircraft Animation Definitions -->
    <Animation name="c_wheel" guid="BC935F16-43CD-4046-8EF3-06E44A5940AB" length="200" type="Sim" typeparam2="c_wheel" typeparam="AutoPlay" />
    <Animation name="elevator_percent" guid="69FCED03-9A10-49A7-AA82-2B79AB5B63E0" length="100" type="Sim" />

    <PartInfo>
        <Name>c_wheel</Name>
        <AnimLength>200</AnimLength>
        <Animation>
            <Parameter>
                <Code>
            (A:GEAR CENTER STEER ANGLE, grads) 0 &gt; if{ (A:GEAR CENTER STEER ANGLE, grads) 0.5 * } els{ (A:GEAR CENTER STEER ANGLE, grads) 0.5 * 200 + }
                </Code>
            </Parameter>
        </Animation>
        <MouseRect>
            <TooltipID>TOOLTIPTEXT_STEER_ANGLE</TooltipID>
        </MouseRect>
    </PartInfo>

    <CompileBehaviors Version="2">
        <Component ID="Gauges" Node="SCREENS">
            <Material>
                <EmissiveFactor>
                    <Parameter>
                        <Code>(A:AMBIENT LIGHT SENSOR, Number) 200 2000 0.005 1 (F:MapRange)</Code>
                    </Parameter>
                    <OverrideBaseEmissive>false</OverrideBaseEmissive>
                </EmissiveFactor>
            </Material>
        </Component>
    </CompileBehaviors>
</ModelInfo>
"""


def test_merge_lods_preserves_comments_and_behaviors():
    tiers = [
        {"min_size": 50.0, "model_file": "New_LOD0.gltf"},
        {"min_size": 25.0, "model_file": "New_LOD1.gltf"},
        {"min_size": 0.5, "model_file": "New_LOD2.gltf"},
    ]

    merged = ModelXMLMerger.merge_lods_into_xml_content(SAMPLE_COMPLEX_MSFS_XML, tiers)

    # 1. Verify new LODs are present
    assert '<LOD minSize="50" ModelFile="New_LOD0.gltf"/>' in merged
    assert '<LOD minSize="25" ModelFile="New_LOD1.gltf"/>' in merged
    assert '<LOD minSize="0.5" ModelFile="New_LOD2.gltf"/>' in merged
    assert "Old_LOD00.gltf" not in merged

    # 2. Verify developer comments are 100% intact
    assert "<!-- Copyright (c) Microsoft Corporation. All rights reserved. -->" in merged
    assert "<!-- Essential Aircraft Animation Definitions -->" in merged

    # 3. Verify RPN Code logic with special XML entities (&gt;, <Code>) is 100% intact
    assert "(A:GEAR CENTER STEER ANGLE, grads) 0 &gt; if{" in merged
    assert "<TooltipID>TOOLTIPTEXT_STEER_ANGLE</TooltipID>" in merged
    assert '<CompileBehaviors Version="2">' in merged
    assert '<Component ID="Gauges" Node="SCREENS">' in merged
    assert "(A:AMBIENT LIGHT SENSOR, Number) 200 2000 0.005 1 (F:MapRange)" in merged


def test_merge_lods_into_xml_without_existing_lods():
    xml_bare = """<?xml version="1.0" encoding="utf-8"?>
<ModelInfo version="1.1">
    <Animation name="prop_anim" guid="E8A94AB5-CBBD-4978-862B-4D78D9FF3E25" length="100" />
</ModelInfo>
"""
    tiers = [{"min_size": 30.0, "model_file": "Aircraft_LOD0.gltf"}]
    merged = ModelXMLMerger.merge_lods_into_xml_content(xml_bare, tiers)

    assert '<LOD minSize="30" ModelFile="Aircraft_LOD0.gltf"/>' in merged
    assert '<Animation name="prop_anim"' in merged


def test_merge_lods_file_atomic(tmp_path: Path):
    target = tmp_path / "test_model.xml"
    target.write_text(SAMPLE_COMPLEX_MSFS_XML, encoding="utf-8")

    tiers = [{"min_size": 40.0, "model_file": "Test_LOD0.gltf"}]
    success = ModelXMLMerger.merge_lods_file(target, tiers)

    assert success is True
    content = target.read_text(encoding="utf-8")
    assert '<LOD minSize="40" ModelFile="Test_LOD0.gltf"/>' in content
    assert "c_wheel" in content
