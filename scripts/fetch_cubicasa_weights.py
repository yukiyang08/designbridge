"""下載 CubiCasa5K 官方權重，轉成只含權重的 state_dict（正式流程用 weights_only=True 安全載入）。

官方檔是舊版 pickle（可能執行任意程式碼），只在這裡、從官方 README 的連結讀一次。
權重 CC BY-NC 4.0，只限非商業用途；存到 models/cubicasa/（git 已忽略）。

    python scripts/fetch_cubicasa_weights.py
    python scripts/fetch_cubicasa_weights.py --from path/to/model_best_val_loss_var.pkl   # 已下載過
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 官方 README 的權重連結（Google Drive）
URL = "https://drive.usercontent.google.com/download?id=1gRB7ez1e4H7a9Y09lLqRuna0luZO5VRK&export=download&confirm=t"


def main() -> None:
    import torch

    from designbridge.core.config import Config
    from designbridge.layout.cubicasa_model import hg_furukawa_original

    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", help="已下載的官方 .pkl")
    args = ap.parse_args()

    out = Path(Config.CUBICASA_WEIGHTS)
    out = out if out.is_absolute() else ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.src:
        pkl = Path(args.src)
    else:
        pkl = Path(tempfile.mkdtemp()) / "model_best_val_loss_var.pkl"
        print("下載官方權重（約 200 MB）…")
        urllib.request.urlretrieve(URL, pkl)
    state = torch.load(pkl, map_location="cpu", weights_only=False)["model_state"]
    # 確認跟搬進專案的網路定義對得上，再存
    hg_furukawa_original(n_classes=44).load_state_dict(state)
    torch.save(state, out)
    if not args.src:
        pkl.unlink()
    print(f"done → {out}（{out.stat().st_size / 1e6:.0f} MB）")


if __name__ == "__main__":
    main()
