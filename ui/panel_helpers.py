"""Helper UI drawers for OmniMesh panels."""

from __future__ import annotations

from typing import Any

_VEHICLE_HELPER_SECTIONS: tuple[tuple[str, str, tuple[tuple[tuple[str, str, str], tuple[str, str, str]], ...]], ...] = (
    (
        "Spatial & Ground",
        "EMPTY_AXIS",
        (
            (
                ("omnimesh.snap_vehicle_point_to_vertex", "Snap Vertex", "SNAP_ON"),
                ("omnimesh.mirror_vehicle_marker", "Mirror L/R", "MOD_MIRROR"),
            ),
            (
                ("omnimesh.generate_vehicle_scrape_points", "Scrape Pts", "MESH_DATA"),
                ("omnimesh.align_gear_ground_level", "Align Gear", "IMPORT"),
            ),
        ),
    ),
    (
        "Cameras & Attachments",
        "CAMERA_DATA",
        (
            (
                ("omnimesh.look_through_vehicle_camera", "Look Cam", "VIEW_CAMERA"),
                ("omnimesh.restore_scene_camera", "Restore Cam", "LOOP_BACK"),
            ),
            (
                ("omnimesh.align_vehicle_camera_to_view", "Cam to View", "ORIENTATION_VIEW"),
                ("omnimesh.add_vehicle_attachment", "Add Attach", "LINKED"),
            ),
        ),
    ),
    (
        "MSFS CFG Sync (Import / Export)",
        "FILE_TEXT",
        (
            (
                ("omnimesh.import_msfs_spatial", "Imp Spatial", "IMPORT"),
                ("omnimesh.export_msfs_spatial", "Exp Spatial", "EXPORT"),
            ),
            (
                ("omnimesh.import_msfs_lights", "Imp Lights", "IMPORT"),
                ("omnimesh.export_msfs_lights", "Exp Lights", "EXPORT"),
            ),
            (
                ("omnimesh.import_msfs_cameras", "Imp Cams", "IMPORT"),
                ("omnimesh.export_msfs_cameras", "Exp Cams", "EXPORT"),
            ),
            (
                ("omnimesh.import_msfs_attachments", "Imp Attach", "IMPORT"),
                ("omnimesh.export_msfs_attachments", "Exp Attach", "EXPORT"),
            ),
        ),
    ),
)


def draw_vehicle_helpers(box_cfg: Any, cfg_props: Any) -> None:
    """Draw collapsible Vehicle & Asset helper tools inside the configurator box."""
    show_helpers = bool(getattr(cfg_props, "show_helpers", False))
    arrow_hlp = "TRIA_DOWN" if show_helpers else "TRIA_RIGHT"
    row_hlp_hdr = box_cfg.row(align=True)
    row_hlp_hdr.prop(cfg_props, "show_helpers", text="Vehicle & Asset Helpers", icon=arrow_hlp, emboss=False)
    if not show_helpers:
        return

    box_hlp = box_cfg.box()
    box_hlp.use_property_split = False
    for sec_title, sec_icon, rows in _VEHICLE_HELPER_SECTIONS:
        box_hlp.label(text=sec_title, icon=sec_icon)
        for left_op, right_op in rows:
            row_hlp = box_hlp.row(align=True)
            row_hlp.operator(left_op[0], text=left_op[1], icon=left_op[2])
            row_hlp.operator(right_op[0], text=right_op[1], icon=right_op[2])
