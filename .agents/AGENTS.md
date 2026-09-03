## 1. Collaboration & Behavioral Rules
* **Friendly & Collegial Partnership**: Maintain a warm, friendly, and collegial tone with a healthy touch of humor. You are an equal engineering partner who works together with the user to achieve great results.
* **Honest Transparency & Uncertainty**: Be openly honest when something is unknown, underspecified, or ambiguous. Never guess or hallucinate solutions; ask clarifying questions and outline trade-offs transparently.
* **Constructive Sparring & Counterproposals**: Actively explore best practices, suggest constructive alternatives, and point out potential flaws or edge cases respectfully.
* **Continuous Self-Improvement & Lean Repository Memory**: Keep [`.agents/KNOWLEDGE.md`](.agents/KNOWLEDGE.md) updated with non-obvious runtime gotchas, hardware/model constraints, and hidden system quirks. NEVER record information in `KNOWLEDGE.md` that is already self-evident from source code, function signatures, or inline docstrings.

---

## 2. Execution & Workflow Protocol
* **Mandatory Architecture Sparring & "Grill Me" Gate (Zero-Exception Protocol)**:
  * **Strict Requirement**: Prior to writing or updating `implementation_plan.md` and requesting user feedback, the agent MUST ALWAYS execute an adversarial sparring loop with the `plan_critic` subagent.
  * **Automated Procedure (Never Wait for User Reminders)**:
    1. Define the `plan_critic` subagent via `define_subagent` (if not already defined in the conversation).
    2. Invoke `plan_critic` via `invoke_subagent` with a detailed architectural draft, explicit edge cases, platform considerations (Win32, Linux, macOS), and potential regression vectors.
    3. Evaluate the critique, address all high-risk findings, and synthesize the finalized, hardened design into `implementation_plan.md`.
    4. Only AFTER this subagent sparring is complete may the agent present the plan to the user for approval.
  * Presenting an `implementation_plan.md` or asking the user for plan approval without preceding `plan_critic` sparring is a direct protocol violation.
* **Incremental & Complete Edits**: Propose changes step-by-step.
* **Zero Placeholders**: Never use placeholders, summaries, or truncation comments (e.g., `// ... existing code ...`, `/* remaining code unchanged */`). Always output fully complete, runnable code files or intact, self-contained functional blocks.
* **Defensive & Dependency Hygiene**: Implement complete logic without unsolicited third-party packages. Rely on native capabilities and existing utilities first.
* **Non-Blocking Execution & Zero-Polling Protocol**: When initiating background processes or async timers, never poll for status in a loop. Update the user with a concise status message and yield control to await background notifications.
* **Task Verification Gate (Code Changes Only)**: Run automated unit tests (`pytest -q` or equivalent) ONLY when executable application source code was modified. Do NOT run unit tests for pure documentation/markdown changes, questions, or config edits. Never run linters or static type checkers during intermediate steps (see Section 7 for complete gate rules).
* **Explicit User Authorization & Pre-Commit Protocol**: Never commit or push changes automatically or "on the side". Present results to the user and wait for their explicit request (e.g., "please push", "bitte committen"). Once authorized, execute the full Pre-Commit Quality Gate (Section 7: CI verification script and `pre_commit_auditor`) before creating the commit and pushing.

---

## 3. Core Architecture & Design Principles
* **Strict English Codebase**: All source code, variable names, function names, class names, docstrings, and internal inline comments MUST be strictly in English. (Domain settings and runtime configuration values are exempt).
* **Pragmatism Over Over-Engineering (KISS & YAGNI)**: Always prefer the simplest, most readable solution. Build strictly what is needed today. Apply SOLID principles pragmatically to serve readability, avoiding artificial fragmentation.
* **Layer Separation**: Strictly isolate application layers into focused modules:
  * *Presentation (UI)*: Blender N-Panel (`ui/panel.py`), properties (`ui/properties.py`), and operators (`ui/operators.py`).
  * *Business Logic & Geometry*: Decimators, collision decomposition, impostors, LOD progression, and topological repair (`core/`).
  * *Bridges & Live Sync*: Engine live links (UE5, Unity, Godot, MSFS) and IPC protocols (`bridges/`).
  * *Exporters*: Multi-engine FBX, glTF, and XML package generators (`exporters/`).
  * *Utilities*: Pure math, matrix transformations, and bounding volume helpers without Blender UI dependencies.
* **Centralized Configuration & State Access**: Never hardcode path lookups or read configuration files manually inside operators or exporters. Always access runtime settings through central state objects (`context.scene.lod_tool` or active `object.lod_tool`).
* **Zero Backward-Compatibility & Generic Fallbacks**: Do NOT build legacy fallbacks or populate missing data with hardcoded default values. If data or configuration is unpopulated, return clean, empty collections (`[]`, `{}`) or empty values rather than inventing synthetic default entries.
* **Modularization & File Size Limits**:
  * **Target Range**: Aim for files between **100 and 500 lines of code**.
  * **Upper Limit**: Refactor and split files if they exceed **800 lines** and carry multiple distinct responsibilities.
  * **Single Responsibility Principle (SRP)**: Each file must have exactly one primary reason to change.

---

## 4. Code Quality, Robustness & Security
* **Explicit Typing & Clean Interfaces**: Use strong Python type hints (`Type Hints`, generic collections `list[str]`, `dict[str, Any]`, `dataclasses`) throughout. Design clean, typed interfaces without legacy fallbacks or backward-compatibility bloat.
* **Explicit Exception Handling & Logging**: Catch specific exception classes and log full error context. Never use silent `try/except: pass` blocks. Prefer narrow exceptions over broad `except Exception` wherever practical.
* **Module-Level Logging**: Use module loggers (`logger = logging.getLogger(__name__)`) instead of the root logger, and prefer structured logging with context over string interpolation.
* **Cross-Platform OS Safety Guards**: Guard all platform-specific native system calls (e.g. Win32 `ctypes.windll`, registry, GDI, memory trim) with explicit runtime platform checks (`if sys.platform == "win32":`), providing non-crashing fallback paths so tests and CI run cleanly across Linux and macOS environments.
* **Resource & Memory Hygiene**:
  * Always release resources (files, sockets, locks, BMesh buffers) using context managers (`with`) or `finally` blocks to prevent leaks.
  * In long-running batch pipelines, explicitly free native BMesh instances (`bm.free()`), clear image buffers, and trigger periodic garbage collection (`gc.collect()`) after processing large files to prevent memory fragmentation.
* **Thread-Safety & Atomic Operations**: Protect shared mutable state across threads using explicit locks (`threading.Lock` / `threading.RLock`) or thread-safe queues. Never invoke Blender Python `bpy` C-API from worker threads.
* **Documentation & Utility Reuse**: Code explains *WHAT* it does through clear naming; inline comments explain exclusively *WHY* (background, edge cases, business logic). Inspect existing utilities and helpers before creating new utility functions.
* **Actionable Error Messages**: User-facing errors in Blender operators (`self.report({'ERROR'}, ...)`) must explain what failed, why it happened, and what the user can do next.

---

## 5. Blender UI/UX & Viewport Standards
* **Ergonomic N-Panel Layout**: Use consistent layout spacing, `layout.use_property_split = True`, and sub-panels with logical collapsible boxes. Never clutter panels with deep nesting.
* **Non-Intrusive Viewport Display**: Auxiliary geometry (such as convex collision hulls) must default to wireframe display (`obj.display_type = 'WIRE'`, `obj.show_wire = True`) and reside in dedicated sibling collections (`{BaseName}_Colliders`).
* **Draw Handler Purity**: Drawing callbacks registered with `bpy.types.SpaceView3D.draw_handler_add` must remain strictly read-only. Never mutate Blender DNA/RNA properties or trigger operator execution within a draw handler callback.
* **Context Resolver Uniformity**: UI controls and operators must always resolve property context via `resolve_lod_context(context)` to support both object-level overrides and scene-level global defaults smoothly.

---

## 6. Git Commit Message Guidelines
When asked to write or suggest Git commit messages, strictly adhere to the following rules:

* **Structure**: Use a short subject line followed by an optional body separated by a blank line. Keep the body concise and easy to scan.
* **Subject Line Rules**:
  * Keep it to **50 characters or fewer**.
  * Start with a capital letter.
  * Do not end with a period.
  * Use the **imperative mood** (for example, "Add CI workflow" instead of "Added CI workflow").
* **Body Rules**:
  * Explain the **reason** for the change, not just the implementation details.
  * Keep it to one or two short sentences.
  * Mention important context such as bug fixes, user impact, or compatibility concerns when relevant.
* **Content Rules**:
  * Be specific and concrete; avoid vague phrases like "improve stuff" or "various fixes".
  * Mention the affected component in brackets (e.g., `[Core]`, `[Exporters]`, `[UI]`, `[Bridges]`).
* **Output Standard**: Return **only** the raw commit message text. Do not include meta-commentary, explanations, or raw diff output.

---

## 7. CI, Testing & Pre-Commit Quality Gate
* **Development & Task Completion Gate (Conditional Unit Tests Only)**:
  * Run unit tests ONLY if application source code (`.py`) was modified in the task (`python -m pytest -q`).
  * If the task involved only documentation, markdown (`.md`), explanations, or non-executable assets, skip test runs entirely.
  * Linters and static type checkers are strictly FORBIDDEN during development iterations to save time and compute.
* **Mandatory Pre-Commit Quality Gate (Triggered Strictly Upon Explicit Commit/Push Request)**:
  * Linters, static type checkers, and the full test suite are executed ONLY when the user explicitly instructs to commit or push (e.g., "bitte committen", "commit and push").
  * Run the central verification script:
    ```bash
    python scripts/verify_ci.py
    ```
  * Deterministically executes CI parity: Dependency check, Ruff Linter, Ruff Formatter, Pyright Static Type Checker, and Full Pytest Suite.
* **Subagent Code & Goal Audit Gate**: For non-trivial refactorings and features, invoke the `pre_commit_auditor` subagent to conduct an adversarial audit on `git diff` against:
  1. **Plan-to-Code Fidelity**: Does the code genuinely solve the root problem and deliver all commitments from `implementation_plan.md`?
  2. **Code & Architecture Standards**: Adherence to `AGENTS.md` rules (no placeholders, resource hygiene, cross-platform guards, SRP limits, zero secret leaks).
  3. **Verification Completeness**: Confirm that `python scripts/verify_ci.py` ran over the entire codebase with 0 errors.
* **Zero Regression Standard**: Commits and pushes are strictly blocked if any linter warning, type diagnostic, test failure, or auditor blocker is present. All gates must succeed with 0 errors before executing the git commit.

---

## 8. Security, Open Source & Privacy Protocol
* **Zero Secret & Privacy Leakage**: Never commit private 3D assets, API keys, tokens, or local environment credentials (`.env`). All test fixtures MUST use synthetic or procedurally generated geometry.
* **Large Binary Hygiene**: Never commit large model files, binary blend files, or weights (> 50 MB) to Git tracking. Always verify `.gitignore` ignores temporary scratch blend files, caches, and virtual environments.
* **Cross-Platform Compatibility**: Do NOT hardcode OS-specific absolute paths. Use `pathlib.Path` and relative, configurable paths across all modules.
* **License Integrity & Attribution**: Preserve software license headers and ensure any new third-party dependency is recorded with its license.
* **Clean Git History**: Run `git status` and verify no scratch logs, temp files, or untracked sensitive data exist before committing or opening pull requests.

---

## 9. Blender Add-on Development & Live MCP Testing Protocol

When building, refactoring, or testing Blender Add-ons using AI assistance and the `blender-mcp` toolserver, strictly enforce the following rules and best practices:

### 9.1 Modern Extension Architecture & Packaging (Blender 4.2+)
* **Dual Manifest Standard**: Always include both `bl_info` in `__init__.py` (for legacy add-on installation) and `blender_manifest.toml` (for Blender 4.2+ extension system).
* **Extension Directory**: For Blender 4.2+, user extensions reside in `%APPDATA%\Blender Foundation\Blender\<ver>\extensions\user_default\<addon_id>` and activate via `bpy.ops.preferences.addon_enable(module="bl_ext.user_default.<addon_id>")`.
* **Modular Layer Separation**:
  * `core`: Pure math, decimation algorithms, collision decomposition, and geometric operations.
  * `exporters`: Engine-specific serialization (FBX, glTF, XML).
  * `bridges`: Live socket/filesystem sync handlers.
  * `ui`: Blender `bpy.types.Operator`, `bpy.types.Panel`, and `bpy.types.PropertyGroup` classes.

### 9.2 Live Iteration & Dynamic Reloading via Blender MCP
* **Hot Reloading Sequence**: When modifying code during a live session, reload modules in strict dependency order using `importlib.reload()` (`core` -> `exporters` -> `bridges` -> `ui` -> `__init__`), unregister previous classes (`unregister()`), and re-register (`register()`).
* **Orphan UI Cleanup**: Always dynamically unregister deprecated or renamed classes from `bpy.types` before registering to prevent ghost headers or duplicate tabs from persisting in Blender's UI memory.
* **Empirical Screenshot Verification**: Never complete UI layout or viewport changes without taking window/viewport screenshots via `get_screenshot_of_window_as_image` or `render_viewport_to_path` to empirically verify panel visibility, button alignment, and geometric results.

### 9.3 Blender Python API & Technical Best Practices
* **Object Preservation & Non-Destructive Sibling Hierarchy**: Add-on steps must be non-destructive. Source geometry in root collection `{BaseName}` is preserved as LOD0. Derivative LODs, colliders, and impostors are created in isolated sibling collections (`{BaseName}_LOD1..k`, `{BaseName}_Colliders`, `{BaseName}_LOD_Impostor`).
* **View Layer Safety (`LayerCollectionGuard`)**: Wrap operations that evaluate modifiers, depsgraphs, or geometry across collections in `LayerCollectionGuard` to temporarily un-exclude collections (`exclude = False`) and guarantee restoration in `finally`.
* **EEVEE Next Shading Compatibility**: Guard legacy material transparency attributes (e.g. `mat.shadow_method`) with `hasattr()` before assignment to ensure non-crashing compatibility across Blender 4.2+ and 5.2 LTS.
* **Native Acceleration**: Prefer built-in `mathutils.kdtree.KDTree` for spatial queries and `mathutils.geometry` for triangulation/bisection over third-party external C-libraries.
