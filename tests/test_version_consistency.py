"""Tests for synchronized Blender extension version metadata."""

from __future__ import annotations

import ast
from pathlib import Path
import tomllib

from scripts.build_extension import get_version


REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_bl_info_version() -> tuple[int, ...]:
    source = (REPO_ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "bl_info" for target in node.targets
        ):
            bl_info = ast.literal_eval(node.value)
            return tuple(bl_info["version"])
    raise AssertionError("bl_info assignment not found")


def test_extension_versions_are_consistent() -> None:
    with (REPO_ROOT / "blender_manifest.toml").open("rb") as manifest_file:
        manifest = tomllib.load(manifest_file)

    manifest_version = str(manifest["version"])
    expected_bl_info = tuple(int(part) for part in manifest_version.split("."))

    assert get_version(REPO_ROOT) == manifest_version
    assert _read_bl_info_version() == expected_bl_info


def test_manifest_version_matches_latest_release_tag() -> None:
    release_tags = sorted(
        (tag.name.removeprefix("v") for tag in REPO_ROOT.glob(".git/refs/tags/v*")),
        key=lambda value: tuple(int(part) for part in value.split(".")),
    )
    if release_tags:
        with (REPO_ROOT / "blender_manifest.toml").open("rb") as manifest_file:
            manifest = tomllib.load(manifest_file)
        assert str(manifest["version"]) == release_tags[-1]
