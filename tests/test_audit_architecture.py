"""Unit and negative boundary tests for scripts/audit_architecture.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_architecture import scan_repository


def test_audit_passes_clean_core_module(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "clean.py").write_text(
        "from __future__ import annotations\ndef run_op(context: object) -> bool:\n    return context is not None\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    assert violations["context_leak_in_core_exporters"] == []
    assert violations["bare_except_pass"] == []
    assert violations["deprecated_blender_apis"] == []


def test_audit_catches_direct_and_obfuscated_bpy_context_in_core(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "leaky.py").write_text(
        "import bpy\n"
        "from bpy import context\n"
        "def bad_access(ctx=None):\n"
        "    a = bpy.context.scene\n"
        '    b = getattr(bpy, "context", None)\n'
        '    c = getattr(getattr(bpy, "context", None), "scene", None)\n'
        "    return a, b, c\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    leaks = violations["context_leak_in_core_exporters"]
    assert len(leaks) == 4
    reasons = [item[2] for item in leaks]
    assert "from bpy import context" in reasons
    assert "bpy.context" in reasons
    assert reasons.count('getattr(..., "context")') == 2


def test_audit_catches_bare_and_log_only_except_swallowing(tmp_path: Path) -> None:
    exp_dir = tmp_path / "exporters"
    exp_dir.mkdir(parents=True)
    (exp_dir / "swallow.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def bad_exceptions():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception:\n"
        "        pass\n"
        "    try:\n"
        "        risky()\n"
        "    except (ValueError, Exception) as exc:\n"
        '        logger.debug("Swallowed: %s", exc)\n'
        "    try:\n"
        "        risky()\n"
        "    except (RuntimeError, AttributeError) as exc:\n"
        '        logger.debug("Narrow exception is allowed: %s", exc)\n',
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    swallowed = violations["bare_except_pass"]
    assert len(swallowed) == 2
    assert swallowed[0][2] == "Exception (pass)"
    assert swallowed[1][2] == "Exception (log-only)"


def test_audit_catches_file_length_over_750(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    oversized_lines = "\n".join(f"x_{i} = {i}" for i in range(755))
    (core_dir / "oversized.py").write_text(oversized_lines + "\n", encoding="utf-8")

    violations = scan_repository(tmp_path)
    assert violations["file_length_over_750"] == [("core/oversized.py", 755)]


def test_audit_catches_broad_except_and_any_in_core_signatures(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "bad_sig.py").write_text(
        "from typing import Any\n"
        "def process_mesh(obj: Any, meta: dict[str, Any]) -> list[Any]:\n"
        "    try:\n"
        "        return [obj]\n"
        "    except Exception as exc:\n"
        "        raise RuntimeError(str(exc)) from exc\n",
        encoding="utf-8",
    )

    violations = scan_repository(tmp_path)
    assert len(violations["broad_except_in_core_exporters"]) == 1
    assert violations["broad_except_in_core_exporters"][0][2] == "Exception"
    sig_violations = violations["any_in_core_exporter_signatures"]
    assert len(sig_violations) == 2
    assert "process_mesh(obj: Any)" in str(sig_violations[0][2])
    assert "process_mesh() -> list[Any]" in str(sig_violations[1][2])


def test_audit_catches_any_in_local_variable_annotations(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "bad_assign.py").write_text(
        "from typing import Any\n"
        "def run_stuff():\n"
        "    x: Any = 123\n"
        "    y: list[Any] = []\n"
        "    z: dict[str, Any] = {}\n",
        encoding="utf-8",
    )

    violations = scan_repository(tmp_path)
    sig_violations = violations["any_in_core_exporter_signatures"]
    assert len(sig_violations) == 2
    assert "x: Any" in str(sig_violations[0][2])
    assert "y: list[Any]" in str(sig_violations[1][2])


def test_audit_catches_unallowed_cast_any_and_evasions(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    (core_dir / "cast_module.py").write_text(
        "import typing\n"
        "from typing import cast, Any\n"
        "def bad_casts(obj, x):\n"
        "    a = cast(Any, obj.foo)\n"
        "    b = typing.cast(typing.Any, obj.bar)\n"
        "    c = cast('Any', obj.baz)\n"
        "    return a, b, c\n",
        encoding="utf-8",
    )

    violations = scan_repository(tmp_path)
    cast_violations = violations["unallowed_cast_any_in_core_exporters"]
    assert len(cast_violations) == 3
    reasons = [item[2] for item in cast_violations]
    assert any("cast(Any, obj.foo)" in str(r) for r in reasons)
    assert any("cast(Any, obj.bar)" in str(r) for r in reasons)
    assert any("cast(Any, obj.baz)" in str(r) for r in reasons)


def test_audit_catches_bpy_data_and_ignores_obj_data(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    # File with standard obj.data which must NOT trigger bpy.data
    (core_dir / "normal_mesh_access.py").write_text(
        "def inspect_mesh(obj):\n    d = obj.data\n    d2 = getattr(obj, 'data', None)\n    return d, d2\n",
        encoding="utf-8",
    )

    violations = scan_repository(tmp_path)
    assert violations["bpy_data_ratchet_in_core_exporters"] == []

    # File with direct and indirect bpy.data
    (core_dir / "leaky_db.py").write_text(
        "import bpy\n"
        "from bpy import data\n"
        "def get_mats():\n"
        "    m1 = bpy.data.materials\n"
        "    m2 = getattr(bpy, 'data')\n"
        "    return m1, m2\n",
        encoding="utf-8",
    )

    # With baseline locked at 0, any references violate the ratchet
    violations2 = scan_repository(tmp_path)
    assert len(violations2["bpy_data_ratchet_in_core_exporters"]) == 1
    assert "bpy.data references (3) exceed ratchet baseline (0)" in str(
        violations2["bpy_data_ratchet_in_core_exporters"][0][2]
    )


def test_audit_catches_context_blend_data_leak_in_core(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True)
    # File with legitimate self.blend_data
    (core_dir / "clean_instance.py").write_text(
        "class Rig:\n    def __init__(self, bdata):\n        self.blend_data = bdata\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    assert violations["context_blend_data_leak_in_core"] == []

    # File with context.blend_data backdoors
    (core_dir / "leaky_blend_data.py").write_text(
        "def bad(context, ctx):\n"
        "    a = context.blend_data\n"
        "    b = ctx.blend_data\n"
        '    c = getattr(context, "blend_data", None)\n'
        "    return a, b, c\n",
        encoding="utf-8",
    )
    violations2 = scan_repository(tmp_path)
    leaks = violations2["context_blend_data_leak_in_core"]
    assert len(leaks) == 3


def test_audit_catches_ui_import_layer_violations(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "bad_import.py").write_text(
        "from ui.utils import get_asset_base_meshes\nimport ui\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    ui_violations = violations["layer_violation_ui_in_core_exporters"]
    assert len(ui_violations) == 2


def test_audit_catches_hasattr_blend_data_leak(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "bad_hasattr.py").write_text(
        "def bad(blend_data, obj):\n"
        '    if hasattr(blend_data, "collections"):\n'
        "        pass\n"
        '    if hasattr(obj, "blend_data"):\n'
        "        pass\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    leaks = violations["hasattr_blend_data_leak_in_core_exporters"]
    assert len(leaks) == 2


def test_audit_catches_hasattr_ratchet_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.audit_architecture as audit_mod

    monkeypatch.setattr(audit_mod, "HASATTR_RATCHET_BASELINE", 1)

    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "hasattr_mod.py").write_text(
        'def check(o):\n    return hasattr(o, "a") and hasattr(o, "b")\n',
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    ratchet = violations["hasattr_ratchet_in_core_exporters"]
    assert len(ratchet) == 1
    assert "exceed ratchet baseline" in str(ratchet[0][2])


def test_audit_catches_getattr_ratchet_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.audit_architecture as audit_mod

    monkeypatch.setattr(audit_mod, "GETATTR_RATCHET_BASELINE", 1)

    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "getattr_mod.py").write_text(
        'def check(o):\n    return getattr(o, "a", 1) + getattr(o, "b", 2)\n',
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    ratchet = violations["getattr_ratchet_in_core_exporters"]
    assert len(ratchet) == 1
    assert "exceed ratchet baseline" in str(ratchet[0][2])


def test_audit_catches_optional_blend_data_in_core(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "optional_bdata.py").write_text(
        "def bad1(*, blend_data: BlendData | None = None):\n"
        "    pass\n"
        "def bad2(blend_data: BlendData | None):\n"
        "    pass\n"
        "def good(*, blend_data: BlendData):\n"
        "    pass\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    opt_violations = violations["optional_blend_data_in_core"]
    assert len(opt_violations) == 2


def test_audit_catches_log_only_except_ratchet_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.audit_architecture as audit_mod

    monkeypatch.setattr(audit_mod, "LOG_ONLY_EXCEPT_RATCHET_BASELINE", 1)

    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "swallow_mod.py").write_text(
        "import logging\n"
        "logger = logging.getLogger(__name__)\n"
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except RuntimeError as e:\n"
        "        logger.debug('err1: %s', e)\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError as e:\n"
        "        logger.debug('err2: %s', e)\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    ratchet = violations["log_only_except_ratchet_in_core_exporters"]
    assert len(ratchet) == 1
    assert "exceed ratchet baseline" in str(ratchet[0][2])


def test_audit_catches_except_pass_ratchet_overflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.audit_architecture as audit_mod

    monkeypatch.setattr(audit_mod, "EXCEPT_PASS_RATCHET_BASELINE", 1)

    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "except_pass_mod.py").write_text(
        "def f():\n"
        "    try:\n"
        "        pass\n"
        "    except RuntimeError:\n"
        "        pass\n"
        "    try:\n"
        "        pass\n"
        "    except ValueError:\n"
        "        pass\n",
        encoding="utf-8",
    )
    violations = scan_repository(tmp_path)
    ratchet = violations["except_pass_ratchet_in_core_exporters"]
    assert len(ratchet) == 1
    assert "exceed ratchet baseline" in str(ratchet[0][2])
