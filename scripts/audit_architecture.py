"""Static Architecture & Clean Code Compliance Auditor for OmniMesh.

Validates AGENTS.md, PROJECT.md, and BLENDER_KNOWLEDGE.md architectural invariants:
1. Zero direct or obfuscated bpy.context leaks in core/ and exporters/ (must use explicit injection).
2. Zero deprecated Blender API patterns (e.g., shadow_method, blend_method='CLIP').
3. Zero silent bare except/pass, log-only exception swallowing, or broad except Exception in core/ and exporters/.
4. Zero untyped Any annotations in core/ and exporters/ function signatures (except JSON dict[str, Any] values).
5. Zero unallowed cast(Any, ...) escape hatches in core/ and exporters/ (strict allowlist required).
6. Monotonic ratchet baseline on direct and indirect bpy.data access in core/ and exporters/.
7. Clean code hygiene (no commented-out dead code blocks, file size <= 750 lines).
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Monotonic ratchet baseline for direct and indirect bpy.data references in core/ and exporters/
BPY_DATA_RATCHET_BASELINE = 8

# Strictly scoped allowlist for cast(Any, ...) justified exclusively by verified Blender stub defects:
# Key: relative file path -> { target_expr: (max_allowed_occurrences, documented_defect_rationale) }
ALLOWED_CAST_ANY: dict[str, dict[str, tuple[int, str]]] = {
    "core/batch.py": {
        "bpy.ops.import_scene": (1, "Blender stub defect: dynamic operator dispatch"),
    },
    "core/decimator.py": {
        "ctx.temp_override": (3, "Blender stub defect: Context.temp_override callable/context manager return type"),
    },
    "core/impostor.py": {
        "impostor_obj.data": (1, "Blender stub defect: ID base class lacks materials attribute"),
        "ctx": (1, "Blender stub defect: Context.temp_override callable return type"),
    },
    "core/impostor_baker.py": {
        "bake_scene.view_settings": (1, "Blender stub defect: Scene.view_settings attributes"),
        "ctx": (1, "Blender stub defect: Context.temp_override callable return type"),
        "scene.render": (1, "Blender stub defect: RenderSettings.engine read-only setter"),
        "img_orm.pixels": (1, "Blender stub defect: Image.pixels lacks foreach_set"),
    },
    "core/impostor_preview.py": {
        "norm_img.colorspace_settings": (1, "Blender stub defect: ColorManagedInputColorspaceSettings name setter"),
        "orm_img.colorspace_settings": (1, "Blender stub defect: ColorManagedInputColorspaceSettings name setter"),
    },
    "core/material_presets.py": {
        "mat": (4, "Dynamic RNA property: msfs_material_type injected by MSFS exporter"),
    },
    "core/materials.py": {
        "out.links": (1, "Blender stub defect: NodeSocket.links sequence typing"),
    },
    "core/modifiers.py": {
        "obj.data": (4, "Blender stub defect: Object.data ID base class downcast"),
        "eval_obj.data": (1, "Blender stub defect: Object.data ID base class downcast"),
        "ctx.temp_override": (1, "Blender stub defect: Context.temp_override callable return type"),
    },
    "core/normals.py": {
        "ctx": (2, "Blender stub defect: Context.temp_override callable return type"),
    },
    "core/rigging.py": {
        "armature_world": (1, "Mathutils stub defect: Matrix @ operator type resolution"),
        "bone_rest_local": (1, "Mathutils stub defect: Matrix @ operator type resolution"),
        "prop_parent_inverse": (1, "Mathutils stub defect: Matrix @ operator type resolution"),
        "prop_basis": (1, "Mathutils stub defect: Matrix @ operator type resolution"),
        "inverted_target": (1, "Mathutils stub defect: Matrix @ operator type resolution"),
    },
    "core/scene_setup.py": {
        "COLLECTION_COLOR_TAGS.get('ROOT', 'COLOR_08')": (1, "Blender stub defect: Collection.color_tag literal enum"),
        "COLLECTION_COLOR_TAGS.get(role_key, 'NONE')": (1, "Blender stub defect: Collection.color_tag literal enum"),
    },
    "core/shader_tracer.py": {
        "scene.render": (2, "Blender stub defect: RenderSettings.engine read-only setter"),
    },
}


def _has_non_dict_any(annotation: ast.AST | None) -> bool:
    """Returns True if an AST annotation contains Any outside of dict/Mapping value parameters."""
    if annotation is None:
        return False
    if isinstance(annotation, ast.Name) and annotation.id == "Any":
        return True
    if isinstance(annotation, ast.Attribute) and annotation.attr == "Any":
        return True
    if isinstance(annotation, ast.Constant) and annotation.value == "Any":
        return True
    if isinstance(annotation, ast.Subscript):
        base_str = ast.unparse(annotation.value)
        if base_str in ("dict", "Dict", "Mapping"):
            if isinstance(annotation.slice, ast.Tuple) and len(annotation.slice.elts) == 2:
                return _has_non_dict_any(annotation.slice.elts[0])
            return False
    return any(_has_non_dict_any(child) for child in ast.iter_child_nodes(annotation))


def _is_bpy_data_access(node: ast.AST) -> bool:
    """Detects direct or indirect access to Blender global datablock pool (bpy.data)."""
    # 1. Direct attribute: bpy.data or _bpy.data
    if isinstance(node, ast.Attribute) and node.attr == "data":
        if isinstance(node.value, ast.Name) and node.value.id in ("bpy", "_bpy"):
            return True

    # 2. Indirect getattr: getattr(bpy, "data"), getattr(_bpy, "data"), or getattr(_bpy_in if ... else bpy, "data")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and node.args[1].value == "data":
            first_arg = node.args[0]
            if isinstance(first_arg, ast.Name) and first_arg.id in ("bpy", "_bpy"):
                return True
            if isinstance(first_arg, ast.IfExp):
                target_names = {n.id for n in ast.walk(first_arg) if isinstance(n, ast.Name)}
                if any(n in target_names for n in ("bpy", "_bpy", "_bpy_in")):
                    return True

    # 3. Import: from bpy import data
    if isinstance(node, ast.ImportFrom) and node.module in ("bpy", "_bpy"):
        if any(alias.name == "data" for alias in node.names):
            return True

    return False


def scan_repository(repo_root: Path | None = None) -> dict[str, list[tuple[object, ...]]]:
    root = repo_root or REPO_ROOT
    violations: dict[str, list[tuple[object, ...]]] = {
        "context_leak_in_core_exporters": [],
        "deprecated_blender_apis": [],
        "bare_except_pass": [],
        "broad_except_in_core_exporters": [],
        "any_in_core_exporter_signatures": [],
        "unallowed_cast_any_in_core_exporters": [],
        "bpy_data_ratchet_in_core_exporters": [],
        "commented_out_code_blocks": [],
        "file_length_over_750": [],
    }

    py_files = [
        p
        for p in root.rglob("*.py")
        if not any(part.startswith(".") or part in ("venv", ".venv", "build", "dist", "scratch") for part in p.parts)
    ]

    total_bpy_data_count = 0
    cast_any_occurrences: dict[str, list[tuple[int, str]]] = {}

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

            # Check for global bpy.data references in core/ and exporters/
            if is_core_or_exporter and _is_bpy_data_access(node):
                total_bpy_data_count += 1

            # Check for cast(Any, ...) escape hatches in core/ and exporters/
            if is_core_or_exporter and isinstance(node, ast.Call):
                func = node.func
                is_cast = (isinstance(func, ast.Name) and func.id == "cast") or (
                    isinstance(func, ast.Attribute) and func.attr == "cast"
                )
                if is_cast and len(node.args) >= 2:
                    arg0 = node.args[0]
                    is_any_type = (
                        (isinstance(arg0, ast.Name) and arg0.id == "Any")
                        or (isinstance(arg0, ast.Attribute) and arg0.attr == "Any")
                        or (isinstance(arg0, ast.Constant) and arg0.value == "Any")
                        or _has_non_dict_any(arg0)
                    )
                    if is_any_type:
                        target_str = ast.unparse(node.args[1])
                        cast_any_occurrences.setdefault(rel_path, []).append((node.lineno, target_str))

            # Generic except: pass / except Exception: pass or broad except Exception in domain modules
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
                if broad_matches:
                    violations["broad_except_in_core_exporters"].append((rel_path, node.lineno, broad_matches[0]))
                    if len(node.body) == 1:
                        stmt = node.body[0]
                        is_pass = isinstance(stmt, ast.Pass)
                        is_log_only = (
                            isinstance(stmt, ast.Expr)
                            and isinstance(stmt.value, ast.Call)
                            and ast.unparse(stmt.value.func).startswith(("logger.", "log.", "logging."))
                        )
                        if is_pass or is_log_only:
                            kind = "pass" if is_pass else "log-only"
                            violations["bare_except_pass"].append(
                                (rel_path, node.lineno, f"{broad_matches[0]} ({kind})")
                            )

            # Check for non-dict Any annotations in core/ and exporters/ function signatures (PROJECT.md §0.5)
            if is_core_or_exporter and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                all_args = (
                    list(node.args.posonlyargs)
                    + list(node.args.args)
                    + list(node.args.kwonlyargs)
                    + ([node.args.vararg] if node.args.vararg else [])
                    + ([node.args.kwarg] if node.args.kwarg else [])
                )
                for arg in all_args:
                    if arg.annotation is not None and _has_non_dict_any(arg.annotation):
                        violations["any_in_core_exporter_signatures"].append(
                            (rel_path, node.lineno, f"{node.name}({arg.arg}: {ast.unparse(arg.annotation)})")
                        )
                if node.returns is not None and _has_non_dict_any(node.returns):
                    violations["any_in_core_exporter_signatures"].append(
                        (rel_path, node.lineno, f"{node.name}() -> {ast.unparse(node.returns)}")
                    )

            # Check for non-dict Any in annotated variable assignments in core/ and exporters/
            if is_core_or_exporter and isinstance(node, ast.AnnAssign):
                if node.annotation is not None and _has_non_dict_any(node.annotation):
                    target_repr = ast.unparse(node.target) if hasattr(ast, "unparse") else "var"
                    violations["any_in_core_exporter_signatures"].append(
                        (rel_path, node.lineno, f"{target_repr}: {ast.unparse(node.annotation)}")
                    )

    # Validate cast(Any, ...) occurrences against strict allowlist
    for r_path, items in cast_any_occurrences.items():
        allowed_for_file = ALLOWED_CAST_ANY.get(r_path, {})
        counts: Counter[str] = Counter()
        for lineno, target in items:
            counts[target] += 1
            if target not in allowed_for_file:
                violations["unallowed_cast_any_in_core_exporters"].append(
                    (
                        r_path,
                        lineno,
                        f"Unregistered cast(Any, {target}) escape hatch. Use concrete types or register in audit allowlist.",
                    )
                )
            elif counts[target] > allowed_for_file[target][0]:
                max_allowed, reason = allowed_for_file[target]
                violations["unallowed_cast_any_in_core_exporters"].append(
                    (
                        r_path,
                        lineno,
                        f"cast(Any, {target}) count ({counts[target]}) exceeds allowed quota ({max_allowed}): {reason}",
                    )
                )

    # Validate bpy.data ratchet baseline
    if total_bpy_data_count > BPY_DATA_RATCHET_BASELINE:
        violations["bpy_data_ratchet_in_core_exporters"].append(
            (
                "GLOBAL_RATCHET",
                total_bpy_data_count,
                f"bpy.data references ({total_bpy_data_count}) exceed ratchet baseline ({BPY_DATA_RATCHET_BASELINE})",
            )
        )

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniMesh Architecture & Clean Code Auditor")
    parser.add_argument("--strict", action="store_true", help="Fail on any architectural warning")
    args = parser.parse_args()

    violations = scan_repository()
    critical_categories = [
        "context_leak_in_core_exporters",
        "deprecated_blender_apis",
        "bare_except_pass",
        "broad_except_in_core_exporters",
        "any_in_core_exporter_signatures",
        "unallowed_cast_any_in_core_exporters",
        "bpy_data_ratchet_in_core_exporters",
    ]
    warning_categories = ["commented_out_code_blocks", "file_length_over_750"]

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
