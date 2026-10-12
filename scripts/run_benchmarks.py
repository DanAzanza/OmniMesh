"""
OmniMesh Empirical Performance & Decimation Benchmark Suite.
Blender 4.2+ and 5.2 LTS Compatible.

Executes reproducible, headless performance profiling on procedural multi-feature test meshes
(10k, 100k, and 500k polygons). Measures:
1. Planar Limited Dissolve (coplanar surface decimation)
2. Vertex Weight Clamping & Normalization (CPU hardening for 4-influence GPU limits)
3. Curvature-Weighted QEM Edge-Collapse (LOD1 50% and LOD3 10% reduction)
4. Split Normal Reprojection & Spatial KDTree Transfer

Outputs structured metrics to benchmark_results.json and prints markdown summary.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any, Dict


def find_blender_binary() -> str | None:
    """Locate Blender executable across Windows, macOS, and Linux platforms."""
    custom_bin = os.environ.get("BLENDER_PATH") or os.environ.get("BLENDER_BIN")
    if custom_bin and os.path.isfile(custom_bin):
        return custom_bin

    path_bin = shutil.which("blender")
    if path_bin:
        return path_bin

    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            for alias in ("blender.exe", "blender-launcher.exe"):
                windows_app_alias = os.path.join(local_app_data, "Microsoft", "WindowsApps", alias)
                if os.path.isfile(windows_app_alias):
                    return windows_app_alias

        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        import glob

        candidates = sorted(
            glob.glob(os.path.join(program_files, "Blender Foundation", "Blender *", "blender.exe")),
            reverse=True,
        )
        if candidates:
            return candidates[0]

    return None


def generate_benchmark_cylinder_bmesh(
    bm: Any,
    radial_segments: int,
    height_cuts: int,
    radius: float = 1.0,
    height: float = 3.0,
    ripple_amplitude: float = 0.15,
) -> tuple[int, int]:
    """
    Constructs a multi-feature procedural mesh with:
    1. Planar top and bottom end caps (normal (0,0,1) and (0,0,-1))
    2. Curvature-rich sinusoidal radial ripple on the cylindrical body
    Returns (v_bot_index, v_top_index).
    """
    import bmesh

    n = radial_segments
    m = height_cuts

    # Generate rings of vertices
    rings: list[list[Any]] = []
    for i in range(m + 1):
        z = -height * 0.5 + height * (i / float(m))
        ring: list[Any] = []
        is_cap_ring = i == 0 or i == m
        for j in range(n):
            theta = 2.0 * math.pi * (j / float(n))
            if is_cap_ring:
                r = radius
            else:
                # High-frequency radial ripple creates variable dihedral curvature
                r = radius + ripple_amplitude * math.sin(6.0 * z + 8.0 * theta)
            x = r * math.cos(theta)
            y = r * math.sin(theta)
            v = bm.verts.new((x, y, z))
            ring.append(v)
        rings.append(ring)

    # Center vertices for planar end caps
    v_bot = bm.verts.new((0.0, 0.0, -height * 0.5))
    v_top = bm.verts.new((0.0, 0.0, height * 0.5))

    # Cap faces (planar fan)
    for j in range(n):
        j_next = (j + 1) % n
        bm.faces.new((v_bot, rings[0][j_next], rings[0][j]))
        bm.faces.new((v_top, rings[m][j], rings[m][j_next]))

    # Body quad faces
    for i in range(m):
        for j in range(n):
            j_next = (j + 1) % n
            bm.faces.new((rings[i][j], rings[i][j_next], rings[i + 1][j_next], rings[i + 1][j]))

    # Triangulate all faces
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    return v_bot.index, v_top.index


def run_single_tier_benchmark(
    target_name: str,
    radial_segments: int,
    height_cuts: int,
) -> Dict[str, Any]:
    """Profiles all core LOD operations for a specific polygon tier."""
    import bmesh
    import bpy
    from core.decimator import MeshDecimator
    from core.normals import NormalManager
    from core.rigging import WeightSanitizer

    scene = bpy.context.scene

    # 1. Procedural mesh generation
    t0_gen = time.perf_counter()
    bm = bmesh.new()
    v_bot_idx, v_top_idx = generate_benchmark_cylinder_bmesh(
        bm, radial_segments=radial_segments, height_cuts=height_cuts
    )
    raw_tri_count = len(bm.faces)
    raw_vert_count = len(bm.verts)

    mesh_lod0 = bpy.data.meshes.new(f"BenchMesh_{target_name}_LOD0")
    bm.to_mesh(mesh_lod0)
    mesh_lod0.update()
    obj_lod0 = bpy.data.objects.new(f"BenchObj_{target_name}_LOD0", mesh_lod0)
    scene.collection.objects.link(obj_lod0)
    bpy.context.view_layer.objects.active = obj_lod0
    obj_lod0.select_set(True)
    dt_gen_ms = (time.perf_counter() - t0_gen) * 1000.0

    tier_results: Dict[str, Any] = {
        "tier": target_name,
        "input_triangles": raw_tri_count,
        "input_vertices": raw_vert_count,
        "mesh_generation_ms": round(dt_gen_ms, 2),
    }

    # 2. Planar Limited Dissolve Benchmark (pure planar caps and low-slope zones)
    bm_planar = bmesh.new()
    bm_planar.from_mesh(mesh_lod0)
    t0_planar = time.perf_counter()
    MeshDecimator.apply_planar_limited_dissolve(bm_planar, angle_limit_rad=math.radians(5.0))
    dt_planar_ms = (time.perf_counter() - t0_planar) * 1000.0
    planar_post_faces = len(bm_planar.faces)
    bm_planar.free()

    tier_results["planar_dissolve"] = {
        "before_faces": raw_tri_count,
        "after_faces": planar_post_faces,
        "faces_collapsed": raw_tri_count - planar_post_faces,
        "elapsed_ms": round(dt_planar_ms, 2),
        "throughput_faces_per_sec": int(raw_tri_count / max(1e-6, dt_planar_ms / 1000.0)),
    }

    # 3. Bone Weight Clamping Benchmark (CPU hardening for 4-influence GPU limits)
    # Assign 6 overlapping deform groups with falloffs
    vg_names = ["Root", "Spine", "Arm_L", "Arm_R", "Leg_L", "Leg_R"]
    vgs = [obj_lod0.vertex_groups.new(name=n) for n in vg_names]
    for v in mesh_lod0.vertices:
        z = v.co.z
        # Assign 5-6 weights per vertex
        for idx, vg in enumerate(vgs):
            dist = abs(z - (-1.5 + 0.6 * idx))
            weight = max(0.02, 1.0 - 0.5 * dist)
            vg.add([v.index], weight, "REPLACE")

    t0_weights = time.perf_counter()
    weight_res = WeightSanitizer.normalize_and_clamp_weights(obj_lod0, max_influences=4, micro_weight_epsilon=0.01)
    dt_weights_ms = (time.perf_counter() - t0_weights) * 1000.0

    tier_results["bone_weight_clamping"] = {
        "vertices_processed": raw_vert_count,
        "max_influences_enforced": 4,
        "singularities_fixed": weight_res.get("singularities_fixed", 0),
        "purged_groups": weight_res.get("purged_vgs", 0),
        "elapsed_ms": round(dt_weights_ms, 2),
        "throughput_verts_per_sec": int(raw_vert_count / max(1e-6, dt_weights_ms / 1000.0)),
    }

    # 4. Curvature Weighting & QEM Decimation 50% (LOD1)
    mesh_lod1 = mesh_lod0.copy()
    obj_lod1 = bpy.data.objects.new(f"BenchObj_{target_name}_LOD1", mesh_lod1)
    scene.collection.objects.link(obj_lod1)
    bpy.context.view_layer.objects.active = obj_lod1
    obj_lod1.select_set(True)

    bm_qem50 = bmesh.new()
    bm_qem50.from_mesh(mesh_lod1)
    t0_qem50 = time.perf_counter()
    MeshDecimator.inject_curvature_weights(
        obj_lod1,
        bm_qem50,
        pinned_vert_indices={v_bot_idx, v_top_idx},
        group_name="OmniMesh_Protection",
    )
    bm_qem50.free()

    MeshDecimator.execute_decimate_qem(
        obj_lod1,
        target_ratio=0.5,
        use_curvature_weight=True,
        group_name="OmniMesh_Protection",
        cleanup_group=True,
    )
    dt_qem50_ms = (time.perf_counter() - t0_qem50) * 1000.0
    post_tri_qem50 = len(mesh_lod1.polygons)

    tier_results["qem_decimate_50"] = {
        "before_triangles": raw_tri_count,
        "after_triangles": post_tri_qem50,
        "ratio_achieved": round(post_tri_qem50 / float(raw_tri_count), 4),
        "elapsed_ms": round(dt_qem50_ms, 2),
        "throughput_tris_per_sec": int(raw_tri_count / max(1e-6, dt_qem50_ms / 1000.0)),
    }

    # 5. Normal Reprojection Benchmark (LOD0 -> LOD1)
    t0_norm = time.perf_counter()
    norm_success = NormalManager.reproject_custom_split_normals(obj_lod1, source_lod0=obj_lod0)
    dt_norm_ms = (time.perf_counter() - t0_norm) * 1000.0

    tier_results["normal_reprojection"] = {
        "source_triangles": raw_tri_count,
        "target_triangles": post_tri_qem50,
        "success": norm_success,
        "elapsed_ms": round(dt_norm_ms, 2),
        "throughput_tris_per_sec": int(post_tri_qem50 / max(1e-6, dt_norm_ms / 1000.0)),
    }

    # 6. Aggressive QEM Decimation 10% (LOD3)
    mesh_lod3 = mesh_lod0.copy()
    obj_lod3 = bpy.data.objects.new(f"BenchObj_{target_name}_LOD3", mesh_lod3)
    scene.collection.objects.link(obj_lod3)
    bpy.context.view_layer.objects.active = obj_lod3
    obj_lod3.select_set(True)

    bm_qem10 = bmesh.new()
    bm_qem10.from_mesh(mesh_lod3)
    t0_qem10 = time.perf_counter()
    MeshDecimator.inject_curvature_weights(
        obj_lod3,
        bm_qem10,
        pinned_vert_indices={v_bot_idx, v_top_idx},
        group_name="OmniMesh_Protection",
    )
    bm_qem10.free()

    MeshDecimator.execute_decimate_qem(
        obj_lod3,
        target_ratio=0.1,
        use_curvature_weight=True,
        group_name="OmniMesh_Protection",
        cleanup_group=True,
    )
    dt_qem10_ms = (time.perf_counter() - t0_qem10) * 1000.0
    post_tri_qem10 = len(mesh_lod3.polygons)

    tier_results["qem_decimate_10"] = {
        "before_triangles": raw_tri_count,
        "after_triangles": post_tri_qem10,
        "ratio_achieved": round(post_tri_qem10 / float(raw_tri_count), 4),
        "elapsed_ms": round(dt_qem10_ms, 2),
        "throughput_tris_per_sec": int(raw_tri_count / max(1e-6, dt_qem10_ms / 1000.0)),
    }

    # Clean up datablocks
    for o in (obj_lod0, obj_lod1, obj_lod3):
        bpy.data.objects.remove(o, do_unlink=True)
    for m in (mesh_lod0, mesh_lod1, mesh_lod3):
        bpy.data.meshes.remove(m, do_unlink=True)
    bm.free()

    return tier_results


def run_worker_in_blender(tier_mode: str, output_path: str) -> None:
    """Entry point when executed inside Blender subprocess."""
    import bpy

    # Define tier resolutions: (radial_segments, height_cuts) -> ~triangles = 2 * n * m + 2 * n
    configs: list[tuple[str, int, int]] = []
    if tier_mode == "QUICK":
        # 10k (10,200 tris) and 100k (100,500 tris)
        configs = [
            ("10k", 100, 50),
            ("100k", 314, 160),
        ]
    else:  # FULL
        # 10k, 100k, and 500k (501,416 tris)
        configs = [
            ("10k", 100, 50),
            ("100k", 314, 160),
            ("500k", 708, 354),
        ]

    blender_version = ".".join(str(x) for x in bpy.app.version)

    results: Dict[str, Any] = {
        "metadata": {
            "blender_version": blender_version,
            "python_version": platform.python_version(),
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "tier_mode": tier_mode,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "tiers": {},
    }

    print(f"\n[BENCHMARK] Executing OmniMesh Benchmarks ({tier_mode} mode)...")
    for name, n, m in configs:
        print(f"[BENCHMARK] Running tier '{name}' (segments={n}, cuts={m})...")
        tier_data = run_single_tier_benchmark(name, radial_segments=n, height_cuts=m)
        results["tiers"][name] = tier_data
        print(f"[BENCHMARK] Tier '{name}' completed successfully ({tier_data['input_triangles']} triangles).")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n[BENCHMARK] Results saved to: {output_path}")


def print_markdown_summary(json_path: str) -> None:
    """Parses benchmark JSON and renders a clean, empirical markdown summary table."""
    if not os.path.isfile(json_path):
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    meta = data.get("metadata", {})
    tiers = data.get("tiers", {})

    print("\n" + "=" * 70)
    print("OmniMesh Empirical Performance Benchmark Results")
    print("=" * 70)
    print(f"Platform: {meta.get('os')} ({meta.get('architecture')}) | Blender: {meta.get('blender_version')}")
    print(f"Date: {meta.get('timestamp')}")
    print("\n### Empirical Benchmark Table\n")
    print(
        "| Poly Tier | Triangles | Planar Dissolve | Bone Clamping | QEM LOD1 (50%) | QEM LOD3 (10%) | Split Normal Xfer |"
    )
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for tier_name, t in tiers.items():
        tris = f"{t.get('input_triangles', 0):,}"
        planar = f"{t.get('planar_dissolve', {}).get('elapsed_ms', 0):.1f} ms"
        weight = f"{t.get('bone_weight_clamping', {}).get('elapsed_ms', 0):.1f} ms"
        qem50 = f"{t.get('qem_decimate_50', {}).get('elapsed_ms', 0):.1f} ms"
        qem10 = f"{t.get('qem_decimate_10', {}).get('elapsed_ms', 0):.1f} ms"
        norm = f"{t.get('normal_reprojection', {}).get('elapsed_ms', 0):.1f} ms"
        print(f"| **{tier_name}** | {tris} | {planar} | {weight} | {qem50} | {qem10} | {norm} |")

    print("\n" + "=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniMesh Headless Performance Benchmark Suite")
    parser.add_argument(
        "--in-blender",
        action="store_true",
        help="Internal flag: signals execution inside headless Blender subprocess.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run full benchmark suite including 500k polygon tier (default is quick 10k/100k).",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run quick benchmark suite (10k and 100k tiers).",
    )
    parser.add_argument(
        "--output",
        default="benchmark_results.json",
        help="Target output JSON path (default: benchmark_results.json).",
    )

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    args, unknown = parser.parse_known_args(argv)

    tier_mode = "FULL" if args.full else "QUICK"
    output_path = os.path.abspath(args.output)

    if args.in_blender:
        run_worker_in_blender(tier_mode=tier_mode, output_path=output_path)
        return 0

    blender_bin = find_blender_binary()
    if not blender_bin:
        print(
            "[ERROR] Blender binary not found. Set BLENDER_PATH environment variable or install Blender.",
            file=sys.stderr,
        )
        return 1

    print(f"[INFO] Using Blender: {blender_bin}")
    this_script = os.path.abspath(__file__)
    cmd = [
        blender_bin,
        "-b",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        this_script,
        "--",
        "--in-blender",
        "--output",
        output_path,
    ]
    if args.full:
        cmd.append("--full")
    else:
        cmd.append("--quick")

    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"[ERROR] Benchmark subprocess failed with exit code {res.returncode}", file=sys.stderr)
        return res.returncode

    print_markdown_summary(output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
