"""
instance_select.py
──────────────────
實例級的家具指認，供佈局重規劃使用。

問題：UPerNet 的 segmentation 是**語意**分割——房間裡兩張椅子共用同一個 `chair` label，
分不開。使用者說「把左邊那張椅子移到右邊」時，若整個 chair 類別一起清掉重畫，另一張
沒被要求動的椅子也會被合成長方體取代，違反「沒說要動的就鎖住原位」。

解法（三步）：
  1. 對指定類別的遮罩做連通區域分析 → 粗略的實例團塊
  2. 每個團塊的 bbox 餵給 SAM 2 → 精確的物件輪廓（SAM 2 不可用時退回連通區域本身）
  3. 用使用者的 qualifier（left / right / by the window …）指認要動的是哪一個

回傳「其餘實例」的聯集遮罩，交給 build_empty_room_disparity 原地保留。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

# 同類實例中，面積小於「最大者 × 此比例」的視為分割碎片而非獨立家具
FRAGMENT_AREA_RATIO = 0.25

# qualifier → 依畫面方位挑選實例時用的排序鍵（值越小越優先）
_LATERAL = {
    "left": lambda inst: inst["centroid_norm"][1],
    "leftmost": lambda inst: inst["centroid_norm"][1],
    "right": lambda inst: -inst["centroid_norm"][1],
    "rightmost": lambda inst: -inst["centroid_norm"][1],
    "center": lambda inst: abs(inst["centroid_norm"][1] - 0.5),
    "centre": lambda inst: abs(inst["centroid_norm"][1] - 0.5),
    "middle": lambda inst: abs(inst["centroid_norm"][1] - 0.5),
    "front": lambda inst: -inst["centroid_norm"][0],
    "foreground": lambda inst: -inst["centroid_norm"][0],
    "back": lambda inst: inst["centroid_norm"][0],
    "far": lambda inst: inst["centroid_norm"][0],
}

# qualifier 裡提到「靠近某個建築元素」時，該元素在 ADE20K 的 label 名稱
_NEAR_ANCHORS: dict[str, frozenset[str]] = {
    "window": frozenset({"windowpane", "window"}),
    "door": frozenset({"door", "double door"}),
    "wall": frozenset({"wall"}),
    "corner": frozenset({"wall"}),
    "bed": frozenset({"bed"}),
    "tv": frozenset({"television receiver", "tv", "monitor"}),
}


def class_instances(
    labels: np.ndarray,
    id_to_label: dict[int, str],
    wanted: frozenset[str],
    *,
    min_area_ratio: float = 0.002,
) -> list[dict[str, Any]]:
    """把命中 `wanted` 的像素切成實例（連通區域）。

    回傳每個實例的 {mask, bbox_xyxy, centroid_norm (row, col), area_ratio}，面積大的在前。
    """
    from designbridge.layout.photo_geometry import mask_for_labels

    cls_mask = mask_for_labels(labels, id_to_label, wanted)
    if not cls_mask.any():
        return []

    h, w = cls_mask.shape
    try:
        from scipy import ndimage as ndi

        struct = ndi.generate_binary_structure(2, 2)
        cleaned = ndi.binary_opening(cls_mask, structure=struct, iterations=2)
        if not cleaned.any():
            cleaned = cls_mask
        labeled, n = ndi.label(cleaned, structure=struct)
    except ImportError:
        # scipy 不可用 → 整個類別視為單一實例，實例級退化成語意級
        labeled, n = cls_mask.astype(np.int32), 1

    out: list[dict[str, Any]] = []
    for i in range(1, int(n) + 1):
        region = labeled == i
        area = int(region.sum())
        if area < h * w * min_area_ratio:
            continue
        ys, xs = np.nonzero(region)
        out.append({
            "mask": region,
            "bbox_xyxy": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            "centroid_norm": (float(ys.mean()) / h, float(xs.mean()) / w),
            "area_ratio": area / (h * w),
        })
    out.sort(key=lambda d: d["area_ratio"], reverse=True)
    return out


def refine_instances_with_sam2(
    instances: list[dict[str, Any]], image_path: str | Path | None
) -> list[dict[str, Any]]:
    """用 SAM 2 把每個實例的粗略團塊精修成物件輪廓。SAM 2 不可用時原樣回傳。"""
    if not instances or not image_path or not Path(str(image_path)).is_file():
        return instances
    try:
        from designbridge.render.inpaint import sam2_mask_from_box
    except Exception:
        return instances

    refined = 0
    for inst in instances:
        m = sam2_mask_from_box(str(image_path), inst["bbox_xyxy"])
        if m is None or m.shape != inst["mask"].shape or not m.any():
            continue
        # SAM 2 偶爾會把整面牆或整個地板一起選進來，明顯過大就不採用
        if m.mean() > 6.0 * inst["area_ratio"] and m.mean() > 0.25:
            continue
        inst["mask"] = m
        refined += 1
    if refined:
        print(f"[instance_select] SAM 2 精修 {refined}/{len(instances)} 個實例輪廓")
    return instances


def resolve_target_instance(
    instances: list[dict[str, Any]],
    qualifier: str,
    *,
    labels: np.ndarray | None = None,
    id_to_label: dict[int, str] | None = None,
) -> int:
    """依 qualifier 指認要操作的是哪一個實例，回傳索引。

    只有一個實例時 qualifier 無關緊要；認不出 qualifier 時退回面積最大的那個
    （通常就是使用者心裡想的主要家具）。
    """
    if not instances:
        return -1
    if len(instances) == 1:
        return 0

    q = (qualifier or "").strip().lower()
    if not q:
        return 0  # 已依面積排序

    for key, sort_key in _LATERAL.items():
        if key in q:
            return min(range(len(instances)), key=lambda i: sort_key(instances[i]))

    if labels is not None and id_to_label is not None:
        from designbridge.layout.photo_geometry import mask_for_labels

        for word, anchor_labels in _NEAR_ANCHORS.items():
            if word not in q:
                continue
            anchor = mask_for_labels(labels, id_to_label, anchor_labels)
            if not anchor.any():
                continue
            ays, axs = np.nonzero(anchor)
            ac = (float(ays.mean()), float(axs.mean()))
            h, w = labels.shape
            ac_norm = (ac[0] / h, ac[1] / w)
            return min(
                range(len(instances)),
                key=lambda i: (
                    (instances[i]["centroid_norm"][0] - ac_norm[0]) ** 2
                    + (instances[i]["centroid_norm"][1] - ac_norm[1]) ** 2
                ),
            )

    return 0


def build_preserve_mask(
    move_ops: list[dict[str, str]] | None,
    seg_path: str | Path,
    seg_meta_path: str | Path,
    *,
    image_path: str | Path | None = None,
    shape: tuple[int, int] | None = None,
) -> tuple[np.ndarray | None, list[str]]:
    """同類多件時，回傳「不該被動到的那幾件」的聯集遮罩。

    對每個 must_move 操作：把該類別切成實例，指認出使用者要移動的那一個，
    其餘實例併入保留遮罩。同類只有一件時不產生任何保留（那一件就是要移動的）。

    回傳 (preserve_mask 或 None, 診斷訊息)。
    """
    from designbridge.layout.photo_geometry import (
        FURNITURE_SEG_LABELS,
        _load_labels_matched,
    )
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    if not move_ops:
        return None, []

    if shape is None:
        from PIL import Image

        with Image.open(str(seg_path)) as im:
            shape = (im.size[1], im.size[0])
    labels, id_to_label = _load_labels_matched(seg_path, seg_meta_path, shape)

    preserve = np.zeros(shape, dtype=bool)
    notes: list[str] = []
    any_preserved = False

    for op in move_ops:
        if not isinstance(op, dict):
            continue
        target = normalize_furniture_type(str(op.get("target") or ""))
        wanted = FURNITURE_SEG_LABELS.get(target)
        if not wanted:
            notes.append(f"{target}: 無對應 segmentation label，略過實例分離")
            continue

        instances = class_instances(labels, id_to_label, wanted)
        if len(instances) <= 1:
            notes.append(f"{target}: 畫面上僅 {len(instances)} 件，不需實例分離")
            continue

        instances = refine_instances_with_sam2(instances, image_path)
        idx = resolve_target_instance(
            instances, str(op.get("qualifier") or ""),
            labels=labels, id_to_label=id_to_label,
        )

        # 分割雜訊會把同一件家具切出零星碎片（例如被前景物遮斷的床腳）。把它們當成
        # 獨立實例保留下來，成圖上就會浮著一小塊搬走前的舊深度。碎片寧可跟著目標一起
        # 重畫——多重畫一小塊幾乎看不出來，留下孤兒碎片卻很明顯。
        largest = max(inst["area_ratio"] for inst in instances)
        kept, fragments = 0, 0
        for i, inst in enumerate(instances):
            if i == idx:
                continue
            if inst["area_ratio"] < FRAGMENT_AREA_RATIO * largest:
                fragments += 1
                continue
            preserve |= inst["mask"]
            any_preserved = True
            kept += 1
        note = (
            f"{target}: {len(instances)} 件，qualifier='{op.get('qualifier') or ''}' "
            f"→ 移動第 {idx} 件，其餘 {kept} 件原地保留"
        )
        if fragments:
            note += f"（{fragments} 塊碎片視為同一物件，一併重畫）"
        notes.append(note)

    return (preserve if any_preserved else None), notes
