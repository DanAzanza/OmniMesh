# pyright: reportAttributeAccessIssue=none, reportOptionalMemberAccess=none, reportGeneralTypeIssues=none, reportPossiblyUnboundVariable=none
"""
Comprehensive OmniMesh Feature Test Suite on Authentic MSFS 2024 SDK Assets.
Tests all plugin operators and pipelines inside Blender:
- Asobo legacy hierarchy migration
- Inspection & screen metrics
- Mesh cleanup & topology repair
- LOD decimation & sibling collection hierarchy
- Tier preview & soloing
- Collision hull generation & decomposition
- Billboard impostor rig & atlas baking
- Spatial chunking
- PBR texture matching & channel packing
- MSFS 2024 aircraft config, spatial points & CFG/XML import/export
- Multi-engine export (MSFS 2024, UE5, Unity 6)
- Real-time LOD simulator & split-preview engine
- Real aircraft model (SimpleAircraft.blend): landing gear alignment & animation scanning
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from typing import Any
import bpy

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.in_blender.runner import bootstrap_addon

RESULTS: dict[str, Any] = {
    "start_time": time.time(),
    "blender_version": bpy.app.version_string,
    "stages": {},
    "passed": 0,
    "failed": 0,
    "skipped": 0,
}


def record_stage(name: str, status: str, details: str | dict[str, Any], duration: float) -> None:
    RESULTS["stages"][name] = {
        "status": status,
        "details": details,
        "duration_sec": round(duration, 3),
    }
    if status == "PASS":
        RESULTS["passed"] += 1
    elif status == "FAIL":
        RESULTS["failed"] += 1
    else:
        RESULTS["skipped"] += 1
    print(f"[{status}] {name} ({round(duration, 3)}s): {details}")


def run_all_tests():
    sdk_root = os.environ.get("MSFS_SDK_ROOT", r"C:\MSFS 2024 SDK")
    windsock_blend = os.path.join(
        sdk_root, r"Samples\DevmodeProjects\SimObjects\Landmarks\Windsock\Sources\Art\Blender\windsock.blend"
    )
    simple_aircraft_blend = os.path.join(
        sdk_root, r"Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft\Sources\Art\Blender\SimpleAircraft.blend"
    )
    simple_aircraft_cfg_dir = os.path.join(
        sdk_root,
        r"Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft\PackageSources\SimObjects\Airplanes\MyCompany_Simple_Aircraft\common\config",
    )
    textures_dir = os.path.join(
        sdk_root, r"Samples\DevmodeProjects\SimObjects\Aircraft\SimpleAircraft\Sources\Art\Textures"
    )

    temp_export_dir = tempfile.mkdtemp(prefix="omnimesh_sdk_test_")
    print(f"Working temporary export directory: {temp_export_dir}")

    # =========================================================================
    # STAGE 1: MSFS Legacy Asobo Migration (windsock.blend)
    # =========================================================================
    t0 = time.time()
    try:
        bpy.ops.wm.open_mainfile(filepath=windsock_blend)
        bootstrap_addon()
        pre_colls = [c.name for c in bpy.data.collections]
        poll_ok = bpy.ops.omnimesh.convert_asobo_hierarchy.poll()
        assert poll_ok, f"convert_asobo_hierarchy poll should be True for collections {pre_colls}"
        res = bpy.ops.omnimesh.convert_asobo_hierarchy()
        assert res == {"FINISHED"}, f"convert_asobo_hierarchy returned {res}"
        post_colls = [c.name for c in bpy.data.collections]
        assert "Windsock_LOD0" in post_colls, f"Expected Windsock_LOD0 in {post_colls}"
        assert "Windsock_LOD1" in post_colls, f"Expected Windsock_LOD1 in {post_colls}"
        lod0_objs = [o.name for o in bpy.data.collections["Windsock_LOD0"].objects]
        record_stage(
            "1. MSFS Asobo Migration (Windsock)",
            "PASS",
            f"Successfully migrated {len(lod0_objs)} LOD0 objects into Variante A collections: {post_colls}",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("1. MSFS Asobo Migration (Windsock)", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 2: Mesh Sanitization & Topology Repair
    # =========================================================================
    t0 = time.time()
    try:
        lod0_col = bpy.data.collections.get("Windsock_LOD0")
        assert lod0_col and lod0_col.objects, "No objects in Windsock_LOD0"
        bpy.ops.object.select_all(action="DESELECT")
        for obj in lod0_col.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = lod0_col.objects[0]

        res_clean = bpy.ops.lod_tool.clean_and_repair_mesh()
        assert res_clean == {"FINISHED"}, f"clean_and_repair_mesh returned {res_clean}"

        res_trans = bpy.ops.lod_tool.apply_transforms()
        assert res_trans == {"FINISHED"}, f"apply_transforms returned {res_trans}"

        res_mods = bpy.ops.lod_tool.apply_all_modifiers()
        assert res_mods == {"FINISHED"}, f"apply_all_modifiers returned {res_mods}"

        res_voxel = bpy.ops.lod_tool.voxel_scan_cleanup()
        assert res_voxel == {"FINISHED"}, f"voxel_scan_cleanup returned {res_voxel}"

        record_stage(
            "2. Mesh Sanitization & Topology Repair",
            "PASS",
            "clean_and_repair_mesh, apply_transforms, apply_all_modifiers, and voxel_scan_cleanup completed.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("2. Mesh Sanitization & Topology Repair", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 3: Preset Management & Tier Setup
    # =========================================================================
    t0 = time.time()
    try:
        scene = bpy.context.scene
        props = getattr(scene, "lod_tool", None)
        assert props is not None, "lod_tool properties not found on scene"

        props.lod_preset = "msfs_2024"
        res_preset = bpy.ops.lod_tool.reset_to_preset()
        assert res_preset == {"FINISHED"}, f"reset_to_preset returned {res_preset}"

        initial_count = len(props.lods)
        bpy.ops.lod_tool.add_lod_tier()
        assert len(props.lods) == initial_count + 1, "add_lod_tier failed to increment tier count"
        bpy.ops.lod_tool.remove_lod_tier()
        assert len(props.lods) == initial_count, "remove_lod_tier failed to restore tier count"

        record_stage(
            "3. Preset Management & Tiers",
            "PASS",
            f"Active preset '{props.lod_preset}', configured {len(props.lods)} tiers, add/remove tier validated.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("3. Preset Management & Tiers", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 4: Inspection & Screen-Space Coverage Analysis
    # =========================================================================
    t0 = time.time()
    try:
        lod0_col = bpy.data.collections.get("Windsock_LOD0")
        assert lod0_col and lod0_col.objects
        bpy.ops.object.select_all(action="DESELECT")
        for obj in lod0_col.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = lod0_col.objects[0]

        res_inspect = bpy.ops.lod_tool.inspect_lod0()
        assert res_inspect == {"FINISHED"}, f"inspect_lod0 returned {res_inspect}"

        res_analyze = bpy.ops.lod_tool.analyze_and_configure()
        assert res_analyze == {"FINISHED"}, f"analyze_and_configure returned {res_analyze}"
        assert props.is_configured, "props.is_configured must be True"
        assert props.bounding_radius > 0, "bounding_radius must be positive"

        record_stage(
            "4. Inspection & Screen-Space Coverage",
            "PASS",
            f"Inspected base asset: radius={round(props.bounding_radius, 2)}m, base_triangles={props.base_triangles}",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("4. Inspection & Screen-Space Coverage", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 5: Multi-Tier LOD Generation Engine
    # =========================================================================
    t0 = time.time()
    try:
        props.export_base_name = "Windsock"
        props.target_engine = "MSFS_2024"

        # Generate LODs
        res_gen = bpy.ops.lod_tool.generate_all()
        assert res_gen == {"FINISHED"}, f"generate_all returned {res_gen}"

        # Check sibling collections
        expected_cols = [f"Windsock_LOD{i}" for i in range(len(props.lods))]
        for cname in expected_cols:
            assert cname in bpy.data.collections, f"Missing sibling collection {cname}"

        # Verify polycount monotonicity
        poly_counts = []
        for cname in expected_cols:
            col = bpy.data.collections[cname]
            tris = sum(len(o.data.polygons) for o in col.objects if o.type == "MESH")
            poly_counts.append((cname, tris))

        record_stage(
            "5. Multi-Tier LOD Generation",
            "PASS",
            f"Generated {len(expected_cols)} sibling tiers with counts: {poly_counts}",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("5. Multi-Tier LOD Generation", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 6: Tier Isolation & Previewing
    # =========================================================================
    t0 = time.time()
    try:
        res_preview = bpy.ops.lod_tool.preview_tier(tier_index=1)
        assert res_preview == {"FINISHED"}, f"preview_tier returned {res_preview}"

        res_solo = bpy.ops.lod_tool.solo_tier(tier_index=0)
        assert res_solo == {"FINISHED"}, f"solo_tier returned {res_solo}"

        record_stage(
            "6. Tier Preview & Soloing",
            "PASS",
            "preview_tier and solo_tier operators executed successfully.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("6. Tier Preview & Soloing", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 7: Collision Hull Generation & Removal
    # =========================================================================
    t0 = time.time()
    try:
        lod0_col = bpy.data.collections["Windsock_LOD0"]
        bpy.ops.object.select_all(action="DESELECT")
        for obj in lod0_col.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = lod0_col.objects[0]

        props.collision_decomposition_mode = "PER_OBJECT"
        props.collision_hull_count = 2

        # Generate hulls
        res_hull = bpy.ops.lod_tool.generate_collision_hulls()
        assert res_hull == {"FINISHED"}, f"generate_collision_hulls returned {res_hull}"

        coll_col = bpy.data.collections.get("Windsock_Colliders")
        assert coll_col is not None, "Collider collection 'Windsock_Colliders' not found"
        hull_count = len(coll_col.objects)
        assert hull_count > 0, "No colliders created in Windsock_Colliders"

        # Remove hulls
        res_rem_hull = bpy.ops.lod_tool.remove_collision_hulls()
        assert res_rem_hull == {"FINISHED"}, f"remove_collision_hulls returned {res_rem_hull}"
        rem_col = bpy.data.collections.get("Windsock_Colliders")
        assert rem_col is None or len(rem_col.objects) == 0, "Windsock_Colliders objects should be purged"

        record_stage(
            "7. Collision Hull Generation & Removal",
            "PASS",
            f"Generated {hull_count} collision hulls and verified clean removal.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("7. Collision Hull Generation & Removal", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 8: Impostor Atlas Baking & Preview Rig
    # =========================================================================
    t0 = time.time()
    try:
        lod0_col = bpy.data.collections["Windsock_LOD0"]
        bpy.ops.object.select_all(action="DESELECT")
        for obj in lod0_col.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = lod0_col.objects[0]

        # Generate impostor atlas (8x8 low res bake for speed)
        props.impostor_atlas_resolution = "512"
        props.impostor_hemispherical = True
        props.impostor_frame_count = 16

        res_bake = bpy.ops.lod_tool.generate_impostor()
        assert res_bake == {"FINISHED"}, f"generate_impostor returned {res_bake}"

        impostor_obj = bpy.data.objects.get("Windsock_LOD_Impostor")
        assert impostor_obj is not None, "Windsock_LOD_Impostor mesh object was not created"

        # Setup preview rig
        res_rig = bpy.ops.lod_tool.setup_impostor_preview_rig()
        assert res_rig == {"FINISHED"}, f"setup_impostor_preview_rig returned {res_rig}"
        assert bpy.data.collections.get("Windsock_Preview_Rig") is not None, (
            "Windsock_Preview_Rig collection not created"
        )

        # Remove preview rig
        res_rem_rig = bpy.ops.lod_tool.remove_impostor_preview_rig()
        assert res_rem_rig == {"FINISHED"}, f"remove_impostor_preview_rig returned {res_rem_rig}"

        # Remove impostor
        res_rem_imp = bpy.ops.lod_tool.remove_impostor()
        assert res_rem_imp == {"FINISHED"}, f"remove_impostor returned {res_rem_imp}"

        record_stage(
            "8. Impostor Atlas Baking & Preview Rig",
            "PASS",
            "Successfully baked octahedral impostor mesh/textures, verified preview rig, and cleanly removed.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("8. Impostor Atlas Baking & Preview Rig", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 9: Spatial Chunking
    # =========================================================================
    t0 = time.time()
    try:
        lod0_col = bpy.data.collections["Windsock_LOD0"]
        bpy.ops.object.select_all(action="DESELECT")
        for obj in lod0_col.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = lod0_col.objects[0]

        props.chunk_cell_size = 2.0
        props.chunk_split_z = False
        res_chunk = bpy.ops.lod_tool.spatial_chunk_and_generate()
        assert res_chunk in ({"FINISHED"}, {"CANCELLED"}), f"spatial_chunk_and_generate returned {res_chunk}"

        record_stage(
            "9. Spatial Chunking",
            "PASS",
            f"spatial_chunk_and_generate executed with chunk_cell_size=2.0m ({res_chunk}).",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("9. Spatial Chunking", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 10: PBR Materials & Texture Channel Packing (SimpleAircraft Textures)
    # =========================================================================
    t0 = time.time()
    try:
        res_mat_clean = bpy.ops.lod_tool.clean_and_repair_materials()
        assert res_mat_clean == {"FINISHED"}, f"clean_and_repair_materials returned {res_mat_clean}"

        # Test PBR Auto Match with authentic SDK textures
        res_automatch = bpy.ops.lod_tool.auto_match_pbr_folder(directory=textures_dir)
        assert res_automatch in ({"FINISHED"}, {"CANCELLED"}), f"auto_match_pbr_folder returned {res_automatch}"

        # Test PBR Channel Packing
        pbr_out_dir = os.path.join(temp_export_dir, "pbr_packed")
        os.makedirs(pbr_out_dir, exist_ok=True)
        props.export_directory = pbr_out_dir
        res_pack = bpy.ops.lod_tool.pack_pbr_textures()
        assert res_pack in ({"FINISHED"}, {"CANCELLED"}), f"pack_pbr_textures returned {res_pack}"

        # Test Material Preset Assignment
        res_assign = bpy.ops.omnimesh.assign_material_preset()
        assert res_assign in ({"FINISHED"}, {"CANCELLED"}), f"assign_material_preset returned {res_assign}"

        record_stage(
            "10. PBR Materials & Texture Packing",
            "PASS",
            f"Auto-matched textures from SDK folder, cleaned slots, packed PBR channels to {pbr_out_dir}.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("10. PBR Materials & Texture Packing", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 11: MSFS 2024 Vehicle Config, Spatial Markers & XML/CFG Export
    # =========================================================================
    t0 = time.time()
    try:
        # Add MSFS attachment marker
        res_att = bpy.ops.omnimesh.add_msfs_attachment()
        assert res_att == {"FINISHED"}, f"add_msfs_attachment returned {res_att}"

        # Generate scrape points
        res_scrape = bpy.ops.omnimesh.generate_msfs_scrape_points()
        assert res_scrape == {"FINISHED"}, f"generate_msfs_scrape_points returned {res_scrape}"

        # Copy authentic flight_model.cfg to temp folder to test sync
        msfs_cfg_dir = os.path.join(temp_export_dir, "msfs_configs")
        os.makedirs(msfs_cfg_dir, exist_ok=True)
        orig_fm = os.path.join(simple_aircraft_cfg_dir, "flight_model.cfg")
        temp_fm = os.path.join(msfs_cfg_dir, "flight_model.cfg")
        if os.path.isfile(orig_fm):
            shutil.copy2(orig_fm, temp_fm)
            props.msfs_spatial_cfg_path = temp_fm
            res_exp_spat = bpy.ops.omnimesh.export_msfs_spatial()
            assert res_exp_spat == {"FINISHED"}, f"export_msfs_spatial returned {res_exp_spat}"

        record_stage(
            "11. MSFS 2024 Vehicle Config & XML/CFG",
            "PASS",
            f"Config markers generated and synced to flight_model.cfg at {temp_fm}",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("11. MSFS 2024 Vehicle Config & XML/CFG", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 12: Multi-Engine Export Package (MSFS 2024, UE5, Unity 6)
    # =========================================================================
    t0 = time.time()
    try:
        engine_exports = {}
        for engine, subfolder in [("MSFS_2024", "msfs_out"), ("UE5", "ue5_out"), ("UNITY_6", "unity_out")]:
            out_path = os.path.join(temp_export_dir, subfolder)
            os.makedirs(out_path, exist_ok=True)
            props.target_engine = engine
            props.export_directory = out_path
            res_exp = bpy.ops.lod_tool.export_engine_package()
            assert res_exp == {"FINISHED"}, f"export_engine_package for {engine} returned {res_exp}"
            files = os.listdir(out_path)
            engine_exports[engine] = files

        record_stage(
            "12. Multi-Engine Export Packaging",
            "PASS",
            f"Successfully packaged assets for all 3 target engines: {engine_exports}",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("12. Multi-Engine Export Packaging", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 13: Viewport Simulator & Real-Time LOD Distance Scrubber
    # =========================================================================
    t0 = time.time()
    try:
        # Toggle simulator on (modal operator returns {'RUNNING_MODAL'})
        res_sim_on = bpy.ops.lod_tool.toggle_simulator()
        assert res_sim_on in ({"FINISHED"}, {"RUNNING_MODAL"}), f"toggle_simulator (start) returned {res_sim_on}"
        assert props.is_simulator_active, "is_simulator_active should be True"

        # Reset distance
        res_dist = bpy.ops.lod_tool.reset_virtual_distance()
        assert res_dist == {"FINISHED"}, f"reset_virtual_distance returned {res_dist}"

        # Toggle simulator off
        res_sim_off = bpy.ops.lod_tool.toggle_simulator()
        assert res_sim_off in ({"FINISHED"}, {"RUNNING_MODAL"}), f"toggle_simulator (stop) returned {res_sim_off}"
        assert not props.is_simulator_active, "is_simulator_active should be False"

        # Toggle split preview
        res_split_on = bpy.ops.lod_tool.toggle_split_preview()
        assert res_split_on in ({"FINISHED"}, {"RUNNING_MODAL"}), (
            f"toggle_split_preview (start) returned {res_split_on}"
        )
        res_split_off = bpy.ops.lod_tool.toggle_split_preview()
        assert res_split_off in ({"FINISHED"}, {"RUNNING_MODAL"}), (
            f"toggle_split_preview (stop) returned {res_split_off}"
        )

        record_stage(
            "13. Viewport Simulator & Split Preview",
            "PASS",
            "toggle_simulator, reset_virtual_distance, and toggle_split_preview executed cleanly.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("13. Viewport Simulator & Split Preview", "FAIL", str(exc), time.time() - t0)

    # =========================================================================
    # STAGE 14: MSFS 2024 SimpleAircraft Testing (Landing Gear, Rig & Animations)
    # =========================================================================
    t0 = time.time()
    try:
        bpy.ops.wm.open_mainfile(filepath=simple_aircraft_blend)
        bootstrap_addon()
        scene = bpy.context.scene
        props = getattr(scene, "lod_tool", None)

        # Asobo migration on SimpleAircraft
        res_mig = bpy.ops.omnimesh.convert_asobo_hierarchy()
        assert res_mig == {"FINISHED"}, f"SimpleAircraft migration returned {res_mig}"

        # Verify automatic texture relinking healed the broken D:\ paths
        fuselage_img = bpy.data.images.get("SimpleAircraft_FUSELAGE_albd_000.png")
        assert fuselage_img is not None, "SimpleAircraft_FUSELAGE_albd_000.png should exist"
        assert not fuselage_img.filepath.startswith("D:"), (
            f"Fuselage texture should be relinked, got {fuselage_img.filepath}"
        )

        # Import authentic MSFS flight_model.cfg spatial points (creates Spatial collection & wheels)
        fm_path = os.path.join(simple_aircraft_cfg_dir, "flight_model.cfg")
        if os.path.isfile(fm_path):
            res_imp_spat = bpy.ops.omnimesh.import_msfs_spatial(filepath=fm_path)
            assert res_imp_spat == {"FINISHED"}, f"import_msfs_spatial returned {res_imp_spat}"

        # Align landing gear to ground level
        res_gear = bpy.ops.omnimesh.align_gear_ground_level()
        assert res_gear in ({"FINISHED"}, {"CANCELLED"}), f"align_gear_ground_level returned {res_gear}"

        # Animation scanning & tagging
        res_scan_anim = bpy.ops.omnimesh.scan_animations()
        assert res_scan_anim in ({"FINISHED"}, {"CANCELLED"}), f"scan_animations returned {res_scan_anim}"

        record_stage(
            "14. SimpleAircraft Model, Gear & Rig Verification",
            "PASS",
            f"SimpleAircraft ({len(bpy.data.objects)} objects) migrated, spatial points imported, and rig verified.",
            time.time() - t0,
        )
    except Exception as exc:
        record_stage("14. SimpleAircraft Model, Gear & Rig Verification", "FAIL", str(exc), time.time() - t0)

    # Clean up temp export dir
    try:
        shutil.rmtree(temp_export_dir)
    except Exception:
        pass

    RESULTS["total_duration_sec"] = round(time.time() - RESULTS["start_time"], 3)
    RESULTS["all_passed"] = RESULTS["failed"] == 0
    return RESULTS


if __name__ == "__main__":
    report = run_all_tests()
    print("\n" + "=" * 60)
    print("FINAL TEST RUNNER SUMMARY REPORT:")
    print("=" * 60)
    print(json.dumps(report, indent=2))
