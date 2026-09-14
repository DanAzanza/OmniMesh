"""
OmniMesh Import Refactoring Script v2.
Safe, AST-aware rewriter that handles all known patterns.

Strategy per try/except block:
  - Collect all import lines (both in try and except body)
  - Deduplicate by what is being imported (same module + names)
  - Keep ONLY the relative-import version of each pair
  - If ONLY absolute imports exist (no relative counterpart), rewrite them to relative

Run from repo root:
    python scripts/fix_imports.py [--dry-run]
"""

from __future__ import annotations

import pathlib
import re
import sys
from typing import NamedTuple

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = ("core", "ui", "exporters", "bridges")
EXCLUDE_DIRS = {"tests", "scripts", ".agents", "__pycache__", ".git", "dist"}


# ---------------------------------------------------------------------------
# Relative prefix calculation
# ---------------------------------------------------------------------------


def relative_prefix(from_file: pathlib.Path, to_package: str) -> str:
    """Return the dotted relative prefix to reach `to_package` from `from_file`."""
    parts = from_file.relative_to(REPO_ROOT).parts  # e.g. ('ui', 'properties', 'cb.py')
    depth = len(parts) - 1  # directory levels below root
    from_pkg = parts[0]
    if from_pkg == to_package:
        return "."
    dots = "." * (depth + 1)
    return f"{dots}{to_package}"


def rewrite_abs_to_rel(line: str, from_file: pathlib.Path) -> str:
    """Convert one absolute import line to relative. Returns line unchanged if not an abs import."""
    m = re.match(r"^(\s*)from (core|ui|exporters|bridges)((?:\.\S+)?)\s+import", line)
    if not m:
        return line
    indent, to_pkg, subpath = m.group(1), m.group(2), m.group(3)
    prefix = relative_prefix(from_file, to_pkg)
    new_from = f"{prefix}{subpath}"
    return re.sub(
        r"^(\s*)from (core|ui|exporters|bridges)((?:\.\S+)?)\s+import",
        rf"{indent}from {new_from} import",
        line,
    )


def is_abs_import(line: str) -> bool:
    return bool(re.match(r"\s*from (core|ui|exporters|bridges)[. ]", line))


def is_rel_import(line: str) -> bool:
    return bool(re.match(r"\s*from \.", line))


# ---------------------------------------------------------------------------
# try/except block finder and transformer
# ---------------------------------------------------------------------------


class Block(NamedTuple):
    start: int  # index of 'try:' line
    try_end: int  # index of 'except' line
    end: int  # index of first line AFTER the block
    try_lines: list[str]
    except_lines: list[str]


def find_try_import_blocks(lines: list[str]) -> list[Block]:
    """Find all top-level or indented try/except (ImportError...) blocks."""
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not re.match(r"(\s*)try:\s*$", line):
            i += 1
            continue

        try_indent = len(line) - len(line.lstrip())
        try_start = i

        # Collect try body
        j = i + 1
        try_lines: list[str] = []
        while j < len(lines):
            bl = lines[j]
            stripped = bl.strip()
            if not stripped:
                try_lines.append(bl)
                j += 1
                continue
            cur_indent = len(bl) - len(bl.lstrip())
            if cur_indent <= try_indent:
                break
            try_lines.append(bl)
            j += 1

        # Expect except (ImportError...) or except ImportError
        if j >= len(lines):
            i += 1
            continue
        except_line = lines[j]
        if not re.match(r"\s*except (?:\(ImportError|ImportError)", except_line):
            i += 1
            continue

        except_start = j
        k = j + 1
        except_lines: list[str] = []
        while k < len(lines):
            bl = lines[k]
            stripped = bl.strip()
            if not stripped:
                except_lines.append(bl)
                k += 1
                continue
            cur_indent = len(bl) - len(bl.lstrip())
            if cur_indent <= try_indent:
                break
            except_lines.append(bl)
            k += 1

        blocks.append(
            Block(
                start=try_start,
                try_end=except_start,
                end=k,
                try_lines=try_lines,
                except_lines=except_lines,
            )
        )
        i = k

    return blocks


def process_try_except_block(
    block: Block,
    from_file: pathlib.Path,
    lines: list[str],
) -> list[str] | None:
    """
    Decide what to emit for this block. Returns new lines or None if no change.

    Rules:
      1. If try body has ONLY relative imports and except body has ONLY absolute imports
         => remove the except block, keep try body as-is.
      2. If try body has ONLY absolute imports and except body has ONLY relative imports
         => remove the try/except wrapper, keep the relative imports only.
      3. If try body has absolute imports and except has sentinels (= None assignments)
         => rewrite abs imports to rel, keep the except as safety net for sentinels.
      4. Nested double-try (Type B exporters): handled separately.
    """
    try_body = [line for line in block.try_lines if line.strip()]
    except_body = [line for line in block.except_lines if line.strip()]

    try_all_rel = try_body and all(is_rel_import(line) for line in try_body)
    try_all_abs = try_body and all(is_abs_import(line) for line in try_body)
    except_all_abs = except_body and all(is_abs_import(line) for line in except_body)
    except_all_rel = except_body and all(is_rel_import(line) for line in except_body)

    # Rule 1: Normal case - try=rel, except=abs (just remove except)
    if try_all_rel and except_all_abs:
        try_line = lines[block.start]
        result = [try_line]
        result.extend(block.try_lines)
        return result

    # Rule 2: Reversed case - try=abs, except=rel (keep only the rel imports)
    if try_all_abs and except_all_rel:
        result = list(block.except_lines)
        return result

    # Rule 3: try=abs, except has sentinels (= None or = object) mixed with abs or just sentinels
    if try_all_abs:
        # Rewrite the try body to relative, keep except for sentinels
        sentinel_lines = [line for line in except_body if not is_abs_import(line)]
        if sentinel_lines:
            try_line = lines[block.start]
            new_try_lines = [rewrite_abs_to_rel(line, from_file) for line in block.try_lines]
            except_kw = lines[block.try_end]
            new_except_lines = [line for line in block.except_lines if not is_abs_import(line) or not line.strip()]
            result = [try_line]
            result.extend(new_try_lines)
            result.append(except_kw)
            result.extend(new_except_lines)
            return result

    return None  # No change


def process_file(path: pathlib.Path) -> tuple[bool, str]:
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  [SKIP] Cannot read {path}: {e}")
        return False, ""

    lines = original.splitlines(keepends=True)
    blocks = find_try_import_blocks(lines)

    if not blocks:
        # Check for direct absolute imports (shim files like msfs_models.py)
        out_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped and is_abs_import(stripped) and not line.startswith(" ") and not line.startswith("\t"):
                out_lines.append(rewrite_abs_to_rel(line, path))
            else:
                out_lines.append(line)
        new_src = "".join(out_lines)
        return new_src != original, new_src

    # Process blocks from bottom to top to preserve line indices
    result_lines = list(lines)
    any_changed = False

    for block in reversed(blocks):
        new_block_lines = process_try_except_block(block, path, lines)
        if new_block_lines is not None:
            result_lines[block.start : block.end] = new_block_lines
            any_changed = True

    if not any_changed:
        # Still check for top-level absolute imports in shim files
        out: list[str] = []
        for line in result_lines:
            stripped = line.strip()
            if stripped and is_abs_import(stripped) and not line.startswith(" ") and not line.startswith("\t"):
                new_l = rewrite_abs_to_rel(line, path)
                out.append(new_l)
                if new_l != line:
                    any_changed = True
            else:
                out.append(line)
        result_lines = out

    # Also fix indented lazy imports inside function bodies
    final: list[str] = []
    for line in result_lines:
        if re.match(r"\s{4,}from (core|ui|exporters|bridges)[. ]", line) and "import" in line:
            new_l = rewrite_abs_to_rel(line, path)
            final.append(new_l)
            if new_l != line:
                any_changed = True
        else:
            final.append(line)

    new_src = "".join(final)
    return new_src != original, new_src


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    changed: list[pathlib.Path] = []
    target_files: list[pathlib.Path] = []
    for pkg in PACKAGES:
        pkg_dir = REPO_ROOT / pkg
        if pkg_dir.exists():
            for f in sorted(pkg_dir.rglob("*.py")):
                if not any(excl in f.parts for excl in EXCLUDE_DIRS):
                    target_files.append(f)

    print(f"OmniMesh Import Refactoring v2: {len(target_files)} files to inspect")
    print(f"Mode: {'DRY RUN' if dry_run else 'WRITE'}\n")

    for path in target_files:
        was_changed, new_content = process_file(path)
        if was_changed:
            changed.append(path)
            rel = path.relative_to(REPO_ROOT)
            if dry_run:
                print(f"  [WOULD CHANGE] {rel}")
            else:
                path.write_text(new_content, encoding="utf-8")
                print(f"  [CHANGED] {rel}")

    print(f"\nSummary: {len(changed)} files changed, {len(target_files) - len(changed)} unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
