"""在渲染圖上移家具：把家具像素剪下貼到新位置，只對舊位置與新位置邊緣做 inpaint，其他像素原樣保留。

家具輪廓用渲染圖本身的語意分割（投影方塊只當範圍提示）：AI 畫出來的家具跟投影方塊
對不齊，直接用方塊剪會帶到旁邊的桌子、漏掉椅腳。

只支援合成相機的投影（純文字/平面圖流程）。照片流程的投影是照片本身的幾何，
另走一套，這裡先不處理。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from designbridge.core.config import Config
from designbridge.layout.layout_items import _DEPTH_SKIP_TYPES

_GEOM_KEYS = ("x", "y", "w", "h")
# 放在家具上、會被分成別的類別的軟件：跟著主體一起剪
_ATTACHED_LABELS = ("pillow", "cushion", "blanket", "quilt", "throw")
# 擺在家具上的小東西：SAM 只切家具本體，這些另外補回來一起搬
_ON_TOP_LABELS = (*_ATTACHED_LABELS, "cup", "vase", "pot", "plant", "flower", "book", "lamp", "tray", "bottle", "bowl", "basket", "box")
# 語意分割裡不算家具的類別：選家具輪廓時跳過
_BACKGROUND_LABELS = frozenset({
    "wall", "floor", "ceiling", "windowpane", "curtain", "door", "sky", "building", "tree", "grass",
    "railing", "step", "stairs", "light", "column", "rug", "earth", "road", "fence", "screen door",
})


class MoveFurnitureError(ValueError):
    """請求本身做不到（不是伺服器錯誤），router 回 400。"""


def _anchor(placements: list[dict]) -> list[dict]:
    # 跟 projected_depth._generate_projected_depth 同一套篩選，id 才對得上深度圖
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type
    return [p for p in placements if normalize_furniture_type(str(p.get("type", ""))) not in _DEPTH_SKIP_TYPES] or placements


def _room_dims(space_info: dict) -> tuple[float, float, float]:
    from designbridge.layout.scene_graph_to_depth import _room_dims as dims
    return dims(space_info)


def _instance_masks(
    placements: list[dict], space_info: dict, camera: dict, size: tuple[int, int],
) -> dict[str, np.ndarray]:
    """用指定相機光柵化，回傳家具 id → 投影方塊在畫面上看得到的像素（已扣掉被擋住的部分）。"""
    from designbridge.layout.camera_projection import CameraParams, LookAtCamera, build_tagged_scene, rasterize_ids

    room_w, room_d, room_h = _room_dims(space_info)
    index: dict[int, int] = {}
    tagged, _ = build_tagged_scene(
        placements, room_w, room_d, room_h, semantic_shapes=Config.ENABLE_SEMANTIC_SHAPES, index_out=index,
    )
    cam = LookAtCamera(room_w, room_d, size[0], size[1], CameraParams(**camera))
    _, idbuf = rasterize_ids(tagged, cam)
    return {str(placements[i].get("id")): idbuf == oid for oid, i in index.items()}


def _changed_ids(
    old: list[dict], new: list[dict], room_w: float, room_d: float,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """回傳 (位置/尺寸變了的, 朝向變了的, 刪掉的, 新增的)。

    朝向用推算後的比：沙發移到另一側會自動改面向電視，貼過去的像素方向就不對了。
    """
    from designbridge.layout.facing import infer_fronts

    old_front = dict(zip((str(p.get("id")) for p in old), infer_fronts(old, room_w, room_d)))
    new_front = dict(zip((str(p.get("id")) for p in new), infer_fronts(new, room_w, room_d)))
    by_id = {str(p.get("id")): p for p in new}
    moved, turned, removed = [], [], []
    for p in old:
        pid = str(p.get("id"))
        q = by_id.get(pid)
        if q is None:
            removed.append(pid)
            continue
        is_moved = any(abs(float(p.get(k, 0)) - float(q.get(k, 0))) > 1e-4 for k in _GEOM_KEYS)
        if is_moved:
            moved.append(pid)
        # 沒動也沒被使用者轉的家具，推算朝向因為別件移動而變了也不算，圖上的它維持原樣
        user_turned = (p.get("front") or "") != (q.get("front") or "") and q.get("front")
        if old_front[pid] != new_front[pid] and (is_moved or user_turned):
            turned.append(pid)
    added = [pid for pid in by_id if pid not in old_front]
    return moved, turned, removed, added


def _dilate(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0 or not mask.any():
        return mask
    img = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(px * 2 + 1))
    return np.asarray(img) > 0


def _erode(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0 or not mask.any():
        return mask
    img = Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(px * 2 + 1))
    return np.asarray(img) > 0


def fill_holes(rgb: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """push-pull 補洞：往下取樣到洞被周圍顏色填滿，再逐層往上放大填回。只是預覽與 inpaint 的起點，不求細節。"""
    if not hole.any():
        return rgb.copy()
    img = rgb.astype(np.float32) * (~hole)[..., None]
    wgt = (~hole).astype(np.float32)
    pyramid = []
    while True:
        pyramid.append((img, wgt))
        h, w = wgt.shape
        if wgt.min() > 0 or min(h, w) <= 2:
            break
        ph, pw = h + h % 2, w + w % 2
        img = np.pad(img, ((0, ph - h), (0, pw - w), (0, 0)))
        wgt = np.pad(wgt, ((0, ph - h), (0, pw - w)))
        img = img.reshape(ph // 2, 2, pw // 2, 2, 3).sum(axis=(1, 3))
        wgt = wgt.reshape(ph // 2, 2, pw // 2, 2).sum(axis=(1, 3))

    img, wgt = pyramid[-1]
    val = img / np.maximum(wgt, 1e-6)[..., None]
    for img, wgt in reversed(pyramid[:-1]):
        h, w = wgt.shape
        up = np.repeat(np.repeat(val, 2, axis=0), 2, axis=1)[:h, :w]
        known = wgt > 1e-6
        val = np.where(known[..., None], img / np.maximum(wgt, 1e-6)[..., None], up)

    blurred = np.asarray(Image.fromarray(np.clip(val, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)))
    out = rgb.copy()
    out[hole] = blurred[hole]
    return out


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def refine_mask(box: np.ndarray, seg: np.ndarray | None, labels: dict[int, str]) -> np.ndarray:
    """投影方塊 → 渲染圖上這件家具的實際輪廓。

    在放大過的方塊範圍內，挑跟方塊重疊最多的非背景類別，只留碰得到方塊的連通塊；
    分割不可用或結果離方塊太遠（面積差太多）就退回方塊本身。
    """
    if seg is None or not box.any():
        return box
    from scipy import ndimage

    x0, y0, x1, y1 = _bbox(box)
    pad = max(8, round(0.2 * max(x1 - x0, y1 - y0)))
    region = _dilate(box, pad)
    core = _dilate(box, pad // 3)
    ids, counts = np.unique(seg[core], return_counts=True)
    best = [(c, i) for i, c in zip(ids.tolist(), counts.tolist()) if labels.get(i, "") not in _BACKGROUND_LABELS]
    if not best:
        return box
    cls = max(best)[1]
    cand = (seg == cls) & region
    comp, n = ndimage.label(cand)
    keep = np.isin(comp, [k for k in range(1, n + 1) if (comp[core] == k).any()])
    area, box_area = int(keep.sum()), int(box.sum())
    if area < 0.25 * box_area or area > 4 * box_area:
        return box
    # 床上的枕頭棉被、沙發上的抱枕被分成別的類別：碰得到主體的一起剪，不然會從家具內部挖出洞
    touch = _dilate(keep, 3)
    for i in ids.tolist():
        if i == cls or not any(k in labels.get(i, "") for k in _ATTACHED_LABELS):
            continue
        comp, n = ndimage.label((seg == i) & region)
        keep |= np.isin(comp, [k for k in range(1, n + 1) if (touch & (comp == k)).any()])
    return _dilate(keep, 2)


def segment_image(image_path: str, size: tuple[int, int]) -> tuple[np.ndarray | None, dict[int, str]]:
    """圖的語意分割，依圖檔快取：同一張圖點第二件家具、按套用都不用再跑一次。失敗回 (None, {})。"""
    out_dir = Path(Config.ARTIFACTS_DIR) / "vision" / "move_seg" / Path(image_path).stem
    seg_path, meta_path = out_dir / "segmentation.png", out_dir / "segmentation_meta.json"
    try:
        if not (seg_path.is_file() and meta_path.is_file()):
            from designbridge.layout.vision import run_segmentation
            run_segmentation(str(image_path), model_name=Config.SEGMENTATION_MODEL, out_dir=out_dir)
        seg = Image.open(seg_path)
        if seg.size != size:
            seg = seg.resize(size, Image.NEAREST)
        labels = json.loads(meta_path.read_text(encoding="utf-8")).get("present_labels") or {}
        return np.asarray(seg).astype(np.int32), {int(k): v for k, v in labels.items()}
    except Exception as e:
        print(f"[move_furniture] 語意分割失敗，退回投影方塊：{e}")
        return None, {}


_precise_cache: dict[tuple, np.ndarray] = {}
_lama_model = None


def lama_fill(image: np.ndarray, hole: np.ndarray) -> np.ndarray | None:
    """LaMa 純背景重建：只會把洞補成周圍的地板／牆，不會像 FLUX 那樣在洞裡畫出新家具。沒裝就回 None。"""
    global _lama_model
    try:
        if _lama_model is None:
            from simple_lama_inpainting import SimpleLama
            _lama_model = SimpleLama()
        out = _lama_model(Image.fromarray(image), Image.fromarray(hole.astype(np.uint8) * 255))
        return np.asarray(out.convert("RGB").resize(image.shape[1::-1], Image.LANCZOS))
    except Exception as e:
        print(f"[move_furniture] LaMa 補洞失敗，改用 FLUX：{e}")
        return None


def precise_mask(image_path: str, coarse: np.ndarray, seg: np.ndarray | None, labels: dict[int, str]) -> np.ndarray:
    """語意輪廓 → SAM 2 實例輪廓。SAM 不可用或切到別的東西（跟語意輪廓幾乎不重疊）就沿用語意輪廓。

    SAM 只切主體，放在上面的杯子、花瓶、檯燈另外從語意分割補回來，不然搬走後它們會浮在原地。
    同一張圖、同一個範圍會先後被點選與套用各算一次，記在記憶體裡。
    """
    if not coarse.any():
        return coarse
    box = _bbox(coarse)
    key = (image_path, box, int(coarse.sum()))
    if key in _precise_cache:
        return _precise_cache[key]
    from designbridge.render.inpaint import sam2_mask_from_box

    m = sam2_mask_from_box(image_path, box)
    if m is None or not m.any():
        return coarse
    if m.shape != coarse.shape:
        m = np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize(coarse.shape[::-1], Image.NEAREST)) > 0
    if (m & coarse).sum() < 0.3 * m.sum() or m.sum() < 0.15 * coarse.sum():
        return coarse
    if seg is not None:
        from scipy import ndimage
        touch, region = _dilate(m, 4), _dilate(coarse, 6)
        for i in np.unique(seg[region]).tolist():
            if not any(k in labels.get(i, "") for k in _ON_TOP_LABELS):
                continue
            comp, n = ndimage.label((seg == i) & region)
            m |= np.isin(comp, [k for k in range(1, n + 1) if (touch & (comp == k)).any()])
    out = _dilate(m, 1)
    _precise_cache[key] = out
    return out


def build_move_composite(
    image: np.ndarray,
    masks: dict[str, np.ndarray],
    moves: dict[str, tuple[float, float, float, float, float]],
    removed: list[str],
    redraw: np.ndarray,
    occluders: dict[str, np.ndarray],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """回傳 (合成圖, 補洞遮罩, 貼上家具的遮罩)。

    moves：家具 id → (舊錨點 u, v, 新錨點 u, v, 縮放)，錨點是家具底下地板中心的像素位置，
    縮放跟前端拖曳預覽同一套（離地平線的距離比），貼的位置才跟使用者放下的一樣。
    occluders：貼到新位置時要留在前面、不能被蓋掉的像素（站在它前面的家具）。
    redraw：轉向／新增的家具在新位置的範圍，沒有能貼的像素，整塊交給 inpaint 畫。
    補洞遮罩 = 舊位置（扣掉旁邊沒動的家具與貼上的家具）+ redraw，要高強度重畫；
    貼上的家具另外給，只做低強度修細節，形狀才不會被重畫掉。
    """
    h, w = image.shape[:2]
    empty = np.zeros((h, w), dtype=bool)
    gone = [pid for pid in (*moves, *removed) if pid in masks]
    others = empty.copy()
    for pid, m in masks.items():
        if pid not in gone:
            others |= m
    hole = empty.copy()
    for pid in gone:
        hole |= masks[pid] | (_dilate(masks[pid], 6) & ~others)
    out = fill_holes(image, hole | redraw)

    pasted = empty.copy()
    for pid, (au, av, bu, bv, s) in moves.items():
        src = masks.get(pid)
        if src is None or not src.any():
            continue
        sx0, sy0, sx1, sy1 = _bbox(src)
        cw, ch = max(1, round((sx1 - sx0) * s)), max(1, round((sy1 - sy0) * s))
        left, top = round(bu + (sx0 - au) * s), round(bv + (sy0 - av) * s)
        x0, y0, x1, y1 = max(left, 0), max(top, 0), min(left + cw, w), min(top + ch, h)
        if x1 <= x0 or y1 <= y0:
            continue
        piece = Image.fromarray(image[sy0:sy1, sx0:sx1]).resize((cw, ch), Image.LANCZOS)
        if s > 1.05:   # 放大會變軟，放越大銳化越多
            piece = piece.filter(ImageFilter.UnsharpMask(radius=2, percent=int(min(160, 60 + 100 * (s - 1))), threshold=2))
        crop = np.asarray(piece)
        # 輪廓邊緣用半透明過渡（抗鋸齒），硬切的邊貼上去一眼就看得出是貼的
        soft = Image.fromarray(src[sy0:sy1, sx0:sx1].astype(np.uint8) * 255).resize((cw, ch), Image.LANCZOS)
        cmask = np.asarray(soft.filter(ImageFilter.GaussianBlur(0.8))).astype(np.float32) / 255.0
        layer, alpha = np.zeros_like(image), np.zeros((h, w), dtype=np.float32)
        layer[y0:y1, x0:x1] = crop[y0 - top:y1 - top, x0 - left:x1 - left]
        alpha[y0:y1, x0:x1] = cmask[y0 - top:y1 - top, x0 - left:x1 - left]
        alpha[occluders.get(pid, empty)] = 0.0
        a = alpha[..., None]
        out = (layer.astype(np.float32) * a + out.astype(np.float32) * (1 - a)).round().astype(np.uint8)
        pasted |= alpha > 0.5

    return out, (hole & ~pasted) | redraw, pasted


def blend_in(base: np.ndarray, repainted: np.ndarray, mask: np.ndarray, protect: np.ndarray | None = None,
             feather: int = 4) -> np.ndarray:
    """把 inpaint 結果只貼回 mask 範圍，邊界往外柔化 feather px。

    只往外不往內：遮罩內全用新圖，遮罩外漸淡；protect（貼上的家具）一律保留 base，
    不然清楚的家具邊會跟 AI 畫的軟邊疊成雙重邊。
    """
    soft = np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.GaussianBlur(feather))) / 255.0
    # 邊界上 blur 約 0.5，乘 2 讓遮罩外緣從 1 漸淡到 0
    alpha = np.where(mask, 1.0, np.clip(soft * 2, 0, 1))
    if protect is not None:
        alpha[protect & ~mask] = 0.0
    a = alpha[..., None]
    return (repainted.astype(np.float32) * a + base.astype(np.float32) * (1 - a)).round().astype(np.uint8)


def _camera_of(scene_graph: dict, generation_params: dict) -> dict | None:
    from designbridge.core.nodes.renderer import _projection_meta
    depth = scene_graph.get("projected_depth_path")
    cam = _projection_meta(str(depth)).get("camera") if depth else None
    return cam or generation_params.get("layout_camera")


class _Context:
    """移家具三個步驟（點選、拖曳換算、重繪）共用的上一張圖資訊。"""

    def __init__(self, plan: dict[str, Any]) -> None:
        self.scene_graph = plan.get("scene_graph") or {}
        self.render_result = plan.get("render_result") or {}
        self.gen = self.render_result.get("generation_params") or {}
        self.image_path = plan.get("generated_image_path") or self.render_result.get("generated_image_path")
        if not self.image_path or not Path(self.image_path).is_file():
            raise MoveFurnitureError("找不到上一張渲染圖")
        if self.scene_graph.get("projection_mode") not in (None, "synthetic"):
            raise MoveFurnitureError("照片流程的渲染圖目前還不能直接移家具")
        self.old = self.scene_graph.get("furniture_placements") or []
        self.space_info = (plan.get("structured_requirement") or {}).get("space_info") or {}
        self.room_w, self.room_d, _ = _room_dims(self.space_info)
        self.camera = _camera_of(self.scene_graph, self.gen)
        self.bounded = bool(self.camera)   # 有排版相機，房間大小才是真的
        if not self.camera:
            # 沒排家具就生的圖沒有投影相機：假設正面平視（預設相機是斜角站在牆角，左半邊會被
            # 換算到很遠的地方），縮放與碰撞是近似但前後一致
            from dataclasses import asdict, replace

            from designbridge.layout.camera_projection import base_camera_from_config
            base = base_camera_from_config(self.room_w, self.room_d)
            self.camera = asdict(replace(base, eye_x_frac=0.5, target_x_frac=0.5))

        size_cfg = self.gen.get("output_size") or {}
        prev = Image.open(self.image_path).convert("RGB")
        self.size = (int(size_cfg.get("width") or prev.width), int(size_cfg.get("height") or prev.height))
        self.image = prev.resize(self.size, Image.LANCZOS) if prev.size != self.size else prev

    def lookat(self):
        from designbridge.layout.camera_projection import CameraParams, LookAtCamera
        return LookAtCamera(self.room_w, self.room_d, self.size[0], self.size[1], CameraParams(**self.camera))

    def segmentation(self) -> tuple[np.ndarray | None, dict[int, str]]:
        return segment_image(str(self.image_path), self.size)

    def object_masks(self, precise: tuple[str, ...] = ()) -> dict[str, np.ndarray]:
        """家具 id → 圖上輪廓。全部先用語意分割（快、夠用來保護旁邊的家具）；
        precise 裡的（要剪下來搬的）再用 SAM 2 精修，細腳、鏤空不會帶到地板。"""
        boxes = _instance_masks(_anchor(self.old), self.space_info, self.camera, self.size)
        seg, labels = self.segmentation()
        masks = {pid: refine_mask(m, seg, labels) for pid, m in boxes.items()}
        for pid in precise:
            if pid in masks:
                masks[pid] = precise_mask(str(self.image_path), masks[pid], seg, labels)
        return masks

    def floor_anchor(self, cam, item: dict) -> tuple[float, float, float]:
        """家具底下地板中心在畫面上的像素位置，與它離相機的深度。"""
        x = (float(item["x"]) + float(item["w"]) / 2) * self.room_w
        z = (1.0 - (float(item["y"]) + float(item["h"]) / 2)) * self.room_d
        c = cam.to_cam(np.array([[x, 0.0, z]]))[0]
        return cam.cx + cam.f * c[0] / c[2], cam.cy - cam.f * c[1] / c[2], float(c[2])


def _pixel_to_floor(cam, u: float, v: float) -> tuple[float, float]:
    """畫面上一點往地板打射線；點在地平線以上（打不到地板）就壓到地平線下一點點。"""
    v = max(v, _horizon_v(cam) + 2.0)
    ray = cam.R.T @ np.array([(u - cam.cx) / cam.f, -(v - cam.cy) / cam.f, 1.0])
    t = -cam.eye[1] / ray[1]
    p = cam.eye + t * ray
    return float(p[0]), float(p[2])


def _horizon_v(cam) -> float:
    # 相機沒有側滾，地板上的東西在畫面上的大小跟「離地平線多遠」成正比，前端拖曳預覽靠這個縮放
    fwd = cam.R[2]
    flat = np.array([fwd[0], 0.0, fwd[2]])
    c = cam.R @ (flat / (np.linalg.norm(flat) + 1e-9))
    return float(cam.cy - cam.f * c[1] / c[2])


def _is_floor_item(p: dict) -> bool:
    # 地毯類本來就鋪在家具底下，跟 2D 編輯器一樣不算碰撞
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type
    return normalize_furniture_type(str(p.get("type", ""))) in _DEPTH_SKIP_TYPES


def _overlaps(a: dict, b: dict, eps: float = 1e-3) -> bool:
    return (a["x"] < b["x"] + b["w"] - eps and a["x"] + a["w"] > b["x"] + eps
            and a["y"] < b["y"] + b["h"] - eps and a["y"] + a["h"] > b["y"] + eps)


def _floor_to_pixel(cam, x: float, z: float) -> tuple[float, float]:
    c = cam.to_cam(np.array([[x, 0.0, z]]))[0]
    return cam.cx + cam.f * c[0] / c[2], cam.cy - cam.f * c[1] / c[2]


def _clamp_fp(fp: dict, bounded: bool = True) -> dict:
    """夾在房間內；沒有排版相機（房間大小也是猜的）時不夾，不然家具全被擠到猜出來的牆邊。"""
    if not bounded:
        return dict(fp)
    w, h = min(fp["w"], 1.0), min(fp["h"], 1.0)
    return {"x": min(max(fp["x"], 0.0), 1.0 - w), "y": min(max(fp["y"], 0.0), 1.0 - h), "w": w, "h": h}


def _instance_layout(ctx: "_Context", insts: list[dict], cam) -> dict[int, dict]:
    """每件切出來的家具在平面圖上的位置（擋碰撞用），能對到 scene_graph 的家具就記下 id。

    碰地點是輪廓最下緣、也就是家具最靠鏡頭的那條邊。對得到排版家具就用它的寬深，
    對不到（AI 自己多畫的）就用碰地那段的寬度估。
    """
    cands = [p for p in ctx.old if not _is_floor_item(p)]
    info, dist = {}, []
    for inst in insts:
        if not inst["movable"]:
            continue
        x0, _, x1, _ = inst["bbox"]
        cu, cv = inst["contact"]
        X, Z = _pixel_to_floor(cam, cu, cv)
        # 用整件的寬度換算，不能只看最下緣：沙發、桌子最下面只有細細的腳
        span = abs(_pixel_to_floor(cam, float(x1), cv)[0] - _pixel_to_floor(cam, float(x0), cv)[0])
        info[inst["index"]] = {"front": (X / ctx.room_w, 1.0 - Z / ctx.room_d), "span": max(span, 0.3)}
        for p in cands:
            fx = (float(p["x"]) + float(p["w"]) / 2) * ctx.room_w
            fz = (1.0 - float(p["y"]) - float(p["h"])) * ctx.room_d
            dist.append((float(np.hypot(fx - X, fz - Z)), inst["index"], str(p["id"])))
    # 近的先配，一件排版家具只配一次；離超過 1 公尺就當作對不到
    used, match = set(), {}
    for d, idx, pid in sorted(dist):
        if d <= 1.0 and idx not in match and pid not in used:
            match[idx] = pid
            used.add(pid)
    by_id = {str(p["id"]): p for p in ctx.old}
    for idx, it in info.items():
        fx, fy = it["front"]
        p = by_id.get(match.get(idx, ""))
        fw = float(p["w"]) if p else it["span"] / ctx.room_w
        fh = float(p["h"]) if p else 0.8 * it["span"] / ctx.room_d
        it["footprint"] = _clamp_fp({"x": fx - fw / 2, "y": fy - fh, "w": fw, "h": fh}, ctx.bounded)
        it["placement_id"] = match.get(idx)
    return info


def _blockers(index: int, layout: dict[int, dict]) -> list[int]:
    """拖這件時不能碰到的其他家具；原本就跟它重疊的不算（AI 畫的餐椅常塞在餐桌底下一點）。"""
    me = layout[index]["footprint"]
    return [k for k, o in layout.items() if k != index and not _overlaps(me, o["footprint"])]


def list_instances(plan: dict[str, Any]) -> dict[str, Any]:
    """渲染圖上自動切出的每件家具：前端一進移動模式就全部框出來，點選、多選、拖曳都不用再問後端。

    每件給：去背圖層、蓋住原位置的粗補貼片（預覽用）、碰地點、平面圖上的位置與碰撞對象。
    圖層存成檔案（同一張圖第二次直接用），回傳的是路徑，router 轉成網址。
    """
    from designbridge.render.furniture_instances import segment_furniture

    ctx = _Context(plan)
    w, h = ctx.size
    insts = segment_furniture(str(ctx.image_path), ctx.size)
    cam = ctx.lookat()
    layout = _instance_layout(ctx, insts, cam)
    out_dir = Path(Config.ARTIFACTS_DIR) / "vision" / "move_seg" / Path(ctx.image_path).stem
    out_dir.mkdir(parents=True, exist_ok=True)
    image = np.asarray(ctx.image)
    items = []
    for inst in insts:
        if not inst["movable"]:
            continue
        k, m = inst["index"], inst["mask"]
        layer_path, patch_path = out_dir / f"layer_{k}.png", out_dir / f"patch_{k}.png"
        x0, y0, x1, y1 = inst["bbox"]
        pm = _dilate(m, 4)
        px0, py0, px1, py1 = _bbox(pm)
        if not (layer_path.is_file() and patch_path.is_file()):
            Image.fromarray(np.dstack([image, m.astype(np.uint8) * 255])[y0:y1, x0:x1]).save(layer_path)
            patch = np.dstack([fill_holes(image, pm), pm.astype(np.uint8) * 255])[py0:py1, px0:px1]
            Image.fromarray(patch).save(patch_path)
        items.append({
            "index": k, "label": inst["label"],
            "bbox": {"x0": x0 / w, "y0": y0 / h, "x1": x1 / w, "y1": y1 / h},
            "anchor": {"x": inst["contact"][0] / w, "y": inst["contact"][1] / h},
            "layer_path": str(layer_path), "patch_path": str(patch_path),
            "patch_bbox": {"x0": px0 / w, "y0": py0 / h, "x1": px1 / w, "y1": py1 / h},
            "footprint": layout[k]["footprint"], "blockers": _blockers(k, layout),
            "placement_id": layout[k]["placement_id"],
        })
    return {
        "instances": items,
        "horizon_y": _horizon_v(cam) / h,
        # 前端拖曳時自己換算地板位置、擋碰撞與出界
        "camera": {"R": cam.R.tolist(), "eye": cam.eye.tolist(), "f": cam.f, "cx": cam.cx, "cy": cam.cy,
                   "width": w, "height": h},
        "room": {"w": ctx.room_w, "d": ctx.room_d},
        "bounded": ctx.bounded,   # false：房間大小是猜的，前端拖曳也不要夾在房間內
    }


def move_instances(plan: dict[str, Any], moves: list[dict], strength: float | None = None) -> dict[str, Any]:
    """moves = [{index, x, y}]：第 index 件家具的碰地點拖到畫面 (x, y)（0–1）。可以一次搬好幾件。

    用的是 list_instances 同一份切分輪廓，貼的位置、縮放跟前端預覽同一套算法；
    對得到排版家具的，scene_graph 跟著平移，2D 佈局與之後換風格才對得上。
    """
    from designbridge.layout.facing import infer_fronts
    from designbridge.render.furniture_instances import segment_furniture

    ctx = _Context(plan)
    w, h = ctx.size
    insts = {i["index"]: i for i in segment_furniture(str(ctx.image_path), ctx.size)}
    cam = ctx.lookat()
    horizon = _horizon_v(cam)
    layout = _instance_layout(ctx, list(insts.values()), cam)

    plans, new_fp = {}, {}
    for mv in moves:
        k = int(mv["index"])
        if k not in layout:
            raise MoveFurnitureError("這件家具不能移動")
        au, av = insts[k]["contact"]
        X0, Z0 = _pixel_to_floor(cam, au, av)
        X1, Z1 = _pixel_to_floor(cam, float(mv["x"]) * w, float(mv["y"]) * h)
        fp = layout[k]["footprint"]
        moved_fp = _clamp_fp({**fp, "x": fp["x"] + (X1 - X0) / ctx.room_w, "y": fp["y"] - (Z1 - Z0) / ctx.room_d}, ctx.bounded)
        # 夾回房間內之後，碰地點從夾過的位置重算，貼的位置才不會跑到牆外
        dx, dz = (moved_fp["x"] - fp["x"]) * ctx.room_w, -(moved_fp["y"] - fp["y"]) * ctx.room_d
        bu, bv = _floor_to_pixel(cam, X0 + dx, Z0 + dz)
        if abs(bu - au) + abs(bv - av) < 1:
            continue
        plans[k] = (au, av, bu, bv, max(0.2, min(4.0, (bv - horizon) / max(av - horizon, 1e-3))), dx, dz)
        new_fp[k] = moved_fp
    if not plans:
        raise MoveFurnitureError("家具位置沒有變動")

    final_fp = {k: new_fp.get(k, it["footprint"]) for k, it in layout.items()}
    for k in plans:
        if any(_overlaps(final_fp[k], final_fp[o]) for o in _blockers(k, layout)):
            raise MoveFurnitureError("這個位置會跟其他家具重疊，請放到空的地方")

    masks = {str(k): i["mask"] for k, i in insts.items()}
    moves_px, occluders = {}, {}
    for k, (au, av, bu, bv, s, _, _) in sorted(plans.items(), key=lambda kv: kv[1][3]):   # 遠的先貼
        moves_px[str(k)] = (au, av, bu, bv, s)
        # 沒動、而且碰地點比新位置更靠鏡頭的家具留在上層
        occ = np.zeros((h, w), dtype=bool)
        for o, inst in insts.items():
            if o not in plans and inst["contact"][1] > bv:
                occ |= inst["mask"]
        occluders[str(k)] = occ
    empty = np.zeros((h, w), dtype=bool)
    composite, fill_mask, pasted = build_move_composite(np.asarray(ctx.image), masks, moves_px, [], empty, occluders)

    # scene_graph：對得到的排版家具跟著平移，朝向全部釘住（不然別件家具的推算朝向會跟著變）
    shift = {layout[k]["placement_id"]: (dx, dz) for k, (*_, dx, dz) in plans.items() if layout[k]["placement_id"]}
    new = []
    for p, front in zip(ctx.old, infer_fronts(ctx.old, ctx.room_w, ctx.room_d)):
        p = {**p, "front": front}
        if str(p.get("id")) in shift:
            dx, dz = shift[str(p["id"])]
            p.update(_clamp_fp({"x": float(p["x"]) + dx / ctx.room_w, "y": float(p["y"]) - dz / ctx.room_d,
                                "w": float(p["w"]), "h": float(p["h"])}))
        new.append(p)
    changed = {"moved": sorted(shift), "instances": sorted(plans), "turned": [], "removed": [], "added": []}
    return _finish_move(ctx, plan, new, composite, fill_mask, pasted, empty, strength, changed)


def move_furniture(plan: dict[str, Any], new_placements: list[dict], strength: float | None = None) -> dict[str, Any]:
    """plan = 上一輪 /api/generate 的完整回應；new_placements = 改完的家具清單。回傳更新後的 plan 欄位。"""
    from designbridge.layout.layout_enforce import _clip_to_room
    from designbridge.layout.layout_items import FurnitureItem

    ctx = _Context(plan)
    camera, space_info, old = ctx.camera, ctx.space_info, ctx.old
    items = _clip_to_room([FurnitureItem(
        id=str(p.get("id", "")), type=str(p.get("type", "default")),
        x=float(p.get("x", 0)), y=float(p.get("y", 0)), w=float(p.get("w", 0.1)), h=float(p.get("h", 0.1)),
        rotation=float(p.get("rotation", 0.0)), product_id=str(p.get("product_id") or ""),
    ) for p in new_placements])
    front_of = {str(p.get("id")): p.get("front") for p in new_placements}
    new = []
    for it in items:
        d = it.to_dict()
        if front_of.get(it.id):
            d["front"] = front_of[it.id]
        new.append(d)

    moved, turned, removed, added = _changed_ids(old, new, ctx.room_w, ctx.room_d)
    if not (moved or turned or removed or added):
        raise MoveFurnitureError("家具位置沒有變動")

    output_size = ctx.size
    cam = ctx.lookat()
    horizon = _horizon_v(cam)
    masks = ctx.object_masks(precise=tuple(p for p in moved if p not in turned))
    old_by_id = {str(p.get("id")): p for p in old}
    new_by_id = {str(p.get("id")): p for p in new}
    unchanged = [pid for pid in masks if pid in new_by_id and pid not in {*moved, *turned}]

    moves, occluders = {}, {}
    for pid in moved:
        if pid in turned:
            continue
        au, av, _ = ctx.floor_anchor(cam, old_by_id[pid])
        bu, bv, bz = ctx.floor_anchor(cam, new_by_id[pid])
        moves[pid] = (au, av, bu, bv, max(0.2, min(4.0, (bv - horizon) / max(av - horizon, 1e-3))))
        # 站在新位置前面（離相機更近）的家具留在上層
        occ = np.zeros(output_size[::-1], dtype=bool)
        for oid in unchanged:
            if ctx.floor_anchor(cam, new_by_id[oid])[2] < bz - 0.15:
                occ |= masks[oid]
        occluders[pid] = occ
    new_boxes = _instance_masks(_anchor(new), space_info, camera, output_size)
    redraw = np.zeros(output_size[::-1], dtype=bool)
    for pid in (*turned, *added):
        if pid in new_boxes:
            redraw |= _dilate(new_boxes[pid], 6)
    # 轉向的家具舊位置也要清掉
    composite, fill_mask, pasted = build_move_composite(
        np.asarray(ctx.image), masks, moves, [*removed, *[p for p in turned if p in masks]], redraw, occluders,
    )

    changed = {"moved": moved, "turned": turned, "removed": removed, "added": added}
    return _finish_move(ctx, plan, new, composite, fill_mask, pasted, redraw, strength, changed)


def _finish_move(ctx: "_Context", plan: dict[str, Any], new: list[dict], composite: np.ndarray,
                 fill_mask: np.ndarray, pasted: np.ndarray, redraw: np.ndarray, strength: float | None,
                 changed: dict) -> dict[str, Any]:
    """合成圖之後的共用流程：新深度圖 → LaMa 補洞 → FLUX 修 → 存檔、更新 scene_graph。"""
    from designbridge.core.nodes.renderer import _fit_condition_image, _instances_to_spatial_text, _projection_instances
    from designbridge.layout.floorplan_render import _generate_floor_plan
    from designbridge.layout.layout_items import FurnitureItem
    from designbridge.layout.projected_depth import _write_projection_meta
    from designbridge.layout.scene_graph_to_depth import project_scene_graph_to_depth
    from designbridge.render.render_backends import _render_inpaint_depth_fal, modal_fill
    from designbridge.style.style_apply import resolve_style_loras

    scene_graph, render_result, gen = ctx.scene_graph, ctx.render_result, ctx.gen
    camera, space_info, output_size = ctx.camera, ctx.space_info, ctx.size
    items = [FurnitureItem(
        id=str(p.get("id", "")), type=str(p.get("type", "default")), x=float(p["x"]), y=float(p["y"]),
        w=float(p["w"]), h=float(p["h"]), rotation=float(p.get("rotation", 0.0)), product_id=str(p.get("product_id") or ""),
    ) for p in new]
    task_id = plan.get("task_id") or str(uuid.uuid4())
    key = f"{task_id}_mv{uuid.uuid4().hex[:6]}"
    render_dir = Path(Config.ARTIFACTS_DIR) / "render"
    render_dir.mkdir(parents=True, exist_ok=True)
    composite_path = render_dir / f"{key}_composite.png"
    Image.fromarray(composite).save(composite_path)

    # 相機釘死成上一張圖的：自動選相機會因為家具位置變了而換角度，整張構圖就跑掉
    layout_dir = Path(Config.ARTIFACTS_DIR) / "layout"
    res = project_scene_graph_to_depth(
        _anchor(new), space_info, layout_dir / f"{key}_projected_depth.png",
        image_size=output_size, seg_out_path=layout_dir / f"{key}_projected_seg.png",
        camera_overrides=camera, auto_select_camera=False,
    )
    _write_projection_meta(res, key)
    depth_path = _fit_condition_image(res["depth_path"], output_size, render_dir / "conditions", f"{key}_depth")

    spatial = _instances_to_spatial_text(_projection_instances(res["depth_path"]))
    base_prompt = gen.get("prompt_preview") or ""
    prompt = (f"Strictly follow this furniture arrangement: {spatial}. " if spatial else "") + base_prompt
    if gen.get("gemini_style_description"):
        prompt += f" Style reference: {gen['gemini_style_description']}"
    loras = gen.get("loras") or resolve_style_loras((plan.get("style_params") or {}).get("style_profile_id"))
    strength = Config.MOVE_FURNITURE_STRENGTH if strength is None else strength

    def _pass(src: np.ndarray, mask: np.ndarray, pass_strength: float, tag: str) -> np.ndarray:
        src_path, mask_path, raw_path = (render_dir / f"{key}_{tag}{s}.png" for s in ("_in", "_mask", ""))
        Image.fromarray(src).save(src_path)
        Image.fromarray(mask.astype(np.uint8) * 255).save(mask_path)
        # 有開 Modal 局部修改就先走自架 Fill dev（沒有深度 ControlNet，靠遮罩外的原圖定位），失敗退回 fal
        painted = modal_fill(
            Image.fromarray(src), Image.fromarray(mask.astype(np.uint8) * 255), prompt,
            steps=28, guidance=Config.FAL_INPAINT_DEV_GUIDANCE, seed=gen.get("seed"),
            label=f"modal.move_{tag}", strength=pass_strength,
        )
        if painted is not None:
            painted.save(raw_path)
            return np.asarray(painted.convert("RGB").resize(output_size, Image.LANCZOS))
        if not _render_inpaint_depth_fal(
            prompt, str(src_path), str(mask_path), str(depth_path), raw_path,
            strength=pass_strength, depth_conditioning_scale=Config.MOVE_FURNITURE_DEPTH_SCALE,
            output_size=output_size, loras=loras, seed=gen.get("seed"),
        ):
            raise RuntimeError("inpaint 重繪失敗")
        return np.asarray(Image.open(raw_path).convert("RGB").resize(output_size, Image.LANCZOS))

    # 1. 舊位置用 LaMa 補成地板／牆（FLUX 高強度補洞常會畫出新家具或把旁邊的床單延伸進來）；
    #    LaMa 不能用、或有轉向／新增家具要生成時才用 FLUX 高強度
    # 2. 家具本體＋邊緣＋補過的洞一起低強度修：補回放大掉的細節、補上接觸陰影、讓 LaMa 的平塗有材質
    # 每段回來的圖遮罩外也會被 VAE 編解碼糊一點，只取遮罩內，遮罩外留原像素
    final = composite
    hole = fill_mask & ~redraw
    lama = lama_fill(final, _dilate(hole, 3)) if hole.any() else None
    if lama is not None:
        final = blend_in(final, lama, hole, protect=pasted)
    flux_fill = redraw if lama is not None or not hole.any() else fill_mask
    if flux_fill.any():
        final = blend_in(final, _pass(final, flux_fill, strength, "fill"), flux_fill, protect=pasted)
    harmonize = Config.MOVE_FURNITURE_HARMONIZE_STRENGTH
    touched = pasted | (hole if lama is not None else np.zeros_like(hole))
    if touched.any() and harmonize > 0:
        body = _dilate(touched, 8)
        final = blend_in(final, _pass(final, body, harmonize, "body"), body)
    out_path = render_dir / f"{key}.png"
    Image.fromarray(final).save(out_path)

    floor_plan_path = _generate_floor_plan(
        items, key, room_type=str(scene_graph.get("room_type") or "living_room"),
        room_w=float(scene_graph.get("room_w") or ctx.room_w), room_d=float(scene_graph.get("room_d") or ctx.room_d),
    )
    new_scene_graph = {
        **scene_graph,
        "furniture_placements": new,
        "floor_plan_path": floor_plan_path,
        "projected_depth_path": res.get("depth_path"),
        "projected_seg_path": res.get("seg_path"),
        "projection_mode": "synthetic",
    }
    generation_params = {
        **gen,
        "backend": "move_furniture_inpaint_fal",
        "model": "fal-ai/flux-general/inpainting",
        "move_strength": strength,
        "move_harmonize_strength": harmonize,
        "move_depth_scale": Config.MOVE_FURNITURE_DEPTH_SCALE,
        "move_changed": changed,
        "move_source_image": str(ctx.image_path),
        "move_composite_image": str(composite_path),
        "layout_camera": camera,
        "furniture_layout_injected": spatial,
    }
    return {
        "generated_image_path": str(out_path),
        "composite_image_path": str(composite_path),
        "scene_graph": new_scene_graph,
        "render_result": {**render_result, "generated_image_path": str(out_path), "generation_params": generation_params},
        "changed": changed,
        "changed_area": round(float((fill_mask | pasted).mean()), 4),
    }
