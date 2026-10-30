"""Parse an uploaded floor-plan image / detect rooms (Gemini vision)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from designbridge.layout.layout_items import FURNITURE_SIZES, FurnitureItem, _parse_llm_layout
from designbridge.layout.layout_enforce import _clip_to_room
from designbridge.layout.floorplan_render import _generate_floor_plan


# ───────────────────── Parse an uploaded floor-plan image ─────────────────────

# Vocabulary we constrain Gemini to, so parsed types line up with FURNITURE_SIZES,
# heights, semantic shapes and floor-plan colors downstream.
_KNOWN_FURNITURE_TYPES = sorted(k for k in FURNITURE_SIZES if k != "default")


def _box_to_xywh(obj: dict) -> tuple[float, float, float, float] | None:
    """box_2d [ymin, xmin, ymax, xmax]（0–1000）→ 正規化 (x, y, w, h)。
    Gemini 的偵測訓練就是這個格式，比要它直接吐 0–1 的 xywh 準。
    缺 box_2d 時退回舊的 x/y/w/h 欄位，避免模型偶爾不照格式就整筆丟掉。"""
    box = obj.get("box_2d")
    if isinstance(box, (list, tuple)) and len(box) == 4:
        try:
            ymin, xmin, ymax, xmax = (float(v) / 1000.0 for v in box)
        except (TypeError, ValueError):
            return None
        x0, x1 = sorted((xmin, xmax))
        y0, y1 = sorted((ymin, ymax))
        return x0, y0, x1 - x0, y1 - y0
    if "x" in obj and "y" in obj:
        try:
            return (float(obj["x"]), float(obj["y"]),
                    float(obj.get("w") or 0.0), float(obj.get("h") or 0.0))
        except (TypeError, ValueError):
            return None
    return None


_SALVAGE_RE = re.compile(
    r'(?<!\w)"?(?:room_type|type)"\s*:\s*"([^"]+)"\s*,\s*"box_2d"\s*:\s*\[([^\]]*)\]'
)


def _salvage_boxes(text: str, type_key: str) -> list[dict]:
    """Gemini 偶爾吐出缺括號的壞 JSON（實測整戶圖 15 間房從第 5 筆起少了 `{"`），
    整包 json.loads 失敗時逐筆撈 type + box_2d。"""
    out = []
    for t, box in _SALVAGE_RE.findall(text or ""):
        try:
            vals = [float(v) for v in box.split(",")]
        except ValueError:
            continue
        if len(vals) == 4:
            out.append({type_key: t, "box_2d": vals})
    return out


def parse_floor_plan_image(
    image_path: str,
    task_id: str,
    room_type: str = "living_room",
    room_w: float = 5.0,
    room_d: float = 4.0,
) -> dict[str, Any] | None:
    """Read furniture from a user-uploaded 2D floor-plan image via Gemini vision.

    Returns a scene_graph (furniture_placements + a re-rendered floor-plan PNG using
    the same coordinate system as the AI-generated layouts), so an uploaded plan can
    drive the SAME accurate layout-projection render path — and be edited in the 2D
    editor — instead of the weaker "raw image as Kontext guide" fallback.

    Returns ``None`` when parsing fails or finds nothing (caller then falls back).
    """
    from designbridge.render.llm import call_llm

    types_csv = ", ".join(_KNOWN_FURNITURE_TYPES)
    prompt = (
        "You are given a 2D top-down interior FLOOR PLAN image. Identify every piece "
        "of furniture drawn in it and return each one's footprint as a bounding box.\n"
        "Use `box_2d` = [ymin, xmin, ymax, xmax], integers normalized to 0-1000, "
        "measured relative to the room interior: x = 0 is the left wall, 1000 is the "
        "right wall; y = 0 is the back/top wall, 1000 is the front/bottom wall.\n"
        f"Use ONLY these furniture type keywords (map synonyms to the closest one): "
        f"{types_csv}. Skip any symbol you cannot confidently classify.\n"
        "Return STRICT JSON only, no prose, no markdown fences:\n"
        '{"furniture":[{"type":"sofa","box_2d":[300,50,430,350]}]}'
    )

    try:
        # ponytail: bounds worst-case latency/cost — observed avg is ~2.3-2.7k tokens
        # (ablation 4.4), a runaway repetition loop with no cap ran to the 32k platform
        # ceiling (308s, see ablation 4.3b). 4000 truncated dense plans (30+ items); 8000
        # still bounds the worst case while giving them room.
        text = call_llm(prompt, images=[image_path], json_mode=True, max_tokens=8000)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Gemini floor-plan parse failed: {e}")
        return None

    data = _parse_llm_layout(text)
    raw = (data or {}).get("furniture") or _salvage_boxes(text, "type")
    if not raw:
        print("⚠️  Gemini floor-plan parse returned no furniture")
        return None

    items: list[FurnitureItem] = []
    for i, f in enumerate(raw):
        ftype = str(f.get("type", "default")).lower().replace(" ", "_")
        if ftype not in FURNITURE_SIZES:
            ftype = "default"
        dw, dh = FURNITURE_SIZES.get(ftype, FURNITURE_SIZES["default"])
        xywh = _box_to_xywh(f)
        if xywh is None:
            continue
        x, y, w, h = xywh
        w = w or dw
        h = h or dh
        items.append(
            FurnitureItem(
                id=f"{ftype}_{i + 1}",
                type=ftype,
                x=max(0.0, min(0.98, x)),
                y=max(0.0, min(0.98, y)),
                w=max(0.02, min(1.0, w)),
                h=max(0.02, min(1.0, h)),
                rotation=float(f.get("rotation", 0) or 0),
            )
        )

    if not items:
        return None

    items = _clip_to_room(items)
    floor_plan_path = _generate_floor_plan(
        items, task_id, room_type=room_type, room_w=room_w, room_d=room_d
    )
    print(f"[parse_floor_plan] Gemini parsed {len(items)} items from uploaded plan")

    return {
        "furniture_placements": [it.to_dict() for it in items],
        "layout_prompt": "",
        "floor_plan_path": floor_plan_path,
        "room_w": room_w,
        "room_d": room_d,
        "source": "uploaded_plan_parsed",
    }


# Room types DesignBridge actually knows how to furnish/render (kept in sync with
# _ROOM_LABEL_MAP below and frontend/src/config/furniture.js ROOM_OPTIONS).
_KNOWN_ROOM_TYPES = ("living_room", "bedroom", "kitchen", "dining_room", "study")


def _normalize_room_type(value: Any) -> str:
    room_type = str(value or "other").lower().replace(" ", "_")
    return room_type if room_type in _KNOWN_ROOM_TYPES else "other"


def detect_rooms_in_floor_plan(image_path: str) -> list[dict] | None:
    """Find every distinct room/space in a (possibly whole-unit) floor-plan image,
    so the caller can let the user pick one room before running it through
    :func:`parse_floor_plan_image`.

    Returns a list of ``{id, room_type, x, y, w, h}`` (normalized, top-left origin);
    the segmentation path also adds ``label`` (room name as written on the plan) and
    ``polygon`` (``[[x, y], ...]``). Unsupported spaces come back as ``"other"``.
    Returns ``None`` on failure (caller treats the whole image as a single room).
    """
    rooms = _detect_rooms_by_segmentation(image_path)
    if rooms:
        return rooms
    print("⚠️  room segmentation failed, falling back to Gemini bounding boxes")
    return _detect_rooms_by_boxes(image_path)


# 家具面板認得、但佈局引擎還不支援的空間；只用來預選家具清單，room_type 仍是 other
_EXTRA_SPACE_TYPES = ("bathroom", "balcony")
# 動線空間（玄關、走廊、走道）：切割時保留自己的範圍、不讓隔壁房間吃掉，但不輸出成房間
_CIRCULATION = "circulation"
_CIRCULATION_WORDS = ("玄關", "走廊", "走道", "過道", "通道", "廊道", "門廳", "入口")
# 不收單獨的 hall：living hall 是客廳
_CIRCULATION_WORDS_EN = ("entrance", "entry", "foyer", "corridor", "hallway", "passage")
# 改了提示詞就換版本號，舊快取自動失效
_SEED_PROMPT_VERSION = "v3"
_SEED_CACHE_DIR = Path("artifacts/cache/room_seeds")
# 逐區辨識的提示詞版本（快取檔名用）；改了逐區辨識的提示詞就換
_LABEL_PROMPT_VERSION = "v4"
# 合併被切開的同一間房時，小塊面積上限（相對大塊）
_MERGE_MAX_RATIO = 0.35
# 逐區辨識平行問幾次取多數
_LABEL_VOTES = 3


def _room_seed_prompt() -> str:
    types_csv = ", ".join(_KNOWN_ROOM_TYPES + _EXTRA_SPACE_TYPES)
    return (
        "You are given a 2D architectural FLOOR PLAN, which may show a single room or a "
        "whole multi-room unit. List every distinct room or space INSIDE the exterior "
        "walls, including bathrooms, toilets, balconies, entrance and kitchen. Entry "
        "arrows, door swings and labels outside the exterior walls are NOT rooms.\n"
        "For each, give `point` = [y, x], integers 0-1000 relative to the whole image, "
        "placed near the CENTER of that room's open floor area (not on furniture, walls "
        "or the edge of the room).\n"
        "`label` = the room name exactly as written on the drawing; use an empty string "
        "if no name is written for that room. Do not invent names.\n"
        f"`room_type` = one of {types_csv}, \"circulation\" for an entrance/foyer, "
        "corridor or hallway, or \"other\" for anything else. When no "
        "name is written, infer it from fixtures (bed → bedroom, toilet/bathtub → "
        "bathroom, stove/sink counter → kitchen).\n"
        "A bay window (凸窗: an angled or boxed window bump on an exterior wall) belongs to "
        "the room it opens from — that room is usually a bedroom or living room, NOT a "
        "balcony. A balcony is a separate strip outside the main exterior wall line, "
        "reached through a door, often with railings, plants, laundry or a washer.\n"
        "Ignore the title block, legend and anything outside the building.\n"
        "Return STRICT JSON only, no prose, no markdown fences:\n"
        '{"rooms":[{"label":"主臥室","room_type":"bedroom","point":[360,220]}]}'
    )


def _room_seeds(image_path: str) -> list[dict] | None:
    """向 Gemini 要每間房的點；同一張圖用內容雜湊快取，重複上傳時分割結果才一致。"""
    import hashlib
    import json

    from designbridge.render.llm import call_llm

    digest = hashlib.sha256(Path(image_path).read_bytes()).hexdigest()[:32]
    cache = _SEED_CACHE_DIR / f"{digest}_{_SEED_PROMPT_VERSION}.json"
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    try:
        text = call_llm(_room_seed_prompt(), images=[image_path], json_mode=True, max_tokens=4000)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Gemini room points failed: {e}")
        return None
    seeds = ((_parse_llm_layout(text) or {}).get("rooms")) or []
    seeds = [s for s in seeds if isinstance(s, dict) and isinstance(s.get("point"), list)]
    if not seeds:
        return None
    try:
        _SEED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(seeds, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return seeds


def _apply_type(target: dict, raw_type: Any) -> None:
    raw = str(raw_type or "other").lower().replace(" ", "_")
    target["room_type"] = _normalize_room_type(raw)
    target["space_type"] = raw if raw in _KNOWN_ROOM_TYPES + _EXTRA_SPACE_TYPES + (_CIRCULATION,) else "other"


def _is_circulation(room: dict) -> bool:
    """玄關、走廊、走道這類動線空間：類型被判成 circulation，或圖上寫的房名有對應字眼。"""
    if room.get("space_type") == _CIRCULATION:
        return True
    label = str(room.get("label") or "")
    low = label.lower()
    return any(w in label for w in _CIRCULATION_WORDS) or any(
        w in low.replace("-", " ").split() for w in _CIRCULATION_WORDS_EN)


def _detect_rooms_by_segmentation(image_path: str) -> list[dict] | None:
    """Gemini 只給每間房的中心點和房名，邊界交給 floorplan_segment 從牆線算；
    切完再請 Gemini 看標號圖逐區確認類型與房名。"""
    from designbridge.layout.floorplan_segment import segment_rooms

    seeds = _room_seeds(image_path) or []  # Gemini 沒給點也照切，靠自動補種子
    for s in seeds:
        _apply_type(s, s.get("room_type"))
        s["label"] = str(s.get("label") or "").strip()
    try:
        rooms = segment_rooms(image_path, seeds)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  room segmentation error: {e}")
        return None
    if rooms:
        _relabel_rooms(image_path, rooms)
        # 動線空間切割時保有自己的範圍（隔壁房間不會吃進來），這裡才拿掉，那一塊就空著
        rooms = [r for r in rooms if not _is_circulation(r)]
        for i, r in enumerate(rooms, 1):
            r["id"] = f"room_{i}"
    return rooms or None


def _mark(i: int) -> str:
    """1→A … 26→Z, 27→AA。用字母不用數字：CAD 圖滿是尺寸數字，數字標記會被混淆。"""
    out = ""
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def _mark_rooms_image(image_path: str, rooms: list[dict]) -> bytes:
    """在平面圖上淡淡塗出每個區域並標上紅色大字母（set-of-mark），給 Gemini 逐區辨識。"""
    import io

    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(image_path).convert("RGB")
    scale = 1600 / max(im.size)
    im = im.resize((round(im.width * scale), round(im.height * scale)))
    W, H = im.size
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    palette = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180),
               (70, 240, 240), (240, 50, 230), (210, 245, 60), (0, 128, 128), (170, 110, 40)]
    for i, r in enumerate(rooms):
        c = palette[i % len(palette)]
        pts = [(x * W, y * H) for x, y in r["polygon"]]
        draw.polygon(pts, fill=c + (55,), outline=c + (255,), width=3)
    font = ImageFont.load_default(size=max(18, W // 45))
    for i, r in enumerate(rooms, 1):
        ax, ay = r["anchor"][0] * W, r["anchor"][1] * H
        rad = max(14, W // 70)
        draw.ellipse((ax - rad, ay - rad, ax + rad, ay + rad), fill=(255, 255, 255, 235),
                     outline=(0, 0, 0, 255), width=2)
        draw.text((ax, ay), _mark(i), fill=(200, 0, 0, 255), font=font, anchor="mm")
    out = Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _relabel_rooms(image_path: str, rooms: list[dict]) -> None:
    """第二次 Gemini：看標了字母的區域逐一回答類型，原地覆寫 rooms。
    逐區分類比要它給座標穩得多，也讓自動補出的區域（沒寫房名的廚房）拿到正確類型。
    只改第一輪沒讀到房名的區域：圖上有寫房名時第一輪就很準，逐區辨識反而會對錯號。
    失敗就保留第一輪的結果。"""
    if all(r.get("label") for r in rooms):
        return
    for r in rooms:
        r["written"] = bool(r.get("label"))  # 第一輪讀到房名 = 圖上有寫
    try:
        _relabel_unwritten(image_path, rooms)
    finally:
        for r in rooms:
            r.pop("written", None)


def _relabel_unwritten(image_path: str, rooms: list[dict]) -> None:
    import hashlib
    import json

    from designbridge.render.llm import call_llm

    digest = hashlib.sha256(
        Path(image_path).read_bytes() + json.dumps([r["polygon"] for r in rooms]).encode()
    ).hexdigest()[:32]
    cache = _SEED_CACHE_DIR / f"{digest}_labels_{_LABEL_PROMPT_VERSION}.json"
    answers = None
    if cache.is_file():
        try:
            answers = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            answers = None
    if answers is None:
        types_csv = ", ".join(_KNOWN_ROOM_TYPES + _EXTRA_SPACE_TYPES)
        prompt = (
            "Image 1 is an architectural floor plan. Image 2 is the same plan with each "
            "region shaded and marked with a RED LETTER in a white circle "
            f"({', '.join(_mark(i) for i in range(1, len(rooms) + 1))}). Black numbers on "
            "the drawing are dimensions, not marks.\n"
            "For EVERY letter, say what space that region is:\n"
            f"- `room_type`: one of {types_csv}, \"circulation\" for an entrance/foyer, corridor "
            "or hallway, or \"other\" (storage, closet, laundry...).\n"
            "- `label`: the room name written on the drawing inside that region, exactly "
            "as written; empty string if none is written. Do not invent names.\n"
            "Use fixtures to decide when nothing is written: bed → bedroom, toilet or "
            "bathtub → bathroom, stove or sink counter → kitchen, sofa/TV → living_room, "
            "dining table → dining_room, desk → study.\n"
            "A bay window (凸窗, an angled or boxed window bump) is part of the room it "
            "opens from and does not make that room a balcony. A balcony is a strip outside "
            "the main exterior wall, often with railings, plants, laundry or a washer.\n"
            "- `same_room_as`: if this region is NOT a room of its own but a small piece "
            "split off a neighbouring lettered region of the same room (a bay-window nook, "
            "an alcove, a sliver with no wall between them), give that neighbour's letter; "
            "otherwise null. Do not merge rooms that are separated by a wall and door.\n"
            "Return STRICT JSON only, no prose, no markdown fences:\n"
            '{"regions":[{"mark":"A","room_type":"bedroom","label":"","same_room_as":null}]}'
        )
        answers = _vote_regions(prompt, [image_path, _mark_rooms_image(image_path, rooms)])
        if not answers:
            return
        try:
            _SEED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    index = {_mark(i): i for i in range(1, len(rooms) + 1)}
    by_n: dict[int, dict] = {}
    for a in answers:
        n = index.get(str(a.get("mark") or "").strip().upper())
        if not n:
            continue
        by_n[n] = a
        room = rooms[n - 1]
        if room["written"]:
            continue  # 圖上有寫房名的保留第一輪結果
        _apply_type(room, a.get("room_type"))
        label = str(a.get("label") or "").strip()
        if label and not label.replace("x", "").replace("×", "").isdigit():
            room["label"] = label
    _merge_split_rooms(rooms, by_n, index)


def _vote_regions(prompt: str, images: list) -> list[dict]:
    """同一題平行問 _LABEL_VOTES 次，每個字母的類型、房名、same_room_as 各取多數。
    沒寫房名的區域（凸窗臥室像不像陽台）單次回答會搖擺。"""
    from collections import Counter
    from concurrent.futures import ThreadPoolExecutor

    from designbridge.render.llm import call_llm

    def ask(_):
        try:
            text = call_llm(prompt, images=images, json_mode=True, max_tokens=4000)
        except Exception as e:  # noqa: BLE001
            print(f"⚠️  Gemini region labeling failed: {e}")
            return []
        return ((_parse_llm_layout(text) or {}).get("regions")) or []

    with ThreadPoolExecutor(max_workers=_LABEL_VOTES) as pool:
        runs = list(pool.map(ask, range(_LABEL_VOTES)))
    votes: dict[str, dict[str, Counter]] = {}
    for run in runs:
        for a in run:
            mark = str(a.get("mark") or "").strip().upper()
            if not mark:
                continue
            v = votes.setdefault(mark, {k: Counter() for k in ("room_type", "label", "same_room_as")})
            for k in v:
                v[k][str(a.get(k) or "").strip()] += 1
    return [
        {"mark": m, **{k: (c.most_common(1)[0][0] or None) for k, c in v.items()}}
        for m, v in votes.items()
    ]


def _merge_split_rooms(rooms: list[dict], by_n: dict[int, dict], index: dict[str, int]) -> None:
    """依逐區辨識的 same_room_as 把被切開的同一間房合回去（凸窗角落、無牆的小塊）。
    只合兩邊都沒寫房名、且小塊面積不到大塊 _MERGE_MAX_RATIO 的：
    Gemini 偶爾會把隔著門的兩間房也判成同一間。"""
    from designbridge.layout.floorplan_segment import merge_room_shapes

    parent = list(range(len(rooms) + 1))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def area(r: dict) -> float:
        return r["w"] * r["h"]

    for n, a in by_n.items():
        m = index.get(str(a.get("same_room_as") or "").strip().upper())
        if not m or m == n:
            continue
        rn, rm = rooms[n - 1], rooms[m - 1]
        if rn.get("written") or rm.get("written"):
            continue
        small, big = sorted((area(rn), area(rm)))
        if big and small / big < _MERGE_MAX_RATIO:
            parent[find(n)] = find(m)

    groups: dict[int, list[int]] = {}
    for n in range(1, len(rooms) + 1):
        groups.setdefault(find(n), []).append(n)
    if all(len(g) == 1 for g in groups.values()):
        return

    merged: list[dict] = []
    for members in groups.values():
        group = [rooms[n - 1] for n in members]
        # 類型和房名跟著面積最大的那塊走
        main = dict(max(group, key=area))
        if len(group) > 1:
            main.update(merge_room_shapes(group))
        merged.append(main)
    merged.sort(key=lambda r: int(r["id"].split("_")[-1]))
    for i, r in enumerate(merged, 1):
        r["id"] = f"room_{i}"
    rooms[:] = merged


def _detect_rooms_by_boxes(image_path: str) -> list[dict] | None:
    """舊做法：Gemini 直接框房間。框較鬆，只在切割失敗時當備援。"""
    from designbridge.render.llm import call_llm

    types_csv = ", ".join(_KNOWN_ROOM_TYPES)
    prompt = (
        "You are given a 2D top-down FLOOR PLAN image, which may show a single room or "
        "a whole multi-room unit (apartment/house). Identify every distinct enclosed "
        "room or space and return each one's bounding box.\n"
        "Use `box_2d` = [ymin, xmin, ymax, xmax], integers normalized to 0-1000 "
        "relative to the whole image.\n"
        f"For `room_type`, use ONLY one of: {types_csv}. If a space clearly doesn't "
        "match any of these (e.g. bathroom, closet, corridor, balcony, entrance), use "
        '"other" and set `space_type` to "bathroom" or "balcony" when it is one, else "other".\n'
        "`label` is the room name written on the plan (copy it as is), or null if none. "
        "Boxes must hug the room's walls and must not overlap each other.\n"
        "Return STRICT JSON only, no prose, no markdown fences:\n"
        '{"rooms":[{"room_type":"bedroom","label":"臥室","box_2d":[50,50,450,400]}]}'
    )

    try:
        text = call_llm(prompt, images=[image_path], json_mode=True, max_tokens=8000)
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Gemini room detection failed: {e}")
        return None

    data = _parse_llm_layout(text)
    raw = (data or {}).get("rooms") or _salvage_boxes(text, "room_type")
    if not raw:
        print("⚠️  Gemini room detection returned no rooms")
        return None

    rooms: list[dict] = []
    for i, r in enumerate(raw):
        xywh = _box_to_xywh(r)
        if xywh is None:
            continue
        x, y, w, h = xywh
        room = {
            "id": f"room_{i + 1}",
            "room_type": _normalize_room_type(r.get("room_type")),
            "x": max(0.0, min(0.98, x)),
            "y": max(0.0, min(0.98, y)),
            "w": max(0.02, min(1.0, w)),
            "h": max(0.02, min(1.0, h)),
        }
        if str(r.get("space_type")) in _EXTRA_SPACE_TYPES:
            room["space_type"] = r["space_type"]
        if r.get("label"):
            room["label"] = str(r["label"]).strip()
        rooms.append(room)

    return rooms or None
