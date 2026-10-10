# designbridge/config.py
"""Configuration for DesignBridge APIs."""

import os
from pathlib import Path

import dotenv

# Load .env from project root (parent of designbridge package) so it works from any cwd
_root = Path(__file__).resolve().parent.parent.parent
dotenv.load_dotenv(_root / ".env")
dotenv.load_dotenv()  # Allow override from current working directory


class Config:
    """DesignBridge configuration."""

    GEMINI_MODEL: str = os.getenv("DESIGNBRIDGE_GEMINI_MODEL", "gemini-3.6-flash")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY")
    # Extra keys tried in order if GEMINI_API_KEY fails (comma-separated).
    GEMINI_API_KEYS: str = os.getenv("GEMINI_API_KEYS", "")

    # Vertex AI mode: no API key, authenticate via service-account JSON (ADC).
    GOOGLE_GENAI_USE_VERTEXAI: bool = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true", "yes")
    GOOGLE_GENAI_FORCE_API_KEY: bool = os.getenv("GOOGLE_GENAI_FORCE_API_KEY", "").lower() in ("1", "true", "yes")
    GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    GEMINI_TEMPERATURE: float = 0.3
    # 2.5 系列模型預設會啟用隱藏推理（thinking），對抽取/翻譯/辨識這類簡單任務只會多花時間。
    # 0 = 關閉 thinking；-1 = 交給模型動態決定；正整數 = 指定 thinking token 上限。
    GEMINI_THINKING_BUDGET: int = int(os.getenv("DESIGNBRIDGE_GEMINI_THINKING_BUDGET", "0"))

    # 消融實驗用：call_llm() 走哪個 provider，"gemini" | "qwen" | "llama"
    LLM_PROVIDER: str = os.getenv("DESIGNBRIDGE_LLM_PROVIDER", "gemini")
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")
    DASHSCOPE_BASE_URL: str = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
    QWEN_MODEL: str = os.getenv("DESIGNBRIDGE_QWEN_MODEL", "qwen3-vl-30b-a3b-instruct")

    LLAMA_MODEL: str = os.getenv("DESIGNBRIDGE_LLAMA_MODEL", "meta/llama-4-scout-17b-16e-instruct-maas")
    LLAMA_LOCATION: str = os.getenv("DESIGNBRIDGE_LLAMA_LOCATION", "us-east5")

    # Model ID for Flux
    FLUX_MODEL: str = os.getenv("DESIGNBRIDGE_FLUX_MODEL", "black-forest-labs/FLUX.1-schnell")

    # Inpainting model (SD 1.5-based; runwayml/stable-diffusion-inpainting is publicly available)
    INPAINT_MODEL: str = os.getenv("DESIGNBRIDGE_INPAINT_MODEL", "runwayml/stable-diffusion-inpainting")


    # fal.ai Inference API (cloud inpainting via FLUX.1-Fill)
    FAL_KEY: str | None = os.getenv("FAL_KEY")
    FAL_INPAINT_MODEL: str = os.getenv("DESIGNBRIDGE_FAL_INPAINT_MODEL", "fal-ai/flux-pro/v1/fill")

    # Outpaint 專用 endpoint。fal-ai/flux-pro/v1/fill 只吃 9 個參數，沒有 negative_prompt
    # （guidance_scale / num_inference_steps 傳了也會被忽略），無法壓掉 FLUX 從訓練資料
    # 學來的浮水印與招牌文字。flux-general/inpainting 有 negative_prompt，預設走 NAG 生效。
    FAL_OUTPAINT_MODEL: str = os.getenv(
        "DESIGNBRIDGE_FAL_OUTPAINT_MODEL", "fal-ai/flux-general/inpainting"
    )
    OUTPAINT_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_OUTPAINT_GUIDANCE", "2.2"))
    OUTPAINT_STEPS: int = int(os.getenv("DESIGNBRIDGE_OUTPAINT_STEPS", "28"))
    # NAG scale：越高越遠離 negative prompt（fal 預設 3）
    OUTPAINT_NAG_SCALE: float = float(os.getenv("DESIGNBRIDGE_OUTPAINT_NAG_SCALE", "5.0"))
    # 兩組 negative：文字浮水印，以及會被重複生成的家具
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

    # Hugging Face Inference API (cloud Flux; no local download). Tried first when HF_TOKEN set.
    ENABLE_HF_INFERENCE: bool = os.getenv("DESIGNBRIDGE_ENABLE_HF_INFERENCE", "true").lower() in ("1", "true", "yes")
    HF_TOKEN: str | None = os.getenv("HF_TOKEN")
    HF_INFERENCE_PROVIDER: str = os.getenv("DESIGNBRIDGE_HF_INFERENCE_PROVIDER", "hf-inference")

    # Kontext LoRA (reference + depth fusion) via Replicate
    KONTEXT_LORA_MODEL: str = "thedeoxen/FLUX.1-Kontext-dev-reference-depth-fusion-LORA"
    KONTEXT_PROVIDER: str = os.getenv("DESIGNBRIDGE_KONTEXT_PROVIDER", "fal-ai")

    # Layout → 3D depth ControlNet: project the 2D floor plan into an eye-level depth
    # map and drive a FLUX depth ControlNet so the render honors furniture positions.
    # Requires FAL_KEY. Used in the layout-driven (text→design, no uploaded photo) flow.
    ENABLE_LAYOUT_CONTROLNET: bool = os.getenv(
        "DESIGNBRIDGE_ENABLE_LAYOUT_CONTROLNET", "true"
    ).lower() in ("1", "true", "yes")
    FAL_DEPTH_CONTROLNET_MODEL: str = os.getenv(
        "DESIGNBRIDGE_FAL_DEPTH_CONTROLNET_MODEL",
        "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro",
    )
    # control_mode for the FLUX Union ControlNet on fal (string enum):
    # canny | tile | depth | blur | pose | gray | low-quality
    FAL_DEPTH_CONTROL_MODE: str = os.getenv("DESIGNBRIDGE_FAL_DEPTH_CONTROL_MODE", "depth")

    # The layout control uses TWO stacked controls on the Union model:
    #   • Canny of the furniture floor-FOOTPRINTS — the PRIMARY, faithful placement
    #     signal (distance-independent; footprints not cuboids, so the model still
    #     renders real furniture not boxes). This carries position AND size, so it is
    #     weighted strongly — under-weighting it is what let furniture drift off-plan.
    #   • Depth of the room shell — SECONDARY, mostly walls/window structure. From the
    #     elevated near-top-down camera, low furniture blends into the floor in depth,
    #     so depth is a weak furniture signal and is kept low on purpose.
    FAL_EDGE_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_FAL_EDGE_CONDITIONING_SCALE", "0.35")
    )
    FAL_DEPTH_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_FAL_DEPTH_CONDITIONING_SCALE", "0.30")
    )
    FAL_DEPTH_STEPS: int = int(os.getenv("DESIGNBRIDGE_FAL_DEPTH_STEPS", "42"))
    FAL_DEPTH_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_FAL_DEPTH_GUIDANCE", "4.2"))

    # Restrict the layout controls to the EARLY denoising steps only. Structure locks
    # in during the first steps; ending control early (e.g. 0.7 = first 70% of steps)
    # then lets the model freely resolve materials, lighting and realistic furniture
    # detail — directly easing the "full-strength control hurts plausibility" problem.
    # 1.0 = control the whole run (old behaviour).
    FAL_DEPTH_CONTROL_END: float = float(os.getenv("DESIGNBRIDGE_FAL_DEPTH_CONTROL_END", "0.4"))
    # Edges carry placement (not shape). Long enough to lock furniture onto the plan,
    # but ended before the final steps so the footprint canny fades instead of surviving
    # as visible floor wireframes in the render.
    FAL_EDGE_CONTROL_END: float = float(os.getenv("DESIGNBRIDGE_FAL_EDGE_CONTROL_END", "0.55"))

    # Draw furniture in the layout depth map as rough semantic silhouettes
    # (bed = low platform + headboard, sofa = seat + backrest + armrests,
    # table/desk = tabletop on legs) instead of plain cuboids, so the model can infer
    # the furniture category from the shape. Falls back to cuboids when false.
    # Keep ON: the semantic silhouette in the depth map is what lets the model render
    # furniture as recognisable furniture. With it OFF, low furniture reads as flat
    # floor mats / grey boxes. The "white clay blob" failure was NOT caused by this —
    # it was an empty/meta prompt starving the render of material content (now fixed by
    # the empty-prompt fallback in render_prompt.py). Requires a real prompt to look good.
    ENABLE_SEMANTIC_SHAPES: bool = os.getenv(
        "DESIGNBRIDGE_ENABLE_SEMANTIC_SHAPES", "true"
    ).lower() in ("1", "true", "yes")

    # Near-eye-level "look-at room centre" camera for the layout control images.
    # The old elevated camera (eye 2.2 m, 2.6 m outside, aimed at 0.5 m) left ~20% of
    # the frame black around a trapezoid room shell, and the model painted that as a
    # glowing "dollhouse" frame seen from above. This one fills the frame (0% black on
    # a 5x4 m room) and still keeps furniture next to the entrance fully framed; going
    # lower/closer (eye 1.5, setback 1.0) crops front-of-room furniture.
    # Tuned on 1024x576; to go back to the old look use EYE_H=2.2 SETBACK=2.6
    # TARGET_H=0.5 TARGET_DEPTH_FRAC=0.58 FOV=58 (and the "Elevated" prompt in renderer.py).
    LAYOUT_CAM_EYE_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_EYE_H", "1.6"))
    LAYOUT_CAM_SETBACK: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_SETBACK", "1.6"))
    LAYOUT_CAM_TARGET_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_H", "0.9"))
    LAYOUT_CAM_TARGET_DEPTH_FRAC: float = float(
        os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_DEPTH_FRAC", "0.6")
    )
    LAYOUT_CAM_FOV: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_FOV", "65"))
    # Depth conditioning backend for re-planned layouts (uses the scene-graph projected depth):
    #   "kontext"    → Kontext depth-fusion LoRA (loose reference depth; community LoRA via HF's
    #                  fal-ai provider routing — unreliable output quality, kept for reference only)
    #   "controlnet" → true FLUX depth ControlNet via fal.ai directly (stronger, more reliable
    #                  geometric control; needs FAL_KEY; current default)
    LAYOUT_DEPTH_CONTROL_BACKEND: str = os.getenv("DESIGNBRIDGE_LAYOUT_DEPTH_CONTROL_BACKEND", "controlnet")
    DEPTH_CONTROLNET_MODEL: str = os.getenv(
        "DESIGNBRIDGE_DEPTH_CONTROLNET_MODEL", "Shakker-Labs/FLUX.1-dev-ControlNet-Depth"
    )
    FAL_CONTROLNET_STEPS: int = int(os.getenv("DESIGNBRIDGE_FAL_CONTROLNET_STEPS", "20"))
    FAL_CONTROLNET_GUIDANCE: float = float(os.getenv("DESIGNBRIDGE_FAL_CONTROLNET_GUIDANCE", "3.5"))
    # 一鍵換風格（img2img）是否套用風格 LoRA。A/B 測試（docs/images/img2img_lora_ab/）
    # 顯示目前這批 LoRA 對換風格沒有正面貢獻（country LoRA 生出來的圖主觀上比沒套 LoRA
    # 還不像鄉村風），還把耗時從 14s 拉到 54s（fal 下載/合併 LoRA 權重的開銷）。先關掉，
    # LoRA 重新微調過、確認有幫助之後再打開。ControlNet 路徑的 LoRA 不受此影響。
    IMG2IMG_USE_LORA: bool = os.getenv("DESIGNBRIDGE_IMG2IMG_USE_LORA", "false").lower() in ("1", "true", "yes")
    # 換風格時用「上一張生成圖的估計深度」鎖構圖（舊行為）。實測這份深度在窗戶/遠牆等平坦區域是雜訊，
    # 會讓窗戶出現龜裂紋、家具黏在一起；預設關閉，換風格改走跟第一次生成相同的 layout ControlNet
    # 分支（同 seed，構圖大致沿用）。設 DESIGNBRIDGE_STYLE_SWAP_DEPTH_LOCK=true 可切回舊行為。
    STYLE_SWAP_DEPTH_LOCK: bool = os.getenv("DESIGNBRIDGE_STYLE_SWAP_DEPTH_LOCK", "false").lower() in ("1", "true", "yes")
    PROJECTED_DEPTH_MAX_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_PROJECTED_DEPTH_MAX_CONDITIONING_SCALE", "0.3")
    )
    # End depth/edge control partway through denoising for the real-photo ControlNet
    # branch (renderer.py's flux_controlnet_depth_fal call). Structure still locks in
    # during the early steps; 1.0 = control the whole run. Kept modest, but debug-console
    # A/B testing showed this alone does NOT fix the "glitched far wall" artifact —
    # see REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE below for the confirmed fix.
    REAL_PHOTO_DEPTH_CONTROL_END: float = float(
        os.getenv("DESIGNBRIDGE_REAL_PHOTO_DEPTH_CONTROL_END", "0.7")
    )
    # Confirmed by controlled A/B testing (2026-09-28): a flat/low-variance region of a
    # depth map (e.g. a far wall with almost no texture) gives the model almost nothing
    # to anchor on. At conditioning_scale >= 0.85 it renders that region as noise no
    # matter what the prompt asks for; at 0.6 the same photo renders cleanly every time.
    # Neither disabling the edge ControlNet nor REAL_PHOTO_DEPTH_CONTROL_END fixed it in
    # isolation — conditioning_scale itself is the lever. requirement_analyzer defaults
    # pure-style requests to 0.85~1.0 ("preserve structure fully"), so cap it here
    # regardless of what it asked for.
    REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE", "0.65")
    )
    # Design Adjuster 的 inpaint strength：edit_scope 移除前是 edit_scope+0.4 算出來的，
    # 產品端過去固定送 0.6 → 換算後一直是封頂值 0.85，這裡直接固定同一個值，行為不變。
    ADJUSTER_INPAINT_STRENGTH: float = float(os.getenv("DESIGNBRIDGE_ADJUSTER_INPAINT_STRENGTH", "0.85"))

    # Second ControlNet carrying object boundaries, stacked on top of depth.
    # Depth alone has no hard edges to offer: harmonic hole-filling smooths the wall and
    # ceiling seams, and low furniture barely separates from the floor it stands on — so
    # the model is free to invent where one surface ends, which reads as soft, drifting
    # geometry. The segmentation map has exactly that information as label
    # discontinuities. FLUX has no public segmentation ControlNet (Union-Pro-2.0 covers
    # canny / soft edge / depth / pose / gray only), so the seg map is converted to an
    # exact boundary image and fed to a canny ControlNet, which takes the same white-on-
    # black line input. Point EDGE_CONTROLNET_MODEL at a real seg ControlNet if one lands.
    ENABLE_EDGE_CONTROL: bool = os.getenv(
        "DESIGNBRIDGE_ENABLE_EDGE_CONTROL", "true"
    ).lower() in ("1", "true", "yes")
    EDGE_CONTROLNET_MODEL: str = os.getenv(
        "DESIGNBRIDGE_EDGE_CONTROLNET_MODEL", "InstantX/FLUX.1-dev-Controlnet-Canny"
    )
    # Union-style ControlNets need an explicit mode index; standalone ones must omit it.
    EDGE_CONTROLNET_MODE: str = os.getenv("DESIGNBRIDGE_EDGE_CONTROLNET_MODE", "")
    # Kept well below the depth scale: boundaries should sharpen the geometry depth
    # already implies, not override it. The segmentation model sometimes splits one
    # real surface into many small flickering regions (clutter, reflections, fabric
    # folds); _seg_to_edge_condition now filters those out before extracting
    # boundaries, but 0.3 (down from 0.45) leaves slack for whatever noise survives
    # that filter instead of forcing FLUX to paint a literal seam at every stray edge.
    EDGE_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_EDGE_CONDITIONING_SCALE", "0.3")
    )

    # Local vision preprocessing (Depth + UPerNet segmentation)
    # NOTE: These models will be downloaded on first run (requires internet).
    ENABLE_DEPTH: bool = True
    ENABLE_SEGMENTATION: bool = True

    # Depth estimation: Depth Anything V2 (via HuggingFace Transformers).
    # Options: Small (24.8M) | Base (97.5M) | Large (335M)
    #
    # Small is the default because nothing downstream reads fine depth detail: the floor
    # and ceiling are fitted as *planes*, and the far-wall distance is a robust
    # percentile. Measured against Large on the sample interiors, the far-wall junction
    # (which sets where furniture lands) agreed to within 4px, while inference dropped
    # from 16.7s to 2.3s on CPU. Raise to Base or Large if a GPU is available.
    DEPTH_MODEL: str = os.getenv(
        "DESIGNBRIDGE_DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Small-hf"
    )
    # Semantic segmentation (UPerNet). Example checkpoint on HuggingFace.
    SEGMENTATION_MODEL: str = os.getenv(
        "DESIGNBRIDGE_SEGMENTATION_MODEL", "openmmlab/upernet-convnext-small"
    )

    # Cap the long edge of the depth / segmentation artifacts. Both models already
    # downscale internally (depth to ~518, UPerNet to 512), so a larger artifact buys no
    # extra detail — it only makes everything reading them slower: the plane fits, the
    # harmonic hole-filling, the boundary extraction. Phone photos are routinely 4000px.
    # 0 disables the cap.
    VISION_MAX_EDGE: int = int(os.getenv("DESIGNBRIDGE_VISION_MAX_EDGE", "1280"))
    # Run depth and segmentation concurrently. Measured 35% faster end-to-end on CPU even
    # with both competing for the same threads, since neither saturates them alone.
    VISION_PARALLEL: bool = os.getenv(
        "DESIGNBRIDGE_VISION_PARALLEL", "true"
    ).lower() in ("1", "true", "yes")
    # Reuse artifacts when the same photo is processed again (content-addressed).
    VISION_CACHE: bool = os.getenv(
        "DESIGNBRIDGE_VISION_CACHE", "true"
    ).lower() in ("1", "true", "yes")

    # Where to write artifacts (depth/segmentation outputs)
    ARTIFACTS_DIR: str = os.getenv("DESIGNBRIDGE_ARTIFACTS_DIR", "artifacts")

    # Layout agent
    LAYOUT_MAX_ITER: int = int(os.getenv("DESIGNBRIDGE_LAYOUT_MAX_ITER", "3"))
    # Candidate nudges the geometric optimizer evaluates after the LLM's initial plan.
    # Each is a handful of float ops over ~8 boxes, so a couple thousand cost milliseconds
    # — far cheaper and far more effective than another LLM round trip.
    LAYOUT_OPTIMIZER_STEPS: int = int(
        os.getenv("DESIGNBRIDGE_LAYOUT_OPTIMIZER_STEPS", "2000")
    )
    LAYOUT_LLM_REFINE: bool = os.getenv(
        "DESIGNBRIDGE_LAYOUT_LLM_REFINE", "false"
    ).lower() in ("1", "true", "yes")
    ENABLE_LAYOUT_DEPTH_PROJECTION: bool = os.getenv(
        "DESIGNBRIDGE_ENABLE_LAYOUT_DEPTH_PROJECTION", "true"
    ).lower() in ("1", "true", "yes")
    LAYOUT_PHOTO_ANCHORED_DEPTH: bool = os.getenv(
        "DESIGNBRIDGE_LAYOUT_PHOTO_ANCHORED_DEPTH", "true"
    ).lower() in ("1", "true", "yes")
    # Assumed camera height for photo-anchored projection; only affects furniture heights.
    LAYOUT_CAMERA_EYE_HEIGHT: float = float(
        os.getenv("DESIGNBRIDGE_LAYOUT_CAMERA_EYE_HEIGHT", "1.5")
    )
    LAYOUT_PROJECTION_HFOV: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_HFOV", "65.0"))
    LAYOUT_PROJECTION_PITCH: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_PITCH", "-8.0"))
    LAYOUT_PROJECTION_SETBACK: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_SETBACK", "1.2"))

    @classmethod
    def get_gemini_api_key(cls) -> str:
        """Get Gemini API key from config or environment."""
        if cls.GEMINI_API_KEY:
            return cls.GEMINI_API_KEY
        raise ValueError(
            "GEMINI_API_KEY not set. Please set it in config.py or as environment variable."
        )
