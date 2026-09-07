"""Layout + Style graph node."""

from __future__ import annotations

import uuid
from typing import Any

from designbridge.core.state import DesignBridgeState
from designbridge.core.timing import timed_call
from designbridge.style.style_apply import build_style_params


def layout_and_style_agent_stub(state: DesignBridgeState) -> dict[str, Any]:
    """Layout + style agent.

    Layout planning is only executed when the user explicitly requests spatial reorganization
    (hint_layout=True from LLM semantic analysis). Otherwise only style params are built,
    and spatial structure is left to the depth map (if available).
    """
    # 已經跑過一次了（/api/plan-layout 先規劃、使用者確認後才呼叫 /api/generate）——
    # 不重新搜尋風格、更不重新呼叫 layout_agent 的 Gemini。但 scene_graph 裡的
    # furniture_placements 可能在 3D 預覽裡被使用者拖動過，projected_depth_path
    # 是純 NumPy 運算出來的（不是 LLM 呼叫，重算很便宜），必須依當下座標重新投影一次，
    # 不然 ControlNet 吃到的還是使用者編輯前的舊位置。
    if state.get("scene_graph"):
        from designbridge.layout.layout_agent import reproject_scene_graph
        from designbridge.render.render_prompt import _resolve_output_size

        req = state.get("structured_requirement") or {}
        user_input = state.get("user_input") or {}
        task_id = state.get("task_id") or str(uuid.uuid4())
        output_size = _resolve_output_size(
            str(user_input.get("output_aspect") or "auto"), user_input.get("initial_image")
        )
        updated_scene_graph = reproject_scene_graph(
            state["scene_graph"], req.get("space_info") or {}, task_id, output_size,
        )
        return {"scene_graph": updated_scene_graph}
    if state.get("style_params"):
        return {}

    req = state.get("structured_requirement") or {}
    user_input = state.get("user_input") or {}
    hint_layout = bool(req.get("hint_layout", False))
    task_id = state.get("task_id") or str(uuid.uuid4())

    style_params = timed_call("layout_and_style.style_search", task_id, build_style_params, req, user_input)

    # Step 1 (the /layout API endpoint) may already have planned the room and seeded its
    # scene_graph into state. Re-running the layout agent here would discard that plan and
    # hand back a different arrangement than the one the user just reviewed and accepted,
    # so reuse it and only build the style params.
    existing_scene_graph = state.get("scene_graph") or {}
    if existing_scene_graph.get("floor_plan_path"):
        print(
            "[layout_and_style] Reusing Step-1 floor plan: "
            f"{existing_scene_graph['floor_plan_path']}"
        )
        return {
            **({"style_params": style_params} if style_params else {}),
            "intermediate_outputs": {
                **(state.get("intermediate_outputs") or {}),
                "layout_and_style_agent": {
                    "layout": "reused_from_step1",
                    "hint_layout": hint_layout,
                    "style_profile_id": style_params.get("style_profile_id") if style_params else None,
                },
            },
        }

    scene_graph: dict[str, Any] | None = None
    layout_intermediate: dict[str, Any] = {}
    if hint_layout:
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
