#!/usr/bin/env python3
"""用 Gemini 自動分類室內設計圖片的風格。

從 style_kb/raw/<source>/<original_style>/ 讀取圖片，
用 Gemini 分析真實風格，並根據信心分數決定去向：
  - 信心 ≥ 0.80: 移到 style_kb/images/<classified_style>/
  - 信心 0.60-0.79: 移到 style_kb/review/<original_style>/
  - 信心 < 0.60: 刪除

Usage (from project root):
    python -m style_kb.classify_image                        # 分類所有圖片
    python -m style_kb.classify_image modern                 # 只分類指定風格
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
from typing import Optional

from designbridge.core.config import Config
from style_kb.styles import STYLES

# ──────────────────────────────────────────────────────────────────────────

RAW_DIR = Path(__file__).resolve().parent / "raw"
IMAGES_DIR = Path(__file__).resolve().parent / "images"
REVIEW_DIR = Path(__file__).resolve().parent / "review"

# Gemini 分類 prompt
CLASSIFICATION_PROMPT = """分析這張室內設計圖片，判斷其主要風格。

可能的風格：
- modern: 現代風格（簡潔線條、極簡、功能性）
- country: 鄉村風格（溫暖色調、自然材質、質樸感）
- classic: 古典風格（對稱、華麗裝飾、傳統元素）
- nordic: 北歐風格（淺色、簡潔、木質、自然光）
- industrial: 工業風格（金屬、混凝土、裸露管線）
- japanese: 日式風格（榻榻米、極簡、禪意）
- american: 美式風格（寬敞、壁爐、舒適感）
- luxury: 奢華風格（大理石、金色、高檔材質）
- neoclassic: 新古典風格（幾何、古典元素現代化）

請以 JSON 格式回覆，包含：
{{
  "primary_style": "<風格 ID>",
  "confidence": 0.85,
  "secondary_style": "<可選次要風格>",
  "reason": "簡短的分類理由"
}}

信心分數 (0.0-1.0)：
- 0.80-1.0: 非常確信
- 0.60-0.79: 相當確信
- 0.40-0.59: 不太確定
- < 0.40: 無法判斷
"""


def _classify_image_with_gemini(image_path: Path) -> dict:
    """用 Gemini 分類單張圖片。"""
    from google.genai import types
    from designbridge.render.llm import get_gemini_client

    client = get_gemini_client()
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"

    print("分析中...")
    response = client.models.generate_content(
        model=Config.GEMINI_MODEL,
        contents=[types.Part.from_bytes(data=Path(image_path).read_bytes(), mime_type=mime),
                  CLASSIFICATION_PROMPT],
        config=types.GenerateContentConfig(temperature=Config.GEMINI_TEMPERATURE),
    )

    text = (getattr(response, "text", "") or "").strip()
    
    # 解析 JSON
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    
    return json.loads(text)


def classify_style(style_id: str, source: Optional[str] = None) -> None:
    """分類單個風格的圖片。"""
    style_name = dict(STYLES).get(style_id, style_id)
    print(f"\n📁 [{style_name} / {style_id}]")
    
    # 取得來源資料夾
    sources = []
    if source:
        sources = [source]
    else:
        sources = [d.name for d in RAW_DIR.iterdir() if d.is_dir()]
    
    high_conf = 0
    mid_conf = 0
    low_conf = 0
    errors = 0
    
    for source_name in sources:
        source_dir = RAW_DIR / source_name / style_id
        if not source_dir.exists():
            continue
        
        print(f"  📂 {source_name}/")
        
        # 列舉圖片檔案
        image_files = sorted([
            f for f in source_dir.glob("*")
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        ])
        
        for image_path in image_files:
            try:
                # 分類
                result = _classify_image_with_gemini(image_path)
                
                classified_style = result.get("primary_style", "unknown")
                confidence = result.get("confidence", 0.0)
                reason = result.get("reason", "")
                
                print(f"    ✅ {image_path.name}")
                print(f"       → {classified_style} (信心: {confidence:.2f})")
                
                # 根據信心分數決定去向
                if confidence >= 0.80:
                    # 移到 images/<classified_style>/
                    target_dir = IMAGES_DIR / classified_style
                    target_dir.mkdir(parents=True, exist_ok=True)
                    
                    target_path = target_dir / image_path.name
                    image_path.rename(target_path)
                    
                    # 保存分類元資訊
                    meta_path = target_dir / f"{image_path.stem}_classification.json"
                    meta_path.write_text(
                        json.dumps({
                            "original_style": style_id,
                            "classified_style": classified_style,
                            "confidence": confidence,
                            "reason": reason,
                            "source": source_name,
                        }, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    
                    high_conf += 1
                
                elif confidence >= 0.60:
                    # 移到 review/<original_style>/
                    review_dir = REVIEW_DIR / style_id
                    review_dir.mkdir(parents=True, exist_ok=True)
                    
                    target_path = review_dir / image_path.name
                    image_path.rename(target_path)
                    
                    # 保存分類元資訊
                    meta_path = review_dir / f"{image_path.stem}_classification.json"
                    meta_path.write_text(
                        json.dumps({
                            "original_style": style_id,
                            "classified_style": classified_style,
                            "confidence": confidence,
                            "reason": reason,
                            "source": source_name,
                        }, ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                    
                    print(f"移到待複審 ({confidence:.2f} < 0.80)")
                    mid_conf += 1
                
                else:
                    # 刪除
                    image_path.unlink()
                    print(f"刪除 (信心: {confidence:.2f} < 0.60)")
                    low_conf += 1
            
            except Exception as e:
                print(f"分類失敗: {e}")
                errors += 1
    
    print(f"  📊 結果: ✅ {high_conf} 通過, ⚠️  {mid_conf} 待複審, 🗑️  {low_conf} 刪除, ❌ {errors} 錯誤")


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini 自動圖片風格分類")
    parser.add_argument(
        "styles",
        nargs="*",
        default=None,
        help="指定要分類的風格（預設：所有風格）",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="指定資料來源 (100interior, searchome)，預設檢查所有",
    )
    args = parser.parse_args()
    
    # 決定要分類的風格
    styles_to_classify = []
    if args.styles:
        for style_id in args.styles:
            if style_id in dict(STYLES):
                styles_to_classify.append(style_id)
            else:
                print(f"⚠️  未知風格: {style_id}")
    else:
        styles_to_classify = [sid for sid, _ in STYLES]
    
    if not styles_to_classify:
        print("❌ 沒有有效的風格指定")
        return
    
    print("=" * 60)
    print(f"🤖 開始 Gemini 自動分類 ({len(styles_to_classify)} 個風格)")
    print("=" * 60)
    
    for style_id in styles_to_classify:
        try:
            classify_style(style_id, args.source)
        except KeyboardInterrupt:
            print("\n⚠️  被用戶中斷")
            break
    
    print("\n" + "=" * 60)
    print("✅ 分類完成！")
    print(f"📁 已分類圖片: {IMAGES_DIR}")
    print(f"⚠️  待複審圖片: {REVIEW_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
