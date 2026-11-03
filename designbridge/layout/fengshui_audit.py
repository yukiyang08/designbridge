"""風水＋動線健檢：對一組已擺好的家具打分數，列出違規項目、白話理由與化解法。

與 special_constraints 的分工：那邊負責「排版時把家具推開」，這裡只讀不改
（`fix_layout` 例外，它就是把同一批 enforcer 套在使用者現有的擺法上）。
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any

from designbridge.layout.facing import screen_facing
from designbridge.layout.layout_items import FurnitureItem, _normalize_ftype
from designbridge.layout.special_constraints import (
    _ENFORCERS,
    _VERIFIERS,
    _WALL_OPPOSITE,
    _nearest_wall,
    _opening_span,
    _opening_wall,
    _wall_distance,
    load_constraint_cards,
)

# 跟 /api/generate-layout 的預設門窗一致：門在近牆中央、窗在遠牆中央
DEFAULT_DOORS = [{"x": 0.45, "y": 0.98, "w": 0.10, "h": 0.02, "wall": "near"}]
DEFAULT_WINDOWS = [{"x": 0.40, "y": 0.0, "w": 0.20, "h": 0.02, "wall": "far"}]

CATEGORY_LABELS = {
    "door": "門口沖煞",
    "backing": "背後有靠",
    "reflect": "鏡面與光線",
    "kitchen": "水火分離",
}

# 不擋路的家具：鋪在地上或掛在牆上
_NON_OBSTACLE = {"rug", "carpet", "mat", "doormat", "mirror"}
# 要走得到才有用的家具（床邊、沙發前、爐灶前…）
_NEEDS_ACCESS = {
    "bed", "bunk_bed", "sofa", "loveseat", "armchair", "desk", "chair", "dining_table",
    "wardrobe", "dresser", "bookshelf", "cabinet", "stove", "sink", "fridge", "toilet",
}
WALKWAY_M = 0.6          # 室內主要走道的常用下限
DOOR_CLEARANCE_M = 0.6   # 門口前要留的淨空深度
_CELL_M = 0.05
_FIX_PASSES = 5


def items_from_placements(placements: list[dict]) -> list[FurnitureItem]:
    items: list[FurnitureItem] = []
    for i, p in enumerate(placements or []):
        try:
            items.append(FurnitureItem(
                id=str(p.get("id") or f"item_{i}"),
                type=_normalize_ftype(str(p.get("type", "default"))),
                x=float(p.get("x", 0.0)), y=float(p.get("y", 0.0)),
                w=float(p.get("w", 0.1)), h=float(p.get("h", 0.1)),
                rotation=float(p.get("rotation", 0.0) or 0.0),
            ))
        except (TypeError, ValueError):
            continue
    return items


def rules_for_room(room_type: str | None) -> list[str]:
    """房型相關的規則；自訂房型對不上任何一條時全部視為相關（與前端選單同邏輯）。"""
    cards = load_constraint_cards()
    fengshui = [c for c in cards.values() if c.constraint_type == "fengshui"]
    hit = [c.trigger for c in fengshui if room_type and room_type in c.rooms]
    return hit or [c.trigger for c in fengshui]


def _applicable(card, types: set[str], doors: list, windows: list) -> str | None:
    """不適用時回傳原因，適用時回傳 None。"""
    if "door" in card.needs and not doors:
        return "沒有門"
    if "window" in card.needs and not windows:
        return "沒有窗"
    for group in card.requires:
        if not types & set(group):
            return "房裡沒有相關家具"
    return None


def audit_fengshui(
    items: list[FurnitureItem],
    doors: list[dict],
    windows: list[dict],
    rules: list[str] | None = None,
    room_type: str | None = None,
) -> dict[str, Any]:
    cards = load_constraint_cards()
    triggers = rules if rules is not None else rules_for_room(room_type)
    types = {it.type for it in items}

    results: list[dict[str, Any]] = []
    for card in sorted((cards[t] for t in triggers if t in cards), key=lambda c: (-c.severity, c.order)):
        entry = {
            "trigger": card.trigger,
            "label": card.label or card.description,
            "category": card.category,
            "category_label": CATEGORY_LABELS.get(card.category, ""),
            "severity": card.severity,
            "reason": card.reason,
            "remedy": card.remedy,
            "offenders": [],
        }
        skip = _applicable(card, types, doors, windows)
        if skip:
            entry.update(status="na", note=skip)
        else:
            offenders: list[str] = []
            for key in card.enforce:
                verifier = _VERIFIERS.get(key)
                if verifier:
                    offenders += verifier(items, doors, windows, card.parameters)
            entry.update(status="fail" if offenders else "pass", offenders=list(dict.fromkeys(offenders)))
        results.append(entry)

    applicable = [r for r in results if r["status"] != "na"]
    total = sum(r["severity"] for r in applicable)
    passed = sum(r["severity"] for r in applicable if r["status"] == "pass")
    return {
        "score": round(100 * passed / total) if total else None,
        "passed": sum(1 for r in applicable if r["status"] == "pass"),
        "failed": sum(1 for r in applicable if r["status"] == "fail"),
        "rules": results,
    }


# ── 動線 ──────────────────────────────────────────────────────────────────────

def _door_geometry(door: dict, room_w: float, room_d: float):
    """門的中心點（公尺）、往室內的單位向量、門寬（公尺）。"""
    wall = _opening_wall(door)
    lo, hi = _opening_span(door, wall)
    mid = (lo + hi) / 2.0
    if wall == "far":
        return (mid * room_w, 0.0), (0.0, 1.0), (hi - lo) * room_w
    if wall == "near":
        return (mid * room_w, room_d), (0.0, -1.0), (hi - lo) * room_w
    if wall == "left":
        return (0.0, mid * room_d), (1.0, 0.0), (hi - lo) * room_d
    return (room_w, mid * room_d), (-1.0, 0.0), (hi - lo) * room_d


def _rect_m(item: FurnitureItem, room_w: float, room_d: float) -> tuple[float, float, float, float]:
    return item.x * room_w, item.y * room_d, (item.x + item.w) * room_w, (item.y + item.h) * room_d


def _dist_to_rect(px: float, py: float, r: tuple[float, float, float, float]) -> float:
    dx = max(r[0] - px, 0.0, px - r[2])
    dy = max(r[1] - py, 0.0, py - r[3])
    return math.hypot(dx, dy)


def audit_circulation(
    items: list[FurnitureItem],
    doors: list[dict],
    room_w: float,
    room_d: float,
) -> dict[str, Any]:
    """在 5 cm 網格上從門口做 BFS：寬度不到 WALKWAY_M 的縫視為走不過去。"""
    if not doors:
        return {"score": None, "issues": [], "note": "沒有門，無法判斷動線"}

    obstacles = [it for it in items if it.type not in _NON_OBSTACLE]
    rects = {it.id: _rect_m(it, room_w, room_d) for it in obstacles}
    radius = WALKWAY_M / 2.0
    nx, ny = max(1, int(room_w / _CELL_M)), max(1, int(room_d / _CELL_M))

    def centre(ix: int, iy: int) -> tuple[float, float]:
        return (ix + 0.5) * _CELL_M, (iy + 0.5) * _CELL_M

    def free(ix: int, iy: int) -> bool:
        px, py = centre(ix, iy)
        if min(px, py, room_w - px, room_d - py) < radius:
            return False
        return all(_dist_to_rect(px, py, r) >= radius for r in rects.values())

    issues: list[dict[str, Any]] = []
    starts: list[tuple[int, int]] = []
    for door in doors:
        (cx, cy), (ux, uy), width = _door_geometry(door, room_w, room_d)
        # 門口淨空：門寬 × DOOR_CLEARANCE_M 的矩形內不能有家具
        half = max(width, 0.6) / 2.0
        zx0 = cx - half if ux == 0 else min(cx, cx + ux * DOOR_CLEARANCE_M)
        zx1 = cx + half if ux == 0 else max(cx, cx + ux * DOOR_CLEARANCE_M)
        zy0 = cy - half if uy == 0 else min(cy, cy + uy * DOOR_CLEARANCE_M)
        zy1 = cy + half if uy == 0 else max(cy, cy + uy * DOOR_CLEARANCE_M)
        blocking = [
            iid for iid, r in rects.items()
            if r[0] < zx1 and r[2] > zx0 and r[1] < zy1 and r[3] > zy0
        ]
        if blocking:
            issues.append({
                "kind": "door_blocked",
                "severity": 3,
                "offenders": blocking,
                "message": f"門口 {int(DOOR_CLEARANCE_M * 100)} 公分內被家具擋住，進出不方便。",
                "remedy": "把擋在門口的家具往內移，門前至少留 60 公分淨空。",
            })
        sx, sy = cx + ux * (radius + _CELL_M), cy + uy * (radius + _CELL_M)
        ix = min(nx - 1, max(0, int(sx / _CELL_M)))
        iy = min(ny - 1, max(0, int(sy / _CELL_M)))
        if free(ix, iy):
            starts.append((ix, iy))

    grid = [[free(ix, iy) for iy in range(ny)] for ix in range(nx)]
    seen = [[False] * ny for _ in range(nx)]
    queue = deque()
    for s in starts:
        if not seen[s[0]][s[1]]:
            seen[s[0]][s[1]] = True
            queue.append(s)
    while queue:
        ix, iy = queue.popleft()
        for jx, jy in ((ix + 1, iy), (ix - 1, iy), (ix, iy + 1), (ix, iy - 1)):
            if 0 <= jx < nx and 0 <= jy < ny and grid[jx][jy] and not seen[jx][jy]:
                seen[jx][jy] = True
                queue.append((jx, jy))
    reached = [centre(ix, iy) for ix in range(nx) for iy in range(ny) if seen[ix][iy]]

    unreachable: list[str] = []
    reach = radius + 0.15
    for it in obstacles:
        if it.type not in _NEEDS_ACCESS:
            continue
        r = rects[it.id]
        if not any(_dist_to_rect(px, py, r) <= reach for px, py in reached):
            unreachable.append(it.id)
    if unreachable:
        issues.append({
            "kind": "unreachable",
            "severity": 2,
            "offenders": unreachable,
            "message": f"從門口走過去，沿途有地方走道不到 {int(WALKWAY_M * 100)} 公分。",
            "remedy": "拉開家具之間的距離，主要走道保留 60 公分以上。",
        })

    free_cells = sum(1 for col in grid for c in col if c)
    score = 100 - sum(30 if i["kind"] == "door_blocked" else 10 * len(i["offenders"]) for i in issues)
    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "walkable_ratio": round(len(reached) / (nx * ny), 3),
        "free_ratio": round(free_cells / (nx * ny), 3),
    }


# ── 對外 ──────────────────────────────────────────────────────────────────────

def audit_layout(
    placements: list[dict],
    room_w: float,
    room_d: float,
    room_type: str | None = None,
    doors: list[dict] | None = None,
    windows: list[dict] | None = None,
    rules: list[str] | None = None,
) -> dict[str, Any]:
    """門窗都沒給時用預設門窗並標記 `assumed_openings`，報告上要講明是推估的。"""
    assumed = doors is None and windows is None
    if assumed:
        doors, windows = DEFAULT_DOORS, DEFAULT_WINDOWS
    items = items_from_placements(placements)
    return {
        "fengshui": audit_fengshui(items, doors or [], windows or [], rules=rules, room_type=room_type),
        "circulation": audit_circulation(items, doors or [], room_w, room_d),
        "assumed_openings": assumed,
        # 平面圖上的朝向箭頭；跟生圖時椅背／床頭、IKEA 模型的擺向是同一套（facing.py）
        "facing": screen_facing(placements, room_w, room_d),
        "doors": doors or [],
        "windows": windows or [],
    }


# 貼著主家具的「跟班」：主家具被推開時一起平移，不然床頭櫃會留在原地、被床疊上去
_COMPANIONS: dict[str, set[str]] = {
    "bed": {"nightstand", "side_table", "lamp"},
    "bunk_bed": {"nightstand", "side_table", "lamp", "bunk_ladder"},
    "desk": {"chair", "lamp"},
    "sofa": {"side_table", "coffee_table", "lamp"},
    "loveseat": {"side_table", "coffee_table", "lamp"},
}
_COMPANION_GAP = 0.04   # 歸一化距離，離主家具這麼近才算跟班
_FLOOR = {"rug", "carpet", "mat", "doormat"}


def _gap(a: FurnitureItem, b: FurnitureItem) -> float:
    dx = max(a.x - (b.x + b.w), b.x - (a.x + a.w), 0.0)
    dy = max(a.y - (b.y + b.h), b.y - (a.y + a.h), 0.0)
    return max(dx, dy)


def _collide(a: FurnitureItem, b: FurnitureItem, eps: float = 0.005) -> bool:
    return (min(a.x + a.w, b.x + b.w) - max(a.x, b.x) > eps
            and min(a.y + a.h, b.y + b.h) - max(a.y, b.y) > eps)


def _companion_groups(items: list[FurnitureItem]) -> dict[str, str]:
    """跟班 id → 主家具 id（只認離它最近的那件主家具）。"""
    owner: dict[str, str] = {}
    for c in items:
        best = None
        for a in items:
            if a is c or c.type not in _COMPANIONS.get(a.type, ()):
                continue
            g = _gap(a, c)
            if g <= _COMPANION_GAP and (best is None or g < best[0]):
                best = (g, a.id)
        if best:
            owner[c.id] = best[1]
    return owner


_SEP_MARGIN = 0.02   # 家具之間至少留的間距（歸一化），跟排版引擎的 _overlaps 一致


def _separate(items: list[FurnitureItem], group_of, moved: set[str]) -> None:
    """解開重疊：一次推一整組（主家具＋跟班），只推最小必要的距離。

    優先推這次被調整過的那一組，原本沒動的家具盡量不碰；兩組都動過或都沒動時推面積小的。
    推了會出界就改推另一組，兩組都推不動就留著，交給最後的退回原位處理。
    """
    by_id = {it.id: it for it in items}
    solid = [it for it in items if it.type not in _FLOOR]

    def shift_ok(ids: set[str], dx: float, dy: float) -> bool:
        return all(
            0.0 <= by_id[i].x + dx and by_id[i].x + by_id[i].w + dx <= 1.0
            and 0.0 <= by_id[i].y + dy and by_id[i].y + by_id[i].h + dy <= 1.0
            for i in ids
        )

    def push(mover: FurnitureItem, other: FurnitureItem) -> bool:
        ids = group_of(mover.id)
        options = [
            (other.x + other.w + _SEP_MARGIN - mover.x + 1e-4, 0.0),
            (-(mover.x + mover.w + _SEP_MARGIN - other.x + 1e-4), 0.0),
            (0.0, other.y + other.h + _SEP_MARGIN - mover.y + 1e-4),
            (0.0, -(mover.y + mover.h + _SEP_MARGIN - other.y + 1e-4)),
        ]
        for dx, dy in sorted(options, key=lambda o: abs(o[0]) + abs(o[1])):
            if shift_ok(ids, dx, dy):
                for i in ids:
                    by_id[i].x += dx
                    by_id[i].y += dy
                return True
        return False

    def area(ids: set[str]) -> float:
        return sum(by_id[i].w * by_id[i].h for i in ids)

    for _ in range(60):
        changed = False
        for i, a in enumerate(solid):
            for b in solid[i + 1:]:
                ga, gb = group_of(a.id), group_of(b.id)
                if ga == gb or not _collide(a, b, eps=-_SEP_MARGIN + 1e-6):
                    continue
                a_moved, b_moved = bool(ga & moved), bool(gb & moved)
                if a_moved != b_moved:
                    first, second = (a, b) if a_moved else (b, a)
                else:
                    first, second = (a, b) if area(ga) <= area(gb) else (b, a)
                if push(first, second) or push(second, first):
                    changed = True
        if not changed:
            return


def _carry_companions(items: list[FurnitureItem], owner: dict[str, str], start: dict) -> None:
    """主家具從 start 移動了多少，沒被單獨移動過的跟班就跟著移動多少。"""
    by_id = {it.id: it for it in items}
    for cid, aid in owner.items():
        c, a = by_id[cid], by_id[aid]
        if (c.x, c.y) != start[cid]:
            continue   # 跟班自己被規則移動過，就照規則的結果
        c.x = max(0.0, min(1.0 - c.w, c.x + a.x - start[aid][0]))
        c.y = max(0.0, min(1.0 - c.h, c.y + a.y - start[aid][1]))


def _settle(items: list[FurnitureItem], space_info: dict, owner: dict[str, str], group_of, moved: set[str]) -> None:
    """排版常理：解開重疊，再套 skills/layout-constraints（靠牆、語意間距、床邊留空），再解一次。"""
    from designbridge.layout.layout_constraints import load_layout_constraints
    from designbridge.layout.layout_enforce import _LAYOUT_ENFORCERS

    _separate(items, group_of, moved)
    start = {it.id: (it.x, it.y) for it in items}
    # 跟班不直接交給常理規則：床頭櫃會被「床邊要留通道」當成擋路推走，它應該跟著床
    anchors = [it for it in items if it.id not in owner]
    for card in load_layout_constraints():
        fn = _LAYOUT_ENFORCERS.get(card.enforce)
        if fn:
            fn(anchors, space_info, card.parameters)   # 原地修改；回傳值（例：補上下鋪梯子）不採用
    _carry_companions(items, owner, start)
    _separate(items, group_of, moved)
    for it in items:
        it.x = max(0.0, min(1.0 - it.w, it.x))
        it.y = max(0.0, min(1.0 - it.h, it.y))


_SEARCH_STEP = 0.025     # 整組搬家時試的格距（歸一化）
_SEARCH_SHORTLIST = 12   # 風水先篩過的候選，最多拿幾個去跑比較貴的動線檢查
_HUG_WALL = 0.03         # 離牆這麼近（歸一化）才算貼牆


def _relocate_groups(
    items: list[FurnitureItem], groups: list[tuple[str, list[str]]], solid: list[FurnitureItem],
    health, fengshui_bad,
) -> None:
    """enforcer 只會沿原本那面牆滑動；房間不夠寬就解不掉（例：床對門，左右都滑不出門的視線）。
    這時把違規的家具搬到房內其他位置試試——等於人會做的「床換一面牆」。

    `groups` 是 (主家具, [跟班…])。先試整組一起搬；床＋兩個床頭櫃常常寬到兩側都放不下，
    就退一步只帶一個跟班、最後只搬主家具（留下的跟班原地不動，照樣要避開它）。

    每種組合先只用風水判定篩出「違規變少、不撞其他家具」的位置，取離原位最近的幾個
    再檢查動線，動線不能變差。一組一組來，前一組搬好之後的狀態就是下一組的起點。

    原本貼牆的主家具搬完仍要貼牆，而且只能是原本那面或對面那面：不然把床拉到房間中間
    就「躲過」床頭靠窗的判定（那條只看貼牆的床），床頭反而懸空；換到側牆則會變成
    長邊靠牆（編輯器旋轉不改長寬，見 LayoutEditor rotateNTimes90）。
    """
    by_id = {it.id: it for it in items}

    def try_move(ids: list[str]) -> bool:
        grp = [by_id[i] for i in ids]
        root = grp[0]
        wall0 = _nearest_wall(root)
        hugging = _wall_distance(root, wall0) <= _HUG_WALL
        walls_ok = {wall0, _WALL_OPPOSITE[wall0]}
        others = [it for it in solid if it.id not in ids]
        gx0, gy0 = min(it.x for it in grp), min(it.y for it in grp)
        gw = max(it.x + it.w for it in grp) - gx0
        gh = max(it.y + it.h for it in grp) - gy0
        if gw > 1.0 or gh > 1.0:
            return False
        start = {it.id: (it.x, it.y) for it in grp}
        base_bad, base_circ, _ = health()

        def place(nx: float, ny: float) -> None:
            for it in grp:
                it.x = start[it.id][0] + nx - gx0
                it.y = start[it.id][1] + ny - gy0

        xs = [i * _SEARCH_STEP for i in range(int((1.0 - gw) / _SEARCH_STEP) + 1)] + [1.0 - gw]
        ys = [i * _SEARCH_STEP for i in range(int((1.0 - gh) / _SEARCH_STEP) + 1)] + [1.0 - gh]
        shortlist = []
        for nx in xs:
            for ny in ys:
                place(nx, ny)
                if hugging:
                    wall = _nearest_wall(root)
                    if wall not in walls_ok or _wall_distance(root, wall) > _HUG_WALL:
                        continue
                if any(_collide(g, o, eps=-_SEP_MARGIN + 1e-6) for g in grp if g.type not in _FLOOR for o in others):
                    continue
                bad = fengshui_bad()
                if bad < base_bad:
                    shortlist.append((bad, math.hypot(nx - gx0, ny - gy0), nx, ny))

        for _, _, nx, ny in sorted(shortlist)[:_SEARCH_SHORTLIST]:
            place(nx, ny)
            bad, circ, _ = health()
            if bad < base_bad and circ >= base_circ:
                return True
        for it in grp:
            it.x, it.y = start[it.id]
        return False

    for root, companions in groups:
        variants = [[root, *companions]]
        if len(companions) > 1:
            variants += [[root, c] for c in companions]
        if companions:
            variants.append([root])
        for ids in variants:
            if try_move(ids):
                break


def fix_layout(
    placements: list[dict],
    doors: list[dict],
    windows: list[dict],
    rules: list[str],
    room_w: float = 5.0,
    room_d: float = 4.0,
) -> list[dict]:
    """把勾選規則的 enforcer 套在現有擺法上，回傳新的 placements（保留原本的額外欄位）。

    每一輪：風水 enforcer 推開違規家具 → 跟班跟著主家具平移 → 排版常理規則收尾
    （不重疊、靠牆、間距）。收尾可能把家具推回禁忌位置，所以反覆到風水也滿足為止。
    最後仍撞在一起的那一組退回原位，由報告給化解建議，不製造疊在一起的假合規。
    """
    cards = load_constraint_cards()
    active = sorted((cards[t] for t in rules if t in cards), key=lambda c: c.order)
    items = items_from_placements(placements)
    by_id = {it.id: it for it in items}
    original = {it.id: (it.x, it.y) for it in items}
    owner = _companion_groups(items)
    space_info = {
        "estimated_size": {"width": room_w, "depth": room_d, "height": 2.8},
        "doors": doors,
        "windows": windows,
    }

    def group_of(iid: str) -> set[str]:
        root = owner.get(iid, iid)
        return {root} | {c for c, a in owner.items() if a == root}

    rule_ids = [c.trigger for c in active]

    def fengshui_bad() -> int:
        return sum(r["severity"] for r in audit_fengshui(items, doors, windows, rules=rule_ids)["rules"] if r["status"] == "fail")

    def health() -> tuple[int, int, dict]:
        """(勾選規則的違規嚴重度總和, 動線分數, 風水報告)；沒有門時動線不計分，當作滿分。"""
        fs = audit_fengshui(items, doors, windows, rules=rule_ids)
        bad = sum(r["severity"] for r in fs["rules"] if r["status"] == "fail")
        circ = audit_circulation(items, doors, room_w, room_d)["score"]
        return bad, 100 if circ is None else circ, fs

    bad0, circ0, fs0 = health()
    offenders0 = {iid for r in fs0["rules"] for iid in r["offenders"]}
    # 原本貼牆的家具 → 調整後允許貼的牆（原本那面＋對面）；排版常理的「床不靠窗」會把床推離牆，
    # 那種床頭懸空的結果不算修好
    hug0 = {
        it.id: {_nearest_wall(it), _WALL_OPPOSITE[_nearest_wall(it)]}
        for it in items
        if it.type not in _FLOOR and _wall_distance(it, _nearest_wall(it)) <= _HUG_WALL
    }

    def fengshui_ok() -> bool:
        return not any(
            _VERIFIERS[key](items, doors, windows, card.parameters)
            for card in active for key in card.enforce if key in _VERIFIERS
        )

    for _ in range(_FIX_PASSES):
        start = {it.id: (it.x, it.y) for it in items}
        for card in active:
            for key in card.enforce:
                fn = _ENFORCERS.get(key)
                if fn:
                    fn(items, doors, windows, card.parameters)
        _carry_companions(items, owner, start)
        _settle(items, space_info, owner, group_of, {it.id for it in items if (it.x, it.y) != original[it.id]})
        if fengshui_ok():
            break

    solid = [it for it in items if it.type not in _FLOOR]
    for _ in range(len(solid)):
        moved = {it.id for it in items if (it.x, it.y) != original[it.id]}
        clash = next((
            (a, b) for i, a in enumerate(solid) for b in solid[i + 1:]
            if (a.id in moved or b.id in moved)
            and group_of(a.id) != group_of(b.id)
            and _collide(a, b)
        ), None)
        if clash is None:
            break
        a, b = clash
        for iid in group_of(a.id if a.id in moved else b.id):
            by_id[iid].x, by_id[iid].y = original[iid]

    # 只接受確實變好的結果：勾選規則的違規要減少，動線分數不能變差。排版常理規則
    # （例：床不靠窗）可能把家具推開卻沒解掉任何違規，或把衣櫃擠到門口——那種「動了
    # 但沒變好」的結果不交給使用者。整組不合格時退一步，只保留原本違規那幾組的移動
    # （被連帶推走的放回原位）再檢查一次；還是不行就全部還原，由報告給化解建議。
    def clashes() -> bool:
        moved = {it.id for it in items if (it.x, it.y) != original[it.id]}
        return any(
            (a.id in moved or b.id in moved) and group_of(a.id) != group_of(b.id) and _collide(a, b)
            for i, a in enumerate(solid) for b in solid[i + 1:]
        )

    def left_wall() -> bool:
        """原本貼牆、被移動過的家具，現在沒貼在原本那面或對面那面牆上（見 _relocate_groups）。"""
        for it in items:
            if it.id not in hug0 or (it.x, it.y) == original[it.id]:
                continue
            wall = _nearest_wall(it)
            if wall not in hug0[it.id] or _wall_distance(it, wall) > _HUG_WALL:
                return True
        return False

    def improved() -> bool:
        bad, circ, _ = health()
        return bad < bad0 and circ >= circ0 and not clashes() and not left_wall()

    full = {it.id: (it.x, it.y) for it in items}
    keep = set().union(*(group_of(i) for i in offenders0))
    trimmed = {iid: full[iid] if iid in keep else original[iid] for iid in full}
    for candidate in (full, trimmed, original):
        for it in items:
            it.x, it.y = candidate[it.id]
        if candidate is original or improved():
            break

    # 局部推移之後還有違規（沒解掉、或只解掉其中幾條），從目前狀態再試整組搬家
    bad_now, _, fs_now = health()
    if bad_now:
        # offenders 也可能是門（「門不對窗」），門搬不動，只搬家具
        offenders_now = {iid for r in fs_now["rules"] if r["status"] == "fail" for iid in r["offenders"]}
        roots = dict.fromkeys(owner.get(i, i) for i in offenders_now if i in by_id)
        groups = [(r, sorted(c for c, a in owner.items() if a == r)) for r in roots]
        _relocate_groups(items, groups, solid, health, fengshui_bad)

    # 只改寫真的被移動的家具；沒動的原樣回傳。若全部都 round，編輯器拖出來的多位小數
    # 座標會變，/api/fengshui/fix 比對位置時就把沒動的家具也算成「已調整」。
    out: list[dict] = []
    for i, p in enumerate(placements):
        it = by_id.get(str(p.get("id") or f"item_{i}"))
        moved = it is not None and (it.x, it.y) != original[it.id]
        out.append({**p, "x": round(it.x, 4), "y": round(it.y, 4)} if moved else p)
    return out
