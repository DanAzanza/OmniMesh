from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

from core.texture_relinker import (
    ProjectTextureRelinker,
    RelinkSummary,
)


class MockImage:
    def __init__(
        self,
        name: str,
        filepath: str,
        source: str = "FILE",
        packed_file: Any = None,
        has_data: bool = True,
    ):
        self.name = name
        self.filepath = filepath
        self.source = source
        self.packed_file = packed_file
        self.packed_files = [packed_file] if packed_file else []
        self.has_data = has_data
        self.reload_called = False

    def reload(self) -> None:
        self.reload_called = True


def test_is_image_valid_cases():
    # 1. None image
    assert not ProjectTextureRelinker.is_image_valid(None)

    # 2. Generated image
    gen_img = MockImage("Canvas", "", source="GENERATED")
    assert ProjectTextureRelinker.is_image_valid(gen_img)  # type: ignore

    # 3. Packed image
    packed_img = MockImage("Packed", "missing.png", source="FILE", packed_file=object())
    assert ProjectTextureRelinker.is_image_valid(packed_img)  # type: ignore

    # 4. Existing disk file
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf_path = tf.name
    try:
        disk_img = MockImage("Disk", tf_path, source="FILE")
        assert ProjectTextureRelinker.is_image_valid(disk_img)  # type: ignore

        # 5. Non-existent disk file
        missing_img = MockImage("Missing", "C:/non/existent/path/tex.png", source="FILE")
        assert not ProjectTextureRelinker.is_image_valid(missing_img)  # type: ignore
    finally:
        if os.path.exists(tf_path):
            os.remove(tf_path)


def test_build_texture_index_and_pruning():
    temp_dir = tempfile.mkdtemp()
    try:
        # Create normal texture directory
        tex_dir = os.path.join(temp_dir, "Sources", "Art", "Textures")
        os.makedirs(tex_dir, exist_ok=True)
        albedo_path = os.path.join(tex_dir, "SimpleAircraft_FUSELAGE_albd_000.png")
        with open(albedo_path, "wb") as f:
            f.write(b"PNG")

        # Create MSFS .png.dds file
        comp_dds_path = os.path.join(tex_dir, "SimpleAircraft_FUSELAGE_comp.png.dds")
        with open(comp_dds_path, "wb") as f:
            f.write(b"DDS")

        # Create ignored directory that should be pruned
        ignored_dir = os.path.join(temp_dir, "node_modules", "package")
        os.makedirs(ignored_dir, exist_ok=True)
        ignored_file = os.path.join(ignored_dir, "ignored_texture.png")
        with open(ignored_file, "wb") as f:
            f.write(b"PNG")

        # Non-texture file
        cfg_file = os.path.join(tex_dir, "flight_model.cfg")
        with open(cfg_file, "wb") as f:
            f.write(b"CFG")

        index = ProjectTextureRelinker.build_texture_index([temp_dir])

        assert "simpleaircraft_fuselage_albd_000.png" in index
        assert len(index["simpleaircraft_fuselage_albd_000.png"]) == 1
        assert index["simpleaircraft_fuselage_albd_000.png"][0] == Path(albedo_path)

        assert "simpleaircraft_fuselage_comp.png.dds" in index
        assert "ignored_texture.png" not in index
        assert "flight_model.cfg" not in index
    finally:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


def test_score_candidate_and_disambiguation():
    cand1 = Path("C:/Project/Sources/Art/Textures/decals.png")
    cand2 = Path("C:/Project/Cockpit/texture/decals.png")

    orig_path = "D:/Work/Cockpit/texture/decals.png"

    score1 = ProjectTextureRelinker.score_candidate(cand1, orig_path)
    score2 = ProjectTextureRelinker.score_candidate(cand2, orig_path)

    # cand2 shares 'cockpit' and 'texture', so it must have higher score
    assert score2 > score1

    index = {"decals.png": [cand1, cand2]}
    match = ProjectTextureRelinker.find_matching_file("decals.png", orig_path, index)
    assert match == cand2


def test_find_matching_file_extension_alias():
    cand_dds = Path("C:/Project/Textures/airframe.dds")
    index = {"airframe.dds": [cand_dds]}

    # Original requested .png, candidate is .dds
    match = ProjectTextureRelinker.find_matching_file("airframe.png", "airframe.png", index)
    assert match == cand_dds


def test_split_drive_portable():
    assert ProjectTextureRelinker._split_drive_portable("C:/Project/file.png") == ("C:", "/Project/file.png")
    assert ProjectTextureRelinker._split_drive_portable("D:\\Textures\\norm.png") == ("D:", "\\Textures\\norm.png")
    assert ProjectTextureRelinker._split_drive_portable("/home/runner/work") == ("", "/home/runner/work")
    assert ProjectTextureRelinker._split_drive_portable("textures/sub/file.png") == ("", "textures/sub/file.png")
    assert ProjectTextureRelinker._split_drive_portable("") == ("", "")


def test_make_relative_path_safety():
    # 1. Unsaved blend file (None)
    target = Path("C:/Project/Textures/diffuse.png")
    assert ProjectTextureRelinker.make_relative_path(target, None) == str(target)

    # 2. Same drive
    blend_file = "C:/Project/Sources/Art/Blender/scene.blend"
    rel_path = ProjectTextureRelinker.make_relative_path(target, blend_file)
    assert rel_path == "//../../Textures/diffuse.png" or rel_path.startswith("//")

    # 3. Cross drive (Windows)
    target_d = Path("D:/Textures/diffuse.png")
    cross_rel = ProjectTextureRelinker.make_relative_path(target_d, blend_file)
    assert cross_rel == str(target_d)

    # 4. Simulated POSIX runner cross-drive isolation
    with patch("core.texture_relinker.os.name", "posix"):
        posix_cross = ProjectTextureRelinker.make_relative_path(target_d, blend_file)
        assert posix_cross == str(target_d)

        # Same drive under POSIX simulation
        posix_same = ProjectTextureRelinker.make_relative_path(target, blend_file)
        assert posix_same.startswith("//")
        assert "diffuse.png" in posix_same


def test_relink_images_end_to_end():
    temp_dir = tempfile.mkdtemp()
    try:
        textures_dir = os.path.join(temp_dir, "Textures")
        os.makedirs(textures_dir, exist_ok=True)

        tex_file = os.path.join(textures_dir, "fuselage_albedo.png")
        with open(tex_file, "wb") as f:
            f.write(b"PNG")

        blend_dir = os.path.join(temp_dir, "Blender")
        os.makedirs(blend_dir, exist_ok=True)
        blend_file = os.path.join(blend_dir, "model.blend")

        # 1. Image with broken hardcoded path (e.g. from developer's D: drive)
        broken_img = MockImage(
            "Fuselage_Mat_Tex",
            "D:/Internal/Asobo/Dev/Textures/fuselage_albedo.png",
            source="FILE",
        )
        # 2. Image that is already valid
        valid_img = MockImage("Valid_Tex", tex_file, source="FILE")
        # 3. Packed image
        packed_img = MockImage("Packed_Tex", "packed.png", source="FILE", packed_file=object())
        # 4. Truly missing image
        missing_img = MockImage("Ghost_Tex", "ghost.png", source="FILE")

        images = [broken_img, valid_img, packed_img, missing_img]

        summary = ProjectTextureRelinker.relink_images(
            images=images,  # type: ignore
            search_roots=[temp_dir],
            blend_filepath=blend_file,
            make_relative=True,
        )

        assert isinstance(summary, RelinkSummary)
        assert summary.total_checked == 4
        assert summary.already_valid == 2  # valid_img + packed_img
        assert summary.relinked == 1  # broken_img
        assert summary.missing_unresolved == 1  # missing_img

        assert broken_img.reload_called is True
        assert broken_img.filepath == "//../Textures/fuselage_albedo.png"
    finally:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


def test_operator_relink_project_textures():
    from ui.pbr_ops import LOD_OT_relink_project_textures

    op = LOD_OT_relink_project_textures()
    op.report = MagicMock()

    mock_bpy = MagicMock()
    mock_bpy.data.images = []
    mock_bpy.data.filepath = "C:/TestProject/Art/scene.blend"
    mock_bpy.ops.lod_tool.import_pbr_set.return_value = {"FINISHED"}

    context = MagicMock()
    context.scene.lod_tool.pbr_import_directory = "C:/TestProject/Textures"

    with patch("ui.pbr_ops.bpy", mock_bpy):
        res = op.execute(context)
        assert res == {"FINISHED"}
