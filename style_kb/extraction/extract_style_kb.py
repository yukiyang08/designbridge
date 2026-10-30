#!/usr/bin/env python3
"""Extract Style KB JSON from interior images using the existing Gemini model.

Usage (from project root `DesignBridge`):

    python -m style_kb.extract_style_kb              # 處理所有風格
    python -m style_kb.extract_style_kb country      # 只處理 country 風格
    python -m style_kb.extract_style_kb luxury       # 只處理 luxury 風格

Put input images under one folder per style (10 styles):
    style_kb/images/<style_id>/

  style_id: modern, country, classic, nordic, industrial, japanese, american, luxury, neoclassic
  (See style_kb.styles.STYLES for the full list and Chinese names.)

Results will be written to:
    style_kb/outputs/<style_id>/<image_stem>.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from style_kb.extraction.prompts_style_kb import STYLE_KB_PROMPT
from style_kb.styles import STYLES


def _call_gemini_style_kb(
    image_path: Path,
    style_id: str,
    style_name: str,
    user_hint: str = "",
) -> dict[str, Any]:
    """Use current Gemini configuration to extract Style KB JSON for a single image."""
    try:
        from google.genai import types
        from designbridge.render.llm import get_gemini_client
    except ImportError as exc:  # noqa: BLE001
        raise RuntimeError(
            "google-genai 未安裝。請先執行: pip install google-genai"
        ) from exc

    client = get_gemini_client()

    prompt = STYLE_KB_PROMPT.format(
        style_id=style_id,
        style_name=style_name,
        user_hint=user_hint,
    )

    suffix = image_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    image_part = types.Part.from_bytes(
        data=image_path.read_bytes(),
        mime_type=mime_map.get(suffix, "image/jpeg"),
    )

    response = client.models.generate_content(
        model=Config.GEMINI_MODEL,
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(
            temperature=Config.GEMINI_TEMPERATURE,
        ),
    )

    text = (getattr(response, "text", "") or "").strip()

    # 處理 ```json ... ``` 包裹
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Gemini 回傳的不是 JSON 物件。")
    # 強制寫入既有風格標籤，確保與資料夾一致
    if "style_info" not in data:
        data["style_info"] = {}
    data["style_info"]["style_id"] = style_id
    data["style_info"]["name"] = style_name
    return data


def main() -> None:
    # 解析命令行參數
    parser = argparse.ArgumentParser(
        description="提取室內設計圖片的風格知識庫 JSON"
    )
    parser.add_argument(
        "style_filter",
        nargs="?",
        default=None,
        help="只處理指定的風格（例如：country, luxury）。若不指定則處理所有風格。",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    images_dir = base_dir / "images"
    out_dir = base_dir / "outputs"
    images_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 建立 10 個風格的 images 與 outputs 子資料夾
    for style_id, style_name in STYLES:
        (images_dir / style_id).mkdir(parents=True, exist_ok=True)
        (out_dir / style_id).mkdir(parents=True, exist_ok=True)
    print(f"📂 已確保 style_kb/images/<style_id>/ 與 style_kb/outputs/<style_id>/ 共 {len(STYLES)} 組資料夾存在。")

    # 決定要處理的風格
    if args.style_filter:
        # 驗證指定的風格是否存在
        valid_styles = [s[0] for s in STYLES]
        if args.style_filter not in valid_styles:
            print(f"❌ 錯誤：風格 '{args.style_filter}' 不存在。")
            print(f"有效的風格包括：{', '.join(valid_styles)}")
            return
        styles_to_process = [(s[0], s[1]) for s in STYLES if s[0] == args.style_filter]
    else:
        styles_to_process = STYLES

    total = 0
    for style_id, style_name in styles_to_process:
        style_images_dir = images_dir / style_id
        if not style_images_dir.is_dir():
            print(f"⏭️ 略過 {style_id}（{style_name}）：無資料夾 {style_images_dir}")
            continue

        image_files = sorted(
            [
                p
                for p in style_images_dir.iterdir()
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            ]
        )
        if not image_files:
            print(f"⏭️ 略過 {style_id}（{style_name}）：資料夾內無圖片")
            continue

        style_out_dir = out_dir / style_id
        style_out_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n📁 風格 [{style_name} / {style_id}] 共 {len(image_files)} 張")

        # 檢查是否有已存在的檔案
        existing_files = [
            f"{img_path.stem}.json"
            for img_path in image_files
            if (style_out_dir / f"{img_path.stem}.json").exists()
        ]
        
        skip_existing = False
        if existing_files:
            print(f"  ⚠️  發現 {len(existing_files)} 個已存在的檔案")
            response = input("     是否要重新生成已存在的檔案？(yes/no，預設 no): ").strip().lower()
            if response not in ("yes", "y", "是", "要"):
                skip_existing = True
                print(f"  ⏭️  將跳過所有已存在的檔案")

        for img_path in image_files:
            out_path = style_out_dir / f"{img_path.stem}.json"
            
            # 如果檔案已存在且選擇跳過，則跳過
            if out_path.exists() and skip_existing:
                print(f"  ⏭️  {img_path.name} (已存在)")
                continue
            
            print(f"  🔍 {img_path.name}")
            try:
                style_kb = _call_gemini_style_kb(
                    img_path, style_id=style_id, style_name=style_name, user_hint=""
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  ❌ 失敗: {exc}")
                continue

            out_path.write_text(
                json.dumps(style_kb, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            total += 1
            print(f"  ✅ {out_path.name}")

    print(f"\n🎯 完成，共輸出 {total} 個 Style KB。")


if __name__ == "__main__":
    main()

