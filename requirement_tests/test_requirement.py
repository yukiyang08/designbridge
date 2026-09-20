"""
test_requirement.py
獨立測試腳本：測試指令會產生什麼 Requirement JSON
放在專案根目錄（與 app.py 同層）執行即可。

用法：
    python test_requirement.py
    python test_requirement.py --prompt "我想把客廳改成北歐風"
    python test_requirement.py --batch   # 跑所有內建測試案例
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# ── 確保可以 import designbridge ──────────────────────────────────────────────
# 此檔案位於 requirement_tests/，需往上一層找到專案根目錄
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from designbridge.core.config import Config
from designbridge.core.nodes import (
    _call_gemini_requirement_analyzer,
    _rule_based_requirement_analyzer,
)

DEFAULT_SCOPE = 0.5  # scope 固定，不對外開放
OUTPUT_DIR = Path(__file__).parent / "outputs"

# ── 內建批次測試案例 ───────────────────────────────────────────────────────────
BATCH_CASES = [
    {"name": "北歐風客廳", "prompt": "我想把客廳改成北歐風，喜歡白色和木質感，希望光線充足"},
    {"name": "工業風書房", "prompt": "書房想要工業風，需要一張大書桌和收納架，常在家工作"},
    {"name": "家有寵物的臥室", "prompt": "臥室想改造，家裡有一隻狗，需要耐用好清理的材質，簡約風格"},
    {"name": "收納不足的廚房", "prompt": "廚房收納空間嚴重不足，想增加置物架和收納櫃"},
    {"name": "日式禪風浴室", "prompt": "浴室想改成日式禪風，使用自然石材，整體放鬆感"},
]


# ── 核心測試函式 ───────────────────────────────────────────────────────────────
def run_single_test(
    prompt: str,
    image: str = "無",
    force_rule_based: bool = False,
) -> dict:
    """執行單一測試，回傳 Requirement JSON。"""
    print(f"\n{'─'*60}")
    print(f"📝 指令：{prompt}")
    print(f"🖼️  圖片：{image}")
    print(f"{'─'*60}")

    if force_rule_based:
        print("⚙️  使用 Rule-based（強制）")
        result = _rule_based_requirement_analyzer(prompt, DEFAULT_SCOPE)
    else:
        try:
            api_key = Config.get_gemini_api_key()
            print("🤖 使用 Gemini API")
            result = _call_gemini_requirement_analyzer(prompt, DEFAULT_SCOPE, image, api_key)
        except (ValueError, RuntimeError) as e:
            print(f"⚠️  Gemini 不可用（{e}），改用 Rule-based")
            result = _rule_based_requirement_analyzer(prompt, DEFAULT_SCOPE)

    print("\n✅ Requirement JSON 輸出：")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    _save_json(result, prompt)
    _validate(result)
    return result


def _save_json(req: dict, prompt: str) -> None:
    """將 Requirement JSON 存成 .json 檔到 test_outputs/。"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 用指令前10字當檔名，移除特殊字元
    slug = "".join(c for c in prompt[:10] if c.isalnum() or c in "._- ").strip().replace(" ", "_")
    filename = f"requirement_{slug}_{timestamp}.json"
    out_path = OUTPUT_DIR / filename
    out_path.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"💾 已儲存：requirement_tests/outputs/{filename}")


def _validate(req: dict) -> None:
    """簡易驗證：印出缺少的必填欄位與預測路由。"""
    required_keys = [
        "meta", "style_preferences", "priority_weights",
        "hint_layout", "hint_style", "hint_adjuster",
    ]
    missing = [k for k in required_keys if k not in req]
    if missing:
        print(f"\n⚠️  缺少必填欄位：{missing}")
    else:
        print("\n✅ 結構驗證通過")

    if req.get("hint_adjuster"):
        routing = "design_adjuster"
    elif req.get("hint_layout") and req.get("hint_style"):
        routing = "layout_and_style"
    elif req.get("hint_layout"):
        routing = "layout"
    elif req.get("hint_style"):
        routing = "style"
    else:
        routing = "layout_and_style（預設）"
    print(f"🗺️  預測路由：→ {routing}")


def run_batch(force_rule_based: bool = False) -> None:
    """跑所有內建批次案例。"""
    print(f"\n{'═'*60}")
    print(f"🧪 批次測試：共 {len(BATCH_CASES)} 個案例")
    print(f"{'═'*60}")
    for i, case in enumerate(BATCH_CASES, 1):
        print(f"\n【案例 {i}/{len(BATCH_CASES)}】{case['name']}")
        run_single_test(case["prompt"], force_rule_based=force_rule_based)
    print(f"\n{'═'*60}")
    print("✅ 批次測試完成")


def interactive_mode(force_rule_based: bool = False) -> None:
    """互動輸入模式，持續測試直到輸入 quit。"""
    print("\n🎨 DesignBridge Requirement JSON 測試工具")
    print("輸入 'quit' 或 'q' 離開\n")
    while True:
        prompt = input("📝 請輸入設計指令：").strip()
        if prompt.lower() in ("quit", "q", ""):
            print("👋 結束測試")
            break
        run_single_test(prompt, force_rule_based=force_rule_based)


# ── 主程式 ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="測試 DesignBridge Requirement Analyzer")
    parser.add_argument("--prompt", "-p", type=str, help="設計指令文字")
    parser.add_argument("--image", "-i", type=str, default="無", help="圖片路徑（選填）")
    parser.add_argument("--batch", "-b", action="store_true", help="跑所有內建批次測試案例")
    parser.add_argument("--rule-based", "-r", action="store_true", help="強制使用 rule-based（不呼叫 Gemini）")
    args = parser.parse_args()

    if args.batch:
        run_batch(force_rule_based=args.rule_based)
    elif args.prompt:
        run_single_test(args.prompt, args.image, args.rule_based)
    else:
        interactive_mode(force_rule_based=args.rule_based)


if __name__ == "__main__":
    main()