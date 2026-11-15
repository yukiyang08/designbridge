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
    ("lamp", "vase"),   # 檯燈的燈座常是花瓶造型，被標成 vase
)
_PLANT_FAMILY = {_FAMILIES.index(f) for f in _FAMILIES if "plant" in f}   # 盆栽腳下的地板常被標成旁邊的家具
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
        return _split_by_depth(m, depth, edges)
    # 斷層上的像素分給最近的那塊
    idx = np.zeros(m.shape, dtype=np.int32)
    for k, b in enumerate(big, 1):
        idx[b] = k
    _, (iy, ix) = ndimage.distance_transform_edt(idx == 0, return_indices=True)
    nearest = idx[iy, ix]
    return [m & (nearest == k) for k in range(1, len(big) + 1)]


def _split_by_depth(m: np.ndarray, depth: np.ndarray, edges: np.ndarray) -> list[np.ndarray]:
    """斷層沒圍成封閉輪廓時（前排沙發椅背連到後排沙發）：按深度雙峰切成前後兩塊。

    交界大多落在深度斷層上才切；沿牆往後延伸的 L 型沙發深度是漸變的，不會被切斷。
    """
    v = depth[m].clip(0, 255).astype(np.int64)
    hist = np.bincount(v, minlength=256).astype(float)
    cnt, tot = np.cumsum(hist), np.cumsum(hist * np.arange(256))
    w0, w1 = cnt[:-1], cnt[-1] - cnt[:-1]
    ok = (w0 > 0) & (w1 > 0)
    between = np.zeros(255)
    mu0 = tot[:-1][ok] / w0[ok]
    mu1 = (tot[-1] - tot[:-1][ok]) / w1[ok]
    between[ok] = w0[ok] * w1[ok] * (mu0 - mu1) ** 2
    t = int(between.argmax()) + 1   # Otsu
    far, near = m & (depth < t), m & (depth >= t)
    if min(far.sum(), near.sum()) < 0.1 * m.sum():
        return [m]
    if float(np.median(depth[near])) - float(np.median(depth[far])) <= _SEED_SPLIT_JUMP:
        return [m]
    border = _dilate(near, 1) & far
    if not border.any() or (border & _dilate(edges, 2)).sum() < 0.6 * border.sum():
        return [m]
    return [near, far]


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
                parts = _split_seed(m, depth, edges)
                if any(p.sum() < min_px for p in parts):   # 落地燈這種細長的切開後兩塊都太小，整件就消失了
                    parts = [m]
                seeds += [(name.strip(), p) for p in parts]
    return seeds


def _inner_point(seed: np.ndarray) -> tuple[int, int]:
    from scipy import ndimage

    dist = ndimage.distance_transform_edt(seed)
    py, px = np.unravel_index(int(dist.argmax()), dist.shape)
    return int(px), int(py)


def _sam_masks(predictor, image: np.ndarray, seeds: list[tuple[str, np.ndarray]]) -> list[tuple[str, np.ndarray, float]]:
    """每個種子：框 + 種子最內部的一點當提示，三個候選裡挑跟種子最吻合的。

    框裡其他種子的內點當負點：後排沙發的框蓋住前排沙發時，SAM 才不會把兩件切成一塊。
    """
    import torch

    from designbridge.render.inpaint import _SAM2_INFER_LOCK

    h, w = image.shape[:2]
    pts = [_inner_point(s) for _, s in seeds]
    out = []
    # predictor 跟描邊、inpaint 共用：不鎖的話別的請求 set_image 會把這張圖的特徵蓋掉
    with torch.inference_mode(), _SAM2_INFER_LOCK:
        predictor.set_image(image)
        for k, (name, seed) in enumerate(seeds):
            x0, y0, x1, y1 = _bbox(seed)
            pad = round(0.05 * max(x1 - x0, y1 - y0))
            box = np.array([max(0, x0 - pad), max(0, y0 - pad), min(w - 1, x1 + pad), min(h - 1, y1 + pad)])
            neg = [p for j, p in enumerate(pts) if j != k and box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]
                   and not seed[p[1], p[0]]]
            coords = np.array([pts[k], *neg])
            masks, scores, _ = predictor.predict(
                point_coords=coords, point_labels=np.array([1] + [0] * len(neg)), box=box, multimask_output=True,
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


def _attach_small_on_top(insts: list[dict], seg: np.ndarray, labels: dict[int, str], depth: np.ndarray) -> None:
    """床頭櫃上的檯燈這種太小、當不成種子的東西：碰得到某件家具、又在它底緣上方，就併進去一起搬。

    同族的優先（盆子給盆栽，不給剛好疊在前面的茶几），同族的不限上下（盆子在盆栽底下）。
    """
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
            fam = _family(name)
            touching = [i for i in insts if (touch & i["mask"]).any()]
            # 花瓶在花底下、中間常隔幾 px：同族的往上也多找 30 px；花很細、深度常跟牆混在一起，不看深度
            up = _dilate(piece, 6)
            for s in range(1, 31):
                up[:-s] |= piece[s:]
            hosts = [i for i in insts if fam & _family(i["label"]) and (up & i["mask"]).any()] or [
                i for i in touching
                if _bbox(piece)[3] < _bbox(i["mask"])[3] and _depth_continuous(piece, i["mask"], touch, depth)]
            host = max(hosts, key=lambda i: int((touch & i["mask"]).sum()), default=None)
            if host is not None:
                host["mask"] |= piece


def _refine_whole(insts: list[dict], image: np.ndarray, seg: np.ndarray, labels: dict[int, str]) -> None:
    """可移動的家具用整件的框＋多個正點再切一次，補回第一輪漏掉的細桌腳、椅腳。

    第一輪每個種子各切各的，細腳被語意分割當成地板，SAM 也只切到桌面；整件一起提示才切得到腳。
    只補原本是背景（地板、牆）的像素；同族零件（桌子底座）大半被整件輪廓蓋住就併進來。
    """
    from designbridge.render.inpaint import _SAM2_INFER_LOCK, _get_sam2_predictor

    movable = [i for i in insts if i["on_floor"]]
    predictor = _get_sam2_predictor() if movable else None
    if predictor is None:
        return
    import torch
    from scipy import ndimage

    h, w = seg.shape
    bg = np.isin(seg, [k for k, n in labels.items() if n.strip() in _BACKGROUND_LABELS])
    with torch.inference_mode(), _SAM2_INFER_LOCK:
        predictor.set_image(image)
        for inst in movable:
            if not inst["mask"].any():
                continue
            near = _dilate(inst["mask"], 15)
            for o in insts:
                if (o is not inst and o["mask"].any() and _family(o["label"]) & _family(inst["label"])
                        and (near & o["mask"]).any() and _same_object(predictor, inst["mask"], o["mask"])):
                    inst["mask"] = inst["mask"] | o["mask"]
                    o["mask"] = np.zeros_like(o["mask"])
        centers = {id(i): _inner_point(i["mask"]) for i in insts if i["mask"].any()}
        for inst in movable:
            m = inst["mask"]
            if not m.any():
                continue
            x0, y0, x1, y1 = _bbox(m)
            pad = round(0.05 * max(x1 - x0, y1 - y0))
            box = np.array([max(0, x0 - pad), max(0, y0 - pad), min(w - 1, x1 + pad), min(h - 1, y1 + pad)])
            comp, n = ndimage.label(m)
            sizes = ndimage.sum(m, comp, range(1, n + 1))
            pos = [_inner_point(comp == k + 1) for k in np.argsort(sizes)[::-1][:4] if sizes[k] >= 0.05 * m.sum()]
            # 同族的（桌子底座）不當負點，才切得進整件
            neg = [c for o in insts if o is not inst and id(o) in centers and not _family(o["label"]) & _family(inst["label"])
                   for c in [centers[id(o)]] if box[0] <= c[0] <= box[2] and box[1] <= c[1] <= box[3] and not m[c[1], c[0]]]
            masks, scores, _ = predictor.predict(
                point_coords=np.array(pos + neg), point_labels=np.array([1] * len(pos) + [0] * len(neg)),
                box=box, multimask_output=True,
            )
            # 分數差不多的候選裡取最大的：整件，不是局部
            ok = [k for k in range(len(scores)) if scores[k] >= scores.max() - 0.1]
            whole = masks[max(ok, key=lambda k: int(masks[k].sum()))].astype(bool)
            others = np.zeros_like(m)
            for o in insts:
                if o is not inst:
                    others |= o["mask"]
            add = whole & bg & ~m & ~others
            if add.sum() <= 0.5 * m.sum():   # 補太多多半是 SAM 把地板一起切進來，不補
                m |= add
            inst["mask"] = m
    insts[:] = [i for i in insts if i["mask"].any()]


def _same_object(predictor, a: np.ndarray, b: np.ndarray, cover: float = 0.9) -> bool:
    """框住兩塊、只點其中一塊，SAM 自己就把另一塊整個切進來，兩個方向都是，才算同一件（桌面跟底座）。

    同時點兩塊 SAM 一定會切成一塊，並排的兩張椅子也會；只點一邊才看得出它們是不是連在一起。
    """
    x0, y0, x1, y1 = _bbox(a | b)
    box = np.array([x0, y0, x1, y1])
    for src, dst in ((a, b), (b, a)):
        masks, _, _ = predictor.predict(point_coords=np.array([_inner_point(src)]), point_labels=np.array([1]),
                                        box=box, multimask_output=True)
        masks = masks.astype(bool)
        if not any((mm & dst).sum() >= cover * dst.sum() and (mm & src).sum() >= cover * src.sum() for mm in masks):
            return False
    return True


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


def _touches_floor(mask: np.ndarray, floorish: np.ndarray, loose: np.ndarray | None = None,
                   depth: np.ndarray | None = None) -> bool:
    """輪廓最下緣正下方大多是地板／地毯：落地家具。掛畫、壁掛電視、層板下方是牆或別的家具。

    loose：沒被任何家具佔走、也不是牆的像素。語意分割常把盆栽腳下的地板標成旁邊的茶几，
    這種像素深度跟家具底部一樣（貼著它），也算地面。
    """
    x0, y0, x1, y1 = _bbox(mask)
    h = mask.shape[0]
    if y1 >= h - 1:
        return True   # 被畫面下緣裁掉的，一定是站在地上靠鏡頭的
    below = _below_ring(mask)
    if not below.any():
        return False
    ground = floorish
    if loose is not None and depth is not None:
        bottom = float(np.median(depth[below]))
        ground = floorish | (loose & (np.abs(depth - bottom) <= 6))
    return ground[below].mean() > 0.4


def _below_ring(mask: np.ndarray) -> np.ndarray:
    x0, y0, x1, y1 = _bbox(mask)
    below = _dilate(mask, 6) & ~mask
    below[: max(0, y1 - max(3, round(0.04 * (y1 - y0))))] = False
    return below


def _floor_hidden_by_nearer(inst: dict, insts: list[dict], floorish: np.ndarray, depth: np.ndarray) -> bool:
    """沙發後面的椅子：椅腳底下被前面的沙發擋住，正下方看到的是沙發不是地板，但它其實站在地上。

    正下方除了地板，其餘大多是明顯比它近的家具才算；還要看得到一點地板，
    掛在沙發上方的壁櫃底下只有沙發、沒有地板，不會被當成落地家具。
    """
    below = _below_ring(inst["mask"])
    if not below.any():
        return False
    med = float(np.median(depth[inst["mask"]]))
    nearer = np.zeros_like(below)
    for o in insts:
        if o is not inst and o["mask"].any() and float(np.median(depth[o["mask"]])) - med > _SEED_SPLIT_JUMP:
            nearer |= o["mask"]
    floor_frac, near_frac = floorish[below].mean(), nearer[below].mean()
    return floor_frac > 0.15 and near_frac > 0.2 and floor_frac + near_frac > 0.6


def _depth_continuous(small: np.ndarray, host: np.ndarray, touch: np.ndarray, depth: np.ndarray,
                      max_jump: float = _SEED_SPLIT_JUMP) -> bool:
    """放在家具上的東西跟家具在交界處深度接近；只是畫面上疊到、其實前後差很遠的（沙發後面的椅子）不併。"""
    edge_h = touch & host
    if not edge_h.any():
        return True
    edge_s = _dilate(edge_h, 3) & small
    if not edge_s.any():   # 隔了一段（檯燈細燈桿）：拿整件的深度比
        edge_s = small
    return abs(float(np.median(depth[edge_h])) - float(np.median(depth[edge_s]))) <= max_jump


def segment_furniture(image_path: str, size: tuple[int, int] | None = None, *, refresh: bool = False,
                      strict: bool = False) -> list[dict]:
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
            # 分數全是 0 = 當時沒有 SAM 2、只有語意輪廓；現在裝好了就重算，不然永遠讀到粗的那份
            if not (meta and all(not m.get("score") for m in meta) and _get_sam2_predictor() is not None):
                return [{**m, "mask": idmap == m["index"] + 1} for m in meta]

    seg, labels = segment_image(image_path, size, strict=strict)
    if seg is None:
        return []
    depth = _depth(image_path, size)
    rgb = np.asarray(image)
    seeds = _seeds(seg, labels, depth)
    raw_path = out / f"sam_raw_v2_{len(seeds)}.npz"   # 提示方式改了換版號，舊快取不沿用
    raw = None
    if raw_path.is_file():   # SAM 是最慢的一步（每件約 2 秒），後處理規則改了只重跑後處理；種子數變了才重算
        z = np.load(raw_path, allow_pickle=False)
        raw = list(zip(z["names"].tolist(), list(z["masks"]), z["scores"].tolist()))
        if raw and all(not r[2] for r in raw) and _get_sam2_predictor() is not None:
            raw = None   # 沒有 SAM 2 時存下的語意種子，現在有 SAM 2 了重切
    if raw is None:
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
        # 只併同類／同族：檯燈的 SAM 輪廓溢到沙發上時不能把整張沙發吃進來，重疊的像素交給 _resolve 依深度分
        same = next((i for i in insts if (m & i["mask"]).sum() > 0.5 * min(m.sum(), i["mask"].sum())
                     and (i["label"] == name or _family(i["label"]) & _family(name))), None)
        if same is not None:
            same["mask"] |= m
            continue
        if m.sum() >= _MIN_AREA * m.size:
            insts.append({"label": name, "score": round(score, 3), "mask": m})
    if insts:
        _resolve(insts, depth)
    insts = [i for i in insts if i["mask"].sum() >= _MIN_AREA * i["mask"].size]
    _merge_continuous(insts, depth)
    # 先把盆子這類小東西併回去，盆栽才碰得到地
    _attach_small_on_top(insts, seg, labels, depth)

    floorish = np.isin(seg, [i for i, n in labels.items() if n.strip() in ("floor", "rug")])
    claimed = np.zeros(seg.shape, dtype=bool)
    for inst in insts:
        claimed |= inst["mask"]
    loose = ~claimed & ~np.isin(seg, [i for i, n in labels.items() if n.strip() in _BACKGROUND_LABELS])
    for inst in insts:
        inst["on_floor"] = _touches_floor(inst["mask"], floorish, loose if _family(inst["label"]) & _PLANT_FAMILY else None, depth)
    for inst in insts:
        if not inst["on_floor"] and _family(inst["label"]):
            inst["on_floor"] = _floor_hidden_by_nearer(inst, insts, floorish, depth)
    # 不碰地的：放在家具上的小東西（杯子、抱枕、檯燈…）併進底下那件一起搬；其他（掛畫、壁掛電視、層板）固定不能搬
    for small in sorted([i for i in insts if not i["on_floor"]], key=lambda i: i["mask"].sum()):
        touch = _dilate(small["mask"], 6)
        hosts = [i for i in insts if i is not small and i["mask"].any() and (touch & i["mask"]).any()]
        host = max(hosts, key=lambda i: int((touch & i["mask"]).sum()), default=None)
        # 只併「本來就放在家具上的東西」或同族的部位（長凳上的坐墊）；壁櫃碰到沙發椅背不能被併進沙發
        if host is None:
            continue
        same_kind = any(k in small["label"] for k in _ON_TOP_LABELS) or _family(small["label"]) & _family(host["label"])
        # 擺在上面的東西接觸處深度幾乎一樣（沙發後面櫃子上的花瓶跟椅背上緣差十幾）；同族部位（抱枕）沿用寬的門檻
        same_part = small["label"] == host["label"] or _family(small["label"]) & _family(host["label"])
        jump = _SEED_SPLIT_JUMP if same_part else 10
        if same_kind and _depth_continuous(small["mask"], host["mask"], touch, depth, max_jump=jump):
            host["mask"] |= small["mask"]
            small["mask"] = np.zeros_like(small["mask"])
    insts = [i for i in insts if i["mask"].any()]
    _refine_whole(insts, rgb, seg, labels)
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
