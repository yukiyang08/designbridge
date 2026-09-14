#!/usr/bin/env python3
"""對 Supabase 所有圖片生成 Flux LoRA 訓練用的英文 caption，寫入 caption_en 欄位。

Caption 格式：
  [style] [space], [key elements], [materials], [color tone], [lighting], [atmosphere]

Dependencies: pip install httpx google-generativeai supabase python-dotenv

Usage (from project root):
    python -m style_kb.extraction.generate_captions_supabase --dry-run
    python -m style_kb.extraction.generate_captions_supabase --limit 20
    python -m style_kb.extraction.generate_captions_supabase                   # 全部未生成的
    python -m style_kb.extraction.generate_captions_supabase --force-rewrite   # 全部重寫
    python -m style_kb.extraction.generate_captions_supabase --style-id nordic
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")
load_dotenv()

from designbridge.core.config import Config
from style_kb.styles import STYLES

STYLE_NAME_MAP = {sid: sname for sid, sname in STYLES}
GEMINI_SLEEP   = float(os.getenv("GEMINI_SLEEP_SEC", "4.0"))
DOWNLOAD_TIMEOUT = 20

CAPTION_PROMPT = """You are an expert at writing training captions for Flux LoRA fine-tuning, where a separate trigger word will represent the design style.

Look at this interior design image and write ONE concise English caption describing ONLY the objective content — never the aesthetic style itself.

Format:
[room type], [furniture items with position], [structural elements: windows/doors/walls if notable], [camera angle/viewpoint]

Rules:
- 20-45 words, plain text only — no JSON, no bullet points, no quotes
- List furniture by type and rough position (e.g. "an L-shaped sofa facing a rectangular coffee table", "a wall-mounted cabinet along one side")
- Do NOT mention any material names, textures, or finishes (no "marble", "oak wood", "brick", "concrete", "velvet", etc.) — these are style signals and must be left for the trigger word to learn
- Do NOT mention color, color palette, or tone
- Do NOT mention lighting quality or mood (no "warm", "cozy", "dramatic", "soft diffused")
- Do NOT mention atmosphere or aesthetic judgment of any kind (no "elegant", "minimalist", "luxurious", "sophisticated", "modern")
- Do NOT name or imply any design style (no "nordic", "industrial", "luxury", "modern", "traditional", etc.)
- Do NOT add trigger words or generic filler like "high quality render"

Example output:
a living room, an L-shaped sofa facing a rectangular coffee table, a wall-mounted cabinet unit along one side, floor-to-ceiling windows on the far wall, wide-angle interior photograph

Only output the caption sentence. Nothing else.
"""

# ── Supabase ─────────────────────────────────────────────────────────────────

_supabase = None

def get_supabase():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        _supabase = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        )
    return _supabase


def fetch_rows(style_id_filter: str | None, limit: int | None, force_rewrite: bool) -> list[dict]:
    client = get_supabase()
    q = client.table("style_images").select("id, style_id, image_url, source_meta")

    if not force_rewrite:
        q = q.is_("caption_en2", "null")

    if style_id_filter:
        q = q.eq("style_id", style_id_filter)

    q = q.order("style_id")

    if limit:
        q = q.limit(limit)

    return (q.execute()).data or []


def update_caption(row_id: str, caption: str) -> None:
    get_supabase().table("style_images").update({"caption_en2": caption}).eq("id", row_id).execute()


# ── Gemini（多 Key 輪替，共用 designbridge.render.llm）───────────────────────────────

class QuotaExceeded(Exception):
    pass


def generate_caption(image_bytes: bytes, mime_type: str) -> str:
    """依序嘗試所有 Gemini key；全部失敗才 raise QuotaExceeded。

    Key 輪替現在由 ``call_llm`` 內建處理（它會依序試 GEMINI_API_KEY 與
    GEMINI_API_KEYS 的每一把，全部失敗才拋 RuntimeError）。
    """
    from designbridge.render.llm import call_llm

    try:
        caption = call_llm(
            CAPTION_PROMPT,
            images=[{"mime_type": mime_type, "data": image_bytes}],
            temperature=0.3,
        ).strip()
    except RuntimeError as e:
        raise QuotaExceeded(str(e)) from e

    # 去除可能的引號包裹
    if caption.startswith('"') and caption.endswith('"'):
        caption = caption[1:-1].strip()
    return caption


# ── 下載 ─────────────────────────────────────────────────────────────────────

def download(url: str) -> tuple[bytes, str]:
    import httpx
    resp = httpx.get(url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        lower = url.split("?")[0].lower()
        content_type = "image/png" if lower.endswith(".png") else (
            "image/webp" if lower.endswith(".webp") else "image/jpeg"
        )
    return resp.content, content_type


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="批次生成 Flux LoRA 訓練用 caption_en")
    parser.add_argument("--style-id",     default=None, help="只處理指定風格，例如 nordic")
    parser.add_argument("--limit",        type=int, default=None, help="最多處理幾筆")
    parser.add_argument("--dry-run",      action="store_true", help="只顯示，不呼叫 Gemini 也不寫入")
    parser.add_argument("--force-rewrite",action="store_true", help="重寫已有 caption_en 的圖")
    parser.add_argument("--sleep",        type=float, default=None, help="每次 Gemini 呼叫後等待秒數（預設 4.0）")
    args = parser.parse_args()

    global GEMINI_SLEEP
    if args.sleep is not None:
        GEMINI_SLEEP = args.sleep

    print("=" * 55)
    print("  generate_captions_supabase")
    print("=" * 55)
    if args.dry_run:
        print("  模式：DRY RUN")
    print(f"  風格篩選：{args.style_id or '全部'}")
    print(f"  force rewrite：{args.force_rewrite}")
    print(f"  最多處理：{args.limit or '全部'}")
    print(f"  Gemini 間隔：{GEMINI_SLEEP}s")
    print("=" * 55)

    rows = fetch_rows(args.style_id, args.limit, args.force_rewrite)
    print(f"\n找到 {len(rows)} 筆待處理\n")

    if not rows:
        print("沒有需要處理的行。")
        return

    # 摘要：各風格數量
    from collections import Counter
    for sid, cnt in sorted(Counter(r["style_id"] for r in rows).items()):
        print(f"  {sid:<15} {cnt:>4} 張")
    print()

    ok = fail = 0
    t0 = time.perf_counter()

    for i, row in enumerate(rows, 1):
        row_id    = row["id"]
        style_id  = row["style_id"]
        image_url = row["image_url"]
        work_name = (row.get("source_meta") or {}).get("work_name", "")
        prefix    = f"[{i:>4}/{len(rows)}] {style_id} | {work_name or row_id[:8]}"

        if not image_url:
            print(f"  ⚠  {prefix} → image_url 為空，略過")
            fail += 1
            continue

        if args.dry_run:
            print(f"  [DRY] {prefix} → {image_url[:60]}")
            ok += 1
            continue

        try:
            img_bytes, mime_type = download(image_url)
        except Exception as e:
            print(f"  ❌ {prefix} → 下載失敗：{e}")
            fail += 1
            continue

        try:
            caption = generate_caption(img_bytes, mime_type)
        except QuotaExceeded as qe:
            print(f"\n⚠️  Quota 已達上限：{qe}")
            print(f"   已處理 {i - 1} 張，中止剩餘 {len(rows) - i + 1} 張。")
            break
        except Exception as e:
            print(f"  ❌ {prefix} → Gemini 失敗：{e}")
            fail += 1
            time.sleep(GEMINI_SLEEP)
            continue

        try:
            update_caption(row_id, caption)
        except Exception as e:
            print(f"  ❌ {prefix} → Supabase 更新失敗：{e}")
            fail += 1
            continue

        short_caption = caption[:80] + ("..." if len(caption) > 80 else "")
        print(f"  ✅ {prefix}")
        print(f"       {short_caption}")
        ok += 1

        time.sleep(GEMINI_SLEEP)

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 55)
    print(f"  完成：✅ {ok}  ❌ {fail}  ⏱ {elapsed:.0f}s")
    if not args.dry_run:
        est_cost = ok * 0.0004
        print(f"  估計費用：~${est_cost:.2f} USD (Gemini Flash)")
    print("=" * 55)


if __name__ == "__main__":
    main()
