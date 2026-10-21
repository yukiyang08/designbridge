"""風水＋動線健檢：報告的狀態（符合／違規／不適用）、分數與一鍵修正。"""

from __future__ import annotations

from designbridge.layout.fengshui_audit import audit_layout, fix_layout, rules_for_room
from designbridge.layout.photo_fengshui import opening_box

DOOR_NEAR = [{"x": 0.45, "y": 0.98, "w": 0.10, "h": 0.02}]
WINDOW_FAR = [{"x": 0.40, "y": 0.0, "w": 0.20, "h": 0.02}]


def _by_trigger(report):
    return {r["trigger"]: r for r in report["fengshui"]["rules"]}


def test_bedroom_rules_are_selected_by_room_type():
    rules = rules_for_room("bedroom")
    assert "door_not_facing_bed" in rules
    assert "door_not_facing_stove" not in rules, "廚房的規則不該套到臥室"
    assert len(rules_for_room("和室")) == 12, "自訂房型對不上時要全部視為相關"


def test_bed_facing_door_is_reported_with_offender():
    bed = {"id": "bed_1", "type": "bed", "x": 0.39, "y": 0.05, "w": 0.22, "h": 0.40}
    report = audit_layout([bed], 4.0, 3.2, "bedroom", DOOR_NEAR, WINDOW_FAR)
    rules = _by_trigger(report)
    assert rules["door_not_facing_bed"]["status"] == "fail"
    assert rules["door_not_facing_bed"]["offenders"] == ["bed_1"]
    assert rules["door_not_facing_bed"]["remedy"], "違規要附化解建議"
    assert rules["mirror_not_facing_bed"]["status"] == "na", "沒有鏡子就不適用"
    assert report["fengshui"]["score"] < 100


def test_fix_moves_bed_and_clears_the_violation():
    bed = {"id": "bed_1", "type": "bed", "x": 0.39, "y": 0.05, "w": 0.22, "h": 0.40, "extra": 1}
    fixed = fix_layout([bed], DOOR_NEAR, WINDOW_FAR, ["door_not_facing_bed"])
    assert fixed[0]["extra"] == 1, "修正不該弄丟原本的欄位"
    assert fixed[0]["x"] != bed["x"]
    report = audit_layout(fixed, 4.0, 3.2, "bedroom", DOOR_NEAR, WINDOW_FAR, ["door_not_facing_bed"])
    assert _by_trigger(report)["door_not_facing_bed"]["status"] == "pass"


def test_missing_openings_are_flagged_as_assumed():
    report = audit_layout([], 4.0, 3.2, "bedroom", rules=["door_not_facing_bed", "mirror_not_facing_bed"])
    assert report["assumed_openings"] is True
    assert report["fengshui"]["score"] is None, "全部不適用時不給分數"


def test_straight_through_without_any_blocker_is_a_violation():
    """穿堂煞：房裡沒有可當屏風的家具，報告要如實說違規（並建議加屏風）。"""
    report = audit_layout([], 4.0, 3.2, "living_room", DOOR_NEAR, WINDOW_FAR, ["door_not_facing_window"])
    assert _by_trigger(report)["door_not_facing_window"]["status"] == "fail"


def test_furniture_in_doorway_blocks_circulation():
    cabinet = {"id": "cabinet_1", "type": "cabinet", "x": 0.42, "y": 0.85, "w": 0.16, "h": 0.12}
    report = audit_layout([cabinet], 4.0, 3.2, "living_room", DOOR_NEAR, WINDOW_FAR)
    kinds = {i["kind"] for i in report["circulation"]["issues"]}
    assert "door_blocked" in kinds


def test_boxed_in_bed_is_unreachable():
    """床被衣櫃和書架圍住、縫隙不到 60 cm，從門口走不到。"""
    room_w, room_d = 4.0, 4.0
    placements = [
        {"id": "bed_1", "type": "bed", "x": 0.05, "y": 0.02, "w": 0.4, "h": 0.5},
        {"id": "wardrobe_1", "type": "wardrobe", "x": 0.0, "y": 0.56, "w": 0.95, "h": 0.12},
        {"id": "shelf_1", "type": "bookshelf", "x": 0.5, "y": 0.0, "w": 0.1, "h": 0.56},
    ]
    report = audit_layout(placements, room_w, room_d, "bedroom", DOOR_NEAR, WINDOW_FAR)
    unreachable = [i for i in report["circulation"]["issues"] if i["kind"] == "unreachable"]
    assert unreachable and "bed_1" in unreachable[0]["offenders"]


def test_open_room_has_clean_circulation():
    placements = [{"id": "bed_1", "type": "bed", "x": 0.05, "y": 0.05, "w": 0.4, "h": 0.5}]
    report = audit_layout(placements, 4.0, 4.0, "bedroom", DOOR_NEAR, WINDOW_FAR)
    assert report["circulation"]["issues"] == []
    assert report["circulation"]["score"] == 100


def test_photo_opening_box_matches_wall():
    side = opening_box("left", 0.5, 0.9, 4.0, 3.0)
    assert side["x"] == 0.0 and abs(side["h"] - 0.3) < 1e-6
    far = opening_box("far", 0.5, 1.0, 4.0, 3.0)
    assert far["y"] == 0.0 and abs(far["w"] - 0.25) < 1e-6


def test_frontend_groups_and_rooms_match_skill_cards():
    """前端選單的分組／適用房型要跟 SKILL.md 一致，否則開關自動挑的規則跟報告對不上。"""
    import re
    from pathlib import Path
    from designbridge.layout.special_constraints import get_constraint_registry

    src = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "composables"
           / "design-flow" / "state.js").read_text(encoding="utf-8")
    block = re.search(r"FENGSHUI_OPTIONS\s*=\s*\[(.*?)\n\]", src, re.DOTALL).group(1)
    cards = get_constraint_registry().load()
    for entry in re.findall(r"\{(.*?)\n  \}", block, re.DOTALL):
        value = re.search(r"value:\s*'([a-z_]+)'", entry).group(1)
        group = re.search(r"group:\s*'([a-z]+)'", entry).group(1)
        rooms = re.findall(r"'([a-z_]+)'", re.search(r"rooms:\s*\[(.*?)\]", entry).group(1))
        assert group == cards[value].category, f"{value} 分組不一致"
        assert set(rooms) == set(cards[value].rooms), f"{value} 適用房型不一致"


def test_nightstands_follow_the_bed():
    """床被推開時，貼在旁邊的床頭櫃要一起走，不能留在原地被床疊上去。"""
    placements = [
        {"id": "bed_1", "type": "bed", "x": 0.39, "y": 0.05, "w": 0.22, "h": 0.40},
        {"id": "ns_1", "type": "nightstand", "x": 0.32, "y": 0.05, "w": 0.07, "h": 0.07},
        {"id": "ns_2", "type": "nightstand", "x": 0.61, "y": 0.05, "w": 0.07, "h": 0.07},
    ]
    fixed = {p["id"]: p for p in fix_layout(placements, DOOR_NEAR, WINDOW_FAR, ["door_not_facing_bed"], 4.0, 3.2)}
    bed = fixed["bed_1"]
    assert bed["x"] != 0.39
    left, right = fixed["ns_1"], fixed["ns_2"]
    assert -1e-3 <= bed["x"] - (left["x"] + left["w"]) <= 0.07, "左側床頭櫃沒跟著床"
    assert -1e-3 <= right["x"] - (bed["x"] + bed["w"]) <= 0.07, "右側床頭櫃沒跟著床"
    assert left["y"] == right["y"] == bed["y"], "床頭櫃要留在床頭那一端"


def test_fix_never_leaves_furniture_overlapping():
    """推開床時兩側都是衣櫃：可以挪動衣櫃讓出位置，但結果不能有任何家具疊在一起。"""
    placements = [
        {"id": "bed_1", "type": "bed", "x": 0.39, "y": 0.05, "w": 0.22, "h": 0.40},
        {"id": "wardrobe_l", "type": "wardrobe", "x": 0.0, "y": 0.0, "w": 0.39, "h": 0.5},
        {"id": "wardrobe_r", "type": "wardrobe", "x": 0.61, "y": 0.0, "w": 0.39, "h": 0.5},
    ]
    fixed = fix_layout(placements, DOOR_NEAR, WINDOW_FAR, ["door_not_facing_bed"], 4.0, 3.2)
    for i, a in enumerate(fixed):
        for b in fixed[i + 1:]:
            ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            assert ox <= 0.005 or oy <= 0.005, f"{a['id']} 與 {b['id']} 疊在一起"


_TV = {"id": "tv_1", "type": "tv_unit", "x": 0.0, "y": 0.03, "w": 0.32, "h": 0.07}
_TABLE = {"id": "ct_1", "type": "coffee_table", "x": 0.08, "y": 0.20, "w": 0.20, "h": 0.10}


def test_report_includes_facing_for_every_piece():
    """平面圖箭頭：每件家具都有正面朝向，跟生圖擺向是同一套（facing.py）。"""
    placements = [
        _TV, _TABLE,
        {"id": "sofa_1", "type": "sofa", "x": 0.05, "y": 0.45, "w": 0.40, "h": 0.18},
        {"id": "dt_1", "type": "dining_table", "x": 0.58, "y": 0.42, "w": 0.27, "h": 0.15},
        {"id": "chair_up", "type": "chair", "x": 0.62, "y": 0.30, "w": 0.08, "h": 0.08},
        {"id": "chair_down", "type": "chair", "x": 0.62, "y": 0.60, "w": 0.08, "h": 0.08},
        {"id": "bed_1", "type": "bed", "x": 0.0, "y": 0.70, "w": 0.35, "h": 0.28},
        {"id": "desk_1", "type": "desk", "x": 0.80, "y": 0.80, "w": 0.18, "h": 0.10},
    ]
    facing = audit_layout(placements, 5.0, 5.0, "living_room")["facing"]
    assert set(facing) == {p["id"] for p in placements}, "每件家具都要有方向"
    assert facing["tv_1"] == "down", "牆角的長電視櫃看長邊：靠上牆、朝下"
    assert facing["sofa_1"] == "up", "沙發面向上方的茶几／電視"
    assert facing["ct_1"] == "down", "茶几面向沙發"
    assert facing["chair_up"] == "down" and facing["chair_down"] == "up", "椅子面向餐桌"
    assert facing["bed_1"] == "right", "床頭靠左牆，床尾朝右"
    assert facing["desk_1"] == "left", "書桌正面（坐的那側）背對它靠的右牆"
