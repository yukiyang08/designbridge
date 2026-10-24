#!/usr/bin/env python3
"""
IKEA 台灣家具爬蟲 (www.ikea.com.tw)

從官方 sitemap 取得所有商品頁網址（網址本身帶分類，例如 /zh/products/sofas/sofas/...），
依下方 SUBCATEGORIES 白名單挑出室內家具，再逐頁讀 <head> 的 og:title / 價格 / 主圖。
舊版捲動分類列表頁每類只拿得到前 20～30 件，也漏掉扶手椅、茶几、書桌、電視櫃等分類。

用法：
    python scripts/scrape_ikea.py                 # 全部重抓，寫入 ikea_tw.json
    python scripts/scrape_ikea.py --limit 5       # 每個子分類只抓 5 件（測試用）
    python scripts/scrape_ikea.py --upload        # 抓完順便 upsert 到 Supabase ikea_products

輸出：designbridge/furniture_kb/ikea_tw.json，每筆格式：
{
  "name": "ISMANTORP 扶手椅，金屬 淺灰米色/Tibbleby 淺米色",
  "category": "chair",           # sofa / table / chair / lamp / rug / storage / bed
  "subcategory": "armchair",     # 細分類，給前端篩選與置換用
  "brand": "IKEA",
  "price": 2499,
  "currency": "TWD",
  "url": "https://www.ikea.com.tw/zh/products/...",
  "image_url": "https://www.ikea.com.tw/...",
  "style_tags": []
}
抓完要重建向量：python scripts/build_ikea_embeddings.py --rebuild
"""

from __future__ import annotations

import argparse
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://www.ikea.com.tw"
SITEMAP_PIP = f"{BASE_URL}/dairyfarm/tw/static_content/sitemaps/taiwan/sitemap-pip-zh.xml"

# 商品網址路徑（/zh/products/ 之後兩層）→ (category, subcategory)
# 系統櫃 / 系統衣櫃（cabinets/system-cabinets、wardrobes/system-wardrobes）大多是門板、層板等零件，不收
SUBCATEGORIES: dict[str, tuple[str, str]] = {
    "sofas/sofas": ("sofa", "sofa"),
    "sofas/sofa-beds": ("sofa", "sofa-bed"),
    "armchairs-footstool-and-sofa-tables/armchairs": ("chair", "armchair"),
    "armchairs-footstool-and-sofa-tables/footstools": ("chair", "footstool"),
    "dining-seating/non-upholstered-chairs": ("chair", "dining-chair"),
    "dining-seating/upholstered-chairs": ("chair", "dining-chair"),
    "dining-seating/stools": ("chair", "stool"),
    "dining-seating/bar-stools": ("chair", "bar-stool"),
    "dining-seating/benches": ("chair", "bench"),
    "home-workspace/home-work-chairs": ("chair", "desk-chair"),
    "dining-tables/tables": ("table", "dining-table"),
    "sofa-tables/sofa-tables-and-side-tables": ("table", "coffee-side-table"),
    "home-workspace/home-desks": ("table", "desk"),
    "luminaires/pendant-lamps": ("lamp", "pendant-lamp"),
    "luminaires/ceiling-lamps-and-spotlights": ("lamp", "ceiling-lamp"),
    "luminaires/floor-lamps": ("lamp", "floor-lamp"),
    "luminaires/table-lamps": ("lamp", "table-lamp"),
    "luminaires/desk-lamps-and-clamp-lamps": ("lamp", "desk-lamp"),
    "luminaires/clamp-and-wall-lamps": ("lamp", "wall-lamp"),
    "home-furnishing-rugs/rugs": ("rug", "rug"),
    "home-furnishing-rugs/small-rugs-and-runners": ("rug", "runner"),
    "cabinets/bookcases": ("storage", "bookcase"),
    "cabinets/open-storage": ("storage", "open-storage"),
    "cabinets/solitaire-cabinets-and-sideboards": ("storage", "sideboard"),
    "display-furniture/display-cabinets": ("storage", "display-cabinet"),
    "chests-and-other-furniture/chest-of-drawers": ("storage", "chest-of-drawers"),
    "chests-and-other-furniture/bedside-tables": ("storage", "bedside-table"),
    "media-furniture/tv-benches": ("storage", "tv-bench"),
    "wardrobes/solitaire-wardrobes": ("storage", "wardrobe"),
    "beds/bed-frames": ("bed", "bed-frame"),
    "beds/bed-with-upholstered-headboard": ("bed", "upholstered-bed"),
}

# 名稱含這些字的是配件或零件，不是整件家具；出現在「附…」「含…」後面的是商品本身附帶的
#（「扶手椅附椅墊」「書櫃附門板組合」），不算。布套、椅套無論怎麼寫都是套子
_COVER_RE = re.compile(r"(椅套|沙發套|布套|套組件|套[，,]|套$)")
_ACCESSORY_RE = re.compile(r"(椅墊|座墊|坐墊|靠墊|床墊|床腳|椅腳|沙發腳|桌腳|腳座|零件|配件|替換|框架|門板|背板|層板|抽屜面板|把手|旋鈕|燈泡|燈罩$)")
_INCLUDED_RE = re.compile(r"[附含][^，,\s]*")


def _is_accessory(name: str) -> bool:
    if re.match(r"^[^\s，,]+\s+扶手[，,]", name):   # 單獨販售的扶手零件（「MALMKÖPING 扶手，…」）
        return True
    return bool(_COVER_RE.search(name) or _ACCESSORY_RE.search(_INCLUDED_RE.sub("", name)))
# 桌類裡混了成套販售的桌椅（「一桌二椅」「餐桌附4張餐椅」），另外標成桌椅組 table-chair-set
_TABLE_SET_RE = re.compile(r"(桌椅組|一桌[一二三四五六兩]椅|附\s*\d+\s*張\S*椅)")
# 沙發分類裡有大量單獨販售的模組（轉角座、單人座模組），拿來置換會缺一角
_MODULE_RE = re.compile(r"(模組|區塊|轉角座$)")

OUTPUT_PATH = Path(__file__).parent.parent / "designbridge" / "furniture_kb" / "ikea_tw.json"
CACHE_PATH = Path(__file__).parent.parent / "designbridge" / "furniture_kb" / ".ikea_scrape_cache.jsonl"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
_HEAD_BYTES = 160_000   # og 標籤都在 <head> 前段，整頁 ~640KB 不用全部下載
_REQUEST_GAP = 0.35     # 每個執行緒兩次請求間隔（秒），3 個執行緒約每秒 8 次


def _meta(text: str, prop: str) -> Optional[str]:
    m = re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % re.escape(prop), text)
    return html.unescape(m.group(1)).strip() if m else None


def fetch_product(url: str) -> Optional[dict]:
    """讀商品頁前段，回傳 name / price / image_url；失敗回傳 None。"""
    try:
        with requests.get(url, headers=HEADERS, timeout=30, stream=True) as r:
            if r.status_code != 200:
                return None
            buf = b""
            for chunk in r.iter_content(16_384):
                buf += chunk
                if len(buf) >= _HEAD_BYTES or b"</head>" in buf:
                    break
        text = buf.decode("utf-8", errors="ignore")
        title = _meta(text, "og:title") or ""
        name = re.sub(r"\s*\|\s*IKEA.*$", "", title).replace(" - ", " ", 1).strip()
        price = _meta(text, "product:price:amount")
        image = _meta(text, "og:image") or ""
        if not name or not price:
            return None
        return {"name": name, "price": int(float(price)), "image_url": image}
    except Exception:
        return None


def list_product_urls(limit: int = 0) -> list[tuple[str, str, str]]:
    """從 sitemap 挑出白名單子分類的商品頁 → [(url, category, subcategory)]。"""
    text = requests.get(SITEMAP_PIP, headers=HEADERS, timeout=60).text
    per_sub: dict[str, int] = {}
    out = []
    for url in re.findall(r"<loc>(.*?)</loc>", text):
        parts = url.split("/zh/products/", 1)[-1].split("/")
        key = "/".join(parts[:2])
        if key not in SUBCATEGORIES:
            continue
        if limit and per_sub.get(key, 0) >= limit:
            continue
        per_sub[key] = per_sub.get(key, 0) + 1
        out.append((url, *SUBCATEGORIES[key]))
    return out


def _load_cache() -> dict[str, dict]:
    cache: dict[str, dict] = {}
    if CACHE_PATH.exists():
        for line in CACHE_PATH.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                cache[row["url"]] = row
            except Exception:
                pass
    return cache


def scrape(limit: int = 0, workers: int = 3) -> list[dict]:
    targets = list_product_urls(limit)
    print(f"sitemap 中符合的商品頁：{len(targets)} 件")
    cache = _load_cache()   # 中斷後重跑不重抓已成功的頁面
    todo = [t for t in targets if t[0] not in cache]
    print(f"已快取 {len(targets) - len(todo)} 件，要抓 {len(todo)} 件")

    lock = threading.Lock()
    done = [0]

    def work(target: tuple[str, str, str]) -> None:
        url = target[0]
        info = fetch_product(url)
        time.sleep(_REQUEST_GAP)
        with lock:
            done[0] += 1
            if info:
                row = {"url": url, **info}
                cache[url] = row
                with CACHE_PATH.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if done[0] % 200 == 0:
                print(f"  進度 {done[0]}/{len(todo)}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, todo))

    items: list[dict] = []
    skipped = {"missing": 0, "no_image": 0, "accessory": 0, "module": 0}
    for url, category, subcategory in targets:
        row = cache.get(url)
        if not row:
            skipped["missing"] += 1
            continue
        name = row["name"]
        if not re.search(r"\.(jpe?g|png|webp)$", row["image_url"], re.I):   # 頁面沒有主圖，無法比對也無法置換
            skipped["no_image"] += 1
            continue
        if _is_accessory(name):
            skipped["accessory"] += 1
            continue
        if category == "sofa" and _MODULE_RE.search(name):
            skipped["module"] += 1
            continue
        if category == "table" and _TABLE_SET_RE.search(name):
            subcategory = "table-chair-set"
        items.append({
            "name": name,
            "category": category,
            "subcategory": subcategory,
            "brand": "IKEA",
            "price": row["price"],
            "currency": "TWD",
            "url": url,
            "image_url": row["image_url"],
            "style_tags": [],
        })
    print(f"略過：抓取失敗 {skipped['missing']}、沒有圖片 {skipped['no_image']}、配件 {skipped['accessory']}、沙發模組 {skipped['module']}")
    return items


def _make_product_id(item: dict) -> str:
    """從 URL 或 name+category 產生穩定的商品 ID。"""
    import hashlib
    key = item.get("url") or f"{item.get('name')}_{item.get('category')}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


def _upsert_to_supabase(items: list[dict]) -> None:
    """將商品 upsert 到 Supabase ikea_products 表。需設定環境變數 SUPABASE_URL / SUPABASE_KEY。"""
    import os
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("  [supabase] 未設定 SUPABASE_URL / SUPABASE_KEY，跳過 Supabase upsert")
        return

    try:
        from supabase import create_client
        client = create_client(url, key)

        rows = [
            {
                "id": _make_product_id(i),
                "name": i["name"],
                "category": i["category"],
                "price": i["price"],
                "currency": i.get("currency", "TWD"),
                "url": i.get("url") or "",
                "image_url": i.get("image_url") or "",
                "style_tags": i.get("style_tags") or [],
            }
            for i in items
        ]

        # 分批 upsert（Supabase 單次最多 ~500 筆）
        batch_size = 100
        total_upserted = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            client.table("ikea_products").upsert(batch).execute()
            total_upserted += len(batch)
            print(f"  [supabase] upserted {total_upserted}/{len(rows)} rows...")
            time.sleep(0.3)

        print(f"  [supabase] 完成：共 {total_upserted} 件商品 upserted")
    except Exception as e:
        print(f"  [supabase] upsert 失敗：{e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="IKEA 台灣家具爬蟲（sitemap 版）")
    parser.add_argument("--limit", type=int, default=0, help="每個子分類最多抓幾件（0 = 全部）")
    parser.add_argument("--workers", type=int, default=3, help="同時抓取的執行緒數")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="輸出 JSON 路徑")
    parser.add_argument("--upload", action="store_true", help="抓完 upsert 到 Supabase（共用資料庫，預設不上傳）")
    args = parser.parse_args()

    unique = scrape(limit=args.limit, workers=args.workers)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成！共 {len(unique)} 件商品，已存到：{args.output}")

    from collections import Counter
    for cat, cnt in sorted(Counter(i["category"] for i in unique).items()):
        subs = Counter(i["subcategory"] for i in unique if i["category"] == cat)
        print(f"  {cat}: {cnt} 件  " + "、".join(f"{s} {n}" for s, n in subs.most_common()))

    if args.upload:
        print("\n[supabase] 開始 upsert...")
        _upsert_to_supabase(unique)


if __name__ == "__main__":
    main()
