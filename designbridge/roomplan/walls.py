"""Derive walls, doors, and windows from a set of already-placed room rectangles."""

from __future__ import annotations

import math

from designbridge.roomplan.constants import (
    DOOR_WIDTH_M,
    ENTRY_DOOR_WIDTH_M,
    EXTERIOR_WALL_THICKNESS_M,
    INTERIOR_WALL_THICKNESS_M,
    MAX_WINDOW_WIDTH_M,
    MIN_SHARED_EDGE_M,
    MIN_WINDOW_WALL_M,
    NO_DIRECT_DOOR_PAIRS,
    NO_WINDOW_ROOM_TYPES,
)
from designbridge.roomplan.geometry import EPS as _EPS
from designbridge.roomplan.geometry import is_exterior_edge as _is_exterior_edge
from designbridge.roomplan.geometry import room_edges as _room_edges
from designbridge.roomplan.schemas import DoorOpening, RoomInstance, WallSegment, WindowOpening


def _door_type(room_type: str) -> str:
    return "bedroom" if room_type in ("bedroom", "bedroom_master") else room_type


def _find_shared_edges(rooms: list[RoomInstance]) -> list[dict]:
    """Pairwise-detect interior walls: edges of two rooms that coincide over >= MIN_SHARED_EDGE_M."""
    shared: list[dict] = []
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            a, b = rooms[i], rooms[j]

            if abs(a.rect.right - b.rect.x) < _EPS:
                lo, hi = max(a.rect.y, b.rect.y), min(a.rect.bottom, b.rect.bottom)
                if hi - lo >= MIN_SHARED_EDGE_M:
                    shared.append({"a": a, "b": b, "orientation": "vertical", "const": a.rect.right, "lo": lo, "hi": hi})
                    continue
            if abs(b.rect.right - a.rect.x) < _EPS:
                lo, hi = max(a.rect.y, b.rect.y), min(a.rect.bottom, b.rect.bottom)
                if hi - lo >= MIN_SHARED_EDGE_M:
                    shared.append({"a": b, "b": a, "orientation": "vertical", "const": b.rect.right, "lo": lo, "hi": hi})
                    continue
            if abs(a.rect.bottom - b.rect.y) < _EPS:
                lo, hi = max(a.rect.x, b.rect.x), min(a.rect.right, b.rect.right)
                if hi - lo >= MIN_SHARED_EDGE_M:
                    shared.append({"a": a, "b": b, "orientation": "horizontal", "const": a.rect.bottom, "lo": lo, "hi": hi})
                    continue
            if abs(b.rect.bottom - a.rect.y) < _EPS:
                lo, hi = max(a.rect.x, b.rect.x), min(a.rect.right, b.rect.right)
                if hi - lo >= MIN_SHARED_EDGE_M:
                    shared.append({"a": b, "b": a, "orientation": "horizontal", "const": b.rect.bottom, "lo": lo, "hi": hi})
    return shared


def _make_interior_door(shared_edge: dict, idx: int) -> DoorOpening:
    a, b = shared_edge["a"], shared_edge["b"]
    mid = (shared_edge["lo"] + shared_edge["hi"]) / 2
    swing_into = a.id if a.rect.area <= b.rect.area else b.id
    if shared_edge["orientation"] == "vertical":
        return DoorOpening(
            id=f"door_int_{idx}", kind="interior", room_ids=[a.id, b.id],
            orientation="vertical", x=shared_edge["const"], y=mid,
            width_m=DOOR_WIDTH_M, swing_into_room_id=swing_into,
        )
    return DoorOpening(
        id=f"door_int_{idx}", kind="interior", room_ids=[a.id, b.id],
        orientation="horizontal", x=mid, y=shared_edge["const"],
        width_m=DOOR_WIDTH_M, swing_into_room_id=swing_into,
    )


def _longest_exterior_edge(room: RoomInstance, bounding_w: float, bounding_d: float, exclude_side: str | None = None):
    best = None
    for side, (x1, y1, x2, y2) in _room_edges(room).items():
        if side == exclude_side or not _is_exterior_edge(side, room, bounding_w, bounding_d):
            continue
        length = math.hypot(x2 - x1, y2 - y1)
        if best is None or length > best[1]:
            best = (side, length, (x1, y1, x2, y2))
    return best


def _make_entry_door(rooms: list[RoomInstance], bounding_w: float, bounding_d: float):
    """Returns (DoorOpening | None, entry_room_id | None, entry_side | None)."""
    entry_room = next((r for r in rooms if r.room_type == "living_dining"), rooms[0] if rooms else None)
    if entry_room is None:
        return None, None, None

    edge = _longest_exterior_edge(entry_room, bounding_w, bounding_d)
    if edge is None:
        candidates = [(r, _longest_exterior_edge(r, bounding_w, bounding_d)) for r in rooms]
        candidates = [(r, e) for r, e in candidates if e is not None]
        if not candidates:
            return None, None, None
        entry_room, edge = max(candidates, key=lambda c: c[1][1])

    side, length, (x1, y1, x2, y2) = edge
    width = min(ENTRY_DOOR_WIDTH_M, length * 0.8)
    if side in ("top", "bottom"):
        mid_x = (x1 + x2) / 2
        door = DoorOpening(
            id="door_entry", kind="entry", room_ids=[entry_room.id],
            orientation="horizontal", x=mid_x, y=y1, width_m=width,
            swing_into_room_id=entry_room.id,
        )
    else:
        mid_y = (y1 + y2) / 2
        door = DoorOpening(
            id="door_entry", kind="entry", room_ids=[entry_room.id],
            orientation="vertical", x=x1, y=mid_y, width_m=width,
            swing_into_room_id=entry_room.id,
        )
    return door, entry_room.id, side


def derive_walls_and_openings(
    rooms: list[RoomInstance], bounding_w: float, bounding_d: float
) -> tuple[list[WallSegment], list[DoorOpening], list[WindowOpening]]:
    walls: list[WallSegment] = []
    shared = _find_shared_edges(rooms)

    for idx, s in enumerate(shared):
        if s["orientation"] == "vertical":
            walls.append(WallSegment(
                id=f"wall_int_{idx}", kind="interior",
                x1=s["const"], y1=s["lo"], x2=s["const"], y2=s["hi"],
                thickness_m=INTERIOR_WALL_THICKNESS_M, room_ids=[s["a"].id, s["b"].id],
            ))
        else:
            walls.append(WallSegment(
                id=f"wall_int_{idx}", kind="interior",
                x1=s["lo"], y1=s["const"], x2=s["hi"], y2=s["const"],
                thickness_m=INTERIOR_WALL_THICKNESS_M, room_ids=[s["a"].id, s["b"].id],
            ))

    ext_idx = 0
    for room in rooms:
        for side, (x1, y1, x2, y2) in _room_edges(room).items():
            if _is_exterior_edge(side, room, bounding_w, bounding_d):
                walls.append(WallSegment(
                    id=f"wall_ext_{ext_idx}", kind="exterior",
                    x1=x1, y1=y1, x2=x2, y2=y2,
                    thickness_m=EXTERIOR_WALL_THICKNESS_M, room_ids=[room.id],
                ))
                ext_idx += 1

    # Interior doors: a real home doesn't connect every pair of rooms that happen to
    # share a wall — it connects each room to the rest via roughly one doorway. So build
    # a *spanning tree* over the room-adjacency graph instead of a door per shared edge:
    # sort candidate edges by shared-span (same-type pairs like bed<->bed / bath<->bath
    # last, used only if nothing else can connect that room), then union-find greedily
    # picks the minimum set of doors that still reaches every room.
    doors: list[DoorOpening] = []
    door_idx = 0

    room_index = {r.id: i for i, r in enumerate(rooms)}
    parent = list(range(len(rooms)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> bool:
        rx, ry = find(x), find(y)
        if rx == ry:
            return False
        parent[rx] = ry
        return True

    def sort_key(s: dict):
        pair = frozenset({_door_type(s["a"].room_type), _door_type(s["b"].room_type)})
        penalty = 1 if pair in NO_DIRECT_DOOR_PAIRS else 0
        return (penalty, -(s["hi"] - s["lo"]))

    for s in sorted(shared, key=sort_key):
        if union(room_index[s["a"].id], room_index[s["b"].id]):
            doors.append(_make_interior_door(s, door_idx))
            door_idx += 1

    entry_door, entry_room_id, entry_side = _make_entry_door(rooms, bounding_w, bounding_d)
    if entry_door:
        doors.append(entry_door)

    windows: list[WindowOpening] = []
    win_idx = 0
    for room in rooms:
        if room.room_type in NO_WINDOW_ROOM_TYPES:
            continue
        exclude_side = entry_side if room.id == entry_room_id else None
        edge = None
        best = None
        for side, (x1, y1, x2, y2) in _room_edges(room).items():
            if side == exclude_side or not _is_exterior_edge(side, room, bounding_w, bounding_d):
                continue
            length = math.hypot(x2 - x1, y2 - y1)
            if length >= MIN_WINDOW_WALL_M and (best is None or length > best[1]):
                best = (side, length, (x1, y1, x2, y2))
        edge = best
        if edge is None:
            continue
        side, length, (x1, y1, x2, y2) = edge
        width = min(length * 0.5, MAX_WINDOW_WIDTH_M)
        if side in ("top", "bottom"):
            mid_x = (x1 + x2) / 2
            windows.append(WindowOpening(id=f"window_{win_idx}", room_id=room.id, orientation="horizontal", x=mid_x, y=y1, width_m=width))
        else:
            mid_y = (y1 + y2) / 2
            windows.append(WindowOpening(id=f"window_{win_idx}", room_id=room.id, orientation="vertical", x=x1, y=mid_y, width_m=width))
        win_idx += 1

    return walls, doors, windows
