"""Atomic file I/O helpers with Windows file-lock retry backoff and temp cleanup."""

from __future__ import annotations

from collections.abc import Sequence
import logging
import os
from pathlib import Path
import tempfile
import time

logger = logging.getLogger(__name__)

DEFAULT_RETRY_DELAYS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4)


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
