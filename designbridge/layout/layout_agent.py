# designbridge/layout_agent.py
"""Layout Agent: furniture placement planning with hard and soft constraints."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from designbridge.core.config import Config
from designbridge.layout.layout_constraints import get_layout_constraint_registry


FURNITURE_SIZES: dict[str, tuple[float, float]] = {
    "sofa": (0.30, 0.13),
    "loveseat": (0.22, 0.12),
    "coffee_table": (0.15, 0.10),
    "tv_unit": (0.22, 0.07),
    "tv": (0.22, 0.06),
    "dining_table": (0.20, 0.13),
    "chair": (0.08, 0.08),
    "armchair": (0.11, 0.11),
    "bed": (0.22, 0.28),
    "bunk_bed": (0.22, 0.30),
    "bunk_ladder": (0.06, 0.08),
    "wardrobe": (0.18, 0.08),
    "desk": (0.16, 0.09),
    "bookshelf": (0.10, 0.05),
    "side_table": (0.07, 0.07),
    "nightstand": (0.07, 0.07),
    "lamp": (0.04, 0.04),
    "rug": (0.32, 0.22),
    "plant": (0.06, 0.06),
    "cabinet": (0.14, 0.07),
    "dresser": (0.14, 0.09),
    "shelf": (0.10, 0.05),
    "default": (0.12, 0.10),
}

FURNITURE_COLORS: dict[str, tuple[int, int, int]] = {
    "sofa": (100, 149, 237),
    "loveseat": (120, 160, 240),
    "bed": (147, 112, 219),
    "bunk_bed": (110, 80, 190),
    "bunk_ladder": (160, 120, 70),
    "dining_table": (205, 133, 63),
    "desk": (70, 130, 180),
    "coffee_table": (176, 196, 222),
    "tv_unit": (105, 105, 105),
    "tv": (80, 80, 80),
    "wardrobe": (139, 90, 43),
    "chair": (188, 143, 143),
    "armchair": (180, 130, 130),
    "rug": (210, 180, 140),
    "bookshelf": (160, 120, 80),
    "shelf": (160, 120, 80),
    "nightstand": (180, 160, 120),
    "side_table": (180, 160, 120),
    "dresser": (150, 110, 70),
    "cabinet": (130, 100, 70),
    "lamp": (255, 220, 100),
    "plant": (80, 160, 80),
    "default": (150, 200, 150),
}

SOFT_WEIGHTS = {
    "circulation": 0.35,
    "balance": 0.25,
    "focal_point": 0.20,
    "natural_light": 0.10,
    "ergonomics": 0.10,
}



@dataclass
class FurnitureItem:
    id: str
    type: str
    x: float   # normalized [0,1] — left edge
    y: float   # normalized [0,1] — top edge
    w: float
    h: float
    rotation: float = 0.0
    # Set when `_enforce_move_ops` placed this piece at a destination the user named.
    # Not serialized — it is a within-run marker telling the optimizer to leave it alone
    # and the scorer not to penalise it for being exactly where it was asked to go.
    pinned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "w": round(self.w, 4),
            "h": round(self.h, 4),
            "rotation": self.rotation,
        }


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


# ─────────────────────────── LLM Interface ───────────────────────────

def _parse_llm_layout(text: str) -> list[dict] | None:
    text = text.strip()
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    if not text.startswith("{"):
        start = text.find("{")
        if start != -1:
            text = text[start:]
    if not text.endswith("}"):
        end = text.rfind("}")
        if end != -1:
            text = text[: end + 1]
    try:
        data = json.loads(text)
        return data.get("furniture") or []
    except Exception:
        return None


def _call_llm_layout(prompt: str) -> list[FurnitureItem]:
    from designbridge.render.llm import call_llm

    text = call_llm(prompt)
    furniture_list = _parse_llm_layout(text)
    if not furniture_list:
        return []

    items: list[FurnitureItem] = []
    for f in furniture_list:
        ftype = str(f.get("type", "default")).lower().replace(" ", "_")
        dw, dh = FURNITURE_SIZES.get(ftype, FURNITURE_SIZES["default"])
        items.append(
            FurnitureItem(
                id=str(f.get("id", f"{ftype}_{len(items)+1}")),
                type=ftype,
                x=max(0.0, min(0.95, float(f.get("x", 0.1)))),
                y=max(0.0, min(0.95, float(f.get("y", 0.1)))),
                w=float(f.get("w", dw)),
                h=float(f.get("h", dh)),
                rotation=float(f.get("rotation", 0)),
            )
        )
    return items


# ───────────────────── Parse an uploaded floor-plan image ─────────────────────

# Vocabulary we constrain Gemini to, so parsed types line up with FURNITURE_SIZES,
# heights, semantic shapes and floor-plan colors downstream.
_KNOWN_FURNITURE_TYPES = sorted(k for k in FURNITURE_SIZES if k != "default")


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
        "of furniture drawn in it and return each one's position as a normalized "
        "bounding box.\n"
        "Coordinate system: origin at the TOP-LEFT of the room interior. "
        "x = 0 is the left wall → 1 is the right wall; y = 0 is the back/top wall → "
        "1 is the front/bottom wall. (x, y) is the TOP-LEFT corner of the footprint; "
        "(w, h) are its width and height. All four values are floats in [0, 1].\n"
        f"Use ONLY these furniture type keywords (map synonyms to the closest one): "
        f"{types_csv}. Skip any symbol you cannot confidently classify.\n"
        "Return STRICT JSON only, no prose, no markdown fences:\n"
        '{"furniture":[{"type":"sofa","x":0.05,"y":0.30,"w":0.30,"h":0.13}]}'
    )

    try:
        text = call_llm(prompt, images=[image_path])
    except Exception as e:  # noqa: BLE001
        print(f"⚠️  Gemini floor-plan parse failed: {e}")
        return None

    raw = _parse_llm_layout(text)
    if not raw:
        print("⚠️  Gemini floor-plan parse returned no furniture")
        return None

    items: list[FurnitureItem] = []
    for i, f in enumerate(raw):
        ftype = str(f.get("type", "default")).lower().replace(" ", "_")
        if ftype not in FURNITURE_SIZES:
            ftype = "default"
        dw, dh = FURNITURE_SIZES.get(ftype, FURNITURE_SIZES["default"])
        try:
            x = float(f.get("x", 0.1))
            y = float(f.get("y", 0.1))
            w = float(f.get("w", dw) or dw)
            h = float(f.get("h", dh) or dh)
        except (TypeError, ValueError):
            continue
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


# ───────────────────────── Default Fallback Layouts ───────────────────────────

def _default_layout(room_type: str) -> list[FurnitureItem]:
    presets: dict[str, list[FurnitureItem]] = {
        "living_room": [
            FurnitureItem("sofa_1", "sofa", 0.10, 0.58, 0.30, 0.13),
            FurnitureItem("coffee_table_1", "coffee_table", 0.18, 0.46, 0.15, 0.10),
            FurnitureItem("tv_unit_1", "tv_unit", 0.28, 0.08, 0.22, 0.07),
            FurnitureItem("armchair_1", "armchair", 0.52, 0.52, 0.11, 0.11),
            FurnitureItem("rug_1", "rug", 0.08, 0.42, 0.38, 0.24),
            FurnitureItem("plant_1", "plant", 0.76, 0.10, 0.06, 0.06),
        ],
        "bedroom": [
            FurnitureItem("bed_1", "bed", 0.30, 0.28, 0.22, 0.28),
            FurnitureItem("wardrobe_1", "wardrobe", 0.08, 0.08, 0.18, 0.08),
            FurnitureItem("nightstand_1", "nightstand", 0.24, 0.35, 0.07, 0.07),
            FurnitureItem("nightstand_2", "nightstand", 0.55, 0.35, 0.07, 0.07),
            FurnitureItem("dresser_1", "dresser", 0.68, 0.08, 0.14, 0.09),
        ],
        "kitchen": [
            FurnitureItem("cabinet_1", "cabinet", 0.05, 0.05, 0.30, 0.08),
            FurnitureItem("shelf_1", "shelf", 0.65, 0.05, 0.18, 0.05),
        ],
        "dining_room": [
            FurnitureItem("dining_table_1", "dining_table", 0.30, 0.38, 0.20, 0.15),
            FurnitureItem("chair_1", "chair", 0.22, 0.40, 0.08, 0.08),
            FurnitureItem("chair_2", "chair", 0.52, 0.40, 0.08, 0.08),
            FurnitureItem("chair_3", "chair", 0.35, 0.30, 0.08, 0.08),
            FurnitureItem("chair_4", "chair", 0.35, 0.52, 0.08, 0.08),
        ],
        "study": [
            FurnitureItem("desk_1", "desk", 0.32, 0.08, 0.16, 0.09),
            FurnitureItem("chair_1", "chair", 0.37, 0.18, 0.08, 0.08),
            FurnitureItem("bookshelf_1", "bookshelf", 0.08, 0.08, 0.10, 0.05),
            FurnitureItem("bookshelf_2", "bookshelf", 0.08, 0.15, 0.10, 0.05),
            FurnitureItem("armchair_1", "armchair", 0.65, 0.55, 0.11, 0.11),
            FurnitureItem("side_table_1", "side_table", 0.62, 0.53, 0.07, 0.07),
        ],
    }
    return list(presets.get(room_type, presets["living_room"]))


# ─────────────────────────── Floor Plan Image ───────────────────────────

_FURNITURE_LABEL_MAP: dict[str, str] = {
    "sofa": "Sofa", "loveseat": "Loveseat", "coffee_table": "Coffee Table",
    "tv_unit": "TV Unit", "tv": "TV", "dining_table": "Dining Table",
    "chair": "Chair", "armchair": "Armchair", "bed": "Bed",
    "bunk_bed": "Bunk Bed", "bunk_ladder": "Ladder",
    "wardrobe": "Wardrobe", "desk": "Desk", "bookshelf": "Bookshelf",
    "side_table": "Side Table", "nightstand": "Nightstand",
    "lamp": "Lamp", "rug": "Rug", "plant": "Plant",
    "cabinet": "Cabinet", "dresser": "Dresser", "shelf": "Shelf",
}

_ROOM_LABEL_MAP: dict[str, str] = {
    "living_room": "LIVING ROOM", "bedroom": "BEDROOM",
    "kitchen": "KITCHEN", "dining_room": "DINING ROOM", "study": "STUDY",
}


def _build_floor_plan_svg(items: list[FurnitureItem], room_type: str) -> str:
    W, H = 800, 800
    M = 80    # outer margin
    R = W - 2 * M   # room box size (640px)
    WT = 16   # wall thickness
    RI = R - 2 * WT  # interior room size (608px)

    def px(v: float) -> float: return M + WT + v * RI
    def py(v: float) -> float: return M + WT + v * RI
    def pw(v: float) -> float: return v * RI
    def ph(v: float) -> float: return v * RI

    lines: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        # White background
        f'<rect width="{W}" height="{H}" fill="white"/>',
        # Wall body (gray = solid concrete/masonry)
        f'<rect x="{M}" y="{M}" width="{R}" height="{R}" fill="#c8c8c8" stroke="#1a1a1a" stroke-width="2.5"/>',
        # Interior floor (off-white)
        f'<rect x="{M+WT}" y="{M+WT}" width="{RI}" height="{RI}" fill="#f8f6f0"/>',
    ]

    # Light grid lines
    for i in range(1, 5):
        gx = M + WT + i * RI // 5
        gy = M + WT + i * RI // 5
        lines.append(f'<line x1="{gx}" y1="{M+WT}" x2="{gx}" y2="{M+WT+RI}" stroke="#e0ddd6" stroke-width="1"/>')
        lines.append(f'<line x1="{M+WT}" y1="{gy}" x2="{M+WT+RI}" y2="{gy}" stroke="#e0ddd6" stroke-width="1"/>')

    # Door — bottom center (gap + swing arc)
    dcx = M + WT + RI // 2
    door_w = 48
    bot_wall_y = M + R - WT
    lines.append(f'<rect x="{dcx - door_w//2}" y="{bot_wall_y - 1}" width="{door_w}" height="{WT + 3}" fill="white"/>')
    lines.append(f'<line x1="{dcx - door_w//2}" y1="{bot_wall_y}" x2="{dcx - door_w//2}" y2="{bot_wall_y - door_w}" stroke="#555" stroke-width="1.5"/>')
    lines.append(f'<path d="M {dcx - door_w//2} {bot_wall_y - door_w} A {door_w} {door_w} 0 0 1 {dcx + door_w//2} {bot_wall_y}" stroke="#555" stroke-width="1.2" fill="none" stroke-dasharray="5,3"/>')

    # Window — top center (blue glazing)
    wcx = M + WT + RI // 2
    win_w = 70
    lines.append(f'<rect x="{wcx - win_w//2}" y="{M}" width="{win_w}" height="{WT}" fill="#c0daf8" stroke="#2e6ab5" stroke-width="1.5"/>')
    lines.append(f'<line x1="{wcx}" y1="{M}" x2="{wcx}" y2="{M + WT}" stroke="#2e6ab5" stroke-width="1.5"/>')

    # Furniture
    for item in items:
        fx1 = px(item.x)
        fy1 = py(item.y)
        fw  = pw(item.w)
        fh  = ph(item.h)
        fx2 = fx1 + fw
        fy2 = fy1 + fh
        fcx = fx1 + fw / 2
        fcy = fy1 + fh / 2

        r, g, b = FURNITURE_COLORS.get(item.type, FURNITURE_COLORS["default"])
        fill = f"rgb({r},{g},{b})"

        if item.type in ("chair", "armchair"):
            rad = max(5.0, min(fw, fh) / 2 - 1)
            lines.append(f'<circle cx="{fcx:.1f}" cy="{fcy:.1f}" r="{rad:.1f}" fill="{fill}" fill-opacity="0.55" stroke="#333" stroke-width="1.5"/>')
            if item.type == "armchair":
                br = rad + 4
                lines.append(f'<path d="M {fcx-br:.1f} {fcy:.1f} A {br} {br} 0 0 1 {fcx+br:.1f} {fcy:.1f}" stroke="#333" stroke-width="2.2" fill="none"/>')

        elif item.type == "plant":
            rad = max(5.0, min(fw, fh) / 2 - 1)
            lines.append(f'<circle cx="{fcx:.1f}" cy="{fcy:.1f}" r="{rad:.1f}" fill="{fill}" fill-opacity="0.65" stroke="#2a6a2a" stroke-width="1.5"/>')
            lines.append(f'<line x1="{fcx:.1f}" y1="{fy1+2:.1f}" x2="{fcx:.1f}" y2="{fy2-2:.1f}" stroke="#2a6a2a" stroke-width="1"/>')
            lines.append(f'<line x1="{fx1+2:.1f}" y1="{fcy:.1f}" x2="{fx2-2:.1f}" y2="{fcy:.1f}" stroke="#2a6a2a" stroke-width="1"/>')

        elif item.type == "lamp":
            rad = max(4.0, min(fw, fh) / 2)
            lines.append(f'<circle cx="{fcx:.1f}" cy="{fcy:.1f}" r="{rad:.1f}" fill="{fill}" fill-opacity="0.8" stroke="#b09000" stroke-width="1.5"/>')

        else:
            fw_r = max(4.0, fw)
            fh_r = max(4.0, fh)
            lines.append(f'<rect x="{fx1:.1f}" y="{fy1:.1f}" width="{fw_r:.1f}" height="{fh_r:.1f}" fill="{fill}" fill-opacity="0.45" stroke="#333" stroke-width="1.5" rx="2"/>')

            if item.type == "sofa" and fw > 40:
                n = max(2, int(fw / 30))
                for k in range(1, n):
                    lx = fx1 + k * fw / n
                    lines.append(f'<line x1="{lx:.1f}" y1="{fy1+3:.1f}" x2="{lx:.1f}" y2="{fy2-3:.1f}" stroke="#555" stroke-width="0.9"/>')
                bk_y = fy1 + fh * 0.32
                lines.append(f'<line x1="{fx1+2:.1f}" y1="{bk_y:.1f}" x2="{fx2-2:.1f}" y2="{bk_y:.1f}" stroke="#555" stroke-width="1.3"/>')

            elif item.type in ("bed", "bunk_bed") and fw > 32:
                hb_h = max(4.0, fh * 0.13)
                lines.append(f'<rect x="{fx1:.1f}" y="{fy1:.1f}" width="{fw_r:.1f}" height="{hb_h:.1f}" fill="#888" stroke="#444" stroke-width="1"/>')
                pl_w = fw * 0.37
                pl_h = max(4.0, fh * 0.22)
                pl_y = fy1 + hb_h + 3
                lines.append(f'<rect x="{fx1+3:.1f}" y="{pl_y:.1f}" width="{pl_w:.1f}" height="{pl_h:.1f}" fill="white" stroke="#666" stroke-width="0.9" rx="3"/>')
                if fw > 55:
                    lines.append(f'<rect x="{fx2-pl_w-3:.1f}" y="{pl_y:.1f}" width="{pl_w:.1f}" height="{pl_h:.1f}" fill="white" stroke="#666" stroke-width="0.9" rx="3"/>')

            elif item.type in ("desk", "dining_table", "coffee_table") and fw > 28:
                lines.append(f'<line x1="{fcx:.1f}" y1="{fy1+2:.1f}" x2="{fcx:.1f}" y2="{fy2-2:.1f}" stroke="#666" stroke-width="0.8"/>')
                lines.append(f'<line x1="{fx1+2:.1f}" y1="{fcy:.1f}" x2="{fx2-2:.1f}" y2="{fcy:.1f}" stroke="#666" stroke-width="0.8"/>')

            elif item.type == "wardrobe" and fw > 28:
                lines.append(f'<line x1="{fcx:.1f}" y1="{fy1:.1f}" x2="{fcx:.1f}" y2="{fy2:.1f}" stroke="#555" stroke-width="1.2"/>')
                lines.append(f'<circle cx="{fcx-4:.1f}" cy="{fcy:.1f}" r="2.5" fill="#555"/>')
                lines.append(f'<circle cx="{fcx+4:.1f}" cy="{fcy:.1f}" r="2.5" fill="#555"/>')

            elif item.type in ("bookshelf", "shelf") and fh > 14:
                n = max(2, int(fh / 12))
                for k in range(1, n):
                    sy = fy1 + k * fh / n
                    lines.append(f'<line x1="{fx1+1:.1f}" y1="{sy:.1f}" x2="{fx2-1:.1f}" y2="{sy:.1f}" stroke="#666" stroke-width="0.9"/>')

            elif item.type == "rug" and fw > 28:
                pad2 = min(7.0, fw * 0.09)
                lines.append(f'<rect x="{fx1+pad2:.1f}" y="{fy1+pad2:.1f}" width="{fw-pad2*2:.1f}" height="{fh-pad2*2:.1f}" fill="none" stroke="#999" stroke-width="0.9" stroke-dasharray="5,3"/>')

            elif item.type == "tv_unit" and fw > 28:
                lines.append(f'<rect x="{fx1+fw*0.15:.1f}" y="{fy1+fh*0.15:.1f}" width="{fw*0.7:.1f}" height="{fh*0.7:.1f}" fill="#555" stroke="#333" stroke-width="0.8" rx="1"/>')

        # Label
        label = _FURNITURE_LABEL_MAP.get(item.type, item.type.replace("_", " ").title())
        short = label if len(label) <= 9 else label[:8] + "."
        if fw >= 24 and fh >= 12:
            fs = int(max(8, min(11, fw / 5.5)))
            lines.append(f'<text x="{fcx:.1f}" y="{fcy+1:.1f}" font-family="Arial,Helvetica,sans-serif" font-size="{fs}" text-anchor="middle" dominant-baseline="middle" fill="#111">{short}</text>')

    # Room title — top-left inside wall
    room_label = _ROOM_LABEL_MAP.get(room_type, room_type.upper().replace("_", " "))
    lines.append(f'<text x="{M+WT+10}" y="{M+WT+22}" font-family="Arial,Helvetica,sans-serif" font-size="15" font-weight="bold" fill="#222">{room_label}</text>')

    # North arrow — top-right
    na_x, na_y = M + R - 24, M + 30
    lines.append(f'<polygon points="{na_x},{na_y-14} {na_x-8},{na_y+8} {na_x+8},{na_y+8}" fill="#333"/>')
    lines.append(f'<text x="{na_x}" y="{na_y+21}" font-family="Arial,Helvetica,sans-serif" font-size="12" text-anchor="middle" fill="#333">N</text>')

    # Scale bar — bottom-left inside wall
    sb_x = M + WT + 10
    sb_y = M + WT + RI - 18
    sb_w = RI // 5
    lines.append(f'<rect x="{sb_x}" y="{sb_y-2}" width="{sb_w}" height="4" fill="#444"/>')
    lines.append(f'<text x="{sb_x + sb_w//2}" y="{sb_y+13}" font-family="Arial,Helvetica,sans-serif" font-size="9" text-anchor="middle" fill="#444">1 m</text>')

    lines.append('</svg>')
    return '\n'.join(lines)


def _generate_floor_plan(
    items: list[FurnitureItem],
    task_id: str,
    room_type: str = "living_room",
    room_w: float = 4.0,
    room_d: float = 4.0,
) -> str | None:
    out = Path(Config.ARTIFACTS_DIR) / "layout" / f"{task_id}_floor_plan.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        import cairo
        import math

        W, H = 900, 980   # extra height for title + legend below
        M = 90            # outer margin
        R = 720           # room box size (square)
        WT = 20           # wall thickness
        RI = R - 2 * WT  # interior room span (680px)

        px_per_m_w = RI / room_w

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        ctx = cairo.Context(surface)
        ctx.set_antialias(cairo.ANTIALIAS_BEST)

        def text(s: str, x: float, y: float, size: float = 9, bold: bool = False, center: bool = False):
            ctx.select_font_face(
                "Arial",
                cairo.FONT_SLANT_NORMAL,
                cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
            )
            ctx.set_font_size(size)
            if center:
                ext = ctx.text_extents(s)
                x -= ext.width / 2
            ctx.move_to(x, y)
            ctx.show_text(s)

        # ── White background ──────────────────────────────────────────
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()

        # ── Outer border / title area ─────────────────────────────────
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.5)
        ctx.rectangle(M - 10, M - 40, R + 20, R + 20 + 60)  # full drawing frame
        ctx.stroke()

        # Title bar at top of drawing frame
        ctx.set_source_rgb(0, 0, 0)
        ctx.rectangle(M - 10, M - 40, R + 20, 36)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        room_label = _ROOM_LABEL_MAP.get(room_type, room_type.upper().replace("_", " "))
        text(f"FLOOR PLAN — {room_label}", M, M - 12, size=14, bold=True)
        size_label = f"{room_w:.1f}m × {room_d:.1f}m  ({room_w * room_d:.1f} m²)"
        ctx.set_source_rgb(0.85, 0.85, 0.85)
        text(size_label, M + R - 4, M - 12, size=10)

        # ── Solid black walls ─────────────────────────────────────────
        ctx.set_source_rgb(0.08, 0.08, 0.08)
        ctx.rectangle(M, M, R, R)
        ctx.fill()

        # ── Interior floor (white) ────────────────────────────────────
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(M + WT, M + WT, RI, RI)
        ctx.fill()

        # ── Fine grid (every meter) ───────────────────────────────────
        ctx.set_source_rgba(0.82, 0.82, 0.82, 1)
        ctx.set_line_width(0.6)
        grid_step_w = RI / room_w
        grid_step_d = RI / room_d
        for i in range(1, int(room_w)):
            gx = M + WT + i * grid_step_w
            ctx.move_to(gx, M + WT); ctx.line_to(gx, M + WT + RI); ctx.stroke()
        for j in range(1, int(room_d)):
            gy = M + WT + j * grid_step_d
            ctx.move_to(M + WT, gy); ctx.line_to(M + WT + RI, gy); ctx.stroke()

        # ── Door — bottom center (gap in wall + swing arc) ────────────
        dcx = M + WT + RI / 2
        door_px = min(80.0, px_per_m_w * 0.9)  # ~0.9m door
        bot_y = float(M + R - WT)
        # Erase gap
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(dcx - door_px / 2, bot_y, door_px, WT + 1)
        ctx.fill()
        # Swing
        hinge = dcx - door_px / 2
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.2)
        ctx.move_to(hinge, bot_y); ctx.line_to(hinge, bot_y - door_px); ctx.stroke()
        ctx.set_dash([4, 3])
        ctx.arc(hinge, bot_y, door_px, -math.pi / 2, 0)
        ctx.stroke()
        ctx.set_dash([])
        # Label
        ctx.set_source_rgb(0.3, 0.3, 0.3)
        text("D", dcx - 3, bot_y + WT + 12, size=8)

        # ── Window — top center (three-line convention) ───────────────
        wcx = M + WT + RI / 2
        win_px = min(100.0, px_per_m_w * 1.2)
        # erase wall gap
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(wcx - win_px / 2, M, win_px, WT)
        ctx.fill()
        # three lines (standard window symbol)
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.2)
        for offset in (-win_px / 2, 0.0, win_px / 2):
            ctx.move_to(wcx + offset, M); ctx.line_to(wcx + offset, M + WT); ctx.stroke()
        ctx.set_line_width(0.8)
        ctx.move_to(wcx - win_px / 2, M + WT / 2)
        ctx.line_to(wcx + win_px / 2, M + WT / 2)
        ctx.stroke()
        # Label
        ctx.set_source_rgb(0.3, 0.3, 0.3)
        text("W", wcx - 3, M - 4, size=8)

        # ── Room dimension ticks (outside walls) ─────────────────────
        ctx.set_source_rgb(0.2, 0.2, 0.2)
        ctx.set_line_width(0.8)
        tick = 6
        # Bottom: width
        dim_y = M + R + 16
        ctx.move_to(M, dim_y - tick); ctx.line_to(M, dim_y + tick); ctx.stroke()
        ctx.move_to(M + R, dim_y - tick); ctx.line_to(M + R, dim_y + tick); ctx.stroke()
        ctx.move_to(M, dim_y); ctx.line_to(M + R, dim_y); ctx.stroke()
        ctx.set_source_rgb(0, 0, 0)
        text(f"{room_w:.1f} m", M + R / 2, dim_y + 13, size=9, center=True)
        # Right: depth
        dim_x = M + R + 16
        ctx.set_source_rgb(0.2, 0.2, 0.2)
        ctx.move_to(dim_x - tick, M); ctx.line_to(dim_x + tick, M); ctx.stroke()
        ctx.move_to(dim_x - tick, M + R); ctx.line_to(dim_x + tick, M + R); ctx.stroke()
        ctx.move_to(dim_x, M); ctx.line_to(dim_x, M + R); ctx.stroke()
        ctx.save()
        ctx.translate(dim_x + 14, M + R / 2)
        ctx.rotate(-math.pi / 2)
        ctx.set_source_rgb(0, 0, 0)
        text(f"{room_d:.1f} m", 0, 0, size=9, center=True)
        ctx.restore()

        # ── Furniture (rugs drawn first as floor layer) ───────────────
        ordered = [i for i in items if i.type == "rug"] + [i for i in items if i.type != "rug"]
        for item in ordered:
            fx1 = M + WT + item.x * RI
            fy1 = M + WT + item.y * RI
            fw  = item.w * RI
            fh  = item.h * RI
            fcx = fx1 + fw / 2
            fcy = fy1 + fh / 2
            fx2 = fx1 + fw
            fy2 = fy1 + fh
            fw_r, fh_r = max(4.0, fw), max(4.0, fh)

            # Real-world size in meters
            rw = item.w * room_w
            rd = item.h * room_d

            if item.type in ("chair", "armchair"):
                rad = max(5.0, min(fw, fh) / 2 - 1)
                ctx.set_source_rgb(0.94, 0.94, 0.94)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.2)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.stroke()
                if item.type == "armchair":
                    ctx.set_line_width(2.0)
                    ctx.arc(fcx, fcy, rad + 5, math.pi, 2 * math.pi); ctx.stroke()

            elif item.type == "plant":
                rad = max(5.0, min(fw, fh) / 2 - 1)
                ctx.set_source_rgb(0.9, 0.9, 0.9)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.2)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.stroke()
                ctx.set_line_width(0.8)
                ctx.move_to(fcx, fy1 + 2); ctx.line_to(fcx, fy2 - 2); ctx.stroke()
                ctx.move_to(fx1 + 2, fcy); ctx.line_to(fx2 - 2, fcy); ctx.stroke()

            elif item.type == "lamp":
                rad = max(4.0, min(fw, fh) / 2)
                ctx.set_source_rgb(0.9, 0.9, 0.9)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.2)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.stroke()

            elif item.type == "rug":
                ctx.set_source_rgb(0.92, 0.92, 0.92)
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.fill()
                ctx.set_source_rgb(0.5, 0.5, 0.5)
                ctx.set_line_width(0.8)
                ctx.set_dash([5, 3])
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.stroke()
                pad = min(6.0, fw * 0.08)
                ctx.rectangle(fx1 + pad, fy1 + pad, fw_r - pad * 2, fh_r - pad * 2); ctx.stroke()
                ctx.set_dash([])

            else:
                # Standard rectangular furniture — white fill, black outline
                ctx.set_source_rgb(0.96, 0.96, 0.96)
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.5)
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.stroke()

                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(0.8)

                if item.type == "sofa" and fw > 35:
                    n = max(2, int(fw / 28))
                    for k in range(1, n):
                        lx = fx1 + k * fw / n
                        ctx.move_to(lx, fy1 + 3); ctx.line_to(lx, fy2 - 3); ctx.stroke()
                    bk_y = fy1 + fh * 0.30
                    ctx.set_line_width(1.5)
                    ctx.move_to(fx1 + 1, bk_y); ctx.line_to(fx2 - 1, bk_y); ctx.stroke()

                elif item.type in ("bed", "bunk_bed") and fw > 28:
                    hb_h = max(4.0, fh * 0.14)
                    ctx.set_source_rgb(0.2, 0.2, 0.2)
                    ctx.rectangle(fx1, fy1, fw_r, hb_h); ctx.fill()
                    pl_w = fw * 0.38
                    pl_h = max(4.0, fh * 0.22)
                    pl_y = fy1 + hb_h + 4
                    ctx.set_source_rgb(1, 1, 1)
                    ctx.rectangle(fx1 + 3, pl_y, pl_w, pl_h); ctx.fill()
                    ctx.set_source_rgb(0, 0, 0)
                    ctx.set_line_width(0.8)
                    ctx.rectangle(fx1 + 3, pl_y, pl_w, pl_h); ctx.stroke()
                    if fw > 50:
                        ctx.set_source_rgb(1, 1, 1)
                        ctx.rectangle(fx2 - pl_w - 3, pl_y, pl_w, pl_h); ctx.fill()
                        ctx.set_source_rgb(0, 0, 0)
                        ctx.rectangle(fx2 - pl_w - 3, pl_y, pl_w, pl_h); ctx.stroke()

                elif item.type in ("desk", "dining_table", "coffee_table") and fw > 24:
                    ctx.set_line_width(0.6)
                    ctx.move_to(fcx, fy1 + 2); ctx.line_to(fcx, fy2 - 2); ctx.stroke()
                    ctx.move_to(fx1 + 2, fcy); ctx.line_to(fx2 - 2, fcy); ctx.stroke()

                elif item.type == "wardrobe" and fw > 24:
                    ctx.set_line_width(1.2)
                    ctx.move_to(fcx, fy1); ctx.line_to(fcx, fy2); ctx.stroke()
                    ctx.set_source_rgb(0, 0, 0)
                    ctx.arc(fcx - 5, fcy, 2.5, 0, 2 * math.pi); ctx.fill()
                    ctx.arc(fcx + 5, fcy, 2.5, 0, 2 * math.pi); ctx.fill()

                elif item.type in ("bookshelf", "shelf", "cabinet") and fh > 12:
                    n = max(2, int(fh / 10))
                    for k in range(1, n):
                        sy = fy1 + k * fh / n
                        ctx.move_to(fx1 + 1, sy); ctx.line_to(fx2 - 1, sy); ctx.stroke()

                elif item.type == "tv_unit" and fw > 24:
                    ctx.set_source_rgb(0.15, 0.15, 0.15)
                    ctx.rectangle(fx1 + fw * 0.12, fy1 + fh * 0.12, fw * 0.76, fh * 0.76)
                    ctx.fill()

                elif item.type == "dresser" and fw > 20:
                    n = max(2, int(fw / 18))
                    for k in range(1, n):
                        lx = fx1 + k * fw / n
                        ctx.move_to(lx, fy1); ctx.line_to(lx, fy2); ctx.stroke()
                    ctx.arc(fcx, fcy, 2.5, 0, 2 * math.pi); ctx.fill()

            # ── Furniture label + real-world size ─────────────────────
            if fw >= 20 and fh >= 12:
                label = _FURNITURE_LABEL_MAP.get(item.type, item.type.replace("_", " ").title())
                fs_name = max(7.5, min(10.0, fw / 6.5))
                fs_dim  = max(6.5, min(8.5,  fw / 7.5))

                ctx.set_source_rgb(0.05, 0.05, 0.05)
                # If enough vertical space show name + dims on separate lines
                if fh >= 26:
                    text(label, fcx, fcy - 1, size=fs_name, center=True)
                    dim_str = f"{rw:.2f}×{rd:.2f}m"
                    ctx.set_source_rgb(0.35, 0.35, 0.35)
                    text(dim_str, fcx, fcy + fs_dim + 2, size=fs_dim, center=True)
                else:
                    short = label if len(label) <= 7 else label[:6] + "."
                    text(short, fcx, fcy + 3, size=fs_name, center=True)

        # ── North arrow (top-right, inside title) ─────────────────────
        na_x, na_y = M + R - 8, M - 24
        ctx.set_source_rgb(1, 1, 1)
        ctx.move_to(na_x, na_y - 10); ctx.line_to(na_x - 6, na_y + 6); ctx.line_to(na_x + 6, na_y + 6)
        ctx.close_path(); ctx.fill()
        ctx.set_source_rgb(0.9, 0.9, 0.9)
        text("N", na_x, na_y + 16, size=9, bold=True, center=True)

        # ── Scale bar (bottom, inside frame) ─────────────────────────
        sb_x = M
        sb_y = M + R + 38
        sb_w = int(px_per_m_w)  # 1 meter in pixels
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.5)
        ctx.move_to(sb_x, sb_y); ctx.line_to(sb_x + sb_w, sb_y); ctx.stroke()
        ctx.set_line_width(1)
        for tick_x in (sb_x, sb_x + sb_w):
            ctx.move_to(tick_x, sb_y - 4); ctx.line_to(tick_x, sb_y + 4); ctx.stroke()
        text("0", sb_x - 3, sb_y + 13, size=8)
        text("1 m", sb_x + sb_w - 6, sb_y + 13, size=8)
        ctx.set_source_rgb(0.4, 0.4, 0.4)
        text("SCALE 1:?  (indicative)", sb_x + sb_w + 16, sb_y + 4, size=7)

        # ── Legend ────────────────────────────────────────────────────
        lx, ly = M + R - 200, M + R + 10
        ctx.set_source_rgb(0.3, 0.3, 0.3)
        text("D = Door  |  W = Window  |  Grid = 1 m", lx, ly + 30, size=7.5)

        surface.write_to_png(str(out))
        print(f"[layout_agent] Floor plan saved (pycairo B&W): {out}")
        return str(out)

    except Exception as e:
        print(f"⚠️ pycairo floor plan failed ({e}), falling back to PIL")

    # Fallback: PIL raster
    try:
        from PIL import Image, ImageDraw, ImageFont

        SIZE, MARGIN = 640, 52
        ROOM = SIZE - 2 * MARGIN
        WALL = 10
        img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN],
                       fill=(30, 30, 30), outline=(0, 0, 0), width=WALL)
        draw.rectangle([MARGIN + WALL, MARGIN + WALL,
                        SIZE - MARGIN - WALL, SIZE - MARGIN - WALL],
                       fill=(255, 255, 255))
        try:
            font_sm = font_md = None
            for fp in ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
                if Path(fp).exists():
                    font_sm = ImageFont.truetype(fp, 9)
                    font_md = ImageFont.truetype(fp, 13)
                    break
            if font_sm is None:
                font_sm = font_md = ImageFont.load_default()
        except Exception:
            font_sm = font_md = ImageFont.load_default()
        ROOM_I = ROOM - 2 * WALL
        for item in items:
            x1 = int(MARGIN + WALL + item.x * ROOM_I)
            y1 = int(MARGIN + WALL + item.y * ROOM_I)
            x2 = max(x1 + 6, int(MARGIN + WALL + (item.x + item.w) * ROOM_I))
            y2 = max(y1 + 6, int(MARGIN + WALL + (item.y + item.h) * ROOM_I))
            draw.rectangle([x1, y1, x2, y2], fill=(240, 240, 240), outline=(0, 0, 0), width=1)
            label = _FURNITURE_LABEL_MAP.get(item.type, item.type.replace("_", " ").title())
            short = label if len(label) <= 8 else label[:7] + "."
            if x2 - x1 >= 18 and y2 - y1 >= 10:
                draw.text(((x1 + x2) // 2, (y1 + y2) // 2), short,
                          fill=(0, 0, 0), anchor="mm", font=font_sm)
        room_label = _ROOM_LABEL_MAP.get(room_type, room_type.upper().replace("_", " "))
        draw.text((MARGIN + WALL + 6, MARGIN + WALL + 6), room_label, fill=(0, 0, 0), font=font_md)
        img.save(str(out))
        print(f"[layout_agent] Floor plan saved (PIL fallback): {out}")
        return str(out)
    except Exception as e:
        print(f"⚠️ Floor plan generation failed: {e}")
        return None


def _generate_projected_depth(
    items: list[FurnitureItem],
    space_info: dict,
    task_id: str,
    vision_features: dict[str, Any] | None = None,
    output_size: tuple[int, int] | None = None,
    preserve_types: frozenset[str] = frozenset(),
    preserve_mask: Any = None,
) -> tuple[str | None, str | None, str]:
    """Project furniture boxes into a perspective depth map (+ segmentation) for ControlNet.

    Three modes, in priority order — the first two composite the furniture onto the
    photo's own depth map, so camera angle, room proportions and the architecture
    (windows, doors, corners) all come from the original photo:

      1. photo_anchored — the floor/wall junction is visible, so the plan→image mapping
         is a homography fitted straight to it. Most accurate.
      2. photo_camera   — the junction is hidden behind furniture (the common case for
         real interiors); the floor trapezoid is reconstructed from the depth map's
         vanishing line and far-wall distance instead.
      3. synthetic      — no usable photo geometry: fall back to the fixed pinhole camera
         over an empty room box sized from space_info.

    Returns (depth_path, seg_path, mode).
    """
    if not Config.ENABLE_LAYOUT_DEPTH_PROJECTION:
        return None, None, "disabled"

    out_dir = Path(Config.ARTIFACTS_DIR) / "layout"
    depth_out = out_dir / f"{task_id}_projected_depth.png"
    seg_out = out_dir / f"{task_id}_projected_seg.png"
    placements = [item.to_dict() for item in items]

    vision = vision_features or {}
    photo_depth = vision.get("depth")
    photo_seg = vision.get("segmentation")
    photo_seg_meta = vision.get("segmentation_meta")
    can_anchor = (
        Config.LAYOUT_PHOTO_ANCHORED_DEPTH
        and all(p and Path(str(p)).is_file() for p in (photo_depth, photo_seg, photo_seg_meta))
    )

    if can_anchor:
        try:
            from designbridge.layout.scene_graph_to_depth import project_layout_onto_photo

            res = project_layout_onto_photo(
                placements,
                str(photo_depth), str(photo_seg), str(photo_seg_meta),
                depth_out,
                seg_out_path=seg_out,
                eye_height=Config.LAYOUT_CAMERA_EYE_HEIGHT,
                output_size=output_size,
                preserve_types=preserve_types,
                preserve_mask=preserve_mask,
            )
            if res is not None:
                mode = "photo_anchored"
                if str((res.get("meta") or {}).get("horizon_source", "")).startswith("camera:"):
                    mode = "photo_camera"
                return res.get("depth_path"), res.get("seg_path"), mode
            print("[layout_agent] 照片地板幾何無法求解，退回合成相機投影")
        except Exception as e:
            print(f"⚠️ Photo-anchored depth projection failed ({e}), falling back to synthetic camera")

    try:
        from designbridge.layout.scene_graph_to_depth import project_scene_graph_to_depth

        res = project_scene_graph_to_depth(
            placements,
            space_info,
            depth_out,
            image_size=output_size or (1024, 1024),
            seg_out_path=seg_out,
            camera_overrides={
                "hfov_deg": Config.LAYOUT_PROJECTION_HFOV,
                "pitch_deg": Config.LAYOUT_PROJECTION_PITCH,
                "setback": Config.LAYOUT_PROJECTION_SETBACK,
            },
        )
        return res.get("depth_path"), res.get("seg_path"), "synthetic"
    except Exception as e:
        print(f"⚠️ Projected depth generation failed: {e}")
        return None, None, "failed"


# ─────────────────────────── Main Entry Point ───────────────────────────

def _format_existing_layout(existing_layout: dict | None) -> str:
    """Turn photo-extracted layout (depth_to_layout output) into readable current-arrangement text.

    Gives the LLM the current furniture positions so it can adjust from the real layout
    (e.g. "sofa is on the right") instead of re-planning from scratch.
    """
    if not existing_layout:
        return "（無現有佈局資料，請依需求自由規劃家具位置）"
    candidates = existing_layout.get("furniture_candidates") or []
    if not candidates:
        return "（無法從照片辨識既有家具，請依需求自由規劃）"
    lines = []
    for c in candidates:
        t = c.get("type", "unknown")
        pos = c.get("position", "unknown")
        size = c.get("size_ratio", 0.0)
        conf = c.get("confidence", "")
        lines.append(f"- {t} 目前位於 {pos}（畫面佔比 {size:.0%}，可信度 {conf}）")
    return "\n".join(lines)


_DISPLAY_NAMES: dict[str, str] = {
    "tv_unit": "TV console",
    "nightstand": "nightstand",
    "ceiling_lamp": "pendant ceiling light",
    "pendant_light": "pendant ceiling light",
    "wall_lamp": "wall sconce",
    "wall_shelf": "wall-mounted shelf",
    "lamp": "floor lamp",
}


def _display_name(ftype: str) -> str:
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    key = normalize_furniture_type(ftype)
    if key in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[key]
    return key.replace("_", " ")


def _describe_position(item: "FurnitureItem", *, ceiling: bool = False) -> str:
    """正規化座標 → 自然語言方位。x：0 左→1 右；y：0 遠牆→1 近觀看者。"""
    cx = item.x + item.w / 2.0
    cy = item.y + item.h / 2.0
    lateral = "on the left" if cx < 0.34 else ("on the right" if cx > 0.66 else "in the centre")
    if ceiling:
        return f"overhead {lateral}"
    depth = (
        "against the far wall" if cy < 0.34
        else ("in the foreground" if cy > 0.66 else "in the middle of the room")
    )
    return f"{lateral}, {depth}"


_WALL_ZH: dict[str, str] = {
    "far": "遠牆（畫面深處）", "near": "近牆（觀看者側）",
    "left": "左牆", "right": "右牆",
}


def _format_openings(openings: Any, kind: str) -> str:
    """Window/door boxes → prose with the actual plan coordinates spelled out.

    Dumping the raw JSON left the planner to parse `{"x":0.0,"y":0.3,...}` itself; giving
    it the coordinate range in the same frame as the output schema is what makes
    "move the desk next to the window" resolvable rather than guessed.
    """
    if not openings:
        return f"（照片判讀不到{kind}位置——規劃時不要假設任何一面牆上有{kind}）"
    lines: list[str] = []
    for op in openings:
        if not isinstance(op, dict):
            continue
        x, y = float(op.get("x", 0.0)), float(op.get("y", 0.0))
        w, h = float(op.get("w", 0.1)), float(op.get("h", 0.1))
        wall = _WALL_ZH.get(str(op.get("wall") or ""), "牆面")
        lines.append(
            f"- {wall}：俯視座標 x {x:.2f}~{x + w:.2f}、y {y:.2f}~{y + h:.2f}"
        )
    return "\n".join(lines) if lines else f"（無{kind}資料）"


def _format_move_ops(move_ops: Any) -> str:
    """must_move 清單 → 給 LLM 讀的條列文字。"""
    if not move_ops:
        return "無"
    lines: list[str] = []
    for op in move_ops:
        if not isinstance(op, dict):
            lines.append(f"- {op}")
            continue
        target = str(op.get("target") or "").strip()
        if not target:
            continue
        qualifier = str(op.get("qualifier") or "").strip()
        dest = str(op.get("to") or "").strip() or "使用者指定的新位置"
        which = f"（指定：{qualifier}）" if qualifier else ""
        lines.append(f"- {target}{which} → 移到 {dest}")
    return "\n".join(lines) if lines else "無"


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


def _classify_preserved(
    items: list["FurnitureItem"], constraints: dict[str, Any] | None = None
) -> frozenset[str]:
    """哪些家具 type 應該原地保留照片裡的真實深度。

    規則：出現在規劃結果裡、且使用者完全沒提到要動的那些。使用者沒說要動的東西
    就不該被清掉再用合成長方體近似——那會丟失照片裡的真實幾何。

    這條規則同時吸收了 LA 的漂移：即使 LLM 擅自把沒被要求變動的家具挪了位置，
    保留原始像素會讓那個漂移不生效，正是我們要的行為。
    """
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    touched = _touched_types(constraints)
    planned = {normalize_furniture_type(it.type) for it in items}
    return frozenset(planned - touched)


def _build_layout_prompt(
    items: list["FurnitureItem"], constraints: dict[str, Any] | None = None
) -> str:
    """由規劃結果生成 additive 的佈局描述。

    只描述 diffusion 沒有其他管道能得知的東西：
      - 吊掛／壁掛物件：不進深度投影（沒有地板 footprint），文字是唯一通道
      - 使用者要求新增的家具：深度圖有了，但文字加強能顯著提高出現率
    既有的落地家具不列舉——深度圖已經精確控制它們，長清單只會稀釋 prompt。
    """
    from designbridge.layout.scene_graph_to_depth import is_floor_standing, normalize_furniture_type

    constraints = constraints or {}
    # 保持 must_add 的原始順序並去重，否則 prompt 每次生成的字序會不一樣
    must_add: list[str] = []
    for s in constraints.get("must_add") or []:
        key = normalize_furniture_type(s)
        if key not in must_add:
            must_add.append(key)

    hanging: list[str] = []
    floor_by_type: dict[str, list[FurnitureItem]] = {}
    for item in items:
        if not is_floor_standing(item.type):
            hanging.append(
                f"a {_display_name(item.type)} {_describe_position(item, ceiling=True)}"
            )
        else:
            floor_by_type.setdefault(normalize_furniture_type(item.type), []).append(item)

    # 每個 must_add 類型只講一次：正規化會讓 low_cabinet 與 cabinet 撞在一起，
    # 全部列出來會把同一個需求重複描述。優先取原始 type 完全吻合的那件。
    added: list[str] = []
    for key in must_add:
        candidates = floor_by_type.get(key)
        if not candidates:
            continue
        chosen = next((it for it in candidates if it.type == key), candidates[0])
        added.append(f"a {_display_name(chosen.type)} {_describe_position(chosen)}")

    parts: list[str] = []
    if added:
        parts.append("The room must include " + ", ".join(added) + ".")
    if hanging:
        parts.append("Also visible: " + ", ".join(hanging) + ".")
    return " ".join(parts)


def run_layout_agent(
    structured_requirement: dict[str, Any],
    task_id: str,
    existing_layout: dict[str, Any] | None = None,
    vision_features: dict[str, Any] | None = None,
    output_size: tuple[int, int] | None = None,
    image_path: str | None = None,
) -> dict[str, Any]:
    """
    Run layout planning. Returns a partial state dict (scene_graph, intermediate_outputs).
    NOTE: intermediate_outputs is NOT pre-merged — callers must merge with existing state.
    NOTE: layout_prompt only carries what the depth projection cannot express — hanging /
          wall-mounted pieces and the user's explicitly requested additions. Enumerating
          every floor piece degrades diffusion quality, so it is deliberately left out.
          Floor plan PNG is used for ControlNet only when ENABLE_LAYOUT_CONTROLNET=true.
    existing_layout: photo-extracted current arrangement (state["layout_from_depth"]); when
          present, the planner adjusts from it rather than re-planning from scratch.
    vision_features: state["vision_features"] — depth/segmentation of the uploaded photo.
          When available the projected depth is anchored to the photo's own floor plane
          instead of a synthetic camera, so the render keeps the original spatial layout.
    output_size: (width, height) the renderer will request from the image model. The projected
          depth map must be built at this same aspect ratio, or the ControlNet control image gets
          mismatched against the render canvas and the uncovered margins render as unconstrained
          (unrelated) content instead of room geometry. Defaults to a square canvas.
    """
    from designbridge.core.prompts import LAYOUT_AGENT_PROMPT, LAYOUT_REFINEMENT_PROMPT
    from designbridge.core.timing import log_stage

    layout_registry = get_layout_constraint_registry()
    meta = structured_requirement.get("meta") or {}
    space_info = structured_requirement.get("space_info") or {}
    constraints = structured_requirement.get("layout_constraints") or {}
    user_description = (
        structured_requirement.get("design_description")
        or structured_requirement.get("user_description_raw")
        or ""
    )
    room_type = meta.get("room_type", "living_room")
    max_iter = Config.LAYOUT_MAX_ITER
    existing_layout_text = _format_existing_layout(existing_layout)

    def _build_prompt(extra: str = "") -> str:
        return LAYOUT_AGENT_PROMPT.format(
            room_type=room_type,
            width=space_info.get("estimated_size", {}).get("width", 5.0),
            depth=space_info.get("estimated_size", {}).get("depth", 4.0),
            windows=_format_openings(space_info.get("windows"), "窗戶"),
            doors=_format_openings(space_info.get("doors"), "門"),
            must_keep=", ".join(constraints.get("must_keep") or []) or "無",
            must_add=", ".join(constraints.get("must_add") or []) or "無",
            must_remove=", ".join(constraints.get("must_remove") or []) or "無",
            must_move=_format_move_ops(constraints.get("must_move")),
            immutable_regions=json.dumps(
                constraints.get("immutable_regions") or [], ensure_ascii=False
            ),
            existing_layout=existing_layout_text,
            user_description=user_description + ("\n" + extra if extra else ""),
        )

    # Initial layout from LLM — the only network-bound step in this function; everything
    # below is local numpy/pycairo, so if /api/generate-layout feels slow this is where to look.
    try:
        with log_stage("layout_agent.llm_layout", task_id=task_id):
            items = _call_llm_layout(_build_prompt())
        if not items:
            raise ValueError("empty response")
    except Exception as e:
        print(f"⚠️ LLM layout failed ({e}), using default layout")
        items = _default_layout(room_type)

    best_items: list[FurnitureItem] = []
    best_score = -1.0
    scores: dict[str, float] = {}
    scores_history: list[float] = []
    SCORE_THRESHOLD = 0.65

    # `photo_anchored` decides whether untouched furniture is frozen: with a photo those
    # pieces keep their original depth pixels regardless of what the plan says.
    _vf_probe = vision_features or {}
    photo_anchored = bool(
        Config.LAYOUT_PHOTO_ANCHORED_DEPTH
        and all(
            _vf_probe.get(k) and Path(str(_vf_probe[k])).is_file()
            for k in ("depth", "segmentation", "segmentation_meta")
        )
    )

    def _settle(seq: list[FurnitureItem]) -> list[FurnitureItem]:
        """Hard constraints and enforcers, in the order that keeps each other's work."""
        seq = _apply_hard_constraints(seq, constraints)
        seq = _enforce_move_ops(seq, constraints, space_info)
        immutable = constraints.get("immutable_regions") or []
        if immutable:
            seq = _enforce_immutable(seq, immutable)
        seq = _clip_to_room(seq)
        seq = _inject_bunk_bed_ladder(seq)
        seq = _push_apart(seq)
        for card in layout_registry.load():
            fn = _LAYOUT_ENFORCERS.get(card.enforce)
            if fn:
                seq = fn(seq, space_info, card.parameters)
        from designbridge.layout.special_constraints import apply_special_layout_constraints
        seq = apply_special_layout_constraints(seq, structured_requirement)
        # The enforcers above snap pieces to walls and push them off doors, which can
        # create overlaps the earlier `_push_apart` had already resolved. Without this
        # second pass those survive into the scene graph and `collision_free` reports
        # False on a layout nothing tried to fix.
        seq = _push_apart(seq)
        return _clip_to_room(seq)

    # One LLM call for the semantics (which pieces, roughly where), then a numeric search
    # for the geometry. Re-prompting the LLM with five scalars — the old refinement loop —
    # cost a round trip per iteration and gave it nothing to act on; the optimizer
    # evaluates thousands of candidates in a fraction of that and is reproducible.
    def _clone(seq: list[FurnitureItem]) -> list[FurnitureItem]:
        """Copy preserving `pinned`, which `to_dict` deliberately does not serialize."""
        out = [FurnitureItem(**it.to_dict()) for it in seq]
        for src, dst in zip(seq, out):
            dst.pinned = src.pinned
        return out

    items = _settle(items)
    baseline = _clone(items)
    before = _weighted_score(_score_soft_constraints(items, space_info))
    scores_history.append(before)

    movable = _movable_indices(items, constraints, photo_anchored)
    with log_stage("layout_agent.optimize_positions", task_id=task_id):
        items, _obj, accepted = _optimize_positions(
            items, space_info, movable, steps=Config.LAYOUT_OPTIMIZER_STEPS
        )
    items = _settle(items)
    total = _weighted_score(_score_soft_constraints(items, space_info))

    # The optimizer maximises the objective, but `_settle` runs again afterwards to
    # re-pin move targets and re-apply the wall/gap enforcers, and those can undo part of
    # the gain. Measure both layouts after the same settling and keep the better one, so
    # optimising can never hand back something worse than it was given.
    if total < before:
        print(f"[layout_agent] optimizer 後 settle 反而變差（{before:.3f} → {total:.3f}），保留原佈局")
        items = baseline
        total = before

    scores = _score_soft_constraints(items, space_info)
    total = _weighted_score(scores)
    scores_history.append(total)
    best_score = total
    best_items = _clone(items)

    print(
        f"[layout_agent] optimizer: {len(movable)}/{len(items)} 件可動"
        f"（{'照片錨定，其餘凍結' if photo_anchored else '無照片，全部可動'}）"
        f" steps={Config.LAYOUT_OPTIMIZER_STEPS} accepted={accepted}"
        f"  score {before:.3f} → {total:.3f}"
    )
    print(
        f"[layout_agent] circ={scores['circulation']:.2f} bal={scores['balance']:.2f} "
        f"foc={scores['focal_point']:.2f} light={scores['natural_light']:.2f} "
        f"erg={scores['ergonomics']:.2f}"
    )

    # Optional: fall back to the old LLM refinement when the optimizer cannot reach the
    # threshold. Off by default — a low score usually means the *initial plan* was wrong
    # (missing or mis-sized pieces), which another geometric nudge cannot fix either.
    if Config.LAYOUT_LLM_REFINE and total < SCORE_THRESHOLD:
        for _ in range(max(0, max_iter - 1)):
            try:
                refined = _call_llm_layout(
                    _build_prompt(LAYOUT_REFINEMENT_PROMPT.format(**scores))
                )
            except Exception:
                break
            if not refined:
                break
            refined = _settle(refined)
            refined, _o, _a = _optimize_positions(
                refined, space_info,
                _movable_indices(refined, constraints, photo_anchored),
                steps=Config.LAYOUT_OPTIMIZER_STEPS,
            )
            refined = _settle(refined)
            scores = _score_soft_constraints(refined, space_info)
            total = _weighted_score(scores)
            scores_history.append(total)
            print(f"[layout_agent] llm refine → score={total:.3f}")
            if total > best_score:
                best_score = total
                best_items = _clone(refined)
            if total >= SCORE_THRESHOLD:
                break

    acceptance_rate = (
        sum(1 for s in scores_history if s >= SCORE_THRESHOLD) / len(scores_history)
        if scores_history else 0.0
    )
    print(
        f"[layout_agent] passes={len(scores_history)} "
        f"best={best_score:.3f} acceptance_rate={acceptance_rate:.2%}"
    )

    from designbridge.layout.special_constraints import verify_special_constraints
    special_satisfaction = verify_special_constraints(best_items, structured_requirement)
    infeasible_constraints = [k for k, v in special_satisfaction.items() if not v]
    feasible = not infeasible_constraints
    if infeasible_constraints:
        print(
            f"[layout_agent] ⚠️  infeasible after convergence: {infeasible_constraints}"
        )

    # Hard constraint satisfaction report
    must_keep_set = {s.lower().replace(" ", "_") for s in (constraints.get("must_keep") or [])}
    must_add_set = {s.lower().replace(" ", "_") for s in (constraints.get("must_add") or [])}
    must_remove_set = {s.lower().replace(" ", "_") for s in (constraints.get("must_remove") or [])}
    existing = {item.type for item in best_items}

    _lc_params = {c.enforce: c.parameters for c in layout_registry.load()}
    _wa_params = _lc_params.get("wall_anchor", {})
    _wall_anchored = set(_wa_params.get("wall_anchored", []))
    _snap_threshold = float(_wa_params.get("snap_threshold", 0.12))
    _gap_map = _build_semantic_gap_map(_lc_params.get("semantic_gaps", {}))

    constraint_check = {
        "must_keep_satisfied": all(t in existing for t in must_keep_set),
        "must_add_satisfied": all(t in existing for t in must_add_set),
        "must_remove_satisfied": all(t not in existing for t in must_remove_set),
        "collision_free": not any(
            _overlaps(best_items[i], best_items[j])
            for i in range(len(best_items))
            for j in range(i + 1, len(best_items))
            if not (_is_underlay_type(best_items[i].type) or _is_underlay_type(best_items[j].type))
        ),
        "wall_anchored": all(
            min(item.x, 1.0 - item.x - item.w, item.y, 1.0 - item.y - item.h) <= _snap_threshold
            for item in best_items if item.type in _wall_anchored
        ),
        "semantic_gaps_met": not any(
            _overlaps(best_items[i], best_items[j],
                      margin=_gap_map.get(frozenset({best_items[i].type, best_items[j].type}), 0.0))
            for i in range(len(best_items))
            for j in range(i + 1, len(best_items))
            if frozenset({best_items[i].type, best_items[j].type}) in _gap_map
        ),
    }

    size = space_info.get("estimated_size") or {}
    _fp_room_w = float(size.get("width", 4.0))
    _fp_room_d = float(size.get("depth", 4.0))
    floor_plan_path = _generate_floor_plan(best_items, task_id, room_type, _fp_room_w, _fp_room_d)

    preserve_types = _classify_preserved(best_items, constraints)
    if preserve_types:
        print(f"[layout_agent] 原地保留（使用者未要求變動）：{sorted(preserve_types)}")

    # 同類多件時，preserve_types 幫不上忙（整個類別要嘛全保留要嘛全重畫）。
    # 針對 must_move 再做一次實例級分離，把「沒被指名的那幾件」也鎖回原位。
    preserve_mask = None
    _vf = vision_features or {}
    _seg, _meta = _vf.get("segmentation"), _vf.get("segmentation_meta")
    if constraints.get("must_move") and _seg and _meta:
        if Path(str(_seg)).is_file() and Path(str(_meta)).is_file():
            try:
                from designbridge.layout.instance_select import build_preserve_mask

                preserve_mask, _notes = build_preserve_mask(
                    constraints["must_move"], _seg, _meta, image_path=image_path
                )
                for n in _notes:
                    print(f"[layout_agent] 實例分離 — {n}")
            except Exception as e:
                print(f"⚠️ 實例級保留失敗（{e}），退回語意級")

    projected_depth_path, projected_seg_path, projection_mode = _generate_projected_depth(
        best_items, space_info, task_id,
        vision_features=vision_features,
        output_size=output_size,
        preserve_types=preserve_types,
        preserve_mask=preserve_mask,
    )

    layout_prompt = _build_layout_prompt(best_items, constraints)
    if layout_prompt:
        print(f"[layout_agent] layout_prompt: {layout_prompt}")

    scene_graph: dict[str, Any] = {
        "furniture_placements": [item.to_dict() for item in best_items],
        "layout_prompt": layout_prompt,
        "layout_constraints_met": constraint_check,
        "soft_constraint_scores": scores,
        "weighted_score": best_score,
        "floor_plan_path": floor_plan_path,
        # Carry the REAL room dimensions used to draw the plan so the Step-2 renderer
        # projects the layout at the correct aspect ratio (otherwise it falls back to
        # the requirement analyzer's guessed size and the layout gets distorted).
        "room_w": _fp_room_w,
        "room_d": _fp_room_d,
        "projected_depth_path": projected_depth_path,
        "projected_seg_path": projected_seg_path,
        "projection_mode": projection_mode,
        "feasible": feasible,
        "infeasible_constraints": infeasible_constraints,
    }

    return {
        "scene_graph": scene_graph,
        "intermediate_outputs": {
            "layout_agent": {
                "status": "ok" if feasible else "infeasible",
                "furniture_count": len(best_items),
                "weighted_score": best_score,
                "soft_scores": scores,
                "constraint_check": constraint_check,
                "floor_plan_path": floor_plan_path,
                "projection_mode": projection_mode,
                "scores_history": scores_history,
                "acceptance_rate": round(acceptance_rate, 3),
                "iterations_run": len(scores_history),
                "feasible": feasible,
                "infeasible_constraints": infeasible_constraints,
            }
        },
    }
