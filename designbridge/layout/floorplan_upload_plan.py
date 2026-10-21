"""把上傳平面圖切出的房間轉成整層流程（CAD 房型生成）同格式的資料，讓上傳的整戶圖也能走
整層進度、總覽、批次套用風格、存雲端。

整層流程以公尺為單位，上傳的圖只有像素：比例尺請 Gemini 逐間讀尺寸標註、除以切割出的
像素寬深換算，讀不到才用一般住宅面積估。整層 SVG 以平面圖為底圖（內嵌，雲端還原時不依賴本機網址），每間房畫成
可點的多邊形；多邊形同時帶外框 x/y/width/height，前端縮圖讀座標的邏輯不用改。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import uuid
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image

from designbridge.core.config import Config

_SCALE_CACHE_DIR = Path("artifacts/cache/room_seeds")
_SCALE_PROMPT_VERSION = "v2"
# 讀不到尺寸標註時假設整戶室內面積（一般台灣住宅約 25 坪）
_ASSUMED_TOTAL_M2 = 85.0
# 比例尺合理範圍：整張圖寬換算後應落在這個公尺區間，否則視為讀錯
_PLAUSIBLE_IMAGE_W_M = (4.0, 80.0)
_SVG_MAX_SIDE = 1600
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


def _embedded_image(image_path: str) -> tuple[str, int, int]:
    """縮到長邊 _SVG_MAX_SIDE 的 JPEG data URI，SVG 自帶底圖，雲端還原時不用另外找圖。"""
    im = Image.open(image_path).convert("RGB")
    scale = min(1.0, _SVG_MAX_SIDE / max(im.size))
    if scale < 1:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), im.width, im.height


def _svg(image_path: str, rooms: list[dict]) -> str:
    href, W, H = _embedded_image(image_path)
    font = max(14, round(H / 45))
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        f'<image href="{href}" x="0" y="0" width="{W}" height="{H}" preserveAspectRatio="none"/>',
    ]
    for r in rooms:
        pts = " ".join(f"{x * W:.1f},{y * H:.1f}" for x, y in r["polygon"])
        b = r["bbox_norm"]
        # 多邊形帶外框座標：前端縮圖用 .room-floor 的 x/y/width/height 算視窗、畫家具
        out.append(f'<g class="room-rect" data-room-id="{r["id"]}" data-room-type="{r["room_type"]}">')
        out.append(
            f'<polygon class="room-floor" points="{pts}" '
            f'x="{b["x"] * W:.1f}" y="{b["y"] * H:.1f}" width="{b["w"] * W:.1f}" height="{b["h"] * H:.1f}" '
            f'fill="#f3eee6" fill-opacity="0.45" stroke="#8a7f70" stroke-width="2"/>'
        )
        ax, ay = r["anchor"]
        out.append(
            f'<text x="{ax * W:.1f}" y="{ay * H:.1f}" font-size="{font}" font-weight="600" '
            f'text-anchor="middle" dominant-baseline="central" fill="#111" stroke="white" '
            f'stroke-width="{font / 4:.1f}" paint-order="stroke" pointer-events="none">'
            f'{escape(r["label_zh"])}</text>'
        )
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def build_upload_plan(image_path: str, rooms: list[dict]) -> dict[str, Any]:
    """detect_rooms_in_floor_plan 的結果 → 整層流程的 cadPlanResult 格式（不含 svg_url，由路由補）。"""
    with Image.open(image_path) as im:
        img_w, img_h = im.size

    mpp = _scale_from_rooms(image_path, rooms, img_w, img_h)
    scale_source = "dimension"
    if mpp is None:
        px_area = sum(_poly_area(r["polygon"]) for r in rooms) * img_w * img_h
        mpp = math.sqrt(_ASSUMED_TOTAL_M2 / px_area) if px_area else 0.01
        scale_source = "assumed"

    plan_rooms: list[dict] = []
    unnamed = 0
    for r in rooms:
        ptype = _plan_type(r)
        label = r.get("label") or _TYPE_LABELS.get(r.get("room_type")) or _TYPE_LABELS.get(r.get("space_type"))
        if not label:
            unnamed += 1
            label = f"房間{unnamed}"
        area = _poly_area(r["polygon"]) * img_w * img_h * mpp * mpp
        ew, eh = _equiv_size(r, img_w, img_h)
        plan_rooms.append({
            "id": r["id"],
            "room_type": ptype,
            "label_zh": label,
            "label_en": ptype.upper(),
            "x": round(r["x"] * img_w * mpp, 3),
            "y": round(r["y"] * img_h * mpp, 3),
            # 單房編輯器用的房間寬深：等面積矩形，x/y 仍是外框左上角
            "w": round(ew * mpp, 3),
            "h": round(eh * mpp, 3),
            "target_area_m2": round(area, 2),
            "actual_area_m2": round(area, 2),
            "polygon": r["polygon"],
            "anchor": r["anchor"],
            "bbox_norm": {"x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]},
        })

    svg_markup = _svg(image_path, plan_rooms)
    out_dir = Path(Config.ARTIFACTS_DIR) / "room_plan"
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / f"upload_{uuid.uuid4()}.svg"
    svg_path.write_text(svg_markup, encoding="utf-8")

    total_m2 = sum(r["actual_area_m2"] for r in plan_rooms)
    return {
        "source": "upload",
        "image_path": image_path,
        "scale_source": scale_source,
        "total_m2": round(total_m2, 1),
        "total_ping": round(total_m2 / 3.306, 1),
        "bounding_w_m": round(img_w * mpp, 3),
        "bounding_d_m": round(img_h * mpp, 3),
        "rooms": plan_rooms,
        "walls": [], "doors": [], "windows": [],
        "svg_path": str(svg_path),
        "svg_markup": svg_markup,
        "warnings": ["平面圖沒有可讀的尺寸標註，房間尺寸為估計值"] if scale_source == "assumed" else [],
    }
