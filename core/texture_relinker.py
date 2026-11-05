"""
OmniMesh Project Texture Verification & Relinking Engine.
Provides high-performance, multimap-indexed discovery and automatic relinking
of missing, broken, or external project textures across nested directories.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import bpy
    from bpy.types import BlendData
else:
    try:
        import bpy
    except ImportError:
        bpy = None
        BlendData = object

logger = logging.getLogger(__name__)

# Directory names pruned during recursive descent to ensure fast I/O
IGNORED_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".idea",
        ".vscode",
        "_packageint",
        "intermediate",
        "binaries",
        "saved",
        "deriveddatacache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

# Standard recognized 2D texture extensions
SUPPORTED_TEXTURE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".dds",
        ".jpg",
        ".jpeg",
        ".tga",
        ".tif",
        ".tiff",
        ".bmp",
        ".webp",
        ".exr",
        ".hdr",
    }
)

# Extension aliases for cross-format fallbacks (e.g. MSFS glTF .png -> engine .dds / .png.dds)
EXTENSION_FALLBACKS: dict[str, tuple[str, ...]] = {
    ".png": (".dds", ".png.dds", ".tga", ".jpg"),
    ".dds": (".png", ".png.dds", ".tga"),
    ".jpg": (".png", ".dds", ".jpeg"),
    ".jpeg": (".jpg", ".png", ".dds"),
    ".tga": (".png", ".dds"),
    ".tif": (".tiff", ".png", ".dds"),
    ".tiff": (".tif", ".png", ".dds"),
}


@dataclass(frozen=True)
class RelinkSummary:
    """Immutable audit and execution summary of texture verification and relinking."""

    total_checked: int = 0
    already_valid: int = 0
    relinked: int = 0
    missing_unresolved: int = 0
    relinked_pairs: tuple[tuple[str, str], ...] = ()


class ProjectTextureRelinker:
    """High-performance indexer and relinker for project asset textures."""

    @staticmethod
    def is_image_valid(
        img: bpy.types.Image | None,
        blend_filepath: str | None = None,
        *,
        blend_data: BlendData,
    ) -> bool:
        """Determines if a Blender Image datablock has valid pixel data or exists on disk."""
        if img is None:
            return False

        # Generated procedural canvases or render results
        if getattr(img, "source", "") in ("GENERATED", "VIEWER"):
            return True

        # Packed internal textures
        if getattr(img, "packed_file", None) is not None:
            return True
        packed_files = getattr(img, "packed_files", None)
        if packed_files is not None and len(packed_files) > 0:
            return True

        raw_filepath = getattr(img, "filepath", "")
        if not raw_filepath:
            return False

        # Evaluate absolute path
        abs_path = ProjectTextureRelinker.resolve_absolute_image_path(
            raw_filepath, blend_filepath, blend_data=blend_data
        )
        if not abs_path:
            return False

        return os.path.isfile(abs_path)

    @staticmethod
    def resolve_absolute_image_path(
        raw_filepath: str,
        blend_filepath: str | None = None,
        *,
        blend_data: BlendData,
    ) -> str:
        """Converts a Blender relative or absolute path into a normalized filesystem path."""
        if not raw_filepath:
            return ""

        if raw_filepath.startswith("//"):
            base_dir = ""
            if blend_filepath:
                base_dir = os.path.dirname(blend_filepath)
            elif blend_data and getattr(blend_data, "filepath", None):
                base_dir = os.path.dirname(blend_data.filepath)

            if base_dir:
                rel_part = raw_filepath[2:].lstrip("/\\")
                return os.path.normpath(os.path.join(base_dir, rel_part))

        if bpy and hasattr(bpy, "path") and hasattr(bpy.path, "abspath"):
            try:
                return os.path.normpath(bpy.path.abspath(raw_filepath))
            except (RuntimeError, ValueError, TypeError, OSError):
                pass

        return os.path.normpath(raw_filepath)

    @staticmethod
    def build_texture_index(
        search_roots: Sequence[Path | str],
        max_depth: int = 5,
    ) -> dict[str, list[Path]]:
        """Recursively indexes all recognized texture files into a case-insensitive multimap.

        Returns a dictionary mapping lowercased filename (e.g. 'albedo.png')
        to a list of absolute Path objects.
        """
        index: dict[str, list[Path]] = {}

        for root in search_roots:
            root_path = Path(root).resolve()
            if not root_path.is_dir():
                continue

            root_depth = len(root_path.parts)

            for dirpath, dirnames, filenames in os.walk(str(root_path), followlinks=False):
                current_parts = Path(dirpath).parts
                depth = len(current_parts) - root_depth
                if depth >= max_depth:
                    dirnames.clear()
                    continue

                # In-place directory pruning
                dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_DIRECTORIES]

                for fname in filenames:
                    fname_lower = fname.lower()
                    # Check single or double extensions (.png or .png.dds)
                    is_texture = any(
                        fname_lower.endswith(ext) for ext in SUPPORTED_TEXTURE_EXTENSIONS
                    ) or fname_lower.endswith(".png.dds")

                    if not is_texture:
                        continue

                    full_path = Path(dirpath, fname)
                    if fname_lower not in index:
                        index[fname_lower] = []
                    index[fname_lower].append(full_path)

        return index

    @staticmethod
    def score_candidate(candidate: Path, original_filepath: str) -> int:
        """Scores candidate path against original filepath based on folder hierarchy similarity.

        Higher score denotes higher match confidence.
        """
        norm_orig = original_filepath.replace("\\", "/").lower()
        orig_parts = set(p for p in norm_orig.split("/") if p and p != "..")

        cand_parts = set(p.lower() for p in candidate.parts)
        # Shared directory names count positively towards match confidence
        common = orig_parts.intersection(cand_parts)
        score = len(common) * 10

        # Bonus for standard texture folder proximity
        if any(folder in cand_parts for folder in ("textures", "texture", "tex")):
            score += 5

        return score

    @staticmethod
    def find_matching_file(
        filename: str,
        original_filepath: str,
        texture_index: dict[str, list[Path]],
    ) -> Path | None:
        """Finds the best matching path from the texture index, supporting extension aliases."""
        clean_name = filename.strip().lower()
        if not clean_name:
            return None

        # 1. Exact filename match
        candidates = texture_index.get(clean_name)

        # 2. Extension alias fallback (.png -> .dds / .png.dds)
        if not candidates:
            dot_idx = clean_name.rfind(".")
            if dot_idx != -1:
                base_stem = clean_name[:dot_idx]
                ext = clean_name[dot_idx:]
                fallbacks = EXTENSION_FALLBACKS.get(ext, ())
                for alt_ext in fallbacks:
                    alt_candidates = texture_index.get(f"{base_stem}{alt_ext}")
                    if alt_candidates:
                        candidates = alt_candidates
                        break

        if not candidates:
            return None

        if len(candidates) == 1:
            return candidates[0]

        # Multi-match disambiguation
        scored = sorted(
            candidates,
            key=lambda c: ProjectTextureRelinker.score_candidate(c, original_filepath),
            reverse=True,
        )
        return scored[0]

    @staticmethod
    def _split_drive_portable(p: str) -> tuple[str, str]:
        """Splits drive letter portably across Windows and POSIX platforms."""
        drive, rest = os.path.splitdrive(p)
        if drive:
            return drive, rest
        if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
            return p[:2], p[2:]
        return "", p

    @staticmethod
    def make_relative_path(target_path: Path, blend_filepath: str | None) -> str:
        """Safely formats path relative to blend file if available, falling back to absolute."""
        if not blend_filepath:
            return str(target_path)

        try:
            target_str = str(target_path)
            blend_str = str(blend_filepath)

            target_drive, _ = ProjectTextureRelinker._split_drive_portable(target_str)
            blend_drive, _ = ProjectTextureRelinker._split_drive_portable(blend_str)

            # Different drives cannot be relative
            if target_drive.lower() != blend_drive.lower():
                return str(target_path)

            if not blend_drive and not os.path.isabs(blend_str):
                blend_dir = os.path.dirname(os.path.abspath(blend_str))
            else:
                blend_dir = os.path.dirname(blend_str)

            if not blend_dir:
                return str(target_path)

            # On POSIX with Windows drive letters, strip drive prefixes for relpath
            if target_drive and os.name != "nt":
                t_no_drive = target_str[len(target_drive) :].replace("\\", "/")
                b_no_drive = blend_dir[len(blend_drive) :].replace("\\", "/")
                rel_str = os.path.relpath(t_no_drive, b_no_drive)
            else:
                rel_str = os.path.relpath(target_str, blend_dir)

            norm_rel = rel_str.replace("\\", "/")
            return f"//{norm_rel}"
        except (ValueError, RuntimeError, OSError):
            return str(target_path)

    @classmethod
    def relink_images(
        cls,
        images: Sequence[bpy.types.Image],
        search_roots: Sequence[Path | str],
        blend_filepath: str | None = None,
        make_relative: bool = True,
        max_depth: int = 5,
        *,
        blend_data: BlendData,
    ) -> RelinkSummary:
        """Audits images and relinks any missing files discovered within search roots."""
        if not images or not search_roots:
            return RelinkSummary()

        resolved_blend_path = blend_filepath or (getattr(blend_data, "filepath", None) if blend_data else None)

        # Filter candidates needing relinking
        missing_images: list[tuple[bpy.types.Image, str]] = []
        already_valid = 0

        for img in images:
            if cls.is_image_valid(img, resolved_blend_path, blend_data=blend_data):
                already_valid += 1
                continue

            raw_path = getattr(img, "filepath", "")
            fname = os.path.basename(raw_path) or getattr(img, "name", "")
            if fname:
                missing_images.append((img, fname))

        if not missing_images:
            return RelinkSummary(
                total_checked=len(images),
                already_valid=already_valid,
                relinked=0,
                missing_unresolved=0,
                relinked_pairs=(),
            )

        # Build index once for the entire batch
        texture_index = cls.build_texture_index(search_roots, max_depth=max_depth)

        relinked_pairs: list[tuple[str, str]] = []
        unresolved_count = 0

        for img, fname in missing_images:
            raw_path = getattr(img, "filepath", "")
            match = cls.find_matching_file(fname, raw_path, texture_index)

            if match is None:
                unresolved_count += 1
                continue

            # Compute target path string
            if make_relative:
                new_path_str = cls.make_relative_path(match, resolved_blend_path)
            else:
                new_path_str = str(match)

            try:
                img.filepath = new_path_str
                # Reload buffers into Blender memory
                reload_fn = getattr(img, "reload", None)
                if callable(reload_fn):
                    try:
                        reload_fn()
                    except RuntimeError as exc:
                        logger.warning("Could not reload image buffer '%s': %s", img.name, exc)
                relinked_pairs.append((img.name, new_path_str))
            except (RuntimeError, TypeError, ValueError, AttributeError, OSError) as exc:
                logger.warning("Failed assigning relinked path to image '%s': %s", img.name, exc)
                unresolved_count += 1

        return RelinkSummary(
            total_checked=len(images),
            already_valid=already_valid,
            relinked=len(relinked_pairs),
            missing_unresolved=unresolved_count,
            relinked_pairs=tuple(relinked_pairs),
        )
