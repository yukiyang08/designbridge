#!/usr/bin/env python3
"""
詩肯柚木家具爬蟲 (www.scanteak.com.tw)

網站是 WooCommerce，直接讀公開的 Store API（/wp-json/wc/store/v1/products）拿名稱、價格、
分類與主圖，不用解析網頁。依商品名稱判斷 category / subcategory，跟 ikea_tw.json 同一套分類。

用法：
    python scripts/scrape_scanteak.py
抓完重建向量：
    python scripts/build_ikea_embeddings.py --brand scanteak --rebuild

輸出：designbridge/furniture_kb/scanteak_tw.json（欄位同 ikea_tw.json，brand 為「詩肯柚木」）
"""

from __future__ import annotations

import html
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import requests

from furniture_fields import color_of, series_of

API = "https://www.scanteak.com.tw/wp-json/wc/store/v1/products"
OUTPUT_PATH = Path(__file__).parent.parent / "designbridge" / "furniture_kb" / "scanteak_tw.json"
BRAND = "詩肯柚木"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

# 床墊、零件、配件與不在 7 大類裡的商品
_EXCLUDE_RE = re.compile(r"(床墊|門片|桶框|一抽|二抽|抽屜\(|托盤|螢幕架|化妝鏡|衣帽架|吊衣|收納方格)")

# (名稱關鍵字, category, subcategory)，由上往下第一個符合的為準
_RULES: list[tuple[str, str, str]] = [
    (r"沙發床", "sofa", "sofa-bed"),
    (r"1人座.*沙發", "chair", "armchair"),
    (r"沙發", "sofa", "sofa"),
    (r"吧檯椅|中島椅", "chair", "bar-stool"),
    (r"書桌椅", "chair", "desk-chair"),
    (r"腳椅|穿鞋", "chair", "footstool"),
    (r"椅凳|STOOL|化妝椅|ㄇ型椅", "chair", "stool"),
    (r"長凳|SWIVEL", "chair", "bench"),
    (r"椅", "chair", "dining-chair"),
    (r"茶几|邊几", "table", "coffee-side-table"),
    (r"書桌|寫字桌", "table", "desk"),
    (r"化妝桌", "table", "dressing-table"),
    (r"餐桌|丹麥桌|丹麥長桌", "table", "dining-table"),
    (r"電視櫃", "storage", "tv-bench"),
    (r"床頭櫃", "storage", "bedside-table"),
    (r"斗櫃", "storage", "chest-of-drawers"),
    (r"書櫃|書架", "storage", "bookcase"),
    (r"展示架|置物架|層架|格櫃", "storage", "open-storage"),
    (r"櫃|抽屜", "storage", "sideboard"),
    (r"床架", "bed", "bed-frame"),
]


def _clean_name(raw: str) -> str:
    """去掉開頭的型號（「T11128-KULLAN …」→「KULLAN …」）。"""
    name = html.unescape(raw).strip()
    return re.sub(r"^T?\d+\s*-?\s*", "", name).strip() or name


def classify(name: str) -> Optional[tuple[str, str]]:
    if _EXCLUDE_RE.search(name):
        return None
    for pattern, category, subcategory in _RULES:
        if re.search(pattern, name, re.I):
            return category, subcategory
    return None


def _dims(p: dict) -> dict[str, float]:
    """API 的 length / width / height（公分）→ 寬 / 深 / 高；空字串代表沒填。"""
    raw = p.get("dimensions") or {}
    out = {}
    for src, label in (("length", "寬度"), ("width", "深度"), ("height", "高度")):
        try:
            out[label] = float(raw.get(src) or "")
        except ValueError:
            pass
    return out


def fetch_all() -> list[dict]:
    products: list[dict] = []
    page = 1
    while True:
        r = requests.get(API, params={"per_page": 100, "page": page}, headers=HEADERS, timeout=40)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        products += batch
        page += 1
        time.sleep(0.5)
    return products


def main() -> None:
    raw = fetch_all()
    print(f"Store API 商品：{len(raw)} 件")

    items: list[dict] = []
    skipped: list[str] = []
    for p in raw:
        name = _clean_name(p.get("name") or "")
        cls = classify(name)
        prices = p.get("prices") or {}
        image = ((p.get("images") or [{}])[0]).get("src") or ""
        # 多規格商品（不同尺寸的床架）主價格是 0，改用規格中的最低價
        amount = int(prices.get("price") or 0) or int((prices.get("price_range") or {}).get("min_amount") or 0)
        if not cls or not amount or not image:
            skipped.append(name)
            continue
        price = amount // (10 ** int(prices.get("currency_minor_unit") or 0))
        dims = _dims(p)
        items.append({
            "name": name,
            "category": cls[0],
            "subcategory": cls[1],
            "brand": BRAND,
            "series": series_of(name),
            "product_code": (p.get("sku") or str(p.get("id"))).strip(" ."),
            "color": color_of(name),
            "price": price,
            "currency": prices.get("currency_code") or "TWD",
            "width_cm": dims.get("寬度"),
            "depth_cm": dims.get("深度"),
            "height_cm": dims.get("高度"),
            "dims": dims,
            "url": p.get("permalink") or "",
            "image_url": image,
            "style_tags": [],   # 由 scripts/tag_furniture_styles.py 用 CLIP 向量標
        })

    OUTPUT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成！共 {len(items)} 件，已存到：{OUTPUT_PATH}")
    for cat, cnt in sorted(Counter(i["category"] for i in items).items()):
        subs = Counter(i["subcategory"] for i in items if i["category"] == cat)
        print(f"  {cat}: {cnt} 件  " + "、".join(f"{s} {n}" for s, n in subs.most_common()))
    print(f"略過 {len(skipped)} 件：" + "、".join(skipped))


if __name__ == "__main__":
    main()
