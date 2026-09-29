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
            constraint_type=str(fm.get("type", "family_need")),
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


# ── Enforcement functions (uniform signature: items, doors, windows, params) ──

def _enforce_wheelchair_clearance(
    items: list, doors: list, windows: list, params: dict
) -> list:
    min_gap = float(params.get("min_gap", 0.15))
    pad = float(params.get("pad", 0.02))
    iterations = int(params.get("iterations", 60))

    for _ in range(iterations):
        moved = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if not _rect_overlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, min_gap):
                    continue
                acx, acy = a.x + a.w / 2, a.y + a.h / 2
                bcx, bcy = b.x + b.w / 2, b.y + b.h / 2
                dx, dy = acx - bcx, acy - bcy
                ox = (a.x + a.w + min_gap) - b.x if dx >= 0 else b.x + b.w + min_gap - a.x
                oy = (a.y + a.h + min_gap) - b.y if dy >= 0 else b.y + b.h + min_gap - a.y
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

    for item in items:
        item.x = max(pad, min(1.0 - item.w - pad, item.x))
        item.y = max(pad, min(1.0 - item.h - pad, item.y))
    return items


def _enforce_child_safety(
    items: list, doors: list, windows: list, params: dict
) -> list:
    default_sharp = [
        "desk", "dining_table", "tv_unit", "cabinet", "dresser", "bookshelf", "shelf",
    ]
    sharp_corner = set(params.get("sharp_corner_furniture", default_sharp))
    wall_threshold = float(params.get("wall_threshold", 0.10))
    pad = float(params.get("pad", 0.02))

    for item in items:
        if item.type not in sharp_corner:
            continue
        d_t, d_b = item.y, 1.0 - (item.y + item.h)
        d_l, d_r = item.x, 1.0 - (item.x + item.w)
        if min(d_t, d_b, d_l, d_r) <= wall_threshold:
            continue
        nearest = min(d_t, d_b, d_l, d_r)
        if d_t == nearest:
            item.y = pad
        elif d_b == nearest:
            item.y = 1.0 - item.h - pad
        elif d_l == nearest:
            item.x = pad
        else:
            item.x = 1.0 - item.w - pad
    return items


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


def _enforce_pet_window_clearance(
    items: list, doors: list, windows: list, params: dict
) -> list:
    clearance = float(params.get("window_clearance", 0.10))
    pad = float(params.get("pad", 0.02))
    default_blockers = [
        "wardrobe", "bookshelf", "shelf", "cabinet", "dresser", "sofa", "loveseat", "armchair",
    ]
    blockers = set(params.get("window_blockers", default_blockers))

    for item in items:
        if item.type not in blockers:
            continue
        for window in windows:
            wx = float(window.get("x", 0.5))
            wy = float(window.get("y", 0.0))
            ww = float(window.get("w", 0.15))
            wh = float(window.get("h", ww))
            if wy <= 0.15:
                if item.y < clearance and item.x + item.w > wx and item.x < wx + ww:
                    item.y = clearance + pad
            elif wy >= 0.85:
                if (item.y + item.h > 1.0 - clearance
                        and item.x + item.w > wx and item.x < wx + ww):
                    item.y = 1.0 - clearance - item.h - pad
            elif wx <= 0.15:
                if item.x < clearance and item.y + item.h > wy and item.y < wy + wh:
                    item.x = clearance + pad
            elif wx >= 0.85:
                if (item.x + item.w > 1.0 - clearance
                        and item.y + item.h > wy and item.y < wy + wh):
                    item.x = 1.0 - clearance - item.w - pad
    return items


def _enforce_pet_corner_zone(
    items: list, doors: list, windows: list, params: dict
) -> list:
    corner_size = float(params.get("corner_size", 0.12))
    pad = float(params.get("pad", 0.02))
    corners = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)]

    def _dist_to_doors(cx: float, cy: float) -> float:
        if not doors:
            return 1.0
        return min(
            ((cx - (float(d.get("x", 0.5)) + float(d.get("w", 0.1)) / 2)) ** 2
             + (cy - float(d.get("y", 1.0))) ** 2) ** 0.5
            for d in doors
        )

    corner_x, corner_y = max(corners, key=lambda c: _dist_to_doors(*c))
    zone_x0 = 0.0 if corner_x == 0.0 else 1.0 - corner_size
    zone_x1 = corner_size if corner_x == 0.0 else 1.0
    zone_y0 = 0.0 if corner_y == 0.0 else 1.0 - corner_size
    zone_y1 = corner_size if corner_y == 0.0 else 1.0

    for item in items:
        if not (item.x + item.w > zone_x0 and item.x < zone_x1
                and item.y + item.h > zone_y0 and item.y < zone_y1):
            continue
        if corner_x == 0.0:
            item.x = max(item.x, zone_x1 + pad)
        else:
            item.x = min(item.x, zone_x0 - item.w - pad)
        if corner_y == 0.0:
            item.y = max(item.y, zone_y1 + pad)
        else:
            item.y = min(item.y, zone_y0 - item.h - pad)
    return items


def _enforce_pet_climbable_wall_anchor(
    items: list, doors: list, windows: list, params: dict
) -> list:
    pad = float(params.get("pad", 0.02))
    default_climbable = ["bookshelf", "shelf", "wardrobe", "cabinet"]
    climbable = set(params.get("climbable_furniture", default_climbable))

    for item in items:
        if item.type not in climbable:
            continue
        d_t, d_b = item.y, 1.0 - (item.y + item.h)
        d_l, d_r = item.x, 1.0 - (item.x + item.w)
        nearest = min(d_t, d_b, d_l, d_r)
        if d_t == nearest:
            item.y = pad
        elif d_b == nearest:
            item.y = 1.0 - item.h - pad
        elif d_l == nearest:
            item.x = pad
        else:
            item.x = 1.0 - item.w - pad
    return items


# ── Dispatch table ────────────────────────────────────────────────────────────

_ENFORCERS: dict[str, Callable] = {
    "wheelchair_clearance":      _enforce_wheelchair_clearance,
    "child_safety":              _enforce_child_safety,
    "bed_not_facing_door":       _enforce_bed_not_facing_door,
    "sofa_not_back_to_door":     _enforce_sofa_not_back_to_door,
    "desk_not_facing_window":    _enforce_desk_not_facing_window,
    "pet_window_clearance":      _enforce_pet_window_clearance,
    "pet_corner_zone":           _enforce_pet_corner_zone,
    "pet_climbable_wall_anchor": _enforce_pet_climbable_wall_anchor,
}


# ── Verification functions (post-placement satisfaction check) ─────────────────

def _verify_wheelchair_clearance(
    items: list, doors: list, windows: list, params: dict
) -> bool:
    min_gap = float(params.get("min_gap", 0.15))
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if _rect_overlap(a.x, a.y, a.w, a.h, b.x, b.y, b.w, b.h, min_gap):
                return False
    return True


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


_VERIFIERS: dict[str, Callable] = {
    "wheelchair_clearance":  _verify_wheelchair_clearance,
    "bed_not_facing_door":   _verify_bed_not_facing_door,
    "sofa_not_back_to_door": _verify_sofa_not_back_to_door,
}


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_requirement(
    structured_requirement: dict[str, Any],
    family_needs: list[str],
    fengshui_rules: list[str],
) -> dict[str, Any]:
    """Merge family_needs and fengshui_rules into structured_requirement.

    Appends prompt text from each constraint's SKILL.md and sets special_constraints flags.
    """
    if not family_needs and not fengshui_rules:
        return structured_requirement

    cards = get_constraint_registry().load()
    active_triggers: set[str] = set(family_needs) | set(fengshui_rules)

    prompt_parts: list[str] = []
    for trigger in list(family_needs) + list(fengshui_rules):
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
    """Apply all enabled special constraints to the furniture item list.

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
    """Return {trigger: satisfied} for each enabled special constraint.

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
