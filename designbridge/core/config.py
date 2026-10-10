# designbridge/config.py
"""DesignBridge 設定：憑證與模型名走環境變數；ControlNet 調參的來由見 docs/CONTROLNET_PARAM_TEST.md。"""

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
    FAL_INPAINT_MODEL: str = os.getenv("DESIGNBRIDGE_FAL_INPAINT_MODEL", "fal-ai/flux-pro/v1/fill")

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

    # 佈局控制圖的鏡頭：接近視線高度、看向房間中心（舊的高視角會留黑邊、畫成娃娃屋）
    # 1024x576 調出來的；回到舊值：EYE_H=2.2 SETBACK=2.6 TARGET_H=0.5 TARGET_DEPTH_FRAC=0.58 FOV=58
    LAYOUT_CAM_EYE_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_EYE_H", "1.6"))
    LAYOUT_CAM_SETBACK: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_SETBACK", "1.6"))
    LAYOUT_CAM_TARGET_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_H", "0.9"))
    LAYOUT_CAM_TARGET_DEPTH_FRAC: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_DEPTH_FRAC", "0.6"))
    LAYOUT_CAM_FOV: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_FOV", "65"))

    # ── ControlNet（有深度圖的流程）：照片深度 / 投影深度 ──────────────────
    # 重排佈局時的深度來源：controlnet（現行）| kontext（品質不穩，僅供參考）
    LAYOUT_DEPTH_CONTROL_BACKEND: str = os.getenv("DESIGNBRIDGE_LAYOUT_DEPTH_CONTROL_BACKEND", "controlnet")
    DEPTH_CONTROLNET_MODEL: str = os.getenv(
        "DESIGNBRIDGE_DEPTH_CONTROLNET_MODEL", "Shakker-Labs/FLUX.1-dev-ControlNet-Depth"
    )
    FAL_CONTROLNET_STEPS: int = int(os.getenv("DESIGNBRIDGE_FAL_CONTROLNET_STEPS", "20"))
    FAL_CONTROLNET_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_FAL_CONTROLNET_GUIDANCE", "3.5"))
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
    # 風格 LoRA 套在 img2img 換風格上：A/B 顯示沒幫助且 14s→54s，先關（ControlNet 路徑不受影響）
    IMG2IMG_USE_LORA: bool = _flag("DESIGNBRIDGE_IMG2IMG_USE_LORA", "false")
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
    LAYOUT_MAX_ITER: int = int(os.getenv("DESIGNBRIDGE_LAYOUT_MAX_ITER", "3"))
    # 幾何優化器在 LLM 初稿後嘗試的微調次數：幾毫秒的浮點運算，比再問一次 LLM 便宜有效
    LAYOUT_OPTIMIZER_STEPS: int = int(os.getenv("DESIGNBRIDGE_LAYOUT_OPTIMIZER_STEPS", "2000"))
    LAYOUT_LLM_REFINE: bool = _flag("DESIGNBRIDGE_LAYOUT_LLM_REFINE", "false")
    ENABLE_LAYOUT_DEPTH_PROJECTION: bool = _flag("DESIGNBRIDGE_ENABLE_LAYOUT_DEPTH_PROJECTION", "true")
    LAYOUT_PHOTO_ANCHORED_DEPTH: bool = _flag("DESIGNBRIDGE_LAYOUT_PHOTO_ANCHORED_DEPTH", "true")
    LAYOUT_CAMERA_EYE_HEIGHT: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAMERA_EYE_HEIGHT", "1.5"))  # 只影響家具高度
    LAYOUT_PROJECTION_HFOV: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_HFOV", "65.0"))
    LAYOUT_PROJECTION_PITCH: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_PITCH", "-8.0"))
    LAYOUT_PROJECTION_SETBACK: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_SETBACK", "1.2"))

    @classmethod
    def get_gemini_api_key(cls) -> str:
        if cls.GEMINI_API_KEY:
            return cls.GEMINI_API_KEY
        raise ValueError("GEMINI_API_KEY not set. Please set it in .env or as environment variable.")
