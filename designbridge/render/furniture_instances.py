"""渲染圖生成後自動切出每件家具（移家具用）。

只看圖本身，不看排版投影：AI 畫的家具常常跟投影框對不上（投影上的邊桌畫成椅子），
拿投影框去切會切到別的東西。流程：
語意分割找出家具區域當種子 → 每個種子用 SAM 2 切實例輪廓 → 用渲染圖自己估的深度
分開重疊的家具、去掉溢到地板／牆的部分 → 放在家具上的小東西併進底下那件。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from designbridge.core.config import Config
from designbridge.render.move_furniture import (
    _ATTACHED_LABELS, _BACKGROUND_LABELS, _ON_TOP_LABELS, _bbox, _dilate, segment_image,
)

_MIN_AREA = 0.0015      # 種子至少佔畫面 0.15%，太小的雜點不當家具
# 語意分割常把同一件家具的部位分成同一族的不同類（長凳 → 凳面 sofa、椅腳 stool、坐墊 ottoman）；
# 只有同族、交界深度又連續的才併，茶几跟長凳、壁櫃跟沙發這種不同族的相鄰家具不會被黏在一起
_FAMILIES = (
    ("sofa", "chair", "armchair", "stool", "ottoman", "bench", "seat", "cushion", "pillow", "swivel chair"),
    ("table", "desk", "counter"),
    ("cabinet", "shelf", "wardrobe", "chest of drawers", "bookcase", "case", "buffet", "sideboard"),
    ("bed", "pillow", "blanket", "quilt"),
    ("plant", "pot", "vase", "flower"),
)
_DEPTH_SPILL = 28       # 0–255 深度刻度：輪廓裡被分成背景、深度又差這麼多的像素是溢出去的
_SEED_SPLIT_JUMP = 25   # 同一類的一塊切開後兩邊中位深度差超過這個，才當成前後兩件家具


def _out_dir(image_path: str) -> Path:
    return Path(Config.ARTIFACTS_DIR) / "vision" / "move_seg" / Path(image_path).stem


def _depth(image_path: str, size: tuple[int, int]) -> np.ndarray:
    """渲染圖自己的深度（近亮遠暗，0–255），依圖檔快取。"""
    out = _out_dir(image_path)
    path = out / "depth.png"
    if not path.is_file():
        from designbridge.layout.vision import run_depth_estimation
        run_depth_estimation(str(image_path), model_name=Config.DEPTH_MODEL, out_dir=out)
    d = Image.open(path).convert("L")
    return np.asarray(d.resize(size, Image.BILINEAR) if d.size != size else d).astype(np.int16)


def _depth_edges(depth: np.ndarray, span: int = 2, jump: int = 14) -> np.ndarray:
    """深度在 2*span px 內跳超過 jump 的地方：前後兩件家具的交界。"""
    e = np.zeros(depth.shape, dtype=bool)
    dx = np.abs(depth[:, 2 * span:] - depth[:, :-2 * span]) > jump
    dy = np.abs(depth[2 * span:, :] - depth[:-2 * span, :]) > jump
    e[:, span:-span] |= dx
    e[span:-span, :] |= dy
    return e


def _split_seed(m: np.ndarray, depth: np.ndarray, edges: np.ndarray) -> list[np.ndarray]:
    """同一類的一塊裡其實是前後兩件家具（長凳左半被分成「茶几」）：沿深度斷層切開。

    只在切出來的幾塊離鏡頭距離明顯不同時才切；沙發椅背跟坐墊之間的落差小，不會被切斷。
    """
    from scipy import ndimage

    comp, n = ndimage.label(m & ~edges)
    big = [comp == k for k in range(1, n + 1) if (comp == k).sum() >= 0.2 * m.sum()]
    meds = [float(np.median(depth[b])) for b in big]
    if len(big) < 2 or max(meds) - min(meds) <= _SEED_SPLIT_JUMP:
        return [m]
    # 斷層上的像素分給最近的那塊
    idx = np.zeros(m.shape, dtype=np.int32)
    for k, b in enumerate(big, 1):
        idx[b] = k
    _, (iy, ix) = ndimage.distance_transform_edt(idx == 0, return_indices=True)
    nearest = idx[iy, ix]
    return [m & (nearest == k) for k in range(1, len(big) + 1)]


def _seeds(seg: np.ndarray, labels: dict[int, str], depth: np.ndarray) -> list[tuple[str, np.ndarray]]:
    from scipy import ndimage

    min_px = _MIN_AREA * seg.size
    edges = _depth_edges(depth)
    seeds = []
    for cls in np.unique(seg).tolist():
        name = labels.get(cls, "")
        if not name or name in _BACKGROUND_LABELS:
            continue
        comp, n = ndimage.label(seg == cls)
        for k in range(1, n + 1):
            m = comp == k
            if m.sum() >= min_px:
                seeds += [(name.strip(), p) for p in _split_seed(m, depth, edges) if p.sum() >= min_px]
    return seeds


def _sam_masks(predictor, image: np.ndarray, seeds: list[tuple[str, np.ndarray]]) -> list[tuple[str, np.ndarray, float]]:
    """每個種子：框 + 種子最內部的一點當提示，三個候選裡挑跟種子最吻合的。"""
    import torch
    from scipy import ndimage

    h, w = image.shape[:2]
    out = []
    with torch.inference_mode():
        predictor.set_image(image)
        for name, seed in seeds:
            x0, y0, x1, y1 = _bbox(seed)
            pad = round(0.05 * max(x1 - x0, y1 - y0))
            box = np.array([max(0, x0 - pad), max(0, y0 - pad), min(w - 1, x1 + pad), min(h - 1, y1 + pad)])
            dist = ndimage.distance_transform_edt(seed)
            py, px = np.unravel_index(int(dist.argmax()), dist.shape)
            masks, scores, _ = predictor.predict(
                point_coords=np.array([[px, py]]), point_labels=np.array([1]), box=box, multimask_output=True,
            )
            ious = [(m & seed).sum() / max((m | seed).sum(), 1) for m in masks.astype(bool)]
            best = int(np.argmax(ious))
            out.append((name, masks[best].astype(bool), float(scores[best]) * float(ious[best])))
    return out


def _resolve(insts: list[dict], depth: np.ndarray) -> None:
    """同一個像素被好幾件搶：給深度最接近的那件（前面的椅子不會被算進後面的桌子）。"""
    stack = np.stack([i["mask"] for i in insts])
    claimed = stack.sum(axis=0) > 1
    if not claimed.any():
        return
    med = np.array([np.median(depth[i["mask"]]) for i in insts])[:, None]
    ys, xs = np.nonzero(claimed)
    cand = stack[:, ys, xs]
    diff = np.where(cand, np.abs(depth[ys, xs][None, :] - med), np.inf)
    owner = diff.argmin(axis=0)
    for k, inst in enumerate(insts):
        inst["mask"][ys, xs] = owner == k


def _family(label: str) -> set[int]:
    return {k for k, fam in enumerate(_FAMILIES) if any(w in label for w in fam)}


def _merge_continuous(insts: list[dict], depth: np.ndarray, max_jump: float = 6.0) -> None:
    """相鄰、交界處深度連續的兩塊是同一件家具（語意分割把一張長凳切成凳面、椅腳、坐墊幾類）。

    兩件不同家具相鄰時交界一定有深度落差（前面那件比後面近）；同一件的不同部位交界是連續表面。
    """
    changed = True
    while changed:
        changed = False
        for a in insts:
            if not a["mask"].any():
                continue
            ring = _dilate(a["mask"], 2) & ~a["mask"]
            for b in insts:
                if b is a or not b["mask"].any() or not (_family(a["label"]) & _family(b["label"])):
                    continue
                edge_b = ring & b["mask"]
                if edge_b.sum() < 15:
                    continue
                edge_a = _dilate(edge_b, 2) & a["mask"]
                if abs(float(np.median(depth[edge_a])) - float(np.median(depth[edge_b]))) <= max_jump:
                    keep, drop = (a, b) if a["mask"].sum() >= b["mask"].sum() else (b, a)
                    keep["mask"] |= drop["mask"]
                    drop["mask"] = np.zeros_like(drop["mask"])
                    changed = True
        insts[:] = [i for i in insts if i["mask"].any()]


def _attach_small_on_top(insts: list[dict], seg: np.ndarray, labels: dict[int, str]) -> None:
    """床頭櫃上的檯燈這種太小、當不成種子的東西：碰得到某件家具、又在它底緣上方，就併進去一起搬。"""
    from scipy import ndimage

    claimed = np.zeros(seg.shape, dtype=bool)
    for i in insts:
        claimed |= i["mask"]
    for cls, name in labels.items():
        if not any(k in name for k in _ON_TOP_LABELS):
            continue
        comp, n = ndimage.label((seg == cls) & ~claimed)
        for k in range(1, n + 1):
            piece = comp == k
            if piece.sum() < 40:
                continue
            # 檯燈的細燈桿常被分成牆，燈罩跟櫃面之間會隔一段：往正下方多找 30 px
            touch = _dilate(piece, 6)
            for s in range(1, 31):
                touch[s:] |= piece[:-s]
            hosts = [i for i in insts if (touch & i["mask"]).any() and _bbox(piece)[3] < _bbox(i["mask"])[3]]
            host = max(hosts, key=lambda i: int((touch & i["mask"]).sum()), default=None)
            if host is not None:
                host["mask"] |= piece


def _clean(mask: np.ndarray) -> np.ndarray:
    """補掉輪廓內部的小破洞、丟掉離主體很遠的碎點。椅腳之間那種跟外面相通的空隙不會被補。"""
    from scipy import ndimage

    filled = ndimage.binary_fill_holes(mask)
    holes = filled & ~mask
    comp, n = ndimage.label(holes)
    if n:
        sizes = ndimage.sum(holes, comp, range(1, n + 1))
        mask = mask | np.isin(comp, [k + 1 for k, s in enumerate(sizes) if s < 0.02 * mask.sum()])
    comp, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, comp, range(1, n + 1))
        mask = np.isin(comp, [k + 1 for k, s in enumerate(sizes) if s >= 0.03 * sizes.max()])
    return mask


def _touches_floor(mask: np.ndarray, floorish: np.ndarray) -> bool:
    """輪廓最下緣正下方大多是地板／地毯：落地家具。掛畫、壁掛電視、層板下方是牆或別的家具。"""
    x0, y0, x1, y1 = _bbox(mask)
    h = mask.shape[0]
    if y1 >= h - 1:
        return True   # 被畫面下緣裁掉的，一定是站在地上靠鏡頭的
    below = _dilate(mask, 6) & ~mask
    below[: max(0, y1 - max(3, round(0.04 * (y1 - y0))))] = False
    return below.any() and floorish[below].mean() > 0.4


def segment_furniture(image_path: str, size: tuple[int, int] | None = None, *, refresh: bool = False) -> list[dict]:
    """回傳每件家具 {index, label, score, bbox, area, contact, depth, mask}，mask 是 bool H×W。

    結果存在 artifacts/vision/move_seg/<圖檔>/：instances.png（像素值 = 第幾件 + 1）與 instances.json，
    同一張圖之後直接讀檔。contact 是家具碰地的點（輪廓最下緣的中點），之後換算地板位置用。
    """
    from designbridge.render.inpaint import _get_sam2_predictor

    image = Image.open(image_path).convert("RGB")
    if size and image.size != size:
        image = image.resize(size, Image.LANCZOS)
    size = image.size
    out = _out_dir(image_path)
    map_path, meta_path = out / "instances.png", out / "instances.json"
    if not refresh and map_path.is_file() and meta_path.is_file():
        idmap = np.asarray(Image.open(map_path)).astype(np.int32)
        if idmap.shape == size[::-1]:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return [{**m, "mask": idmap == m["index"] + 1} for m in meta]

    seg, labels = segment_image(image_path, size)
    if seg is None:
        return []
    depth = _depth(image_path, size)
    rgb = np.asarray(image)
    seeds = _seeds(seg, labels, depth)
    raw_path = out / f"sam_raw_{len(seeds)}.npz"
    if raw_path.is_file():   # SAM 是最慢的一步（每件約 2 秒），後處理規則改了只重跑後處理；種子數變了才重算
        z = np.load(raw_path, allow_pickle=False)
        raw = list(zip(z["names"].tolist(), list(z["masks"]), z["scores"].tolist()))
    else:
        predictor = _get_sam2_predictor()
        raw = _sam_masks(predictor, rgb, seeds) if predictor is not None and seeds else [(n, m, 0.0) for n, m in seeds]
        if raw:
            out.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(raw_path, names=np.array([r[0] for r in raw]),
                                masks=np.stack([r[1] for r in raw]), scores=np.array([r[2] for r in raw]))

    insts: list[dict] = []
    bg = np.isin(seg, [i for i, n in labels.items() if n in _BACKGROUND_LABELS])
    for name, m, score in sorted(raw, key=lambda r: -r[2]):
        if not m.any():
            continue
        med = float(np.median(depth[m]))
        m = m & ~(bg & (np.abs(depth - med) > _DEPTH_SPILL))
        # 跟已收的大半重疊：兩個種子切到同一件（長凳左右半各一個種子），合成一件
        same = next((i for i in insts if (m & i["mask"]).sum() > 0.5 * min(m.sum(), i["mask"].sum())), None)
        if same is not None:
            same["mask"] |= m
            continue
        if m.sum() >= _MIN_AREA * m.size:
            insts.append({"label": name, "score": round(score, 3), "mask": m})
    if insts:
        _resolve(insts, depth)
    insts = [i for i in insts if i["mask"].sum() >= _MIN_AREA * i["mask"].size]
    _merge_continuous(insts, depth)

    floorish = np.isin(seg, [i for i, n in labels.items() if n.strip() in ("floor", "rug")])
    for inst in insts:
        inst["on_floor"] = _touches_floor(inst["mask"], floorish)
    # 不碰地的：放在家具上的小東西（杯子、抱枕、檯燈…）併進底下那件一起搬；其他（掛畫、壁掛電視、層板）固定不能搬
    for small in sorted([i for i in insts if not i["on_floor"]], key=lambda i: i["mask"].sum()):
        touch = _dilate(small["mask"], 6)
        hosts = [i for i in insts if i is not small and i["mask"].any() and (touch & i["mask"]).any()]
        host = max(hosts, key=lambda i: int((touch & i["mask"]).sum()), default=None)
        # 只併「本來就放在家具上的東西」或同族的部位（長凳上的坐墊）；壁櫃碰到沙發椅背不能被併進沙發
        if host is not None and (any(k in small["label"] for k in _ON_TOP_LABELS)
                                 or _family(small["label"]) & _family(host["label"])):
            host["mask"] |= small["mask"]
            small["mask"] = np.zeros_like(small["mask"])
    insts = [i for i in insts if i["mask"].any()]
    _attach_small_on_top(insts, seg, labels)
    for inst in insts:
        inst["mask"] = _clean(inst["mask"])

    for k, inst in enumerate(insts):
        m = inst["mask"]
        x0, y0, x1, y1 = _bbox(m)
        ys, xs = np.nonzero(m)
        low = ys >= y1 - 1 - max(2, round(0.03 * (y1 - y0)))
        inst.update(
            index=k, bbox=[x0, y0, x1, y1], area=int(m.sum()), movable=bool(inst["on_floor"]),
            contact=[float(xs[low].mean()), float(y1 - 1)], depth=float(np.median(depth[m])),
        )
        inst.pop("on_floor")

    out.mkdir(parents=True, exist_ok=True)
    idmap = np.zeros(size[::-1], dtype=np.uint16)
    for inst in sorted(insts, key=lambda i: i["depth"]):   # 近的後寫，重疊時近的贏
        idmap[inst["mask"]] = inst["index"] + 1
    Image.fromarray(idmap).save(map_path)
    meta = [{k: v for k, v in i.items() if k != "mask"} for i in insts]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return [{**m, "mask": idmap == m["index"] + 1} for m in meta]
