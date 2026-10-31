"""局部修改／擴圖用的 FLUX.1 Fill dev（Modal）。跟主渲染的 designbridge-flux 分開部署，互不覆蓋。

modal run scripts/modal_flux/edit_app.py::download    # 下載 Fill dev 權重到共用 Volume（CPU，約 34 GB）
python scripts/modal_flux/deploy.py --app edit         # 部署（GPU／閒置等待同 .env 的 DESIGNBRIDGE_MODAL_MODE）
"""

import contextlib
import sys
from pathlib import Path

import modal

HERE = Path(__file__).parent
REPO = HERE.parents[1] if len(HERE.parents) > 1 else HERE
MOUNT = "/weights"

try:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
except Exception:
    pass

sys.path.insert(0, str(HERE))
from profiles import resolve  # noqa: E402

DEPLOY = resolve()

app = modal.App("designbridge-edit")
weights = modal.Volume.from_name("designbridge-weights")

_base = modal.Image.debian_slim(python_version="3.11").env({"HF_HOME": f"{MOUNT}/hf"})
download_image = _base.pip_install("huggingface_hub")
gpu_image = (
    _base.pip_install(
        "torch", "diffusers==0.42.1", "transformers", "accelerate", "sentencepiece",
        "protobuf", "safetensors", "pillow", "huggingface_hub",
    )
    .env({"HF_HUB_OFFLINE": "1"})
    .add_local_file(HERE / "fill_inference.py", "/root/fill_inference.py")
    .add_local_file(HERE / "profiles.py", "/root/profiles.py")
)


@app.function(
    image=download_image,
    volumes={MOUNT: weights},
    secrets=[modal.Secret.from_name("huggingface-secret")],
    timeout=3600,
)
def download():
    import subprocess

    from huggingface_hub import snapshot_download

    # 根目錄的單檔權重是給 ComfyUI 的，diffusers 用不到，省約 24 GB（gated：token 帳號要先在模型頁同意授權）
    snapshot_download("black-forest-labs/FLUX.1-Fill-dev",
                      ignore_patterns=["flux1-fill-dev.safetensors", "ae.safetensors", "*.jpg", "*.png"])
    weights.commit()
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
    gpu=DEPLOY["gpu"],
    volumes={MOUNT: weights},
    timeout=900,
    scaledown_window=DEPLOY["scaledown"],
)
class Editor:
    @modal.enter()
    def load(self):
        from fill_inference import FluxFiller

        with _plain_errors("load"):
            self.f = FluxFiller()
        self._served = 0

    @modal.method()
    def info(self) -> dict:
        return {"model": "FLUX.1-Fill-dev", "load_seconds": self.f.load_seconds}

    @modal.method()
    def fill(self, **kwargs) -> dict:
        with _plain_errors("fill"):
            out = self.f.fill(**kwargs)
        out["cold_start"] = self._served == 0
        out["load_seconds"] = self.f.load_seconds
        self._served += 1
        return out
