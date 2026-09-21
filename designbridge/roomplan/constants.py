"""Constants for room-program floor plan generation."""

from __future__ import annotations

PING_TO_M2 = 3.305785

BOUNDING_ASPECT_RATIO = 1.25  # width / depth, matches api.py's existing 5:4 assumption

MIN_ROOM_DIM_M = 1.5

EXTERIOR_WALL_THICKNESS_M = 0.20
INTERIOR_WALL_THICKNESS_M = 0.10

DOOR_WIDTH_M = 0.9
ENTRY_DOOR_WIDTH_M = 1.0

MIN_SHARED_EDGE_M = 0.9
MIN_WINDOW_WALL_M = 1.2
MAX_WINDOW_WIDTH_M = 1.8

# Room types that never get an exterior window (privacy convention).
NO_WINDOW_ROOM_TYPES = frozenset({"bathroom"})

# Room-type pairs that don't get a direct door between two instances of the same type,
# unless that's the only shared edge a room has (see walls.py fallback pass).
NO_DIRECT_DOOR_PAIRS = frozenset({
    frozenset({"bedroom", "bedroom"}),
    frozenset({"bathroom", "bathroom"}),
})

# weight: relative share of total area. min_area_m2: floor below which a room can't shrink.
ROOM_TYPE_SPECS: dict[str, dict] = {
    "living_dining": {"weight": 3.0, "min_area_m2": 10.0, "label_zh": "客餐廳", "label_en": "LIVING/DINING"},
    "bedroom_master": {"weight": 2.2, "min_area_m2": 9.0, "label_zh": "主臥室", "label_en": "MASTER BEDROOM"},
    "bedroom": {"weight": 1.6, "min_area_m2": 6.5, "label_zh": "臥室", "label_en": "BEDROOM"},
    "kitchen": {"weight": 1.3, "min_area_m2": 4.0, "label_zh": "廚房", "label_en": "KITCHEN"},
    "bathroom": {"weight": 0.8, "min_area_m2": 3.0, "label_zh": "衛浴", "label_en": "BATHROOM"},
    "balcony": {"weight": 0.6, "min_area_m2": 2.0, "label_zh": "陽台", "label_en": "BALCONY"},
}
