# DesignBridge FastAPI 後端
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()  # 必須先於 routers 匯入（API_PUBLIC_URL 在匯入時讀取）

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import floorplan, generate, history, style


@asynccontextmanager
async def _app_lifespan(_: FastAPI):
    """Preload heavy ML stacks in background so the server accepts requests immediately."""
    import threading

    def _warmup():
        try:
            from designbridge.core.warmup import run_startup_warmup
            run_startup_warmup()
        except Exception as e:
            print(f"⚠️ DesignBridge startup warmup failed: {e}")

    threading.Thread(target=_warmup, daemon=True).start()
    yield


app = FastAPI(
    title="DesignBridge API",
    description="室內設計 AI 工作流接口",
    lifespan=_app_lifespan,
)

artifacts_dir = Path("artifacts")
artifacts_dir.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir)), name="artifacts")

style_images_dir = Path("style_kb/images")
if style_images_dir.exists():
    app.mount("/style-images", StaticFiles(directory=str(style_images_dir)), name="style-images")

debug_console_dir = Path("debug-console")
if debug_console_dir.exists():
    app.mount("/debug-console", StaticFiles(directory=str(debug_console_dir), html=True), name="debug-console")

# 解決前後端跨域問題 (具備彈性與擴充性的解法)
cors_origins = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,             # 讀取 .env 中的自訂網域 (適合正式上線環境)
    allow_origin_regex=r"^https?://localhost:\d+$", # 允許所有 localhost 的開發埠號 (適合開發環境，不用再一直加 5174, 5175...)
    allow_methods=["*"],
    allow_headers=["*"],
)


for _r in (history, style, floorplan, generate):
    app.include_router(_r.router)


@app.get("/api/health")
def health():
    """Lightweight readiness probe for the frontend (no ML load)."""
    return {"status": "ok"}



@app.get("/")
def read_root():
    return {"message": "DesignBridge API is running"}
