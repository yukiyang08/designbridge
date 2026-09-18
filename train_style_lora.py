"""用 fal.ai API 訓練單一風格的 Flux LoRA。

沿用 designbridge_flux_lora_v4 notebook 的訓練邏輯，只是把 base/trainer 換成 fal 的
`fal-ai/flux-lora-fast-training`（底層就是 FLUX.1-dev + ai-toolkit 配方）：
  - per-style LoRA，trigger word = dsgnbrg_<style>（已寫進每張 caption，不靠 fal 的 trigger 欄位）
  - steps = clamp(n_imgs * 15, 500, 2000)，可用 --steps 覆蓋
  - caption 保留（fal 有 caption 時會用 caption、忽略 trigger_word）

資料來源二選一：
  （預設）現撈 Supabase：呼叫 export_dataset.py --style <style> 產生乾淨的單風格 zip
  --zip PATH          從既有 zip 篩出該風格、修正 caption trigger word 後重新打包

用法：
  python train_style_lora.py                          # 互動選單
  python train_style_lora.py --style american         # 直接指定，現撈 Supabase
  python train_style_lora.py --style luxury --steps 1500 --yes
  python train_style_lora.py --style industrial --zip /path/to/dataset_triggered_v3.zip

需要 .env：SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY（現撈時）、FAL_KEY。
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")

STYLES = [
    "modern", "country", "classic", "nordic", "industrial",
    "japanese", "american", "luxury", "neoclassic", "other",
]
FILENAME_PATTERN = re.compile(r"^(\d+)_([a-zA-Z]+)\.(jpg|jpeg|png|txt)$", re.IGNORECASE)

TRAIN_ENDPOINT = "fal-ai/flux-lora-fast-training"
PRICE_PER_STEP_USD = 0.02  # fal MCP 回報值，實際以 dashboard 為準
LEDGER = ROOT / "trained_loras.json"


def choose_style() -> str:
    print("\n可訓練的風格：\n")
    for i, s in enumerate(STYLES, 1):
        print(f"  {i}. {s}")
    while True:
        raw = input("\n選擇要訓練的風格（編號或名稱）：").strip().lower()
        if raw.isdigit() and 1 <= int(raw) <= len(STYLES):
            return STYLES[int(raw) - 1]
        if raw in STYLES:
            return raw
        print("  輸入無效，再試一次。")


def zip_from_supabase(style: str) -> Path:
    """呼叫既有的 export_dataset.py 產生乾淨的單風格 zip（caption 已含 dsgnbrg_<style> 前綴）。"""
    print(f"\n📥 從 Supabase 現撈 {style}（export_dataset.py）...")
    subprocess.run(
        [sys.executable, str(ROOT / "export_dataset.py"), "--style", style],
        check=True, cwd=ROOT,
    )
    zip_path = ROOT / f"designbridge_dataset_{style}.zip"
    if not zip_path.exists():
        sys.exit(f"❌ 預期的 zip 沒產生：{zip_path}")
    return zip_path


def zip_from_existing(style: str, src_zip: Path) -> Path:
    """從既有 zip 篩出該風格的圖文組，修正 caption trigger word，重新打包成單風格 zip。"""
    if not src_zip.exists():
        sys.exit(f"❌ 找不到 zip：{src_zip}")
    trigger = f"dsgnbrg_{style}"
    work = ROOT / "_lora_prep"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    with zipfile.ZipFile(src_zip) as z:
        z.extractall(work)

    groups: dict[str, dict] = {}
    for path in glob.glob(f"{work}/**/*.*", recursive=True):
        m = FILENAME_PATTERN.match(os.path.basename(path))
        if not m:
            continue
        idx, fstyle, ext = m.groups()
        if fstyle.lower() != style:
            continue
        groups.setdefault(idx, {})["caption" if ext.lower() == "txt" else "img"] = path
        if ext.lower() != "txt":
            groups[idx]["ext"] = ext

    complete = {i: e for i, e in groups.items() if "img" in e and "caption" in e}
    if not complete:
        sys.exit(f"❌ zip 裡沒有 {style} 的完整圖文組")

    out_zip = ROOT / f"designbridge_dataset_{style}.zip"
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, e in complete.items():
            caption = Path(e["caption"]).read_text(encoding="utf-8")
            caption = re.sub(r"dsgnbrg\w*", trigger, caption, flags=re.IGNORECASE)
            if trigger not in caption:
                caption = f"{trigger}, {caption}"
            zf.write(e["img"], f"{idx}_{style}.{e['ext']}")
            zf.writestr(f"{idx}_{style}.txt", caption)
    shutil.rmtree(work, ignore_errors=True)
    return out_zip


def count_images(zip_path: Path) -> int:
    with zipfile.ZipFile(zip_path) as z:
        return sum(1 for n in z.namelist() if n.lower().endswith((".jpg", ".jpeg", ".png")))


def sample_caption(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.lower().endswith(".txt"):
                return z.read(n).decode("utf-8").strip()
    return ""


def train(style: str, zip_path: Path, steps: int) -> dict:
    import fal_client

    if not os.environ.get("FAL_KEY"):
        sys.exit("❌ .env 缺 FAL_KEY")

    print("\n☁️  上傳 zip 到 fal...")
    images_data_url = fal_client.upload_file(str(zip_path))
    print(f"🚀 訓練中（{TRAIN_ENDPOINT}，steps={steps}）...")

    def on_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in (update.logs or []):
                print(f"   [fal] {log.get('message', '')}")

    return fal_client.subscribe(
        TRAIN_ENDPOINT,
        arguments={
            "images_data_url": images_data_url,
            "steps": steps,
            "is_style": False,      # zip 內含 .txt caption（已帶 dsgnbrg_<style>），不走 trigger-word-only
            "create_masks": False,  # 室內空間沒有要遮罩的主體
        },
        with_logs=True,
        on_queue_update=on_update,
    )


def save_ledger(style: str, steps: int, result: dict) -> str | None:
    ledger = json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else {}
    url = (result.get("diffusers_lora_file") or {}).get("url")
    ledger[style] = {
        "lora_url": url,
        "config_url": (result.get("config_file") or {}).get("url"),
        "trigger": f"dsgnbrg_{style}",
        "steps": steps,
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    LEDGER.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    return url


def main():
    ap = argparse.ArgumentParser(description="用 fal.ai 訓練單一風格 Flux LoRA")
    ap.add_argument("--style", choices=STYLES, help="要訓練的風格（省略則進互動選單）")
    ap.add_argument("--zip", help="從既有 zip 篩該風格（省略則現撈 Supabase）")
    ap.add_argument("--steps", type=int, help="訓練步數（省略則 clamp(n*15, 500, 2000)）")
    ap.add_argument("--yes", action="store_true", help="跳過費用確認")
    args = ap.parse_args()

    style = args.style or choose_style()

    zip_path = zip_from_existing(style, Path(args.zip)) if args.zip else zip_from_supabase(style)
    n_imgs = count_images(zip_path)
    steps = args.steps or min(max(n_imgs * 15, 500), 2000)

    print(f"\n✅ {zip_path.name}（{zip_path.stat().st_size / 1e6:.1f} MB，{n_imgs} 張）")
    print(f"   trigger：dsgnbrg_{style}")
    print(f"   caption 範例：{sample_caption(zip_path)[:120]}")
    if n_imgs < 30:
        print(f"⚠️  只有 {n_imgs} 張，LoRA 效果可能偏弱（建議 ≥ 30）")

    est = steps * PRICE_PER_STEP_USD
    print(f"\n風格：{style}  步數：{steps}  估計費用：~${est:.0f} USD")
    if not args.yes and input("確認開始？(y/N) ").strip().lower() != "y":
        sys.exit("已取消")

    result = train(style, zip_path, steps)
    url = save_ledger(style, steps, result)

    print("\n✅ 訓練完成")
    print(f"   LoRA:    {url}")
    print(f"   trigger: dsgnbrg_{style}")
    print(f"   已記錄到 {LEDGER.name}")


if __name__ == "__main__":
    main()
