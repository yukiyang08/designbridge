"""設計路由決策（DB-F-004）的規則層：refine_mode 優先、LLM 失敗或回傳不合法值時預設走新設計。
離線，LLM 以假函式取代。"""
import json

import pytest

from designbridge.core import graph
from designbridge.core.nodes import requirement as ra


def _req():
    return {"user_description_raw": "x", "design_description": "x", "meta": {"room_type": "living_room"},
            "space_info": {"estimated_size": {"width": 5.0, "height": 3.0, "depth": 4.0}, "windows": [], "doors": []}}


def _fake_ra(decision):
    def fake(text_prompt, initial_image, style_reference_image=""):
        r = _req()
        if decision is not None:
            r["_routing_decision"] = decision
        return r
    return fake


def _route(monkeypatch, state, decision):
    monkeypatch.setattr(ra, "_call_llm_requirement_analyzer", _fake_ra(decision))
    return ra.requirement_analyzer(state)["routing_decision"]


def test_refine_mode_always_routes_to_adjuster(monkeypatch):
    state = {"user_input": {"text_prompt": "全新設計一個北歐風客廳", "refine_mode": True}}
    assert _route(monkeypatch, state, "design") == "design_adjuster"   # 即使 LLM 判成新設計


def test_llm_decision_is_used_without_refine_mode(monkeypatch):
    assert _route(monkeypatch, {"user_input": {"text_prompt": "把沙發換成綠色"}}, "design_adjuster") == "design_adjuster"
    assert _route(monkeypatch, {"user_input": {"text_prompt": "設計北歐風客廳"}}, "design") == "design"


def test_llm_failure_defaults_to_new_design(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(ra, "_call_llm_requirement_analyzer", boom)
    out = ra.requirement_analyzer({"user_input": {"text_prompt": "把沙發換成綠色"}})
    assert out["routing_decision"] == "design"


def test_missing_decision_defaults_to_new_design(monkeypatch):
    assert _route(monkeypatch, {"user_input": {"text_prompt": "x"}}, None) == "design"


def test_invalid_llm_value_defaults_to_new_design(monkeypatch):
    payload = json.dumps({"routing_decision": "do_something_else", "structured_requirement": _req()})
    monkeypatch.setattr("designbridge.render.llm.call_llm", lambda *a, **k: payload)
    out = ra.requirement_analyzer({"user_input": {"text_prompt": "x"}})
    assert out["routing_decision"] == "design"


def test_existing_requirement_is_reused_and_refine_mode_still_wins(monkeypatch):
    def must_not_call(*a, **k):
        raise AssertionError("已有 structured_requirement 不該再呼叫 LLM")
    monkeypatch.setattr(ra, "_call_llm_requirement_analyzer", must_not_call)
    state = {"structured_requirement": _req(), "user_input": {"refine_mode": True}}
    assert ra.requirement_analyzer(state)["routing_decision"] == "design_adjuster"
    state = {"structured_requirement": _req(), "user_input": {}}
    assert ra.requirement_analyzer(state)["routing_decision"] == "design"


@pytest.mark.parametrize("decision,node", [
    ("design_adjuster", "adjuster_agent"),
    ("design", "layout_and_style_agent"),
    (None, "layout_and_style_agent"),
    ("unknown", "layout_and_style_agent"),
])
def test_graph_maps_decision_to_node(decision, node):
    assert graph._route_after_requirement({"routing_decision": decision}) == node
