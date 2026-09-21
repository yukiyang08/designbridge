"""Room-program -> room rectangles: area allocation, adjacency ordering, guillotine slicing."""

from __future__ import annotations

import math

from designbridge.roomplan.constants import (
    BOUNDING_ASPECT_RATIO,
    MIN_ROOM_DIM_M,
    PING_TO_M2,
    ROOM_TYPE_SPECS,
)
from designbridge.roomplan.schemas import Rect, RoomInstance, RoomSpec


class RoomProgramError(ValueError):
    """Raised when the requested room program cannot fit in the given total_ping."""


def _expand_program(program: dict) -> list[RoomSpec]:
    specs: list[RoomSpec] = []

    def add(room_type: str, count: int) -> None:
        meta = ROOM_TYPE_SPECS[room_type]
        for i in range(1, count + 1):
            specs.append(RoomSpec(
                room_type=room_type,
                instance_index=i,
                weight=meta["weight"],
                min_area_m2=meta["min_area_m2"],
                label_zh=meta["label_zh"],
                label_en=meta["label_en"],
            ))

    bedroom_count = int(program.get("bedroom_count", 0) or 0)
    if bedroom_count > 0:
        add("bedroom_master", 1)
        add("bedroom", bedroom_count - 1)
    add("living_dining", int(program.get("living_count", 0) or 0))
    add("kitchen", int(program.get("kitchen_count", 0) or 0))
    add("bathroom", int(program.get("bathroom_count", 0) or 0))
    add("balcony", int(program.get("balcony_count", 0) or 0))
    return specs


def allocate_areas(program: dict) -> list[RoomSpec]:
    """Expand the room-count program into RoomSpecs with a target_area_m2 each.

    Uses constrained proportional allocation ("water-filling"): rooms are given area
    proportional to their weight, except any room whose proportional share would fall
    below its min_area_m2 is clamped to that minimum, and the remaining area is
    redistributed among the rest — repeated until nothing needs clamping.
    """
    specs = _expand_program(program)
    if not specs:
        return specs

    total_ping = float(program.get("total_ping", 0) or 0)
    total_m2 = total_ping * PING_TO_M2
    sum_min = sum(s.min_area_m2 for s in specs)
    if sum_min > total_m2:
        min_ping = sum_min / PING_TO_M2
        raise RoomProgramError(
            f"總坪數不足以容納所需房間的最小面積。目前 {total_ping:.1f} 坪"
            f"（約 {total_m2:.1f} m²），最少需要約 {min_ping:.1f} 坪（{sum_min:.1f} m²）。"
        )

    free = list(specs)
    fixed_total = 0.0
    while free:
        free_weight = sum(s.weight for s in free)
        remaining = total_m2 - fixed_total
        candidates = {id(s): remaining * s.weight / free_weight for s in free}
        violators = [s for s in free if candidates[id(s)] < s.min_area_m2]
        if not violators:
            for s in free:
                s.target_area_m2 = candidates[id(s)]
            break
        for s in violators:
            s.target_area_m2 = s.min_area_m2
            fixed_total += s.min_area_m2
        violator_ids = {id(s) for s in violators}
        free = [s for s in free if id(s) not in violator_ids]
    return specs


def split_into_zones(specs: list[RoomSpec]) -> tuple[list[RoomSpec], list[RoomSpec]]:
    """Group specs into a public zone (balcony/living-dining/kitchen) and a private zone
    (bathroom/bedrooms), each already ordered for sensible adjacency within itself.

    Real apartments read as two wings — a public hall and a private sleeping wing — not
    one long chain of rooms. `partition_rooms` cuts the bounding rect once between these
    two groups, then slices each zone independently, so a bedroom can no longer end up
    wedged between the kitchen and the living room just because of list order.
    """
    by_type: dict[str, list[RoomSpec]] = {}
    for s in specs:
        by_type.setdefault(s.room_type, []).append(s)

    public = by_type.get("balcony", []) + by_type.get("living_dining", []) + by_type.get("kitchen", [])
    private = by_type.get("bathroom", []) + by_type.get("bedroom_master", []) + by_type.get("bedroom", [])
    return public, private


def _split_rect(rect: Rect, ratio: float) -> tuple[Rect, Rect]:
    """Cut `rect` into two along its currently-longer side, giving the first piece
    `ratio` of that side (clamped so neither piece goes below MIN_ROOM_DIM_M)."""
    if rect.w >= rect.h:
        lo, hi = MIN_ROOM_DIM_M, max(MIN_ROOM_DIM_M, rect.w - MIN_ROOM_DIM_M)
        w1 = min(max(rect.w * ratio, lo), hi)
        return Rect(rect.x, rect.y, w1, rect.h), Rect(rect.x + w1, rect.y, rect.w - w1, rect.h)
    lo, hi = MIN_ROOM_DIM_M, max(MIN_ROOM_DIM_M, rect.h - MIN_ROOM_DIM_M)
    h1 = min(max(rect.h * ratio, lo), hi)
    return Rect(rect.x, rect.y, rect.w, h1), Rect(rect.x, rect.y + h1, rect.w, rect.h - h1)


def slice_sequence(rect: Rect, specs: list[RoomSpec]) -> list[RoomInstance]:
    """Recursively bisect `rect` between two consecutive sub-groups of `specs`.

    The cut position is the groups' relative share of target area (not a fixed 50/50).
    Splitting by *group* area (rather than carving one room at a time using the full
    current cross-dimension) keeps each room's own footprint proportioned on both axes —
    critical once the sequence mixes very different room sizes (e.g. a balcony next to a
    living room). Exact, non-overlapping tiling of `rect` is guaranteed by construction.
    """
    if len(specs) == 1:
        spec = specs[0]
        return [RoomInstance(
            id=spec.id, room_type=spec.room_type, rect=rect,
            target_area_m2=spec.target_area_m2, actual_area_m2=rect.area,
            label_zh=spec.label_zh, label_en=spec.label_en,
        )]

    total_area = sum(s.target_area_m2 for s in specs)
    split_idx = len(specs) - 1
    cum = 0.0
    for idx, s in enumerate(specs):
        cum += s.target_area_m2
        if cum >= total_area / 2:
            split_idx = idx + 1
            break
    split_idx = max(1, min(split_idx, len(specs) - 1))

    group_a, group_b = specs[:split_idx], specs[split_idx:]
    area_a = sum(s.target_area_m2 for s in group_a)
    area_b = sum(s.target_area_m2 for s in group_b)
    ratio = area_a / (area_a + area_b) if (area_a + area_b) > 0 else 0.5

    rect_a, rect_b = _split_rect(rect, ratio)
    return slice_sequence(rect_a, group_a) + slice_sequence(rect_b, group_b)


def partition_rooms(program: dict) -> tuple[list[RoomInstance], float, float, list[str]]:
    """Top-level: allocate areas -> split public/private zones -> bounding box ->
    zone-cut -> slice each zone.

    Returns (rooms, bounding_w_m, bounding_d_m, warnings).
    """
    specs = allocate_areas(program)
    if not specs:
        raise RoomProgramError("至少需要一個房間")

    total_m2 = float(program.get("total_ping", 0) or 0) * PING_TO_M2
    bounding_w = math.sqrt(total_m2 * BOUNDING_ASPECT_RATIO)
    bounding_d = math.sqrt(total_m2 / BOUNDING_ASPECT_RATIO)
    bounding_rect = Rect(0.0, 0.0, bounding_w, bounding_d)

    public_specs, private_specs = split_into_zones(specs)
    if not public_specs or not private_specs:
        # Everything landed in one zone (e.g. no bedrooms, or no living/kitchen/balcony
        # at all) — nothing to cut a zone boundary between, fall back to one chain.
        rooms = slice_sequence(bounding_rect, public_specs or private_specs)
    else:
        area_public = sum(s.target_area_m2 for s in public_specs)
        area_private = sum(s.target_area_m2 for s in private_specs)
        total_zoned = area_public + area_private
        ratio = area_public / total_zoned if total_zoned > 0 else 0.5
        rect_public, rect_private = _split_rect(bounding_rect, ratio)
        rooms = slice_sequence(rect_public, public_specs) + slice_sequence(rect_private, private_specs)

    warnings: list[str] = []
    for room in rooms:
        if room.target_area_m2 > 0:
            deviation = abs(room.actual_area_m2 - room.target_area_m2) / room.target_area_m2
            if deviation > 0.15:
                warnings.append(
                    f"{room.label_zh}（{room.id}）實際面積 {room.actual_area_m2:.1f} m² "
                    f"與預期 {room.target_area_m2:.1f} m² 偏差較大"
                )
        shortest_side = min(room.rect.w, room.rect.h)
        if shortest_side < 1.0:
            warnings.append(
                f"{room.label_zh}（{room.id}）邊長過短（{shortest_side:.2f} m），版面可能不合理"
            )

    return rooms, bounding_w, bounding_d, warnings
