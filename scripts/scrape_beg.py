#!/usr/bin/env python3
"""
北二高家具（www.b-e-g.com.tw）二手家具爬蟲

只收各分類的「二手」子分類與二手辦公家具；全新、展示出清、二手家電不收。
二手品庫存少（全站約數十件）且賣掉就下架，列表沒有分頁，建議定期重跑。

用法：
    python scripts/scrape_beg.py            # 寫入 secondhand_tw.json
抓完重建向量：
    python scripts/build_ikea_embeddings.py --brand secondhand --rebuild
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from pathlib import Path

import urllib.request

BASE = "https://www.b-e-g.com.tw/products/"
BRAND = "北二高家具"
OUTPUT_PATH = Path(__file__).parent.parent / "designbridge" / "furniture_kb" / "secondhand_tw.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
_REQUEST_GAP = 0.5

# (group_id, second_id) → 預設 category；second_id 是該分類底下的「二手」子分類
LISTINGS: list[tuple[int, int | None, str]] = [
    (4352, 22857, "sofa"),       # 各式沙發
    (4773, 22860, "storage"),    # 衣櫥櫃
    (4786, 22862, "storage"),    # 電視櫃
    (4787, 22864, "table"),      # 茶几&桌類
    (4788, 22866, ""),           # 實木家具（什麼都有，看名稱）
    (4789, 22868, "chair"),      # 椅子
    (18612, 22870, "storage"),   # 收納斗櫃
    (18613, 22872, "bed"),       # 床墊&床架組
    (4351, None, ""),            # 二手辦公家具OA
]

# 家電、單賣的床墊在渲染圖上比不到（床墊附床架的組合照收）
_EXCLUDE_RE = re.compile(r"冰箱|洗衣機|冷氣|電視機|微波|烘碗|飲水機|保險箱")
_MATTRESS_ONLY_RE = re.compile(r"^(?!.*(床架|床組|床底)).*床墊")

# 名稱 → (category, subcategory)，由上往下第一個符合的為準；跟 furniture_kb._SUBCATEGORY_RULES 同一套細分類
_RULES: list[tuple[str, str, str]] = [
    (r"沙發床", "sofa", "sofa-bed"),
    (r"桌椅組|桌椅套組|\d桌\d椅", "table", "table-chair-set"),
    # 「三人座沙發椅」是沙發，先排除多人座才判斷單椅
    (r"(雙人|兩人|二人|三人|四人|L型).*沙發|沙發.*(雙人|三人|L型)", "sofa", "sofa"),
    (r"單人沙發|沙發椅|扶手沙發|主人椅|休閒椅|扶手椅|躺椅|搖椅", "chair", "armchair"),
    (r"沙發", "sofa", "sofa"),
    (r"吧台椅|吧檯椅|高腳椅", "chair", "bar-stool"),
    (r"辦公椅|電腦椅|書桌椅|主管椅|職員椅|會議椅|網椅", "chair", "desk-chair"),
    (r"腳凳|椅凳|凳", "chair", "stool"),
    (r"長凳|長椅", "chair", "bench"),
    (r"餐椅|椅", "chair", "dining-chair"),
    (r"電視櫃|視聽櫃", "storage", "tv-bench"),
    (r"床頭櫃|床邊櫃", "storage", "bedside-table"),
    (r"衣櫃|衣櫥", "storage", "wardrobe"),
    (r"斗櫃|抽屜櫃|五斗|四斗|三斗", "storage", "chest-of-drawers"),
    (r"展示櫃|玻璃櫃|酒櫃", "storage", "display-cabinet"),
    (r"書櫃|書架", "storage", "bookcase"),
    (r"層架|置物架|格櫃|格.*儲物櫃|開放式", "storage", "open-storage"),
    (r"鐵櫃|公文櫃|檔案櫃|餐櫃|邊櫃|收納櫃|鞋櫃|櫃", "storage", "sideboard"),
    (r"餐桌", "table", "dining-table"),
    (r"書桌|辦公桌|電腦桌|工作桌|會議桌|主管桌", "table", "desk"),
    (r"化妝桌|梳妝", "table", "dressing-table"),
    (r"茶几|茶幾|邊桌|邊几|和室桌|矮桌|桌", "table", "coffee-side-table"),
    (r"床架|床組|床底|雙人床|單人床|床", "bed", "bed-frame"),
]


def _get(url: str) -> str:
    # 用 urllib 而不是 requests：網站憑證缺中繼憑證，certifi 驗不過，系統憑證庫可以
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=20) as r:
        text = r.read().decode("utf-8", errors="replace")
    time.sleep(_REQUEST_GAP)
    return text


def classify(name: str, default: str) -> tuple[str, str] | None:
    """名稱比對細分類；比不到就用列表頁的分類（沒有分類的列表比不到就不收）。"""
    clean = re.sub(r"【[^】]*】", "", name)   # 「【二手品】」「【沙發+茶几組】」這類標籤不算
    for pattern, cat, sub in _RULES:
        if re.search(pattern, clean):
            return cat, sub
    return (default, "") if default else None


def parse_listing(page: str) -> list[dict]:
    items = []
    for m in re.finditer(r'<li class="item">(.*?)</li>', page, re.S):
        block = m.group(1)
        link = re.search(r'href="info\.php\?id=(\d+)[^"]*"\s+title="([^"]*)"', block)
        img = re.search(r'<img src="([^"]+)"', block)
        price = re.search(r"\$\s*([\d,]+)", block)
        if not link:
            continue
        items.append({
            "id": link.group(1),
            "name": html.unescape(link.group(2)).strip(),
            "image_url": img.group(1) if img else "",
            "price": int(price.group(1).replace(",", "")) if price else 0,
        })
    return items


def parse_detail(page: str) -> dict:
    """商品頁的尺寸（寬 x 深 x 高 cm）與材質。"""
    text = html.unescape(re.sub(r"<[^>]+>", " ", page))
    out: dict = {}
    size = re.search(r"尺寸：\s*寬\s*([\d.]+)\s*cm\s*x\s*深\s*([\d.]+)\s*cm\s*x\s*高\s*([\d.]+)\s*cm", text)
    if size:
        out["width_cm"], out["depth_cm"], out["height_cm"] = (float(v) for v in size.groups())
    material = re.search(r"材質：\s*([^\s]+)", text)
    if material:
        out["material"] = material.group(1)
    return out


def scrape() -> list[dict]:
    seen: set[str] = set()
    products: list[dict] = []
    for group_id, second_id, default_cat in LISTINGS:
        url = f"{BASE}index.php?group_id={group_id}&title_id=5849"
        if second_id:
            url += f"&second_id={second_id}"
        listing = parse_listing(_get(url))
        print(f"[beg] group {group_id}/{second_id}: {len(listing)} 件")
        for it in listing:
            if (it["id"] in seen or _EXCLUDE_RE.search(it["name"]) or _MATTRESS_ONLY_RE.search(it["name"])
                    or not it["price"] or not it["image_url"]):
                continue
            cls = classify(it["name"], default_cat)
            if cls is None:
                print(f"  略過（分類不明）：{it['name']}")
                continue
            seen.add(it["id"])
            detail_url = f"{BASE}info.php?id={it['id']}&title_id=5849"
            try:
                detail = parse_detail(_get(detail_url))
            except OSError as e:
                print(f"  商品頁讀取失敗 {it['id']}：{e}")
                detail = {}
            products.append({
                "name": it["name"],
                "category": cls[0],
                "subcategory": cls[1],
                "brand": BRAND,
                "condition": "二手",
                "product_code": it["id"],
                "price": it["price"],
                "currency": "TWD",
                **detail,
                "url": detail_url,
                "image_url": it["image_url"],
            })
    return products


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    products = scrape()
    args.output.write_text(json.dumps(products, ensure_ascii=False, indent=2), encoding="utf-8")
    by_cat: dict[str, int] = {}
    for p in products:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    print(f"[beg] 共 {len(products)} 件 → {args.output}  {by_cat}")


if __name__ == "__main__":
    main()
