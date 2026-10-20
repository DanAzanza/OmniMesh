"""Static Architecture & Clean Code Compliance Auditor for OmniMesh.

Validates AGENTS.md, PROJECT.md, and BLENDER_KNOWLEDGE.md architectural invariants:
1. Zero direct or obfuscated bpy.context leaks in core/ and exporters/ (must use explicit injection).
2. Zero deprecated Blender API patterns (e.g., shadow_method, blend_method='CLIP').
3. Zero silent bare except/pass or generic exception swallowing in business logic.
4. Clean code hygiene (no commented-out dead code blocks).
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def scan_repository(repo_root: Path | None = None) -> dict[str, list[tuple[object, ...]]]:
    root = repo_root or REPO_ROOT
    violations: dict[str, list[tuple[object, ...]]] = {
        "context_leak_in_core_exporters": [],
        "deprecated_blender_apis": [],
        "bare_except_pass": [],
        "commented_out_code_blocks": [],
        "file_length_over_750": [],
    }

    py_files = [
        p
        for p in root.rglob("*.py")
        if not any(part.startswith(".") or part in ("venv", ".venv", "build", "dist", "scratch") for part in p.parts)
    ]

    for fpath in py_files:
        rel_path = fpath.relative_to(root).as_posix()
        try:
            content = fpath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        lines = content.splitlines()

        # 1. File Length Check (> 750 lines)
        if len(lines) > 750:
            violations["file_length_over_750"].append((rel_path, len(lines)))

        # 2. Deprecated Blender APIs / Invariants from BLENDER_KNOWLEDGE.md (only in core, ui, exporters)
        if not rel_path.startswith("scripts/") and not rel_path.startswith("tests/"):
            if "shadow_method" in content:
                violations["deprecated_blender_apis"].append((rel_path, "shadow_method found"))
            if "blend_method" in content and "'CLIP'" in content:
                violations["deprecated_blender_apis"].append((rel_path, "blend_method='CLIP' found"))

        # 3. Commented-out Code Blocks
        comment_streak: list[str] = []
        streak_start = 0
        for idx, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") and any(
                stripped.startswith(f"# {kw}")
                for kw in ("def ", "class ", "if ", "for ", "while ", "return ", "import ", "from ")
            ):
                if not comment_streak:
                    streak_start = idx
                comment_streak.append(stripped)
            else:
                if len(comment_streak) >= 3:
                    violations["commented_out_code_blocks"].append((rel_path, streak_start, len(comment_streak)))
                comment_streak = []
        if len(comment_streak) >= 3:
            violations["commented_out_code_blocks"].append((rel_path, streak_start, len(comment_streak)))

        # 4. AST Analysis
        try:
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError:
            continue

        is_core_or_exporter = rel_path.startswith("core/") or rel_path.startswith("exporters/")

        for node in ast.walk(tree):
            # Check for direct bpy.context, from bpy import context, or getattr(..., "context") in core/ and exporters/
            if is_core_or_exporter and isinstance(node, ast.Attribute):
                if isinstance(node.value, ast.Name) and node.value.id in ("bpy", "_bpy") and node.attr == "context":
                    violations["context_leak_in_core_exporters"].append(
                        (rel_path, node.lineno, f"{node.value.id}.context")
                    )

            if is_core_or_exporter and isinstance(node, ast.ImportFrom):
                if node.module == "bpy" and any(alias.name == "context" for alias in node.names):
                    violations["context_leak_in_core_exporters"].append(
                        (rel_path, node.lineno, "from bpy import context")
                    )

            if is_core_or_exporter and isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "getattr":
                    if len(node.args) >= 2:
                        second_arg = node.args[1]
                        if isinstance(second_arg, ast.Constant) and second_arg.value == "context":
                            violations["context_leak_in_core_exporters"].append(
                                (rel_path, node.lineno, 'getattr(..., "context")')
                            )

            # Generic except: pass / except Exception: pass or log-only swallowing in domain modules
            if is_core_or_exporter and isinstance(node, ast.ExceptHandler):
                caught_names: list[str] = []
                if node.type is None:
                    caught_names.append("bare")
                elif isinstance(node.type, ast.Name):
                    caught_names.append(node.type.id)
                elif isinstance(node.type, ast.Tuple):
                    for elt in node.type.elts:
                        if isinstance(elt, ast.Name):
                            caught_names.append(elt.id)
                        else:
                            caught_names.append(ast.unparse(elt))
                else:
                    caught_names.append(ast.unparse(node.type))

                broad_matches = [n for n in caught_names if n in ("bare", "Exception", "BaseException")]
                if broad_matches and len(node.body) == 1:
                    stmt = node.body[0]
                    is_pass = isinstance(stmt, ast.Pass)
                    is_log_only = (
                        isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Call)
                        and ast.unparse(stmt.value.func).startswith(("logger.", "log.", "logging."))
                    )
                    if is_pass or is_log_only:
                        kind = "pass" if is_pass else "log-only"
                        violations["bare_except_pass"].append((rel_path, node.lineno, f"{broad_matches[0]} ({kind})"))

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniMesh Architecture & Clean Code Auditor")
    parser.add_argument("--strict", action="store_true", help="Fail on any architectural warning")
    args = parser.parse_args()

    violations = scan_repository()
    critical_categories = ["context_leak_in_core_exporters", "deprecated_blender_apis", "bare_except_pass"]
    warning_categories = ["commented_out_code_blocks"]

    has_critical = any(len(violations.get(cat, [])) > 0 for cat in critical_categories)
    has_warning = any(len(violations.get(cat, [])) > 0 for cat in warning_categories)

    print("=" * 60)
    print("OmniMesh Architectural Compliance Audit")
    print("=" * 60)

    for cat, items in violations.items():
        count = len(items)
        status = "[FAIL]" if (cat in critical_categories and count > 0) else "[INFO]"
        print(f"\n{status} {cat} ({count} issue{'s' if count != 1 else ''}):")
        for it in items[:10]:
            print(f"  - {it}")
        if count > 10:
            print(f"  ... and {count - 10} more")

    if has_critical:
        print("\n[FAILED] Critical architectural invariants violated!")
        return 1

    if args.strict and has_warning:
        print("\n[FAILED] Architectural warnings found in strict mode!")
        return 1

    print("\n[PASSED] Architecture and clean code compliance verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
