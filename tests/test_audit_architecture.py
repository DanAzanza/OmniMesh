"""Unit and negative boundary tests for scripts/audit_architecture.py."""

from __future__ import annotations

from pathlib import Path

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
