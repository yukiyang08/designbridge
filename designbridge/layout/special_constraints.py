"""Special layout constraints loaded from skills/constraints/*/SKILL.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from designbridge.layout._skill_frontmatter import parse_skill_frontmatter


# ── Skill Card ────────────────────────────────────────────────────────────────

@dataclass
class ConstraintSkillCard:
    trigger: str
    name: str
    description: str
    constraint_type: str
    enforce: list[str]
    prompt_addition: str
    order: int = 99
    parameters: dict = field(default_factory=dict)


# ── Registry ──────────────────────────────────────────────────────────────────

class ConstraintRegistry:

    def __init__(self, constraints_root: Path | None = None) -> None:
        if constraints_root is None:
            _root = Path(__file__).resolve().parent.parent.parent
            constraints_root = _root / "skills" / "constraints"
        self._root = constraints_root
        self._cache: dict[str, ConstraintSkillCard] | None = None

    def _parse_skill_md(self, skill_id: str) -> ConstraintSkillCard | None:
        fm = parse_skill_frontmatter(self._root / skill_id / "SKILL.md")
        if fm is None:
            return None

        enforce = fm.get("enforce") or []
        if isinstance(enforce, str):
            enforce = [enforce]

        return ConstraintSkillCard(
            trigger=str(fm.get("trigger", skill_id)),
            name=str(fm.get("name", skill_id)),
            description=str(fm.get("description", "")),
            constraint_type=str(fm.get("type", "fengshui")),
            enforce=enforce,
            prompt_addition=str(fm.get("prompt_addition", "")),
            order=int(fm.get("order", 99)),
            parameters=fm.get("parameters") or {},
        )

    def load(self) -> dict[str, ConstraintSkillCard]:
        if self._cache is not None:
            return self._cache
        result: dict[str, ConstraintSkillCard] = {}
        if not self._root.is_dir():
            return result
        for child in sorted(self._root.iterdir()):
            if child.is_dir():
                card = self._parse_skill_md(child.name)
                if card:
                    result[card.trigger] = card
        self._cache = result
        return result


_registry: ConstraintRegistry | None = None


def get_constraint_registry() -> ConstraintRegistry:
    global _registry
    if _registry is None:
        _registry = ConstraintRegistry()
    return _registry


# ── Geometry helper ───────────────────────────────────────────────────────────

def _rect_overlap(ax, ay, aw, ah, bx, by, bw, bh, margin: float) -> bool:
    return not (
        ax + aw + margin <= bx
        or bx + bw + margin <= ax
        or ay + ah + margin <= by
        or by + bh + margin <= ay
    )


def _opening_wall(opening: dict) -> str:
    """開口貼在哪面牆：'far'（y=0）/'near'（y=1）/'left'（x=0）/'right'（x=1）。

    平面圖座標：x 左→右、y 遠（0）→近（1）。優先用開口自己宣告的 `wall`；
    沒宣告時才從座標推——取離四面牆最近的那一面，而不是用固定門檻，
    因為門可以落在牆上任何位置，硬套 0.3/0.7 會把牆角的門判到錯誤的牆上。
    """
    declared = str(opening.get("wall") or "").strip().lower()
    if declared in ("far", "near", "left", "right"):
        return declared
    ox = float(opening.get("x", 0.5))
    oy = float(opening.get("y", 1.0))
    ow = float(opening.get("w", 0.10))
    oh = float(opening.get("h", 0.02))
    cx, cy = ox + ow / 2.0, oy + oh / 2.0
    dists = {"far": cy, "near": 1.0 - cy, "left": cx, "right": 1.0 - cx}
    return min(dists, key=dists.get)


def _opening_span(opening: dict, wall: str) -> tuple[float, float]:
    """門在它所屬牆面上佔據的區間（沿著那面牆的軸）。

    上下牆用 x 區間，左右牆用 y 區間——左右牆的門寬記在 `h` 裡（`w` 是牆厚）。
    兩者都缺就退回 `w`，寧可抓寬一點也不要算出零寬度的視線帶。
    """
    if wall in ("far", "near"):
        lo = float(opening.get("x", 0.5))
        return lo, lo + float(opening.get("w", 0.10))
    lo = float(opening.get("y", 0.5))
    length = float(opening.get("h", 0.0)) or float(opening.get("w", 0.10))
    return lo, lo + length


def _sightline_band(opening: dict, margin: float) -> tuple[str, float, float]:
    """門的正向視線帶：回傳 (橫向軸, 區間下界, 區間上界)。

    站在門口直視前方，看得到的是門寬往室內延伸出去的那條帶狀區域。
    `axis` 是這條帶「橫跨」的軸——上下牆的門，帶子沿 y 延伸、橫跨 x。
    """
    wall = _opening_wall(opening)
    lo, hi = _opening_span(opening, wall)
    axis = "x" if wall in ("far", "near") else "y"
    return axis, lo - margin, hi + margin


# ── Enforcement functions (uniform signature: items, doors, windows, params) ──

def _enforce_bed_not_facing_door(
    items: list, doors: list, windows: list, params: dict
) -> list:
    if not doors:
        return items
    offset = float(params.get("offset", 0.12))
    pad = float(params.get("pad", 0.02))

    for item in items:
        if item.type not in ("bed", "bunk_bed"):
            continue
        bed_cx = item.x + item.w / 2
        bed_foot_y = item.y + item.h
        for door in doors:
            dx = float(door.get("x", 0.5))
            dw = float(door.get("w", 0.10))
            dy = float(door.get("y", 1.0))
            door_cx = dx + dw / 2
            if dy > bed_foot_y and abs(door_cx - bed_cx) < (item.w / 2 + dw / 2):
                if bed_cx < 0.5:
                    item.x = min(item.x + offset, 1.0 - item.w - pad)
                else:
                    item.x = max(item.x - offset, pad)
    return items


def _enforce_sofa_not_back_to_door(
    items: list, doors: list, windows: list, params: dict
) -> list:
    if not doors:
        return items
    push = float(params.get("push_amount", 0.15))
    door_hi = float(params.get("door_threshold_high", 0.7))
    door_lo = float(params.get("door_threshold_low", 0.3))
    sofa_hi = float(params.get("sofa_threshold_high", 0.65))
    sofa_lo = float(params.get("sofa_threshold_low", 0.35))
    pad = float(params.get("pad", 0.02))

    for item in items:
        if item.type not in ("sofa", "loveseat"):
            continue
        for door in doors:
            dy = float(door.get("y", 0))
            if dy > door_hi and item.y + item.h > sofa_hi:
                item.y = max(pad, item.y - push)
            elif dy < door_lo and item.y < sofa_lo:
                item.y = min(1.0 - item.h - pad, item.y + push)
    return items


def _enforce_desk_not_facing_window(
    items: list, doors: list, windows: list, params: dict
) -> list:
    if not windows:
        return items
    push = float(params.get("push", 0.15))
    min_y = float(params.get("min_y", 0.22))
    win_wall = float(params.get("window_wall_threshold", 0.15))
    desk_thr = float(params.get("desk_threshold", 0.20))

    for item in items:
        if item.type != "desk":
            continue
        for window in windows:
            wx = float(window.get("x", 0.5))
            wy = float(window.get("y", 0))
            ww = float(window.get("w", 0.15))
            window_cx = wx + ww / 2
            desk_cx = item.x + item.w / 2
            if (wy < win_wall and item.y < desk_thr
                    and abs(desk_cx - window_cx) < (item.w / 2 + ww / 2)):
                item.y = max(min_y, item.y + push)
    return items


_WALL_OPPOSITE: dict[str, str] = {
    "far": "near", "near": "far", "left": "right", "right": "left",
}


def _nearest_wall(item) -> str:
    """家具靠的那面牆——四個邊裡離牆最近的那一邊。"""
    dists = {
        "far": item.y,
        "near": 1.0 - (item.y + item.h),
        "left": item.x,
        "right": 1.0 - (item.x + item.w),
    }
    return min(dists, key=dists.get)


def _item_span(item, axis: str) -> tuple[float, float]:
    if axis == "x":
        return item.x, item.x + item.w
    return item.y, item.y + item.h


def _shift_clear_of_band(item, axis: str, lo: float, hi: float, pad: float) -> bool:
    """把 item 沿 `axis` 推出 [lo, hi] 這條視線帶。已經在帶外就不動。

    回傳是否「最終落在帶外」。房間窄到兩側都放不下時保持原位並回傳 False，
    讓 verifier 如實回報這條規則沒被滿足——硬推到牆裡只會製造假的合規。
    """
    i_lo, i_hi = _item_span(item, axis)
    if i_hi <= lo or hi <= i_lo:
        return True

    size = i_hi - i_lo
    limit = 1.0 - size - pad
    before, after = lo - size - pad, hi + pad
    # 先試離目前位置較近的那一側，讓修正幅度最小
    centre, band_centre = i_lo + size / 2.0, (lo + hi) / 2.0
    order = (before, after) if centre < band_centre else (after, before)

    for target in order:
        if pad <= target <= limit:
            if axis == "x":
                item.x = target
            else:
                item.y = target
            return True
    return False


def _enforce_door_sightline_clear(
    items: list, doors: list, windows: list, params: dict
) -> list:
    """「開門不見灶」「開門不見廁所」：指定家具不得落在門的正向視線帶上。

    站在門口直視前方看到的是門寬往室內延伸的那條帶子；標的落在帶上就沿橫向推開，
    推去離原位較近的一側。`blocked_types` 由各張卡片自己宣告，所以同一支函式
    可以同時服務灶與廁所兩條規則。
    """
    if not doors:
        return items
    blocked = set(params.get("blocked_types") or [])
    if not blocked:
        return items
    margin = float(params.get("margin", 0.03))
    pad = float(params.get("pad", 0.02))

    for item in items:
        if item.type not in blocked:
            continue
        for door in doors:
            axis, lo, hi = _sightline_band(door, margin)
            _shift_clear_of_band(item, axis, lo, hi, pad)
    return items


def _enforce_desk_not_back_to_door(
    items: list, doors: list, windows: list, params: dict
) -> list:
    """「書桌不背門」：坐在書桌前的人不該背對門口。

    書桌靠哪面牆，人就面向那面牆，背因此朝向**對牆**。只有當門開在那面對牆、
    而且落在書桌的橫向範圍內時才算背門——此時沿牆推開書桌，讓座位側身見門。
    """
    if not doors:
        return items
    targets = set(params.get("desk_types") or ["desk"])
    margin = float(params.get("margin", 0.03))
    pad = float(params.get("pad", 0.02))

    for item in items:
        if item.type not in targets:
            continue
        back_wall = _WALL_OPPOSITE[_nearest_wall(item)]
        for door in doors:
            if _opening_wall(door) != back_wall:
                continue
            axis, lo, hi = _sightline_band(door, margin)
            _shift_clear_of_band(item, axis, lo, hi, pad)
    return items


def _wall_distance(item, wall: str) -> float:
    """家具那一邊離 `wall` 多遠。"""
    return {
        "far": item.y,
        "near": 1.0 - (item.y + item.h),
        "left": item.x,
        "right": 1.0 - (item.x + item.w),
    }[wall]


def _item_facing_band(item, margin: float) -> tuple[str, float, float]:
    """靠牆家具的正面視線帶——鏡子照出去、沙發面向的那條帶子。

    形狀跟門的視線帶完全一樣（`_sightline_band`），只是起點換成家具自己貼的那面牆：
    它靠哪面牆就背著那面牆，正面因此朝向室內。
    """
    wall = _nearest_wall(item)
    axis = "x" if wall in ("far", "near") else "y"
    lo, hi = _item_span(item, axis)
    return axis, lo - margin, hi + margin


def _enforce_not_backed_by_opening(
    items: list, doors: list, windows: list, params: dict
) -> list:
    """「床頭不靠窗」「灶後不宜空」「沙發不背窗」：家具背後那面牆不得是開口。

    家具貼哪面牆，背就朝那面牆。同一面牆上的窗（或門）若與家具重疊，
    就沿著牆把家具滑到實牆段，推去離原位較近的一側。

    只處理**已經貼著牆**（距牆 ≤ `wall_threshold`）的家具——擺在房間中央的床
    沒有「背靠」可言，這條規則不該對它出手。
    """
    targets = set(params.get("types") or [])
    if not targets:
        return items
    kind = str(params.get("opening_kind", "window"))
    openings: list = []
    if kind in ("window", "both"):
        openings += windows
    if kind in ("door", "both"):
        openings += doors
    if not openings:
        return items

    margin = float(params.get("margin", 0.02))
    pad = float(params.get("pad", 0.02))
    wall_threshold = float(params.get("wall_threshold", 0.12))

    for item in items:
        if item.type not in targets:
            continue
        wall = _nearest_wall(item)
        if _wall_distance(item, wall) > wall_threshold:
            continue
        for opening in openings:
            if _opening_wall(opening) != wall:
                continue
            axis, lo, hi = _sightline_band(opening, margin)
            _shift_clear_of_band(item, axis, lo, hi, pad)
    return items


def _enforce_item_sightline_clear(
    items: list, doors: list, windows: list, params: dict
) -> list:
    """「鏡不照床」：`blocked_types` 不得落在 `source_types` 的正面視線帶上。

    跟 `door_sightline_clear` 是同一套幾何，只是視線起點從門換成家具（鏡子）。
    """
    sources = set(params.get("source_types") or [])
    blocked = set(params.get("blocked_types") or [])
    if not sources or not blocked:
        return items
    margin = float(params.get("margin", 0.03))
    pad = float(params.get("pad", 0.02))

    source_items = [it for it in items if it.type in sources]
    if not source_items:
        return items

    for item in items:
        if item.type not in blocked:
            continue
        for src in source_items:
            if src is item:
                continue
            axis, lo, hi = _item_facing_band(src, margin)
            _shift_clear_of_band(item, axis, lo, hi, pad)
    return items


def _enforce_group_separation(
    items: list, doors: list, windows: list, params: dict
) -> list:
    """「水火不相容」：`group_a` 與 `group_b` 的家具之間至少留 `min_gap`。

    只推開跨組的配對，組內（例如兩座爐灶）維持原本的排法不動。
    """
    group_a = set(params.get("group_a") or [])
    group_b = set(params.get("group_b") or [])
    if not group_a or not group_b:
        return items
    min_gap = float(params.get("min_gap", 0.12))
    pad = float(params.get("pad", 0.02))
    iterations = int(params.get("iterations", 30))

    pairs = [
        (a, b)
        for a in items if a.type in group_a
        for b in items if b.type in group_b and b is not a
    ]
    if not pairs:
        return items

    def _clip(item) -> None:
        item.x = max(pad, min(1.0 - item.w - pad, item.x))
        item.y = max(pad, min(1.0 - item.h - pad, item.y))

    for _ in range(iterations):
        moved = False
        for a, b in pairs:
            if not _rect_overlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, min_gap):
                continue
            dx = (a.x + a.w / 2) - (b.x + b.w / 2)
            dy = (a.y + a.h / 2) - (b.y + b.h / 2)
            # 還差多少才拉得開：兩件的半寬和 + 要求的間距 − 現在的中心距。
            # 兩軸都是正的（否則 _rect_overlap 不會成立），沿差距小的那一軸推，
            # 修正幅度最小；`slack` 讓結果穩穩落在門檻外側，不卡在剛好相等。
            slack = 1e-4
            need_x = (a.w + b.w) / 2 + min_gap - abs(dx) + slack
            need_y = (a.h + b.h) / 2 + min_gap - abs(dy) + slack
            if need_x <= need_y:
                half = need_x / 2
                sign = 1.0 if dx >= 0 else -1.0
                a.x += half * sign
                b.x -= half * sign
            else:
                half = need_y / 2
                sign = 1.0 if dy >= 0 else -1.0
                a.y += half * sign
                b.y -= half * sign
            _clip(a)
            _clip(b)
            moved = True
        if not moved:
            break
    return items


def _straight_through_bands(
    doors: list, windows: list, margin: float
) -> list[tuple[str, float, float, str]]:
    """穿堂煞的直通帶：門與對牆的窗在同一軸上重疊的那一段。

    回傳 (橫向軸, 帶下界, 帶上界, 門所在的牆)。門窗不在對牆、或兩者的投影
    沒有交集，就不成一線，不列入。
    """
    bands: list[tuple[str, float, float, str]] = []
    for door in doors:
        d_wall = _opening_wall(door)
        d_lo, d_hi = _opening_span(door, d_wall)
        axis = "x" if d_wall in ("far", "near") else "y"
        for window in windows:
            if _opening_wall(window) != _WALL_OPPOSITE[d_wall]:
                continue
            w_lo, w_hi = _opening_span(window, _WALL_OPPOSITE[d_wall])
            lo, hi = max(d_lo, w_lo), min(d_hi, w_hi)
            if hi <= lo:
                continue
            bands.append((axis, lo - margin, hi + margin, d_wall))
    return bands


def _band_is_blocked(items: list, axis: str, lo: float, hi: float, types: set) -> bool:
    for item in items:
        if item.type not in types:
            continue
        i_lo, i_hi = _item_span(item, axis)
        if i_hi > lo and hi > i_lo:
            return True
    return False


def _enforce_door_window_screen(
    items: list, doors: list, windows: list, params: dict
) -> list:
    """「穿堂煞」：門直通對牆的窗，中間要有東西擋一下（玄關屏風的作用）。

    沒有直通帶就不動。有直通帶、但帶上已經有夠份量的家具擋著，也不動——
    擋的是「氣直穿」，不是非得某一件家具站在那裡。

    兩者皆非時，挑一件 `blocker_types` 的家具搬到帶上、離門 `distance_from_door` 處
    當屏風。房間裡一件都沒有就維持原樣，由 verifier 如實回報。
    """
    if not doors or not windows:
        return items
    blocker_types = set(params.get("blocker_types") or [])
    if not blocker_types:
        return items
    margin = float(params.get("margin", 0.03))
    pad = float(params.get("pad", 0.02))
    distance = float(params.get("distance_from_door", 0.22))

    for axis, lo, hi, d_wall in _straight_through_bands(doors, windows, margin):
        if _band_is_blocked(items, axis, lo, hi, blocker_types):
            continue
        blocker = next((it for it in items if it.type in blocker_types), None)
        if blocker is None:
            continue

        centre = (lo + hi) / 2.0
        if axis == "x":
            blocker.x = centre - blocker.w / 2.0
            blocker.y = distance if d_wall == "far" else 1.0 - distance - blocker.h
        else:
            blocker.y = centre - blocker.h / 2.0
            blocker.x = distance if d_wall == "left" else 1.0 - distance - blocker.w
        blocker.x = max(pad, min(1.0 - blocker.w - pad, blocker.x))
        blocker.y = max(pad, min(1.0 - blocker.h - pad, blocker.y))
    return items


# ── Dispatch table ────────────────────────────────────────────────────────────

_ENFORCERS: dict[str, Callable] = {
    "door_sightline_clear":      _enforce_door_sightline_clear,
    "desk_not_back_to_door":     _enforce_desk_not_back_to_door,
    "not_backed_by_opening":     _enforce_not_backed_by_opening,
    "item_sightline_clear":      _enforce_item_sightline_clear,
    "group_separation":          _enforce_group_separation,
    "door_window_screen":        _enforce_door_window_screen,
    "bed_not_facing_door":       _enforce_bed_not_facing_door,
    "sofa_not_back_to_door":     _enforce_sofa_not_back_to_door,
    "desk_not_facing_window":    _enforce_desk_not_facing_window,
}


# ── Verification functions (post-placement satisfaction check) ─────────────────

def _verify_bed_not_facing_door(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    if not doors:
        return True
    for item in items:
        if item.type not in ("bed", "bunk_bed"):
            continue
        bed_cx = item.x + item.w / 2
        bed_foot_y = item.y + item.h
        for door in doors:
            dx = float(door.get("x", 0.5))
            dw = float(door.get("w", 0.10))
            dy = float(door.get("y", 1.0))
            door_cx = dx + dw / 2
            if dy > bed_foot_y and abs(door_cx - bed_cx) < (item.w / 2 + dw / 2):
                return False
    return True


def _verify_sofa_not_back_to_door(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    if not doors:
        return True
    door_hi = float(params.get("door_threshold_high", 0.7))
    door_lo = float(params.get("door_threshold_low", 0.3))
    sofa_hi = float(params.get("sofa_threshold_high", 0.65))
    sofa_lo = float(params.get("sofa_threshold_low", 0.35))
    for item in items:
        if item.type not in ("sofa", "loveseat"):
            continue
        for door in doors:
            dy = float(door.get("y", 0))
            if dy > door_hi and item.y + item.h > sofa_hi:
                return False
            if dy < door_lo and item.y < sofa_lo:
                return False
    return True


def _verify_door_sightline_clear(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    if not doors:
        return True
    blocked = set(params.get("blocked_types") or [])
    if not blocked:
        return True
    margin = float(params.get("margin", 0.03))
    for item in items:
        if item.type not in blocked:
            continue
        for door in doors:
            axis, lo, hi = _sightline_band(door, margin)
            i_lo, i_hi = _item_span(item, axis)
            if i_hi > lo and hi > i_lo:
                return False
    return True


def _verify_desk_not_back_to_door(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    if not doors:
        return True
    targets = set(params.get("desk_types") or ["desk"])
    margin = float(params.get("margin", 0.03))
    for item in items:
        if item.type not in targets:
            continue
        back_wall = _WALL_OPPOSITE[_nearest_wall(item)]
        for door in doors:
            if _opening_wall(door) != back_wall:
                continue
            axis, lo, hi = _sightline_band(door, margin)
            i_lo, i_hi = _item_span(item, axis)
            if i_hi > lo and hi > i_lo:
                return False
    return True


def _verify_not_backed_by_opening(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    targets = set(params.get("types") or [])
    if not targets:
        return True
    kind = str(params.get("opening_kind", "window"))
    openings: list = []
    if kind in ("window", "both"):
        openings += windows
    if kind in ("door", "both"):
        openings += doors
    if not openings:
        return True
    margin = float(params.get("margin", 0.02))
    wall_threshold = float(params.get("wall_threshold", 0.12))

    for item in items:
        if item.type not in targets:
            continue
        wall = _nearest_wall(item)
        if _wall_distance(item, wall) > wall_threshold:
            continue
        for opening in openings:
            if _opening_wall(opening) != wall:
                continue
            axis, lo, hi = _sightline_band(opening, margin)
            i_lo, i_hi = _item_span(item, axis)
            if i_hi > lo and hi > i_lo:
                return False
    return True


def _verify_item_sightline_clear(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    sources = set(params.get("source_types") or [])
    blocked = set(params.get("blocked_types") or [])
    if not sources or not blocked:
        return True
    margin = float(params.get("margin", 0.03))
    source_items = [it for it in items if it.type in sources]
    if not source_items:
        return True

    for item in items:
        if item.type not in blocked:
            continue
        for src in source_items:
            if src is item:
                continue
            axis, lo, hi = _item_facing_band(src, margin)
            i_lo, i_hi = _item_span(item, axis)
            if i_hi > lo and hi > i_lo:
                return False
    return True


def _verify_group_separation(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    group_a = set(params.get("group_a") or [])
    group_b = set(params.get("group_b") or [])
    if not group_a or not group_b:
        return True
    min_gap = float(params.get("min_gap", 0.12))
    for a in items:
        if a.type not in group_a:
            continue
        for b in items:
            if b is a or b.type not in group_b:
                continue
            if _rect_overlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, min_gap):
                return False
    return True


def _verify_door_window_screen(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    """沒有直通帶、或房間裡根本沒有可當屏風的家具時，這條規則無從施力，回報滿足。"""
    if not doors or not windows:
        return True
    blocker_types = set(params.get("blocker_types") or [])
    if not blocker_types:
        return True
    margin = float(params.get("margin", 0.03))
    bands = _straight_through_bands(doors, windows, margin)
    if not bands:
        return True
    if not any(it.type in blocker_types for it in items):
        return True
    return all(
        _band_is_blocked(items, axis, lo, hi, blocker_types)
        for axis, lo, hi, _ in bands
    )


def _verify_desk_not_facing_window(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    if not windows:
        return True
    win_wall = float(params.get("window_wall_threshold", 0.15))
    desk_thr = float(params.get("desk_threshold", 0.20))
    for item in items:
        if item.type != "desk":
            continue
        for window in windows:
            wx = float(window.get("x", 0.5))
            wy = float(window.get("y", 0))
            ww = float(window.get("w", 0.15))
            if (wy < win_wall and item.y < desk_thr
                    and abs((item.x + item.w / 2) - (wx + ww / 2)) < (item.w / 2 + ww / 2)):
                return False
    return True


_VERIFIERS: dict[str, Callable] = {
    "bed_not_facing_door":   _verify_bed_not_facing_door,
    "sofa_not_back_to_door": _verify_sofa_not_back_to_door,
    "door_sightline_clear":  _verify_door_sightline_clear,
    "desk_not_back_to_door": _verify_desk_not_back_to_door,
    "not_backed_by_opening": _verify_not_backed_by_opening,
    "item_sightline_clear":  _verify_item_sightline_clear,
    "group_separation":      _verify_group_separation,
    "door_window_screen":    _verify_door_window_screen,
    "desk_not_facing_window": _verify_desk_not_facing_window,
}


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_requirement(
    structured_requirement: dict[str, Any],
    fengshui_rules: list[str],
) -> dict[str, Any]:
    """Merge fengshui_rules into structured_requirement.

    Appends prompt text from each constraint's SKILL.md and sets special_constraints flags.
    """
    if not fengshui_rules:
        return structured_requirement

    cards = get_constraint_registry().load()
    active_triggers: set[str] = set(fengshui_rules)

    prompt_parts: list[str] = []
    for trigger in fengshui_rules:
        card = cards.get(trigger)
        if card and card.prompt_addition:
            prompt_parts.append(card.prompt_addition)

    if prompt_parts:
        existing = (structured_requirement.get("design_description") or "").strip()
        addition = "; ".join(prompt_parts)
        if existing:
            existing = existing.rstrip(".")
            structured_requirement["design_description"] = f"{existing}. {addition}"
        else:
            structured_requirement["design_description"] = addition

    structured_requirement["special_constraints"] = {
        trigger: trigger in active_triggers for trigger in cards
    }
    return structured_requirement


def apply_special_layout_constraints(
    items: list,
    structured_requirement: dict[str, Any],
) -> list:
    """Apply all enabled fengshui constraints to the furniture item list.

    Constraints are applied in ascending `order` as declared in each SKILL.md.
    """
    special = structured_requirement.get("special_constraints") or {}
    space_info = structured_requirement.get("space_info") or {}
    doors = space_info.get("doors") or []
    windows = space_info.get("windows") or []

    cards = get_constraint_registry().load()
    for card in sorted(cards.values(), key=lambda c: c.order):
        if not special.get(card.trigger):
            continue
        for enforce_key in card.enforce:
            fn = _ENFORCERS.get(enforce_key)
            if fn:
                items = fn(items, doors, windows, card.parameters)

    return items


def verify_special_constraints(
    items: list,
    structured_requirement: dict[str, Any],
) -> dict[str, bool]:
    """Return {trigger: satisfied} for each enabled fengshui constraint.

    Only constraints with a registered verifier are included in the result.
    An absent entry means the constraint has no geometric verifier defined.
    """
    special = structured_requirement.get("special_constraints") or {}
    space_info = structured_requirement.get("space_info") or {}
    doors = space_info.get("doors") or []
    windows = space_info.get("windows") or []

    cards = get_constraint_registry().load()
    result: dict[str, bool] = {}
    for card in sorted(cards.values(), key=lambda c: c.order):
        if not special.get(card.trigger):
            continue
        for enforce_key in card.enforce:
            verifier = _VERIFIERS.get(enforce_key)
            if verifier:
                ok = verifier(items, doors, windows, card.parameters)
                result[card.trigger] = result.get(card.trigger, True) and ok
    return result
