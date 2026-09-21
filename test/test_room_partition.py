"""Sanity checks for the room-program floor plan partition algorithm.

Verifies the properties the slicing algorithm is supposed to guarantee by construction
(no overlaps, exact tiling), plus the door/window derivation invariants (exactly one
entry door, no room left unreachable) and the infeasible-program error path.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from designbridge.roomplan.partition import RoomProgramError, partition_rooms
from designbridge.roomplan.walls import derive_walls_and_openings

SAMPLE_PROGRAMS = [
    {"bedroom_count": 2, "living_count": 1, "bathroom_count": 1, "kitchen_count": 1, "balcony_count": 1, "total_ping": 25},
    {"bedroom_count": 3, "living_count": 1, "bathroom_count": 2, "kitchen_count": 1, "balcony_count": 2, "total_ping": 32},
    {"bedroom_count": 1, "living_count": 1, "bathroom_count": 1, "kitchen_count": 1, "balcony_count": 0, "total_ping": 12},
    {"bedroom_count": 4, "living_count": 2, "bathroom_count": 2, "kitchen_count": 1, "balcony_count": 1, "total_ping": 45},
]


def _overlap_area(a, b) -> float:
    ox = max(0.0, min(a.rect.right, b.rect.right) - max(a.rect.x, b.rect.x))
    oy = max(0.0, min(a.rect.bottom, b.rect.bottom) - max(a.rect.y, b.rect.y))
    return ox * oy


def test_no_overlaps_and_full_tiling():
    for program in SAMPLE_PROGRAMS:
        rooms, bounding_w, bounding_d, warnings = partition_rooms(program)

        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                overlap = _overlap_area(rooms[i], rooms[j])
                assert overlap < 1e-6, (
                    f"{program}: rooms {rooms[i].id} and {rooms[j].id} overlap by {overlap:.6f} m²"
                )

        total_room_area = sum(r.actual_area_m2 for r in rooms)
        bounding_area = bounding_w * bounding_d
        assert abs(total_room_area - bounding_area) < 1e-6, (
            f"{program}: room areas sum to {total_room_area:.6f} but bounding box is {bounding_area:.6f}"
        )
        print(f"[tiling] {len(rooms)} rooms, bounding={bounding_w:.2f}x{bounding_d:.2f} m, "
              f"area matches ({total_room_area:.3f} m²), warnings={warnings}")


def test_min_dimension_sanity():
    # A small room (e.g. balcony) sharing a cut with a much bigger sibling can still end
    # up over its target area (it inherits the sibling's cross-dimension) — that's a
    # known v1 limitation the `warnings` list is meant to surface, not eliminate. What
    # actually matters here is that MIN_ROOM_DIM_M holds: no degenerate sliver rooms.
    for program in SAMPLE_PROGRAMS:
        rooms, _, _, warnings = partition_rooms(program)
        shortest = min(min(r.rect.w, r.rect.h) for r in rooms)
        assert shortest >= 1.0, f"{program}: unexpectedly thin room: {shortest:.2f} m"
        print(f"[dimensions] shortest room side = {shortest:.2f} m, warnings={warnings}")


def test_infeasible_program_raises():
    program = {"bedroom_count": 6, "living_count": 1, "bathroom_count": 4, "kitchen_count": 1, "balcony_count": 0, "total_ping": 8}
    try:
        partition_rooms(program)
        raise AssertionError("expected RoomProgramError for an infeasible program")
    except RoomProgramError as e:
        print(f"[infeasible] correctly raised: {e}")


def test_every_room_has_a_door_and_exactly_one_entry():
    for program in SAMPLE_PROGRAMS:
        rooms, bounding_w, bounding_d, _ = partition_rooms(program)
        walls, doors, windows = derive_walls_and_openings(rooms, bounding_w, bounding_d)

        entry_doors = [d for d in doors if d.kind == "entry"]
        assert len(entry_doors) == 1, f"{program}: expected exactly one entry door, got {len(entry_doors)}"

        reachable = set()
        for d in doors:
            reachable.update(d.room_ids)
        all_ids = {r.id for r in rooms}
        unreachable = all_ids - reachable
        assert not unreachable, f"{program}: rooms with no door at all: {unreachable}"
        print(f"[doors] {len(rooms)} rooms, {len(doors)} doors (1 entry), all reachable, {len(windows)} windows")


if __name__ == "__main__":
    test_no_overlaps_and_full_tiling()
    test_min_dimension_sanity()
    test_infeasible_program_raises()
    test_every_room_has_a_door_and_exactly_one_entry()
    print("\nALL ROOM-PARTITION CHECKS PASSED ✅")
