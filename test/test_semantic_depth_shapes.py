"""Verify the projected depth map encodes *what* each furniture piece is, not just where.

A depth map is grayscale — a solid cuboid is all the depth-ControlNet ever sees, so it
renders a cuboid. These checks assert the two things that make a block identifiable:

  1. Shape — a table's depth shows floor under its top (legs, not a brick); a sofa shows
     a backrest taller than its seat; a lamp is a slender pole, not a column.
  2. Identity — every projected piece reports the image-space bbox it actually occupies,
     so the render prompt can name it where the depth map really put it.
"""

from __future__ import annotations

import numpy as np

from designbridge.layout.scene_graph_to_depth import (
    _shape_kind,
    furniture_parts,
    project_scene_graph_to_depth,
)

SPACE = {"estimated_size": {"width": 5.0, "depth": 4.0, "height": 2.8}}
IMG = 768


def _project(placements):
    return project_scene_graph_to_depth(placements, SPACE, image_size=(IMG, IMG))


def _item(ftype, x=0.35, y=0.40, w=0.22, h=0.18):
    return {"id": f"{ftype}_1", "type": ftype, "x": x, "y": y, "w": w, "h": h}


def test_shape_kinds_survive_free_text_labels():
    """The planner invents modifier forms; they must still reach the right silhouette."""
    cases = {
        "sofa": "seat", "loveseat": "seat", "armchair": "seat",
        "platform_bed": "bed", "bunk_bed": "bed",
        "coffee_table": "table", "dining_table": "table", "desk": "table",
        "floor_lamp": "lamp", "potted_plant": "plant", "tv": "panel",
        "wardrobe": "box", "some_unknown_thing": "box",
    }
    for ftype, expected in cases.items():
        got = _shape_kind(ftype)
        assert got == expected, f"{ftype}: expected {expected}, got {got}"
    print(f"[kinds] {len(cases)} labels mapped to the right silhouette")


def test_table_top_floats_above_the_floor():
    """A table's parts must leave a gap under the top — that gap is what stops the
    model rendering it as a solid block."""
    parts = furniture_parts("dining_table", 0.3, 0.3, 0.3, 0.2, 0.75)
    tops = [p for p in parts if p[4] > 0.0]
    legs = [p for p in parts if p[4] == 0.0]
    assert tops, "tabletop must start above the floor"
    assert len(legs) == 4, f"expected 4 legs, got {len(legs)}"
    # every leg is a thin corner post, not the full footprint
    for u0, u1, v0, v1, _z0, _z1 in legs:
        assert (u1 - u0) <= 0.2 and (v1 - v0) <= 0.2, "leg is not slender"
    print(f"[table] top lifted to {tops[0][4]:.2f}m over {len(legs)} slender legs")


def test_seat_has_a_backrest_taller_than_the_cushion():
    parts = furniture_parts("sofa", 0.05, 0.3, 0.2, 0.4, 0.85)
    # the cushion is the one part covering the whole footprint from the floor up
    cushions = [
        p for p in parts
        if (p[0], p[1], p[2], p[3], p[4]) == (0.0, 1.0, 0.0, 1.0, 0.0)
    ]
    assert len(cushions) == 1, f"expected exactly one seat cushion, got {cushions}"
    tallest = max(p[5] for p in parts)
    assert tallest > cushions[0][5], "backrest must rise above the seat cushion"
    print(f"[seat] cushion {cushions[0][5]:.2f}m, backrest {tallest:.2f}m, {len(parts)} parts")


def test_table_projects_thinner_than_a_cabinet_of_the_same_footprint():
    """Same footprint, same height: the table must cover far fewer pixels, because the
    space under its top stays floor. If it covers as much, it is still a brick."""
    table = _project([_item("dining_table")])
    box = _project([_item("cabinet")])
    table_px = int((table["id_map"] >= 4).sum())
    box_px = int((box["id_map"] >= 4).sum())
    assert table_px < box_px * 0.8, (
        f"table {table_px}px vs cabinet {box_px}px — table is not hollowed out"
    )
    print(f"[silhouette] table {table_px}px < cabinet {box_px}px (same footprint)")


def test_lamp_is_slender():
    lamp = _project([_item("floor_lamp", w=0.08, h=0.08)])
    cabinet = _project([_item("cabinet", w=0.08, h=0.08)])
    lamp_px = int((lamp["id_map"] >= 4).sum())
    cab_px = int((cabinet["id_map"] >= 4).sum())
    assert 0 < lamp_px < cab_px, f"lamp {lamp_px}px should be visible but slimmer than {cab_px}px"
    print(f"[lamp] {lamp_px}px vs solid column {cab_px}px")


def test_every_piece_reports_where_it_landed_on_screen():
    placements = [
        _item("sofa", x=0.06, y=0.30, w=0.18, h=0.42),
        _item("coffee_table", x=0.38, y=0.44, w=0.24, h=0.18),
        _item("tv_unit", x=0.74, y=0.34, w=0.14, h=0.36),
    ]
    inst = _project(placements)["meta"]["instances"]
    by_type = {i["type"]: i for i in inst}
    assert set(by_type) == {"sofa", "coffee_table", "tv_unit"}, by_type.keys()
    for i in inst:
        assert i["visible"], f"{i['type']} vanished from the projection"
        assert 0.0 <= i["cx"] <= 1.0 and 0.0 <= i["cy"] <= 1.0

    # left-to-right on the plan must stay left-to-right on screen, otherwise the prompt
    # would name each blob on the wrong side of the frame
    assert by_type["sofa"]["cx"] < by_type["coffee_table"]["cx"] < by_type["tv_unit"]["cx"], (
        {t: i["cx"] for t, i in by_type.items()}
    )
    print("[instances] " + ", ".join(f"{t}@x={i['cx']:.2f}" for t, i in by_type.items()))


def test_offscreen_piece_is_reported_not_silently_dropped():
    """Furniture hugging a side wall falls outside the camera's FOV. It must come back
    marked invisible so the renderer can drop it from the prompt rather than asking the
    model to paint a sofa where the depth map is empty."""
    inst = _project([_item("wardrobe", x=0.02, y=0.40, w=0.06, h=0.06)])["meta"]["instances"]
    assert len(inst) == 1 and inst[0]["visible"] is False, inst
    print("[offscreen] wall-hugging piece correctly reported as not visible")


if __name__ == "__main__":
    test_shape_kinds_survive_free_text_labels()
    test_table_top_floats_above_the_floor()
    test_seat_has_a_backrest_taller_than_the_cushion()
    test_table_projects_thinner_than_a_cabinet_of_the_same_footprint()
    test_lamp_is_slender()
    test_every_piece_reports_where_it_landed_on_screen()
    test_offscreen_piece_is_reported_not_silently_dropped()
    print("\nALL SEMANTIC-DEPTH CHECKS PASSED ✅")
