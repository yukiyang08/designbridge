"""
一次性腳本：用 Gemini Vision 為 ikea_tw.json 每件商品生成中文視覺描述，
並寫回 json。已有 visual_description 的商品跳過（支援斷點續跑）。

執行方式：
    python scripts/enrich_kb_descriptions.py
"""
import json
import sys
import time
from pathlib import Path

import httpx
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # 直接 python scripts/... 也找得到 designbridge
from designbridge.render.llm import get_gemini_client  # noqa: E402

MODEL = "gemini-2.5-flash"   # 原本的 gemini-1.5-flash 已下架
KB_PATH = Path(__file__).parent.parent / "designbridge" / "furniture_kb" / "ikea_tw.json"
PROMPT = (
    "請用15字以內的中文描述這件家具的外觀，"
    "包含形狀、顏色、材質特徵，不要提品牌或型號。"
    "只輸出描述文字，不要其他說明。"
)


def describe_item(client, image_url: str) -> str:
    img_bytes = httpx.get(image_url, timeout=10).content
    response = client.models.generate_content(
        model=MODEL,
        contents=[PROMPT, types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")],
    )
    return response.text.strip()


def main():
    client = get_gemini_client()

    items = json.loads(KB_PATH.read_text(encoding="utf-8"))
    updated = 0

    for i, item in enumerate(items):
        if item.get("visual_description"):
            continue
        if not item.get("image_url"):
            item["visual_description"] = ""
            continue
        try:
            desc = describe_item(client, item["image_url"])
            item["visual_description"] = desc
            updated += 1
            print(f"[{i+1}/{len(items)}] {item['name'][:20]} → {desc}")
            if updated % 10 == 0:
                KB_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            time.sleep(0.5)
        except Exception as e:
            print(f"  SKIP {item['name'][:20]}: {e}")
            item["visual_description"] = ""

    KB_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成，共更新 {updated} 件")


if __name__ == "__main__":
    main()
