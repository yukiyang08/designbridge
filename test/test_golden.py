"""黃金樣本：重構前後的行為快照（離線，不呼叫任何外部 API）。

比對 renderer 的後端選擇與參數、layout agent 的家具座標與分數。
行為「刻意」改變時，重新產生快照：
    GOLDEN_UPDATE=1 python -m pytest test/test_golden.py -q
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from designbridge.core.config import Config
import importlib
from designbridge.layout import layout_agent
from designbridge.layout.layout_items import FurnitureItem

# nodes/__init__ 以同名函式覆蓋了模組屬性，要用 importlib 取模組
renderer_mod = importlib.import_module("designbridge.core.nodes.renderer")

GOLDEN = Path(__file__).parent / "golden" / "snapshot.json"
_TMP = Path(tempfile.mkdtemp(prefix="golden_"))
Config.ARTIFACTS_DIR = str(_TMP)
Config.FAL_KEY = "fake"
Config.HF_TOKEN = "fake"
Config.ENABLE_HF_INFERENCE = True
Config.ENABLE_LAYOUT_CONTROLNET = True
Config.ENABLE_LAYOUT_DEPTH_PROJECTION = True

_BACKENDS = {
    "_render_hf_inference": "hf_inference",
    "_render_hf_kontext": "hf_kontext",
    "_render_flux_controlnet_depth_fal": "flux_controlnet_depth_fal",
    "_render_flux_depth_controlnet_fal": "flux_depth_controlnet_fal",
    "_render_flux_img2img_fal": "flux_img2img_fal",
    "_render_flux_fal": "flux_fal",
}


def _clean(v):
    if isinstance(v, (str, Path)) and (os.sep in str(v) or "/" in str(v)) and len(str(v)) > 40:
        return "<path>"
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    return v


def _run_renderer(state: dict, succeed: set[str]) -> dict:
    """假後端：記錄呼叫順序與參數，只有 succeed 內的後端回傳成功。"""
    calls: list[dict] = []
    originals = {n: getattr(renderer_mod, n) for n in _BACKENDS}

    def make(name):
        def fake(*args, **kwargs):
            kw = {k: _clean(v) for k, v in kwargs.items() if k not in ("seed", "out_path")}
            calls.append({"backend": _BACKENDS[name], "kwargs": kw})
            return _BACKENDS[name] in succeed
        return fake

    for n in _BACKENDS:
        setattr(renderer_mod, n, make(n))
    try:
        out = renderer_mod.renderer(state)
    finally:
        for n, f in originals.items():
            setattr(renderer_mod, n, f)
    gp = out["render_result"]["generation_params"]
    gp = {k: _clean(v) for k, v in gp.items() if k not in ("seed", "prompt_preview")}
    return {
        "calls": calls,
        "backend": gp.pop("backend"),
        "params": gp,
        "prompt": out["render_result"]["generation_params"]["prompt_preview"],
        "controlnet_inputs": sorted((out["render_result"].get("controlnet_inputs") or {}).keys()),
    }


def _state(**over) -> dict:
    base = {
        "task_id": "golden",
        "structured_requirement": {
            "design_description": "a cozy modern living room with warm wood tones",
            "space_info": {"estimated_size": {"width": 4.5, "depth": 3.5}},
            "meta": {"room_type": "living_room"},
        },
        "user_input": {"text_prompt": "modern living room"},
    }
    base.update(over)
    return base


def _depth_png() -> str:
    p = _TMP / "depth.png"
    if not p.exists():
        Image.linear_gradient("L").resize((64, 48)).save(p)
    return str(p)


def _placements() -> list[dict]:
    return [
        {"id": "sofa_1", "type": "sofa", "x": 0.30, "y": 0.60, "w": 0.30, "h": 0.13},
        {"id": "table_1", "type": "coffee_table", "x": 0.38, "y": 0.42, "w": 0.15, "h": 0.10},
        {"id": "tv_1", "type": "tv_unit", "x": 0.39, "y": 0.04, "w": 0.22, "h": 0.07},
    ]


def renderer_snapshot() -> dict:
    ALL = set(_BACKENDS.values())
    layout_state = _state(
        structured_requirement={**_state()["structured_requirement"], "hint_layout": True},
        scene_graph={"furniture_placements": _placements(), "room_w": 4.5, "room_d": 3.5},
    )
    photo_state = _state(vision_features={"depth": _depth_png()})
    return {
        "text_all_ok": _run_renderer(_state(), ALL),
        "text_hf_fails": _run_renderer(_state(), ALL - {"hf_inference"}),
        "text_all_fail": _run_renderer(_state(), set()),
        "photo_depth_all_ok": _run_renderer(photo_state, ALL),
        "photo_depth_controlnet_fails": _run_renderer(photo_state, ALL - {"flux_controlnet_depth_fal"}),
        "layout_no_depth_all_ok": _run_renderer(layout_state, ALL),
    }


def layout_snapshot() -> dict:
    items = [
        FurnitureItem("bed_1", "bed", 0.35, 0.05, 0.22, 0.28),
        FurnitureItem("wardrobe_1", "wardrobe", 0.02, 0.40, 0.18, 0.08),
        FurnitureItem("desk_1", "desk", 0.70, 0.55, 0.16, 0.09),
        FurnitureItem("nightstand_1", "nightstand", 0.30, 0.10, 0.07, 0.07),
    ]
    original = layout_agent._call_llm_layout
    layout_agent._call_llm_layout = lambda prompt: [FurnitureItem(**i.__dict__) for i in items]
    try:
        req = {
            "meta": {"room_type": "bedroom"},
            "space_info": {
                "estimated_size": {"width": 4.0, "depth": 3.5},
                "windows": [{"wall": "far", "x": 0.4, "y": 0.0, "w": 0.3, "h": 0.05}],
                "doors": [{"wall": "near", "x": 0.1, "y": 0.95, "w": 0.15, "h": 0.05}],
            },
            "layout_constraints": {},
            "design_description": "a quiet bedroom",
        }
        out = layout_agent.run_layout_agent(req, task_id="golden_layout")
    finally:
        layout_agent._call_llm_layout = original
    sg = out["scene_graph"]
    return {
        "placements": sg["furniture_placements"],
        "soft_scores": _clean(sg["soft_constraint_scores"]),
        "weighted_score": _clean(sg["weighted_score"]),
        "constraints_met": _clean(sg["layout_constraints_met"]),
        "feasible": sg["feasible"],
        "layout_prompt": sg["layout_prompt"],
        "projection_mode": sg["projection_mode"],
    }


def snapshot() -> dict:
    return {"renderer": renderer_snapshot(), "layout": layout_snapshot()}


def test_golden():
    cur = json.loads(json.dumps(snapshot(), ensure_ascii=False))
    if os.getenv("GOLDEN_UPDATE") or not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(cur, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return
    old = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for section in cur:
        for key in cur[section]:
            assert cur[section][key] == old[section][key], f"{section}.{key} 與黃金樣本不同"


if __name__ == "__main__":
    test_golden()
    print("ok")
