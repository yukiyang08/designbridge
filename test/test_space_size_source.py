"""房間尺寸來源：前端靠 size_source 標出尺寸是 AI 估的還是預設值。"""

from __future__ import annotations

from designbridge.core.nodes.requirement import _normalize_space_info


def _source(space_info: dict | None) -> str:
    req = {} if space_info is None else {"space_info": space_info}
    _normalize_space_info(req)
    return req["space_info"]["size_source"]


def test_ai_estimate_is_marked_ai():
    assert _source({"estimated_size": {"width": 3.6, "depth": 4.2}}) == "ai"


def test_missing_size_is_marked_default():
    assert _source(None) == "default"
    assert _source({"estimated_size": {"width": 0, "depth": 4.0}}) == "default"


def test_copied_prompt_example_is_marked_default():
    assert _source({"estimated_size": {"width": 5.0, "height": 2.8, "depth": 4.0}}) == "default"


def test_existing_source_is_kept():
    assert _source({"estimated_size": {"width": 5.0, "depth": 4.0}, "size_source": "user"}) == "user"
