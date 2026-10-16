"""Furniture vocabulary, sizes/colors, the FurnitureItem dataclass and LLM-JSON parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any



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
    "cat_tree": (0.06, 0.06),
    "dog_bed": (0.10, 0.08),
    "litter_box": (0.07, 0.06),
    # 廚衛設備與鏡子：風水規則（開門不見灶／不見廁所、水火不相容、鏡不照床…）
    # 要拿它們當標的，沒有進受控詞彙的話會被 _normalize_ftype 收斂成 default，
    # 規則就永遠不會觸發。
    "stove": (0.13, 0.08),
    "toilet": (0.09, 0.12),
    "sink": (0.10, 0.08),
    "fridge": (0.09, 0.09),
    "mirror": (0.12, 0.03),
    "default": (0.12, 0.10),
}

# The layout LLM freely names furniture ("dog_bed_in_a_corner", "tv_stand", "couch").
# Collapse everything to the controlled vocabulary above so we don't get duplicate pieces
# and unknown types rendering as identical mystery boxes.
_FTYPE_ALIASES: dict[str, str] = {
    "couch": "sofa", "settee": "sofa", "sectional": "sofa", "sectional_sofa": "sofa",
    "tv_stand": "tv_unit", "tv_console": "tv_unit", "media_console": "tv_unit",
    "media_unit": "tv_unit", "television": "tv", "tv_cabinet": "tv_unit",
    "centre_table": "coffee_table", "center_table": "coffee_table", "cocktail_table": "coffee_table",
    "end_table": "side_table", "accent_table": "side_table",
    "book_shelf": "bookshelf", "bookcase": "bookshelf", "shelving": "shelf", "shelves": "shelf",
    "closet": "wardrobe", "armoire": "wardrobe",
    "chest_of_drawers": "dresser", "drawers": "dresser", "chest": "dresser",
    "potted_plant": "plant", "houseplant": "plant", "indoor_plant": "plant",
    "floor_lamp": "lamp", "standing_lamp": "lamp", "table_lamp": "lamp",
    "area_rug": "rug", "carpet": "rug",
    "cat_tower": "cat_tree", "cat_condo": "cat_tree", "scratching_post": "cat_tree", "cat_climber": "cat_tree",
    "dog_crate": "dog_bed", "pet_bed": "dog_bed", "dog_house": "dog_bed", "dog_kennel": "dog_bed",
    "litter_tray": "litter_box", "cat_litter": "litter_box", "litter_pan": "litter_box",
    "cooktop": "stove", "stovetop": "stove", "hob": "stove", "gas_stove": "stove",
    "range": "stove", "cooker": "stove", "kitchen_stove": "stove", "oven": "stove",
    "wc": "toilet", "water_closet": "toilet", "commode": "toilet", "lavatory": "toilet",
    "kitchen_sink": "sink", "washbasin": "sink", "wash_basin": "sink", "basin": "sink",
    "washstand": "sink", "mop_sink": "sink",
    "refrigerator": "fridge", "freezer": "fridge", "icebox": "fridge", "fridge_freezer": "fridge",
    "wall_mirror": "mirror", "full_length_mirror": "mirror", "dressing_mirror": "mirror",
    "floor_mirror": "mirror", "looking_glass": "mirror", "vanity_mirror": "mirror",
}


def _normalize_ftype(raw: str) -> str:
    """Map a free-form furniture label to a known type, or 'default' if nothing matches."""
    t = re.sub(r"[^a-z_]", "", str(raw).lower().strip().replace(" ", "_").replace("-", "_"))
    t = re.sub(r"_+", "_", t).strip("_")
    if t in FURNITURE_SIZES:
        return t
    if t in _FTYPE_ALIASES:
        return _FTYPE_ALIASES[t]
    # positional suffixes etc: "dog_bed_in_a_corner" contains "dog_bed".
    # Longest key first so "dog_bed" wins over "bed", "coffee_table" over "table".
    for known in sorted((*FURNITURE_SIZES, *_FTYPE_ALIASES), key=len, reverse=True):
        if known != "default" and known in t:
            return _FTYPE_ALIASES.get(known, known)
    return "default"

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
    "cat_tree": (170, 140, 110),
    "dog_bed": (200, 170, 140),
    "litter_box": (190, 190, 200),
    "stove": (90, 90, 95),
    "toilet": (225, 230, 235),
    "sink": (200, 215, 225),
    "fridge": (185, 192, 202),
    "mirror": (170, 205, 220),
    "default": (150, 200, 150),
}

SOFT_WEIGHTS = {
    "circulation": 0.35,
    "balance": 0.25,
    "focal_point": 0.20,
    "natural_light": 0.10,
    "ergonomics": 0.10,
}

# What gets left OUT of the ControlNet depth map. The original rule kept only big
# wall-anchored pieces, because every item was extruded as a solid cuboid and the small
# ones just became box-noise on the floor. Semantic silhouettes removed that reason — a
# coffee table now projects as a floating top on four legs, which is a useful signal, not
# noise — so only genuinely flat floor coverings stay out: at 2cm tall they carry no
# depth information and render as a stray rectangle outline.
_DEPTH_SKIP_TYPES = {"rug", "carpet", "mat", "doormat"}



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




def _parse_llm_layout(text: str) -> dict | None:
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
        return json.loads(text)
    except Exception:
        return None
