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
*(Deterministically runs dependency validation, Ruff linter & formatter check, Pyright static type checker, static architectural invariant audit via `scripts/audit_architecture.py`, and the full dual-runtime test suite).*

* **Dual-Runtime Test Architecture & Coverage Ratchets**:
  1. *Host Unit Tests (`tests/`)*: Fast pytest suite against `fake-bpy-module` stubs (`tests/conftest.py` provides canonical `MockVector`, `MockQuaternion`, `MockMeshObject`, and `MockAction` test doubles). Host coverage threshold is enforced via `[tool.coverage.report] fail_under` in `pyproject.toml`.
  2. *In-Blender Integration Tests (`tests/in_blender/`)*: Headless integration tests running inside a live Blender C-runtime via `scripts/run_blender_tests.py`.
  3. *Unified Coverage Gate*: `scripts/verify_ci.py` merges both coverage databases and enforces the unified coverage floor (`--fail-under=70`).
* **Large 3D Binary Asset Limit**: Model files (`.blend`, `.fbx`, `.gltf`, `.bin`, `.dds`) and raw textures must not exceed **50 MB** in Git tracking. Temporary bake scratch files and `.coverage*` artifacts must remain `.gitignore`d.

### 0.2 Git Commit Scope Mapping
Repository-specific component scopes required by `AGENTS.md` Section 6:
* `[Core]`: Core LOD decimation engine, modifier pipeline, impostor baking, property groups (`core/`).
* `[Exporters]`: Target engine exporters (MSFS 2024, Unreal Engine 5, Unity 6) (`exporters/`).
* `[Bridges]`: External tool bridges, IPC socket servers, subprocess execution (`bridges/`).
* `[UI]`: 3D Viewport N-Panels, custom UILists, modal operators, popovers (`ui/`).
* `[Tests]`: Test suite, test fixtures, headless Blender test runners (`tests/`, `scripts/test_engine_exports.py`).
* `[CI]`: Quality gate scripts, GitHub Actions workflows (`scripts/`, `.github/`).

### 0.3 Architecture Audit (`scripts/audit_architecture.py`) & Type Checking Contracts
* **Single Source of Truth for Ratchet Baselines**: Monotonic ceilings for `bpy.data` (locked at `0`), `hasattr`/`getattr` calls, local `: Any` assignments (locked at `0`), and the scoped `ALLOWED_CAST_ANY` allowlist are maintained exclusively in `scripts/audit_architecture.py`.
* **Audit Integrity**:
  * Every audit rule must catch semantic evasions (`getattr(bpy, "context")`, `except` blocks that only log without re-raising or handling) rather than bare syntax alone.
  * Never document "safe" workarounds for banned patterns; legitimate exceptions require a narrow, named allowlist entry in `scripts/audit_architecture.py`.
  * Never loosen an audit rule in the same change that makes failing code pass it.
* **`pyrightconfig.json` Ban**: Pyright silently prioritizes `pyrightconfig.json` over `[tool.pyright]` in `pyproject.toml`. Keep `pyproject.toml` as the sole configuration file.
* **Strict Typing & `Any` Ban in Domain Modules**: Domain signatures and local variable annotations in `core/` and `exporters/` must use concrete stub types (`bpy.types.Object`, `bpy.types.Context`, `bmesh.types.BMesh`) or structural protocols (`LODTierProtocol`, `LODSettingsProtocol`, `QuaternionLike`) under `TYPE_CHECKING`. `cast(Any, ...)` is restricted to `ALLOWED_CAST_ANY` in `scripts/audit_architecture.py` for verified Blender stub defects; runtime operator dispatch is encapsulated in `core/compat.py`.
* **Sanctioned File-Level Suppression**: `# pyright: reportInvalidTypeForm=none` is permitted only in UI modules declaring RNA properties (`ui/*_ops.py`, `ui/properties/`), never in `core/`, `exporters/`, or `bridges/`.

### 0.4 Cross-Platform Path & CI Test Invariants
* **Blender 5.x Minimum Baseline**: Legacy Blender 4.x compatibility is dropped (`blender_manifest.toml` locks `blender_version_min = "5.0.0"`). Keep `version` synchronized between `blender_manifest.toml` and `pyproject.toml`. CI headless runners baseline against Blender 5.3.0 (`linux-x64`) with a 3-attempt `apt-get` retry loop in `.github/workflows/`.
* **POSIX `os.path.splitdrive` Trap on Windows Paths**: On Linux runners, `os.path.splitdrive("C:/...")` returns `("", "C:/...")`. Cross-platform utilities comparing drive roots or computing blend-relative paths (`//`) must use `_split_drive_portable`.
* **Windows CI 8.3 Short Directory Aliasing (`RUNNER~1` vs `runneradmin`)**: On Windows GitHub Actions runners, `tempfile.mkdtemp()` returns 8.3 short paths, whereas `Path(p).resolve()` returns long paths. Test assertions comparing temporary paths must canonicalize via `Path(...).resolve()`.
* **Cross-Platform Subprocess Invocations**: Never hardcode Windows shells (`["cmd.exe", "/c", ...]`) in workers or tests; invoke `[sys.executable, "-c", "..."]` directly so Linux CI runners succeed.

---

## 1. Project Architecture & Module Boundaries

### 1.1 Layer Separation & Dependency Injection
* **Unidirectional Layer Boundaries**:
  * `ui/`: Presentation layer, 3D viewport panels, modal operators. Gathers user parameters and dispatches commands.
  * `core/`: Core decimation algorithms, impostor generation, mesh merging (`MeshMergeEngine`), hierarchy managers, and LOD chain calculators.
  * `exporters/`: Engine packaging logic (MSFS 2024, UE5, Unity 6) with transactional scene-graph rollback.
  * `bridges/`: External IPC socket clients, health probes, and live engine sync. Strictly non-blocking.
* **Zero Global Context / Database Reads in Domain (`core/`, `exporters/`)**:
  * Domain modules must never read `bpy.context` or `bpy.data` directly or indirectly (`getattr(bpy, "context" | "data")`).
  * `context`/`scene` and `blend_data: BlendData` must be injected explicitly from the presentation/CLI boundary.
  * Any function in `core/` declaring `blend_data` must require it as a non-optional parameter (`blend_data: BlendData` without `= None` or `| None`, enforced by `optional_blend_data_in_core` in `scripts/audit_architecture.py`) and fail fast with `ValueError` if `None` is passed at runtime.
* **UI Layout, Popover & Persistence Conventions**:
  * **Preset Row Layout**: Across all preset controls (Import, PBR, Configurator, LOD, Export), order buttons strictly as `[row.prop(..., "preset")] [row.popover(..., icon="PREFERENCES")] [DUPLICATE] [DELETE]`.
  * **Popover Space & Options-Only Rule**: Popovers (`OMNIMESH_PT_popover_*`) manage configuration properties and toggles only—never destructive action/execution buttons. Action rows paired with a popover in narrow N-Panels must hold at most **one** primary operator button so the gear icon is never clipped.
  * **Clean Path Initialization & Auto-Persistence**: Path properties (`DIR_PATH`, `FILE_PATH`) default to `""` (avoiding dummy `//Textures/` paths and Windows NetBIOS delays) and auto-synchronize via `_PERSISTENT_PIPELINE_KEYS` in `ui/properties/callbacks.py` to `pipeline_settings.json`.

### 1.2 Vehicle & Interactive Asset Scene-Graph Invariants
* **Unified Scene Data Model (`{AssetName}_Config`)**:
  Configuration metadata is decoupled from render geometry and stored in dedicated sibling Outliner collections alongside `{AssetName}_LOD0`. Decimation engines, mesh mergers, and render LOD generators must never mutate, decimate, or ingest objects in `{AssetName}_Config`:
  * **`Spatial` Subcollection**: Empties for Datum Origin, Center of Gravity (CG), aerodynamic reference points, ground contact points, scrape points, and fuel tank centroids.
  * **`Lights` Subcollection**: Photometric light empties with custom RNA parameters (color temperature K, lumen intensity, beam angle, attenuation radius, flash timing profiles).
  * **`Cameras` Subcollection**: Camera empties for pilot/driver eyepoints, instrument inspection zooms, exterior orbit pivots, and chase camera anchors.
  * **`Interaction` Subcollection**: Bounding box and hull empties defining VR/mouse click trigger volumes, grab handles, and switch articulation limits.
* **Serialization & Geometry Isolation Boundaries**:
  * **MSFS 2024 Serialization**: Serializes `{AssetName}_Config` into modular XML and CFG specifications (`systems.xml`, `cameras.xml`, `flight_model.cfg`, `attached_objects.cfg`).
  * **Geometry Export Isolation**: Mounting sockets (`ATTACH_POINT_*`) in LOD0 are preserved in exported glTF meshes for attachment rigging, whereas `{AssetName}_Config` empties and attachment instances are filtered out during mesh export.

---

## 2. Multi-Engine Export Pipelines & Target Engine Contracts

### 2.1 Live Engine Subprocess Gating & CLI Execution
* **Live Engine Subprocess Gating (`RUN_LIVE_ENGINE_TESTS`)**: Headless unit tests must gate live game engine subprocesses behind `RUN_LIVE_ENGINE_TESTS` to avoid 4–5s editor startup latency during standard test runs. Run `python scripts/test_engine_exports.py` to validate all 3 engine export pipelines end-to-end.
* **Engine Headless CLI Execution**:
  * **Unity 6**: `unity run <project_dir> --editor-version <installed_ver> -- -nographics`. Never pass `-quit` or `-batchmode` after `--`.
  * **Unreal Engine 5**: `UnrealEditor-Cmd.exe <Project.uproject> -run=pythonscript -script="<script>.py" -nullrhi -nosound -unattended`. Colliders: `UCX_{Asset}_{Index}`.
  * **MSFS 2024**: `fspackagetool.exe <Project.xml> -forcesteam -nopause` with `stdin=subprocess.DEVNULL`. Steam installs require `fspackagetool_overrideExePath.txt`. All interior references in `model.cfg` must use POSIX forward slashes (`interior=../model/{Interior}.xml`).

### 2.2 Exporter Hierarchy, Rollback & Sockets
* **Transactional Scene-Graph Rollback (`try...finally`)**: Exporters mutating object names (`UCX_`) or parenting meshes to temporary `LODGroup` empties must record original state in dictionaries, run export in `try:`, raise `ExportPipelineError` on deep failures, and restore original hierarchy and names in `finally:`. The public facade (`ExporterManager.export_asset`) catches `ExportPipelineError`, logs structured context, and returns `(False, str(e))`.
* **Multi-LOD Pivot & Origin Parity on Impostors**: All engine LOD parsers require all tiers to share the exact same pivot translation (`(obj.matrix_world.translation - lod0_pivot).length <= 1e-4`). Center impostors in local BMesh space rather than offsetting object location.
* **MSFS XML `minSize` Lower-Bound Invariance**: In MSFS XML, `<LOD minSize="X">` is the lower-bound exit threshold, whereas OmniMesh `tier.screen_size_pct` is the upper-bound entry threshold. LOD0 is always 100%, and LOD $i$ receives `lod_infos[i - 1].min_size`.
* **MSFS 2024 `attached_objects.cfg` CST Serialization Invariants**:
  * `attach_offset` coordinates in `[sim_attachment.N]` are strictly relative to the mounting socket empty (`attach_to_node`), never aircraft datum.
  * Official SDK samples frequently omit `attach_offset` and `attach_pbh` when zero. The Concrete Syntax Tree (CST) serializer must dynamically flush missing spatial keys upon section transition (or EOF) when non-zero coordinates exist, preserving comments, indentation, and custom SDK parameters losslessly.
  * Newly synthesized attachments must enforce gapless, monotonically increasing integer headers (`[sim_attachment.0]`, `[sim_attachment.1]`, ...).

### 2.3 Engine Bridge CQS & Domain Exception Contracts
* **Bridge Probe vs Command Invariance (CQS)**: Background UI heartbeat timers (`ping_engine`) are query probes and must return `(False, msg)` when target engine editors are offline—never raise `BridgeConnectionError`. `BridgeConnectionError` is reserved for active payload commands (`sync_asset`, `sync_asset_headless`) on broken sockets or network drops.
* **Bridge Probe Timeout Isolation**: Heartbeat queries and unit tests against offline engine ports (e.g. Unreal Live Link on `127.0.0.1:6776` or WebControl on `30010`) must supply `timeout_sec <= 0.08` or mock `ConnectionRefusedError` to prevent 1s+ OS TCP timeout stalls.
