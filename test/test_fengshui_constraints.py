"""風水硬約束：勾選後是否真的把家具移出禁忌位置，以及沒勾選時是否完全不動。

這些檢查故意不看「看起來對不對」，只斷言幾何事實：
  1. 觸發 —— 勾選的規則確實寫進 special_constraints，並附上給 LLM 的提示文字。
  2. 修正 —— 違規的家具被推出門的視線帶；verifier 在修正前回報 False、修正後 True。
  3. 不誤傷 —— 門開在別面牆、或規則沒勾選時，家具座標一動也不動。
  4. 誠實 —— 房間窄到無解時保持原位並回報未滿足，而不是把家具塞進牆裡。
"""

from __future__ import annotations

import re
from pathlib import Path

from designbridge.layout.layout_items import FurnitureItem, _normalize_ftype
from designbridge.layout.special_constraints import (
    _ENFORCERS,
    _VERIFIERS,
    _opening_wall,
    apply_special_layout_constraints,
    enrich_requirement,
    get_constraint_registry,
    verify_special_constraints,
)

# 選項清單原本在 useDesignFlow.js，前端拆檔後搬到 design-flow/state.js
_FLOW_JS = (Path(__file__).resolve().parent.parent
            / "frontend" / "src" / "composables" / "design-flow" / "state.js")


def _frontend_fengshui_values() -> set[str]:
    """從 useDesignFlow.js 的 FENGSHUI_OPTIONS 撈出前端真的會送出的 trigger。"""
    src = _FLOW_JS.read_text(encoding="utf-8")
    block = re.search(r"FENGSHUI_OPTIONS\s*=\s*\[(.*?)\n\]", src, re.DOTALL)
    assert block, "design-flow/state.js 裡找不到 FENGSHUI_OPTIONS"
    return set(re.findall(r"value:\s*'([a-z_]+)'", block.group(1)))

# 門在近牆（y=1）正中央——api.py 產生的預設門就長這樣
DOOR_NEAR = {"x": 0.45, "y": 1.0, "w": 0.10, "h": 0.02}
# 門在左牆：左右牆的門寬記在 h，w 是牆厚
DOOR_LEFT = {"x": 0.0, "y": 0.40, "w": 0.02, "h": 0.10}


def _req(rules: list[str], doors: list[dict] | None = None) -> dict:
    req = {
        "space_info": {
            "estimated_size": {"width": 4.0, "depth": 3.2, "height": 2.8},
            "windows": [{"x": 0.4, "y": 0.0, "w": 0.2, "h": 0.02}],
            "doors": doors if doors is not None else [DOOR_NEAR],
        },
    }
    return enrich_requirement(req, rules)


def _xy(items: list) -> list[tuple[float, float]]:
    return [(round(i.x, 4), round(i.y, 4)) for i in items]


def test_new_cards_are_registered():
    """新增的卡片要被 registry 讀到，否則勾了也不會有任何作用。"""
    cards = get_constraint_registry().load()
    for trigger in (
        "bed_not_facing_door", "sofa_not_back_to_door", "desk_not_facing_window",
        "desk_not_back_to_door", "door_not_facing_stove", "door_not_facing_toilet",
        "door_not_facing_mirror", "door_not_facing_bed", "mirror_not_facing_bed",
        "bed_head_not_under_window", "sofa_not_back_to_window", "stove_not_under_window",
        "stove_away_from_water", "door_not_facing_window",
    ):
        assert trigger in cards, f"{trigger} 沒有被 registry 載入"
        assert cards[trigger].enforce, f"{trigger} 沒宣告 enforce"
        assert cards[trigger].prompt_addition, f"{trigger} 沒有給 LLM 的提示文字"
        for key in cards[trigger].enforce:
            assert key in _ENFORCERS, f"{trigger} 的 {key} 沒有對應的 enforcer"
            assert key in _VERIFIERS, f"{trigger} 的 {key} 沒有對應的 verifier"
    fengshui = [c for c in cards.values() if c.constraint_type == "fengshui"]
    assert len(fengshui) == 14, f"預期 14 條風水規則，實際 {len(fengshui)}"
    # 前端的風水選單要跟後端卡片一對一，少一條就是勾不到、多一條就是勾了沒作用
    ui, backend = _frontend_fengshui_values(), {c.trigger for c in fengshui}
    assert ui == backend, (
        f"前端選單與後端卡片不一致：只在前端 {sorted(ui - backend)}，"
        f"只在後端 {sorted(backend - ui)}"
    )
    assert len(cards) == len(fengshui), "registry 裡混進了非風水卡片"
    print(f"[registry] {len(fengshui)} 條風水規則，前端選單一致")


def test_checking_a_rule_writes_it_into_the_requirement():
    """勾選 = 寫進硬約束旗標 + 把提示文字併進 design_description。"""
    req = _req(["door_not_facing_stove"])
    assert req["special_constraints"]["door_not_facing_stove"] is True
    assert req["special_constraints"]["door_not_facing_toilet"] is False
    assert "stove" in req["design_description"].lower()
    print("[enrich] 旗標與提示文字都寫入了")


def test_stove_in_the_doorway_sightline_is_pushed_aside():
    """開門不見灶：爐灶擋在門的正向視線上 → 推開；推完 verifier 要轉為滿足。"""
    req = _req(["door_not_facing_stove"])
    items = [
        FurnitureItem("stove_1", "stove", 0.46, 0.04, 0.13, 0.08),
        FurnitureItem("cabinet_1", "cabinet", 0.05, 0.04, 0.30, 0.08),
    ]
    assert verify_special_constraints(items, req)["door_not_facing_stove"] is False

    items = apply_special_layout_constraints(items, req)
    assert verify_special_constraints(items, req)["door_not_facing_stove"] is True

    stove = items[0]
    # 門帶是 x∈[0.41, 0.59]；爐灶必須整個落在帶外
    assert stove.x >= 0.59 or stove.x + stove.w <= 0.41, f"stove x={stove.x}"
    assert items[1].x == 0.05, "沒被規則指名的櫥櫃不該被動到"
    print(f"[stove] 0.46 → {stove.x:.2f}，已移出門的視線帶")


def test_toilet_is_checked_against_a_side_wall_door():
    """左右牆的門，視線帶沿 y 橫跨——門寬要從 h 讀，不是 w。"""
    assert _opening_wall(DOOR_LEFT) == "left"
    req = _req(["door_not_facing_toilet"], doors=[DOOR_LEFT])
    items = [FurnitureItem("toilet_1", "toilet", 0.12, 0.42, 0.09, 0.12)]
    assert verify_special_constraints(items, req)["door_not_facing_toilet"] is False

    items = apply_special_layout_constraints(items, req)
    assert verify_special_constraints(items, req)["door_not_facing_toilet"] is True
    t = items[0]
    assert t.x == 0.12, "左牆的門只該讓馬桶沿 y 移動，x 不動"
    print(f"[toilet] y 0.42 → {t.y:.2f}（側牆門，沿 y 推開）")


def test_desk_with_its_back_to_the_door_is_moved():
    """書桌不背門：書桌靠遠牆 → 人背朝近牆；門開在近牆且對齊就是背門。"""
    req = _req(["desk_not_back_to_door"])
    items = [FurnitureItem("desk_1", "desk", 0.42, 0.03, 0.16, 0.09)]
    assert verify_special_constraints(items, req)["desk_not_back_to_door"] is False

    items = apply_special_layout_constraints(items, req)
    assert verify_special_constraints(items, req)["desk_not_back_to_door"] is True
    print(f"[desk] x 0.42 → {items[0].x:.2f}，座位不再正背著門")


def test_door_on_another_wall_does_not_move_the_desk():
    """門開在左牆時，靠遠牆的書桌背對的是近牆，這條規則不該出手。"""
    req = _req(["desk_not_back_to_door"], doors=[DOOR_LEFT])
    items = [FurnitureItem("desk_1", "desk", 0.42, 0.03, 0.16, 0.09)]
    before = _xy(items)
    items = apply_special_layout_constraints(items, req)
    assert _xy(items) == before, "門不在背後那面牆，書桌不該被移動"
    assert verify_special_constraints(items, req)["desk_not_back_to_door"] is True
    print("[desk] 側牆的門不觸發背門規則")


def test_unchecked_rules_change_nothing():
    """沒勾選的規則完全不參與——違規擺法原封不動。"""
    req = _req([])
    items = [
        FurnitureItem("stove_1", "stove", 0.46, 0.04, 0.13, 0.08),
        FurnitureItem("desk_1", "desk", 0.42, 0.03, 0.16, 0.09),
    ]
    before = _xy(items)
    items = apply_special_layout_constraints(items, req)
    assert _xy(items) == before, "沒勾選卻動了家具"
    assert verify_special_constraints(items, req) == {}
    print("[off] 未勾選時座標不變")


def test_unsatisfiable_case_is_reported_not_faked():
    """門寬到整個房間都在視線帶上時，保持原位並回報未滿足——不硬塞進牆。"""
    wide = {"x": 0.05, "y": 1.0, "w": 0.90, "h": 0.02}
    req = _req(["door_not_facing_stove"], doors=[wide])
    items = [FurnitureItem("stove_1", "stove", 0.40, 0.04, 0.13, 0.08)]
    items = apply_special_layout_constraints(items, req)
    assert items[0].x == 0.40, "無解時不該亂移"
    assert verify_special_constraints(items, req)["door_not_facing_stove"] is False
    print("[infeasible] 無解時如實回報，未偽裝成合規")


def test_free_text_labels_reach_the_controlled_types():
    """LLM 會自由命名；對不到 stove/toilet 的話這兩條規則永遠不會觸發。"""
    cases = {
        "cooktop": "stove", "gas_stove": "stove", "hob": "stove", "oven": "stove",
        "wc": "toilet", "water_closet": "toilet", "lavatory": "toilet",
        "toilet": "toilet", "stove": "stove",
    }
    for raw, expected in cases.items():
        got = _normalize_ftype(raw)
        assert got == expected, f"{raw}: 預期 {expected}，得到 {got}"
    print(f"[types] {len(cases)} 個自由標籤都收斂到受控詞彙")



def test_bed_head_is_slid_off_the_window():
    """床頭不靠窗：床貼遠牆、窗也在遠牆且重疊 → 沿牆滑到實牆段。"""
    req = _req(["bed_head_not_under_window"])
    items = [FurnitureItem("bed_1", "bed", 0.42, 0.02, 0.22, 0.28)]
    assert verify_special_constraints(items, req)["bed_head_not_under_window"] is False

    items = apply_special_layout_constraints(items, req)
    assert verify_special_constraints(items, req)["bed_head_not_under_window"] is True
    bed = items[0]
    # 窗帶是 x∈[0.38, 0.62]（窗 0.4–0.6 各加 margin 0.02）
    assert bed.x >= 0.62 or bed.x + bed.w <= 0.38, f"bed x={bed.x}"
    assert bed.y == 0.02, "床頭規則只沿牆滑，不該把床推離牆面"
    print(f"[bed-head] x 0.42 → {bed.x:.2f}，床頭離開窗下")


def test_bed_in_the_middle_of_the_room_has_no_headboard_wall():
    """沒貼牆的床沒有「床頭靠牆」可言——規則不該把它硬拉到牆邊。"""
    req = _req(["bed_head_not_under_window"])
    items = [FurnitureItem("bed_1", "bed", 0.42, 0.35, 0.22, 0.28)]
    before = _xy(items)
    items = apply_special_layout_constraints(items, req)
    assert _xy(items) == before, "置中的床被動了"
    assert verify_special_constraints(items, req)["bed_head_not_under_window"] is True
    print("[bed-head] 置中的床不觸發靠牆規則")


def test_mirror_reflecting_the_bed_moves_the_bed():
    """鏡不照床：移動的是床，不是掛在牆上的鏡子。"""
    req = _req(["mirror_not_facing_bed"])
    mirror = FurnitureItem("mirror_1", "mirror", 0.0, 0.40, 0.03, 0.12)
    bed = FurnitureItem("bed_1", "bed", 0.30, 0.42, 0.22, 0.28)
    items = [mirror, bed]
    assert verify_special_constraints(items, req)["mirror_not_facing_bed"] is False

    items = apply_special_layout_constraints(items, req)
    assert verify_special_constraints(items, req)["mirror_not_facing_bed"] is True
    assert (mirror.x, mirror.y) == (0.0, 0.40), "鏡子掛在牆上，不該被搬走"
    # 鏡帶是 y∈[0.37, 0.55]（鏡 0.40–0.52 各加 margin 0.03）
    assert bed.y >= 0.55 or bed.y + bed.h <= 0.37, f"bed y={bed.y}"
    print(f"[mirror] 床 y 0.42 → {bed.y:.2f}，離開鏡面正對方向")


def test_stove_and_sink_are_pushed_apart():
    """水火不相容：跨組配對推開到 min_gap，組內配對不受影響。"""
    req = _req(["stove_away_from_water"])
    stove = FurnitureItem("stove_1", "stove", 0.20, 0.05, 0.13, 0.08)
    sink = FurnitureItem("sink_1", "sink", 0.30, 0.05, 0.10, 0.08)
    cabinet = FurnitureItem("cabinet_1", "cabinet", 0.60, 0.05, 0.14, 0.07)
    items = [stove, sink, cabinet]
    assert verify_special_constraints(items, req)["stove_away_from_water"] is False

    items = apply_special_layout_constraints(items, req)
    assert verify_special_constraints(items, req)["stove_away_from_water"] is True
    gap = max(stove.x - (sink.x + sink.w), sink.x - (stove.x + stove.w))
    assert gap >= 0.12 - 1e-6, f"爐灶與水槽只隔 {gap:.3f}"
    assert (cabinet.x, cabinet.y) == (0.60, 0.05), "沒被規則指名的櫥櫃不該被動到"
    print(f"[水火] 爐灶／水槽間距 {gap:.2f}")


def test_straight_through_draft_gets_a_screen():
    """穿堂煞：門與對牆的窗成一線時，把一件家具搬到直通帶上當屏風。"""
    req = _req(["door_not_facing_window"])
    cabinet = FurnitureItem("cabinet_1", "cabinet", 0.05, 0.04, 0.14, 0.07)
    items = [cabinet]
    assert verify_special_constraints(items, req)["door_not_facing_window"] is False

    items = apply_special_layout_constraints(items, req)
    assert verify_special_constraints(items, req)["door_not_facing_window"] is True
    # 直通帶是門（x 0.45–0.55）與窗（x 0.4–0.6）的交集，各加 margin 0.03 → [0.42, 0.58]
    assert cabinet.x + cabinet.w > 0.42 and cabinet.x < 0.58, f"cabinet x={cabinet.x}"
    print(f"[穿堂] 櫥櫃移到 ({cabinet.x:.2f}, {cabinet.y:.2f}) 擋住直通線")


def test_no_blocker_in_the_room_is_not_faked_into_a_screen():
    """房間裡沒有可當屏風的家具時，這條規則無從施力，不該硬搬別的東西充數。"""
    req = _req(["door_not_facing_window"])
    items = [FurnitureItem("rug_1", "rug", 0.30, 0.30, 0.32, 0.22)]
    before = _xy(items)
    items = apply_special_layout_constraints(items, req)
    assert _xy(items) == before, "地毯被當成屏風搬走了"
    print("[穿堂] 沒有可用屏風時維持原樣")


def test_window_on_a_side_wall_is_not_a_straight_through():
    """門在近牆、窗在左牆時兩者不成一線——不該無中生有搬一件家具去擋。"""
    req = _req(["door_not_facing_window"])
    req["space_info"]["windows"] = [{"x": 0.0, "y": 0.40, "w": 0.02, "h": 0.20}]
    items = [FurnitureItem("cabinet_1", "cabinet", 0.05, 0.04, 0.14, 0.07)]
    before = _xy(items)
    items = apply_special_layout_constraints(items, req)
    assert _xy(items) == before, "門窗不在對牆卻被判成穿堂"
    assert verify_special_constraints(items, req)["door_not_facing_window"] is True
    print("[穿堂] 側牆的窗不構成穿堂煞")


def test_new_types_reach_the_controlled_vocabulary():
    """新增的風水標的（鏡／水槽／冰箱）也要收斂得到，否則規則永遠不會觸發。"""
    cases = {
        "wall_mirror": "mirror", "full_length_mirror": "mirror", "looking_glass": "mirror",
        "kitchen_sink": "sink", "washbasin": "sink", "wash_basin": "sink",
        "refrigerator": "fridge", "freezer": "fridge", "fridge": "fridge",
    }
    for raw, expected in cases.items():
        got = _normalize_ftype(raw)
        assert got == expected, f"{raw}: 預期 {expected}，得到 {got}"
    print(f"[types] {len(cases)} 個新標的都收斂到受控詞彙")


if __name__ == "__main__":
    for fn in list(globals().values()):
        if callable(fn) and getattr(fn, "__name__", "").startswith("test_"):
            fn()
    print("\nALL FENGSHUI CONSTRAINT CHECKS PASSED ✅")
