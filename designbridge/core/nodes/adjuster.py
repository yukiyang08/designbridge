"""Design Adjuster graph node — localized inpainting on the initial image."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from designbridge.core.state import DesignBridgeState
from designbridge.render.inpaint import (
    mask_from_segmentation,
    expand_mask_by_segmentation,
    fallback_center_mask,
    generate_mask_with_sam2,
    run_lama_inpainting,
    build_inpaint_prompt,
    run_inpainting,
    run_hf_inpainting,
    run_fal_inpainting,
    load_mask_from_path,
)


def _bbox_mask_from_vision(image_path: str, target_object: str, img_size: tuple) -> Any:
    """
    當 segmentation 找不到目標物件（mask 過小）時，
    請 Gemini Vision 直接給出物件的 bounding box，用來生成 mask。
    """
    from PIL import Image, ImageDraw, ImageFilter

    prompt = f"""Look at this interior design image.
Find the "{target_object}" in the image.
Return ONLY valid JSON with the bounding box as fractions of image dimensions (0.0 to 1.0):
{{"x1": 0.3, "y1": 0.2, "x2": 0.6, "y2": 0.5}}
Where x1,y1 is top-left corner and x2,y2 is bottom-right corner.
If the object is not visible in the image, return: {{"not_found": true}}"""

    try:
        from designbridge.render.llm import call_llm
        raw = call_llm(prompt, images=[image_path], max_tokens=300, temperature=0.0)
        raw = raw.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        bbox = json.loads(raw.strip())
        if bbox.get("not_found"):
            print(f"[adjuster] vision bbox: '{target_object}' not found in image")
            return None
        w, h = img_size
        x1 = int(bbox["x1"] * w)
        y1 = int(bbox["y1"] * h)
        x2 = int(bbox["x2"] * w)
        y2 = int(bbox["y2"] * h)
        mask = Image.new("L", img_size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rectangle([x1, y1, x2, y2], fill=255)
        mask = mask.filter(ImageFilter.MaxFilter(21))
        print(f"[adjuster] vision bbox: '{target_object}' at ({x1},{y1})-({x2},{y2})")
        return mask
    except Exception as e:
        print(f"[adjuster] _bbox_mask_from_vision failed ({e})")
        return None


def analyze_edit_intent(
    text: str,
    image_path: str,
    seg_meta_path: str | None,
) -> dict:
    """
    用 Gemini Vision 同時判斷：
    - action: remove / replace / modify_style / add
    - seg_labels: 要操作的物件（從圖中已偵測到的 present_labels 中選）
    - replace_with: 若 action=replace，描述替換目標

    比起純字典比對，能正確處理位置語境（「床上電腦」→ target=laptop, not bed）
    和任意自然語言 prompt。
    """
    # 讀取圖中實際偵測到的物件清單，讓 LLM 從真實存在的 label 中選
    available_labels: list[str] = []
    if seg_meta_path and Path(seg_meta_path).is_file():
        with open(seg_meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        labels_dict = meta.get("present_labels") or meta.get("labels") or {}
        available_labels = list(labels_dict.values())

    labels_hint = f"Objects detected in the image: {available_labels}" if available_labels else ""

    prompt = f"""You are an interior design AI assistant.
Analyze this modification request and return JSON only (no markdown, no explanation).

User request: "{text}"
{labels_hint}

Return this exact JSON:
{{
  "action": "remove",
  "seg_labels": ["<label>"],
  "replace_with": null
}}

Where action must be one of: remove | replace | modify_style | add
- remove: 移除/刪除/去除/拿掉/清除/刪掉
- replace: 換掉/換成/改成/替換/換一個
- modify_style: 改顏色/改風格/換材質/換色
- add: 加入/添加/放一個/增加

seg_labels rules:
- Pick the TARGET OBJECT being modified, NOT its location.
  Example: "移除床上電腦" → ["laptop"] not ["bed"]
- If the object appears in the detected list, use that exact label name.
- If not in the list, use the best English noun (e.g. "laptop", "computer").

replace_with: describe the new object only if action=replace, else null."""

    try:
        from designbridge.render.llm import call_llm
        images = [image_path] if image_path and Path(image_path).is_file() else None
        raw = call_llm(prompt, images=images, max_tokens=500, temperature=0.0)
        raw = raw.strip()
        # 去掉 LLM 可能包的 markdown fence
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        action      = result.get("action", "modify_style")
        seg_labels  = [l.lower() for l in (result.get("seg_labels") or []) if l]
        replace_with = result.get("replace_with")
        print(f"[adjuster] vision intent → action={action}  seg_labels={seg_labels}")
        return {"action": action, "seg_labels": seg_labels, "replace_with": replace_with}
    except Exception as e:
        print(f"[adjuster] analyze_edit_intent failed ({e}), fallback to modify_style")
        return {"action": "modify_style", "seg_labels": [], "replace_with": None}


def adjuster_agent_stub(state: DesignBridgeState) -> dict[str, Any]:
    """
    Design Adjuster Agent：對初始圖片進行局部 inpainting。
    觸發條件：requirement_analyzer/design_director 判斷 routing_decision = "design_adjuster"。
    """
    from PIL import Image

    task_id = state.get("task_id") or str(uuid.uuid4())
    user_input = state.get("user_input") or {}
    req = state.get("structured_requirement") or {}
    vision = state.get("vision_features") or {}
    style_params = state.get("style_params")

    image_path = user_input.get("initial_image", "")
    manual_mask_path = user_input.get("mask_image")   # 手繪遮罩路徑（選填）

    # 沒有原圖就無法 inpaint，跳過
    if not image_path or not Path(image_path).is_file():
        return {
            "intermediate_outputs": {
                **(state.get("intermediate_outputs") or {}),
                "adjuster_agent": "no_initial_image_skipped",
            }
        }

    # 決定要修改哪些物件
    constraints = req.get("layout_constraints") or {}
    must_remove = constraints.get("must_remove") or []
    must_add = constraints.get("must_add") or []
    target_labels = must_remove if must_remove else ["furniture"]
    target_objects = must_add if must_add else target_labels

    # Mask 生成優先序：
    #   有手繪 + 有 segmentation → 展開成完整物件遮罩（方式二）
    #   只有手繪                 → 直接用手繪遮罩
    #   只有 segmentation        → 從文字 prompt 解析物件標籤
    #   都沒有                   → 中央 fallback
    original_img = Image.open(image_path)
    img_size = original_img.size

    seg_path = vision.get("segmentation")
    seg_meta = vision.get("segmentation_meta")
    has_seg  = bool(seg_path and seg_meta
                    and Path(str(seg_path)).is_file()
                    and Path(str(seg_meta)).is_file())
    print(f"[adjuster] seg_path: {seg_path}  exists={has_seg}")

    edit_action      = None   # 由 analyze_edit_intent 填入（無手繪遮罩時）
    replace_with     = None
    effective_labels: list[str] = []

    has_manual_mask = bool(manual_mask_path and Path(str(manual_mask_path)).is_file())

    if has_manual_mask:
        drawn_mask = load_mask_from_path(str(manual_mask_path), img_size)

        # 若有 segmentation，先算出手繪範圍觸碰到的物件類別完整展開遮罩，
        # 當作 SAM 2 box prompt 的輔助範圍：避免使用者只塗到物件局部
        # （例如椅背/椅座，漏畫輪子、桌腳），導致 SAM 2 的框也只框住局部
        seg_aux_mask = None
        seg_aux_labels: list[str] = []
        seg_aux_per_object: list[tuple[Any, Any, str]] = []
        if has_seg:
            try:
                seg_aux_mask, seg_aux_labels, seg_aux_per_object = expand_mask_by_segmentation(
                    drawn_mask, str(seg_path), str(seg_meta), img_size
                )
            except Exception as e:
                print(f"[adjuster] seg aux mask for SAM2 box failed: {e}")

        if len(seg_aux_per_object) > 1:
            # 使用者同時塗到多個不相鄰的物件（例如左邊櫃子 + 右邊檯燈）。
            # SAM 2 的一次 box prompt 只能回傳「單一物件」的實例遮罩，
            # 若把所有物件的範圍合併成一個大 box 丟給 SAM 2，只會選中其中
            # 一個最顯眼的物件、漏掉其他物件。因此改成對每個物件個別呼叫
            # SAM 2（box 範圍只框住該物件自己的塗鴉 + segmentation 範圍），
            # 再把每個物件的精確遮罩聯集起來。
            import numpy as np
            from PIL import Image

            combined_arr = None
            ok_count = 0
            for comp_drawn, class_full, label in seg_aux_per_object:
                obj_mask, obj_ok = generate_mask_with_sam2(
                    image_path, comp_drawn, img_size, aux_mask=class_full
                )
                if obj_ok:
                    ok_count += 1
                    arr = np.array(obj_mask.convert("L"))
                    combined_arr = arr if combined_arr is None else np.maximum(combined_arr, arr)
                else:
                    # 該物件 SAM 2 失敗 → 至少用 segmentation 的完整像素範圍頂替
                    arr = np.array(class_full.convert("L"))
                    combined_arr = arr if combined_arr is None else np.maximum(combined_arr, arr)

            mask = Image.fromarray(combined_arr, mode="L")
            mask_source = f"sam2_instance_multi(x{ok_count}/{len(seg_aux_per_object)})"
            seg_labels = seg_aux_labels
            print(f"[adjuster] mask source: SAM 2 instance segmentation, multi-object x{len(seg_aux_per_object)}")
        else:
            # 優先用 SAM 2 取得實例層級精確遮罩
            sam2_mask, sam2_ok = generate_mask_with_sam2(
                image_path, drawn_mask, img_size, aux_mask=seg_aux_mask
            )
            if sam2_ok:
                mask = sam2_mask
                mask_source = "sam2_instance"
                seg_labels = seg_aux_labels
                print("[adjuster] mask source: SAM 2 instance segmentation")
            elif has_seg and seg_aux_mask is not None:
                # SAM 2 失敗 → fallback：沿用剛才算好的 segmentation 展開遮罩
                mask, seg_labels = seg_aux_mask, seg_aux_labels
                mask_source = "manual_expanded_by_seg"
            else:
                mask = drawn_mask
                mask_source = "manual_drawing"
                seg_labels = []
    else:
        # Gemini Vision 判斷意圖：物件目標 + 動作類型
        text_prompt = user_input.get("text_prompt") or ""
        intent       = analyze_edit_intent(text_prompt, image_path, str(seg_meta) if seg_meta else None)
        edit_action  = intent["action"]
        seg_labels   = intent["seg_labels"]
        replace_with = intent["replace_with"]
        effective_labels = seg_labels or target_labels
        print(f"[adjuster] effective_labels: {effective_labels}")
        if has_seg:
            mask, seg_matched = mask_from_segmentation(str(seg_path), str(seg_meta), effective_labels, img_size)
            mask_source = f"segmentation({'+'.join(seg_matched[:3])})" if seg_matched else "fallback_center"
        else:
            mask = fallback_center_mask(img_size)
            mask_source = "fallback_center"

    # Prompt 組裝：使用者輸入 text_prompt 為主，風格資訊為輔
    user_text = (user_input.get("text_prompt") or "").strip()
    auto_prompt, negative_prompt = build_inpaint_prompt(req, style_params, target_objects)

    # 純移除動作詞集合
    _REMOVAL_ACTIONS = {"刪除", "移除", "去除", "清除", "刪掉", "拿掉"}

    # 動作詞對照表：中文 → 英文 inpainting 指令模板
    _ACTION_TEMPLATES = {
        "刪除":  "Remove the {obj} completely. {fill}",
        "移除":  "Remove the {obj} completely. {fill}",
        "去除":  "Remove the {obj} completely. {fill}",
        "清除":  "Remove the {obj} completely. {fill}",
        "刪掉":  "Remove the {obj} completely. {fill}",
        "拿掉":  "Remove the {obj} completely. {fill}",
        "換掉":  "Replace the {obj} with a suitable alternative that matches the room style",
        "換一個": "Replace the {obj} with a suitable alternative that matches the room style",
    }

    # 物件移除後的背景填補描述（依物件類型決定填什麼）
    _OBJ_FILL_CONTEXT: dict[str, str] = {
        "lamp":                "Fill with clean ceiling surface matching the surrounding texture and color",
        "light":               "Fill with clean ceiling surface matching the surrounding texture and color",
        "chandelier":          "Fill with clean ceiling surface matching the surrounding texture and color",
        "pendant":             "Fill with clean ceiling surface matching the surrounding texture and color",
        "sconce":              "Fill with clean wall surface matching the surrounding",
        "sofa":                "Fill with clean floor surface matching the surrounding floor material",
        "couch":               "Fill with clean floor surface matching the surrounding floor material",
        "chair":               "Fill with clean floor surface matching the surrounding floor material",
        "table":               "Fill with clean floor surface matching the surrounding floor material",
        "desk":                "Fill with clean floor surface matching the surrounding floor material",
        "coffee table":        "Fill with clean floor surface matching the surrounding floor material",
        "television receiver": "Fill with clean wall surface matching the surrounding wall color",
        "tv":                  "Fill with clean wall surface matching the surrounding wall color",
        "monitor":             "Fill with clean wall surface matching the surrounding wall color",
        "plant":               "Fill with clean floor area matching the surrounding",
        "potted plant":        "Fill with clean floor area matching the surrounding",
        "curtain":             "Fill with a clear window showing natural light",
        "rug":                 "Fill with clean floor surface matching the surrounding floor material",
        "carpet":              "Fill with clean floor surface matching the surrounding floor material",
        "shelf":               "Fill with clean wall surface matching the surrounding wall color",
        "bookcase":            "Fill with clean wall surface matching the surrounding wall color",
    }

    # 根據 seg_labels 取得最相關的填補描述
    def _get_fill_context(labels: list[str]) -> str:
        for lbl in labels:
            for key, ctx in _OBJ_FILL_CONTEXT.items():
                if key in lbl.lower() or lbl.lower() in key:
                    return ctx
        return "Fill with background that seamlessly blends with the surrounding environment"

    # 判斷是否為純移除任務
    # 無手繪遮罩：用 Vision 意圖分析結果；有手繪遮罩：fallback 到動作詞比對
    if edit_action is not None:
        is_removal = (edit_action == "remove")
    else:
        is_removal = any(a in user_text for a in _REMOVAL_ACTIONS)

    # 設定 fal.ai 推理參數
    # 移除任務：更多步數（細節更好）+ 較低 guidance（讓背景填補更自然）
    # 顏色/風格修改：標準步數 + 較高 guidance（prompt 跟隨更準）
    fal_num_steps     = 50  if is_removal else 28
    fal_guidance      = 3.0 if is_removal else 5.0

    if user_text:
        # 若 user_text 是純動作詞，補上 segmentation 偵測到的物件名稱 + 背景填補描述
        action_en = None
        for zh_action, template in _ACTION_TEMPLATES.items():
            if user_text.strip() == zh_action:
                obj_name = seg_labels[0] if seg_labels else "object"
                fill_ctx = _get_fill_context(seg_labels) if is_removal else ""
                action_en = template.format(obj=obj_name, fill=fill_ctx).strip()
                print(f"[adjuster] vague prompt '{user_text}' → auto-completed: {action_en}")
                break

        if action_en:
            en_text = action_en
        else:
            # 嘗試用 Gemini 翻譯成英文（FLUX 效果更好），失敗就直接用原文
            en_text = user_text
            try:
                from designbridge.render.llm import call_llm
                obj_hint = f" The selected object is: {seg_labels[0]}." if seg_labels else ""
                translated = call_llm(
                    f"Translate this interior design modification request to English in one sentence.{obj_hint} "
                    "Output ONLY the translated sentence itself — a single line, no markdown, no bullet points, "
                    "no quotes, no explanation of how you translated it, no meta-commentary.\n\n"
                    f"{user_text}",
                    max_tokens=500,
                    temperature=0.0,
                )
                t = translated.strip()
                # 有效翻譯的判斷：
                #  - 至少 2 個英文字，且不以虛詞結尾（避免截斷的不完整翻譯）
                #  - 單行（多行代表可能混入推理草稿而非乾淨的翻譯）
                #  - 不含中文字（代表翻譯沒做完，或把推理過程/原文片段混進來了）
                _incomplete_endings = {"a", "an", "the", "to", "of", "with", "and", "from", "in", "on", "at", "by", "for", "into", "onto"}
                last_word = t.rstrip(".").split()[-1].lower() if t else ""
                is_multiline = "\n" in t
                has_cjk = any("一" <= ch <= "鿿" for ch in t)
                if t and len(t.split()) >= 2 and last_word not in _incomplete_endings and not is_multiline and not has_cjk:
                    en_text = t
                    print(f"[adjuster] translated prompt: {en_text}")
                else:
                    reason = "contains Chinese" if has_cjk else "multiline" if is_multiline else "incomplete"
                    print(f"[adjuster] translation rejected ({reason}: '{t[:80]}'), using original: {user_text}")
            except Exception:
                pass

        prompt = (
            f"{en_text}. Photorealistic, high quality, seamless integration, "
            "lit consistently with the room's ambient lighting direction and color temperature, "
            "with edges that blend naturally into the surrounding scene. "
            "No text, no writing, no letters, no words, no typography, no signage or wall decals anywhere in the image."
        )
    else:
        prompt = (
            f"{auto_prompt} Lit consistently with the room's ambient lighting direction and color temperature, "
            "with edges that blend naturally into the surrounding scene. "
            "No text, no writing, no letters, no words, no typography, no signage or wall decals anywhere in the image."
        )

    # Debug：印出送出的 prompt 與 mask 狀況
    mask_white = sum(1 for p in mask.getdata() if p > 128) if hasattr(mask, 'getdata') else -1
    mask_total = mask.width * mask.height if hasattr(mask, 'width') else -1
    print(f"[adjuster] prompt: {prompt[:120]}")
    print(f"[adjuster] mask: {mask_white}/{mask_total} white px ({mask_white/mask_total:.1%} edit area)" if mask_total > 0 else "[adjuster] mask: unknown")
    print(f"[adjuster] mask_source: {mask_source}")

    # 無手繪遮罩時，以下兩種情況改用 Vision bbox 精準定位：
    #   1. mask 覆蓋率過低（< 2%），代表 segmentation 幾乎沒抓到東西
    #   2. mask_source 是 fallback_center，代表完全沒比對到目標物件標籤，
    #      此時 mask 雖然有 25% 面積（不會被上面 < 2% 擋到），但位置是
    #      固定置中矩形，對天花板燈具、窗邊家具等邊緣物件幾乎必定對不準
    mask_too_small = mask_total > 0 and mask_white / mask_total < 0.02
    mask_is_center_fallback = mask_source == "fallback_center"
    if edit_action is not None and (mask_too_small or mask_is_center_fallback):
        target_name = (effective_labels or seg_labels or ["object"])[0]
        reason = "too small" if mask_too_small else "center fallback (no label matched)"
        area_desc = f"{mask_white/mask_total:.1%}" if mask_total > 0 else "n/a"
        print(f"[adjuster] mask {reason} ({area_desc}), trying vision bbox for '{target_name}'")
        bbox_mask = _bbox_mask_from_vision(image_path, target_name, img_size)
        if bbox_mask is not None:
            mask = bbox_mask
            mask_source = f"vision_bbox({target_name})"
            mask_white = sum(1 for p in mask.getdata() if p > 128)
            print(f"[adjuster] bbox mask: {mask_white}/{mask_total} white px ({mask_white/mask_total:.1%})")

    # 無手繪遮罩時，若已定位到合理範圍（非置中 fallback，因為置中矩形
    # 位置本身就不可靠，拿去當 SAM 2 box prompt 沒有意義），用 SAM 2 精修一次，
    # 取得像素級精確輪廓（例如連椅子的輪子、桌腳一起框進去），
    # 避免純 segmentation/vision bbox 遮罩過於粗略導致邊緣殘留或誤刪背景
    if not has_manual_mask and mask_source != "fallback_center":
        sam2_refined, sam2_ok = generate_mask_with_sam2(image_path, mask, img_size)
        if sam2_ok:
            mask = sam2_refined
            mask_source = f"sam2_refined({mask_source})"
            mask_white = sum(1 for p in mask.getdata() if p > 128)
            print(f"[adjuster] SAM 2 refine: {mask_white}/{mask_total} white px ({mask_white/mask_total:.1%})" if mask_total > 0 else "[adjuster] SAM 2 refine done")

    # DRY_RUN 模式：只存遮罩，不呼叫任何 inpainting API（測試用）
    import os
    if os.getenv("ADJUSTER_DRY_RUN"):
        dry_out = Path(Config.ARTIFACTS_DIR) / "render" / f"{task_id}_dry_mask.png"
        dry_out.parent.mkdir(parents=True, exist_ok=True)
        mask.save(str(dry_out))
        print(f"[adjuster] DRY_RUN: 遮罩已存到 {dry_out}，跳過 inpainting")
        return {
            "generated_image": image_path,   # 回傳原圖，讓 renderer 跳過
            "intermediate_outputs": {
                **(state.get("intermediate_outputs") or {}),
                "adjuster_agent": {"status": "dry_run", "mask_path": str(dry_out), "mask_source": mask_source},
            }
        }

    strength = Config.ADJUSTER_INPAINT_STRENGTH

    render_suffix = uuid.uuid4().hex[:8]
    out_path = Path(Config.ARTIFACTS_DIR) / "render" / f"{task_id}_{render_suffix}.png"
    backend = "placeholder"

    # 1. LaMa（純移除任務：背景重建最穩定）
    if is_removal:
        if run_lama_inpainting(image_path, mask, out_path):
            backend = "lama_inpainting"

    # 2. fal.ai FLUX.1-Fill（修改任務，或 LaMa 失敗時的 fallback）
    if backend == "placeholder" and Config.FAL_KEY:
        print(f"[adjuster] task={'removal' if is_removal else 'modification'}  steps={fal_num_steps}  guidance={fal_guidance}")
        if run_fal_inpainting(image_path, mask, prompt, out_path,
                              num_steps=fal_num_steps, guidance_scale=fal_guidance):
            backend = "fal_inpainting"

    # 4. HF Inference API
    if backend == "placeholder" and Config.HF_TOKEN:
        if run_hf_inpainting(image_path, mask, prompt, out_path):
            backend = "hf_inpainting"

    # 5. 本地 SD Inpainting
    if backend == "placeholder":
        if run_inpainting(image_path, mask, prompt, negative_prompt, strength, out_path,
                          mask_path=manual_mask_path):
            backend = "sd_inpainting"

    # 6. Fallback：複製原圖
    if backend == "placeholder":
        out_path.parent.mkdir(parents=True, exist_ok=True)
        original_img.save(str(out_path))

    adjust_plan = {
        "inpaint_regions": [{
            "target_labels": target_labels,
            "target_objects": target_objects,
            "prompt": prompt,
            "strength": strength,
            "mask_source": mask_source,
        }],
        "consistency_guidance": (req.get("style_preferences") or {}).get("primary_style", ""),
    }

    return {
        "generated_image": str(out_path),
        "render_result": {
            "generated_image_path": str(out_path),
            "generation_params": {
                "backend": backend,
                "model": "stable-diffusion-2-inpainting",
                "strength": strength,
                "mask_source": mask_source,
                "prompt_preview": prompt,  # 完整 prompt（不截斷）：testing 用
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "intermediate_outputs": {
            **(state.get("intermediate_outputs") or {}),
            "adjuster_agent": adjust_plan,
        },
    }
