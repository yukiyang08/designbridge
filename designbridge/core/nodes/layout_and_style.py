"""Layout + Style graph node."""

from __future__ import annotations

import uuid
from typing import Any

from designbridge.core.config import Config
from designbridge.core.state import DesignBridgeState
from designbridge.core.timing import timed_call
from designbridge.style.style_apply import build_style_params


def replan_layout(state: DesignBridgeState, req: dict[str, Any], hint: str) -> dict[str, Any] | None:
    """composer 回頭請 layout agent 依提示重排一次；失敗回 None，呼叫端沿用原佈局。"""
    from designbridge.layout.layout_agent import run_layout_agent
    from designbridge.render.render_prompt import _resolve_output_size

    user_input = state.get("user_input") or {}
    try:
        return run_layout_agent(
            req, state.get("task_id") or str(uuid.uuid4()),
            existing_layout=state.get("layout_from_depth"),
            output_size=_resolve_output_size(
                str(user_input.get("output_aspect") or "auto"), user_input.get("initial_image")
            ),
            vision_features=state.get("vision_features"),
            image_path=user_input.get("initial_image"),
            extra_hint=hint,
        ).get("scene_graph")
    except Exception as e:
        print(f"⚠️ [composer] layout replan failed ({e}), keep original layout")
        return None


def layout_and_style_agent_stub(state: DesignBridgeState) -> dict[str, Any]:
    """Layout + style agent.

    Layout planning is only executed when the user explicitly requests spatial reorganization
    (hint_layout=True from LLM semantic analysis) and there isn't already a planned scene_graph.
    Style params are searched independently and exactly once, regardless of which layout branch
    below is taken — style search used to live inside the "no existing scene_graph" branch only,
    which meant requests arriving with a scene_graph already set (Step 1's /api/generate-layout
    or /api/parse-floor-plan output) silently got no style_params at all, ever. Computing it up
    front fixes that without duplicating the search.
    """
    req = state.get("structured_requirement") or {}
    user_input = state.get("user_input") or {}
    hint_layout = bool(req.get("hint_layout", False))
    task_id = state.get("task_id") or str(uuid.uuid4())

    style_params = state.get("style_params")
    if style_params is None:
        style_params = timed_call(
            "layout_and_style.style_search", task_id, build_style_params, req, user_input
        )

    scene_graph: dict[str, Any] | None = None
    layout_intermediate: dict[str, Any] = {}
    existing_scene_graph = state.get("scene_graph")
    if existing_scene_graph:
        from designbridge.layout.projected_depth import reproject_scene_graph
        from designbridge.render.render_prompt import _resolve_output_size

        output_size = _resolve_output_size(
            str(user_input.get("output_aspect") or "auto"), user_input.get("initial_image")
        )
        # 有照片時疊回照片深度；post_estimate 是上一張生成圖的估計深度，不是照片，不能拿來錨定
        vision = state.get("vision_features") or {}
        photo_vision = vision if vision.get("depth") and vision.get("depth_source") != "post_estimate" else None
        scene_graph = timed_call(
            "layout_and_style.reproject", task_id, reproject_scene_graph,
            existing_scene_graph, req.get("space_info") or {}, task_id, output_size,
            vision_features=photo_vision,
            photo_path=user_input.get("initial_image") if photo_vision else None,
        )
        layout_status = "reused_from_step1"
    elif hint_layout or (Config.ENABLE_PRODUCT_MESHES and not user_input.get("initial_image")):
        # 開啟 IKEA 商品時，沒照片的流程（例如跳過排版）也要先排版，家具才綁得到商品；
        # 有照片但沒要求重排時維持原樣，使用者自己的家具不被換掉
        from designbridge.layout.layout_agent import run_layout_agent
        from designbridge.render.render_prompt import _resolve_output_size

        existing_layout = state.get("layout_from_depth")  # 照片萃取的現有家具位置（若有上傳圖）
        # 必須跟 renderer 最終請求的畫布比例一致，否則投影深度圖與生圖畫布長寬比不符，
        # ControlNet 對不到深度的邊緣區域會生成跟房間無關的內容。
        output_size = _resolve_output_size(
            str(user_input.get("output_aspect") or "auto"), user_input.get("initial_image")
        )
        try:
            result = timed_call(
                "layout_and_style.layout_agent", task_id,
                run_layout_agent, req, task_id,
                existing_layout=existing_layout, output_size=output_size,
                # 照片錨定投影要用照片的深度/分割（b613dad0 原本有傳，之後在合併時遺失）
                vision_features=state.get("vision_features"),
                image_path=user_input.get("initial_image"),
            )
            scene_graph = result.get("scene_graph")
            layout_intermediate = result.get("intermediate_outputs") or {}
            layout_status = "ok"
            _proj = (scene_graph or {}).get("projected_depth_path")
            print(
                f"[layout_and_style] hint_layout=True → layout planned "
                f"({len((scene_graph or {}).get('furniture_placements') or [])} items, "
                f"projected_depth={'yes' if _proj else 'no'})"
            )
        except Exception as e:
            layout_status = f"failed: {e}"
            print(f"⚠️ [layout_and_style] layout agent failed ({e}), continuing with style only")
    else:
        layout_status = "skipped: no layout replanning requested"
        print("[layout_and_style] hint_layout=False → skipping layout, spatial structure from depth map")

    return {
        **({"style_params": style_params} if style_params else {}),
        **({"scene_graph": scene_graph} if scene_graph else {}),
        "intermediate_outputs": {
            **(state.get("intermediate_outputs") or {}),
            **layout_intermediate,
            "layout_and_style_agent": {
                "layout": layout_status,
                "hint_layout": hint_layout,
                "style_profile_id": style_params.get("style_profile_id") if style_params else None,
            },
        }
    }
