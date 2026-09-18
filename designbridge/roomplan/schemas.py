"""Plain dataclasses for room-program floor plan generation (mirrors FurnitureItem's style)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def area(self) -> float:
        return self.w * self.h


@dataclass
class RoomSpec:
    """One room instance still awaiting a placed rectangle (allocation stage)."""

    room_type: str
    instance_index: int
    weight: float
    min_area_m2: float
    label_zh: str
    label_en: str
    target_area_m2: float = 0.0

    @property
    def id(self) -> str:
        return f"{self.room_type}_{self.instance_index}"


@dataclass
class RoomInstance:
    id: str
    room_type: str
    rect: Rect
    target_area_m2: float
    actual_area_m2: float
    label_zh: str
    label_en: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_type": self.room_type,
            "x": round(self.rect.x, 4),
            "y": round(self.rect.y, 4),
            "w": round(self.rect.w, 4),
            "h": round(self.rect.h, 4),
            "target_area_m2": round(self.target_area_m2, 2),
            "actual_area_m2": round(self.actual_area_m2, 2),
            "label_zh": self.label_zh,
            "label_en": self.label_en,
        }


@dataclass
class WallSegment:
    id: str
    kind: str  # "exterior" | "interior"
    x1: float
    y1: float
    x2: float
    y2: float
    thickness_m: float
    room_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "x1": round(self.x1, 4), "y1": round(self.y1, 4),
            "x2": round(self.x2, 4), "y2": round(self.y2, 4),
            "thickness_m": self.thickness_m,
            "room_ids": self.room_ids,
        }


@dataclass
class DoorOpening:
    id: str
    kind: str  # "interior" | "entry"
    room_ids: list[str]
    orientation: str  # "horizontal" | "vertical" — the wall the door sits in
    x: float
    y: float
    width_m: float
    swing_into_room_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "room_ids": self.room_ids,
            "orientation": self.orientation,
            "x": round(self.x, 4), "y": round(self.y, 4),
            "width_m": self.width_m,
            "swing_into_room_id": self.swing_into_room_id,
        }


@dataclass
class WindowOpening:
    id: str
    room_id: str
    orientation: str  # "horizontal" | "vertical" — the wall the window sits in
    x: float
    y: float
    width_m: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "orientation": self.orientation,
            "x": round(self.x, 4), "y": round(self.y, 4),
            "width_m": self.width_m,
        }


@dataclass
class RoomPlanResult:
    task_id: str
    program: dict[str, Any]
    total_m2: float
    bounding_w_m: float
    bounding_d_m: float
    rooms: list[RoomInstance]
    walls: list[WallSegment]
    doors: list[DoorOpening]
    windows: list[WindowOpening]
    svg_path: str
    svg_markup: str
    warnings: list[str] = field(default_factory=list)
