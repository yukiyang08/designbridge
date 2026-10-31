"""入口二（照片 → 偵測家具 → 改佈局 → 生圖）的後端接線。離線：Gemini、視覺模型、投影都用假函式。"""
import pytest
from fastapi import HTTPException

import designbridge.core.nodes as nodes
import designbridge.layout.layout_agent as layout_agent
import designbridge.layout.photo_fengshui as photo_fengshui
import designbridge.layout.projected_depth as projected_depth
import routers.floorplan as floorplan
from designbridge.core.nodes import layout_and_style as las
from designbridge.core.nodes import requirement as ra
from designbridge.core.nodes.renderer import _wants_projected_depth

_PLAN = {
    "room_type": "living_room", "room_w": 4.2, "room_d": 3.6, "confidence": "high",
    "placements": [{"id": "sofa_1", "type": "sofa", "rotation": 0, "x": 0.2, "y": 0.0, "w": 0.5, "h": 0.25,
                    "image_box": [0.2, 0.4, 0.7, 0.8]}],
    "doors": [{"x": 0.0, "y": 0.4, "w": 0.02, "h": 0.2, "wall": "left", "assumed": False}],
    "windows": [{"x": 0.3, "y": 0.0, "w": 0.4, "h": 0.02, "wall": "far", "assumed": False}],
}
_VISION = {"depth": "artifacts/vision/d.png", "segmentation": "artifacts/vision/s.png",
           "segmentation_meta": "artifacts/vision/s.json"}


@pytest.fixture
def no_file_check(monkeypatch):
    monkeypatch.setattr(floorplan, "_require_artifact_file", lambda *a, **k: None)


def test_photo_layout_returns_editable_scene_graph_and_vision(monkeypatch, no_file_check):
    seen = {}
    monkeypatch.setattr(photo_fengshui, "parse_room_photo", lambda path, rt=None: seen.setdefault("plan", (path, rt)) and _PLAN)
    monkeypatch.setattr(nodes, "visual_preprocessing_local",
                        lambda st: seen.setdefault("vision", st["user_input"]["initial_image"]) and {"vision_features": _VISION})

    out = floorplan.photo_layout(floorplan.PhotoLayoutRequest(image_path="artifacts/uploads/a.jpg", room_type="bedroom"), user_id="")

    assert seen == {"plan": ("artifacts/uploads/a.jpg", "bedroom"), "vision": "artifacts/uploads/a.jpg"}
    sg = out["scene_graph"]
    assert sg["source"] == "photo"
    assert sg["furniture_placements"][0]["image_box"] == [0.2, 0.4, 0.7, 0.8]
    assert (sg["room_w"], sg["room_d"], sg["room_type"]) == (4.2, 3.6, "living_room")
    assert sg["doors"] == _PLAN["doors"] and sg["windows"] == _PLAN["windows"]
    assert out["vision_features"] == _VISION


def test_photo_layout_422_when_nothing_detected(monkeypatch, no_file_check):
    monkeypatch.setattr(photo_fengshui, "parse_room_photo", lambda *a: None)
    monkeypatch.setattr(nodes, "visual_preprocessing_local", lambda st: {})
    with pytest.raises(HTTPException) as e:
        floorplan.photo_layout(floorplan.PhotoLayoutRequest(image_path="artifacts/uploads/a.jpg"), user_id="")
    assert e.value.status_code == 422


def _capture_layout_agent(monkeypatch):
    seen = {}

    def fake(req, task_id, **kw):
        seen["space_info"] = req["space_info"]
        return {"scene_graph": {"furniture_placements": []}}
    monkeypatch.setattr(layout_agent, "run_layout_agent", fake)
    return seen


def test_auto_relayout_uses_detected_openings(monkeypatch):
    seen = _capture_layout_agent(monkeypatch)
    floorplan.generate_layout(floorplan.LayoutRequest(
        room_w=4.2, room_d=3.6, furniture_list=["sofa"], doors=_PLAN["doors"], windows=_PLAN["windows"],
    ), user_id="")
    assert seen["space_info"]["doors"] == _PLAN["doors"]
    assert seen["space_info"]["windows"] == _PLAN["windows"]


def test_auto_relayout_keeps_default_openings_without_photo(monkeypatch):
    seen = _capture_layout_agent(monkeypatch)
    floorplan.generate_layout(floorplan.LayoutRequest(room_w=4.0, room_d=3.0), user_id="")
    assert seen["space_info"]["windows"][0]["y"] == 0.0 and seen["space_info"]["doors"][0]["y"] == 1.0


def _capture_projection(monkeypatch):
    seen = {}

    def fake(items, space_info, task_id, **kw):
        seen.update(kw, space_info=space_info, items=items)
        return "d.png", "s.png", "photo_anchored"
    monkeypatch.setattr(projected_depth, "_generate_projected_depth", fake)
    monkeypatch.setattr(projected_depth, "_generate_floor_plan", lambda *a, **k: "fp.png")
    monkeypatch.setattr(projected_depth.Config, "ENABLE_PRODUCT_MESHES", False)
    return seen


def test_reproject_passes_photo_and_room_size(monkeypatch):
    seen = _capture_projection(monkeypatch)
    sg = {"source": "photo", "room_w": 4.2, "room_d": 3.6, "furniture_placements": _PLAN["placements"]}
    out = projected_depth.reproject_scene_graph(sg, {}, "t", (1024, 768), vision_features=_VISION, photo_path="p.jpg")

    assert seen["vision_features"] == _VISION and seen["photo_path"] == "p.jpg"
    assert seen["space_info"]["estimated_size"] == {"width": 4.2, "depth": 3.6}
    assert out["projection_mode"] == "photo_anchored" and out["source"] == "photo"


def test_reproject_without_photo_unchanged(monkeypatch):
    seen = _capture_projection(monkeypatch)
    projected_depth.reproject_scene_graph({"furniture_placements": []}, {"a": 1}, "t")
    assert seen["vision_features"] is None and seen["space_info"] == {"a": 1}


@pytest.mark.parametrize("vision,anchored", [
    (_VISION, True),
    ({**_VISION, "depth_source": "post_estimate"}, False),   # 上一張生成圖的估計深度，不是照片
    ({}, False),
])
def test_layout_node_reprojects_onto_photo_only_with_real_photo_depth(monkeypatch, vision, anchored):
    seen = {}

    def fake_reproject(sg, space_info, task_id, output_size, **kw):
        seen.update(kw)
        return sg
    monkeypatch.setattr(projected_depth, "reproject_scene_graph", fake_reproject)
    monkeypatch.setattr(las, "build_style_params", lambda *a: {})
    las.layout_and_style_agent_stub({
        "structured_requirement": {}, "style_params": {"style_profile_id": "x"},
        "user_input": {"initial_image": "p.jpg"}, "vision_features": vision,
        "scene_graph": {"source": "photo", "furniture_placements": []},
    })
    assert (seen["vision_features"] is not None) == anchored
    assert seen["photo_path"] == ("p.jpg" if anchored else None)


def test_renderer_uses_projected_depth_for_photo_layout():
    assert _wants_projected_depth({}, {"source": "photo"})
    assert _wants_projected_depth({"hint_layout": True}, {})
    assert not _wants_projected_depth({}, {"furniture_placements": []})


def test_photo_layout_always_routes_to_full_design(monkeypatch):
    def fake(text_prompt, initial_image, style_reference_image=""):
        return {"design_description": "x", "meta": {}, "_routing_decision": "design_adjuster"}
    monkeypatch.setattr(ra, "_call_llm_requirement_analyzer", fake)
    state = {"user_input": {"text_prompt": "北歐風", "initial_image": "p.jpg"}, "scene_graph": {"source": "photo"}}
    assert ra.requirement_analyzer(state)["routing_decision"] == "design"


@pytest.mark.parametrize("raw,want", [
    ([0.2, 0.4, 0.7, 0.8], [0.2, 0.4, 0.7, 0.8]),
    ([0.0, 6.72, 0.55, 1.0], [0.0, 0.672, 0.55, 1.0]),     # 漏小數點
    ([200, 400, 700, 800], [0.2, 0.4, 0.7, 0.8]),          # 0–1000 刻度
    ([0.7, 0.8, 0.2, 0.4], [0.2, 0.4, 0.7, 0.8]),          # 角點顛倒
    ([0.5, 1.0, 0.6, 1.0], None),                          # 面積為零
    (["x", 0, 1, 1], None),
])
def test_photo_box_repairs_gemini_quirks(raw, want):
    got = photo_fengshui._box(raw)
    assert got == want if want is None else got == pytest.approx(want)
