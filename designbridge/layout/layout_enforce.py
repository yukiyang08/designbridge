"""Geometry, scoring, optimizer and hard-constraint enforcers for furniture layouts."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

from designbridge.layout.layout_items import FURNITURE_SIZES, FurnitureItem, SOFT_WEIGHTS


# ─────────────────────────── Geometry ───────────────────────────

# Flat floor coverings that other furniture is *meant* to stand on. Excluding them from
# collision is not a relaxation — it is the correct model. A rug under the sofa is the
# intended arrangement, and treating it as solid makes `_push_apart` shove the seating off
# it and makes `collision_free` report False on a perfectly good layout.
_UNDERLAY_TYPES = frozenset({"rug", "carpet", "mat", "floor_mat", "runner"})


@lru_cache(maxsize=256)
def _is_underlay_type(ftype: str) -> bool:
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    return normalize_furniture_type(ftype) in _UNDERLAY_TYPES


def _overlaps(a: FurnitureItem, b: FurnitureItem, margin: float = 0.02) -> bool:
    if _is_underlay_type(a.type) or _is_underlay_type(b.type):
        return False
    return not (
        a.x + a.w + margin <= b.x
        or b.x + b.w + margin <= a.x
        or a.y + a.h + margin <= b.y
        or b.y + b.h + margin <= a.y
    )


def _push_apart(items: list[FurnitureItem], iterations: int = 60) -> list[FurnitureItem]:
    """AABB collision resolution: iteratively push overlapping pairs apart.

    Clipping happens inside the loop. Separating first and clipping afterwards — the
    previous arrangement — lets the final clip shove an item that had been pushed past
    the wall straight back into its neighbour, so the pass reports success while leaving
    a collision behind, and more iterations never help because the clip undoes each one.
    """
    for _ in range(iterations):
        moved = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if _is_underlay_type(a.type) or _is_underlay_type(b.type):
                    continue
                if not _overlaps(a, b):
                    continue
                acx, acy = a.x + a.w / 2, a.y + a.h / 2
                bcx, bcy = b.x + b.w / 2, b.y + b.h / 2
                dx, dy = acx - bcx, acy - bcy
                ox = (a.x + a.w + 0.02) - b.x if dx >= 0 else b.x + b.w + 0.02 - a.x
                oy = (a.y + a.h + 0.02) - b.y if dy >= 0 else b.y + b.h + 0.02 - a.y
                # Push along shorter overlap axis
                if abs(ox) <= abs(oy):
                    half = ox / 2
                    a.x += half * (1 if dx >= 0 else -1)
                    b.x -= half * (1 if dx >= 0 else -1)
                else:
                    half = oy / 2
                    a.y += half * (1 if dy >= 0 else -1)
                    b.y -= half * (1 if dy >= 0 else -1)
                moved = True
        _clip_to_room(items)
        if not moved:
            break
    return items


def _clip_to_room(items: list[FurnitureItem], pad: float = 0.02) -> list[FurnitureItem]:
    for item in items:
        item.x = max(pad, min(1.0 - item.w - pad, item.x))
        item.y = max(pad, min(1.0 - item.h - pad, item.y))
    return items


# ─────────────────────────── Soft Constraints ───────────────────────────

def _score_soft_constraints(
    items: list[FurnitureItem], space_info: dict
) -> dict[str, float]:
    n = len(items)
    if n == 0:
        return {k: 0.5 for k in SOFT_WEIGHTS}

    size = space_info.get("estimated_size") or {}
    room_w = float(size.get("width", 5.0))   # metres
    room_d = float(size.get("depth", 4.0))

    # Pairwise gaps in physical metres
    gaps_m: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = items[i], items[j]
            gx = max(b.x - (a.x + a.w), a.x - (b.x + b.w), 0.0) * room_w
            gy = max(b.y - (a.y + a.h), a.y - (b.y + b.h), 0.0) * room_d
            gaps_m.append(gx + gy)

    # Circulation (35%): fraction of pairs with physical clearance ≥ 0.60 m
    AISLE_MIN_M = 0.60
    circulation = (
        sum(1 for g in gaps_m if g >= AISLE_MIN_M) / len(gaps_m)
    ) if gaps_m else 0.5

    # Balance (25%): area-weighted CoM distance from room centre (0.5, 0.5)
    areas = [item.w * item.h for item in items]
    total_area = sum(areas) or 1.0
    cx = sum((item.x + item.w / 2) * a for item, a in zip(items, areas)) / total_area
    cy = sum((item.y + item.h / 2) * a for item, a in zip(items, areas)) / total_area
    balance = max(0.0, 1.0 - 2 * (abs(cx - 0.5) + abs(cy - 0.5)))

    # Focal point (20%): largest piece near focal wall (y≈0.72) and horizontally centred
    largest = max(items, key=lambda i: i.w * i.h)
    focal_dx = abs(largest.x + largest.w / 2 - 0.5)
    focal_dy = abs(largest.y + largest.h / 2 - 0.72)
    focal_point = max(0.0, 1.0 - (focal_dx + focal_dy) * 1.5)

    # Natural light (10%): penalise large items blocking top-wall windows (y < 0.15).
    # Two exemptions. Pinned pieces: the user asked for them there ("move the desk to the
    # window"), so counting them scores obedience as a defect. Underlays: `h` is depth in
    # plan, not height — a 0.24-deep rug trips the size test while being flat on the floor
    # and physically incapable of blocking anything.
    windows = space_info.get("windows") or []
    blocking = sum(
        1 for item in items
        if item.y < 0.15
        and item.h > 0.08
        and not item.pinned
        and not _is_underlay_type(item.type)
    )
    if windows:
        natural_light = max(0.0, 1.0 - blocking / max(len(windows), 1))
    else:
        natural_light = max(0.0, 0.75 - blocking * 0.15)

    # Ergonomics (10%): fraction of pairs with physical gap ≥ 0.40 m
    ERGO_MIN_M = 0.40
    ergonomics = (
        sum(1 for g in gaps_m if g >= ERGO_MIN_M) / len(gaps_m)
    ) if gaps_m else 1.0

    return {
        "circulation": round(circulation, 3),
        "balance": round(balance, 3),
        "focal_point": round(focal_point, 3),
        "natural_light": round(natural_light, 3),
        "ergonomics": round(ergonomics, 3),
    }


def _weighted_score(scores: dict[str, float]) -> float:
    return round(sum(scores.get(k, 0.0) * w for k, w in SOFT_WEIGHTS.items()), 4)


# ─────────────────────────── Geometric optimizer ───────────────────────────

# Overlap is measured as area, so this weight makes a 1%-of-room intersection cost about
# as much as a 0.04 drop in the weighted score — enough that the optimizer never trades
# a real collision for a marginal circulation gain.
_OVERLAP_PENALTY = 4.0


def _layout_objective(items: list[FurnitureItem], space_info: dict) -> float:
    """Soft score minus hard-violation penalties, as a single number to maximise."""
    score = _weighted_score(_score_soft_constraints(items, space_info))

    penalty = 0.0
    n = len(items)
    solid = [not _is_underlay_type(it.type) for it in items]
    for i in range(n):
        a = items[i]
        penalty += max(0.0, -a.x) + max(0.0, -a.y)
        penalty += max(0.0, a.x + a.w - 1.0) + max(0.0, a.y + a.h - 1.0)
        if not solid[i]:
            continue
        for j in range(i + 1, n):
            if not solid[j]:
                continue
            b = items[j]
            ox = min(a.x + a.w, b.x + b.w) - max(a.x, b.x)
            oy = min(a.y + a.h, b.y + b.h) - max(a.y, b.y)
            if ox > 0.0 and oy > 0.0:
                penalty += ox * oy

    return score - _OVERLAP_PENALTY * penalty


def _movable_indices(
    items: list[FurnitureItem], constraints: dict, photo_anchored: bool
) -> list[int]:
    """Which items the optimizer is allowed to move.

    With a photo, every piece the user did not ask to change keeps its original depth
    pixels (see `_classify_preserved`), so repositioning it in the plan changes nothing in
    the render — it only perturbs the score and drags the pieces that *do* matter to worse
    positions. Freezing them makes the search both faster and more faithful to "I only
    asked you to move one thing". Without a photo nothing is preserved, so everything is
    fair game.
    """
    if not photo_anchored:
        return [i for i, it in enumerate(items) if not it.pinned]

    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    touched = _touched_types(constraints)
    return [
        i for i, it in enumerate(items)
        if not it.pinned and normalize_furniture_type(it.type) in touched
    ]


def _optimize_positions(
    items: list[FurnitureItem],
    space_info: dict,
    movable: list[int],
    *,
    steps: int = 2000,
    seed: int = 0,
) -> tuple[list[FurnitureItem], float, int]:
    """Hill-climb furniture positions against `_layout_objective`.

    This replaces asking the LLM to try again. The five soft scores are cheap, purely
    geometric functions of the boxes, so thousands of candidate nudges evaluate in the
    time one LLM round trip takes — and the LLM never had the information to do better
    anyway: `LAYOUT_REFINEMENT_PROMPT` handed it five scalars with no indication of which
    piece was responsible.

    Step size decays from coarse to fine so early moves can escape a bad initial
    arrangement while late ones settle. Seeded, so the same plan optimises identically
    on every run.
    """
    import random

    if not movable or steps <= 0:
        return items, _layout_objective(items, space_info), 0

    rng = random.Random(seed)
    current = _layout_objective(items, space_info)
    best = current
    best_pos = [(it.x, it.y) for it in items]
    accepted = 0

    for step in range(steps):
        sigma = 0.18 * (1.0 - step / steps) + 0.01
        item = items[rng.choice(movable)]
        prev = (item.x, item.y)

        item.x = min(max(item.x + rng.gauss(0.0, sigma), 0.0), max(0.0, 1.0 - item.w))
        item.y = min(max(item.y + rng.gauss(0.0, sigma), 0.0), max(0.0, 1.0 - item.h))

        candidate = _layout_objective(items, space_info)
        if candidate > current:
            current = candidate
            accepted += 1
            if candidate > best:
                best = candidate
                best_pos = [(i.x, i.y) for i in items]
        else:
            item.x, item.y = prev

    for item, (x, y) in zip(items, best_pos):
        item.x, item.y = x, y
    return items, best, accepted


# ─────────────────────────── Hard Constraints ───────────────────────────

def _apply_hard_constraints(
    items: list[FurnitureItem], constraints: dict
) -> list[FurnitureItem]:
    """Enforce must_remove / must_add against the LLM's plan.

    Matching goes through `normalize_furniture_type`, the same collapse the depth
    projection and `_classify_preserved` use. A bare `.lower().replace(" ", "_")` misses
    the modifier forms the planner is explicitly allowed to invent (`low_cabinet`,
    `platform_bed`), so `must_remove: ["cabinet"]` would silently no-op and
    `must_add: ["cabinet"]` would bolt a second cabinet onto a plan that has one.
    """
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    must_remove = {
        normalize_furniture_type(s) for s in (constraints.get("must_remove") or [])
    }
    # Duplicates are kept on purpose: `must_add: ["chair", "chair", "chair"]` means three
    # chairs, not one. What stops a lone `must_add: ["cabinet"]` from bolting a second
    # cabinet onto a plan that already has one is the count-aware pass below, which
    # subtracts what the layout already holds — not de-duplicating the request itself.
    must_add = [
        normalize_furniture_type(s) for s in (constraints.get("must_add") or [])
    ]

    items = [
        item for item in items
        if normalize_furniture_type(item.type) not in must_remove
    ]

    # Count-aware: must_add may list a type multiple times (e.g. 3 chairs). Add as
    # many of each type as requested, minus however many the base layout already has.
    # Types are compared normalized, matching the must_remove filter above.
    from collections import Counter
    desired = Counter(must_add)
    have = Counter(normalize_furniture_type(item.type) for item in items)
    for ftype, want in desired.items():
        w, h = FURNITURE_SIZES.get(ftype, FURNITURE_SIZES["default"])
        for _ in range(max(0, want - have.get(ftype, 0))):
            # spawn near centre with a small scatter; _push_apart spreads them out
            jitter = 0.02 * len([i for i in items if normalize_furniture_type(i.type) == ftype])
            items.append(FurnitureItem(
                f"{ftype}_{len(items)+1}", ftype,
                min(0.9, 0.72 + jitter), min(0.9, 0.72 + jitter), w, h,
            ))

    return items


# ─────────────────────────── must_move enforcement ───────────────────────────

_QUALIFIER_ANCHORS: dict[str, tuple[float, float]] = {
    "left": (0.0, 0.5), "right": (1.0, 0.5),
    "center": (0.5, 0.5), "centre": (0.5, 0.5), "middle": (0.5, 0.5),
    "far": (0.5, 0.0), "back": (0.5, 0.0),
    "near": (0.5, 1.0), "front": (0.5, 1.0),
}

# How far off the wall an item pushed "to the window" ends up sitting.
_WALL_STANDOFF = 0.06


def _opening_anchor(openings: list[dict], inset: float = _WALL_STANDOFF) -> tuple[float, float] | None:
    """Centre of the widest opening, nudged into the room so the item isn't inside the wall."""
    if not openings:
        return None
    widest = max(openings, key=lambda o: float(o.get("w", 0)) * float(o.get("h", 0)))
    cx = float(widest.get("x", 0.5)) + float(widest.get("w", 0.1)) / 2.0
    cy = float(widest.get("y", 0.0)) + float(widest.get("h", 0.1)) / 2.0
    wall = widest.get("wall")
    if wall == "far":
        cy += inset
    elif wall == "near":
        cy -= inset
    elif wall == "left":
        cx += inset
    elif wall == "right":
        cx -= inset
    else:
        cy += inset
    return cx, cy


def _resolve_destination(
    to_text: str, space_info: dict, items: list[FurnitureItem], moving: FurnitureItem
) -> tuple[float, float] | None:
    """`must_move["to"]` free text → a target centre in normalized plan coordinates.

    Only patterns we can resolve unambiguously are honoured; anything else returns None
    and the LLM's own placement stands. Deliberately conservative — a wrong destination
    enforced in code is worse than an imprecise one the planner chose with full context.
    """
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    text = (to_text or "").strip().lower()
    if not text:
        return None

    if "window" in text:
        anchor = _opening_anchor((space_info or {}).get("windows") or [])
        if anchor:
            return anchor
    if "door" in text:
        anchor = _opening_anchor((space_info or {}).get("doors") or [])
        if anchor:
            return anchor

    # "next to the sofa" / "left of the bed" — resolve against another planned piece.
    for other in items:
        if other is moving:
            continue
        name = normalize_furniture_type(other.type).replace("_", " ")
        if name not in text:
            continue
        ocx = other.x + other.w / 2.0
        ocy = other.y + other.h / 2.0
        gap = (other.w + moving.w) / 2.0 + 0.03
        if "left" in text:
            return ocx - gap, ocy
        if "right" in text:
            return ocx + gap, ocy
        if "front" in text or "facing" in text:
            return ocx, ocy + (other.h + moving.h) / 2.0 + 0.06
        if "behind" in text or "back" in text:
            return ocx, ocy - (other.h + moving.h) / 2.0 - 0.06
        return ocx + gap, ocy   # bare "next to" / "beside"

    # Bare wall / region words.
    if "corner" in text:
        cx = 0.0 + _WALL_STANDOFF if "left" in text else 1.0 - _WALL_STANDOFF
        cy = 1.0 - _WALL_STANDOFF if ("near" in text or "front" in text) else _WALL_STANDOFF
        return cx, cy
    for word, (ax, ay) in _QUALIFIER_ANCHORS.items():
        if word in text:
            cx = ax + _WALL_STANDOFF if ax == 0.0 else (ax - _WALL_STANDOFF if ax == 1.0 else ax)
            cy = ay + _WALL_STANDOFF if ay == 0.0 else (ay - _WALL_STANDOFF if ay == 1.0 else ay)
            return cx, cy
    return None


def _pick_move_target(
    matches: list[FurnitureItem], qualifier: str
) -> FurnitureItem:
    """Which of several same-type pieces the user meant, from the analyzer's qualifier."""
    q = (qualifier or "").strip().lower()
    if len(matches) == 1 or not q:
        return max(matches, key=lambda it: it.w * it.h)
    if "left" in q:
        return min(matches, key=lambda it: it.x + it.w / 2.0)
    if "right" in q:
        return max(matches, key=lambda it: it.x + it.w / 2.0)
    if "center" in q or "centre" in q or "middle" in q:
        return min(matches, key=lambda it: abs(it.x + it.w / 2.0 - 0.5))
    return max(matches, key=lambda it: it.w * it.h)


def _enforce_move_ops(
    items: list[FurnitureItem], constraints: dict, space_info: dict
) -> list[FurnitureItem]:
    """Apply must_move in code rather than trusting the planner to have obeyed it.

    Nothing previously enforced must_move at all — it was passed to the LLM as prose and
    that was the end of it. When the destination text resolves to a concrete anchor
    (a window, a door, another piece, a named wall) the item is placed there; when it
    doesn't, the planner's own choice is left alone.
    """
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    for op in constraints.get("must_move") or []:
        if not isinstance(op, dict):
            continue
        target = normalize_furniture_type(str(op.get("target") or ""))
        if not target or target == "default":
            continue

        matches = [it for it in items if normalize_furniture_type(it.type) == target]
        if not matches:
            # The planner dropped the piece the user asked to relocate — put it back.
            w, h = FURNITURE_SIZES.get(target, FURNITURE_SIZES["default"])
            restored = FurnitureItem(f"{target}_{len(items) + 1}", target, 0.5, 0.5, w, h)
            items.append(restored)
            matches = [restored]
            print(f"[layout_agent] must_move 目標 {target} 不在規劃結果中，已補回")

        chosen = _pick_move_target(matches, str(op.get("qualifier") or ""))
        dest = _resolve_destination(str(op.get("to") or ""), space_info, items, chosen)
        if dest is None:
            print(f"[layout_agent] must_move {target} → '{op.get('to')}' 無法解算，沿用規劃座標")
            continue

        chosen.x = dest[0] - chosen.w / 2.0
        chosen.y = dest[1] - chosen.h / 2.0
        if not chosen.pinned:
            print(
                f"[layout_agent] must_move {target} → '{op.get('to')}' "
                f"落點 ({chosen.x:.2f}, {chosen.y:.2f})"
            )
        chosen.pinned = True

    return items


def _enforce_immutable(
    items: list[FurnitureItem], regions: list[dict]
) -> list[FurnitureItem]:
    """Push items out of immutable regions (door/window clearance zones)."""
    for region in regions:
        rx = float(region.get("x", 0))
        ry = float(region.get("y", 0))
        rw = float(region.get("w", 0.1))
        rh = float(region.get("h", 0.1))
        for item in items:
            if (item.x + item.w > rx and item.x < rx + rw
                    and item.y + item.h > ry and item.y < ry + rh):
                candidate_x = rx - item.w - 0.03
                item.x = candidate_x if candidate_x >= 0 else rx + rw + 0.03
    return items


def _enforce_wall_anchor(
    items: list[FurnitureItem], space_info: dict, params: dict
) -> list[FurnitureItem]:
    """Snap wall-anchored furniture to the nearest wall if floating in the room."""
    wall_anchored = set(params.get("wall_anchored", []))
    snap_threshold = float(params.get("snap_threshold", 0.12))
    pad = float(params.get("pad", 0.02))
    for item in items:
        if item.type not in wall_anchored:
            continue
        d_t = item.y
        d_b = 1.0 - (item.y + item.h)
        d_l = item.x
        d_r = 1.0 - (item.x + item.w)
        if min(d_t, d_b, d_l, d_r) <= snap_threshold:
            continue
        if d_t <= d_b and d_t <= d_l and d_t <= d_r:
            item.y = pad
        elif d_b <= d_l and d_b <= d_r:
            item.y = 1.0 - item.h - pad
        elif d_l <= d_r:
            item.x = pad
        else:
            item.x = 1.0 - item.w - pad
    return items


def _build_semantic_gap_map(params: dict) -> dict[frozenset, float]:
    result: dict[frozenset, float] = {}
    for pair in params.get("pairs", []):
        types = pair.get("types", [])
        gap = float(pair.get("gap", 0.0))
        if len(types) == 2:
            result[frozenset(types)] = gap
    return result


def _enforce_semantic_gaps(
    items: list[FurnitureItem], space_info: dict, params: dict
) -> list[FurnitureItem]:
    """Push semantically incompatible furniture pairs apart to their required minimum gap."""
    gap_map = _build_semantic_gap_map(params)
    iterations = int(params.get("iterations", 30))
    for _ in range(iterations):
        moved = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if _is_underlay_type(a.type) or _is_underlay_type(b.type):
                    continue
                gap = gap_map.get(frozenset({a.type, b.type}))
                if gap is None or not _overlaps(a, b, margin=gap):
                    continue
                acx, acy = a.x + a.w / 2, a.y + a.h / 2
                bcx, bcy = b.x + b.w / 2, b.y + b.h / 2
                dx, dy = acx - bcx, acy - bcy
                ox = (a.x + a.w + gap) - b.x if dx >= 0 else b.x + b.w + gap - a.x
                oy = (a.y + a.h + gap) - b.y if dy >= 0 else b.y + b.h + gap - a.y
                if abs(ox) <= abs(oy):
                    half = ox / 2
                    a.x += half * (1 if dx >= 0 else -1)
                    b.x -= half * (1 if dx >= 0 else -1)
                else:
                    half = oy / 2
                    a.y += half * (1 if dy >= 0 else -1)
                    b.y -= half * (1 if dy >= 0 else -1)
                moved = True
        if not moved:
            break
    return items


def _enforce_bed_clearance(
    items: list[FurnitureItem], space_info: dict, params: dict
) -> list[FurnitureItem]:
    """Ensure each bed has at least one accessible side (left or right) free of obstruction."""
    side_clearance = float(params.get("side_clearance", 0.06))
    beds = [i for i in items if i.type == "bed"]
    others = [i for i in items if i.type != "bed"]

    for bed in beds:
        def _zone_clear(zx: float, zy: float, zw: float, zh: float) -> bool:
            return all(
                o.x + o.w <= zx or o.x >= zx + zw or
                o.y + o.h <= zy or o.y >= zy + zh
                for o in others
            )

        left_ok = bed.x >= side_clearance and _zone_clear(
            bed.x - side_clearance, bed.y, side_clearance, bed.h
        )
        right_ok = bed.x + bed.w + side_clearance <= 1.0 and _zone_clear(
            bed.x + bed.w, bed.y, side_clearance, bed.h
        )
        if left_ok or right_ok:
            continue
        for other in others:
            if (other.x < bed.x + bed.w + side_clearance and
                    other.x + other.w > bed.x + bed.w and
                    other.y < bed.y + bed.h and other.y + other.h > bed.y):
                other.x = bed.x + bed.w + side_clearance

    return items


def _enforce_desk_bed_separation(
    items: list[FurnitureItem], space_info: dict, params: dict
) -> list[FurnitureItem]:
    """Push desks away from beds and bunk beds so no part of the desk overlaps the bed area.
    Only the desk is moved — beds are wall-anchored and stay put.
    """
    M = float(params.get("min_gap", 0.10))
    bed_types = set(params.get("bed_types", ["bed", "bunk_bed"]))
    iterations = int(params.get("iterations", 40))
    pad = float(params.get("pad", 0.02))

    for _ in range(iterations):
        moved = False
        for desk in (i for i in items if i.type == "desk"):
            for bed in (i for i in items if i.type in bed_types):
                if not _overlaps(desk, bed, margin=M):
                    continue
                dcx = desk.x + desk.w / 2
                dcy = desk.y + desk.h / 2
                bcx = bed.x + bed.w / 2
                bcy = bed.y + bed.h / 2
                dx, dy = dcx - bcx, dcy - bcy
                ox = (desk.x + desk.w + M) - bed.x if dx >= 0 else bed.x + bed.w + M - desk.x
                oy = (desk.y + desk.h + M) - bed.y if dy >= 0 else bed.y + bed.h + M - desk.y
                if abs(ox) <= abs(oy):
                    desk.x += ox * (1 if dx >= 0 else -1)
                else:
                    desk.y += oy * (1 if dy >= 0 else -1)
                desk.x = max(pad, min(1.0 - desk.w - pad, desk.x))
                desk.y = max(pad, min(1.0 - desk.h - pad, desk.y))
                moved = True
        if not moved:
            break
    return items


def _enforce_bunk_bed_ladder_clearance(
    items: list[FurnitureItem], space_info: dict, params: dict
) -> list[FurnitureItem]:
    """Ensure each bunk bed has at least one side clear at floor level for ladder access.
    Checks all 4 sides; if none is clear, pushes obstructing items away from the bottom side
    (most natural ladder placement).
    """
    LC = float(params.get("ladder_clearance", 0.08))
    bunk_beds = [i for i in items if i.type == "bunk_bed"]
    others = [i for i in items if i.type != "bunk_bed"]

    for bed in bunk_beds:
        def _zone_clear(zx: float, zy: float, zw: float, zh: float) -> bool:
            return all(
                o.x + o.w <= zx or o.x >= zx + zw or
                o.y + o.h <= zy or o.y >= zy + zh
                for o in others
            )

        top_ok    = bed.y >= LC and _zone_clear(bed.x, bed.y - LC, bed.w, LC)
        bottom_ok = bed.y + bed.h + LC <= 1.0 and _zone_clear(bed.x, bed.y + bed.h, bed.w, LC)
        left_ok   = bed.x >= LC and _zone_clear(bed.x - LC, bed.y, LC, bed.h)
        right_ok  = bed.x + bed.w + LC <= 1.0 and _zone_clear(bed.x + bed.w, bed.y, LC, bed.h)

        if top_ok or bottom_ok or left_ok or right_ok:
            continue

        for other in others:
            if (other.x < bed.x + bed.w and other.x + other.w > bed.x
                    and other.y < bed.y + bed.h + LC
                    and other.y + other.h > bed.y + bed.h):
                other.y = bed.y + bed.h + LC

    return items


_LADDER_WALL_THRESHOLD = 0.05  # side is "against wall" if bed edge within this distance

def _inject_bunk_bed_ladder(items: list[FurnitureItem]) -> list[FurnitureItem]:
    """Place a bunk_ladder item next to each bunk_bed on its clearest floor-accessible side.

    Only non-wall sides are considered — the ladder must start from open floor space,
    not be sandwiched between the bed and a wall.
    Prefers foot-end (bottom) → right → left → head-end (top).
    Safe to call every iteration — skips beds that already have a ladder.
    """
    PAD = 0.02
    base_lw, base_lh = FURNITURE_SIZES["bunk_ladder"]

    others = [i for i in items if i.type not in ("bunk_bed", "bunk_ladder")]
    existing_ids = {i.id for i in items if i.type == "bunk_ladder"}
    new_ladders: list[FurnitureItem] = []

    for bed in (i for i in items if i.type == "bunk_bed"):
        ladder_id = f"bunk_ladder_{bed.id}"
        if ladder_id in existing_ids:
            continue

        def _zone_clear(zx: float, zy: float, zw: float, zh: float) -> bool:
            if zx < PAD or zy < PAD or zx + zw > 1.0 - PAD or zy + zh > 1.0 - PAD:
                return False
            return all(
                o.x + o.w <= zx or o.x >= zx + zw or
                o.y + o.h <= zy or o.y >= zy + zh
                for o in others
            )

        # Detect which sides are wall-adjacent — ladder cannot start from a wall
        wall_top    = bed.y <= _LADDER_WALL_THRESHOLD
        wall_bottom = 1.0 - (bed.y + bed.h) <= _LADDER_WALL_THRESHOLD
        wall_left   = bed.x <= _LADDER_WALL_THRESHOLD
        wall_right  = 1.0 - (bed.x + bed.w) <= _LADDER_WALL_THRESHOLD

        cx = bed.x + (bed.w - base_lw) / 2
        cy = bed.y + (bed.h - base_lw) / 2

        # (priority, lx, ly, lw, lh) — only non-wall sides eligible
        attempts: list[tuple[float, float, float, float, float]] = []

        if not wall_bottom:
            lx, ly = cx, bed.y + bed.h + PAD
            if _zone_clear(lx, ly, base_lw, base_lh):
                attempts.append((3.0, lx, ly, base_lw, base_lh))

        if not wall_right:
            lx, ly = bed.x + bed.w + PAD, cy
            if _zone_clear(lx, ly, base_lh, base_lw):
                attempts.append((2.0, lx, ly, base_lh, base_lw))

        if not wall_left:
            lx, ly = bed.x - base_lh - PAD, cy
            if _zone_clear(lx, ly, base_lh, base_lw):
                attempts.append((1.0, lx, ly, base_lh, base_lw))

        if not wall_top:
            lx, ly = cx, bed.y - base_lh - PAD
            if _zone_clear(lx, ly, base_lw, base_lh):
                attempts.append((0.0, lx, ly, base_lw, base_lh))

        if not attempts:
            continue

        _, lx, ly, lw, lh = max(attempts, key=lambda a: a[0])
        new_ladders.append(FurnitureItem(
            id=ladder_id, type="bunk_ladder",
            x=max(PAD, min(1.0 - lw - PAD, lx)),
            y=max(PAD, min(1.0 - lh - PAD, ly)),
            w=lw, h=lh,
        ))

    return items + new_ladders


def _enforce_bed_not_near_window(
    items: list[FurnitureItem], space_info: dict, params: dict
) -> list[FurnitureItem]:
    """Push beds and bunk beds away from window openings on any wall."""
    windows = space_info.get("windows") or []
    wc = float(params.get("window_clearance", 0.08))
    pad = float(params.get("pad", 0.02))
    bed_types = set(params.get("bed_types", ["bed", "bunk_bed"]))

    for item in items:
        if item.type not in bed_types:
            continue
        for window in windows:
            wx = float(window.get("x", 0.5))
            wy = float(window.get("y", 0.0))
            ww = float(window.get("w", 0.15))
            wh = float(window.get("h", ww))

            # `wall` is authoritative when present: a left-wall window starting near the
            # far end has wy ≤ 0.15 too, and the positional fallback would call it a
            # far-wall window and push the bed along the wrong axis.
            wall = window.get("wall")
            if wall == "left" or (wall is None and wx <= 0.15 and wy > 0.15):
                if item.x < wc and item.y + item.h > wy and item.y < wy + wh:
                    item.x = wc + pad
                continue
            if wall == "right" or (wall is None and wx >= 0.85 and wy > 0.15):
                if (item.x + item.w > 1.0 - wc
                        and item.y + item.h > wy and item.y < wy + wh):
                    item.x = 1.0 - wc - item.w - pad
                continue

            if wy <= 0.15:
                if item.y < wc and item.x + item.w > wx and item.x < wx + ww:
                    item.y = wc + pad
            elif wy >= 0.85:
                if (item.y + item.h > 1.0 - wc
                        and item.x + item.w > wx and item.x < wx + ww):
                    item.y = 1.0 - wc - item.h - pad
            elif wx <= 0.15:
                if item.x < wc and item.y + item.h > wy and item.y < wy + wh:
                    item.x = wc + pad
            elif wx >= 0.85:
                if (item.x + item.w > 1.0 - wc
                        and item.y + item.h > wy and item.y < wy + wh):
                    item.x = 1.0 - wc - item.w - pad
    return items


_LAYOUT_ENFORCERS: dict[str, Callable] = {
    "wall_anchor":               _enforce_wall_anchor,
    "semantic_gaps":             _enforce_semantic_gaps,
    "desk_bed_separation":       _enforce_desk_bed_separation,
    "bed_clearance":             _enforce_bed_clearance,
    "bunk_bed_ladder_clearance": _enforce_bunk_bed_ladder_clearance,
    "bed_not_near_window":       _enforce_bed_not_near_window,
}



def _touched_types(constraints: dict[str, Any] | None) -> frozenset[str]:
    """使用者明確要求變動的家具 type（新增／刪除／移動），已正規化。"""
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    constraints = constraints or {}
    touched: set[str] = set()
    for key in ("must_add", "must_remove"):
        for s in constraints.get(key) or []:
            touched.add(normalize_furniture_type(str(s)))
    for op in constraints.get("must_move") or []:
        target = op.get("target") if isinstance(op, dict) else op
        if target:
            touched.add(normalize_furniture_type(str(target)))
    return frozenset(touched)
