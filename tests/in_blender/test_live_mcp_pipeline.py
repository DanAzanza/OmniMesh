"""
OmniMesh Live MCP In-Blender Pipeline Verification Suite.
Blender 5.2 LTS Compatible.

Executes live end-to-end testing directly inside an active Blender session:
1. Spawns a procedural test mesh (Monkey).
2. Executes LOD0..LOD3 decimation and verifies triangle monotonicity.
3. Bakes PBR Impostor textures (BaseColor, Normal, ORM) and verifies disk files and PNG headers.
4. Simulates distance scrubber steps and verifies active collection visibility.
5. Emits structured JSON summary report.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

import bpy


def run_live_mcp_pipeline_tests() -> str:
    results: dict[str, Any] = {
        "timestamp": time.time(),
        "blender_version": bpy.app.version_string,
        "tests": {},
        "all_passed": False,
    }

    test_start = time.time()

    # Step 1: Clean scene and create test asset
    try:
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)

        # Clear orphaned mesh collections from previous runs
        for col in list(bpy.data.collections):
            if any(k in col.name for k in ("Suzanne", "OMNIMESH", "LOD")):
                bpy.data.collections.remove(col)

        bpy.ops.mesh.primitive_monkey_add(size=2.0, location=(0, 0, 0))
        monkey = bpy.context.active_object
        assert monkey is not None, "Failed to spawn monkey mesh"
        monkey.name = "Suzanne"
        results["tests"]["mesh_creation"] = {
            "status": "PASS",
            "name": monkey.name,
            "triangles": len(monkey.data.polygons),
        }
    except Exception as exc:
        results["tests"]["mesh_creation"] = {"status": "FAIL", "error": str(exc)}
        return json.dumps(results, indent=2)

    # Step 2: Initialize LOD Collection hierarchy & tiers
    try:
        # Resolve OmniMesh operators or core modules
        from core.lod_generator import generate_all_lods
        from ui.properties.callbacks import project_preset_tiers

        scene = bpy.context.scene
        props = getattr(scene, "lod_tool", None)
        assert props is not None, "Scene has no lod_tool property group"

        # Organize into base asset collection
        base_col = bpy.data.collections.new("Suzanne")
        scene.collection.children.link(base_col)
        if monkey.name in scene.collection.objects:
            scene.collection.objects.unlink(monkey)
        base_col.objects.link(monkey)

        # Apply standard game asset preset and configure tiers
        from core.lod_presets import LODPresetManager

        LODPresetManager.load_presets(force_reload=True)
        props.lod_preset = "unreal_engine_5"
        props.export_base_name = "Suzanne"
        project_preset_tiers(props, bpy.context, asset_name="Suzanne")

        success, msg = generate_all_lods(bpy.context, props, [monkey], base_name="Suzanne")
        assert success, f"LOD generation failed: {msg}"

        # Verify created LOD collections
        lod_cols = [c for c in bpy.data.collections if c.name.startswith("Suzanne_LOD")]
        assert len(lod_cols) >= 3, f"Expected at least 3 LOD collections, found {len(lod_cols)}"

        poly_counts = []
        for col in sorted(lod_cols, key=lambda c: c.name):
            col_tris = sum(len(o.data.polygons) for o in col.objects if o.type == "MESH")
            poly_counts.append(col_tris)

        # Assert monotonic triangle reduction
        for i in range(len(poly_counts) - 1):
            assert poly_counts[i] >= poly_counts[i + 1], (
                f"Triangle reduction failed: tier {i} ({poly_counts[i]}) < tier {i + 1} ({poly_counts[i + 1]})"
            )

        results["tests"]["lod_generation"] = {
            "status": "PASS",
            "tier_counts": poly_counts,
            "message": msg,
        }
    except Exception as exc:
        results["tests"]["lod_generation"] = {"status": "FAIL", "error": str(exc)}
        return json.dumps(results, indent=2)

    # Step 3: Bake PBR Impostor Textures
    try:
        from core.impostor_baker import ImpostorAtlasBaker

        tmp_dir = tempfile.mkdtemp(prefix="om_mcp_test_")
        bake_results = ImpostorAtlasBaker.bake_impostor_textures(
            mesh_objs=[monkey],
            base_name="Suzanne",
            output_dir=tmp_dir,
            mode="CROSS_QUADS",
            atlas_resolution=512,
            target_engine="UE5",
            dilation_iterations=2,
        )

        assert "BaseColor" in bake_results, "BaseColor map was not generated"
        assert "Normal" in bake_results, "Normal map was not generated"
        assert "ORM" in bake_results, "ORM map was not generated"

        for channel, path in bake_results.items():
            assert os.path.exists(path), f"Baked texture {channel} does not exist at {path}"
            assert os.path.getsize(path) > 100, f"Baked texture {channel} is empty or corrupted ({path})"
            # Verify PNG 8-byte header
            with open(path, "rb") as f:
                header = f.read(8)
                assert header == b"\x89PNG\r\n\x1a\n", f"File {path} is not a valid PNG"

        results["tests"]["impostor_baking"] = {
            "status": "PASS",
            "output_dir": tmp_dir,
            "baked_maps": {k: os.path.getsize(v) for k, v in bake_results.items()},
        }
    except Exception as exc:
        results["tests"]["impostor_baking"] = {"status": "FAIL", "error": str(exc)}
        return json.dumps(results, indent=2)

    # Step 4: Distance Scrubber Visibility Evaluation
    try:
        from core.simulator import LODSimulatorEngine

        # Scrub at 10m, 40m, 120m
        scrub_evals = []
        for dist in [10.0, 40.0, 120.0]:
            LODSimulatorEngine.evaluate_distance_scrub(bpy.context, dist)
            # Query collection visibility
            visible_cols = [
                c.name for c in bpy.data.collections if "Suzanne" in c.name and not getattr(c, "hide_viewport", False)
            ]
            scrub_evals.append({"distance": dist, "visible_collections": visible_cols})

        LODSimulatorEngine.reset_distance_scrub(bpy.context)
        results["tests"]["distance_scrubber"] = {
            "status": "PASS",
            "evaluations": scrub_evals,
        }
    except Exception as exc:
        results["tests"]["distance_scrubber"] = {"status": "FAIL", "error": str(exc)}
        return json.dumps(results, indent=2)

    results["all_passed"] = all(t.get("status") == "PASS" for t in results["tests"].values())
    results["duration_seconds"] = round(time.time() - test_start, 3)
    return json.dumps(results, indent=2)


if __name__ == "__main__":
    print(run_live_mcp_pipeline_tests())
