"""每個帳號的 API 用量與估計花費（Gemini token、fal 生圖），寫進 usage_events 表（docs/sql/usage.sql）。

金額是用下面的單價估算，跟帳單可能有小誤差；以 Vertex / fal 後台帳單為準。
"""
from __future__ import annotations

import contextvars
import math
import os
from concurrent.futures import ThreadPoolExecutor

# middleware 每個請求放一個 dict，get_user_id 驗證後填 user_id。
# 用可變 dict：依賴注入跑在 context 副本裡，在那裡 set 傳不回端點。丟進 thread pool 的工作要 copy_context 才帶得到
_request: contextvars.ContextVar[dict | None] = contextvars.ContextVar("usage_request", default=None)

# USD／百萬 token（輸入, 輸出）。Gemini 3.6 Flash 在 Vertex 優惠價到 2026/12/31，之後是 1.5 / 7.5
GEMINI_PRICE = (
    float(os.getenv("DESIGNBRIDGE_GEMINI_PRICE_IN", "0.75")),
    float(os.getenv("DESIGNBRIDGE_GEMINI_PRICE_OUT", "3.75")),
)
# USD／百萬像素（fal 按 1024×1024 為 1 MP、無條件進位計費），2026-11 查 fal pricing
FAL_PRICE_PER_MP = {
    "fal-ai/flux-general": 0.075,
    "fal-ai/flux-general/inpainting": 0.075,
    "fal-ai/flux-general/image-to-image": 0.075,
    "fal-ai/flux-lora-fill": 0.035,
    "fal-ai/flux-pro/v1/fill": 0.05,
    "fal-ai/flux-kontext/dev": 0.025,
}
_FAL_DEFAULT_PER_MP = 0.075   # 沒列到的端點先用最貴的估，寧可高估

# ponytail: 單一背景執行緒逐筆 insert，量大再改批次寫入
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="usage-writer")


def start_request(route: str) -> None:
    _request.set({"user_id": None, "route": route})


def set_user(user_id: str) -> None:
    req = _request.get()
    if req is not None:
        req["user_id"] = user_id or None


def record_llm(model: str, prompt_tokens: int | None, completion_tokens: int | None, duration_s: float) -> None:
    pt, ct = prompt_tokens or 0, completion_tokens or 0
    cost = (pt * GEMINI_PRICE[0] + ct * GEMINI_PRICE[1]) / 1e6
    _record("llm", model, prompt_tokens=pt, completion_tokens=ct, cost_usd=cost, duration_s=duration_s)


def record_fal(endpoint: str, result, duration_s: float, queue_s: float | None = None) -> None:
    """queue_s：在 fal 排隊等待的秒數（含在 duration_s 裡）。"""
    images = (result or {}).get("images") or ([result["image"]] if isinstance((result or {}).get("image"), dict) else [])
    # 沒回尺寸就當 1 MP
    mp = sum(math.ceil((im.get("width") or 1024) * (im.get("height") or 1024) / (1024 * 1024)) for im in images) or 1
    cost = mp * FAL_PRICE_PER_MP.get(endpoint, _FAL_DEFAULT_PER_MP)
    _record("image", endpoint, images=max(len(images), 1), cost_usd=cost, duration_s=duration_s, queue_s=queue_s)


def _record(kind: str, model: str, **fields) -> None:
    req = _request.get() or {}
    row = {"kind": kind, "model": model, "user_id": req.get("user_id"), "route": req.get("route"), **fields}
    row["cost_usd"] = round(row["cost_usd"], 6)
    for k in ("duration_s", "queue_s"):
        if row.get(k) is not None:
            row[k] = round(row[k], 2)
    _writer.submit(_insert, row)


def _insert(row: dict) -> None:
    try:
        from designbridge.style.style_supabase import _get_supabase
        _get_supabase().table("usage_events").insert(row).execute()
    except Exception as e:  # noqa: BLE001 — 記帳失敗不能影響生圖
        print(f"⚠️ [usage] 寫入用量失敗：{e}")
