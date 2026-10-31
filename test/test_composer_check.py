from designbridge.core.nodes.composer import check_prompt


def test_check_prompt():
    pl = [{"type": "sofa"}, {"type": "bed"}]
    assert check_prompt("a leather sofa and a wooden bed by the window", pl) == []
    assert any("bed" in i for i in check_prompt("a leather sofa near the window", pl))
    assert check_prompt("sofa bed, per the user", pl)


def test_composer_asks_ra(monkeypatch):
    import json
    from designbridge.core.nodes import composer, requirement

    replies = iter([
        json.dumps({"prompt": "a sofa", "ra_issue": "原話要輕奢，描述寫工業風"}),
        "輕奢風客廳",                                   # revise_requirement
        json.dumps({"prompt": "a luxe sofa in a light-luxury room", "ra_issue": None}),
    ])
    monkeypatch.setattr("designbridge.render.llm.call_llm", lambda *a, **k: next(replies))
    state = {
        "structured_requirement": {"design_description": "工業風客廳"},
        "style_params": {"style_prompt": "loft", "style_profile_id": "industrial"},
        "scene_graph": {"furniture_placements": [{"type": "sofa"}]},
        "user_input": {"text_prompt": "輕奢客廳"},
    }
    out = composer.composer_node(state)
    assert out["structured_requirement"]["design_description"] == "輕奢風客廳"
    assert "luxe" in out["composed_prompt"]
    assert out["intermediate_outputs"]["composer"]["ra_issue"]


def test_composer_asks_layout(monkeypatch):
    import json
    from designbridge.core.nodes import composer

    replies = iter([
        json.dumps({"prompt": "a sofa", "layout_issue": "原話要兩張沙發，佈局只有一張"}),
        json.dumps({"prompt": "two sofas facing each other", "layout_issue": None}),
    ])
    monkeypatch.setattr("designbridge.render.llm.call_llm", lambda *a, **k: next(replies))
    new_sg = {"furniture_placements": [{"type": "sofa", "x": .1, "y": .3, "w": .3, "h": .2},
                                       {"type": "sofa", "x": .5, "y": .3, "w": .3, "h": .2}]}
    seen = {}
    monkeypatch.setattr("designbridge.core.nodes.layout_and_style.replan_layout",
                        lambda st, req, hint: seen.setdefault("hint", hint) and new_sg)
    state = {
        "structured_requirement": {"design_description": "客廳"},
        "style_params": {"style_prompt": "warm"},
        "scene_graph": {"furniture_placements": [{"type": "sofa", "x": .1, "y": .3, "w": .3, "h": .2}]},
        "user_input": {"text_prompt": "兩張沙發的客廳"},
        "intermediate_outputs": {"layout_and_style_agent": {"layout": "ok"}},
    }
    out = composer.composer_node(state)
    assert out["scene_graph"] is new_sg and "兩張" in seen["hint"]
    assert "two sofas" in out["composed_prompt"]
    # Step 1 使用者確認過的佈局（layout != ok）不重排
    seen.clear()
    replies = iter([json.dumps({"prompt": "a sofa", "layout_issue": "x"})] )
    monkeypatch.setattr("designbridge.render.llm.call_llm", lambda *a, **k: next(replies))
    state["intermediate_outputs"] = {"layout_and_style_agent": {"layout": "reused_from_step1"}}
    assert "scene_graph" not in composer.composer_node(state) and not seen


def test_check_prompt_multiword_type():
    assert check_prompt("a media console with a wall-mounted TV", [{"type": "tv_unit"}]) == []


def test_visible_placements_drops_out_of_frame(monkeypatch):
    import sys

    from designbridge.core.nodes import composer

    # nodes/__init__ 把 renderer 函式蓋在同名子模組上，所以直接取 sys.modules
    monkeypatch.setattr(sys.modules["designbridge.core.nodes.renderer"], "_projection_instances", lambda _p: [
        {"type": "sofa", "visible": True}, {"type": "bookshelf", "visible": False}])
    sg = {"projected_depth_path": "x.png",
          "furniture_placements": [{"type": "sofa"}, {"type": "bookshelf"}]}
    assert [p["type"] for p in composer._visible_placements(sg)] == ["sofa"]
    # 沒有投影資訊時維持原行為
    assert len(composer._visible_placements({"furniture_placements": [{"type": "sofa"}, {"type": "bookshelf"}]})) == 2
