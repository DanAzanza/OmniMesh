# OmniMesh Domain & Runtime Knowledge Base

> **Rule**: Persistent memory strictly for **non-obvious runtime quirks, hardware/model constraints, and hidden system behaviors** that cannot be inferred from reading source code, function signatures, or docstrings alone.

---

## 0. Repository Gates & Workflow Contracts

### 0.1 Central Pre-Commit Verification Gate
The central verification script required by `AGENTS.md` Section 7:
```bash
python scripts/verify_ci.py
```
*(Deterministically runs dependency validation, Ruff linter & formatter check, Pyright static type checker across core and test modules, and the full test suite).*

### 0.2 Git Commit Scope Mapping
Repository-specific component scopes required by `AGENTS.md` Section 6:
* `[Core]`: Core LOD decimation engine, modifier pipeline, impostor baking, property groups (`core/`).
* `[Exporters]`: Target engine exporters (MSFS 2024, Unreal Engine 5, Unity 6, Godot 4) (`exporters/`).
* `[Bridges]`: External tool bridges, IPC socket servers, subprocess execution (`bridges/`).
* `[UI]`: 3D Viewport N-Panels, custom UILists, modal operators, popovers (`ui/`).
* `[Tests]`: Test suite, test fixtures, headless Blender test runners (`tests/`, `scripts/test_engine_exports.py`).
* `[CI]`: Quality gate scripts, GitHub Actions workflows (`scripts/`, `.github/`).

### 0.3 Autonomous Subagent & Large Binary Conventions
* **Subagent Workflow Roles**:
  * Architecture sparring & critique gate: `plan_critic`
  * Pre-commit adversarial audit gate: `pre_commit_auditor`
* **Large 3D Binary Asset Limit**:
  * Model files (`.blend`, `.fbx`, `.gltf`, `.bin`, `.dds`) and raw textures must not exceed **50 MB** in Git tracking. Ensure temporary bake scratch files and `.coverage` artifacts remain strictly `.gitignore`d.

---

## 1. Blender 5.0+ & 5.2 LTS API Quirks & Runtime Invariants

### 1.1 Shading, Enums & EEVEE Next
* **EEVEE Next Shading**: `material.shadow_method` does not exist and `mat.blend_method = 'CLIP'` is dead code. Transparency for cutouts/impostors strictly requires `mat.surface_render_method = 'DITHERED'` (or `'BLENDED'`).
* **glTF 2.0 Export Format**: Use `export_format='GLTF_SEPARATE'` for `.gltf` + `.bin` export in Blender 5.2 LTS (`GLTF_EMBEDDED` was deprecated).
* **`DATA_TRANSFER` Loop Mapping**: `dt_mod.loop_mapping = 'POLYINTERP_LNORPROJ'` is the only valid enum in Blender 5.2 LTS (`POLYINTERP_NEAREST_CORNER` was removed).
* **Native `mathutils.geometry.delaunay_2d_cdt` Return Length**: Unlike standard 2D triangulation routines returning 3 items, Blender's native C-routine returns a 6-item tuple: `(verts, edges, faces, orig_verts, orig_edges, orig_faces)`.

### 1.2 Collection & Object RNA Lifecycle
* **RNA Pointer Invalidation on Collection Purge**: Storing a collection reference before unlinking/removing collections invalidates the C struct pointer (`ReferenceError: StructRNA of type Collection has been removed`). Purges and deletions must strictly precede retrieving or creating target collections.
* **View Layer Collection Exclusion (`LayerCollectionGuard`)**: Evaluating modifiers, depsgraphs, or transferring normals fails or outputs empty meshes when the target collection is excluded (`layer_collection.exclude = True`). All multi-collection processing must be wrapped in `LayerCollectionGuard`.
* **Modifier Execution Context under `temp_override`**: In Blender 5.2+, applying modifiers on objects inside collections without `temp_override(active_object=lod_obj, object=lod_obj, selected_objects=[lod_obj])` fails or causes view layer selection lockups.

### 1.3 Viewport Simulator Performance & C-API Memory
* **Draw Callback Restriction**: Writing to Blender RNA/DNA properties inside `draw_handler_add` raises `RuntimeError: Operator or data manipulation during draw callback is forbidden`. Draw handlers must remain strictly read-only.
* **Zero Undo Pollution**: Modal simulation loops must omit `{'UNDO'}` from `bl_options` to keep user `Ctrl+Z` history clean.
* **Differential Visibility Sets**: Only call `obj.hide_set()` if `obj.hide_get()` differs from the target state to avoid rebuilding the depsgraph every frame.
* **Blender Native Image Buffer Deallocation (`buffers_free`)**: `img.pixels.foreach_get(buf)` caches native unmanaged memory in C++. Free explicitly via `if hasattr(img, "buffers_free"): img.buffers_free()` inside `finally` blocks.
* **Global Undo & Memory Leaks in Batch Runs**: Multi-asset batch processing retains undo modifier history in RAM. Wrap in `use_global_undo = False` and invoke `bpy.data.orphans_purge(...)` + `gc.collect()` + OS heap compaction (`ctypes.cdll.msvcrt._heapmin()` on Win32 / `malloc_trim(0)` on Linux).
* **Async Texture Worker Safety**: Blender's Python `bpy` C-API is not thread-safe. Worker threads in `ThreadPoolExecutor` must receive pre-quantized NumPy arrays / PIL images and file paths only (zero `bpy` calls on workers). Enforce a synchronous join barrier (`wait_all()`) before package export.

---

## 2. Blender RNA, UI & Extension Traps

* **Extension Directory Invariant (Blender 4.2+)**: User extensions reside strictly in `%APPDATA%\Blender Foundation\Blender\<ver>\extensions\user_default\<addon_id>` (`bl_ext.user_default.<addon_id>`). Copying files to legacy `scripts/addons/<addon_id>` will NOT update the live extension.
* **Blender Extension Wheel Dependency Isolation**: User extensions (`blender_manifest.toml`) do not bundle third-party PyPI wheels (such as Pillow/PIL). In live Blender installations, `Image` is `None`. All core texture packing, channel extraction, and resampling operations must rely strictly on pure-NumPy vectorized algorithms (e.g. `resample_channel_bilinear_numpy`) rather than falling back to crude nearest-neighbor slicing or failing due to missing wheels. Test suites must explicitly test the `Image = None` code path.
* **Dynamic UI Class Unregistration & RNA Ghosting**: Hot-reloading modules fails if stale class references persist in Blender's C++/RNA registry. Clean unregistration must dynamically inspect `existing = getattr(bpy.types, cls.__name__, None)` and unregister `existing` before registering the reloaded class definition.
* **UIList Duplicate Registration & Zero-Height Collision Trap**: Failing to dynamically unregister reloaded `UIList` classes causes duplicate classes in `bpy.types.UIList.__subclasses__()`, rendering template lists with zero vertical height.
* **Ghost "Misc" Sidebar Tab Trap**: Any `Panel` declared with `bl_region_type = 'UI'` without an explicit `bl_category` defaults to `"Misc"`. Popovers must use `bl_region_type = 'HEADER'`. Collapsible subpanels (`bl_parent_id`) must explicitly declare `bl_category = "OmniMesh"`.
* **Popover Horizontal Space Starvation**: In narrow N-Panels, pairing multiple text operator buttons alongside a popover button in an aligned row silently clips the gear icon off-screen. Action rows paired with a popover must hold at most ONE primary operator button.
* **RNA Mutation Ban in `Panel.draw()` (Runaway Redraw Loop)**: Never mutate RNA properties or sync data inside `draw()`. Writing to RNA triggers layout invalidation, forcing an infinite 60fps+ redraw loop at 100% CPU thread load. All sync logic belongs in `update` callbacks, operators, or `load_post` handlers.
* **`from __future__ import annotations` in Operators**: Writing `prop: Any = bpy.props.StringProperty(...)` stores the literal string `'Any'` in annotations, causing Blender to silently skip RNA registration and raise `TypeError: keyword unrecognized`. Use `prop: bpy.props.StringProperty(...)` directly.
* **Dynamic `EnumProperty` Item Invalidation**: When deleting a custom item (such as a JSON preset), reassign active dynamic enum properties to a guaranteed fallback (e.g. `DEFAULT_PRESET_ID`) *before* disk deletion to prevent `bpy.rna WARNING current value matches no enum`.
* **RNA Property Leading Underscore Ban**: Properties on `bpy.types.PropertyGroup` MUST NOT start with an underscore (`_`), or registration of all subsequent properties in the class halts silently.
* **Operator Subclassing Invariant**: Never subclass a registered `bpy.types.Operator` class. Subclassing corrupts Blender's C++ RNA class table. Inherit directly from `bpy.types.Operator` and delegate via `bpy.ops`.
* **Blender C-RNA Dynamic Enum Assignment in Operators**: Assigning a dynamically added enum item immediately inside `execute()` can fail if the enum items tuple was cached at invocation. Wrap the assignment in a deferred timer (`bpy.app.timers.register(..., first_interval=0.005)`).
* **BMesh `bm.verts.index_update()` Requirement**: Newly created or bisected vertices keep `v.index == -1`. Attempting to populate vertex groups using `vg.add([v.index for v in ...])` without calling `bm.verts.index_update()` silently adds 0 vertices.

---

## 3. Skeletal Rigging, Transforms & BMesh Invariants

* **Rest-Pose Coordinate Inversion**: Transform bone-parented props into rest-pose local space before joining into a skinned character to prevent pose explosion.
* **Armature Rest-Pose Lock**: During decimation and normal data transfers, `armature.data.pose_position` MUST be set to `'REST'`, and restored afterwards.
* **Quaternion Sign Continuity Invariant ($\mathbf{q}_t \cdot \mathbf{q}_{t-1} < 0$)**: In 4D hyperspace, $\mathbf{q}$ and $-\mathbf{q}$ represent the identical spatial orientation ($360^\circ$ equivalence). If consecutive keyframes flip signs ($\mathbf{q}_t \cdot \mathbf{q}_{t-1} < 0$), spherical or linear interpolation (SLERP/LERP) traverses the long path around the hypersphere, causing visible $360^\circ$ spin flips. `AnimationRigSanitizer.enforce_quaternion_continuity` must negate $\mathbf{q}$ to $-\mathbf{q}$ when the dot product is negative prior to baking deform animations.
* **Vertex Group Index Shifting**: `obj.vertex_groups.remove(vg)` shifts indices of subsequent groups. Collect used group names first and purge by name.
* **GPU Weight Singularity Guard**: Stripping micro-weights ($< 0.01$) must never leave $\sum w = 0.0$ (causing GPU division-by-zero NaN shader crashes). Fall back to anchor bone (`1.0`).
* **`bpy.types.VertexGroup.add()` Parameter Quirk**: `vg.add(index, weight, type)` accepts a list of indices, but `weight` MUST be a single float (passing a list/array raises `TypeError`).
* **Copy-on-Write (CoW) Mesh Datablock Safety**: Applying modifiers or `transform_apply` on objects whose mesh datablock has multiple users (`obj.data.users > 1`, e.g. `Alt+D` duplicates) mutates shared geometry across all variants simultaneously. Always isolate: `if obj.data.users > 1: obj.data = obj.data.copy()`.
* **Shape Keys & Modifier Application (Fail-Fast QEM)**: In Blender C-API (`modifier.cc`), `bpy.ops.object.modifier_apply` strictly throws `RuntimeError: Modifier cannot be applied to a mesh with shape keys`. All derivative LOD meshes (`tier_idx >= 1`) must have shape keys purged via `purge_all_shape_keys(tier_obj)` before QEM decimation runs, while strictly preserving shape keys on the hero source mesh (LOD0). Decimation routines must raise `DecimationError` fail-fast upon apply failure rather than silently discarding modifiers.
* **BMesh Dissolve & Boundary Pinning Index Invariance**: `bmesh.ops.dissolve_limit` mutates vertex indices. Planar limited dissolve must always run *before* boundary and UV seam tagging on the post-dissolve topology.
* **Spatial Bisect Seam Pinning vs. Natural Mesh Openings**: Tagging edges with `edge.is_boundary` mistakenly locks natural openings (eyes, sleeves). Seam locking must test vertex world coordinates against the explicit mathematical bisect plane ($|wco \cdot \vec{n} - d| < \epsilon$).
* **AABB Extent Bounding Sphere vs Centroid Bias**: Computing bounding sphere centers via point centroid $\frac{1}{N}\sum \mathbf{p}$ biases centers toward dense vertex clusters (cockpit controls, bevels), artificially inflating radius $r$ and decimation error. Centers must strictly derive from symmetric AABB extents $\frac{\min + \max}{2}$.
* **Blender RNA `ReferenceError` on Removed Objects**: Accessing attributes on an unlinked/removed RNA struct raises `ReferenceError: StructRNA of type Object has been removed`. Viewport draw handlers must guard with `(ReferenceError, AttributeError)`.

---

## 4. Multi-Engine Export Pipelines & Testing

### 4.1 Headless Testing & CLI Commands
* **Blender Headless `--python-exit-code 1`**: Blender headless (`blender -b`) exits with code `0` even when unhandled exceptions occur or unittests fail. CI pipelines and verification scripts must explicitly supply `--python-exit-code 1`.
* **Headless `bpy` Mocking Boundary**: When executing pure unit tests via Pytest outside Blender, `bpy` is `None`. Defensive guards (`if not bpy or not context: return True, ...`) bypass execution early. To test transactional rollbacks, pose restorations, and failure branches in headless mode, tests must explicitly mock `bpy` using `monkeypatch.setattr("core.lod_generator.bpy", MagicMock())`.
* **Live Engine Subprocess Gating (`RUN_LIVE_ENGINE_TESTS`)**: Spawning external game engine executables (such as `godot --headless`) introduces ~4–5 seconds of startup latency per test run. Headless unit test suites must gate live editor subprocesses behind `RUN_LIVE_ENGINE_TESTS` to keep regular test runs sub-5s while preserving end-to-end integration capability.
* **Multi-Engine Export Test Runner**: Run `python scripts/test_engine_exports.py` to validate all 4 engine export pipelines (distinct from the central pre-commit gate `scripts/verify_ci.py`).
* **Engine Headless CLI Execution**:
  * **Godot 4**: `godot --headless --path <project_dir> --editor --quit` (requires `Godot_*_win64_console.exe`, GUI exe drops stdout/stderr pipes). Colliders: `-convcolonly` for invisible hulls (`-convcol` creates visible shapes). Custom impostor suffixes bypass regex; map explicitly to max distance tier (`visibility_range_begin = max_tier_distance`).
  * **Unity 6**: `unity run <project_dir> --editor-version <installed_ver> -- -nographics`. Never pass `-quit` or `-batchmode` after `--`.
  * **Unreal Engine 5**: `UnrealEditor-Cmd.exe <Project.uproject> -run=pythonscript -script="<script>.py" -nullrhi -nosound -unattended`. Colliders: `UCX_{Asset}_{Index}`.
  * **MSFS 2024**: `fspackagetool.exe <Project.xml> -forcesteam -nopause` with `stdin=subprocess.DEVNULL`. Steam installs require `fspackagetool_overrideExePath.txt`. All interior references in `model.cfg` must use POSIX forward slashes (`interior=../model/{Interior}.xml`).

### 4.2 Exporter Hierarchy, Rollback & Sockets
* **Transactional Scene-Graph Rollback (`try...finally`)**: Single-mesh engine exporters mutate names (`UCX_`, `-convcol`) and parent meshes to temporary `LODGroup` empties. Exporters must record original state in dictionaries, run export in `try`, and restore original hierarchy and names in `finally`.
* **Multi-LOD Pivot & Origin Parity on Impostors**: All engine LOD parsers require all tiers to share the exact same pivot translation (`(obj.matrix_world.translation - lod0_pivot).length <= 1e-4`). Center impostors in local BMesh space rather than offsetting object location.
* **MSFS XML minSize Lower-Bound Invariance**: In MSFS XML, `<LOD minSize="X">` is the lower-bound exit threshold, whereas OmniMesh `tier.screen_size_pct` is the upper-bound entry threshold. LOD0 is always 100%, and LOD $i$ receives `lod_infos[i - 1].min_size`.
* **MSFS 2024 Modular Attachments (`attached_objects.cfg`)**: `attach_offset` coordinates in `[sim_attachment.N]` are strictly relative to the mounting socket empty (`attach_to_node`), never aircraft datum. Socket markers (`ATTACH_POINT_*`) in LOD0 must be exported in glTF, but attachment instances reside in `{AssetName}_Config` and are excluded from glTF.
* **Blender MCP Socket Server (Port 9876)**: The `blender-mcp` toolserver requires Siddharth Ahuja's TCP JSON socket server on `127.0.0.1:9876` (`blender_mcp.py`). Campbell Barton's official extension (`bl_ext.blender_org.mcp`) uses stdio and will reject port 9876 connections.

### 4.3 Engine Bridge CQS & Domain Exception Contracts
* **Bridge Probe vs Command Invariance (CQS)**: Routine background UI heartbeat timers (`ping_engine`) are query probes and must NEVER raise `BridgeConnectionError` when target engine editors are closed or offline; they must return `(False, msg)`. Strongly typed `BridgeConnectionError` exceptions are strictly reserved for active payload transmissions (`sync_asset`, `sync_asset_headless`) on broken sockets, truncated frames, or network drops.
* **Bridge Probe Timeout Isolation**: Heartbeat queries and unit tests against offline engine ports (e.g. Unreal Engine on port 30010) must never block on default OS TCP connection timeouts (1+ second delay). Always supply `timeout_sec <= 0.08` or mock `ConnectionRefusedError` to maintain non-blocking UI cycles and sub-millisecond unit test execution.
* **Transactional Exporter Facade Contract**: Exporter implementations mutate active scene graphs (colliders, temporary LODGroup empties). Deep export failures must raise `ExportPipelineError` within the `try:` block so `finally:` rollback executes deterministically. The public facade (`ExporterManager.export_asset`) catches `ExportPipelineError`, logs structured context, and returns `(False, str(e))` to preserve the caller contract across UI operators and batch runners.

---

## 5. Impostor Systems & Atlas Baking Invariants

* **Octahedral Normal Baking Invariant**: Octahedral atlas normals must be rendered via camera-orbit animation frames (1..64) in an isolated unlit scene (`bpy.ops.render.render(animation=True)`). Neutral surface-facing normal is $(0.5, 0.5, 1.0)$.
* **Cycles GPU Device Detection (Blender 5.0+)**: Assigning `cpref.compute_device_type = backend` does NOT automatically refresh `cpref.devices`. Calling `cpref.get_devices()` is mandatory before iterating devices or setting `d.use = True`.
* **Headless Impostor Bake Acceleration**: Software OpenGL/Vulkan via Mesa `llvmpipe` on CPU cloud runners stalls on shader compilation (>25 min for 192 views). Headless bake scenes (`bpy.app.background == True`) must prioritize CPU `CYCLES` with `samples = 1` and SIMD BVH ray-tracing (~12s).
* **Zenith Pole Singularity & Dynamic Up-Vector**: At zenith $(0, 0, 1)$, naive camera tracking collapses into a zero vector and causes $180^\circ$ highlight flipping. The camera coordinate basis must dynamically switch its reference up-vector from $(0, 0, 1)$ to $(0, 1, 0)$ when $|\text{Forward}_z| \ge 0.999$.
* **Single-Card Impostor UV Island Packing Hazard**: `bpy.ops.uv.pack_islands()` displaces normalized $[0, 1]^2$ UV bounds on single-card octahedral proxy meshes. Single-card and octahedral meshes must be strictly excluded from automatic island packing.
* **Fillrate Overdraw Cutout Octagons**: Bounding sphere quads leave $> 80\%$ transparent pixels on slender assets. Beveling quad corners by $25\%$ yields an 8-vertex convex polygon that cuts transparent fillrate overdraw by $30\text{--}40\%$.
* **Windows UNC `//` NetBIOS Freeze Trap on Unsaved Scenes**: In unsaved scenes (`filepath == ""`), relative paths starting with `"//"` evaluate as Windows UNC network paths (`\\Textures`), triggering a 30-second NetBIOS timeout before `[WinError 53]`. Unsaved relative paths must anchor to `tempfile.gettempdir()`.
* **Blender C-API `img.pixels` Scanline Inversion**: `img.pixels.foreach_get` orders scanlines bottom-up ($Y=0$ at bottom). Standard PNG encoders write top-down ($Y=0$ at top). Without vertical array reversal (`np.ascontiguousarray(arr.reshape((h, w, 4))[::-1]...)`), baked octahedral tiles are inverted, corrupting octahedral UV sampling.
* **Camera-Space Normal Mapping Z-Sign Invariant**: Blender camera forward is $-Z$ in camera space ($Z_{\text{cam}} = -1.0$ for camera-facing surfaces). To map to tangent space $+Z$ (flat blue $(0.5, 0.5, 1.0)$), the Z scale factor in the unlit emission override must be $-0.5$ (`(0.5, -0.5, -0.5)` for UE5 DirectX, `(0.5, 0.5, -0.5)` for OpenGL). Using $+0.5$ produces $Z \le 0.0$ (pitch black normals).
* **AgX / Filmic Color Management on Data Passes**: In Blender 5.0+, the default `AgX` view transform tone-maps linear vectors into non-linear sRGB (crushing normal blue channels from $1.0$ down to $\sim 0.3$). Ephemeral bake scenes must set `bake_scene.view_settings.view_transform = "Raw"` for data passes (Normal, Depth, ORM) and `"Standard"` for BaseColor.
* **Billboard Perspective Fanning vs Uniform View Vector**: Per-fragment `Geometry.Incoming` on billboard proxy quads causes perspective fanning across large quads at close distance, crossing octahedral tile thresholds and causing seams across the asset face. Shaders must compute a uniform view vector: `normalize(CamWorldPos - ObjWorldPos)` via `ShaderNodeVectorTransform(POINT, CAMERA/OBJECT -> WORLD)`.
* **Decoupled Billboard Tracking Target vs F-Curve Animation Overwrite**: Billboard `TRACK_TO` targeting a camera with turntable keyframes causes depsgraph F-curve evaluation to clobber camera position updates during interactive navigation. The billboard constraint must target an Empty (`Preview_Tracker_Target`) driven by an epsilon-gated background timer (`bpy.app.timers`) at $10^{-4}$ threshold.

---

## 6. Vehicle & Interactive Asset Scene-Graph Invariants

### 6.1 Unified Scene Data Model (`{AssetName}_Config`)
Configuration metadata is strictly decoupled from render geometry and stored in dedicated sibling Outliner collections alongside `{AssetName}_LOD0`. Decimation engines, mesh mergers, and render LOD generators must never mutate, decimate, or ingest objects in `{AssetName}_Config`:
* **`Spatial` Subcollection**:
  * Empties representing Datum Origin, Center of Gravity (CG), aerodynamic reference points, ground contact points (gear/wheels), scrape points, and fuel tank centroids.
* **`Lights` Subcollection**:
  * Photometric light empties with custom RNA parameters: color temperature (K), lumen intensity, beam angle, attenuation radius, and animated flash timing profiles (nav, beacon, strobe, taxi, landing, cabin).
* **`Cameras` Subcollection**:
  * Camera empties defining pilot/driver first-person eyepoints, instrument inspection zooms, exterior orbit pivots, and chase camera anchor points.
* **`Interaction` Subcollection**:
  * Bounding box and hull empties defining VR/mouse click trigger volumes, grab handles, and switch articulation limits.

### 6.2 Serialization & Geometry Isolation Boundaries
* **MSFS 2024 Serialization**: Serializes `{AssetName}_Config` into modular XML and CFG specifications (`systems.xml`, `cameras.xml`, `flight_model.cfg`, `attached_objects.cfg`).
* **Geometry Export Isolation**: Configuration metadata Empties must remain strictly separate from exported glTF meshes. Mounting sockets (`ATTACH_POINT_*`) in LOD0 are preserved for attachment rigging, but config Empties reside in `{AssetName}_Config` and are filtered during mesh export.

---

## 7. Subprocess & Headless Runtime Execution Invariants

* **Headless Subprocess CLI Argument Parsing Trap (`--` delimiter)**:
  When launching headless Blender with `--python script.py -- [args]`, Python's `argparse.parse_known_args()` terminates option parsing upon encountering `--`. All subsequent arguments are placed into the `unknown` vector. Scripts expecting CLI arguments inside Blender must explicitly slice `argv = sys.argv[sys.argv.index("--") + 1:]` prior to invoking `parser.parse_known_args(argv)`. Failure to slice `sys.argv` causes flags like `--in-blender` to be missed (`args.in_blender == False`), causing scripts that re-invoke Blender to enter infinite recursive fork loops.
* **Working Directory `sys.path` Resolution under `--factory-startup`**:
  Headless Blender instances launched with `--factory-startup` do not automatically register the repository working directory in Python's `sys.path`. Subprocess scripts executed via `--python` must programmatically determine the repository root (`os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`) and inject it into `sys.path` before attempting to import repository packages (`core`, `ui`, `exporters`, `bridges`).
* **BMesh Topological Rollback and Recovery Contract**:
  During non-manifold edge or bowtie vertex splits in BMesh, `bmesh.ops` operations can fail midway. The standard contract requires: if new element creation fails, attempt restoring original vertices; if restoration succeeds, log a warning and preserve the original geometry safely; if restoration *also* fails, immediately raise `TopologyError` fail-fast with actionable diagnostics rather than leaving deleted elements or corrupted holes in the mesh.

