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
    GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    GEMINI_TEMPERATURE: float = 0.3
    # 2.5 系列模型預設會啟用隱藏推理（thinking），對抽取/翻譯/辨識這類簡單任務只會多花時間。
    # 0 = 關閉 thinking；-1 = 交給模型動態決定；正整數 = 指定 thinking token 上限。
    GEMINI_THINKING_BUDGET: int = int(os.getenv("DESIGNBRIDGE_GEMINI_THINKING_BUDGET", "0"))

    # Text embedding model for style retrieval (text-to-text).
    TEXT_EMBEDDING_MODEL: str = os.getenv("DESIGNBRIDGE_TEXT_EMBEDDING_MODEL", "BAAI/bge-m3")

    @classmethod
    def get_dynamic_routing_enabled(cls) -> bool:
        return os.getenv("DESIGNBRIDGE_ENABLE_DYNAMIC_ROUTING", "false").lower() in ("1", "true", "yes")

    ROUTER_TEMPERATURE: float = float(os.getenv("DESIGNBRIDGE_ROUTER_TEMPERATURE", "0.0"))

    # Image generation (Imagen) - same API key as Gemini; requires billing
    IMAGEN_MODEL: str = os.getenv("DESIGNBRIDGE_IMAGEN_MODEL", "imagen-4.0-generate-001")
    # Local image generation backend: always Flux
    @classmethod
    def get_local_model_type(cls) -> str:
        return "flux"

    # Model ID for Flux
    FLUX_MODEL: str = os.getenv("DESIGNBRIDGE_FLUX_MODEL", "black-forest-labs/FLUX.1-schnell")

    # Inpainting model (SD 1.5-based; runwayml/stable-diffusion-inpainting is publicly available)
    INPAINT_MODEL: str = os.getenv("DESIGNBRIDGE_INPAINT_MODEL", "runwayml/stable-diffusion-inpainting")

    FLUX_STEPS: int = int(os.getenv("DESIGNBRIDGE_FLUX_STEPS", "4"))
    ENABLE_FLUX_FALLBACK: bool = os.getenv("DESIGNBRIDGE_ENABLE_FLUX_FALLBACK", "true").lower() in ("1", "true", "yes")

    # fal.ai Inference API (cloud inpainting via FLUX.1-Fill)
    FAL_KEY: str | None = os.getenv("FAL_KEY")
    FAL_INPAINT_MODEL: str = os.getenv("DESIGNBRIDGE_FAL_INPAINT_MODEL", "fal-ai/flux-pro/v1/fill")

    # 3D 場景重建：算圖前先 outpaint 擴圖，填補深度網格旋轉時的破洞
    ENABLE_MESH_OUTPAINT: bool = os.getenv("DESIGNBRIDGE_ENABLE_MESH_OUTPAINT", "false").lower() in ("1", "true", "yes")
    MESH_OUTPAINT_BORDER: float = float(os.getenv("DESIGNBRIDGE_MESH_OUTPAINT_BORDER", "0.2"))
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

    # Text2Room 逐步 outpaint 環景（預設關閉 → 只產單視角 GLB）
    ENABLE_TEXT2ROOM: bool = os.getenv("DESIGNBRIDGE_ENABLE_TEXT2ROOM", "false").lower() in ("1", "true", "yes")
    TEXT2ROOM_AZIMUTHS: str = os.getenv("DESIGNBRIDGE_TEXT2ROOM_AZIMUTHS", "-30,30")
    # 每側 outpaint 幾次。單一 typical FOV ~75° 的原圖，每次向外補約半張寬度
    # （約 +37°），steps_per_side=1 只覆蓋 ~150°，其餘角度在球面環景上會是
    # 大片鏡射填色而非 AI 想像的內容。3 次/側覆蓋約 300°，缺口縮小到 ~60°；
    # 4 次/側可覆蓋滿 360° 但每次都是一次額外的 fal.ai 呼叫（+30~60 秒)。
    TEXT2ROOM_STEPS_PER_SIDE: int = int(os.getenv("DESIGNBRIDGE_TEXT2ROOM_STEPS_PER_SIDE", "3"))

    # Hugging Face Inference API (cloud Flux; no local download). Tried first when HF_TOKEN set.
    ENABLE_HF_INFERENCE: bool = os.getenv("DESIGNBRIDGE_ENABLE_HF_INFERENCE", "true").lower() in ("1", "true", "yes")
    HF_TOKEN: str | None = os.getenv("HF_TOKEN")
    HF_INFERENCE_PROVIDER: str = os.getenv("DESIGNBRIDGE_HF_INFERENCE_PROVIDER", "hf-inference")
    FAL_REDUX_STEPS: int = int(os.getenv("FAL_REDUX_STEPS", "28"))
    FAL_REDUX_GUIDANCE: float = float(os.getenv("FAL_REDUX_GUIDANCE", "3.5"))
    ENABLE_FLUX_REDUX: bool = os.getenv("DESIGNBRIDGE_ENABLE_FLUX_REDUX", "false").lower() in ("1", "true", "yes")
    FAL_IP_ADAPTER_STEPS: int = int(os.getenv("FAL_IP_ADAPTER_STEPS", "28"))
    FAL_IP_ADAPTER_GUIDANCE: float = float(os.getenv("FAL_IP_ADAPTER_GUIDANCE", "3.5"))
    FAL_IP_ADAPTER_SCALE: float = float(os.getenv("FAL_IP_ADAPTER_SCALE", "0.6"))
    FAL_IP_ADAPTER_SIZE: int = int(os.getenv("FAL_IP_ADAPTER_SIZE", "512"))

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

    # Elevated three-quarter "look-at room centre" camera for the layout control
    # images — spreads the floor layout out legibly (an eye-level view crushes it).
    # Footroom-tuned: a lower/further eye aimed slightly deeper lifts the FRONT wall
    # off the bottom edge, so front-of-room furniture (e.g. an accent armchair) stays
    # fully framed instead of being clipped into the bottom dead zone and dropped.
    LAYOUT_CAM_EYE_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_EYE_H", "2.2"))
    LAYOUT_CAM_SETBACK: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_SETBACK", "2.6"))
    LAYOUT_CAM_TARGET_H: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_H", "0.5"))
    LAYOUT_CAM_TARGET_DEPTH_FRAC: float = float(
        os.getenv("DESIGNBRIDGE_LAYOUT_CAM_TARGET_DEPTH_FRAC", "0.58")
    )
    LAYOUT_CAM_FOV: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_CAM_FOV", "58"))
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
    PROJECTED_DEPTH_MAX_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_PROJECTED_DEPTH_MAX_CONDITIONING_SCALE", "0.3")
    )

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
    # already implies, not override it.
    EDGE_CONDITIONING_SCALE: float = float(
        os.getenv("DESIGNBRIDGE_EDGE_CONDITIONING_SCALE", "0.45")
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
    # Re-enable the old "score the plan, ask the LLM again" loop on top of the optimizer.
    # Off by default: it costs one round trip per iteration and the feedback it sends is
    # five scalars with no indication of which piece is at fault.
    LAYOUT_LLM_REFINE: bool = os.getenv(
        "DESIGNBRIDGE_LAYOUT_LLM_REFINE", "false"
    ).lower() in ("1", "true", "yes")
    # Project scene-graph furniture boxes into a perspective depth map for ControlNet.
    # When true and the user re-plans layout, this projected depth overrides the
    # input-photo depth so the precise coordinates actually control the render.
    ENABLE_LAYOUT_DEPTH_PROJECTION: bool = os.getenv(
        "DESIGNBRIDGE_ENABLE_LAYOUT_DEPTH_PROJECTION", "true"
    ).lower() in ("1", "true", "yes")
    # Anchor the projected depth to the uploaded photo's own floor plane (homography from
    # depth + segmentation) instead of a synthetic camera over an empty box. This is what
    # keeps the render's camera angle, room proportions and architecture matching the photo.
    LAYOUT_PHOTO_ANCHORED_DEPTH: bool = os.getenv(
        "DESIGNBRIDGE_LAYOUT_PHOTO_ANCHORED_DEPTH", "true"
    ).lower() in ("1", "true", "yes")
    # Assumed camera height for photo-anchored projection; only affects furniture heights.
    LAYOUT_CAMERA_EYE_HEIGHT: float = float(
        os.getenv("DESIGNBRIDGE_LAYOUT_CAMERA_EYE_HEIGHT", "1.5")
    )

    # Synthetic-camera fallback (no photo, or floor geometry unsolvable).
    # Calibrated against FLUX Kontext renders: pitch=-16 framed the room far better
    # than -6/-8 (more floor visible, furniture distribution matched the depth boxes).
    LAYOUT_PROJECTION_HFOV: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_HFOV", "65.0"))
    LAYOUT_PROJECTION_PITCH: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_PITCH", "-16.0"))
    LAYOUT_PROJECTION_SETBACK: float = float(os.getenv("DESIGNBRIDGE_LAYOUT_PROJECTION_SETBACK", "0.8"))

    @classmethod
    def get_gemini_api_key(cls) -> str:
        """Get Gemini API key from config or environment."""
        if cls.GEMINI_API_KEY:
            return cls.GEMINI_API_KEY
        raise ValueError(
            "GEMINI_API_KEY not set. Please set it in config.py or as environment variable."
        )
