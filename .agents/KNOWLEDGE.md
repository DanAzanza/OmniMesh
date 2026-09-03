# OmniMesh Domain & Runtime Knowledge Base

> **Rule**: This repository knowledge base serves strictly as persistent memory for **non-obvious runtime quirks, hardware/model constraints, and hidden system behaviors** that cannot be inferred from reading source code, function signatures, or docstrings alone. Do NOT document standard component mappings, obvious file listings, or generic code patterns here.

---

## 1. Blender 4.2+ & 5.2 LTS API Quirks & Runtime Invariants

### 1.1 Collection & Object RNA Lifecycle
* **RNA Pointer Invalidation on Collection Purge**: Storing a collection reference (`target = bpy.data.collections.get(...)`) before executing a cleanup/purge routine that unlinks or removes collections invalidates the C struct pointer (`ReferenceError: StructRNA of type Collection has been removed`). Purges and deletions must strictly precede retrieving or creating target collections.
* **View Layer Collection Exclusion (`LayerCollectionGuard`)**: Evaluating modifiers, depsgraphs, or transferring normals fails or outputs empty meshes when the target collection is excluded (`layer_collection.exclude = True`). All multi-collection processing must be wrapped in `LayerCollectionGuard` to temporarily un-exclude collections and restore view layer state in `finally`.

### 1.2 Shading, Enums & EEVEE Next Compatibility
* **EEVEE Next `shadow_method` Removal**: In Blender 4.2+ and 5.2 LTS, `material.shadow_method` was removed (`AttributeError: 'Material' object has no attribute 'shadow_method'`). Shadow handling is raytraced or automatic. Material transparency setup must guard with `if hasattr(mat, "shadow_method"):`.
* **glTF 2.0 Export Format**: Use `export_format='GLTF_SEPARATE'` for `.gltf` + `.bin` export in Blender 5.2 LTS (`GLTF_EMBEDDED` was deprecated).
* **`DATA_TRANSFER` Loop Mapping**: `dt_mod.loop_mapping = 'POLYINTERP_LNORPROJ'` is the only valid enum in Blender 5.2 LTS (`POLYINTERP_NEAREST_CORNER` was deprecated/removed).
* **Native `mathutils.geometry.delaunay_2d_cdt` Return Length**: Unlike standard 2D triangulation routines that return `(verts, edges, faces)`, Blender's native `delaunay_2d_cdt` returns a 6-item tuple: `(verts, edges, faces, orig_verts, orig_edges, orig_faces)`. Unpacking fewer items raises `ValueError`.

### 1.3 Skeletal Mesh Rigging & Transform Invariants
* **Rest-Pose Coordinate Inversion**: Transforming bone-parented static props into rest-pose local space before joining into a skinned character prevents "pose explosion" (where animated rotations are permanently baked into the rest mesh).
* **Armature Rest-Pose Lock**: During decimation and normal data transfers, `armature.data.pose_position` MUST be set to `'REST'`, and restored afterwards.
* **Vertex Group Index Shifting**: In Blender, removing a vertex group via `obj.vertex_groups.remove(vg)` shifts the indices of all subsequent groups. Always collect used group *names* first and purge by name to avoid data corruption.
* **GPU Weight Singularity Guard**: Stripping micro-weights ($< 0.01$) must never leave a vertex with $\sum w = 0.0$. Fall back to the anchor bone (`1.0`) if all weights drop below epsilon, preventing GPU division-by-zero NaN shader crashes.
* **`bpy.types.VertexGroup.add()` Parameter Quirk**: `vg.add(index, weight, type)` accepts a list of vertex indices, but `weight` MUST be a single float (passing a list/array of weights raises `TypeError`).

### 1.4 Viewport Simulator Performance & Undo Hygiene
* **Draw Callback Restriction**: Writing to Blender RNA/DNA properties inside `draw_handler_add` raises `RuntimeError: Operator or data manipulation during draw callback is forbidden`.
* **Zero Undo Pollution**: The modal simulation loop must omit `{'UNDO'}` from `bl_options` to keep the user's `Ctrl+Z` history clean.
* **Differential Visibility Sets**: Only call `obj.hide_set()` if `obj.hide_get()` differs from the target state. This avoids rebuilding the dependency graph on frames where the camera moves within the same LOD zone.

### 1.5 Batch Processing, Memory & Threading
* **Global Undo & Orphan Datablock Purge**: Batch processing multi-asset folders without disabling global undo retains the modifier/import history of every asset in RAM. Operators must wrap execution in `use_global_undo = False` and call `bpy.data.orphans_purge(...)` + `gc.collect()` + OS heap compaction (`ctypes.cdll.msvcrt._heapmin()` on Win32 / `libc.so.6.malloc_trim(0)` on Linux) to prevent multi-gigabyte memory leaks.
* **Async Texture Worker Safety**: Blender's Python `bpy` C-API is not thread-safe. Worker threads in `ThreadPoolExecutor` must receive pre-quantized `uint8` NumPy arrays / PIL images and file paths only (zero `bpy` calls on workers). Enforce a synchronous join barrier (`wait_all()`) before exporting packages.
* **Modifier Execution under `temp_override`**: In Blender 5.2+, applying modifiers on objects inside collections without `temp_override(active_object=lod_obj, object=lod_obj, selected_objects=[lod_obj])` can fail or cause view layer selection lockups if the object is not active in the current window context.

### 1.6 UI Drawing & Dynamic Hot-Reloading
* **Invalid Icon RNA Fatal Draw Abort**: Passing an invalid `icon` string (e.g. `"DIAGNOSTIC"`) to `layout.label()` or `layout.operator()` raises a fatal Python `TypeError` inside Blender's C++ UI draw loop, instantly aborting panel rendering for that frame and leaving the panel header un-expandable or blank without viewport errors. Always verify icon strings against valid Blender RNA enum items.
* **Dynamic UI Class Unregistration & RNA Registry Ghosting**: When hot-reloading add-on modules during live development or MCP sessions, unregistering classes via module class objects (`bpy.utils.unregister_class(cls)`) fails if old class references were already replaced in `sys.modules`. In Blender's underlying C++/RNA registry, orphaned panel definitions (`OMNIMESH_PT_*`) persist in `bpy.types` and cause registration collisions. Clean unregistration must dynamically inspect `dir(bpy.types)` and unregister matching class identifiers before re-registering.

---

## 2. Headless CI, Python & Testing Quirks

* **`MagicMock` Boolean Evaluation Trap**: In headless tests with mock objects, `getattr(mock_obj, "prop", False)` returns a truthy `MagicMock` when unset. Code that runs under test mocks must explicitly check `bool(getattr(obj, "prop", False) is True)`.
* **Python Ternary Tuple Return Precedence**: `return a if cond else b, c` evaluates as `return a if cond else (b, c)`. Parentheses `return (a if cond else b), c` are mandatory to return a tuple in all branches.
* **Linux `sys.path` Quirk**: Unlike Windows, `pytest` on Ubuntu runners does NOT include the root working directory in `sys.path`. Always configure `pythonpath = .` in `pytest.ini` and declare `PYTHONPATH: .` in GitHub Actions workflows.
* **Dependency Parity Invariant**: Blender bundles `numpy` and `Pillow` internally, but standalone test suites in clean CI environments require them declared in `pyproject.toml` and installed via `pip install -e .[dev]`.
