# designbridge/config.py
"""DesignBridge 設定：憑證與模型名走環境變數；ControlNet 調參的來由見 docs/experiments/CONTROLNET_PARAM_TEST.md。"""

import os
from pathlib import Path

import dotenv

# 先載專案根目錄的 .env，再允許工作目錄的 .env 覆寫
_root = Path(__file__).resolve().parent.parent.parent
dotenv.load_dotenv(_root / ".env")
dotenv.load_dotenv()


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


class Config:
    # ── LLM：Gemini（直連 API key 或 Vertex）─────────────────────────────
    GEMINI_MODEL: str = os.getenv("DESIGNBRIDGE_GEMINI_MODEL", "gemini-3.6-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    GEMINI_API_KEYS: str = os.getenv("GEMINI_API_KEYS", "")  # 備援 key，逗號分隔，依序嘗試
    GEMINI_TEMPERATURE: float = 0.3
    # thinking token 上限：0 關閉（抽取/翻譯/辨識不需要）、-1 由模型決定
    GEMINI_THINKING_BUDGET: int = int(os.getenv("DESIGNBRIDGE_GEMINI_THINKING_BUDGET", "0"))

    # Vertex 模式：不用 API key，改用 service-account JSON 驗證
    GOOGLE_GENAI_USE_VERTEXAI: bool = _flag("GOOGLE_GENAI_USE_VERTEXAI", "")
    GOOGLE_GENAI_FORCE_API_KEY: bool = _flag("GOOGLE_GENAI_FORCE_API_KEY", "")
    GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")

    # 消融實驗用：call_llm() 的 provider（gemini | qwen | llama），正式流程固定 gemini
    LLM_PROVIDER: str = os.getenv("DESIGNBRIDGE_LLM_PROVIDER", "gemini")
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_BASE_URL: str = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    QWEN_MODEL: str = os.getenv("DESIGNBRIDGE_QWEN_MODEL", "qwen3-vl-30b-a3b-instruct")
    LLAMA_MODEL: str = os.getenv("DESIGNBRIDGE_LLAMA_MODEL", "meta/llama-4-scout-17b-16e-instruct-maas")
    LLAMA_LOCATION: str = os.getenv("DESIGNBRIDGE_LLAMA_LOCATION", "us-east5")

    # ── 出圖後端：fal.ai / Hugging Face ──────────────────────────────────
    FAL_KEY: str | None = os.getenv("FAL_KEY")
    # 預設 Fill dev（公開權重，可自架）；要用閉源的 Fill Pro 設成 fal-ai/flux-pro/v1/fill
    FAL_INPAINT_MODEL: str = os.getenv("DESIGNBRIDGE_FAL_INPAINT_MODEL", "fal-ai/flux-lora-fill")
    # 局部修改改用可下載的 Fill dev（fal-ai/flux-lora-fill）時的 guidance
    FAL_INPAINT_DEV_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_FAL_INPAINT_DEV_GUIDANCE", "30"))

    HF_TOKEN: str | None = os.getenv("HF_TOKEN")
    ENABLE_HF_INFERENCE: bool = _flag("DESIGNBRIDGE_ENABLE_HF_INFERENCE", "true")
    HF_INFERENCE_PROVIDER: str = os.getenv("DESIGNBRIDGE_HF_INFERENCE_PROVIDER", "hf-inference")
    FLUX_MODEL: str = os.getenv("DESIGNBRIDGE_FLUX_MODEL", "black-forest-labs/FLUX.1-schnell")

    KONTEXT_LORA_MODEL: str = "thedeoxen/FLUX.1-Kontext-dev-reference-depth-fusion-LORA"
    KONTEXT_PROVIDER: str = os.getenv("DESIGNBRIDGE_KONTEXT_PROVIDER", "fal-ai")


    # ── Outpaint（環景擴圖）─────────────────────────────────────────────
    # 用 flux-general/inpainting：flux-pro/fill 沒有 negative_prompt，壓不掉浮水印與招牌字
    FAL_OUTPAINT_MODEL: str = os.getenv("DESIGNBRIDGE_FAL_OUTPAINT_MODEL", "fal-ai/flux-general/inpainting")
    OUTPAINT_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_OUTPAINT_GUIDANCE", "2.2"))
    OUTPAINT_STEPS: int = int(os.getenv("DESIGNBRIDGE_OUTPAINT_STEPS", "28"))
    OUTPAINT_NAG_SCALE: float = float(os.getenv("DESIGNBRIDGE_OUTPAINT_NAG_SCALE", "5.0"))  # 越高越遠離 negative
    # negative 兩組：文字浮水印、會被重複生成的家具
    OUTPAINT_NEGATIVE_TEXT: str = os.getenv(
        "DESIGNBRIDGE_OUTPAINT_NEGATIVE_TEXT",
        "text, letters, words, lettering, typography, font, caption, subtitle, "
        "watermark, logo, brand mark, signature, copyright notice, stamp, "
        "sign, signage, banner, poster, label, nameplate, writing, "
        "collage, photo grid, contact sheet, catalogue page",
    )
    OUTPAINT_NEGATIVE_DUPES: str = os.getenv(
        "DESIGNBRIDGE_OUTPAINT_NEGATIVE_DUPES",
        "television, tv screen, monitor, fireplace, media cabinet, sideboard, "
        "sofa, potted plant, duplicated furniture, repeated furniture, "
        "mirrored room, cluttered",
    )

    @classmethod
    def outpaint_negative_prompt(cls) -> str:
        return f"{cls.OUTPAINT_NEGATIVE_TEXT}, {cls.OUTPAINT_NEGATIVE_DUPES}"

    # ── ControlNet（文字生成流程）：家具輪廓 canny + 房間外殼 depth ───────────
    ENABLE_LAYOUT_CONTROLNET: bool = _flag("DESIGNBRIDGE_ENABLE_LAYOUT_CONTROLNET", "true")
    FAL_DEPTH_CONTROLNET_MODEL: str = os.getenv(
        "DESIGNBRIDGE_FAL_DEPTH_CONTROLNET_MODEL", "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro"
    )
    # Union 模型的 control_mode：canny | tile | depth | blur | pose | gray | low-quality
    FAL_DEPTH_CONTROL_MODE: str = os.getenv("DESIGNBRIDGE_FAL_DEPTH_CONTROL_MODE", "depth")
    # canny 管家具位置與大小（主訊號，太低家具會漂移）；depth 只管牆窗結構，刻意壓低
    FAL_EDGE_CONDITIONING_SCALE: float = float(os.getenv("DESIGNBRIDGE_FAL_EDGE_CONDITIONING_SCALE", "0.35"))
    FAL_DEPTH_CONDITIONING_SCALE: float = float(os.getenv("DESIGNBRIDGE_FAL_DEPTH_CONDITIONING_SCALE", "0.30"))
    FAL_DEPTH_STEPS: int = int(os.getenv("DESIGNBRIDGE_FAL_DEPTH_STEPS", "42"))
    FAL_DEPTH_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_FAL_DEPTH_GUIDANCE", "4.2"))
    # 控制只作用在前段去噪：結構早期就定下，後段讓模型自由處理材質與細節（1.0 = 全程控制）
    FAL_DEPTH_CONTROL_END: float = float(os.getenv("DESIGNBRIDGE_FAL_DEPTH_CONTROL_END", "0.4"))
    # canny 稍晚結束但不到最後，避免輪廓線殘留成地板線框
    FAL_EDGE_CONTROL_END: float = float(os.getenv("DESIGNBRIDGE_FAL_EDGE_CONTROL_END", "0.55"))
    # 深度圖裡家具畫成粗略語意輪廓（床、沙發、桌）而非方塊；關掉低矮家具會被畫成地墊
    ENABLE_SEMANTIC_SHAPES: bool = _flag("DESIGNBRIDGE_ENABLE_SEMANTIC_SHAPES", "true")

    # 佈局控制圖的鏡頭：站在近側一角、看向對角牆角的兩點透視斜角視角（左右角落由遮擋評分挑）。
    # SETBACK 為負代表站在房內。回到正面視角：EYE_X_FRAC=0.5 TARGET_X_FRAC=0.5 SETBACK=1.6
    # TARGET_DEPTH_FRAC=0.6 FOV=65
    LAYOUT_CAM_EYE_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_EYE_H", "1.6"))
    LAYOUT_CAM_SETBACK: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_SETBACK", "-0.3"))
    LAYOUT_CAM_TARGET_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_H", "0.9"))
    LAYOUT_CAM_TARGET_DEPTH_FRAC: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_DEPTH_FRAC", "1.0"))
    LAYOUT_CAM_FOV: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_FOV", "58"))
    LAYOUT_CAM_EYE_X_FRAC: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_EYE_X_FRAC", "0.06"))
    LAYOUT_CAM_TARGET_X_FRAC: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_X_FRAC", "0.9"))
    # 小房間（浴室、廁所）相機離瞄準點太近，前景會被設備塞滿：不足這個水平距離（公尺）就沿房深
    # 往後退（可退到近牆外，近牆會被剔除），同時把眼高提到 SMALL_ROOM_EYE_H。主臥以上的房間不受影響
    LAYOUT_CAM_MIN_VIEW_DIST: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_MIN_VIEW_DIST", "3.5"))
    LAYOUT_CAM_SMALL_ROOM_EYE_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_SMALL_ROOM_EYE_H", "1.8"))

    # ── ControlNet（有深度圖的流程）：照片深度 / 投影深度 ──────────────────
    # 重排佈局時的深度來源：controlnet（現行）| kontext（品質不穩，僅供參考）
    LAYOUT_DEPTH_CONTROL_BACKEND: str = os.getenv("DESIGNBRIDGE_LAYOUT_DEPTH_CONTROL_BACKEND", "controlnet")
    DEPTH_CONTROLNET_MODEL: str = os.getenv(
        "DESIGNBRIDGE_DEPTH_CONTROLNET_MODEL", "Shakker-Labs/FLUX.1-dev-ControlNet-Depth"
    )
    FAL_CONTROLNET_STEPS: int = int(os.getenv("DESIGNBRIDGE_FAL_CONTROLNET_STEPS", "20"))
    FAL_CONTROLNET_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_FAL_CONTROLNET_GUIDANCE", "3.5"))
    # 自架 GPU（Modal，需先 modal deploy scripts/modal_flux/modal_app.py）：打開後 ControlNet 生圖先走它，
    # 失敗／逾時／不支援的模型組合都退回 fal
    # 一個變數切換：off（預設，全走 fal）｜dev 省錢、不暖機｜demo 展示、進 /studio 就暖機。GPU／閒置等待見 scripts/modal_flux/profiles.py
    MODAL_MODE: str = os.getenv("DESIGNBRIDGE_MODAL_MODE", "off").strip().lower()
    USE_MODAL_GPU: bool = MODAL_MODE in ("dev", "demo")
    MODAL_APP_NAME: str = os.getenv("DESIGNBRIDGE_MODAL_APP_NAME", "designbridge-flux")
    MODAL_TIMEOUT_S: float = float(os.getenv("DESIGNBRIDGE_MODAL_TIMEOUT_S", "120"))  # 含冷啟動約 35~60 秒
    # 局部修改／擴圖走自架 Fill dev（另一個部署 designbridge-edit，見 scripts/modal_flux/edit_app.py）；失敗退回 fal
    USE_MODAL_EDIT: bool = USE_MODAL_GPU and _flag("DESIGNBRIDGE_MODAL_EDIT", "false")
    MODAL_EDIT_APP_NAME: str = os.getenv("DESIGNBRIDGE_MODAL_EDIT_APP_NAME", "designbridge-edit")
    # 暖機：先叫起容器，使用者按生圖時就不用等冷啟動；只暖 Union 路徑（CAD／平面圖流程）
    MODAL_WARMUP: str = "studio" if MODAL_MODE == "demo" else "off"
    MODAL_WARMUP_MODES: str = "union"
    # 投影深度是軸對齊方塊，條件過強會讓家具漂浮成方塊，故設上限
    PROJECTED_DEPTH_MAX_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_PROJECTED_DEPTH_MAX_CONDITIONING_SCALE", "0.3")
    )
    REAL_PHOTO_DEPTH_CONTROL_END: float = float(os.getenv("DESIGNBRIDGE_REAL_PHOTO_DEPTH_CONTROL_END", "0.7"))
    # A/B 實測（2026-09-28）：>=0.85 會把平坦深度區（遠牆）畫成雜訊，0.6 穩定；
    # RA 預設給 0.85~1.0，所以在這裡封頂。單靠 CONTROL_END 或關 edge 都修不好
    REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE", "0.65")
    )

    # 第二個 ControlNet：分割圖抽出的物件邊界（FLUX 沒有公開的 seg ControlNet，改用 canny 吃邊界線）
    ENABLE_EDGE_CONTROL: bool = _flag("DESIGNBRIDGE_ENABLE_EDGE_CONTROL", "true")
    EDGE_CONTROLNET_MODEL: str = os.getenv("DESIGNBRIDGE_EDGE_CONTROLNET_MODEL", "InstantX/FLUX.1-dev-Controlnet-Canny")
    EDGE_CONTROLNET_MODE: str = os.getenv("DESIGNBRIDGE_EDGE_CONTROLNET_MODE", "")  # Union 型才需要 mode，獨立型留空
    # 遠低於 depth：邊界只補強幾何，不該蓋過它（分割碎塊會變成多餘接縫）
    EDGE_CONDITIONING_SCALE: float = float(os.getenv("DESIGNBRIDGE_EDGE_CONDITIONING_SCALE", "0.3"))

    # ── 換風格 / 微調 ───────────────────────────────────────────────────
    # 換風格是否沿用上一張圖補算的深度（舊行為）：該深度在窗戶/遠牆是雜訊，預設關
    STYLE_SWAP_DEPTH_LOCK: bool = _flag("DESIGNBRIDGE_STYLE_SWAP_DEPTH_LOCK", "false")
    ADJUSTER_INPAINT_STRENGTH: float = float(os.getenv("DESIGNBRIDGE_ADJUSTER_INPAINT_STRENGTH", "0.85"))

    # ── 視覺預處理：深度 + 分割（首次執行會下載模型）─────────────────────────
    ENABLE_DEPTH: bool = True
    ENABLE_SEGMENTATION: bool = True
    # Small 就夠：樓地板當平面擬合、遠牆取穩健百分位，與 Large 差 4px 但 CPU 快 7 倍（16.7s→2.3s）
    DEPTH_MODEL: str = os.getenv("DESIGNBRIDGE_DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Small-hf")
    SEGMENTATION_MODEL: str = os.getenv("DESIGNBRIDGE_SEGMENTATION_MODEL", "openmmlab/upernet-convnext-small")
    # 深度/分割圖長邊上限（模型內部本來就縮到約 512，更大只會拖慢後續處理；0 = 不限）
    VISION_MAX_EDGE: int = int(os.getenv("DESIGNBRIDGE_VISION_MAX_EDGE", "1280"))
    VISION_PARALLEL: bool = _flag("DESIGNBRIDGE_VISION_PARALLEL", "true")  # 深度與分割並行，實測快 35%
    VISION_CACHE: bool = _flag("DESIGNBRIDGE_VISION_CACHE", "true")  # 同一張照片重用結果

    # ── 佈局 agent 與投影 ───────────────────────────────────────────────
    ARTIFACTS_DIR: str = os.getenv("DESIGNBRIDGE_ARTIFACTS_DIR", "artifacts")
    # 幾何優化器在 LLM 初稿後嘗試的微調次數：幾毫秒的浮點運算，比再問一次 LLM 便宜有效
    LAYOUT_OPTIMIZER_STEPS: int = int(os.getenv("DESIGNBRIDGE_LAYOUT_OPTIMIZER_STEPS", "2000"))
    # 佈局檢查 agent：有風水／動線問題才把報告交回 LLM 決定是否重排，最多一次
    LAYOUT_REVIEW_AGENT: bool = _flag("DESIGNBRIDGE_LAYOUT_REVIEW_AGENT", "true")
    ENABLE_LAYOUT_DEPTH_PROJECTION: bool = _flag("DESIGNBRIDGE_ENABLE_LAYOUT_DEPTH_PROJECTION", "true")
    LAYOUT_PHOTO_ANCHORED_DEPTH: bool = _flag("DESIGNBRIDGE_LAYOUT_PHOTO_ANCHORED_DEPTH", "true")
    LAYOUT_CAMERA_EYE_HEIGHT: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAMERA_EYE_HEIGHT", "1.5"))  # 只影響家具高度
    # Synthetic-camera depth projection (scene_graph_to_depth's no-photo branch) now
    # shares the same look-at camera + parameters as the renderer's layout fallback
    # (LAYOUT_CAM_EYE_H/SETBACK/TARGET_H/TARGET_DEPTH_FRAC/FOV above) instead of its
    # own separate HFOV/pitch/setback knobs, so both paths tune as one camera.
    #
    # That shared set is now only the *base* station point (candidate 0): when
    # LAYOUT_CAMERA_AUTO_SELECT is on, a few perturbed candidates around it are
    # rendered and scored by how little furniture occludes other furniture, and the
    # best-scoring one is used instead of always the fixed base station.
    LAYOUT_CAMERA_AUTO_SELECT: bool = _flag("DESIGNBRIDGE_LAYOUT_CAMERA_AUTO_SELECT", "true")
    LAYOUT_CAMERA_CANDIDATES: int = int(os.getenv("DESIGNBRIDGE_LAYOUT_CAMERA_CANDIDATES", "6"))

    # ── IKEA 商品 3D 模型（product_meshes）──────────────────────────────
    # 佈局家具綁定 IKEA SKU、深度圖改用真實模型，渲染時鎖住家具像素只生成房間
    ENABLE_PRODUCT_MESHES: bool = _flag("DESIGNBRIDGE_ENABLE_PRODUCT_MESHES", "false")
    PRODUCT_MESH_DIR: str = os.getenv("DESIGNBRIDGE_PRODUCT_MESH_DIR", "designbridge/furniture_kb/meshes")
    # 房間區域重繪強度（家具區不重繪）；1.0 = 房間完全重新生成
    PRODUCT_ROOM_INPAINT_STRENGTH: float = float(os.getenv("DESIGNBRIDGE_PRODUCT_ROOM_INPAINT_STRENGTH", "1.0"))
    # 整張圖補光影的低強度 img2img；太高家具會被改掉，0 = 跳過
    PRODUCT_HARMONIZE_STRENGTH: float = float(os.getenv("DESIGNBRIDGE_PRODUCT_HARMONIZE_STRENGTH", "0.3"))
    PRODUCT_DEPTH_CONDITIONING_SCALE: float = float(os.getenv("DESIGNBRIDGE_PRODUCT_DEPTH_CONDITIONING_SCALE", "0.6"))
