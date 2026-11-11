# Blender Platform & Runtime Knowledge Base

> **Scope**: Universally applicable to Blender 5.0+ and 5.2 LTS add-on development, headless automation, and C-API bindings.
> **Rule**: Persistent memory strictly for **non-obvious runtime quirks, C-API memory management, RNA lifecycle traps, and `fake-bpy-module` stub defects** that cannot be inferred from reading standard Python documentation or type annotations alone.

---

## 1. Blender 5.0+ & 5.2 LTS Shading, Enums & Rendering

### 1.1 Shading, Enums & EEVEE Next
* **EEVEE Next Shading**: `material.shadow_method` does not exist and `mat.blend_method = 'CLIP'` is dead code. Transparency for cutouts/impostors strictly requires `mat.surface_render_method = 'DITHERED'` (or `'BLENDED'`).
* **glTF 2.0 Export Format**: Use `export_format='GLTF_SEPARATE'` for `.gltf` + `.bin` export in Blender 5.2 LTS (`GLTF_EMBEDDED` was deprecated).
* **`DATA_TRANSFER` Loop Mapping & `ray_radius` BVH Traversal Trap**: `dt_mod.loop_mapping = 'POLYINTERP_LNORPROJ'` is the only valid projected normal loop mapping enum in Blender 5.2 LTS (`POLYINTERP_NEAREST_CORNER` was removed). Keep `dt_mod.ray_radius = 0.0` and `use_max_distance = False`: a non-zero `ray_radius` forces `BLI_bvhtree_ray_cast` to perform cylindrical radius overlap checks ($O(N \cdot K)$ instead of $O(N \log M)$), degrading 100k-triangle normal reprojection from ~1.2s to ~14.8s.
* **Native `mathutils.geometry.delaunay_2d_cdt` Return Length**: Unlike standard 2D triangulation routines returning 3 items, Blender's native C-routine returns a 6-item tuple: `(verts, edges, faces, orig_verts, orig_edges, orig_faces)`.

### 1.2 Cycles GPU & Headless Rendering Invariants
* **Cycles GPU Device Detection**: Assigning `cpref.compute_device_type = backend` does NOT automatically refresh `cpref.devices`. Calling `cpref.get_devices()` is mandatory before iterating devices or setting `d.use = True`.
* **Headless Impostor Bake Acceleration**: Software OpenGL/Vulkan via Mesa `llvmpipe` on CPU cloud runners stalls on shader compilation (>25 min for 192 views). Headless bake scenes (`bpy.app.background == True`) must prioritize CPU `CYCLES` with `samples = 1` and SIMD BVH ray-tracing (~12s).
* **AgX / Filmic Color Management on Data Passes**: In Blender 5.0+, the default `AgX` view transform tone-maps linear vectors into non-linear sRGB (crushing normal blue channels from $1.0$ down to $\sim 0.3$). Ephemeral bake scenes must set `bake_scene.view_settings.view_transform = "Raw"` for data passes (Normal, Depth, ORM) and `"Standard"` for BaseColor.

---

## 2. Collection & Object RNA Lifecycle

* **RNA Pointer Invalidation on Collection Purge**: Storing a collection reference before unlinking/removing collections invalidates the C struct pointer (`ReferenceError: StructRNA of type Collection has been removed`). Purges and deletions must strictly precede retrieving or creating target collections.
* **View Layer Collection Exclusion (`LayerCollectionGuard`)**: Evaluating modifiers, depsgraphs, or transferring normals fails or outputs empty meshes when the target collection is excluded (`layer_collection.exclude = True`). All multi-collection processing must ensure target layer collections are included.
* **Modifier Execution Context under `temp_override`**: In Blender 5.2+, applying modifiers on objects inside collections without `temp_override(active_object=lod_obj, object=lod_obj, selected_objects=[lod_obj])` fails or causes view layer selection lockups.
* **Evaluated Depsgraph & Matrix Evaluation Latency (`context.view_layer.update()`)**: Assigning `obj.location`, `rotation_euler`, or `scale` mutates local RNA attributes immediately, but `obj.matrix_world` does NOT update synchronously for relative transformations (`parent.matrix_world.inverted() @ child.matrix_world`) until `context.view_layer.update()` is called prior to `context.evaluated_depsgraph_get()`.
* **`bpy.context` Volatility in Headless & Batch Environments**: In headless Blender (`blender -b`) or background workers, `bpy.context` attributes (`view_layer`, `scene`) are frequently `None` when no active viewport exists. Always pass explicit `context`/`scene` and `blend_data` references rather than reading global `bpy.context` or `bpy.data`.
* **Copy-on-Write (CoW) Mesh Datablock Safety**: Applying modifiers or `transform_apply` on objects whose mesh datablock has multiple users (`obj.data.users > 1`, e.g. `Alt+D` duplicates) mutates shared geometry across all instances. Always isolate first: `if obj.data.users > 1: obj.data = obj.data.copy()`.
* **Blender RNA `ReferenceError` on Removed Objects**: Accessing attributes on an unlinked/removed RNA struct raises `ReferenceError: StructRNA of type Object has been removed`. Viewport draw handlers and event listeners must guard with `(ReferenceError, AttributeError)`.

---

## 3. Blender RNA, UI & Extension Traps

* **Extension Directory & Packaging Invariants**:
  * User extensions reside in `%APPDATA%\Blender Foundation\Blender\<ver>\extensions\user_default\<addon_id>` (`bl_ext.user_default.<addon_id>`), configured exclusively via `blender_manifest.toml` (legacy `bl_info` in `__init__.py` and `scripts/addons/` are ignored).
  * Extensions do not bundle third-party PyPI wheels (e.g. Pillow/PIL) unless explicitly packed as wheels; provide pure-NumPy vectorized fallbacks where `PIL.Image` may be absent.
* **Blend-Relative Paths (`//`)**: `bpy.props.StringProperty(subtype="FILE_PATH")` requires `options={"PATH_SUPPORTS_BLEND_RELATIVE"}` so Blender 5.x accepts `//` project-relative paths without emitting a `RuntimeWarning`.
* **Dynamic Class Reloading & `bpy.ops` Dispatch Cache**:
  * Hot-reloading via `importlib.reload(module)` updates Python bytecode, but Blender's C++ RNA registry and `bpy.ops.<ns>.<op>` dispatch cache retain pointers to old classes (and duplicate `UIList` subclasses cause zero-height rendering).
  * Always inspect `existing = getattr(bpy.types, cls.__name__, None)` and call `bpy.utils.unregister_class(existing)` before re-registering reloaded classes.
* **Ghost "Misc" Sidebar Tab Trap**: Any `Panel` with `bl_region_type = 'UI'` without an explicit `bl_category` defaults to `"Misc"`. Popovers must use `bl_region_type = 'HEADER'`, and collapsible subpanels (`bl_parent_id`) must repeat their parent's `bl_category`.
* **Read-Only `Panel.draw()` & `draw_handler_add` Callbacks**: Writing to RNA/DNA properties inside `Panel.draw()` triggers layout invalidation and an infinite 60fps+ redraw loop; writing inside `draw_handler_add` raises `RuntimeError: Operator or data manipulation during draw callback is forbidden`. Keep all draw routines strictly read-only.
* **RNA Property Registration Traps**:
  * **`from __future__ import annotations`**: Writing `prop: Any = bpy.props.StringProperty(...)` stores `'Any'`, causing Blender to skip registration (`TypeError: keyword unrecognized`). Declare `prop: bpy.props.StringProperty(...)` directly.
  * **Headless Dummy `bpy.props` Helpers**: When importing operator modules outside Blender where `typing.get_type_hints()` runs, dummy property factories inside `except ImportError:` must return `typing.Any` (returning `""` or `None` crashes `get_type_hints()`).
  * **Leading Underscore Ban**: `PropertyGroup` property names must never start with `_`, or registration of all subsequent properties in the class halts silently.
  * **Operator Subclassing Ban**: Never subclass a registered `bpy.types.Operator` class (corrupts C++ RNA class tables). Inherit directly from `bpy.types.Operator` and share logic via helper functions.
* **Dynamic `EnumProperty` Lifecycle**:
  * Before deleting a backing preset/item on disk, reassign the active enum property to a valid fallback ID to avoid `bpy.rna WARNING current value matches no enum`.
  * Assigning a newly added dynamic enum item inside `Operator.execute()` can fail if items were cached at invocation; defer assignment via `bpy.app.timers.register(..., first_interval=0.005)`.
* **Operator Error Reporting in Python Calls**: Invoking a `bpy.ops.*` operator from Python that calls `self.report({"ERROR"}, ...)` and returns `{"CANCELLED"}` raises a `RuntimeError` in the Python caller rather than returning `{"CANCELLED"}`.
* **`fake-bpy-module` Stub Defects & Strict Pyright Patterns**:
  * **Read-Only / Incomplete Setters**: `Panel.layout`, `Modifier.object`, `Material.msfs_material_type`, and `RenderSettings.engine` (typed solely as `Literal['BLENDER_EEVEE']`, omitting `'CYCLES'`) trigger Pyright errors on direct assignment, while `setattr(...)` triggers Ruff `B010`. Use `cast(Any, target).attr = value` (paired with `getattr(scene, "cycles", None)` for optional add-on properties).
  * **Optional Return Types**: `.copy()` on Objects/Meshes, `eval_obj.to_mesh()`, `armature.animation_data_create()`, `UILayout.operator()`, `mesh_data.uv_layers.new()`, and `NodeSocket.get()` return `T | None` in recent stubs; always guard with `if res is not None:` before chaining attributes.
  * **Dynamic `bpy.ops` Submodules**: Custom add-on namespaces (`bpy.ops.<custom>`) are absent from static stubs; use `cast(Any, bpy.ops).<custom>` in tests or encapsulate dispatch in a compatibility helper.

---

## 4. Skeletal Rigging, Transforms & BMesh Invariants

* **Rest-Pose Coordinate Inversion & Armature Lock**: Transform bone-parented props into rest-pose local space before joining into a skinned character. During decimation and normal transfer, lock `armature.data.pose_position = 'REST'` and restore afterward.
* **Quaternion Sign Continuity ($\mathbf{q}_t \cdot \mathbf{q}_{t-1} < 0$)**: Since $\mathbf{q}$ and $-\mathbf{q}$ represent the same 3D orientation, opposite signs between consecutive keyframes cause SLERP/LERP to take the long $360^\circ$ path. Negate $\mathbf{q}_t$ when $\mathbf{q}_t \cdot \mathbf{q}_{t-1} < 0$ prior to baking deform animations.
* **Vertex Group Quirks**:
  * **Index Shifting**: `obj.vertex_groups.remove(vg)` shifts subsequent group indices; collect group names first and remove by reference/name.
  * **GPU Weight Singularity Guard**: Stripping micro-weights ($< 0.01$) must never leave $\sum w = 0.0$ (causes NaN shader crashes); fall back to the anchor bone (`1.0`).
  * **`VertexGroup.add()` Signature**: `vg.add(indices, weight, type)` accepts an index list, but `weight` MUST be a single `float`.
* **Shape Keys & Modifier Application**: In Blender C-API (`modifier.cc`), `bpy.ops.object.modifier_apply` raises `RuntimeError` if the mesh has shape keys. Purge shape keys on derivative LOD meshes before applying modifiers while preserving them on LOD0.
* **BMesh Topological & Indexing Invariants**:
  * **`bm.verts.index_update()`**: Newly created or bisected vertices have `v.index == -1` until `bm.verts.index_update()` is called; omitting it causes `vg.add([v.index ...])` to silently add 0 vertices.
  * **Dissolve Ordering**: `bmesh.ops.dissolve_limit` mutates indices; run planar limited dissolve *before* boundary and UV seam tagging.
  * **Bisect Seam Pinning**: `edge.is_boundary` also matches natural mesh openings (eyes, sleeves). Test vertex coordinates against the mathematical bisect plane ($|wco \cdot \vec{n} - d| < \epsilon$) instead.
  * **Mid-Operation Recovery**: If `bmesh.ops` split/creation fails midway, attempt to restore original vertices; if restoration fails, raise a typed exception immediately rather than leaving corrupted holes.
* **AABB Extent Bounding Sphere vs Centroid Bias**: Vertex mean $\frac{1}{N}\sum \mathbf{p}$ biases sphere centers toward dense clusters (cockpits, bevels), inflating radius $r$. Compute centers from symmetric AABB extents $\frac{\min + \max}{2}$.
* **Fast C-Buffer Mesh Population & $O(1)$ Triangle Count**:
  * Populate dense `bpy.types.Mesh` geometry via `mesh.vertices.add(n)` + `mesh.vertices.foreach_set("co", flat_float32_array)` rather than `from_pydata(points.tolist(), ...)`.
  * Compute polygon mesh triangle counts in $O(1)$ via the Euler loop-polygon relation $n_{\text{tris}} = n_{\text{loops}} - 2 \cdot n_{\text{polys}}$ rather than iterating `mesh.polygons` (which is $O(N)$ and lacks `__len__` on `bpy_prop_array` in stubs).

---

## 5. Headless CLI, Subprocess & Memory Management

* **Headless Exit Codes & `--` Argument Slicing**:
  * `blender -b` exits with code `0` even on unhandled Python exceptions unless `--python-exit-code 1` is passed.
  * Under `blender -b --python script.py -- [args]`, `argparse` stops at `--`. Slice `argv = sys.argv[sys.argv.index("--") + 1:]` before parsing arguments to prevent missed flags and recursive fork loops.
  * `--factory-startup` does not add the working directory to `sys.path`; scripts run via `--python` must inject the repo root into `sys.path` explicitly and guard `import pytest` with a `unittest` fallback (embedded Blender Python does not bundle `pytest`).
* **Headless Unit Test Mock Traps**:
  * **Container Truthiness (`if container is None:`)**: Dict-backed mock datablock containers (`BlendData.objects`, etc.) evaluate `len(container) == 0` as `False` under `if not container:`. Always test availability with `if container is None:`.
  * **`bpy_prop_collection` Lookup**: Unconfigured `MagicMock` collections return `False` for `"name" in obj.vertex_groups`; prefer `vg = obj.vertex_groups.get("name"); if vg is not None:`.
  * **BMesh & Matrix Mocks**: `bmesh.from_mesh()` mocks must provide `.ensure_lookup_table()`, `.index_update()`, and `.layers.deform` on vertex/edge/face sequences; matrix mocks chained with `@` must return a mock whose `.decompose()` returns a 3-tuple `(loc, rot, scale)`.
* **Viewport Performance & Batch Memory Hygiene**:
  * Omit `{'UNDO'}` from modal simulation operators (`bl_options`) and guard `obj.hide_set()` with `if obj.hide_get() != target:` to avoid per-frame depsgraph rebuilds.
  * Free cached C++ image float buffers after `img.pixels.foreach_get(buf)` via `if hasattr(img, "buffers_free"): img.buffers_free()` in `finally:`.
  * Wrap multi-asset batch runs in `use_global_undo = False` followed by `bpy.data.orphans_purge(...)`, `gc.collect()`, and OS heap compaction (`_heapmin()` on Win32 / `malloc_trim(0)` on Linux).
  * **Thread Safety**: `bpy` is not thread-safe. Background `ThreadPoolExecutor` workers must operate strictly on NumPy arrays / file paths and join (`wait_all()`) before `bpy` export steps.
* **Blender MCP Socket Server (Port 9876)**: The `blender-mcp` toolserver requires Siddharth Ahuja's TCP JSON socket server on `127.0.0.1:9876` (`blender_mcp.py`), not Campbell Barton's stdio extension (`bl_ext.blender_org.mcp`).

---

## 6. Texture Baking & Impostor Invariants

* **Octahedral Normal & Camera-Space Z-Sign Invariants**:
  * Octahedral atlas normals render via camera-orbit animation frames in an unlit scene (`neutral = (0.5, 0.5, 1.0)`).
  * At zenith $(0, 0, 1)$, switch the camera tracking up-vector from $(0, 0, 1)$ to $(0, 1, 0)$ when $|\text{Forward}_z| \ge 0.999$ to avoid pole flip singularities.
  * Blender camera forward is $-Z$ in camera space ($Z_{\text{cam}} = -1.0$ for camera-facing surfaces). The Z scale factor in unlit emission normal overrides must be $-0.5$ (`(0.5, -0.5, -0.5)` for DirectX, `(0.5, 0.5, -0.5)` for OpenGL); $+0.5$ yields black normals ($Z \le 0$).
* **Impostor UV & Billboard Shader Traps**:
  * Exclude single-card and octahedral proxy meshes from `bpy.ops.uv.pack_islands()` so normalized $[0, 1]^2$ UVs are not displaced.
  * Per-fragment `Geometry.Incoming` on billboard quads causes perspective fanning across octahedral tile boundaries at close range; compute a uniform view vector `normalize(CamWorldPos - ObjWorldPos)` via `ShaderNodeVectorTransform`.
  * Billboard `TRACK_TO` constraints targeting an animated turntable camera get overwritten by depsgraph F-curve evaluation during viewport navigation; target a dedicated Empty (`Preview_Tracker_Target`) updated by an epsilon-gated `bpy.app.timers` callback.
* **Windows UNC `//` Freeze on Unsaved Scenes**: In unsaved scenes (`filepath == ""`), relative paths starting with `"//"` resolve as Windows UNC network paths (`\\Textures`), causing a 30s NetBIOS timeout (`[WinError 53]`). Fall back to `tempfile.gettempdir()`.
* **Blender 5.x `colorspace_settings` ImBuf Reset & Scanline Orientation**:
  * Setting `image.colorspace_settings.name = "Non-Color"` in Blender 5.x zeroes any unsaved in-memory float buffer (`ImBuf`). Always set `colorspace_settings.name` *before* calling `image.pixels.foreach_set(...)`.
  * `Image.pixels` is ordered bottom-to-top (`row 0` = $V=0.0$). Flip vertically (`arr.reshape((h, w, 4))[::-1]`) when passing to top-down PNG encoders.
