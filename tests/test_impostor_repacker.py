"""Tests for pure-Python/NumPy PNG reading and engine-independent Impostor texture repacking."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from core import png_writer
from core.impostor_repacker import (
    CanonicalImpostorSources,
    ImpostorTextureRepacker,
    find_canonical_impostor_sources,
    resolve_factory_preset_id_for_engine,
)
from core.pbr_presets import PBRExportPresetManager
from ui.utils import parse_sphere_center


class TestPngWriterDirectRead:
    def test_roundtrip_without_pil_8bit_and_16bit(self, tmp_path: Path) -> None:
        rgb_u8 = np.array([[[10, 20, 30], [200, 150, 100]], [[0, 128, 255], [42, 84, 168]]], dtype=np.uint8)
        rgba_u8 = np.array(
            [[[10, 20, 30, 255], [200, 150, 100, 128]], [[0, 128, 255, 0], [42, 84, 168, 77]]],
            dtype=np.uint8,
        )
        rgba_u16 = (rgba_u8.astype(np.uint16) * 257).astype(np.uint16)
        gray_u8 = np.array([[[15], [240]], [[99], [180]]], dtype=np.uint8)

        p_rgb = str(tmp_path / "rgb8.png")
        p_rgba = str(tmp_path / "rgba8.png")
        p_u16 = str(tmp_path / "rgba16.png")
        p_gray = str(tmp_path / "gray8.png")

        assert png_writer.write_png_direct(p_rgb, rgb_u8, bit_depth=8) is True
        assert png_writer.write_png_direct(p_rgba, rgba_u8, bit_depth=8) is True
        assert png_writer.write_png_direct(p_u16, rgba_u16, bit_depth=16) is True
        assert png_writer.write_png_direct(p_gray, gray_u8, bit_depth=8) is True

        # Verify 16-bit read stays uint16 even when PIL is available (regression against PIL 8-bit truncation)
        np.testing.assert_array_equal(png_writer.read_png_direct(p_u16), rgba_u16)

        with patch.object(png_writer, "Image", None):
            np.testing.assert_array_equal(png_writer.read_png_direct(p_rgb), rgb_u8)
            np.testing.assert_array_equal(png_writer.read_png_direct(p_rgba), rgba_u8)
            np.testing.assert_array_equal(png_writer.read_png_direct(p_u16), rgba_u16)
            np.testing.assert_array_equal(png_writer.read_png_direct(p_gray), gray_u8)

    def test_unfilter_png_scanlines_all_filters(self) -> None:
        h, w, ch = 5, 4, 4
        img = np.arange(h * w * ch, dtype=np.uint8).reshape((h, w, ch)) * 3
        bpp = ch
        filtered_rows: list[bytes] = []

        for y in range(h):
            cur = img[y].reshape(w * bpp)
            prev = img[y - 1].reshape(w * bpp) if y > 0 else np.zeros(w * bpp, dtype=np.uint8)
            ftype = y % 5
            if ftype == 0:
                filt = cur
            elif ftype == 1:
                left = np.concatenate([np.zeros(bpp, dtype=np.uint8), cur[:-bpp]])
                filt = ((cur.astype(np.int32) - left.astype(np.int32)) & 0xFF).astype(np.uint8)
            elif ftype == 2:
                filt = ((cur.astype(np.int32) - prev.astype(np.int32)) & 0xFF).astype(np.uint8)
            elif ftype == 3:
                left = np.concatenate([np.zeros(bpp, dtype=np.uint8), cur[:-bpp]])
                avg = (left.astype(np.int32) + prev.astype(np.int32)) >> 1
                filt = ((cur.astype(np.int32) - avg) & 0xFF).astype(np.uint8)
            else:
                left = np.concatenate([np.zeros(bpp, dtype=np.uint8), cur[:-bpp]]).astype(np.int32)
                upleft = np.concatenate([np.zeros(bpp, dtype=np.uint8), prev[:-bpp]]).astype(np.int32)
                pred = png_writer._paeth_predictor(left, prev.astype(np.int32), upleft)
                filt = ((cur.astype(np.int32) - pred) & 0xFF).astype(np.uint8)
            filtered_rows.append(bytes([ftype]) + filt.tobytes())

        raw_stream = b"".join(filtered_rows)
        reconstructed = png_writer._unfilter_png_scanlines(raw_stream, w, h, ch, 8)
        np.testing.assert_array_equal(reconstructed, img)

    def test_read_png_negative_errors(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            png_writer.read_png_direct(str(tmp_path / "does_not_exist.png"))

        bad_sig = tmp_path / "bad.png"
        bad_sig.write_bytes(b"NOT_A_PNG_STREAM")
        with patch.object(png_writer, "Image", None), pytest.raises(ValueError, match="Invalid PNG signature"):
            png_writer.read_png_direct(str(bad_sig))

        with pytest.raises(ValueError, match="Truncated PNG scanline stream"):
            png_writer._unfilter_png_scanlines(b"\x00\x01\x02", 4, 4, 4, 8)

        with pytest.raises(ValueError, match="Unsupported PNG filter type"):
            png_writer._unfilter_png_scanlines(bytes([9] + [0] * 4), 1, 1, 4, 8)


def _write_canonical_jet_master(directory: Path, base_name: str = "Jet") -> CanonicalImpostorSources:
    h, w = 4, 4
    base = np.full((h, w, 4), [180, 90, 45, 255], dtype=np.uint8)
    # OpenGL Normal: R=128, G=200, B=255, Depth=77 in Alpha
    normal = np.full((h, w, 4), [128, 200, 255, 77], dtype=np.uint8)
    # Canonical ORM: R=AO(210), G=Roughness(100), B=Metallic(240)
    orm = np.full((h, w, 4), [210, 100, 240, 255], dtype=np.uint8)

    p_base = str(directory / f"T_{base_name}_Impostor_BaseColor.png")
    p_norm = str(directory / f"T_{base_name}_Impostor_Normal.png")
    p_orm = str(directory / f"T_{base_name}_Impostor_ORM.png")

    assert png_writer.write_png_direct(p_base, base, bit_depth=8)
    assert png_writer.write_png_direct(p_norm, normal, bit_depth=8)
    assert png_writer.write_png_direct(p_orm, orm, bit_depth=8)
    return CanonicalImpostorSources(
        base_name=base_name,
        base_color_path=p_base,
        normal_path=p_norm,
        orm_path=p_orm,
        source_convention="CANONICAL",
    )


class TestImpostorTextureRepacker:
    def test_repack_all_five_factory_presets(self, tmp_path: Path) -> None:
        master_dir = tmp_path / "master"
        master_dir.mkdir()
        sources = _write_canonical_jet_master(master_dir, "Jet")

        # 1. Unreal Engine 5 (DX Normal + ORM, preserves Depth in Normal.A)
        ue5_dir = tmp_path / "ue5"
        ue5_preset = PBRExportPresetManager.get_preset("unreal_engine_5")
        ue5_out = ImpostorTextureRepacker.repack_impostor_textures(sources, str(ue5_dir), "UE5", ue5_preset)
        assert set(ue5_out.keys()) == {"base_color", "orm", "normal"}
        dx_norm = png_writer.read_png_direct(ue5_out["normal"])
        assert tuple(dx_norm[0, 0]) == (128, 55, 255, 77)
        ue_orm = png_writer.read_png_direct(ue5_out["orm"])
        assert tuple(ue_orm[0, 0]) == (210, 100, 240, 255)

        # Canonical master in master_dir remains untouched (OpenGL G=200)
        assert tuple(png_writer.read_png_direct(sources.normal_path)[0, 0]) == (128, 200, 255, 77)

        # 2. Unity HDRP MaskMap (16-bit R=Metallic, G=AO, B=0, A=Smoothness=255-Roughness)
        hdrp_dir = tmp_path / "unity_hdrp"
        hdrp_preset = PBRExportPresetManager.get_preset("unity_hdrp_maskmap")
        hdrp_out = ImpostorTextureRepacker.repack_impostor_textures(sources, str(hdrp_dir), "UNITY_6", hdrp_preset)
        assert set(hdrp_out.keys()) == {"base_color", "maskmap", "normal"}
        maskmap = png_writer.read_png_direct(hdrp_out["maskmap"])
        assert maskmap.dtype == np.uint16
        # Expect exact 257-scaled 8-bit channels: Metallic=240, AO=210, Detail=0, Smoothness=155
        assert tuple(maskmap[0, 0]) == (240 * 257, 210 * 257, 0, 155 * 257)
        gl_norm = png_writer.read_png_direct(hdrp_out["normal"])
        assert gl_norm.dtype == np.uint16
        assert gl_norm[0, 0, 1] == 200 * 257

        # 3. Unity URP Metallic Smoothness
        urp_dir = tmp_path / "unity_urp"
        urp_preset = PBRExportPresetManager.get_preset("unity_urp_metallic")
        urp_out = ImpostorTextureRepacker.repack_impostor_textures(sources, str(urp_dir), "UNITY_6", urp_preset)
        assert set(urp_out.keys()) == {"base_color", "metallic_smoothness", "normal", "occlusion"}
        ms = png_writer.read_png_direct(urp_out["metallic_smoothness"])
        assert tuple(ms[0, 0]) == (240, 240, 240, 155)
        occ = png_writer.read_png_direct(urp_out["occlusion"])
        assert occ[0, 0, 0] == 210

        # 4. MSFS 2024 Comp + DX Normal
        msfs_dir = tmp_path / "msfs"
        msfs_preset = PBRExportPresetManager.get_preset("msfs_2024_comp")
        msfs_out = ImpostorTextureRepacker.repack_impostor_textures(sources, str(msfs_dir), "MSFS_2024", msfs_preset)
        assert set(msfs_out.keys()) == {"albedo", "comp", "normal"}
        assert png_writer.read_png_direct(msfs_out["normal"])[0, 0, 1] == 55

        # 5. Standard PBR Split (individual grayscale channels)
        split_dir = tmp_path / "split"
        split_preset = PBRExportPresetManager.get_preset("standard_pbr_split")
        split_out = ImpostorTextureRepacker.repack_impostor_textures(sources, str(split_dir), "ALL", split_preset)
        assert set(split_out.keys()) == {"base_color", "normal", "roughness", "metallic", "ambient_occlusion"}
        assert png_writer.read_png_direct(split_out["roughness"])[0, 0, 0] == 100
        assert png_writer.read_png_direct(split_out["metallic"])[0, 0, 0] == 240
        assert png_writer.read_png_direct(split_out["ambient_occlusion"])[0, 0, 0] == 210

    def test_custom_dx_preset_in_place_preserves_normal_master_backup(self, tmp_path: Path) -> None:
        sources = _write_canonical_jet_master(tmp_path, "Custom")
        custom_dx_preset = {
            "id": "custom_dx_inplace",
            "name": "Custom DX In-Place",
            "bit_depth": 8,
            "maps": [
                {
                    "id": "normal",
                    "export_suffix": "_Normal",
                    "color_space": "Non-Color",
                    "normal_format": "DIRECTX",
                    "channels": {"rgb": {"target": "Normal", "invert": False}},
                }
            ],
        }
        out = ImpostorTextureRepacker.repack_impostor_textures(sources, str(tmp_path), "UE5", custom_dx_preset)
        assert png_writer.read_png_direct(out["normal"])[0, 0, 1] == 55

        backup_path = tmp_path / "T_Custom_Impostor_Normal_Master.png"
        assert backup_path.is_file()
        assert png_writer.read_png_direct(str(backup_path))[0, 0, 1] == 200

        discovered = find_canonical_impostor_sources("Custom", [str(tmp_path)])
        assert discovered is not None
        assert Path(discovered.normal_path) == backup_path

    def test_legacy_ue5_and_unity_source_conventions_cross_convert(self, tmp_path: Path) -> None:
        # Legacy UE5 bake (DX normal G=55, ORM R=210 G=100 B=240) -> Unity HDRP MaskMap
        ue_dir = tmp_path / "legacy_ue5"
        ue_dir.mkdir()
        bc = ue_dir / "T_Ship_Impostor_BaseColor.png"
        dx = ue_dir / "T_Ship_Impostor_Normal.png"
        orm = ue_dir / "T_Ship_Impostor_ORM.png"
        png_writer.write_png_direct(str(bc), np.full((2, 2, 4), 255, dtype=np.uint8))
        png_writer.write_png_direct(str(dx), np.full((2, 2, 4), [128, 55, 255, 90], dtype=np.uint8))
        png_writer.write_png_direct(str(orm), np.full((2, 2, 4), [210, 100, 240, 255], dtype=np.uint8))

        ue_sources = CanonicalImpostorSources("Ship", str(bc), str(dx), str(orm), source_convention="UE5")
        unity_dir = tmp_path / "to_unity"
        unity_out = ImpostorTextureRepacker.repack_impostor_textures(ue_sources, str(unity_dir), "UNITY_6")
        # Reconstructed OpenGL Green should equal 200 * 257 in 16-bit HDRP preset
        assert png_writer.read_png_direct(unity_out["normal"])[0, 0, 1] == 200 * 257
        assert tuple(png_writer.read_png_direct(unity_out["maskmap"])[0, 0]) == (240 * 257, 210 * 257, 0, 155 * 257)

        # Legacy Unity HDRP bake -> UE5 DX + ORM
        u_dir = tmp_path / "legacy_unity"
        u_dir.mkdir()
        u_bc = u_dir / "T_Crate_Impostor_BaseColor.png"
        u_gl = u_dir / "T_Crate_Impostor_Normal.png"
        u_mm = u_dir / "T_Crate_Impostor_ORM.png"
        png_writer.write_png_direct(str(u_bc), np.full((2, 2, 4), 255, dtype=np.uint8))
        png_writer.write_png_direct(str(u_gl), np.full((2, 2, 4), [128, 200, 255, 90], dtype=np.uint8))
        png_writer.write_png_direct(str(u_mm), np.full((2, 2, 4), [240, 210, 0, 155], dtype=np.uint8))

        u_sources = CanonicalImpostorSources("Crate", str(u_bc), str(u_gl), str(u_mm), source_convention="UNITY_6")
        ue5_dir = tmp_path / "to_ue5"
        ue5_out = ImpostorTextureRepacker.repack_impostor_textures(u_sources, str(ue5_dir), "UE5")
        assert tuple(png_writer.read_png_direct(ue5_out["normal"])[0, 0]) == (128, 55, 255, 90)
        assert tuple(png_writer.read_png_direct(ue5_out["orm"])[0, 0]) == (210, 100, 240, 255)

    def test_helpers_and_negative_missing_source(self, tmp_path: Path) -> None:
        assert resolve_factory_preset_id_for_engine("UNITY_6") == "unity_hdrp_maskmap"
        assert resolve_factory_preset_id_for_engine("MSFS_2024") == "msfs_2024_comp"
        assert resolve_factory_preset_id_for_engine("UNKNOWN") == "standard_pbr_split"
        assert parse_sphere_center("1.5, -2.0, 3.25") == (1.5, -2.0, 3.25)
        assert parse_sphere_center("invalid") == (0.0, 0.0, 0.0)
        assert find_canonical_impostor_sources("MissingAsset", [str(tmp_path)]) is None

        bad = CanonicalImpostorSources("Missing", str(tmp_path / "nope.png"), "", "")
        with pytest.raises(FileNotFoundError):
            ImpostorTextureRepacker.repack_impostor_textures(bad, str(tmp_path), "UE5")

    def test_inplace_standard_pbr_split_preserves_alpha_master_for_subsequent_ue5_repack(self, tmp_path: Path) -> None:
        base_rgba = np.full((4, 4, 4), [180, 90, 45, 180], dtype=np.uint8)
        p_base = str(tmp_path / "T_Jet_Impostor_BaseColor.png")
        p_norm = str(tmp_path / "T_Jet_Impostor_Normal.png")
        p_orm = str(tmp_path / "T_Jet_Impostor_ORM.png")
        assert png_writer.write_png_direct(p_base, base_rgba)
        assert png_writer.write_png_direct(p_norm, np.full((4, 4, 4), [128, 200, 255, 77], dtype=np.uint8))
        assert png_writer.write_png_direct(p_orm, np.full((4, 4, 4), [210, 100, 240, 255], dtype=np.uint8))

        sources = CanonicalImpostorSources("Jet", p_base, p_norm, p_orm, source_convention="CANONICAL")
        split_preset = PBRExportPresetManager.get_preset("standard_pbr_split")
        ImpostorTextureRepacker.repack_impostor_textures(sources, str(tmp_path), "ALL", split_preset)

        # In-place BaseColor from standard_pbr_split is RGB (alpha stripped), while backup holds full RGBA
        assert png_writer.read_png_direct(p_base).shape == (4, 4, 3)
        backup_bc = tmp_path / "T_Jet_Impostor_BaseColor_Master.png"
        assert backup_bc.is_file()
        assert png_writer.read_png_direct(str(backup_bc))[0, 0, 3] == 180

        # Switching later to UE5 (even with material_paths pointing at stripped _BaseColor.png) recovers Alpha=180
        discovered = find_canonical_impostor_sources(
            "Jet", [str(tmp_path)], material_paths={"BaseColor": p_base, "Normal": p_norm, "ORM": p_orm}
        )
        assert discovered is not None
        assert Path(discovered.base_color_path) == backup_bc

        ue5_dir = tmp_path / "ue5_later"
        ue5_preset = PBRExportPresetManager.get_preset("unreal_engine_5")
        ue5_out = ImpostorTextureRepacker.repack_impostor_textures(discovered, str(ue5_dir), "UE5", ue5_preset)
        ue5_bc = png_writer.read_png_direct(ue5_out["base_color"])
        assert tuple(ue5_bc[0, 0]) == (180, 90, 45, 180)

    def test_export_false_skipped_and_scalar_targets_in_rgb_broadcast(self, tmp_path: Path) -> None:
        sources = _write_canonical_jet_master(tmp_path, "ScalarRgb")
        out_dir = tmp_path / "out"
        custom_preset = {
            "id": "custom_scalar_rgb",
            "name": "Custom Scalar RGB",
            "bit_depth": 8,
            "maps": [
                {
                    "id": "disabled_map",
                    "export": False,
                    "export_suffix": "_Disabled",
                    "color_space": "sRGB",
                    "channels": {"rgb": {"target": "Base Color", "invert": False}},
                },
                {
                    "id": "smooth_rgb",
                    "export": True,
                    "export_suffix": "_SmoothnessRGB",
                    "color_space": "Non-Color",
                    "channels": {"rgb": {"target": "Roughness", "invert": True, "default": 0.0}},
                },
            ],
        }
        res = ImpostorTextureRepacker.repack_impostor_textures(sources, str(out_dir), "UE5", custom_preset)
        assert "disabled_map" not in res
        assert not (out_dir / "T_ScalarRgb_Impostor_Disabled.png").exists()
        assert "smooth_rgb" in res
        smooth = png_writer.read_png_direct(res["smooth_rgb"])
        assert tuple(smooth[0, 0, :3]) == (155, 155, 155)

    def test_mismatched_source_dimensions_raise_value_error(self, tmp_path: Path) -> None:
        p_bc = str(tmp_path / "T_Bad_Impostor_BaseColor.png")
        p_norm_big = str(tmp_path / "T_Bad_Impostor_Normal.png")
        p_norm_ok = str(tmp_path / "T_Bad_Impostor_Normal_Ok.png")
        p_orm_big = str(tmp_path / "T_Bad_Impostor_ORM.png")
        assert png_writer.write_png_direct(p_bc, np.full((2, 2, 4), 255, dtype=np.uint8))
        assert png_writer.write_png_direct(p_norm_big, np.full((4, 4, 4), 128, dtype=np.uint8))
        assert png_writer.write_png_direct(p_norm_ok, np.full((2, 2, 4), 128, dtype=np.uint8))
        assert png_writer.write_png_direct(p_orm_big, np.full((4, 4, 4), 200, dtype=np.uint8))

        with pytest.raises(ValueError, match="Normal texture dimensions"):
            ImpostorTextureRepacker.repack_impostor_textures(
                CanonicalImpostorSources("Bad", p_bc, p_norm_big, ""), str(tmp_path / "out1"), "UE5"
            )
        with pytest.raises(ValueError, match="ORM texture dimensions"):
            ImpostorTextureRepacker.repack_impostor_textures(
                CanonicalImpostorSources("Bad", p_bc, p_norm_ok, p_orm_big), str(tmp_path / "out2"), "UE5"
            )
