#!/usr/bin/env python3
"""用 Gemini Vision 生成 caption、驗證風格、分類空間類型，寫回 Supabase。

Usage (from project root):
    python -m style_kb.collection.generate_captions --sample 3     # 測試 3 張
    python -m style_kb.collection.generate_captions --run          # 跑全部未標記
    python -m style_kb.collection.generate_captions --run --style modern
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

_root = __file__
for _ in range(3):
    _root = os.path.dirname(_root)
sys.path.insert(0, _root)

from dotenv import load_dotenv
load_dotenv(os.path.join(_root, ".env"))
load_dotenv()

from style_kb.style_descriptions import STYLE_CLIP_TEXTS, STYLE_DESCRIPTIONS_ZH, STYLE_CAPTION_HINTS

MODEL     = "gemini-2.5-flash"
FAL_MODEL = "google/gemini-2.5-flash"
BUCKET    = "style-images"


# ── Style reference block (English) ──────────────────────────────────────────

def _style_reference_block() -> str:
    lines = []
    for sid, desc in STYLE_CLIP_TEXTS.items():
        lines.append(f"[{sid}] {desc}")
    return "\n".join(lines)


STYLE_REF = _style_reference_block()
VALID_STYLES = list(STYLE_DESCRIPTIONS_ZH.keys())
VALID_SPACES = [
    "living_room", "bedroom", "kitchen", "bathroom",
    "dining_room", "study", "hallway", "foyer", "balcony", "office", "other"
]
SPACE_ZH = {
    "living_room": "客廳",
    "bedroom":     "臥室",
    "kitchen":     "廚房",
    "bathroom":    "浴室",
    "dining_room": "餐廳",
    "study":       "書房",
    "hallway":     "走道",
    "foyer":       "玄關",
    "balcony":     "陽台",
    "office":      "辦公室",
    "other":       "其他",
}


def _build_prompt(style_id: str) -> str:
    hint = STYLE_CAPTION_HINTS.get(style_id, "Describe the visual style and dominant design elements.")
    return f"""You are an interior design image analyst. Analyze the image and return ONLY valid JSON, no extra text.

Style definitions for reference:
{STYLE_REF}

Return this exact JSON (all fields required):
{{
  "style_id": "<best matching key from above: modern/nordic/japanese/industrial/american/classic/luxury/country/other>",
  "space_type": "<{' | '.join(VALID_SPACES)}>",
  "caption_en": "<50-80 words describing space type, style, materials, colors, lighting, and atmosphere>",
  "style_confidence": <0.0-1.0 confidence score for style classification>
}}

Caption focus for style '{style_id}': {hint}
Do NOT mention people, watermarks, or image quality."""


def _parse_json_output(text: str) -> dict:
    import re
    text = text.strip()
    # 先試直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 移除 markdown code block
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 用 regex 抓第一個 {...} 物件
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"無法解析 JSON，原始輸出：{text[:200]}")


def _call_fal(image_url: str, prompt: str) -> dict:
    import fal_client
    result = fal_client.subscribe(
        "fal-ai/any-llm/vision",
        {"model": FAL_MODEL, "image_urls": [image_url],
         "prompt": prompt, "max_tokens": 4096, "temperature": 0.3},
    )
    return _parse_json_output(result["output"])


def _call_gemini(image_url: str, prompt: str, client) -> dict:
    import urllib.request
    from google.genai import types
    req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        img_bytes = resp.read()
    ext = image_url.split(".")[-1].lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    response = client.models.generate_content(
        model=MODEL,
        contents=[prompt, types.Part.from_bytes(data=img_bytes, mime_type=mime)],
        config=types.GenerateContentConfig(
            temperature=0.3, max_output_tokens=4096,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return _parse_json_output(response.text)


class QuotaExceeded(Exception):
    pass


def _is_quota_error(e: Exception) -> bool:
    msg = str(e).lower()
    return ("429" in msg or "quota" in msg or "resourceexhausted" in type(e).__name__.lower()
            or "rate_limit" in msg or "ratelimit" in msg)


def _call_gemini_with_rotation(image_url: str, prompt: str) -> dict:
    """依序嘗試所有 Gemini key（Vertex 模式只有一次）；全部 quota 耗盡才 raise QuotaExceeded。"""
    from designbridge.render.llm import _get_client, _resolve_gemini_api_keys
    keys = _resolve_gemini_api_keys()
    if not keys:
        raise RuntimeError("未設定 Gemini 認證（API key 或 service-account.json）")
    for key in keys:
        try:
            return _call_gemini(image_url, prompt, _get_client(key))
        except Exception as e:
            if not _is_quota_error(e):
                raise
    raise QuotaExceeded("所有 Gemini key 的配額都已耗盡")


def analyze_image(image_url: str, style_id: str, provider: str = "auto") -> dict | None:
    prompt = _build_prompt(style_id)
    try:
        if provider == "fal":
            return _call_fal(image_url, prompt)
        if provider == "gemini":
            return _call_gemini_with_rotation(image_url, prompt)
        # auto: fal → gemini fallback
        try:
            return _call_fal(image_url, prompt)
        except Exception as fal_err:
            if _is_quota_error(fal_err):
                raise QuotaExceeded(f"fal.ai quota: {fal_err}")
            print(f"    ⚠️  fal.ai 失敗：{fal_err}，改用 Gemini...")
            return _call_gemini_with_rotation(image_url, prompt)
    except QuotaExceeded:
        raise
    except Exception as e:
        if _is_quota_error(e):
            raise QuotaExceeded(str(e))
        print(f"    ❌ 失敗：{e}")
        return None


# ── Supabase ──────────────────────────────────────────────────────────────────

def get_supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def move_storage_file(client, old_path: str, new_style_id: str) -> dict:
    """Storage 搬檔：old_path → new_style_id/filename。回傳要更新的 DB 欄位，無需搬則回傳 {}。"""
    filename = old_path.split("/")[-1]
    new_path = f"{new_style_id}/{filename}"
    if old_path == new_path:
        return {}
    try:
        file_bytes = client.storage.from_(BUCKET).download(old_path)
        ext = filename.rsplit(".", 1)[-1].lower()
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
        client.storage.from_(BUCKET).upload(new_path, file_bytes,
                                             {"content-type": mime, "upsert": "true"})
        client.storage.from_(BUCKET).remove([old_path])
        new_url = (f"{os.environ['SUPABASE_URL']}/storage/v1/object/public/{BUCKET}/{new_path}")
        print(f"    📁 {old_path} → {new_path}")
        return {"image_path": new_path, "image_url": new_url}
    except Exception as e:
        print(f"    ⚠️  檔案搬移失敗：{e}（僅更新 DB）")
        return {}


def fetch_rows(style: str | None, limit: int | None) -> list[dict]:
    client = get_supabase()
    PAGE = 1000
    all_rows: list[dict] = []
    offset = 0
    while True:
        q = (client.table("style_images")
             .select("id, image_url, image_path, style_id")
             .is_("caption_model", "null"))
        if style:
            q = q.eq("style_id", style)
        if limit:
            q = q.limit(limit)
            return (q.execute()).data or []
        batch = (q.range(offset, offset + PAGE - 1).execute()).data or []
        all_rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return all_rows


def write_result(client, row_id: str, result: dict, caption_model: str = MODEL,
                 original_row: dict | None = None) -> None:
    new_style = result.get("style_id")
    update: dict = {
        "caption_en":          result.get("caption_en"),
        "space":               SPACE_ZH.get(result.get("space_type", ""), result.get("space_type")),
        "ai_style_confidence": result.get("style_confidence"),
        "caption_model":       caption_model,
        "caption_at":          datetime.now(timezone.utc).isoformat(),
    }
    if new_style:
        update["style_id"] = new_style
        # 風格改變時搬 Storage 檔案
        if (original_row and
                new_style != original_row.get("style_id") and
                original_row.get("image_path")):
            update.update(move_storage_file(client, original_row["image_path"], new_style))
    client.table("style_images").update(update).eq("id", row_id).execute()


# ── 主流程 ────────────────────────────────────────────────────────────────────

def _auto_open_review(json_path: str, port: int = 8765) -> None:
    import subprocess
    import webbrowser
    print(f"\n🚀 自動開啟審核伺服器（port {port}）...")
    subprocess.Popen(
        [sys.executable, "-m", "style_kb.collection.review_server",
         "--from-json", json_path, "--port", str(port)],
        cwd=_root,
    )
    time.sleep(1.5)
    webbrowser.open(f"http://localhost:{port}")


def main():
    parser = argparse.ArgumentParser(description="AI Vision 生成 caption（預設 dry-run）")
    parser.add_argument("--sample",   type=int, default=None, help="只處理 N 張")
    parser.add_argument("--run",      action="store_true",   help="直接寫入 DB（跳過人工審核）")
    parser.add_argument("--style",    type=str, default=None, help="只處理指定風格")
    parser.add_argument("--json-out", type=str, default=None, help="dry-run 輸出路徑（預設 caption_review.json）")
    parser.add_argument("--provider", type=str, default="auto", choices=["auto", "fal", "gemini"],
                        help="auto（預設，fal → gemini fallback）/ fal / gemini")
    args = parser.parse_args()

    limit = args.sample
    rows = fetch_rows(args.style, limit)
    print(f"待處理：{len(rows)} 張  ({'直接寫 DB' if args.run else 'dry-run → caption_review.json'})\n")

    client = get_supabase() if args.run else None
    ok = fail = 0
    pending: list[dict] = []

    quota_hit = False
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row['style_id']} — {row['id'][:8]}...")
        try:
            result = analyze_image(row["image_url"], row["style_id"] or "other", args.provider)
        except QuotaExceeded as qe:
            print(f"\n⚠️  Quota 已達上限：{qe}")
            print(f"   已處理 {i - 1} 張，中止剩餘 {len(rows) - i + 1} 張。")
            quota_hit = True
            break

        if result:
            print(f"    style: {result.get('style_id')}  space: {result.get('space_type')}")
            print(f"    caption: {result.get('caption_en','')[:80]}...")
            if not args.run:
                pending.append({
                    "id":                  row["id"],
                    "image_url":           row["image_url"],
                    "image_path":          row["image_path"],
                    "original_style_id":   row["style_id"] or "other",
                    "style_id":            result.get("style_id", row["style_id"] or "other"),
                    "space":               SPACE_ZH.get(result.get("space_type", ""), result.get("space_type", "")),
                    "caption_en":          result.get("caption_en", ""),
                    "ai_style_confidence": result.get("style_confidence"),
                    "caption_model":       MODEL,
                })
            else:
                write_result(client, row["id"], result, MODEL, original_row=row)
            ok += 1
        else:
            fail += 1

        if i < len(rows):
            time.sleep(1)

    if not args.run:
        out = Path(args.json_out) if args.json_out else Path(_root) / "caption_review.json"
        out.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
        if quota_hit:
            print(f"\n💾 Quota 中止，已暫存 {ok} 筆到 {out}（失敗 {fail}）")
        else:
            print(f"\n✅ 暫存 {ok} 筆到 {out}（失敗 {fail}）")
        if ok > 0:
            _auto_open_review(str(out))
    else:
        if quota_hit:
            print(f"\n⚠️  Quota 中止：成功 {ok} / 失敗 {fail}（已寫入 DB）")
        else:
            print(f"\n✅ 完成：成功 {ok} / 失敗 {fail}")


if __name__ == "__main__":
    main()
