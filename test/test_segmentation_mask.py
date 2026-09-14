"""
測試 mask_from_segmentation() 能否從 UPerNet 輸出正確產生遮罩。

執行方式（在專案根目錄）：
    python test/test_segmentation_mask.py

輸出：
    artifacts/test_masks/mask_<label>.png  ← 用圖片檢視器打開確認白色區域位置
"""

from __future__ import annotations

import sys
from pathlib import Path

# 讓 Python 找得到 designbridge 套件
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from designbridge.render.inpaint import mask_from_segmentation, fallback_center_mask

# ── 設定：改成你要測試的 task_id ────────────────────────────────────────────────
VISION_DIR = Path(__file__).resolve().parent.parent / "artifacts" / "vision"
OUT_DIR    = Path(__file__).resolve().parent / "artifacts" / "test_masks"

# 自動選第一個有 segmentation 的 task
def _pick_task() -> Path | None:
    # 還沒跑過生圖流程時 artifacts/vision/ 根本不存在，iterdir() 會直接拋
    # FileNotFoundError，蓋掉底下那句本來就寫好的友善提示。
    if not VISION_DIR.is_dir():
        return None
    for d in sorted(VISION_DIR.iterdir()):
        if (d / "segmentation.png").exists() and (d / "segmentation_meta.json").exists():
            return d
    return None


def run():
    task_dir = _pick_task()
    if task_dir is None:
        print("[FAIL] artifacts/vision/ 裡沒有找到 segmentation 檔案，請先跑一次生圖流程")
        return

    seg_path  = str(task_dir / "segmentation.png")
    meta_path = str(task_dir / "segmentation_meta.json")
    print(f"使用: {task_dir.name}")

    # 讀 segmentation_meta 取得可用標籤
    import json
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    present = list(meta.get("present_labels", {}).values())
    print(f"偵測到的物件: {present}\n")

    # 用 depth.png 推算圖片尺寸（原圖不一定存在）
    from PIL import Image
    depth_path = task_dir / "depth.png"
    if depth_path.exists():
        img_size = Image.open(depth_path).size
    else:
        img_size = (512, 512)
    print(f"圖片尺寸: {img_size}\n")

    # 測試幾個常見標籤
    test_labels = ["chair", "armchair", "sofa", "couch", "curtain", "wall", "floor", "table", "bed"]
    # 只測試這張圖有的標籤
    test_labels = [l for l in test_labels if any(l in p for p in present)]
    if not test_labels:
        test_labels = present[:4]   # fallback: 直接取前四個

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_pass = True

    for label in test_labels:
        mask, matched = mask_from_segmentation(seg_path, meta_path, [label], img_size)
        white = sum(1 for p in mask.getdata() if p > 128)
        total = mask.width * mask.height
        ratio = white / total if total else 0

        out = OUT_DIR / f"mask_{label.replace(' ', '_')}.png"
        mask.save(str(out))

        status = "PASS" if ratio > 0 else "FAIL"
        if ratio == 0:
            all_pass = False
        print(f"[{status}] {label:25s}  白色像素: {white:>6}/{total}  ({ratio:.1%})  -> {out.name}")

    print()
    if all_pass:
        print("全部通過，遮罩生成正常。打開 artifacts/test_masks/ 確認白色區域位置。")
    else:
        print("有標籤回傳空遮罩，請確認 mask_from_segmentation() 的 label 對應邏輯。")


if __name__ == "__main__":
    run()
