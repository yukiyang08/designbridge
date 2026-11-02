"""浴室／陽台：設備不能被收斂成不明方塊，生圖 prompt 不能帶客廳的 sofa/legs／天花板字眼。"""

import importlib

import pytest
from PIL import Image

from designbridge.core.config import Config
from designbridge.layout import condition_prefetch
from designbridge.layout.layout_items import _normalize_ftype

rn = importlib.import_module("designbridge.core.nodes.renderer")


@pytest.mark.parametrize("raw,want", [
    ("bathtub", "bathtub"), ("freestanding_bathtub", "bathtub"),
    ("shower_stall", "shower"), ("vanity", "sink"), ("vanity_mirror", "mirror"),
    ("washing_machine", "washer"), ("clothes_rack", "drying_rack"), ("hair_dryer", "default"),
    ("shoe_rack", "shoe_cabinet"), ("shoe_cabinet", "shoe_cabinet"),
])
def test_bathroom_fixtures_normalize(raw, want):
    assert _normalize_ftype(raw) == want


@pytest.mark.parametrize("ftype,room_type,want", [
    ("bathtub", None, "sanitary ware"),
    ("washer", None, "balcony"),
    ("sofa", "balcony", "balcony"),   # LLM 判斷的房型優先
    ("stove", None, "countertop"),
    ("fridge", "kitchen", "countertop"),
    ("shoe_cabinet", None, "foyer"),
    ("sofa", "circulation", "foyer"),   # 平面圖解析給的字彙
    ("sofa", None, "nothing draped on the sofa"),
])
def test_layout_prompt_follows_room(tmp_path, monkeypatch, ftype, room_type, want):
    depth = tmp_path / "d.png"
    Image.new("L", (64, 48), 128).save(depth)
    monkeypatch.setattr(Config, "ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "FAL_KEY", "x")
    monkeypatch.setattr(Config, "USE_MODAL_GPU", False)
    monkeypatch.setattr(Config, "ENABLE_PRODUCT_MESHES", False)
    monkeypatch.setattr(rn, "resolve_style_loras", lambda *_: [])
    monkeypatch.setattr(condition_prefetch, "get_conditions",
                        lambda *a, **k: {"camera": {}, "edge_path": None, "depth_path": str(depth)})
    seen = {}
    monkeypatch.setattr(rn, "_render_flux_depth_controlnet_fal",
                        lambda prompt, *a, **k: seen.setdefault("prompt", prompt) and True)
    rn.renderer({"task_id": "t", "composed_prompt": "a room", "user_input": {},
                 "structured_requirement": {"meta": {"room_type": room_type}},
                 "scene_graph": {"furniture_placements": [{"type": ftype, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.1}]}})
    assert want in seen["prompt"]
    assert ("nothing draped on the sofa" in seen["prompt"]) is want.startswith("nothing")
