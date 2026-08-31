# OmniMesh Domain & Runtime Knowledge Base

> **Rule**: This repository knowledge base serves strictly as persistent memory for **non-obvious runtime quirks, hardware/model constraints, and hidden system behaviors** that cannot be inferred from reading source code, function signatures, or docstrings alone. Do NOT document standard component mappings, obvious file listings, or generic code patterns here.


## 1. Verification Commands & Quality Gates

* **Iterative Development (Code changes only)**:
  ```bash
  python -m pytest -q
  ```
  *(Run ONLY when `.py` code changed. Never run Ruff or Pyright during iterative steps).*

* **Pre-Commit Quality Gate (Triggered strictly on explicit user commit request)**:
  ```bash
  python scripts/verify_ci.py
  ```
  *(Runs dependency parity check, full pytest test suite, Ruff linter, Ruff formatter check, and Pyright static type checker).*

---

## 2. Specialized Multi-Agent Quality Subagents

* **`plan_critic` ("Grill Me" Sparring Panel)**: Multi-perspective architectural reviewer before writing implementation plans. Actively attacks assumptions, validates against real codebase APIs, and enforces KISS/YAGNI.
* **`pre_commit_auditor` ("Grill Me" Code & Goal Auditor)**: Adversarial auditor before commit approval. Scrutinizes `git diff` against Plan Fidelity (no cut corners) and `AGENTS.md` standards (zero placeholders, cross-platform guards, SRP limits).

---

## 3. Blender 5.2+ API Quirks & Engine Runtime Invariants

### 3.1 Normal Projection & glTF Enums
* **`DATA_TRANSFER` Loop Mapping**: `dt_mod.loop_mapping = 'POLYINTERP_LNORPROJ'` is the only valid enum in Blender 5.2 LTS (`POLYINTERP_NEAREST_CORNER` was deprecated/removed).
* **glTF 2.0 Export Format**: Use `export_format='GLTF_SEPARATE'` for `.gltf` + `.bin` export in Blender 5.2 LTS (`GLTF_EMBEDDED` was deprecated).

### 3.2 Skeletal Mesh Rigging & Transform Invariants
* **Rest-Pose Coordinate Inversion**:
  $$\mathbf{M}_{S \to M\_rest} = \mathbf{M}_{M\_rest\_world}^{-1} \cdot \mathbf{M}_{Arm\_world} \cdot \mathbf{M}_{B\_bone\_local} \cdot \mathbf{M}_{S\_parent\_inv} \cdot \mathbf{M}_{S\_basis}$$
  Transforming bone-parented static props into rest-pose local space before joining into a skinned character prevents the "pose explosion" where animated rotations get permanently baked into the rest mesh.
* **Armature Rest-Pose Lock**: During decimation and normal data transfers, `armature.data.pose_position` MUST be set to `'REST'`, and restored afterwards.
* **Vertex Group Index Shifting Trap**: In Blender, removing a vertex group via `obj.vertex_groups.remove(vg)` shifts the indices of all subsequent groups. Always collect used group *names* first and purge by name to avoid data corruption.
* **GPU Weight Singularity Guard**: Stripping micro-weights ($< 0.01$) must never leave a vertex with $\sum w = 0.0$. `normalize_weights_pure` falls back to the anchor bone (`1.0`) if all weights drop below epsilon, preventing GPU division-by-zero NaN shader crashes.

### 3.3 Real-Time Viewport Simulator Performance & Undo Hygiene
* **Draw Callback Restriction**: Writing to Blender RNA/DNA properties inside `draw_handler_add` raises `RuntimeError: Operator or data manipulation during draw callback is forbidden`.
* **Zero Undo Pollution**: The modal simulation loop must omit `{'UNDO'}` from `bl_options` to keep the user's `Ctrl+Z` history clean.
* **Differential Visibility Sets**: Only call `obj.hide_set()` if `obj.hide_get()` differs from the target state. This prevents rebuilding the dependency graph on frames where the camera moves within the same LOD zone.

### 3.4 Clean CI Matrix & Dependency Declaration Invariant
* **Dependency Parity Invariant**: Blender bundles `numpy` and `Pillow` internally, but standalone test suites in clean CI environments (Ubuntu/Windows runners) require them declared in `pyproject.toml` and installed via `pip install -e .[dev]`. `scripts/verify_ci.py` automatically checks declared dependencies against requirements before any commit.
* **Linux `sys.path` Quirk**: Unlike Windows, `pytest` on Ubuntu runners does NOT include the root working directory in `sys.path`. Always configure `pythonpath = .` in `pytest.ini` and declare `PYTHONPATH: .` in GitHub Actions workflows.
