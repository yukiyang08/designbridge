#!/usr/bin/env python3
"""
北二高家具（www.b-e-g.com.tw）二手家具爬蟲

只收各分類的「二手」子分類與二手辦公家具；全新、展示出清、二手家電不收。
二手品賣掉就下架，建議定期重跑；只換掉北二高的商品，其他店家（CSV 匯入的）不動，
向量也一起更新（沿用舊圖片的向量，只算新商品）。

用法：
    python scripts/scrape_beg.py
    python scripts/scrape_beg.py --dry-run   # 只列出抓到的商品，不寫檔
"""

from __future__ import annotations

import argparse
import html
import re
import time
import urllib.request

from secondhand_store import classify, save_store

BASE = "https://www.b-e-g.com.tw/products/"
BRAND = "北二高家具"
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

def _get(url: str) -> str:
    # 用 urllib 而不是 requests：網站憑證缺中繼憑證，certifi 驗不過，系統憑證庫可以
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=20) as r:
        text = r.read().decode("utf-8", errors="replace")
    time.sleep(_REQUEST_GAP)
    return text


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
        # 列表每頁 15 件，超過要翻頁；翻到沒有新商品為止
        listing, ids, page = [], set(), 1
        while True:
            batch = [it for it in parse_listing(_get(f"{url}&page={page}")) if it["id"] not in ids]
            if not batch:
                break
            listing += batch
            ids |= {it["id"] for it in batch}
            page += 1
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
                "id": f"beg-{it['id']}",
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
    parser.add_argument("--dry-run", action="store_true", help="只列出抓到的商品，不寫檔")
    args = parser.parse_args()

    products = scrape()
    by_cat: dict[str, int] = {}
    for p in products:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    print(f"[beg] 共 {len(products)} 件  {by_cat}")
    if args.dry_run:
        for p in products:
            print(f"  {p['category']:8} {p['subcategory']:18} {p['price']:>7}  {p['name']}")
        return
    merged = save_store(BRAND, products)
    print(f"[beg] 二手資料共 {len(merged)} 件（含其他店家）")


if __name__ == "__main__":
    main()
