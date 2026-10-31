"""Composer graph node — reconciles design_description + style_kb prompt + layout
furniture facts into one coherent, conflict-free render prompt.

The pieces feeding the renderer's final prompt come from independent sources that
never see each other: RA's own room description (design_description), the
style_kb-matched reference image's positive_prompt, and the layout system's exact
furniture placements. Naively concatenating them (the old
`_build_imagen_prompt_from_requirement` behavior plus renderer's own string
prefixing, still used as the fallback when this node is skipped or fails) produces
contradictions when the matched style disagrees with what the user actually asked
for (e.g. user says "light luxury", the KB match is "industrial loft"), when the
style text names furniture that clashes with the layout's own furniture list (e.g.
"round coffee tables" vs. layout's single rectangular one), or just repeats the
same visual concept twice when sources happen to agree. This node asks Gemini to
merge them into one paragraph instead: the user's own description sets the
aesthetic direction, the layout's furniture facts are treated as ground truth to
preserve verbatim, and the style reference contributes only material/light/mood
words that don't collide with either.
"""

from __future__ import annotations

from typing import Any

from designbridge.core.prompts import COMPOSER_PROMPT
from designbridge.core.state import DesignBridgeState
from designbridge.render.render_prompt import _build_imagen_prompt_from_requirement, _describe_color


def _layout_facts_text(state: DesignBridgeState, req: dict[str, Any]) -> str:
    """Assemble whatever layout/furniture facts are already known at this point in the
    graph (composer runs before renderer, so the depth-projection-corrected furniture
    description — only computable once renderer picks a ControlNet condition image —
    isn't available here; renderer still injects that narrower, more precise variant
    separately when it applies, see renderer.py's `using_projected_depth` branch)."""
    scene_graph = state.get("scene_graph") or {}
    parts: list[str] = []

    furniture_placements = scene_graph.get("furniture_placements") or []
    if furniture_placements:
        from designbridge.core.nodes.renderer import (
            _furniture_to_spatial_text, _instances_to_spatial_text, _projection_instances,
        )
        # 優先用家具在投影深度圖上的實際落點（相機站位不同，平面圖的「左／後」不一定是畫面的左／後）
        proj = scene_graph.get("projected_depth_path")
        spatial = _instances_to_spatial_text(_projection_instances(str(proj))) if proj else ""
        parts.append(spatial or _furniture_to_spatial_text(furniture_placements))

    layout_prompt = (scene_graph.get("layout_prompt") or "").strip()
    if not layout_prompt and req.get("hint_layout"):
        layout_from_depth = state.get("layout_from_depth") or {}
        if layout_from_depth:
            from designbridge.render.render_prompt import _layout_json_to_prompt_text
            layout_prompt = _layout_json_to_prompt_text(layout_from_depth)
    if layout_prompt:
        parts.append(layout_prompt)

    return " ".join(parts)


_MAX_REVISIONS = 2
_META_WORDS = ("user", "style reference", "layout", "conflict", "使用者", "風格參考", "佈局")


def check_prompt(prompt: str, placements: list[dict]) -> list[str]:
    """純程式檢查 composer 草稿：家具是否都提到、有無後設詞、字數。回傳問題清單（空 = 通過）。"""
    # ponytail: 只比對家具名詞是否出現，不驗數量與方位；需要時再加
    from designbridge.core.nodes.renderer import _FURNITURE_DESC

    low = prompt.lower()
    issues: list[str] = []
    for raw in dict.fromkeys(p.get("type", "") for p in placements):
        desc = _FURNITURE_DESC.get(raw, "a " + raw.replace("_", " "))
        # tv_unit 這類名稱 prompt 常寫成 "TV console"，所以任一字出現即算提到
        nouns = [w.lower().rstrip("s") for w in raw.split("_") if len(w) > 1]
        if nouns and not any(n in low for n in nouns):
            issues.append(f"家具佈局的 {raw}（{desc}）沒有出現在 prompt 裡，必須補回")
    for w in _META_WORDS:
        if w in low:
            issues.append(f"出現後設詞「{w}」，請改成直接描述空間")
    if len(prompt.split()) > 150:
        issues.append("超過 130 字，請精簡")
    return issues


def _parse_composer_output(text: str) -> tuple[str, str | None, str | None]:
    """解析 composer 的 JSON 輸出 → (prompt, ra_issue, layout_issue)；不是 JSON 就整段當 prompt。"""
    import json

    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(t)
        return str(d.get("prompt") or "").strip(), (d.get("ra_issue") or None), (d.get("layout_issue") or None)
    except Exception:
        return text.strip(), None, None


def composer_node(state: DesignBridgeState) -> dict[str, Any]:
    """Merge design_description + style_params + layout furniture facts into one
    `composed_prompt`.

    No-op (returns {}) when there's neither a style_prompt nor any furniture/layout
    facts to weave in — the renderer's own base-prompt builder is already
    single-source and coherent then, and there is nothing for this node to add. Also
    degrades to {} (renderer falls back to the naive concatenation) on any LLM
    failure, same graceful-degradation pattern as every other Gemini call in this
    pipeline.

    Also no-op on a pure style swap with no furniture facts to weave in. This node's
    whole job is resolving a conflict between the user's own room description and the
    KB-matched style text — but on a swap (state already has a prior generated_image,
    see routers/generate.py's plan replay) the base-prompt builder already skips the
    stale old-style description and builds a neutral room_type+new_style template
    instead (is_style_swap, below), which by construction doesn't conflict with the
    same style's own style_prompt. There's nothing left to reconcile, so the Gemini
    round-trip (~12-18s per docs/experiments/PERFORMANCE_NOTES.md) is pure latency with no upside —
    skip it and let the non-LLM concatenation in renderer.py's fallback handle it.
    Furniture facts still need this node: weaving new-style material words onto a
    fixed list of furniture is real merge work an LLM-free concatenation can't do.
    """
    req = state.get("structured_requirement") or {}
    style_params = state.get("style_params") or {}
    style_prompt = (style_params.get("style_prompt") or "").strip()
    furniture_facts = _layout_facts_text(state, req)
    # 換風格時 state 已經有上一輪的 generated_image（見 routers/generate.py 的 plan
    # replay），用這個當訊號跳過 design_description——那段文字是原本那個風格寫的，
    # 原封不動塞給 Gemini當「使用者自己的描述，優先權最高」，換風格時只會變成新風格
    # 的詞彙擠不過舊風格的描述，生出來的圖跟原圖幾乎一樣。
    is_style_swap = bool(state.get("generated_image"))
    if not furniture_facts and (not style_prompt or is_style_swap):
        return {}

    user_text_prompt = ((state.get("user_input") or {}).get("text_prompt") or "").strip()
    style_name = (style_params.get("style_profile_id") or "unspecified").strip()
    strength = style_params.get("style_strength", 0.7)

    color_guidance = style_params.get("color_guidance") or {}
    palette_bits = [
        f"{label} {_describe_color(color_guidance[key])}"
        for label, key in (("primary", "primary_color"), ("secondary", "secondary_color"), ("accent", "accent_color"))
        if color_guidance.get(key)
    ]
    palette = ", ".join(palette_bits) if palette_bits else "無特定色碼"

    def _build_prompt(r: dict[str, Any], facts: str) -> str:
        # style_params=None：沿用 base-prompt 邏輯但不做天真的風格串接，那正是本節點取代的部分
        base = _build_imagen_prompt_from_requirement(
            r, style_params=None, user_text_prompt=user_text_prompt, is_style_swap=is_style_swap,
            style_id_override=(style_params.get("style_profile_id") or None) if is_style_swap else None,
        )
        return COMPOSER_PROMPT.format(
            base_prompt=base,
            style_name=style_name,
            strength=strength,
            palette=palette,
            style_reference_text=style_prompt or "無",
            furniture_facts=facts or "無指定家具佈局",
            raw_text=user_text_prompt or "無",
        )

    try:
        from designbridge.core.nodes.requirement import revise_requirement
        from designbridge.render.llm import call_llm

        def _ask(text: str) -> tuple[str, str | None, str | None]:
            return _parse_composer_output(call_llm(text, temperature=0.3, max_tokens=360))

        prompt_text = _build_prompt(req, furniture_facts)
        composed, ra_issue, layout_issue = _ask(prompt_text)
        if not composed:
            raise ValueError("empty composer output")
        log: dict[str, Any] = {"revisions": []}
        out: dict[str, Any] = {}
        # 與 RA / layout 的溝通：發現矛盾就回頭請對方修正，只回頭一輪、修完合併一次
        # 風格切換重播不觸發；layout 只在本輪真的排過版時才重排（Step 1 使用者確認過的佈局不動）
        scene_graph = state.get("scene_graph") or {}
        layout_ran = ((state.get("intermediate_outputs") or {}).get("layout_and_style_agent") or {}).get("layout") == "ok"
        redo = False
        if ra_issue and not is_style_swap:
            req = revise_requirement(req, ra_issue, user_text_prompt)
            out["structured_requirement"] = req
            log["ra_issue"] = ra_issue
            redo = True
        if layout_issue and layout_ran and not is_style_swap:
            from designbridge.core.nodes.layout_and_style import replan_layout

            log["layout_issue"] = layout_issue
            new_sg = replan_layout(state, req, layout_issue)
            if new_sg:
                scene_graph = new_sg
                out["scene_graph"] = new_sg
                furniture_facts = _layout_facts_text({**state, "scene_graph": new_sg}, req)
                redo = True
        if redo:
            prompt_text = _build_prompt(req, furniture_facts)
            composed, _, _ = _ask(prompt_text)
            if not composed:
                raise ValueError("empty composer output after revision")
        # 生成 → 程式檢查 → 帶問題修訂，最多 _MAX_REVISIONS 次；修不好就用最後一版
        placements = scene_graph.get("furniture_placements") or []
        for step in range(_MAX_REVISIONS):
            issues = check_prompt(composed, placements)
            log["revisions"].append({"step": step, "issues": issues})
            if not issues:
                break
            fix, _, _ = _ask(
                f"{prompt_text}\n\n## 上一版輸出\n{composed}\n\n## 程式檢查發現的問題（逐項修正）\n"
                + "\n".join(f"- {i}" for i in issues) + "\n\n修正後輸出："
            )
            if not fix:
                break
            composed = fix
        print(f"[composer] merged prompt: {composed[:120]}")
        out_log = {**(state.get("intermediate_outputs") or {}), "composer": log}
        return {
            **out,
            "composed_prompt": composed,
            "composed_includes_furniture": bool(furniture_facts),
            "intermediate_outputs": out_log,
        }
    except Exception as e:
        print(f"⚠️ [composer] failed ({e}), renderer will fall back to naive concatenation")
        return {}
