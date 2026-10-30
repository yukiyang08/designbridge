"""路由決策（DB-F-004）AI 判斷層正確率：30 條指令，局部編輯與全新設計各半，呼叫真實 Gemini。

標準答案依 requirement_analyzer prompt 自己的判斷規則：
  局部編輯（design_adjuster）＝針對畫面中「已存在」物件的移除／替換／改色；
  全新設計（design）＝風格或整體調整、新增家具、指定家具擺放位置；不確定時預設全新設計。
每條指令都附同一張室內照片；全新設計中最後五條為模糊指令（沒有指明單一既有物件）。指令文字刻意不直接引用 prompt 內的範例。用法：python scripts/eval_routing_accuracy.py out.json
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from designbridge.core.nodes.requirement import _call_llm_requirement_analyzer  # noqa: E402

PHOTO = str(ROOT / "test" / "test_picture" / "室內.jpg")

ADJUST = [
    "把沙發換成綠色", "沙發顏色太亮了，換成深灰色", "把左邊那張椅子換成黑色", "把電視拿掉", "把茶几移除",
    "把電視櫃換成白色", "拿掉地毯", "把床單換成灰色", "把吊燈換成黑色", "移除牆上的掛畫",
    "把餐椅換成木頭材質", "把書桌換成黑色", "把窗簾換成米色", "拿掉角落的盆栽", "把抱枕換成藍色",
]
DESIGN = [
    "改成美式鄉村風格", "整體色調換成淺木色系", "在牆上加一面鏡子", "在沙發旁邊加一個邊桌", "把餐桌移到客廳中間",
    "改造成地中海風格", "沙發面對電視牆，茶几放中間", "重新安排客廳動線", "把書房改成開放式", "在窗邊放一張餐桌",
    "氣氛溫馨一點", "讓客廳更有質感", "感覺有點單調", "沙發看起來太老氣了", "房間太暗了",   # 後五條為模糊指令，依預設規則應走全新設計
]
CASES = [(t, "design_adjuster") for t in ADJUST] + [(t, "design") for t in DESIGN]

out = []
for text, expected in CASES:
    t0 = time.perf_counter()
    try:
        got = _call_llm_requirement_analyzer(text, PHOTO).get("_routing_decision")
    except Exception as e:  # 呼叫失敗時系統預設走全新設計
        got = f"ERROR:{type(e).__name__}"
    dt = time.perf_counter() - t0
    out.append(dict(text=text, expected=expected, got=got, seconds=round(dt, 1)))
    print(f"{'OK ' if got == expected else 'XX '} 預期={expected:15s} 實際={got}  {dt:4.1f}s  {text}", flush=True)
    time.sleep(0.5)

ok = sum(1 for r in out if r["got"] == r["expected"])
adj = [r for r in out if r["expected"] == "design_adjuster"]
des = [r for r in out if r["expected"] == "design"]
print(f"RESULT 全部 {ok}/{len(out)} = {ok / len(out):.1%}")
print(f"RESULT 局部編輯 {sum(r['got'] == r['expected'] for r in adj)}/{len(adj)}；全新設計 {sum(r['got'] == r['expected'] for r in des)}/{len(des)}")
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf8")
