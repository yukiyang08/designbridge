"""風格代理人：檢索 → 評審 → 必要時改寫重查，挑出最適合的一張參考圖。

只包住文字檢索這一步；任何失敗回傳 None，由呼叫端退回直接檢索。
"""

from __future__ import annotations

import json
from typing import Any

from designbridge.style.style_supabase import (
    SupabaseStyleResult,
    _compose_style_kb_text,
    query_style_images_supabase,
)

_TOP_K = 5
_REVIEW_PROMPT = """你是室內設計風格顧問。使用者想要的空間：{room}；需求描述：{desc}
下面是風格資料庫檢索到的候選（編號從 0 開始）：
{cands}

請判斷哪一張最符合需求。若沒有任何一張合適（房型不符、風格與描述衝突），ok 設為 false，
並在 rewrite 給一句更精準的中文檢索語句。只輸出 JSON：
{{"ok": true/false, "best": 最合適的編號, "reason": "一句話理由", "rewrite": "改寫後的檢索語句"}}"""


def _summarize(results: list[SupabaseStyleResult]) -> str:
    lines = []
    for i, r in enumerate(results):
        text = _compose_style_kb_text({"style_kb": r.style_kb})[:160]
        lines.append(f"[{i}] {r.style_name}（相似度 {r.similarity}）{text}")
    return "\n".join(lines)


def _review(room: str, desc: str, results: list[SupabaseStyleResult]) -> dict[str, Any]:
    from designbridge.render.llm import call_llm

    text = call_llm(
        _REVIEW_PROMPT.format(room=room, desc=desc or "（未描述）", cands=_summarize(results)),
        json_mode=True,
    )
    return json.loads(text)


def pick_style_results(
    req: dict[str, Any],
    query: str,
    style_id: str | None,
    max_rounds: int = 2,
) -> tuple[list[SupabaseStyleResult], str] | None:
    """回傳 (最佳者排第一的候選, 選擇理由)；失敗或無結果回 None。"""
    room = (req.get("meta") or {}).get("room_type", "living_room")
    desc = req.get("design_description") or req.get("user_description_raw") or query
    try:
        results: list[SupabaseStyleResult] = []
        verdict: dict[str, Any] = {}
        for _ in range(max_rounds):
            results = query_style_images_supabase(text_query=query, style_id=style_id, top_k=_TOP_K)
            if not results:
                return None
            verdict = _review(room, desc, results)
            if verdict.get("ok"):
                break
            query = str(verdict.get("rewrite") or query)
            print(f"[style_agent] 候選不合格，改寫查詢：{query}")
        best = int(verdict.get("best", 0))
        if not 0 <= best < len(results):
            best = 0
        # blend 只取第一張，所以把評審選的移到最前面
        ordered = [results[best]] + [r for i, r in enumerate(results) if i != best]
        return ordered, str(verdict.get("reason") or "")
    except Exception as e:
        print(f"⚠️ style agent 失敗，退回直接檢索：{e}")
        return None
