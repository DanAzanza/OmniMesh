"""Atomic file I/O helpers with Windows file-lock retry backoff and temp cleanup."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

logger = logging.getLogger(__name__)

DEFAULT_RETRY_DELAYS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4)
_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str, fallback: str = "Asset") -> str:
    """Replaces filesystem-unsafe characters in ``name`` with underscores."""
    cleaned = _INVALID_FILENAME_CHARS_RE.sub("_", str(name or "")).strip(" .")
    return cleaned or fallback


def split_drive_portable(path_str: str) -> tuple[str, str]:
    """Splits a Windows drive letter portably across Windows and POSIX platforms."""
    drive, rest = os.path.splitdrive(path_str)
    if drive:
        return drive, rest
    if len(path_str) >= 2 and path_str[1] == ":" and path_str[0].isalpha():
        return path_str[:2], path_str[2:]
    return "", path_str


def resolve_blender_path(
    raw_filepath: str,
    blend_filepath: str | None = None,
    *,
    abspath_fn: Callable[[str], str] | None = None,
    fallback_raw_on_unsaved: bool = False,
) -> str:
    """Resolves a Blender relative (``//``) or standard path without Windows UNC stalls on unsaved scenes."""
    if not raw_filepath:
        return ""

    if raw_filepath.startswith("//"):
        base_dir = os.path.dirname(blend_filepath) if blend_filepath else ""
        if base_dir:
            rel_part = raw_filepath[2:].lstrip("/\\")
            return os.path.normpath(os.path.join(base_dir, rel_part))
        return os.path.normpath(raw_filepath) if fallback_raw_on_unsaved else ""

    if abspath_fn is not None:
        try:
            return os.path.normpath(abspath_fn(raw_filepath))
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            logger.debug("Blender path abspath fallback for '%s': %s", raw_filepath, exc)

    return os.path.normpath(raw_filepath)


def create_timestamped_backup(file_path: Path | str) -> Path | None:
    """Creates a timestamped ``.bak_YYYYMMDD_HHMMSS`` sibling backup if ``file_path`` exists."""
    src = Path(file_path)
    if not src.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = src.with_name(f"{src.name}.bak_{stamp}")
    shutil.copy2(src, backup_path)
    return backup_path


def detect_text_file_format(file_path: Path | str) -> tuple[str, bool, str]:
    """Detects encoding (UTF-8/16 BOM or CP1252 fallback), BOM presence, and line ending."""
    raw = Path(file_path).read_bytes()

    if raw.startswith(b"\xef\xbb\xbf"):
        has_bom = True
        encoding = "utf-8-sig"
    elif raw.startswith(b"\xff\xfe"):
        has_bom = True
        encoding = "utf-16-le"
    elif raw.startswith(b"\xfe\xff"):
        has_bom = True
        encoding = "utf-16-be"
    else:
        has_bom = False
        try:
            raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            encoding = "cp1252"

    newline_style = "\r\n" if b"\r\n" in raw else "\n"
    return encoding, has_bom, newline_style


def _cleanup_temp_file(tmp_path: str) -> None:
    """Removes a leftover temporary file, logging a warning if deletion fails."""
    if not os.path.exists(tmp_path):
        return
    try:
        os.remove(tmp_path)
    except OSError as exc:
        logger.warning("Failed to remove temporary file '%s': %s", tmp_path, exc)


def _replace_with_retry(
    tmp_path: str,
    target_path: Path,
    retry_delays: tuple[float, ...],
) -> None:
    """Replaces ``target_path`` atomically, backing off across transient lock errors."""
    attempts = len(retry_delays) + 1
    for attempt in range(attempts):
        try:
            os.replace(tmp_path, target_path)
            return
        except OSError:
            if attempt >= len(retry_delays):
                raise
            time.sleep(retry_delays[attempt])


def _write_temp_and_replace(
    target_path: Path | str,
    payload: str | Sequence[str] | bytes | bytearray,
    *,
    mode: str,
    encoding: str | None = None,
    newline: str | None = None,
    prefix: str = "omnimesh_",
    suffix: str = ".tmp",
    sync: bool = False,
    create_parents: bool = False,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> None:
    """Creates a sibling temp file, writes ``payload``, and atomically replaces target."""
    dest = Path(target_path)
    if create_parents:
        dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode=mode,
            dir=str(dest.parent),
            prefix=prefix,
            suffix=suffix,
            encoding=encoding,
            newline=newline,
            delete=False,
        ) as handle:
            tmp_path = handle.name
            if isinstance(payload, (bytes, bytearray, str)):
                handle.write(payload)
            else:
                handle.writelines(payload)
            if sync:
                handle.flush()
                os.fsync(handle.fileno())
        _replace_with_retry(tmp_path, dest, retry_delays)
    finally:
        if tmp_path is not None:
            _cleanup_temp_file(tmp_path)


def atomic_write_text(
    target_path: Path | str,
    content: str | Sequence[str],
    *,
    encoding: str = "utf-8",
    newline: str | None = None,
    prefix: str = "omnimesh_",
    suffix: str = ".tmp",
    sync: bool = False,
    create_parents: bool = False,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> None:
    """Atomically writes text or pre-formatted lines to ``target_path``."""
    _write_temp_and_replace(
        target_path,
        content,
        mode="w",
        encoding=encoding,
        newline=newline,
        prefix=prefix,
        suffix=suffix,
        sync=sync,
        create_parents=create_parents,
        retry_delays=retry_delays,
    )


def atomic_write_bytes(
    target_path: Path | str,
    data: bytes | bytearray,
    *,
    prefix: str = "omnimesh_",
    suffix: str = ".tmp",
    sync: bool = False,
    create_parents: bool = False,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> None:
    """Atomically writes raw bytes to ``target_path`` using sibling temp replacement."""
    _write_temp_and_replace(
        target_path,
        data,
        mode="wb",
        prefix=prefix,
        suffix=suffix,
        sync=sync,
        create_parents=create_parents,
        retry_delays=retry_delays,
    )
