"""Unit and negative boundary tests for core.io_utils atomic write helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from core.io_utils import atomic_write_bytes, atomic_write_text


def test_atomic_write_text_writes_string_and_creates_parents(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "config.json"
    atomic_write_text(target, '{"ok": true}', create_parents=True, sync=True)

    assert target.read_text(encoding="utf-8") == '{"ok": true}'
    assert [p.name for p in target.parent.iterdir()] == ["config.json"]


def test_atomic_write_text_preserves_lines_encoding_and_crlf(tmp_path: Path) -> None:
    target = tmp_path / "aircraft.cfg"
    lines = ["[WEIGHT_AND_BALANCE]\r\n", "station_load.0 = 170, 0, 0, 0 ; Pilot\r\n"]

    atomic_write_text(target, lines, encoding="utf-8-sig", newline="", sync=True)

    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" in raw
    assert raw.decode("utf-8-sig") == "".join(lines)


def test_atomic_write_bytes_writes_exact_payload(tmp_path: Path) -> None:
    target = tmp_path / "model.xml"
    payload = b"\xef\xbb\xbf<ModelInfo/>\n"

    atomic_write_bytes(target, payload, create_parents=True, sync=True)

    assert target.read_bytes() == payload
    assert [p.name for p in target.parent.iterdir()] == ["model.xml"]


def test_atomic_write_retries_transient_lock_and_succeeds(tmp_path: Path) -> None:
    target = tmp_path / "locked.txt"
    calls = {"count": 0}
    real_replace = __import__("os").replace

    def flaky_replace(src: str, dst: Path) -> None:
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("Simulated transient AV lock")
        real_replace(src, dst)

    with (
        patch("core.io_utils.os.replace", side_effect=flaky_replace),
        patch("core.io_utils.time.sleep") as mock_sleep,
    ):
        atomic_write_text(target, "recovered", retry_delays=(0.01, 0.02, 0.04))

    assert calls["count"] == 3
    assert mock_sleep.call_count == 2
    assert target.read_text(encoding="utf-8") == "recovered"
    assert [p.name for p in tmp_path.iterdir()] == ["locked.txt"]


def test_atomic_write_cleans_up_temp_file_when_retries_exhausted(tmp_path: Path) -> None:
    target = tmp_path / "persistent_lock.txt"
    target.write_text("original", encoding="utf-8")

    with (
        patch("core.io_utils.os.replace", side_effect=PermissionError("Locked permanently")),
        patch("core.io_utils.time.sleep") as mock_sleep,
        pytest.raises(PermissionError, match="Locked permanently"),
    ):
        atomic_write_text(target, "replacement", retry_delays=(0.01, 0.02))

    assert mock_sleep.call_count == 2
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["persistent_lock.txt"]


def test_atomic_write_closes_fd_and_cleans_up_when_fdopen_fails(tmp_path: Path) -> None:
    target = tmp_path / "bad_encoding.txt"

    with pytest.raises(LookupError):
        atomic_write_text(target, "payload", encoding="nonexistent-encoding-xyz")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_logs_warning_if_temp_cleanup_fails(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    target = tmp_path / "cleanup_warn.txt"
    caplog.set_level(logging.WARNING)

    with (
        patch("core.io_utils.os.replace", side_effect=OSError("replace boom")),
        patch("core.io_utils.os.remove", side_effect=PermissionError("unlink locked")),
        pytest.raises(OSError, match="replace boom"),
    ):
        atomic_write_bytes(target, b"abc", retry_delays=())

    assert "Failed to remove temporary file" in caplog.text
    # Remove leaked test temp file cleanly
    for extra in tmp_path.iterdir():
        if extra != target:
            extra.unlink()
