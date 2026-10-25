"""家具資料庫各品牌爬蟲共用的欄位推導：系列名、顏色、尺寸換算。"""

from __future__ import annotations

import re
from typing import Optional

# 高度、深度在不同商品頁的寫法（沙發常只標「含靠墊高度」、躺椅沙發標最大／最小深度）
_HEIGHT_KEYS = ("高度", "總高度", "含靠墊高度", "含頭靠墊高度", "椅背高度", "床頭板高度")
_DIAMETER_KEYS = ("燈罩直徑", "直徑", "底座直徑")


def dims_to_cm(dims: dict[str, float], category: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """商品頁「尺寸」區塊 {標籤: 公分} → (寬, 深, 高)。寬 = 沿牆方向／較長邊，
    規則同 designbridge.layout.product_mesh_build.dims_to_m，另外補上沙發常見的高度寫法。"""
    d = dims or {}
    height = next((d[k] for k in _HEIGHT_KEYS if d.get(k)), None)
    diameter = next((d[k] for k in _DIAMETER_KEYS if d.get(k)), None)
    if category == "bed":
        w, dep = d.get("寬度"), d.get("長度") or d.get("深度")
        if not (w and dep) and d.get("床墊寬度") and d.get("床墊長度"):
            w, dep = d["床墊寬度"] + 10, d["床墊長度"] + 10   # 只標床墊尺寸：床框每邊約多 5 公分
    elif "寬度" in d and ("深度" in d or "最大深度" in d):
        w, dep = d["寬度"], d.get("深度") or d["最大深度"]
    elif "長度" in d and "寬度" in d:
        w, dep = max(d["長度"], d["寬度"]), min(d["長度"], d["寬度"])
    elif diameter:
        w = dep = diameter
    else:
        w, dep = d.get("寬度") or d.get("長度"), d.get("深度")
    return w or None, dep or None, height


def series_of(name: str) -> Optional[str]:
    """名稱開頭的系列名：「KIVIK 三人座沙發…」→ KIVIK、「IKEA PS 2026/HÖGVED 餐桌…」→ IKEA PS 2026。"""
    m = re.match(r"(IKEA PS \d{4}|[A-Za-zÀ-ÿ][^\s，,]*)", name.strip())
    if not m:
        return None
    return m.group(1).split("/")[0] if not m.group(1).startswith("IKEA PS") else m.group(1)


def color_of(name: str) -> Optional[str]:
    """名稱裡的顏色、木紋與木種：「…，金屬 淺灰米色/Tibbleby 淺米色」→ 淺灰米色/淺米色。"""
    found: list[str] = []
    for token in re.findall(r"[一-鿿]{0,4}(?:色|木紋)|橡木|胡桃木|松木|樺木|梣木|櫸木|柚木|籐|竹|大理石", name):
        token = re.sub(r"^(?:附|含|與|及|和)", "", token)
        if (len(token) >= 2 or token in ("籐", "竹")) and token not in found:
            found.append(token)
    return "/".join(found[:3]) or None
