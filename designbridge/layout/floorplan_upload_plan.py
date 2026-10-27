"""把上傳平面圖切出的房間轉成整層流程（CAD 房型生成）同格式的資料，讓上傳的整戶圖也能走
整層進度、總覽、批次套用風格、存雲端。

整層流程以公尺為單位，上傳的圖只有像素：比例尺優先用使用者輸入的總坪數，其次請 Gemini 逐間讀
尺寸標註、除以切割出的像素寬深換算，讀不到才用一般住宅面積估。換算後把每間房吸附成彼此貼齊的
矩形，交給 roomplan 的牆／門／窗推導與 SVG 繪製，輸出跟「房型生成」完全同一種平面圖（尺寸線、
面積、比例尺、總坪數都是它畫的）。多邊形與原圖外框另外帶著，單房流程要用它裁原圖。
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from designbridge.core.config import Config
from designbridge.roomplan.constants import PING_TO_M2
from designbridge.roomplan.schemas import DoorOpening, RoomInstance, Rect, WindowOpening
from designbridge.roomplan.svg_render import render_room_plan_svg
from designbridge.roomplan.walls import derive_walls_and_openings

_SCALE_CACHE_DIR = Path("artifacts/cache/room_seeds")
_SCALE_PROMPT_VERSION = "v2"
# 讀不到尺寸標註時假設整戶室內面積（一般台灣住宅約 25 坪）
_ASSUMED_TOTAL_M2 = 85.0
# 比例尺合理範圍：整張圖寬換算後應落在這個公尺區間，否則視為讀錯
_PLAUSIBLE_IMAGE_W_M = (4.0, 80.0)
_SNAP_TOL_M = 0.25   # 房間外框的邊界相差在這以內，視為同一條牆線
_MIN_DIM_M = 0.3     # 吸附／裁切後房間邊長的下限，再小就放棄這次調整
_TYPE_LABELS = {
    "living_room": "客廳", "bedroom": "臥室", "kitchen": "廚房", "dining_room": "餐廳",
    "study": "書房", "bathroom": "浴室", "balcony": "陽台",
}


def _scale_from_rooms(image_path: str, rooms: list[dict], img_w: int, img_h: int) -> float | None:
    """請 Gemini 看字母標記圖，逐間讀出寬、深的尺寸標註（公尺），除以切割出的像素寬深，
    取所有房間的中位數當每像素幾公尺。Gemini 讀數字很準、標位置不準，所以位置交給切割；
    取中位數讓個別讀錯的房間不影響結果。讀不到或不合理回 None。"""
    import statistics

    from designbridge.layout.floorplan_parse import _mark, _mark_rooms_image, _parse_llm_layout
    from designbridge.render.llm import call_llm

    key = Path(image_path).read_bytes() + json.dumps([r["polygon"] for r in rooms]).encode()
    digest = hashlib.sha256(key).hexdigest()[:32]
    cache = _SCALE_CACHE_DIR / f"{digest}_scale_{_SCALE_PROMPT_VERSION}.json"
    answers = None
    if cache.is_file():
        try:
            answers = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            answers = None
    if answers is None:
        prompt = (
            "Image 1 is an architectural floor plan. Image 2 is the same plan with each region "
            "shaded and marked with a RED LETTER in a white circle.\n"
            "For every letter whose width (left-right) or depth (top-bottom) is given by a "
            "dimension number written on the drawing, return that size in METERS. Convert the "
            "unit: Taiwanese CAD plans write mm when numbers are in the thousands (3460 = 3.46 m) "
            "and cm when in the hundreds (355 = 3.55 m). Use null for a size with no dimension.\n"
            "Return STRICT JSON only:\n"
            '{"regions":[{"mark":"A","width_m":3.46,"depth_m":null}]}'
        )
        try:
            text = call_llm(prompt, images=[image_path, _mark_rooms_image(image_path, rooms)],
                            json_mode=True, max_tokens=3000)
            answers = ((_parse_llm_layout(text) or {}).get("regions")) or []
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Gemini plan scale failed: {e}")
            return None
        try:
            _SCALE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    index = {_mark(i): r for i, r in enumerate(rooms, 1)}
    ratios = []
    for a in answers:
        r = index.get(str(a.get("mark") or "").strip().upper())
        if not r:
            continue
        ew, eh = _equiv_size(r, img_w, img_h)
        for k, px in (("width_m", ew), ("depth_m", eh)):
            try:
                m = float(a.get(k))
            except (TypeError, ValueError):
                continue
            if 0.5 <= m <= 20 and px > 10:
                ratios.append(m / px)
    if len(ratios) < 2:
        return None
    mpp = statistics.median(ratios)
    lo, hi = _PLAUSIBLE_IMAGE_W_M
    return mpp if lo <= img_w * mpp <= hi else None


def _equiv_size(r: dict, img_w: int, img_h: int) -> tuple[float, float]:
    """等面積矩形的寬深（像素）：沿用外框長寬比、面積等於切出的多邊形。
    房間形狀含門口、凹處時外框會撐大，直接用外框寬深會高估房間尺寸。"""
    bw, bh = r["w"] * img_w, r["h"] * img_h
    area = _poly_area(r["polygon"]) * img_w * img_h
    if bw <= 0 or bh <= 0 or area <= 0:
        return bw, bh
    k = math.sqrt(area / (bw * bh))
    return bw * k, bh * k


def _poly_area(points: list[list[float]]) -> float:
    s = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


def _plan_type(room: dict) -> str:
    """整層流程用的房型：支援的五種照用，浴室／陽台用 space_type，其他一律 other。"""
    if room.get("room_type") in _TYPE_LABELS and room["room_type"] not in ("bathroom", "balcony"):
        return room["room_type"]
    st = room.get("space_type")
    return st if st in ("bathroom", "balcony") else "other"


# ── 像素外框 → 彼此貼齊的公尺矩形 ──────────────────────────────────────────────

def _cluster(values: list[float], tol: float) -> dict[float, float]:
    """一維分群：排序後相鄰差距 ≤ tol 的併成一群，群內都換成平均值（取到 1 cm）。
    ponytail: 單連結，一長串等距的邊會被併成同一群；住宅牆線稀疏，目前沒遇過。"""
    out: dict[float, float] = {}
    group: list[float] = []

    def flush() -> None:
        mean = round(sum(group) / len(group), 2)
        out.update({g: mean for g in group})

    for v in sorted(set(values)):
        if group and v - group[-1] > tol:
            flush()
            group = []
        group.append(v)
    if group:
        flush()
    return out


def _snap_rects(boxes: list[tuple[float, float, float, float]]) -> list[Rect]:
    """(x, y, w, h) 公尺 → 邊界吸附後的 Rect。相鄰房間的牆線落在同一個座標，
    roomplan 才認得出共用牆；牆線誤差 _SNAP_TOL_M 內都併成一條。"""
    ends = [(x, y, x + w, y + h) for x, y, w, h in boxes]
    xs = _cluster([e[0] for e in ends] + [e[2] for e in ends], _SNAP_TOL_M)
    ys = _cluster([e[1] for e in ends] + [e[3] for e in ends], _SNAP_TOL_M)
    return [Rect(xs[x0], ys[y0], xs[x1] - xs[x0], ys[y1] - ys[y0]) for x0, y0, x1, y1 in ends]


def _trim_overlaps(rects: list[Rect]) -> None:
    """兩間房的外框重疊（L 型房的外框常撐進隔壁）：把較小的那間沿重疊較淺的軸往後縮，
    縮到剛好貼著對方的邊。縮完會小於下限就不動，寧可留著重疊也不做出細縫。"""
    for _ in range(len(rects)):
        changed = False
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                ox = min(a.right, b.right) - max(a.x, b.x)
                oy = min(a.bottom, b.bottom) - max(a.y, b.y)
                if ox <= 1e-6 or oy <= 1e-6:
                    continue
                small, big = (a, b) if a.area <= b.area else (b, a)
                if ox <= oy:
                    if small.x + small.w / 2 < big.x + big.w / 2:
                        lo, hi = small.x, big.x
                    else:
                        lo, hi = big.right, small.right
                    if hi - lo < _MIN_DIM_M:
                        continue
                    small.x, small.w = lo, hi - lo
                else:
                    if small.y + small.h / 2 < big.y + big.h / 2:
                        lo, hi = small.y, big.y
                    else:
                        lo, hi = big.bottom, small.bottom
                    if hi - lo < _MIN_DIM_M:
                        continue
                    small.y, small.h = lo, hi - lo
                changed = True
        if not changed:
            return


def _normalize(rects: list[Rect]) -> tuple[list[Rect], float, float]:
    """原點平移到最左上的房間、座標取到 1 cm，回傳 (矩形, 整體寬, 整體深)。
    先各自取整再算寬深：共用牆的兩側才會是同一個數字（roomplan 用誤差 1e-6 判斷）。"""
    ox, oy = min(r.x for r in rects), min(r.y for r in rects)
    out = []
    for r in rects:
        x0, y0 = round(r.x - ox, 2), round(r.y - oy, 2)
        x1, y1 = round(r.right - ox, 2), round(r.bottom - oy, 2)
        out.append(Rect(x0, y0, round(x1 - x0, 2), round(y1 - y0, 2)))
    return out, max(r.right for r in out), max(r.bottom for r in out)


# ── 門窗：請 Gemini 讀圖上畫的位置，貼到吸附後的房間邊上 ─────────────────────────

_SIDES = ("top", "bottom", "left", "right")


def _detect_openings(image_path: str, rooms: list[dict]) -> list[dict]:
    """逐個門窗回 {kind, rooms:[字母], side, center, span, width_m}。
    只問「在哪間房的哪一側、沿那一側的位置比例」，不問像素座標——Gemini 標像素位置不準，
    但說得出門窗在哪面牆的哪一段；真正的座標由吸附後的房間邊算出來。失敗回空串列。"""
    from designbridge.layout.floorplan_parse import _mark_rooms_image, _parse_llm_layout
    from designbridge.render.llm import call_llm

    key = Path(image_path).read_bytes() + json.dumps([r["polygon"] for r in rooms]).encode()
    cache = _SCALE_CACHE_DIR / f"{hashlib.sha256(key).hexdigest()[:32]}_openings_v1.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    prompt = (
        "Image 1 is an architectural floor plan. Image 2 is the same plan with each region shaded "
        "and marked with a RED LETTER in a white circle.\n"
        "List every WINDOW and DOOR drawn in the walls of these regions. For each give:\n"
        '- "kind": "window", "door" (between two spaces) or "entry" (the unit\'s main entrance).\n'
        '- "rooms": region letters it belongs to. Door between two marked regions: both letters, '
        "the FIRST one is the region whose side you describe. Window or entry: one letter.\n"
        '- "side": which side of the FIRST region the opening is on, as drawn: top, bottom, left or right.\n'
        '- "center": position along that side, 0..1 (left to right for top/bottom, top to bottom '
        "for left/right).\n"
        '- "span": the opening width as a fraction of that side\'s length (0..1).\n'
        '- "width_m": the width in METERS only if a dimension is written for it, else null.\n'
        'Return STRICT JSON only: {"openings":[{"kind":"window","rooms":["A"],"side":"top",'
        '"center":0.5,"span":0.4,"width_m":null}]}'
    )
    try:
        text = call_llm(prompt, images=[image_path, _mark_rooms_image(image_path, rooms)],
                        json_mode=True, max_tokens=6000)
        raw = ((_parse_llm_layout(text) or {}).get("openings")) or []
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Gemini plan openings failed: {e}")
        return []
    try:
        _SCALE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return raw


def _openings_from_spec(
    spec: list[dict], rooms: list[RoomInstance], letters: dict[str, str]
) -> tuple[list[DoorOpening], list[WindowOpening]]:
    """spec（字母＋側＋比例）→ 貼在房間矩形邊上的門窗。字母對不上、側或比例不合法的整筆略過。"""
    by_id = {r.id: r for r in rooms}
    doors: list[DoorOpening] = []
    windows: list[WindowOpening] = []
    for s in spec:
        try:
            ids = [letters[str(L).strip().upper()] for L in (s.get("rooms") or [])]
            side, center = str(s.get("side")).lower(), float(s.get("center"))
            span = float(s.get("span") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if not ids or side not in _SIDES or not 0 <= center <= 1:
            continue
        room = by_id[ids[0]]
        r = room.rect
        horizontal = side in ("top", "bottom")
        length = r.w if horizontal else r.h
        try:
            width = float(s.get("width_m"))
        except (TypeError, ValueError):
            width = span * length
        kind = s.get("kind")
        lo, hi = (0.4, 3.0) if kind == "window" else (0.7, 1.2)
        width = round(min(max(width, lo), length * 0.9), 2)
        if horizontal:
            x, y = r.x + center * r.w, (r.y if side == "top" else r.bottom)
        else:
            x, y = (r.x if side == "left" else r.right), r.y + center * r.h
        orient = "horizontal" if horizontal else "vertical"
        if kind == "window":
            windows.append(WindowOpening(id=f"window_{len(windows)}", room_id=room.id,
                                         orientation=orient, x=x, y=y, width_m=width))
        elif kind in ("door", "entry"):
            pair = ids[:2] if kind == "door" else ids[:1]
            swing = min((by_id[i] for i in pair), key=lambda q: q.rect.area).id
            doors.append(DoorOpening(
                id="door_entry" if kind == "entry" else f"door_int_{len(doors)}",
                kind="entry" if kind == "entry" else "interior", room_ids=pair,
                orientation=orient, x=x, y=y, width_m=width, swing_into_room_id=swing,
            ))
    return doors, windows


def _specs(rooms: list[RoomInstance], walls, doors, windows) -> dict[str, list[dict]]:
    """給前端的尺寸明細：每間房、每面牆、每個門窗的公尺規格。"""
    name = {r.id: r.label_zh for r in rooms}
    return {
        "rooms": [{
            "id": r.id, "label": r.label_zh, "w_m": round(r.rect.w, 2), "d_m": round(r.rect.h, 2),
            "area_m2": round(r.actual_area_m2, 2), "area_ping": round(r.actual_area_m2 / PING_TO_M2, 2),
        } for r in rooms],
        "walls": [{
            "id": w.id, "kind": w.kind,
            "length_m": round(math.hypot(w.x2 - w.x1, w.y2 - w.y1), 2), "thickness_m": w.thickness_m,
            "rooms": [name.get(i, i) for i in w.room_ids],
        } for w in walls],
        "windows": [{"id": w.id, "room": name.get(w.room_id, w.room_id), "width_m": w.width_m} for w in windows],
        "doors": [{
            "id": d.id, "kind": d.kind, "rooms": [name.get(i, i) for i in d.room_ids], "width_m": d.width_m,
        } for d in doors],
    }


# ── 組成整層流程格式 ──────────────────────────────────────────────────────────

def _assemble(
    image_path: str, metas: list[dict], rects: list[Rect], scale_source: str,
    make_openings=None, openings_source: str = "inferred",
) -> dict[str, Any]:
    """metas[i] 是第 i 間房的非幾何資料（id、房型、名稱、多邊形…），rects[i] 是它的公尺矩形。
    make_openings(rooms) 回 (doors, windows)；沒給或結果是空的就用 roomplan 依相鄰關係推估。"""
    rects, bw, bd = _normalize(rects)
    rooms = [
        RoomInstance(
            id=m["id"], room_type=m["room_type"], rect=rc,
            target_area_m2=m["target_area_m2"], actual_area_m2=rc.area,
            label_zh=m["label_zh"], label_en=m["room_type"].upper(),
        )
        for m, rc in zip(metas, rects)
    ]
    walls, derived_doors, derived_windows = derive_walls_and_openings(rooms, bw, bd)
    doors, windows = make_openings(rooms) if make_openings else ([], [])
    if not doors and not windows:
        doors, windows, openings_source = derived_doors, derived_windows, "inferred"
    total_m2 = sum(r.actual_area_m2 for r in rooms)
    svg_markup = render_room_plan_svg(rooms, walls, doors, windows, bw, bd, total_m2)

    out_dir = Path(Config.ARTIFACTS_DIR) / "room_plan"
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / f"upload_{uuid.uuid4()}.svg"
    svg_path.write_text(svg_markup, encoding="utf-8")

    warnings = [
        "門與窗是 AI 從圖上辨識的位置，可能有偏差，實際以原圖為準" if openings_source == "detected"
        else "圖上的門窗沒辨識出來，位置是依房間相鄰關係推估的，實際以原圖為準"
    ]
    if scale_source == "assumed":
        warnings.insert(0, "平面圖沒有可讀的尺寸標註，房間尺寸為估計值，可輸入總坪數校正")
    return {
        "source": "upload",
        "plan_kind": "whole_floor" if len(rooms) > 1 else "single_room",
        "image_path": image_path,
        "scale_source": scale_source,
        "openings_source": openings_source,
        "specs": _specs(rooms, walls, doors, windows),
        "total_m2": round(total_m2, 1),
        "total_ping": round(total_m2 / PING_TO_M2, 1),
        "bounding_w_m": bw,
        "bounding_d_m": bd,
        "rooms": [
            {**r.to_dict(), **{k: m[k] for k in ("polygon", "anchor", "bbox_norm")}}
            for r, m in zip(rooms, metas)
        ],
        "walls": [w.to_dict() for w in walls],
        "doors": [d.to_dict() for d in doors],
        "windows": [w.to_dict() for w in windows],
        "svg_path": str(svg_path),
        "svg_markup": svg_markup,
        "warnings": warnings,
    }


def build_upload_plan(image_path: str, rooms: list[dict], total_ping: float | None = None) -> dict[str, Any]:
    """detect_rooms_in_floor_plan 的結果 → 整層流程的 cadPlanResult 格式（不含 svg_url，由路由補）。

    比例尺優先序：使用者給的坪數 > 圖上讀到的尺寸標註 > 假設一般住宅面積。"""
    with Image.open(image_path) as im:
        img_w, img_h = im.size
    # 牆線切割失敗退回方框偵測時沒有輪廓：用方框當輪廓，照樣轉成整層平面圖
    from_boxes = any(not r.get("polygon") for r in rooms)
    rooms = [
        r if r.get("polygon") else {
            **r,
            "polygon": [[r["x"], r["y"]], [r["x"] + r["w"], r["y"]],
                        [r["x"] + r["w"], r["y"] + r["h"]], [r["x"], r["y"] + r["h"]]],
            "anchor": [r["x"] + r["w"] / 2, r["y"] + r["h"] / 2],
        }
        for r in rooms
    ]
    px_area = sum(_poly_area(r["polygon"]) for r in rooms) * img_w * img_h

    def from_total(total_m2: float) -> float:
        return math.sqrt(total_m2 / px_area) if px_area else 0.01

    if total_ping and total_ping > 0:
        mpp, scale_source = from_total(total_ping * PING_TO_M2), "user"
    else:
        mpp = _scale_from_rooms(image_path, rooms, img_w, img_h)
        scale_source = "dimension"
        if mpp is None:
            mpp, scale_source = from_total(_ASSUMED_TOTAL_M2), "assumed"

    metas: list[dict] = []
    boxes: list[tuple[float, float, float, float]] = []
    unnamed = 0
    for r in rooms:
        ptype = _plan_type(r)
        label = r.get("label") or _TYPE_LABELS.get(r.get("room_type")) or _TYPE_LABELS.get(r.get("space_type"))
        if not label:
            unnamed += 1
            label = f"房間{unnamed}"
        metas.append({
            "id": r["id"], "room_type": ptype, "label_zh": label,
            "target_area_m2": _poly_area(r["polygon"]) * img_w * img_h * mpp * mpp,
            "polygon": r["polygon"], "anchor": r["anchor"],
            "bbox_norm": {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]},
        })
        boxes.append((r["x"] * img_w * mpp, r["y"] * img_h * mpp, r["w"] * img_w * mpp, r["h"] * img_h * mpp))

    rects = _snap_rects(boxes)
    _trim_overlaps(rects)

    from designbridge.layout.floorplan_parse import _mark
    letters = {_mark(i): m["id"] for i, m in enumerate(metas, 1)}
    spec = _detect_openings(image_path, rooms)
    plan = _assemble(
        image_path, metas, rects, scale_source,
        make_openings=lambda rs: _openings_from_spec(spec, rs, letters), openings_source="detected",
    )
    if from_boxes:
        plan["warnings"].insert(0, "圖片線條不夠清楚（例如翻拍或歪斜），房間範圍是 AI 框出來的，可能不準；建議上傳正面、清晰的平面圖")
    return plan


def rescale_upload_plan(plan: dict[str, Any], total_ping: float) -> dict[str, Any]:
    """使用者輸入總坪數後重算：整張平面圖等比例放大縮小到該坪數，不必重跑房間辨識。"""
    old_m2 = sum(r["w"] * r["h"] for r in plan["rooms"])
    if old_m2 <= 0 or total_ping <= 0:
        raise ValueError("坪數必須大於 0")
    k = math.sqrt(total_ping * PING_TO_M2 / old_m2)
    metas = [
        {
            "id": r["id"], "room_type": r["room_type"], "label_zh": r["label_zh"],
            "target_area_m2": r["target_area_m2"] * k * k,
            "polygon": r["polygon"], "anchor": r["anchor"], "bbox_norm": r["bbox_norm"],
        }
        for r in plan["rooms"]
    ]
    rects = [Rect(r["x"] * k, r["y"] * k, r["w"] * k, r["h"] * k) for r in plan["rooms"]]

    def scaled(rs):
        # 門窗座標跟房間用同一個原點（偵測時已平移過），等比例放大即可
        def s(d, keys=("x", "y", "width_m")):
            return {**d, **{key: d[key] * k for key in keys}}
        return ([DoorOpening(**s(d)) for d in plan["doors"]], [WindowOpening(**s(w)) for w in plan["windows"]])

    return _assemble(plan["image_path"], metas, rects, "user", make_openings=scaled,
                     openings_source=plan.get("openings_source", "inferred"))
