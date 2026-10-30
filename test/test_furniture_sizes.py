"""家具尺寸以公尺為準：不能跟著房間比例縮放。"""

from __future__ import annotations

from designbridge.layout.layout_enforce import _bind_companions, _score_soft_constraints
from designbridge.layout.layout_items import FurnitureItem, default_footprint, fit_real_size


def _metres(item: FurnitureItem, room_w: float, room_d: float) -> tuple[float, float]:
    return round(item.w * room_w, 2), round(item.h * room_d, 2)


def test_default_footprint_is_same_size_in_any_room():
    for room_w, room_d in ((3.0, 3.0), (4.0, 3.5), (8.0, 6.0)):
        w, h = default_footprint("sofa", room_w, room_d)
        assert (round(w * room_w, 2), round(h * room_d, 2)) == (2.0, 0.9)


def test_fit_clamps_implausible_depth_and_keeps_centre():
    sofa = FurnitureItem("sofa_1", "sofa", 0.3, 0.6, 0.30, 0.13)   # 4 m 房間裡深 0.52 m
    cx, cy = sofa.x + sofa.w / 2, sofa.y + sofa.h / 2
    assert fit_real_size(sofa, 4.0, 4.0)
    assert _metres(sofa, 4.0, 4.0)[1] >= 0.67
    assert abs(sofa.x + sofa.w / 2 - cx) < 1e-9 and abs(sofa.y + sofa.h / 2 - cy) < 1e-9


def test_fit_keeps_plausible_sizes():
    single_bed = FurnitureItem("bed_1", "bed", 0.0, 0.3, 0.225, 0.5)   # 0.9 × 2.0 m
    assert not fit_real_size(single_bed, 4.0, 4.0)


def test_fit_handles_bed_turned_against_side_wall():
    bed = FurnitureItem("bed_1", "bed", 0.0, 0.3, 0.55, 0.40)   # 2.2 × 1.6 m，長邊沿牆
    fit_real_size(bed, 4.0, 4.0)
    w, d = _metres(bed, 4.0, 4.0)
    assert w > d and 1.8 <= w <= 2.4


def test_coffee_table_binds_to_sofa_at_standard_gap():
    space = {"estimated_size": {"width": 5.0, "depth": 5.0}}
    sofa = FurnitureItem("sofa_1", "sofa", 0.30, 0.60, 0.40, 0.18)
    table = FurnitureItem("coffee_table_1", "coffee_table", 0.20, 0.30, 0.22, 0.12)   # 離沙發 0.9 m
    _bind_companions([sofa, table], space)
    assert table.anchor == "sofa_1"
    assert round((sofa.y - table.y - table.h) * 5.0, 2) == 0.45
    assert abs((table.x + table.w / 2) - (sofa.x + sofa.w / 2)) < 1e-9


def test_wall_cabinet_beside_window_does_not_block_light():
    space = {"estimated_size": {"width": 4.0, "depth": 3.5},
             "windows": [{"wall": "far", "x": 0.4, "y": 0.0, "w": 0.3, "h": 0.05}]}
    beside = [FurnitureItem("wardrobe_1", "wardrobe", 0.05, 0.02, 0.30, 0.17)]
    under = [FurnitureItem("wardrobe_1", "wardrobe", 0.42, 0.02, 0.30, 0.17)]
    assert _score_soft_constraints(beside, space)["natural_light"] == 1.0
    assert _score_soft_constraints(under, space)["natural_light"] == 0.0
