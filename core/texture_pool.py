"""
OmniMesh Background Texture Pool Manager.
Provides thread-safe multi-threaded image compression, background disk writes,
and synchronous join barriers with native memory compaction.
"""

from __future__ import annotations

import atexit
import concurrent.futures
import ctypes
import gc
import logging
import os
import sys
import threading
from typing import Optional
import numpy as np

try:
    from .png_writer import write_png_direct
except ImportError:
    from core.png_writer import write_png_direct

logger = logging.getLogger(__name__)


class TexturePoolManager:
    """Manages background multi-threaded texture compression and disk writes with thread safety."""

    _executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_executor(cls) -> concurrent.futures.ThreadPoolExecutor:
        with cls._lock:
            if cls._executor is None:
                max_w = min(4, max(1, os.cpu_count() or 2))
                cls._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_w, thread_name_prefix="OmniMesh_TexPool"
                )
            return cls._executor

    @classmethod
    def submit_save(cls, arr: np.ndarray, filepath: str, bit_depth: int = 8) -> concurrent.futures.Future[bool]:
        """Submits numpy array for parallel PNG compression and saving."""
        if arr is None or not isinstance(arr, np.ndarray) or arr.size == 0 or not filepath:
            f: concurrent.futures.Future[bool] = concurrent.futures.Future()
            f.set_result(False)
            return f

        try:
            executor = cls.get_executor()
            return executor.submit(write_png_direct, filepath, arr, bit_depth)
        except RuntimeError:
            with cls._lock:
                cls._executor = None
            executor = cls.get_executor()
            return executor.submit(write_png_direct, filepath, arr, bit_depth)

    @classmethod
    def wait_all(cls, futures: list[concurrent.futures.Future[bool]], timeout: float = 60.0) -> list[bool]:
        """Synchronous barrier ensuring all background texture writes are completed safely."""
        if not futures:
            return []

        results: list[bool] = []
        try:
            done, not_done = concurrent.futures.wait(
                futures, timeout=timeout, return_when=concurrent.futures.ALL_COMPLETED
            )
            for f in futures:
                if f in done:
                    try:
                        res = f.result(timeout=0.01)
                        results.append(bool(res))
                    except Exception as exc:
                        logger.error("Texture pool worker raised exception: %s", exc)
                        results.append(False)
                else:
                    logger.warning("Texture pool worker timed out before completion.")
                    results.append(False)
        except Exception as exc:
            logger.error("Exception in TexturePoolManager.wait_all: %s", exc)
        finally:
            cls.compact_memory()

        return results

    @staticmethod
    def compact_memory() -> None:
        """Force OS-level heap compaction to prevent memory fragmentation."""
        gc.collect()
        if sys.platform == "win32":
            try:
                ctypes.cdll.msvcrt._heapmin()
            except (AttributeError, OSError) as exc:
                logger.debug("Win32 heap compaction skipped: %s", exc)
        elif sys.platform.startswith("linux"):
            try:
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except (AttributeError, OSError) as exc:
                logger.debug("Linux malloc_trim skipped: %s", exc)

    @classmethod
    def shutdown(cls) -> None:
        with cls._lock:
            if cls._executor:
                try:
                    cls._executor.shutdown(wait=True)
                except Exception as exc:
                    logger.debug("Texture pool shutdown exception: %s", exc)
                cls._executor = None


atexit.register(TexturePoolManager.shutdown)
