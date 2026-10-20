# OmniMesh Project Knowledge & Architecture Specification

> **Scope**: OmniMesh (LOD-Tool) architectural specifications, verification gates, module boundaries, and multi-engine export contracts.
> **Cross-Reference**: For universal Blender platform invariants, C-API memory rules, and RNA lifecycle traps, refer to [`.agents/BLENDER_KNOWLEDGE.md`](BLENDER_KNOWLEDGE.md).

---

## 0. Repository Gates & Workflow Contracts

### 0.1 Central Pre-Commit Verification Gate
The central verification script required by `AGENTS.md` Section 7:
```bash
python scripts/verify_ci.py
```
*(Deterministically runs dependency validation, Ruff linter & formatter check, Pyright static type checker across core and test modules, static architectural invariant audit via `scripts/audit_architecture.py`, and the full test suite).*

### 0.2 Git Commit Scope Mapping
Repository-specific component scopes required by `AGENTS.md` Section 6:
* `[Core]`: Core LOD decimation engine, modifier pipeline, impostor baking, property groups (`core/`).
* `[Exporters]`: Target engine exporters (MSFS 2024, Unreal Engine 5, Unity 6) (`exporters/`).
* `[Bridges]`: External tool bridges, IPC socket servers, subprocess execution (`bridges/`).
* `[UI]`: 3D Viewport N-Panels, custom UILists, modal operators, popovers (`ui/`).
* `[Tests]`: Test suite, test fixtures, headless Blender test runners (`tests/`, `scripts/test_engine_exports.py`).
* `[CI]`: Quality gate scripts, GitHub Actions workflows (`scripts/`, `.github/`).

### 0.3 Autonomous Subagent Roles & Binary Asset Limits
* **Subagent Workflow Roles**:
  * Architecture sparring & critique gate: `plan_critic`
  * Pre-commit adversarial audit gate: `pre_commit_auditor`
* **Large 3D Binary Asset Limit**:
  * Model files (`.blend`, `.fbx`, `.gltf`, `.bin`, `.dds`) and raw textures must not exceed **50 MB** in Git tracking. Ensure temporary bake scratch files and `.coverage` artifacts remain strictly `.gitignore`d.

### 0.4 Architecture Audit Integrity (`scripts/audit_architecture.py`)
* **Bypass Vectors Must Be Covered**: `scripts/audit_architecture.py` checks semantics, not spelling. Every rule must also catch its known evasions: `getattr(bpy, "context")` / `getattr(getattr(bpy, ...))` for context leaks, and `except` blocks whose only statement is a logging call (`logger.debug/info/warning`) for swallowed errors — not just a bare `pass`.
* **No Whitelisted Workarounds**: Audit rule docstrings and this file must never name a "safe" alternative spelling of a banned pattern. If a pattern is legitimately needed, add a narrow, named allowlist entry (file + line reason) in the audit script instead.
* **Separation of Gate and Code Changes**: Never loosen or rewrite an audit rule in the same change that makes previously failing code pass it.

### 0.5 Static Analysis & Type Checking Configuration
* **`pyrightconfig.json` Precedence Trap**: Pyright silently prioritizes `pyrightconfig.json` over `[tool.pyright]` in `pyproject.toml`. If `pyrightconfig.json` exists in the repository root, any strict configurations in `pyproject.toml` are completely ignored. Maintain `pyproject.toml` as the sole authoritative configuration file; `pyrightconfig.json` must never be reintroduced.
* **`Any` Silently Disables Strict Mode**: Pyright performs no attribute, optional, or argument checks on values typed `Any`. A green Pyright run therefore says nothing about functions with `obj: Any` / `context: Any` parameters. Domain signatures in `core/` and `exporters/` must use concrete stub types (`bpy.types.Object`, `bpy.types.Context`, `bmesh.types.BMesh`) imported under `TYPE_CHECKING`. `cast(Any, ...)` is reserved strictly for documented stub defects (read-only setters, `RenderSettings.engine`) and must not be used as a general escape hatch.
* **Sanctioned File-Level Suppression**: `# pyright: reportInvalidTypeForm=none` is permitted only in modules declaring RNA properties via `prop: bpy.props.X(...)` annotations (`ui/*_ops.py`, `ui/properties/`). It must not appear in `core/`, `exporters/`, or `bridges/`.

---

## 1. Project Architecture & Module Boundaries

### 1.1 Layer Separation & Data Flow
* **Unidirectional Layer Boundaries**:
  * `ui/`: Presentation layer, 3D viewport panels, modal operators. Gathers user parameters and dispatches commands.
  * `core/`: Core decimation algorithms, impostor generation, hierarchy managers, and LOD chain calculators. Zero global `bpy.context` reads; all data and context dependencies are explicitly injected.
  * `exporters/`: Engine packaging logic (MSFS 2024, UE5, Unity 6). Implements transactional rollback (`try...finally`).
  * `bridges/`: External IPC socket clients, health probes, and live engine sync. Strictly non-blocking.
* **Core Domain Isolation**: Pure math, mesh partitioning, and quadric decimation algorithms must remain isolated from host UI state and headless batch loops.

### 1.2 Vehicle & Interactive Asset Scene-Graph Invariants
* **Unified Scene Data Model (`{AssetName}_Config`)**:
  Configuration metadata is strictly decoupled from render geometry and stored in dedicated sibling Outliner collections alongside `{AssetName}_LOD0`. Decimation engines, mesh mergers, and render LOD generators must never mutate, decimate, or ingest objects in `{AssetName}_Config`:
  * **`Spatial` Subcollection**: Empties representing Datum Origin, Center of Gravity (CG), aerodynamic reference points, ground contact points (gear/wheels), scrape points, and fuel tank centroids.
  * **`Lights` Subcollection**: Photometric light empties with custom RNA parameters: color temperature (K), lumen intensity, beam angle, attenuation radius, and animated flash timing profiles (nav, beacon, strobe, taxi, landing, cabin).
  * **`Cameras` Subcollection**: Camera empties defining pilot/driver first-person eyepoints, instrument inspection zooms, exterior orbit pivots, and chase camera anchor points.
  * **`Interaction` Subcollection**: Bounding box and hull empties defining VR/mouse click trigger volumes, grab handles, and switch articulation limits.
* **Serialization & Geometry Isolation Boundaries**:
  * **MSFS 2024 Serialization**: Serializes `{AssetName}_Config` into modular XML and CFG specifications (`systems.xml`, `cameras.xml`, `flight_model.cfg`, `attached_objects.cfg`).
  * **Geometry Export Isolation**: Configuration metadata Empties must remain strictly separate from exported glTF meshes. Mounting sockets (`ATTACH_POINT_*`) in LOD0 are preserved for attachment rigging, but config Empties reside in `{AssetName}_Config` and are filtered during mesh export.

---

## 2. Multi-Engine Export Pipelines & Target Engine Contracts

### 2.1 Live Engine Subprocess Gating & CLI Execution
* **Live Engine Subprocess Gating (`RUN_LIVE_ENGINE_TESTS`)**: Spawning external game engine executables introduces ~4–5 seconds of startup latency per test run. Headless unit test suites must gate live editor subprocesses behind `RUN_LIVE_ENGINE_TESTS` to keep regular test runs sub-5s while preserving end-to-end integration capability.
* **Multi-Engine Export Test Runner**: Run `python scripts/test_engine_exports.py` to validate all 3 engine export pipelines (distinct from the central pre-commit gate `scripts/verify_ci.py`).
* **Engine Headless CLI Execution**:
  * **Unity 6**: `unity run <project_dir> --editor-version <installed_ver> -- -nographics`. Never pass `-quit` or `-batchmode` after `--`.
  * **Unreal Engine 5**: `UnrealEditor-Cmd.exe <Project.uproject> -run=pythonscript -script="<script>.py" -nullrhi -nosound -unattended`. Colliders: `UCX_{Asset}_{Index}`.
  * **MSFS 2024**: `fspackagetool.exe <Project.xml> -forcesteam -nopause` with `stdin=subprocess.DEVNULL`. Steam installs require `fspackagetool_overrideExePath.txt`. All interior references in `model.cfg` must use POSIX forward slashes (`interior=../model/{Interior}.xml`).

### 2.2 Exporter Hierarchy, Rollback & Sockets
* **Transactional Scene-Graph Rollback (`try...finally`)**: Single-mesh engine exporters mutate names (`UCX_`) and parent meshes to temporary `LODGroup` empties. Exporters must record original state in dictionaries, run export in `try`, and restore original hierarchy and names in `finally`.
* **Transactional Exporter Facade Contract**: Exporter implementations mutate active scene graphs (colliders, temporary LODGroup empties). Deep export failures must raise `ExportPipelineError` within the `try:` block so `finally:` rollback executes deterministically. The public facade (`ExporterManager.export_asset`) catches `ExportPipelineError`, logs structured context, and returns `(False, str(e))` to preserve the caller contract across UI operators and batch runners.
* **Multi-LOD Pivot & Origin Parity on Impostors**: All engine LOD parsers require all tiers to share the exact same pivot translation (`(obj.matrix_world.translation - lod0_pivot).length <= 1e-4`). Center impostors in local BMesh space rather than offsetting object location.
* **MSFS XML minSize Lower-Bound Invariance**: In MSFS XML, `<LOD minSize="X">` is the lower-bound exit threshold, whereas OmniMesh `tier.screen_size_pct` is the upper-bound entry threshold. LOD0 is always 100%, and LOD $i$ receives `lod_infos[i - 1].min_size`.
* **MSFS 2024 Modular Attachments (`attached_objects.cfg`)**: `attach_offset` coordinates in `[sim_attachment.N]` are strictly relative to the mounting socket empty (`attach_to_node`), never aircraft datum. Socket markers (`ATTACH_POINT_*`) in LOD0 must be exported in glTF, but attachment instances reside in `{AssetName}_Config` and are excluded from glTF.

### 2.3 Engine Bridge CQS & Domain Exception Contracts
* **Bridge Probe vs Command Invariance (CQS)**: Routine background UI heartbeat timers (`ping_engine`) are query probes and must NEVER raise `BridgeConnectionError` when target engine editors are closed or offline; they must return `(False, msg)`. Strongly typed `BridgeConnectionError` exceptions are strictly reserved for active payload transmissions (`sync_asset`, `sync_asset_headless`) on broken sockets, truncated frames, or network drops.
* **Bridge Probe Timeout Isolation**: Heartbeat queries and unit tests against offline engine ports (e.g. Unreal Engine on port 30010) must never block on default OS TCP connection timeouts (1+ second delay). Always supply `timeout_sec <= 0.08` or mock `ConnectionRefusedError` to maintain non-blocking UI cycles and sub-millisecond unit test execution.
