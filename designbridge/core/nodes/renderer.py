"""Renderer graph node."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from designbridge.core.state import DesignBridgeState
from designbridge.core.timing import timed_call
from designbridge.render.render_prompt import (
    _analyze_style_image_with_gemini,
    _build_imagen_prompt_from_requirement,
    _resolve_output_size,
)
from designbridge.render.render_backends import (
    _render_hf_inference,
    _render_hf_kontext,
    _render_flux_kontext_fal,
    _render_flux_controlnet_depth_fal,
    _render_flux_depth_controlnet_fal,
    _render_flux_redux_fal,
    _render_flux_redux_local,
    _render_flux_ipadapter_fal,
    _render_flux_fal,
    _render_flux,
)

_BASE_NEGATIVE_PROMPT = (
    "people, person, human, man, woman, child, hands, face, "
    "animal, pet, cat, dog, bird, "
    "text, watermark, signature, logo"
)


def _fit_condition_image(
    image_path: str, output_size: tuple[int, int], out_dir: Path, tag: str,
    *, nearest: bool = False,
) -> str:
    """Center-crop + resize a ControlNet condition image to the renderer's output size.

    Without this the condition (depth / segmentation) is silently stretched to the output
    aspect by the backend, which shears the room geometry and defeats the whole point of
    conditioning on it. Returns the original path when it already matches.

    `nearest` forces nearest-neighbour for label images, where interpolating between two
    ids invents a third that belongs to neither region.
    """
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            src_w, src_h = img.size
            target_w, target_h = output_size
            if (src_w, src_h) == (target_w, target_h):
                return image_path

            target_ratio = target_w / target_h
            src_ratio = src_w / src_h
            if abs(src_ratio - target_ratio) > 1e-3:
                if src_ratio > target_ratio:      # too wide → crop left/right
                    crop_w = int(round(src_h * target_ratio))
                    left = (src_w - crop_w) // 2
                    box = (left, 0, left + crop_w, src_h)
                else:                              # too tall → crop top/bottom
                    crop_h = int(round(src_w / target_ratio))
                    top = (src_h - crop_h) // 2
                    box = (0, top, src_w, top + crop_h)
                img = img.crop(box)

            if nearest or img.mode in ("I", "I;16", "P"):
                resample = Image.NEAREST
            else:
                resample = Image.BICUBIC
            fitted = img.resize((target_w, target_h), resample)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{tag}_{target_w}x{target_h}.png"
            fitted.save(str(out_path))
            return str(out_path)
    except Exception as e:
        print(f"⚠️  無法調整條件圖尺寸（{e}），沿用原檔：{Path(image_path).name}")
        return image_path


def _seg_to_edge_condition(
    seg_path: str, output_size: tuple[int, int], out_dir: Path, tag: str
) -> str | None:
    """Segmentation map → white-on-black object boundaries, sized for the renderer.

    Extraction is exact rather than detected: the segmentation is a label image we
    produced ourselves, so a boundary is simply a pixel whose right or lower neighbour
    carries a different id. Running an actual Canny over it would only add noise.

    Resize happens before extraction so the lines come out a clean 1–2px at the target
    resolution; downsampling already-drawn lines breaks them into dashes.
    """
    try:
        import numpy as np
        from PIL import Image

        fitted = _fit_condition_image(seg_path, output_size, out_dir, f"{tag}_seg", nearest=True)

        with Image.open(fitted) as img:
            if img.mode in ("I", "I;16", "L", "P"):
                labels = np.asarray(img, dtype=np.int64)
            else:
                rgb = np.asarray(img.convert("RGB"), dtype=np.int64)
                labels = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]

        if labels.ndim != 2 or min(labels.shape) < 2:
            return None

        edge = np.zeros(labels.shape, dtype=bool)
        edge[:, :-1] |= labels[:, :-1] != labels[:, 1:]
        edge[:-1, :] |= labels[:-1, :] != labels[1:, :]
        # Thicken to 2px: a hairline survives neither the VAE encode nor the ControlNet's
        # own downsampling, and a boundary the model cannot see conditions nothing.
        edge[:, 1:] |= edge[:, :-1].copy()
        edge[1:, :] |= edge[:-1, :].copy()

        if not edge.any():
            print("⚠️  segmentation 沒有邊界可抽，略過 edge ControlNet")
            return None

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{tag}_{output_size[0]}x{output_size[1]}.png"
        Image.fromarray((edge * 255).astype("uint8"), mode="L").convert("RGB").save(str(out_path))
        print(f"[renderer] edge condition from segmentation: {out_path.name} ({edge.mean():.1%} 邊界像素)")
        return str(out_path)
    except Exception as e:
        print(f"⚠️  無法從 segmentation 產生邊界條件圖（{e}），只用深度條件")
        return None


# Rich noun phrases so each depth box renders as a recognizable, distinct piece of
# furniture instead of an abstract block — especially small items (e.g. armchair)
# that the model otherwise merges into neighbouring furniture.
_FURNITURE_DESC: dict[str, str] = {
    "sofa": "a fabric upholstered sofa",
    "armchair": "a single upholstered accent armchair with armrests",
    "chair": "a dining chair",
    "coffee_table": "a low coffee table",
    "side_table": "a small side table",
    "nightstand": "a nightstand",
    "dining_table": "a dining table",
    "desk": "a desk",
    "tv_unit": "a TV media console with a wall-mounted flat TV above it",
    "tv": "a wall-mounted flat TV",
    "bed": "a bed with headboard",
    "bunk_bed": "a bunk bed",
    "wardrobe": "a tall wardrobe",
    "bookshelf": "a tall bookshelf",
    "shelf": "a shelving unit",
    "cabinet": "a storage cabinet",
    "dresser": "a dresser",
    "plant": "a potted green plant",
    "lamp": "a floor lamp",
    "floor_lamp": "a floor lamp",
    "rug": "a soft area rug on the floor",
}


def _furniture_to_spatial_text(placements: list[dict]) -> str:
    """Convert normalized furniture positions to precise spatial description for prompt injection.

    Coordinate system: x=0 left wall, x=1 right wall, y=0 back/far wall, y=1 front/entrance wall.
    Items within 0.12 of a wall edge are described as 'against [wall] wall'.
    """
    PAD = 0.12
    parts: list[str] = []
    for item in placements[:12]:
        raw = item.get("type", "")
        desc = _FURNITURE_DESC.get(raw, "a " + raw.replace("_", " "))
        x, y = item.get("x", 0.5), item.get("y", 0.5)
        w, h = item.get("w", 0.1), item.get("h", 0.1)
        cx, cy = x + w / 2, y + h / 2

        # Always keep the horizontal (left/right) and depth (back/front) zone so the
        # left-right ordering between items is never lost — even for wall-adjacent
        # pieces. Wall adjacency is added on top, not instead of, the zone.
        h_zone = "left" if cx < 0.40 else ("right" if cx > 0.60 else "center")
        v_zone = "back" if cy < 0.40 else ("front" if cy > 0.60 else "middle")

        wall_tags: list[str] = []
        if x <= PAD:
            wall_tags.append("left")
        if x + w >= 1.0 - PAD:
            wall_tags.append("right")
        if y <= PAD:
            wall_tags.append("back")
        if y + h >= 1.0 - PAD:
            wall_tags.append("front")

        # Base position: horizontal side + depth zone (e.g. "on the right side, back of the room").
        if h_zone == "center":
            pos = f"in the center, {v_zone} of the room"
        else:
            pos = f"on the {h_zone} side, {v_zone} of the room"

        if wall_tags:
            pos += ", against the " + " and ".join(wall_tags) + (
                " wall" if len(wall_tags) == 1 else " walls"
            )

        parts.append(f"{desc} {pos}")
    return "; ".join(parts)


def renderer(state: DesignBridgeState) -> dict[str, Any]:
    """
    Renderer: generate image from structured_requirement using Flux.
    Falls back to placeholder on failure.
    若 routing_decision 為 design_adjuster 且已有 generated_image，直接跳過不覆蓋。
    """
    # Adjuster 已產出 inpainted 圖片，renderer 不再重新生成
    if state.get("routing_decision") == "design_adjuster" and state.get("generated_image"):
        return {}

    task_id = state.get("task_id") or str(uuid.uuid4())
    req = state.get("structured_requirement") or {}
    style_params = state.get("style_params") or {}
    artifacts_root = Path(Config.ARTIFACTS_DIR)
    render_dir = artifacts_root / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    # 加入隨機短碼，確保每次生成都是獨立新檔案（避免 task_id 相同時回傳舊圖）
    render_suffix = uuid.uuid4().hex[:8]
    out_path = render_dir / f"{task_id}_{render_suffix}.png"

    _user_text_prompt = ((state.get("user_input") or {}).get("text_prompt") or "").strip()
    prompt = _build_imagen_prompt_from_requirement(
        req, style_params=style_params, user_text_prompt=_user_text_prompt,
    )

    # 只有使用者明確要求重新規劃佈局時，才把 layout 結果注入 prompt
    if req.get("hint_layout"):
        scene_graph = state.get("scene_graph") or {}
        layout_prompt = (scene_graph.get("layout_prompt") or "").strip()

        if not layout_prompt:
            layout_from_depth = state.get("layout_from_depth") or {}
            if layout_from_depth:
                from designbridge.render.render_prompt import _layout_json_to_prompt_text
                layout_prompt = _layout_json_to_prompt_text(layout_from_depth)

        if layout_prompt:
            prompt = f"{prompt} {layout_prompt}"
            print(f"[renderer] layout_prompt injected: {layout_prompt[:80]}")

    _style_neg = (style_params.get("negative_prompt") or "").strip(", ")
    negative_prompt = f"{_BASE_NEGATIVE_PROMPT}, {_style_neg}" if _style_neg else _BASE_NEGATIVE_PROMPT
    _special = req.get("special_constraints") or {}
    if _special.get("wheelchair"):
        negative_prompt = f"{negative_prompt}, wheelchair, wheelchair user, mobility aid, disability equipment"
    if _special.get("children"):
        negative_prompt = f"{negative_prompt}, child, children, baby, toddler, kid"
    if _special.get("pets"):
        negative_prompt = f"{negative_prompt}, cat, dog, bird, rabbit, hamster, pet, animal"
    user_input = state.get("user_input") or {}

    vision = state.get("vision_features") or {}
    output_aspect = str(user_input.get("output_aspect") or "auto")
    output_size = _resolve_output_size(output_aspect, user_input.get("initial_image"))
    output_width, output_height = output_size
    generation_params: dict[str, Any] = {
        # 完整 prompt（不截斷）：testing 用，前端結構化需求卡片會顯示這份
        "prompt_preview": prompt,
        "negative_prompt_preview": negative_prompt or "",
        "output_aspect": output_aspect,
        "output_size": {"width": output_width, "height": output_height},
    }
    backend = "placeholder"

    if style_params:
        generation_params["style_profile_id"] = style_params.get("style_profile_id")
        generation_params["style_profile_name"] = style_params.get("style_profile_name")
        generation_params["style_strength"] = style_params.get("style_strength")

    # Get vision features for ControlNet (if available)
    depth_path = vision.get("depth")
    seg_path = vision.get("segmentation")

    # When the user re-plans layout, the input-photo depth no longer matches the new
    # furniture arrangement. Override it with the depth projected from the scene-graph
    # coordinates so the Layout Agent's precise placements actually control the render.
    using_projected_depth = False
    if req.get("hint_layout") and Config.ENABLE_LAYOUT_DEPTH_PROJECTION:
        _sg = state.get("scene_graph") or {}
        _proj_depth = _sg.get("projected_depth_path")
        if _proj_depth and Path(_proj_depth).exists():
            depth_path = _proj_depth
            using_projected_depth = True
            _proj_seg = _sg.get("projected_seg_path")
            if _proj_seg and Path(_proj_seg).exists():
                seg_path = _proj_seg
            print(f"[renderer] using scene-graph projected depth as ControlNet condition: {Path(_proj_depth).name}")

    # Condition images must match the output resolution, otherwise the backend stretches
    # them to the output aspect and the room geometry shears.
    if depth_path and Path(str(depth_path)).is_file():
        depth_path = _fit_condition_image(
            str(depth_path), output_size, render_dir / "conditions", f"{task_id}_depth"
        )

    # Boundaries from the segmentation, stacked on depth as a second ControlNet. The seg
    # map itself was only ever recorded as metadata — no backend consumed it — so nothing
    # was telling the model where one surface stops and the next begins.
    edge_path: str | None = None
    if Config.ENABLE_EDGE_CONTROL and seg_path and Path(str(seg_path)).is_file():
        edge_path = _seg_to_edge_condition(
            str(seg_path), output_size, render_dir / "conditions", f"{task_id}_edge"
        )

    controlnet_inputs: dict[str, str] = {}
    if depth_path:
        controlnet_inputs["depth"] = str(depth_path)
    if seg_path:
        controlnet_inputs["segmentation"] = str(seg_path)
    if edge_path:
        controlnet_inputs["edge"] = edge_path

    # Use 2D floor plan as structural guide when available
    scene_graph_data = state.get("scene_graph") or {}
    floor_plan_path = scene_graph_data.get("floor_plan_path")
    if floor_plan_path and Path(str(floor_plan_path)).is_file():
        controlnet_inputs["floor_plan"] = str(floor_plan_path)
        print(f"[renderer] 2D floor plan → 3D render guide: {Path(floor_plan_path).name}")

    # Inject furniture positions from scene_graph into prompt
    furniture_placements = scene_graph_data.get("furniture_placements") or []
    if furniture_placements:
        spatial_desc = _furniture_to_spatial_text(furniture_placements)
        if spatial_desc:
            layout_prefix = (
                f"Strictly follow this furniture arrangement: {spatial_desc}. "
                f"Exact positions must match the floor plan layout. "
            )
            prompt = layout_prefix + prompt
            generation_params["furniture_layout_injected"] = spatial_desc
            print(f"[renderer] Furniture layout injected: {spatial_desc[:120]}")

    # 1. Hugging Face Inference API (cloud Flux; no local download)
    hf_model_id = Config.FLUX_MODEL

    # Use style_reference_image as control image:
    # priority: user upload > Supabase matched image > depth map
    style_method = user_input.get("style_method", "ai_analysis")
    style_reference_image = user_input.get("style_reference_image")
    user_style_reference_local: str | None = None
    if isinstance(style_reference_image, str) and style_reference_image.strip():
        style_reference_candidate = style_reference_image.strip()
        if Path(style_reference_candidate).exists():
            user_style_reference_local = style_reference_candidate
        elif style_reference_candidate.startswith(("http://", "https://")):
            try:
                from designbridge.style.style_supabase import download_style_image

                downloaded_ref = download_style_image(style_reference_candidate)
                if downloaded_ref and downloaded_ref.exists():
                    user_style_reference_local = str(downloaded_ref)
            except Exception as e:
                print(f"⚠️  下載使用者風格參考圖失敗：{e}")

    if user_style_reference_local:
        control_img = user_style_reference_local
        controlnet_inputs["style_reference_image"] = user_style_reference_local
        if style_method == "ai_analysis":
            _kb_url = (style_params or {}).get("reference_image_url", "")
            _kb_text = (style_params or {}).get("style_summary", "").strip()
            _is_kb_image = (
                _kb_url
                and _kb_text
                and isinstance(style_reference_image, str)
                and style_reference_image.strip() == _kb_url
            )
            if _is_kb_image:
                # KB's English style_prompt is already folded into `prompt` by
                # _build_imagen_prompt_from_requirement; its Chinese description
                # (_kb_text) is UI-display-only, so skip re-injecting it here.
                print(f"📚 Supabase KB 圖片已作為風格參考（風格描述已由 style_prompt 注入，跳過 Gemini 分析）")
            else:
                style_vision_desc = timed_call(
                    "renderer.gemini_style_analysis", task_id,
                    _analyze_style_image_with_gemini, user_style_reference_local,
                )
                if style_vision_desc:
                    prompt = f"{prompt} Style reference: {style_vision_desc}"
                    generation_params["gemini_style_description"] = style_vision_desc
                    print(f"🎨 Gemini 風格描述已注入 prompt：{style_vision_desc[:80]}…")
    elif style_params and style_params.get("reference_image_path") and Path(style_params["reference_image_path"]).exists():
        control_img = style_params["reference_image_path"]
        controlnet_inputs["style_reference_image"] = control_img
        print(f"使用 Supabase 匹配圖作為風格參考：{Path(control_img).name}")
    else:
        control_img = depth_path if depth_path and Path(depth_path).exists() else None

    # IP-Adapter 模式：文字控制空間類型，圖像注入風格（fal.ai FLUX-general）
    if style_method == "ipadapter" and user_style_reference_local and backend == "placeholder":
        if not Config.FAL_KEY:
            print("⚠️  IP-Adapter 模式需要 FAL_KEY，改走 ai_analysis fallback")
        elif timed_call(
            "renderer.flux_ipadapter_fal", task_id,
            _render_flux_ipadapter_fal,
            user_style_reference_local, out_path, prompt=prompt,
            ip_adapter_scale=Config.FAL_IP_ADAPTER_SCALE,
            num_steps=Config.FAL_IP_ADAPTER_STEPS,
            guidance_scale=Config.FAL_IP_ADAPTER_GUIDANCE,
            output_size=(Config.FAL_IP_ADAPTER_SIZE, Config.FAL_IP_ADAPTER_SIZE),
        ):
            backend = "flux_ipadapter_fal"
            generation_params["model"] = "fal-ai/flux-general + XLabs IP-Adapter"
            generation_params["style_reference"] = user_style_reference_local
            generation_params["ip_adapter_scale"] = Config.FAL_IP_ADAPTER_SCALE

    # Redux 模式：本地 FLUX.1-Redux pipeline（需先在 HuggingFace 接受授權並下載模型）
    # DESIGNBRIDGE_ENABLE_FLUX_REDUX=true 才嘗試載入，避免未授權時每次報錯
    if style_method == "redux" and user_style_reference_local and backend == "placeholder":
        if not Config.ENABLE_FLUX_REDUX:
            print("⚠️  FLUX.1-Redux 未啟用（DESIGNBRIDGE_ENABLE_FLUX_REDUX=false），改走 ai_analysis fallback")
        elif Config.FAL_KEY and timed_call(
            "renderer.flux_redux_fal", task_id,
            _render_flux_redux_fal,
            user_style_reference_local, out_path, prompt=prompt, output_size=output_size,
            num_steps=Config.FAL_REDUX_STEPS, guidance_scale=Config.FAL_REDUX_GUIDANCE,
        ):
            backend = "flux_redux_fal"
            generation_params["model"] = "fal-ai/flux-1/dev/redux"
            generation_params["style_reference"] = user_style_reference_local
        elif timed_call(
            "renderer.flux_redux_local", task_id,
            _render_flux_redux_local,
            user_style_reference_local, out_path, prompt=prompt, output_size=output_size,
        ):
            backend = "flux_redux_local"
            generation_params["model"] = "black-forest-labs/FLUX.1-Redux-dev (local)"
            generation_params["style_reference"] = user_style_reference_local

    # Kontext LoRA：有 depth map 時優先，保留空間結構
    # depth_conditioning_scale: 1.0=完全保留結構, 0.0=忽略深度圖
    # lora scale 直接對應 depth_conditioning_scale，不需轉換
    depth_conditioning_scale = float(req.get("depth_conditioning_scale") or 0.85)
    depth_conditioning_scale = max(0.0, min(1.0, depth_conditioning_scale))
    # The LLM's depth_conditioning_scale is calibrated for real photo depth ("how much to
    # preserve an existing room's structure"). Projected/synthetic depth is geometrically
    # blockier (sharp axis-aligned furniture boxes, no natural surface variation) than what
    # ControlNet was trained on — conditioning that strongly on it renders furniture as
    # disconnected floating boxes instead of a coherent room, so cap it lower here.
    if using_projected_depth:
        depth_conditioning_scale = min(depth_conditioning_scale, Config.PROJECTED_DEPTH_MAX_CONDITIONING_SCALE)
    effective_depth_path = depth_path if depth_conditioning_scale >= 0.20 else None

    # 真正的 FLUX depth ControlNet（opt-in，需 FAL_KEY）：對深度幾何的約束遠強於 Kontext LoRA，
    # 讓 scene-graph 投影深度真正控制家具擺位。設 LAYOUT_DEPTH_CONTROL_BACKEND=controlnet 啟用。
    if (
        backend == "placeholder"
        and Config.LAYOUT_DEPTH_CONTROL_BACKEND == "controlnet"
        and Config.FAL_KEY
        and effective_depth_path and Path(str(effective_depth_path)).is_file()
    ):
        _extra_controls: list[dict[str, Any]] = []
        if edge_path:
            _extra_controls.append({
                "path": Config.EDGE_CONTROLNET_MODEL,
                "image_path": edge_path,
                "scale": Config.EDGE_CONDITIONING_SCALE,
                "mode": Config.EDGE_CONTROLNET_MODE or None,
            })

        if timed_call(
            "renderer.flux_controlnet_depth_fal", task_id,
            _render_flux_controlnet_depth_fal,
            prompt, str(effective_depth_path), out_path,
            conditioning_scale=depth_conditioning_scale,
            num_steps=Config.FAL_CONTROLNET_STEPS,
            guidance_scale=Config.FAL_CONTROLNET_GUIDANCE,
            output_size=output_size,
            extra_controls=_extra_controls,
        ):
            backend = "flux_controlnet_depth_fal"
            generation_params["model"] = f"fal-ai/flux-general + {Config.DEPTH_CONTROLNET_MODEL}"
            generation_params["depth_conditioning_scale"] = depth_conditioning_scale
            if _extra_controls:
                generation_params["edge_controlnet_model"] = Config.EDGE_CONTROLNET_MODEL
                generation_params["edge_conditioning_scale"] = Config.EDGE_CONDITIONING_SCALE

    if backend == "placeholder" and effective_depth_path and Path(str(effective_depth_path)).is_file():
        if Config.HF_TOKEN:
            if timed_call(
                "renderer.hf_kontext", task_id,
                _render_hf_kontext,
                prompt, str(effective_depth_path), out_path,
                depth_conditioning_scale=depth_conditioning_scale,
            ):
                backend = "hf_kontext"
                generation_params["model"] = Config.KONTEXT_LORA_MODEL
                generation_params["provider"] = Config.KONTEXT_PROVIDER
                generation_params["depth_conditioning_scale"] = depth_conditioning_scale

    # Fallback when there is no depth map at all — neither an uploaded photo's nor one
    # projected upstream by the layout agent. The 2D plan is still a complete description
    # of where the furniture goes, so project it here (footprint canny for placement,
    # room-shell depth for structure) rather than rendering the layout blind.
    # Layout-driven depth ControlNet: project the 2D floor plan into an eye-level
    # depth map (same viewpoint as the render) and drive a FLUX depth ControlNet so
    # furniture positions from the 2D plan are actually honored in 3D.
    # Only in the text→design flow (no uploaded photo / no real depth map).
    if (
        backend == "placeholder"
        and Config.ENABLE_LAYOUT_CONTROLNET
        and Config.FAL_KEY
        and furniture_placements
        and not (effective_depth_path and Path(str(effective_depth_path)).is_file())
    ):
        layout_depth_path: str | None = None
        layout_edge_path: str | None = None
        try:
            from designbridge.layout.layout_projection import (
                render_layout_depth_map,
                render_layout_edge_map,
            )

            # Prefer the REAL room dims carried from the Step-1 layout (scene_graph);
            # only fall back to the requirement analyzer's guess when absent. Using the
            # wrong size distorts the projection's aspect ratio and moves furniture
            # off-plan.
            _room = (req.get("space_info") or {}).get("estimated_size") or {}
            _rw = float(scene_graph_data.get("room_w") or _room.get("width", 4.0) or 4.0)
            _rd = float(scene_graph_data.get("room_d") or _room.get("depth", 4.0) or 4.0)
            # Elevated three-quarter "look-at" camera so the floor layout reads clearly.
            _cam = {
                "eye_h": Config.LAYOUT_CAM_EYE_H,
                "setback": Config.LAYOUT_CAM_SETBACK,
                "target_h": Config.LAYOUT_CAM_TARGET_H,
                "target_depth_frac": Config.LAYOUT_CAM_TARGET_DEPTH_FRAC,
                "fov_v_deg": Config.LAYOUT_CAM_FOV,
            }
            # Canny of furniture FOOTPRINTS = distance-independent placement without
            # forcing cuboid shapes; depth of the room shell = 3D structure.
            layout_edge_path = render_layout_edge_map(
                furniture_placements, task_id, room_w=_rw, room_d=_rd,
                img_w=output_width, img_h=output_height,
                footprints_only=True, cam_kwargs=_cam,
            )
            layout_depth_path = render_layout_depth_map(
                furniture_placements, task_id, room_w=_rw, room_d=_rd,
                img_w=output_width, img_h=output_height,
                semantic_shapes=Config.ENABLE_SEMANTIC_SHAPES, cam_kwargs=_cam,
            )
        except Exception as e:
            print(f"⚠️  layout projection failed: {e}")

        if layout_depth_path and Path(layout_depth_path).is_file():
            controlnet_inputs["layout_depth"] = layout_depth_path
            if layout_edge_path:
                controlnet_inputs["layout_footprint_edges"] = layout_edge_path
            # Add tidiness/quality cues so the model renders clean, well-formed
            # furniture (no draped clothes, tables keep their legs, etc.). A negative
            # prompt can't be used — it breaks the ControlNet-Union pipeline on fal.
            layout_prompt = (
                "Elevated three-quarter photorealistic interior view. " + prompt +
                " Clean tidy space, well-proportioned realistic furniture with proper legs, "
                "nothing draped on the sofa, professional interior design photography, high detail."
            )
            if _render_flux_depth_controlnet_fal(
                layout_prompt,
                layout_depth_path,
                out_path,
                edge_path=layout_edge_path,
                edge_conditioning_scale=Config.FAL_EDGE_CONDITIONING_SCALE,
                conditioning_scale=Config.FAL_DEPTH_CONDITIONING_SCALE,
                depth_control_end=Config.FAL_DEPTH_CONTROL_END,
                edge_control_end=Config.FAL_EDGE_CONTROL_END,
                num_steps=Config.FAL_DEPTH_STEPS,
                guidance_scale=Config.FAL_DEPTH_GUIDANCE,
                output_size=output_size,
            ):
                backend = "flux_depth_controlnet_fal"
                generation_params["model"] = Config.FAL_DEPTH_CONTROLNET_MODEL
                generation_params["provider"] = "fal-ai/flux-general"
                generation_params["layout_edge_conditioning_scale"] = Config.FAL_EDGE_CONDITIONING_SCALE
                generation_params["layout_depth_conditioning_scale"] = Config.FAL_DEPTH_CONDITIONING_SCALE
                generation_params["layout_depth_control_end"] = Config.FAL_DEPTH_CONTROL_END
                generation_params["layout_edge_control_end"] = Config.FAL_EDGE_CONTROL_END
                generation_params["layout_semantic_shapes"] = Config.ENABLE_SEMANTIC_SHAPES
                generation_params["layout_control_source"] = "2d_plan_footprint+depth"
                print("[renderer] 2D plan → footprint canny + elevated depth → FLUX Union render")

    # Last structural resort: no depth map, but a 2D floor plan exists. Feeding the plan
    # itself to Kontext is a weaker signal than projected depth, but it still anchors the
    # room's proportions and furniture positions far better than an unconditioned render.
    if (
        backend == "placeholder"
        and Config.HF_TOKEN
        and floor_plan_path
        and Path(str(floor_plan_path)).is_file()
    ):
        _SPATIAL_STRENGTH = {"none": 0.55, "minor": 0.60, "major": 0.75}
        _kontext_strength = _SPATIAL_STRENGTH.get(
            (req.get("spatial_change_level") or "minor").lower(), 0.70
        )
        print("[renderer] No depth map — using 2D floor plan as Kontext structural guide")
        if timed_call(
            "renderer.hf_kontext_floor_plan", task_id,
            _render_hf_kontext,
            prompt, str(floor_plan_path), out_path, strength=_kontext_strength,
        ):
            backend = "hf_kontext"
            generation_params["model"] = Config.KONTEXT_LORA_MODEL
            generation_params["provider"] = Config.KONTEXT_PROVIDER
            generation_params["kontext_strength"] = _kontext_strength
            generation_params["kontext_control_source"] = "floor_plan"

    # AI 分析模式 fallback：HF Inference API
    if backend == "placeholder" and Config.ENABLE_HF_INFERENCE and Config.HF_TOKEN:
        if timed_call(
            "renderer.hf_inference", task_id,
            _render_hf_inference,
            prompt, out_path, model=hf_model_id, output_size=output_size,
        ):
            backend = "hf_inference"
            generation_params["model"] = hf_model_id
            generation_params["provider"] = Config.HF_INFERENCE_PROVIDER

    # 2. fal.ai FLUX 純文字生圖（雲端，不需 depth/style 參考圖；HF 兩條路都失敗時的快速備援）
    if backend == "placeholder" and Config.FAL_KEY:
        if timed_call(
            "renderer.flux_fal", task_id,
            _render_flux_fal,
            prompt, out_path, output_size=output_size,
        ):
            backend = "flux_fal"
            generation_params["model"] = "fal-ai/flux/schnell"

    # 3. Local Flux model（最後手段：CPU 推理慢，且首次會下載整包模型，僅在雲端全部失敗時使用）
    if backend == "placeholder" and Config.ENABLE_FLUX_FALLBACK:
        if timed_call("renderer.flux_local", task_id, _render_flux, prompt, out_path):
            backend = "flux"
            generation_params["model"] = hf_model_id
        else:
            generation_params["render_error"] = "local render failed"

    # 4. Fallback to placeholder
    if backend == "placeholder":
        generation_params["render_error"] = "API unavailable: both Kontext and HF Inference failed"
        print("⚠️  Renderer: all API backends failed, no image generated")

    generation_params["backend"] = backend
    path_str = str(out_path)
    render_result: dict[str, Any] = {
        "generated_image_path": path_str,
        "generation_params": generation_params,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Add controlnet_inputs if any were used
    if controlnet_inputs:
        render_result["controlnet_inputs"] = controlnet_inputs

    return {
        "generated_image": path_str,
        "render_result": render_result,
    }
