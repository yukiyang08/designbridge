"""家具組：餐椅、床頭櫃要跟著主家具走，不能被推擠或優化器拆散。"""

from __future__ import annotations

from designbridge.layout import layout_agent
from designbridge.layout.layout_enforce import _edge_gap
from designbridge.layout.layout_items import FurnitureItem


def _dining() -> list[FurnitureItem]:
    chairs = [FurnitureItem(f"chair_{i}", "chair", x, y, 0.09, 0.08) for i, (x, y) in enumerate(
        [(0.33, 0.35), (0.45, 0.35), (0.57, 0.35), (0.36, 0.69), (0.48, 0.69), (0.60, 0.69)])]
    return [
        FurnitureItem("cabinet_1", "cabinet", 0.25, 0.05, 0.45, 0.12),
        FurnitureItem("bookshelf_1", "bookshelf", 0.05, 0.28, 0.10, 0.58),
        FurnitureItem("dining_table_1", "dining_table", 0.32, 0.44, 0.38, 0.24),
        FurnitureItem("side_table_1", "side_table", 0.80, 0.38, 0.09, 0.10),
        *chairs,
    ]


def _run(items: list[FurnitureItem]) -> list[dict]:
    original = layout_agent._call_llm_layout
    layout_agent._call_llm_layout = lambda prompt: items
    try:
        out = layout_agent.run_layout_agent({
            "meta": {"room_type": "dining_room"},
            "space_info": {"estimated_size": {"width": 4.5, "depth": 4.0},
                           "doors": [{"wall": "near", "x": 0.1, "y": 0.95, "w": 0.15, "h": 0.05}]},
            "layout_constraints": {},
            "design_description": "dining room",
        }, task_id="test_companions")
    finally:
        layout_agent._call_llm_layout = original
    return out["scene_graph"]


def _box(p: dict) -> FurnitureItem:
    return FurnitureItem(p["id"], p["type"], p["x"], p["y"], p["w"], p["h"])


def test_chairs_stay_at_table():
    sg = _run(_dining())
    placed = sg["furniture_placements"]
    table = _box(next(p for p in placed if p["type"] == "dining_table"))
    chairs = [_box(p) for p in placed if p["type"] == "chair"]
    assert len(chairs) == 6
    assert all(_edge_gap(c, table) <= 0.02 for c in chairs)
    assert sg["layout_constraints_met"]["collision_free"]


def test_overlapping_nightstand_is_separated_but_kept_beside_bed():
    sg = _run([
        FurnitureItem("bed_1", "bed", 0.35, 0.05, 0.22, 0.28),
        FurnitureItem("nightstand_1", "nightstand", 0.30, 0.10, 0.07, 0.07),
    ])
    placed = {p["type"]: _box(p) for p in sg["furniture_placements"]}
    assert _edge_gap(placed["nightstand"], placed["bed"]) <= 0.02
    assert sg["layout_constraints_met"]["collision_free"]
