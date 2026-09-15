"""
測試 detect_rooms_in_floor_plan()：能否從一張整戶平面圖抓出每個房間的邊界框。

執行方式（在專案根目錄）：
    python test/test_detect_rooms.py <平面圖圖片路徑>

輸出：
    test/artifacts/detect_rooms/<檔名>_boxes.png  ← 疊了偵測框的圖，用圖片檢視器打開比對是否對齊
"""

from __future__ import annotations

import sys
from pathlib import Path

# 讓 Python 找得到 designbridge 套件
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from designbridge.layout.layout_agent import detect_rooms_in_floor_plan

OUT_DIR = Path(__file__).resolve().parent / "artifacts" / "detect_rooms"


def run(image_path: str):
    from PIL import Image, ImageDraw

    src = Path(image_path)
    if not src.is_file():
        print(f"[FAIL] 找不到圖片：{src}")
        return

    rooms = detect_rooms_in_floor_plan(str(src))
    if not rooms:
        print("[FAIL] 沒有偵測到任何房間（Gemini 呼叫失敗或回傳空結果）")
        return

    print(f"[PASS] 偵測到 {len(rooms)} 個空間：")
    for r in rooms:
        print(f"  - {r['room_type']:<12} x={r['x']:.2f} y={r['y']:.2f} w={r['w']:.2f} h={r['h']:.2f}")

    img = Image.open(src).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img)
    for r in rooms:
        box = (r["x"] * W, r["y"] * H, (r["x"] + r["w"]) * W, (r["y"] + r["h"]) * H)
        color = "red" if r["room_type"] == "other" else "lime"
        draw.rectangle(box, outline=color, width=3)
        draw.text((box[0] + 4, box[1] + 4), r["room_type"], fill=color)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{src.stem}_boxes.png"
    img.save(out_path)
    print(f"\n疊框圖已存到：{out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python test/test_detect_rooms.py <平面圖圖片路徑>")
        sys.exit(1)
    run(sys.argv[1])
