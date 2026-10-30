"""Furniture vocabulary, sizes/colors, the FurnitureItem dataclass and LLM-JSON parsing."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any



# 家具標準尺寸（寬, 深），單位公尺；家具大小不能跟著房間比例縮放。
# 有 IKEA 商品的類別取 furniture_kb/meshes/manifest.json 的中位數附近。
FURNITURE_SIZES: dict[str, tuple[float, float]] = {
    "sofa": (2.00, 0.90),
    "loveseat": (1.50, 0.85),
    "coffee_table": (1.10, 0.60),
    "tv_unit": (1.60, 0.40),
    "tv": (1.20, 0.25),
    "dining_table": (1.40, 0.80),
    "chair": (0.46, 0.52),
    "armchair": (0.80, 0.80),
    "bed": (1.55, 2.05),
    "bunk_bed": (1.00, 2.05),
    "bunk_ladder": (0.30, 0.40),
    "wardrobe": (1.20, 0.60),
    "desk": (1.20, 0.60),
    "bookshelf": (0.80, 0.35),
    "side_table": (0.45, 0.45),
    "nightstand": (0.45, 0.40),
    "lamp": (0.35, 0.35),
    "rug": (2.00, 1.40),
    "plant": (0.40, 0.40),
    "cabinet": (0.85, 0.40),
    "dresser": (0.90, 0.50),
    "shelf": (0.80, 0.35),
    "cat_tree": (0.50, 0.50),
    "dog_bed": (0.80, 0.60),
    "litter_box": (0.50, 0.40),
    # 廚衛設備與鏡子：風水規則（開門不見灶／不見廁所、水火不相容、鏡不照床…）
    # 要拿它們當標的，沒有進受控詞彙的話會被 _normalize_ftype 收斂成 default，
    # 規則就永遠不會觸發。
    "stove": (0.60, 0.60),
    "toilet": (0.40, 0.70),
    "sink": (0.60, 0.50),
    "fridge": (0.70, 0.70),
    "mirror": (0.60, 0.10),
    "default": (0.60, 0.50),
}

# LLM 給的尺寸可偏離標準尺寸的倍率範圍。寬度差異大（單人床、L 型沙發、八人餐桌），
# 深度幾乎是固定的（沙發 0.8–1 m、櫃子 0.4–0.6 m），所以收得比較緊；床長更固定，地毯兩邊都不定
_WIDTH_RATIO = (0.5, 1.6)
_DEPTH_RATIO = (0.75, 1.4)
_TYPE_RATIOS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "bed": (_WIDTH_RATIO, (0.9, 1.15)),
    "bunk_bed": (_WIDTH_RATIO, (0.9, 1.15)),
    "rug": ((0.5, 2.0), (0.5, 2.0)),
}
_ROOM_FILL = 0.96


def room_size(space_info: dict | None) -> tuple[float, float]:
    """房間寬深（公尺）；佈局、提示詞、平面圖都要用同一組預設值。"""
    size = (space_info or {}).get("estimated_size") or {}
    return float(size.get("width") or 4.0), float(size.get("depth") or 4.0)


def default_footprint(ftype: str, room_w: float, room_d: float) -> tuple[float, float]:
    """標準尺寸換成正規化的 (w, h)。"""
    w_m, d_m = FURNITURE_SIZES.get(ftype, FURNITURE_SIZES["default"])
    return min(w_m / room_w, _ROOM_FILL), min(d_m / room_d, _ROOM_FILL)


def fit_real_size(item: "FurnitureItem", room_w: float, room_d: float) -> bool:
    """把 LLM 粗估的 footprint 夾回標準尺寸的合理範圍，中心不動。回傳是否有改。

    靠側牆的床、沙發會轉 90° 擺，所以長短邊取跟標準尺寸較接近的那個方向比。
    """
    std_w, std_d = FURNITURE_SIZES.get(item.type, FURNITURE_SIZES["default"])
    w_ratio, d_ratio = _TYPE_RATIOS.get(item.type, (_WIDTH_RATIO, _DEPTH_RATIO))
    w_m, d_m = item.w * room_w, item.h * room_d
    if w_m <= 0 or d_m <= 0:
        w_m, d_m = std_w, std_d
    elif abs(math.log(w_m / std_d)) + abs(math.log(d_m / std_w)) < (
            abs(math.log(w_m / std_w)) + abs(math.log(d_m / std_d))):
        std_w, std_d, w_ratio, d_ratio = std_d, std_w, d_ratio, w_ratio
    new_w = min(max(w_m, std_w * w_ratio[0]), std_w * w_ratio[1]) / room_w
    new_h = min(max(d_m, std_d * d_ratio[0]), std_d * d_ratio[1]) / room_d
    new_w, new_h = min(new_w, _ROOM_FILL), min(new_h, _ROOM_FILL)
    if abs(new_w - item.w) < 1e-4 and abs(new_h - item.h) < 1e-4:
        return False
    item.x += (item.w - new_w) / 2
    item.y += (item.h - new_h) / 2
    item.w, item.h = new_w, new_h
    return True


def size_reference_text() -> str:
    """給佈局 LLM 的標準尺寸表。"""
    return "\n".join(
        f"- {k}: {w:.2f} × {d:.2f} m" for k, (w, d) in FURNITURE_SIZES.items() if k != "default"
    )

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
    # 跟班家具（餐椅、床頭櫃…）綁定的主家具 id 與相對位移；不序列化，只在單次佈局中整組移動用
    anchor: str = ""
    offset: tuple[float, float] = (0.0, 0.0)
    # 綁定的 IKEA SKU（product_meshes.assign_products 填入）；空字串 = 沒有對應商品
    product_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "type": self.type,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "w": round(self.w, 4),
            "h": round(self.h, 4),
            "rotation": self.rotation,
        }
        if self.product_id:
            d["product_id"] = self.product_id
        return d




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
