"""FLUX ControlNet 推論的 Modal 外殼（可行性驗證用，尚未接進後端）。

modal run scripts/modal_flux/modal_app.py::download          # 下載權重到 Volume（CPU，約 42 GB）
modal run scripts/modal_flux/modal_app.py::bench             # 跑 cases.json，結果存到 artifacts/modal_flux/
modal run scripts/modal_flux/modal_app.py::bench --steps 20,42 --lora on,off
"""

import contextlib
import json
import os
import shutil
import time
from pathlib import Path

import modal

HERE = Path(__file__).parent
REPO = HERE.parents[1] if len(HERE.parents) > 1 else HERE  # 容器內路徑較淺，REPO 只有本機入口會用到
MOUNT = "/weights"

# 部署時讀專案根目錄的 .env：GPU／閒置等待／常駐數量只在一處設定（容器內沒有 .env，值用不到）
try:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
except Exception:
    pass


import sys

sys.path.insert(0, str(HERE))
from profiles import resolve  # noqa: E402

DEPLOY = resolve()  # GPU／閒置等待：.env 的 DESIGNBRIDGE_MODAL_MODE


app = modal.App("designbridge-flux")
weights = modal.Volume.from_name("designbridge-weights")

_base = modal.Image.debian_slim(python_version="3.11").env({"HF_HOME": f"{MOUNT}/hf"})
download_image = _base.pip_install("huggingface_hub")
# 推論時權重都在 Volume，離線模式避免再連 Hugging Face（也就不需要 token）
gpu_image = (
    _base.pip_install(
        "torch", "diffusers==0.42.1", "transformers", "accelerate", "sentencepiece",
        "protobuf", "peft", "safetensors", "pillow", "huggingface_hub",
    )
    .env({"HF_HUB_OFFLINE": "1"})
    .add_local_file(HERE / "inference.py", "/root/inference.py")
    .add_local_file(HERE / "profiles.py", "/root/profiles.py")  # modal_app 在容器內也會被載入，import 得到
)


@app.function(
    image=download_image,
    volumes={MOUNT: weights},
    secrets=[modal.Secret.from_name("huggingface-secret")],
    timeout=3600,
)
def download():
    import os

    from huggingface_hub import snapshot_download

    # 根目錄的單檔權重（flux1-dev / ae）diffusers 格式用不到，省約 24 GB
    snapshot_download("black-forest-labs/FLUX.1-dev", ignore_patterns=["flux1-dev.safetensors", "ae.safetensors", "*.jpg"])
    snapshot_download("Shakker-Labs/FLUX.1-dev-ControlNet-Depth", allow_patterns=["config.json", "*.safetensors"])
    snapshot_download("InstantX/FLUX.1-dev-Controlnet-Canny", allow_patterns=["config.json", "*.safetensors"])
    snapshot_download("Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro", allow_patterns=["config.json", "*.safetensors"])
    snapshot_download("MovingForward/designbridge-flux-lora", allow_patterns=["flux1dev/*"])
    weights.commit()

    # 不能用 rglob 加總：快取裡的符號連結會讓大小重複計算
    import subprocess

    print("Volume 實體大小:", subprocess.run(["du", "-sh", f"{MOUNT}/hf/hub"], capture_output=True, text=True).stdout.strip())


@contextlib.contextmanager
def _plain_errors(stage: str):
    """torch 例外型別本機沒裝 torch 解不開，改成純文字錯誤丟回。"""
    try:
        yield
    except Exception:
        import traceback

        tb = traceback.format_exc()
        print(tb)
        raise RuntimeError(f"[{stage}] 容器內錯誤:\n{tb[-2500:]}") from None


@app.cls(
    image=gpu_image,
    gpu=DEPLOY["gpu"],  # 改了要重新 modal deploy（建議用 scripts/modal_flux/deploy.py）
    volumes={MOUNT: weights},
    timeout=900,
    # 閒置多久關掉；閒置期間仍計費。使用者按生圖時容器還活著才不用等冷啟動
    scaledown_window=DEPLOY["scaledown"],
)
class Renderer:
    # two = 深度 + 邊緣兩個獨立 ControlNet；union = Union-Pro。每個模式各自有獨立的容器與冷啟動
    mode: str = modal.parameter(default="two")

    @modal.enter()
    def load(self):
        from inference import FluxRenderer

        with _plain_errors("load"):
            self.r = FluxRenderer(mode=self.mode)
        self._served = 0  # 這個容器已處理幾次呼叫；第一次就是「冷啟動」那一次

    @modal.method()
    def info(self) -> dict:
        from inference import versions

        return {**versions(), "mode": self.mode, "load_seconds": self.r.load_seconds}

    @modal.method()
    def render(self, **kwargs) -> dict:
        with _plain_errors("render"):
            out = self.r.generate(**kwargs)
        # 讓呼叫端（後端耗時面板）知道這次是不是被冷啟動拖慢
        out["cold_start"] = self._served == 0
        out["load_seconds"] = self.r.load_seconds
        self._served += 1
        return out


def _read(rel: str | None) -> bytes | None:
    return (REPO / rel).read_bytes() if rel else None


@app.local_entrypoint()
def bench(cases: str = "cases.json", out: str = "artifacts/modal_flux", steps: str = "", lora: str = "on", repeat: int = 1, cn: str = "1", mode: str = "two"):
    """cn：ControlNet 強度倍率清單（0 = 關閉、1 = 照案例設定、2 = 加倍），例如 --cn 0,1,2；mode：two | union"""
    spec = json.loads((HERE / cases).read_text(encoding="utf-8"))["cases"]
    outdir = REPO / out
    outdir.mkdir(parents=True, exist_ok=True)

    renderer = Renderer(mode=mode)
    t0 = time.time()
    print("環境:", renderer.info.remote(), f"(首次呼叫含冷啟動，共 {time.time() - t0:.1f}s)")

    rows = []
    for c in spec:
        for st in [int(s) for s in steps.split(",")] if steps else [c["steps"]]:
            for mode in lora.split(","):
                for m in [float(x) for x in cn.split(",")]:
                    for k in range(1, repeat + 1):
                        t = time.time()
                        res = renderer.render.remote(
                            prompt=c["prompt"], depth_png=_read(c["depth"]), edge_png=_read(c.get("edge")),
                            width=c["width"], height=c["height"], steps=st, guidance=c["guidance"],
                            depth_scale=c["depth_scale"] * m, edge_scale=c["edge_scale"] * m,
                            depth_end=c["depth_end"], edge_end=c["edge_end"], seed=c.get("seed"),
                            lora_style=c["style"] if mode == "on" else None,
                        )
                        wall = round(time.time() - t, 2)
                        name = f"{c['name']}_s{st}_lora{mode}_cn{m:g}_r{k}.png"
                        (outdir / name).write_bytes(res.pop("png"))
                        row = {"case": c["name"], "steps": st, "lora": mode, "cn": m, "run": k, "wall_seconds": wall, **res}
                        rows.append(row)
                        print(row)
        if c.get("baseline"):
            shutil.copy(REPO / c["baseline"], outdir / f"{c['name']}_baseline_fal.png")

    (outdir / "metrics.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"結果存到 {outdir}")
