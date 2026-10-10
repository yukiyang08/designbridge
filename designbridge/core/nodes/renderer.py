"""Renderer 節點：依條件選後端出圖。"""

from __future__ import annotations

import json
import secrets
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
    _render_flux_controlnet_depth_fal,
    _render_flux_depth_controlnet_fal,
    _render_flux_img2img_fal,
    _render_flux_fal,
)
from designbridge.style.style_apply import resolve_style_loras

_BASE_NEGATIVE_PROMPT = (
    "people, person, human, man, woman, child, hands, face, "
    "animal, pet, cat, dog, bird, "
    "text, watermark, signature, logo, "
    "embossed texture, relief carving, engraved pattern, corrugated surface, "
    "bumpy wall texture, mosaic screen, pixelated glitch"
)


def _fit_condition_image(
    image_path: str, output_size: tuple[int, int], out_dir: Path, tag: str,
    *, nearest: bool = False,
) -> str:
    """置中裁切並縮放條件圖（深度/分割）到輸出尺寸，避免後端拉伸造成房間變形。已符合則回傳原路徑。

    `nearest` 用於標籤圖，避免插值產生不存在的 id。
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
                if src_ratio > target_ratio:      # 太寬：裁左右
                    crop_w = int(round(src_h * target_ratio))
                    left = (src_w - crop_w) // 2
                    box = (left, 0, left + crop_w, src_h)
                else:                              # 太高：裁上下
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


def _denoise_labels(labels: "np.ndarray", min_region_px: int = 40) -> "np.ndarray":
    """把小於 min_region_px 的標籤碎塊併入最近的區域。

    分割模型常把雜物/布料皺褶切成許多碎塊，每塊都會變成邊界，
    ControlNet 會把它們當接縫畫出來（牆面出現浮雕狀斑塊）。
    """
    import numpy as np
    from scipy import ndimage

    keep = np.ones(labels.shape, dtype=bool)
    for val in np.unique(labels):
        comp, n = ndimage.label(labels == val)
        if n == 0:
            continue
        sizes = ndimage.sum(np.ones_like(comp), comp, index=np.arange(1, n + 1))
        small_ids = np.where(sizes < min_region_px)[0] + 1
        if len(small_ids):
            keep &= ~np.isin(comp, small_ids)

    if keep.all():
        return labels

    # 被移除的像素取最近倖存像素的標籤
    _, (iy, ix) = ndimage.distance_transform_edt(~keep, return_indices=True)
    return np.where(keep, labels, labels[iy, ix])


def _seg_to_edge_condition(
    seg_path: str, output_size: tuple[int, int], out_dir: Path, tag: str
) -> str | None:
    """分割圖 → 黑底白線的物件邊界圖，尺寸對齊輸出。

    標籤圖是自己產生的，直接比對相鄰像素 id 即可，不必跑 Canny（只會多雜訊）。
    先縮放再抽邊界，線條才乾淨（先畫線再縮小會斷成虛線）。
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

        labels = _denoise_labels(labels)

        edge = np.zeros(labels.shape, dtype=bool)
        edge[:, :-1] |= labels[:, :-1] != labels[:, 1:]
        edge[:-1, :] |= labels[:-1, :] != labels[1:, :]
        # 加粗到 2px：細線撐不過 VAE 編碼與 ControlNet 降採樣
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


# 家具描述短語：讓深度圖上的方塊被畫成可辨識的家具（小件如扶手椅容易被併入鄰近家具）
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


def _projection_instances(depth_path: str) -> list[dict]:
    """讀取深度圖旁的投影 meta（每件家具在影像上的實際 bbox）。沒有就回空 list。"""
    meta = Path(str(depth_path)).with_name(
        Path(str(depth_path)).name.replace("_projected_depth", "_projection").rsplit(".", 1)[0] + ".json"
    )
    if not meta.is_file():
        return []
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get("instances") or []
    except (OSError, ValueError) as e:
        print(f"⚠️ 讀取投影 meta 失敗（{e}）")
        return []


def _instances_to_spatial_text(instances: list[dict]) -> str:
    """用家具在投影影像上的實際落點描述位置（而非平面圖座標）。

    透視後平面圖方位未必對得上畫面，貼牆家具還可能出框；
    改用投影後的 bbox，文字才對齊深度圖上的方塊，出框者不提。
    """
    parts: list[str] = []
    for inst in instances:
        if not inst.get("visible"):
            continue
        raw = inst.get("type", "")
        desc = _FURNITURE_DESC.get(raw, "a " + str(raw).replace("_", " "))
        cx, cy = float(inst.get("cx", 0.5)), float(inst.get("cy", 0.5))
        h_zone = "left" if cx < 0.38 else ("right" if cx > 0.62 else "center")
        # 畫面越下方離相機越近
        v_zone = "foreground" if cy > 0.66 else ("background" if cy < 0.42 else "mid-ground")
        where = "in the center" if h_zone == "center" else f"on the {h_zone}"
        parts.append(f"{desc} {where} of the frame, in the {v_zone}")
    return "; ".join(parts[:12])


def _furniture_to_spatial_text(placements: list[dict]) -> str:
    """平面圖座標（0~1）轉成位置描述，注入 prompt。

    x: 0 左牆 → 1 右牆；y: 0 後牆 → 1 入口牆。離牆 0.12 內視為「靠牆」。
    """
    PAD = 0.12
    parts: list[str] = []
    for item in placements[:12]:
        raw = item.get("type", "")
        desc = _FURNITURE_DESC.get(raw, "a " + raw.replace("_", " "))
        x, y = item.get("x", 0.5), item.get("y", 0.5)
        w, h = item.get("w", 0.1), item.get("h", 0.1)
        cx, cy = x + w / 2, y + h / 2

        # 永遠保留左右/前後分區以維持家具左右順序，靠牆資訊是附加而非取代
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

        # 基本位置：左右側 + 前後區
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
    """Renderer：依序嘗試各雲端後端出圖，全部失敗則不產圖。adjuster 已產出 inpaint 圖時直接跳過。"""
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
    composed_prompt = (state.get("composed_prompt") or "").strip()
    composed_includes_furniture = bool(state.get("composed_includes_furniture"))
    if composed_prompt:
        prompt = composed_prompt
    else:
        # composer 被跳過或失敗時走這裡，is_style_swap 的理由見 composer.py
        prompt = _build_imagen_prompt_from_requirement(
            req, style_params=style_params, user_text_prompt=_user_text_prompt,
            is_style_swap=bool(state.get("generated_image")),
        )

    # 使用者要求重排佈局時才注入 layout；composer 已合併過就不重複注入
    if req.get("hint_layout") and not composed_includes_furniture:
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
    user_input = state.get("user_input") or {}
    # debug-console 用：單次請求覆寫 ControlNet/LoRA 設定，免改環境變數
    render_overrides = user_input.get("render_overrides") or {}

    vision = state.get("vision_features") or {}
    output_aspect = str(user_input.get("output_aspect") or "auto")
    output_size = _resolve_output_size(output_aspect, user_input.get("initial_image"))
    output_width, output_height = output_size
    generation_params: dict[str, Any] = {
        # 完整 prompt（不截斷），前端需求卡片會顯示
        "prompt_preview": prompt,
        "negative_prompt_preview": negative_prompt or "",
        "output_aspect": output_aspect,
        "output_size": {"width": output_width, "height": output_height},
        # true = composer 合併成功；false = 落回字串硬接（composer 被跳過或 LLM 失敗）
        "composer_used": bool(composed_prompt),
        "composer_includes_furniture": composed_includes_furniture,
    }
    # 同房間換風格沿用上一輪 seed（由 API 帶入），首次才隨機；記進 generation_params 供下輪使用
    seed = user_input.get("seed")
    if seed is None:
        seed = secrets.randbelow(2**31)
    seed = int(seed)
    generation_params["seed"] = seed
    backend = "placeholder"

    style_loras = resolve_style_loras(style_params.get("style_profile_id"))
    # debug-console 的 LoRA 覆寫在此統一套用，所有後端都吃得到
    # （controlnet_* 覆寫只作用於下方單一 ControlNet 分支）
    if render_overrides.get("loras") is not None:
        style_loras = render_overrides["loras"]
    if render_overrides.get("disable_lora"):
        style_loras = []

    if style_params:
        generation_params["style_profile_id"] = style_params.get("style_profile_id")
        generation_params["style_profile_name"] = style_params.get("style_profile_name")
        generation_params["style_strength"] = style_params.get("style_strength")
    if style_loras:
        generation_params["style_lora"] = style_loras[0]["path"]

    # 照片的深度/分割圖（有的話）
    depth_path = vision.get("depth")
    seg_path = vision.get("segmentation")

    # 重排佈局後原照片深度與新家具位置不符，改用 scene graph 投影的深度
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

    # 條件圖尺寸需與輸出一致，否則被拉伸、房間變形
    if depth_path and Path(str(depth_path)).is_file():
        depth_path = _fit_condition_image(
            str(depth_path), output_size, render_dir / "conditions", f"{task_id}_depth"
        )

    # 分割圖抽邊界，當第二個 ControlNet 疊在深度上（深度本身缺少明確的物件邊界）
    edge_path: str | None = None
    if (
        Config.ENABLE_EDGE_CONTROL
        and not render_overrides.get("disable_edge_control")
        and seg_path and Path(str(seg_path)).is_file()
    ):
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

    # 有 2D 平面圖時當結構引導
    scene_graph_data = state.get("scene_graph") or {}
    floor_plan_path = scene_graph_data.get("floor_plan_path")
    if floor_plan_path and Path(str(floor_plan_path)).is_file():
        controlnet_inputs["floor_plan"] = str(floor_plan_path)
        print(f"[renderer] 2D floor plan → 3D render guide: {Path(floor_plan_path).name}")

    # 把 scene graph 的家具位置寫進 prompt
    furniture_placements = scene_graph_data.get("furniture_placements") or []
    if furniture_placements and composed_includes_furniture:
        generation_params["layout_prompt_source"] = "composer"
    elif furniture_placements:
        # 走投影深度時用家具在深度圖上的實際落點描述，「左邊」才對得上深度圖的輪廓
        spatial_desc = ""
        if using_projected_depth and depth_path:
            _instances = _projection_instances(str(scene_graph_data.get("projected_depth_path") or ""))
            if _instances:
                spatial_desc = _instances_to_spatial_text(_instances)
                _dropped = [i["type"] for i in _instances if not i.get("visible")]
                if _dropped:
                    print(f"[renderer] 投影後不在畫面內，已從 prompt 移除：{', '.join(_dropped)}")
                if spatial_desc:
                    generation_params["layout_prompt_source"] = "projected_image_space"
        if not spatial_desc:
            spatial_desc = _furniture_to_spatial_text(furniture_placements)
        if spatial_desc:
            layout_prefix = (
                f"Strictly follow this furniture arrangement: {spatial_desc}. "
                f"Exact positions must match the floor plan layout. "
            )
            prompt = layout_prefix + prompt
            generation_params["furniture_layout_injected"] = spatial_desc
            print(f"[renderer] Furniture layout injected: {spatial_desc[:120]}")

    # HF Inference 使用的模型
    hf_model_id = Config.FLUX_MODEL

    # 風格參考圖優先序：使用者上傳 > Supabase 配對圖 > 深度圖
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
                # KB 的英文 style_prompt 已併入 prompt；中文描述僅供 UI 顯示，不重複注入
                print("📚 Supabase KB 圖片已作為風格參考（風格描述已由 style_prompt 注入，跳過 Gemini 分析）")
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

    # 深度條件強度：1.0 完全保留結構、0.0 忽略深度圖（Kontext LoRA 的 scale 與它相同）。
    # LLM 沒給值（含呼叫失敗）時預設 0.6：0.85 太僵，目標風格差異大時模型無法重繪材質，
    # 只會在原幾何上貼一層雕刻/浮雕感。
    depth_conditioning_scale = float(req.get("depth_conditioning_scale") or 0.6)
    depth_conditioning_scale = max(0.0, min(1.0, depth_conditioning_scale))
    # 投影深度是軸對齊的方塊，條件過強會讓家具變成漂浮方塊，故壓低上限
    if using_projected_depth:
        depth_conditioning_scale = min(depth_conditioning_scale, Config.PROJECTED_DEPTH_MAX_CONDITIONING_SCALE)
    else:
        # 實測 >=0.85 會把平坦深度區（遠牆）畫成雜訊，原因見 config.REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE
        depth_conditioning_scale = min(depth_conditioning_scale, Config.REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE)
    effective_depth_path = depth_path if depth_conditioning_scale >= 0.20 else None

    # img2img 只給 debug-console 手動測試（render_overrides.img2img_base_image），不自動接手換風格：
    # 實測換風格後風格差異不明顯，改走下方 ControlNet/Kontext 重新生成。
    _img2img_base = render_overrides.get("img2img_base_image")
    if backend == "placeholder" and Config.FAL_KEY and _img2img_base:
        _img2img_strength = render_overrides.get("img2img_strength")
        _img2img_strength = 0.5 if _img2img_strength is None else max(0.01, min(1.0, float(_img2img_strength)))
        # 風格 LoRA 對 img2img 沒幫助且變慢，預設不套用（見 config.IMG2IMG_USE_LORA）；
        # debug-console 明確指定 loras 時照放行
        _img2img_loras = style_loras if (Config.IMG2IMG_USE_LORA or render_overrides.get("loras") is not None) else []
        if timed_call(
            "renderer.flux_img2img_fal", task_id,
            _render_flux_img2img_fal,
            prompt, str(_img2img_base), out_path,
            strength=_img2img_strength,
            loras=_img2img_loras,
        ):
            backend = "flux_img2img_fal"
            generation_params["model"] = "fal-ai/flux-general/image-to-image"
            generation_params["img2img_strength"] = _img2img_strength
            generation_params["img2img_base_image"] = str(_img2img_base)
            generation_params["img2img_source"] = "debug_override" if render_overrides.get("img2img_base_image") else "style_swap"
            if _img2img_loras:
                generation_params["loras"] = _img2img_loras
            controlnet_inputs["img2img_base"] = str(_img2img_base)

    # FLUX depth ControlNet（需 FAL_KEY）：約束力遠強於 Kontext LoRA，讓投影深度控制家具擺位
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

        # debug-console 覆寫：單次請求換 ControlNet 模型/強度/步數
        _ro = render_overrides
        _cn_model = _ro.get("controlnet_model") or Config.DEPTH_CONTROLNET_MODEL
        _cn_scale = _ro.get("controlnet_scale")
        _cn_scale = depth_conditioning_scale if _cn_scale is None else max(0.0, min(1.0, float(_cn_scale)))
        _cn_steps = _ro.get("controlnet_steps") or Config.FAL_CONTROLNET_STEPS
        _cn_guidance = _ro.get("controlnet_guidance") or Config.FAL_CONTROLNET_GUIDANCE
        _cn_control_end = _ro.get("controlnet_control_end")
        _cn_control_end = Config.REAL_PHOTO_DEPTH_CONTROL_END if _cn_control_end is None else max(0.0, min(1.0, float(_cn_control_end)))

        if timed_call(
            "renderer.flux_controlnet_depth_fal", task_id,
            _render_flux_controlnet_depth_fal,
            prompt, str(effective_depth_path), out_path,
            conditioning_scale=_cn_scale,
            control_end=_cn_control_end,
            num_steps=_cn_steps,
            guidance_scale=_cn_guidance,
            output_size=output_size,
            extra_controls=_extra_controls,
            loras=style_loras,
            controlnet_model=_cn_model,
            seed=seed,
        ):
            backend = "flux_controlnet_depth_fal"
            generation_params["model"] = f"fal-ai/flux-general + {_cn_model}"
            generation_params["depth_conditioning_scale"] = _cn_scale
            generation_params["controlnet_control_end"] = _cn_control_end
            generation_params["controlnet_steps"] = _cn_steps
            generation_params["controlnet_guidance"] = _cn_guidance
            if style_loras:
                generation_params["loras"] = style_loras
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

    # 完全沒有深度圖（沒有照片深度，也沒有上游投影）時，在這裡用 2D 平面圖投影：
    # 家具輪廓 canny 管位置，房間外殼深度管結構。僅限文字生成流程。
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

            # 優先用 Step-1 佈局帶來的真實房間尺寸，否則投影比例失真、家具偏離平面圖
            _room = (req.get("space_info") or {}).get("estimated_size") or {}
            _rw = float(scene_graph_data.get("room_w") or _room.get("width", 4.0) or 4.0)
            _rd = float(scene_graph_data.get("room_d") or _room.get("depth", 4.0) or 4.0)
            # 接近視線高度的鏡頭（參數說明見 Config.LAYOUT_CAM_*）
            _cam = {
                "eye_h": Config.LAYOUT_CAM_EYE_H,
                "setback": Config.LAYOUT_CAM_SETBACK,
                "target_h": Config.LAYOUT_CAM_TARGET_H,
                "target_depth_frac": Config.LAYOUT_CAM_TARGET_DEPTH_FRAC,
                "fov_v_deg": Config.LAYOUT_CAM_FOV,
            }
            # 家具輪廓 canny 管位置（不強迫長方體），房間外殼深度管 3D 結構
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
            # 加整潔/品質提示（不能用 negative prompt，會弄壞 fal 上的 ControlNet-Union）
            layout_prompt = (
                "Natural eye-level wide-angle photorealistic interior view, the whole room "
                "visible with solid walls and ceiling. " + prompt +
                " Clean tidy space, well-proportioned realistic furniture with proper legs, "
                "nothing draped on the sofa, professional interior design photography, high detail."
            )
            if timed_call(
                "renderer.fal_flux_depth_controlnet", task_id,
                _render_flux_depth_controlnet_fal,
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
                loras=style_loras,
                seed=seed,
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

    # 最後的結構手段：沒深度圖但有平面圖，直接餵 Kontext，仍比無條件生成貼近房間比例與家具位置
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

    # HF Inference（純文字出圖）
    if backend == "placeholder" and Config.ENABLE_HF_INFERENCE and Config.HF_TOKEN:
        if timed_call(
            "renderer.hf_inference", task_id,
            _render_hf_inference,
            prompt, out_path, model=hf_model_id, output_size=output_size,
        ):
            backend = "hf_inference"
            generation_params["model"] = hf_model_id
            generation_params["provider"] = Config.HF_INFERENCE_PROVIDER

    # fal.ai FLUX 純文字出圖（雲端備援）
    if backend == "placeholder" and Config.FAL_KEY:
        if timed_call(
            "renderer.flux_fal", task_id,
            _render_flux_fal,
            prompt, out_path, output_size=output_size,
        ):
            backend = "flux_fal"
            generation_params["model"] = "fal-ai/flux/schnell"

    # 全部後端失敗
    if backend == "placeholder":
        generation_params["render_error"] = "所有雲端後端皆失敗"
        print("⚠️  Renderer: all API backends failed, no image generated")

    generation_params["backend"] = backend
    path_str = str(out_path)
    render_result: dict[str, Any] = {
        "generated_image_path": path_str,
        "generation_params": generation_params,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # 有用到的 ControlNet 輸入才記錄
    if controlnet_inputs:
        render_result["controlnet_inputs"] = controlnet_inputs

    result: dict[str, Any] = {
        "generated_image": path_str,
        "render_result": render_result,
    }

    # 這輪完全沒有深度可用時（純文字/無 hint_layout），對生成圖補跑深度估計存進 vision_features，
    # 下次換風格才有結構可鎖，避免整張重新構圖。
    if not vision.get("depth") and not using_projected_depth and backend != "placeholder" and Path(path_str).is_file():
        try:
            from designbridge.layout.vision import run_depth_estimation
            new_depth_path, _ = timed_call(
                "renderer.post_depth_estimation", task_id,
                run_depth_estimation,
                path_str, model_name=Config.DEPTH_MODEL, out_dir=render_dir / "conditions",
            )
            result["vision_features"] = {**vision, "depth": new_depth_path, "depth_source": "post_estimate"}
            print(f"[renderer] 這輪沒有 depth 輸入，已對生成結果補跑深度估計供下次換風格鎖定結構：{new_depth_path}")
        except Exception as e:
            print(f"[renderer] 補跑深度估計失敗（{e}），下次換風格仍不會有結構鎖定")

    return result
