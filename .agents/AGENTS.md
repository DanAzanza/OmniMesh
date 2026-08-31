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
* **Task Verification Gate (Code Changes Only)**: Run automated unit tests (`pytest -q` or equivalent) ONLY when executable application source code was modified. Do NOT run unit tests for pure documentation/markdown changes, questions, or config edits. Never run linters or static type checkers during intermediate steps (see Section 8 for complete gate rules).
* **Explicit User Authorization & Pre-Commit Protocol**: Never commit or push changes automatically or "on the side". Present results to the user and wait for their explicit request (e.g., "please push", "bitte committen"). Once authorized, execute the full Pre-Commit Quality Gate (Section 8: CI verification script and `pre_commit_auditor`) before creating the commit and pushing.

---

## 3. Core Architecture & Design Principles
* **Strict English Codebase**: All source code, variable names, function names, class names, docstrings, and internal inline comments MUST be strictly in English. (Domain settings and runtime configuration values are exempt).
* **Pragmatism Over Over-Engineering (KISS & YAGNI)**: Always prefer the simplest, most readable solution. Build strictly what is needed today. Apply SOLID principles pragmatically to serve readability, avoiding artificial fragmentation.
* **Layer Separation**: Strictly isolate application layers into focused modules:
  * *Presentation (UI)*: Visual layout and direct user interaction.
  * *Business Logic & State*: Data processing, state updates, and workflows.
  * *Data & API*: Network clients, database queries, and raw I/O.
  * *Types & Schemas*: Domain models and interface definitions.
  * *Utilities*: Pure helper functions without UI or state dependencies.
* **Centralized Configuration & State Access**: Never hardcode path lookups or read configuration files manually inside API handlers or subservices. Always access runtime settings through central state objects or dedicated configuration managers.
* **Zero Backward-Compatibility & Generic Fallbacks**: Do NOT build legacy fallbacks or populate missing data with hardcoded default values. If data or configuration is unpopulated, return clean, empty collections (`[]`, `{}`) or empty values rather than inventing synthetic default entries.
* **Modularization & File Size Limits**:
  * **Target Range**: Aim for files between **100 and 500 lines of code**.
  * **Upper Limit**: Refactor and split files if they exceed **800 lines** and carry multiple distinct responsibilities.
  * **Single Responsibility Principle (SRP)**: Each file must have exactly one primary reason to change. Separate frontend JS modules cleanly into API clients (`*_api.js`), view rendering (`*_views.js`), and event handlers (`*_events.js`).

---

## 4. Code Quality, Robustness & Security
* **Explicit Typing & Clean Interfaces**: Use strong typing (Type Hints, Pydantic schemas, TypeScript/JSDoc interfaces) throughout. Design clean, generic interfaces without legacy fallbacks or backward-compatibility bloat.
* **Explicit Exception Handling & Logging**: Catch specific exception classes and log full error context. Never use silent `try/except: pass` blocks. Prefer narrow exceptions over broad `except Exception` wherever practical.
* **Module-Level Logging**: Use module loggers such as `logger = logging.getLogger(__name__)` instead of the root logger for application code, and prefer structured logging with context over string interpolation.
* **Cross-Platform OS Safety Guards**: Guard all platform-specific native system calls (e.g. Win32 `ctypes.windll`, registry, GDI) with explicit runtime platform checks (`if sys.platform == "win32":`), providing non-crashing fallback paths so tests and CI run cleanly across environments.
* **Resource & Memory Hygiene**:
  * Always release resources (files, sockets, locks, database connections, native graphics buffers) using context managers (`with`) or `finally` blocks to prevent leaks.
  * In long-running batch pipelines, explicitly deallocate large native buffers and trigger periodic garbage collection (`gc.collect()`) after processing large files to prevent memory fragmentation and OS-level access violations.
* **Thread-Safety & Atomic Operations**: Protect shared mutable state across threads using explicit locks (`threading.Lock` / `threading.RLock`) or thread-safe queues. Ensure file manipulations are fail-safe and atomic.
* **Documentation & Utility Reuse**: Code explains *WHAT* it does through clear naming; inline comments explain exclusively *WHY* (background, edge cases, business logic). Inspect existing utilities and helpers before creating new utility functions.
* **Actionable Error Messages**: User-facing errors must explain what failed, why it happened, and what the user can do next. Avoid vague exceptions or silent fallbacks in workflows that affect user experience.

---

## 5. Frontend & UI/UX Standards
* **No Inline Styles in JavaScript**: Define visual styles using CSS classes and variables in stylesheet files. Never inject dynamic `element.style` strings via JavaScript.
* **DOM Security**: Sanitize and escape dynamic user-generated content (e.g., using `escapeHtml()`) to prevent XSS vulnerabilities.
* **Semantic HTML & Accessibility**: Use explicit `<button type="button">` attributes and semantic HTML5 elements.
* **Lifecycle & Background Tab Synchronization**: Modern browsers throttle background/sleeping tabs. Dashboards must hook full state synchronization into both `visibilitychange` (when tab becomes active) and `window.focus` to instantly refresh stale views and metrics upon user return.

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
  * Mention the affected component in brackets when helpful (e.g., `[Core Engine]`, `[API]`, `[UI]`).
* **Output Standard**: Return **only** the raw commit message text. Do not include meta-commentary, explanations, or raw diff output.

---

## 7. Browser & E2E Testing Protocol
* **Browser Automation & DevTools Integration**: When validating web dashboards, frontend components, or live web UI flows, leverage browser automation tools (e.g. Chrome DevTools MCP: `navigate_page`, `evaluate_script`, `take_screenshot`, `list_console_messages`, `list_network_requests`).
* **Visual Verification**: Take viewport or full-page screenshots to empirically verify UI rendering, layout alignment, and DOM modifications before concluding frontend work.
* **Console & Network Hygiene**: Inspect console logs and network traffic via DevTools tools to confirm clean execution without silent API failures or unhandled client-side exceptions.

---

## 8. CI, Testing & Pre-Commit Quality Gate
* **Development & Task Completion Gate (Conditional Unit Tests Only)**:
  * Run unit tests ONLY if application source code (`.py`, `.js`, etc.) was modified in the task.
  * If the task involved only documentation, markdown (`.md`), explanations, or non-executable assets, skip test runs entirely.
  * Linters and static type checkers are strictly FORBIDDEN during development iterations to save time and compute.
* **Mandatory Pre-Commit Quality Gate (Triggered Strictly Upon Explicit Commit/Push Request)**:
  * Linters, static type checkers, and the full test suite are executed ONLY when the user explicitly instructs to commit or push (e.g., "bitte committen", "commit and push").
  * Run the central verification script documented in [`.agents/KNOWLEDGE.md`](.agents/KNOWLEDGE.md).
  * Deterministically execute CI parity: Linter, Static Type Checker, and Full Test Suite.
* **Subagent Code & Goal Audit Gate**: For non-trivial refactorings and features, invoke the `pre_commit_auditor` subagent to conduct an adversarial audit on `git diff` against:
  1. **Plan-to-Code Fidelity**: Does the code genuinely solve the root problem and deliver all commitments from `implementation_plan.md`, or were corners cut and edge cases dropped?
  2. **Code & Architecture Standards**: Adherence to `AGENTS.md` rules (no placeholders, resource hygiene, cross-platform guards, SRP limits, zero secret leaks).
  3. **Verification Completeness**: Confirm that the verification script ran over the entire codebase with 0 errors.
* **Zero Regression Standard**: Commits and pushes are strictly blocked if any linter warning, type diagnostic, test failure, or auditor blocker is present. All gates must succeed with 0 errors before executing the git commit.

---

## 9. Security, Open Source & Privacy Protocol
* **Zero Secret & Privacy Leakage**: Never commit private document samples, API keys, tokens, or local environment credentials (`.env`). All test fixtures MUST use synthetic, dummy data.
* **Large Binary Hygiene**: Never commit large model files, binary weights (> 50 MB), or `.coverage` artifacts to Git tracking. Always verify `.gitignore` ignores large binaries, virtual environments, and temporary scratch directories.
* **Cross-Platform Compatibility**: Do NOT hardcode OS-specific absolute paths. Use standard path libraries (`pathlib.Path`) and relative, configurable paths across all modules.
* **License Integrity & Attribution**: Preserve software license headers and ensure any new third-party dependency is recorded with its license.
* **Clean Git History**: Run `git status` and verify no scratch logs, temp files, or untracked sensitive data exist before committing or opening pull requests.

---

## 10. Browser & E2E Testing Protocol
* **Visual Verification**: Take viewport or full-page screenshots to empirically verify UI rendering, layout alignment, and DOM modifications before concluding frontend work.
* **Console & Network Hygiene**: Inspect console logs and network traffic via DevTools tools to confirm clean execution without silent API failures or unhandled client-side exceptions.

---

## 11. Blender Add-on Development & Live MCP Testing Protocol

When building, refactoring, or testing Blender Add-ons using AI assistance and the `blender-mcp` toolserver, strictly enforce the following rules and best practices:

### 11.1 Modern Extension Architecture & Packaging (Blender 4.2+)
* **Dual Manifest Standard**: Always include both `bl_info` in `__init__.py` (for legacy add-on installation) and `blender_manifest.toml` (for Blender 4.2+ extension system).
* **Extension Directory**: For Blender 4.2+, copy user extensions to `%APPDATA%\Blender Foundation\Blender\<ver>\extensions\user_default\<addon_id>` and activate via `bpy.ops.preferences.addon_enable(module="bl_ext.user_default.<addon_id>")`. Save user preferences (`bpy.ops.wm.save_userpref()`) to persist across restarts.
* **Modular Layer Separation**:
  * `parser / IO`: Pure data loading (`load_xyz_file`).
  * `generators`: Core math, grid rasterization, and geometry creation.
  * `operators`: `bpy.types.Operator` subclasses exposing UI actions.
  * `ui_panel`: `bpy.types.Panel` subclasses drawing N-Panel controls.

### 11.2 Live Iteration & Dynamic Reloading via Blender MCP
* **Hot Reloading Sequence**: When modifying code during a live session, reload modules in strict dependency order using `importlib.reload()` (`parser` -> `generators` -> `operators` -> `ui_panel` -> `__init__`), unregister previous classes (`unregister()`), and re-register (`register()`).
* **Orphan UI Cleanup**: Always explicitly unregister deprecated or renamed panel classes (`bpy.utils.unregister_class`) to prevent ghost headers or duplicate tabs from persisting in Blender's UI memory.
* **Empirical Screenshot Verification**: Never complete UI layout work without taking window/viewport screenshots via `get_screenshot_of_window_as_image` to empirically verify panel visibility, button alignment, and label formatting.

### 11.3 Blender Python API & Technical Best Practices
* **Object Preservation & Decoupled Workflows**: Add-on steps should be non-destructive and independent. Step 1 imports the source object (e.g. Point Cloud). Steps 2 & 3 operate on `context.active_object` to generate new derivative objects without modifying or deleting the source object.
* **Float Image Buffer Management**: When updating existing `bpy.data.images` assets, remove stale instances (`bpy.data.images.remove(old_img, do_unlink=True)`) before creating new float buffers to avoid pixel dimension mismatch errors during `image.pixels.foreach_set()`.
* **Heightmap Shader Color Space**: Always set `image.colorspace_settings.name = 'Non-Color'` for displacement maps to prevent linear float elevation values from being warped by sRGB gamma curves.
* **Native `mathutils` Acceleration**: Use built-in `mathutils.kdtree.KDTree` for spatial interpolation (e.g., IDW gap filling) and `mathutils.geometry.delaunay_2d_cdt` for 2D/3D triangulation instead of requiring external C-libraries. Always verify return tuple length (e.g. `delaunay_2d_cdt` returns 6 items).
