# designbridge/graph.py
"""DesignBridge LangGraph: build and compile the workflow."""

from __future__ import annotations

from typing import Any, Callable

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from designbridge.core.nodes import (
    adjuster_agent_stub,
    clip_evaluator_node,
    composer_node,
    depth_cloud_node,
    layout_and_style_agent_stub,
    requirement_analyzer,
    renderer,
    visual_preprocessing_local,
)
from designbridge.core.state import DesignBridgeState, RoutingDecision
from designbridge.core.timing import log_stage


def _timed_node(
    name: str, fn: Callable[[DesignBridgeState], dict[str, Any]]
) -> Callable[[DesignBridgeState], dict[str, Any]]:
    """Wrap a graph node so its wall-clock duration is logged on exit."""

    def _wrapped(state: DesignBridgeState) -> dict[str, Any]:
        task_id = state.get("task_id")
        with log_stage(name, task_id=task_id):
            return fn(state)

    _wrapped.__name__ = getattr(fn, "__name__", name)
    return _wrapped


def _route_after_requirement(state: DesignBridgeState) -> str:
    """Map routing_decision (always set by requirement_analyzer) to agent node name."""
    decision: RoutingDecision | None = state.get("routing_decision")
    return {
        "design_adjuster": "adjuster_agent",
        "design": "layout_and_style_agent",
    }.get(decision, "layout_and_style_agent")


def build_graph() -> StateGraph:
    """
    Build DesignBridge workflow:
    START -> requirement_analyzer -> visual_preprocessing
      -> (adjuster_agent | layout_and_style_agent -> composer) -> renderer
      -> depth_cloud -> clip_evaluator -> END

    routing_decision（design vs design_adjuster）完全由 requirement_analyzer 決定
    （RA 語意判斷 → refine_mode 覆蓋 → 都沒有才預設 "design"）。原本這裡有個獨立的
    design_director 節點負責路由，但它唯一還有作用的兩件事（refine_mode 覆蓋、
    RA 失敗時的預設值）都已經折進 requirement_analyzer 裡，動態讀 SKILL.md 用 LLM
    路由那條路徑在實務上從沒真的被觸發過（RA 自己的語意判斷早就取代了它），
    所以整個節點直接拿掉，不用再多一次 graph hop。

    composer 只接在 layout_and_style_agent 後面，不接在 adjuster_agent 後面——
    局部編輯（inpaint）改的是既有照片的一小塊區域，prompt 本來就該貼著那個物件講，
    沒有「design_description 跟風格參考互相矛盾」這個問題要協調。

    注意：quotation_agent（家具估價/報價推薦）不在這個自動流程裡執行。
    它耗時較長（觀測約 30-40 秒），且不影響生成圖片本身，因此改成
    使用者按下「取得家具報價」按鈕才呼叫獨立的 /api/quotation
    endpoint（見 api.py），而不是每次 /api/generate 都自動跑一次。
    """
    graph: StateGraph[DesignBridgeState] = StateGraph(DesignBridgeState)

    graph.add_node("requirement_analyzer", _timed_node("requirement_analyzer", requirement_analyzer))
    graph.add_node("visual_preprocessing", _timed_node("visual_preprocessing", visual_preprocessing_local))
    graph.add_node("adjuster_agent", _timed_node("adjuster_agent", adjuster_agent_stub))
    graph.add_node("layout_and_style_agent", _timed_node("layout_and_style_agent", layout_and_style_agent_stub))
    graph.add_node("composer", _timed_node("composer", composer_node))
    graph.add_node("renderer", _timed_node("renderer", renderer))
    graph.add_node("depth_cloud", _timed_node("depth_cloud", depth_cloud_node))
    graph.add_node("clip_evaluator", _timed_node("clip_evaluator", clip_evaluator_node))

    graph.add_edge(START, "requirement_analyzer")
    graph.add_edge("requirement_analyzer", "visual_preprocessing")
    graph.add_conditional_edges(
        "visual_preprocessing",
        _route_after_requirement,
        path_map={
            "adjuster_agent": "adjuster_agent",
            "layout_and_style_agent": "layout_and_style_agent",
        },
    )
    graph.add_edge("adjuster_agent", "renderer")
    graph.add_edge("layout_and_style_agent", "composer")
    graph.add_edge("composer", "renderer")
    graph.add_edge("renderer", "depth_cloud")
    graph.add_edge("depth_cloud", "clip_evaluator")
    graph.add_edge("clip_evaluator", END)

    return graph


def get_compiled_graph():
    """Return compiled graph ready for invoke/stream."""
    return build_graph().compile()
