"""佈局檢查 agent：有問題才交回 LLM，LLM 可選擇重排或保留，重排變差就不採用。"""

from __future__ import annotations

import pytest

from designbridge.core.config import Config
from designbridge.layout import layout_agent, layout_review
from designbridge.layout.layout_items import FurnitureItem

REQ = {
    "meta": {"room_type": "living_room"},
    "space_info": {"estimated_size": {"width": 4.5, "depth": 4.0},
                   "doors": [{"wall": "near", "x": 0.45, "y": 0.98, "w": 0.10, "h": 0.02}]},
    "layout_constraints": {},
    "design_description": "living room",
}


def _draft() -> list[FurnitureItem]:
    return [
        FurnitureItem("sofa_1", "sofa", 0.30, 0.55, 0.30, 0.13),
        FurnitureItem("cabinet_1", "cabinet", 0.40, 0.80, 0.14, 0.07),
    ]


def _fake_review(items, *_args):
    """每個 cabinet 算一個擋門問題。"""
    return [{"kind": "動線", "severity": 3, "message": "門口被擋住", "remedy": "移開",
             "offenders": [it.id]} for it in items if it.type == "cabinet"]


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setattr(Config, "LAYOUT_REVIEW_AGENT", True)
    monkeypatch.setattr(Config, "ENABLE_PRODUCT_MESHES", False)
    monkeypatch.setattr(layout_review, "review_layout", _fake_review)
    monkeypatch.setattr(layout_agent, "_call_llm_layout", lambda prompt: _draft())
    prompts: list[str] = []

    def _run(verdict):
        def fake_llm(prompt):
            prompts.append(prompt)
            if isinstance(verdict, Exception):
                raise verdict
            return verdict
        monkeypatch.setattr(layout_agent, "_call_llm_review", fake_llm)
        out = layout_agent.run_layout_agent(dict(REQ), task_id="test_review")
        types = [p["type"] for p in out["scene_graph"]["furniture_placements"]]
        return types, out["intermediate_outputs"]["layout_agent"]["review"], prompts
    return _run


def test_revise_that_fixes_issues_is_accepted(run):
    sofa_only = {"decision": "revise", "reason": "櫃子擋門，移除", "items": _draft()[:1]}
    types, review, prompts = run(sofa_only)
    assert "門口被擋住" in prompts[0], "報告要交給 LLM"
    assert review["accepted"] and review["issues_after"] == []
    assert "cabinet" not in types


def test_keep_leaves_layout_untouched(run):
    types, review, _ = run({"decision": "keep", "reason": "使用者指定", "items": []})
    assert review["decision"] == "keep" and not review["accepted"]
    assert "cabinet" in types


def test_worse_revision_is_rejected(run):
    worse = _draft() + [FurnitureItem("cabinet_2", "cabinet", 0.70, 0.10, 0.14, 0.07)]
    types, review, _ = run({"decision": "revise", "reason": "", "items": worse})
    assert not review["accepted"]
    assert types.count("cabinet") == 1


def test_llm_failure_falls_back(run):
    types, review, _ = run(RuntimeError("quota"))
    assert review["decision"] == "error" and "cabinet" in types


def test_no_issues_skips_llm(run, monkeypatch):
    monkeypatch.setattr(layout_review, "review_layout", lambda *a: [])
    _, review, prompts = run({"decision": "keep", "reason": "", "items": []})
    assert prompts == [] and review["decision"] == "pass"


def test_real_report_lists_fengshui_and_circulation():
    req = {"space_info": {"doors": [{"x": 0.45, "y": 0.98, "w": 0.10, "h": 0.02}],
                          "windows": [{"x": 0.40, "y": 0.0, "w": 0.20, "h": 0.02}]},
           "special_constraints": {"door_not_facing_bed": True}}
    items = [FurnitureItem("bed_1", "bed", 0.39, 0.05, 0.22, 0.40),
             FurnitureItem("cabinet_1", "cabinet", 0.42, 0.85, 0.16, 0.12)]
    issues = layout_review.review_layout(items, req, 4.0, 3.2)
    assert {i["kind"] for i in issues} == {"風水", "動線"}
    text = layout_review.format_issues(issues)
    assert "bed_1" in text and "cabinet_1" in text
