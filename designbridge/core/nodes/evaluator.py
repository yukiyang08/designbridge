"""CLIP Evaluator graph node."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from designbridge.core.state import DesignBridgeState
from designbridge.core.timing import timed_call


def clip_evaluator_node(state: DesignBridgeState) -> dict[str, Any]:
    """Run CLIP evaluation on the generated image against the user's original input.

    Translates the raw user text_prompt to English before scoring so that the
    English-trained CLIP model can compare faithfully against what the user asked for.
    """
    image_path = state.get("generated_image")
    user = state.get("user_input") or {}
    raw_prompt = (user.get("text_prompt") or "").strip()
    # requirement_analyzer already asks Gemini for an English design_description
    # (see prompts.py REQUIREMENT_ANALYZER_PROMPT) — reuse it instead of paying
    # for a second Gemini translation call of the raw (often Chinese) text_prompt.
    design_description = ((state.get("structured_requirement") or {}).get("design_description") or "").strip()

    if not image_path or not Path(image_path).is_file():
        return {"evaluation_result": {"scores": {}, "weighted_score": 0.0, "decision": "skip", "feedback": "no generated image", "issues_found": [], "suggestions": []}}

    if not raw_prompt and not design_description:
        return {"evaluation_result": {"scores": {}, "weighted_score": 0.0, "decision": "skip", "feedback": "no text prompt", "issues_found": [], "suggestions": []}}

    task_id = state.get("task_id")

    def _run() -> None:
        try:
            from designbridge.render.clip_evaluator import evaluate, _translate_to_english
            text_prompt = design_description or timed_call(
                "clip_evaluator.translate", task_id, _translate_to_english, raw_prompt
            )
            result = timed_call("clip_evaluator.evaluate", task_id, evaluate, image_path, text_prompt)
            print(f"[clip_evaluator][{task_id}] {result.get('feedback')}")
        except Exception as e:
            print(f"⚠️ [clip_evaluator] CLIP evaluation failed: {e}")

    # 分數沒有任何下游節點或前端在用，放背景跑，不佔生圖回應時間；結果只印在後端 log
    threading.Thread(target=_run, daemon=True).start()
    return {"evaluation_result": {"scores": {}, "weighted_score": 0.0, "decision": "background", "feedback": "CLIP 評分在背景執行，結果見後端 log", "issues_found": [], "suggestions": []}}
