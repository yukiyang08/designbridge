#!/usr/bin/env python3
"""
把其他店家的二手家具從 CSV 匯入（估價的二手推薦、家具查詢的二手清單都會用到）。

每次匯入會整批換掉同一個店家的商品（CSV 沒有的就當作已下架），其他店家不動；
向量一起更新，沿用舊圖片的向量、只替新商品下載圖片。範本見 docs/secondhand_import_template.csv。

欄位（第一列是標題，中英文都可以）：
    必填：名稱 name、價格 price、網址 url、圖片網址 image_url
    選填：分類 category（沙發／椅子／桌子／收納／床，或 sofa/chair/table/storage/bed；沒填看名稱判斷）、
          原價 original_price、寬 width_cm、深 depth_cm、高 height_cm、評級 grade、編號 product_code

用法：
    python scripts/import_secondhand_csv.py --store "ESG.STYLE" --csv esg.csv
    python scripts/import_secondhand_csv.py --store "ESG.STYLE" --csv esg.csv --dry-run   # 只檢查，不寫檔
    python scripts/import_secondhand_csv.py --store "ESG.STYLE" --remove                  # 刪掉這家的商品
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

from secondhand_store import classify, load_items, normalize_category, save_store

# 標題 → 欄位；Excel 存的 CSV 常帶空白、全形字
COLUMNS = {
    "name": ("name", "名稱", "商品名稱"),
    "price": ("price", "價格", "售價", "二手價"),
    "url": ("url", "網址", "商品網址", "連結"),
    "image_url": ("image_url", "圖片網址", "圖片", "圖片連結"),
    "category": ("category", "分類", "類別"),
    "original_price": ("original_price", "原價"),
    "width_cm": ("width_cm", "寬", "寬度"),
    "depth_cm": ("depth_cm", "深", "深度"),
    "height_cm": ("height_cm", "高", "高度"),
    "grade": ("grade", "評級", "成色"),
    "product_code": ("product_code", "編號", "商品編號"),
}
REQUIRED = ("name", "price", "url", "image_url")


def read_rows(path: Path) -> list[dict]:
    """Excel 存的 CSV 可能是 UTF-8（含 BOM）或 Big5，依序試。"""
    for enc in ("utf-8-sig", "cp950"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    sys.exit(f"讀不了 {path}：請另存成 UTF-8 的 CSV")


def _field(row: dict, key: str) -> str:
    for header, value in row.items():
        if (header or "").strip().lower() in COLUMNS[key]:
            return (value or "").strip()
    return ""


def _number(text: str) -> float | None:
    m = re.search(r"\d[\d,]*(\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def _slug(store: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", store.lower()).strip("-")
    return ascii_part or hashlib.md5(store.encode()).hexdigest()[:6]


def convert(rows: list[dict], store: str) -> tuple[list[dict], list[str]]:
    """CSV 列 → 商品；回傳 (商品, 略過原因)。"""
    items, problems, seen = [], [], set()
    for n, row in enumerate(rows, start=2):   # 第 1 列是標題
        vals = {k: _field(row, k) for k in COLUMNS}
        missing = [k for k in REQUIRED if not vals[k]]
        if missing:
            problems.append(f"第 {n} 列缺少 {', '.join(missing)}")
            continue
        price = _number(vals["price"])
        if not price:
            problems.append(f"第 {n} 列價格看不懂：{vals['price']}")
            continue
        if not vals["image_url"].startswith("http") or not vals["url"].startswith("http"):
            problems.append(f"第 {n} 列網址要以 http 開頭")
            continue
        default = normalize_category(vals["category"])
        if vals["category"] and not default:
            problems.append(f"第 {n} 列分類不認得：{vals['category']}（用 沙發／椅子／桌子／收納／床）")
            continue
        cls = classify(vals["name"], default, keep_default=True)
        if cls is None:
            problems.append(f"第 {n} 列看名稱判斷不出分類，請填分類：{vals['name']}")
            continue
        if vals["url"] in seen:
            problems.append(f"第 {n} 列商品網址重複：{vals['url']}")
            continue
        seen.add(vals["url"])
        code = vals["product_code"] or hashlib.md5(vals["url"].encode()).hexdigest()[:10]
        item = {
            "id": f"{_slug(store)}-{code}",
            "name": vals["name"],
            "category": cls[0],
            "subcategory": cls[1],
            "brand": store,
            "condition": "二手",
            "product_code": code,
            "price": int(price),
            "currency": "TWD",
            "url": vals["url"],
            "image_url": vals["image_url"],
        }
        for key in ("original_price", "width_cm", "depth_cm", "height_cm"):
            v = _number(vals[key])
            if v:
                item[key] = int(v) if key == "original_price" else v
        if vals["grade"]:
            item["grade"] = vals["grade"]
        items.append(item)
    return items, problems


def main():
    ap = argparse.ArgumentParser(description="匯入其他店家的二手家具 CSV")
    ap.add_argument("--store", required=True, help="店家名稱，會顯示在品牌選單與推薦上（例如 ESG.STYLE）")
    ap.add_argument("--csv", type=Path, help="CSV 檔路徑")
    ap.add_argument("--dry-run", action="store_true", help="只檢查 CSV，不寫檔")
    ap.add_argument("--remove", action="store_true", help="刪掉這個店家的所有商品")
    args = ap.parse_args()
    store = args.store.strip()

    existing = sum(1 for it in load_items() if it.get("brand") == store)
    if args.remove:
        merged = save_store(store, [])
        print(f"已刪除 {store} 的 {existing} 件，二手資料剩 {len(merged)} 件")
        return
    if not args.csv:
        ap.error("需要 --csv（或用 --remove 刪除店家）")

    items, problems = convert(read_rows(args.csv), store)
    for p in problems:
        print(f"  略過：{p}")
    by_cat: dict[str, int] = {}
    for it in items:
        by_cat[it["category"]] = by_cat.get(it["category"], 0) + 1
    print(f"[import] {store}：可匯入 {len(items)} 件、略過 {len(problems)} 列  {by_cat}")
    if not items:
        sys.exit("沒有可匯入的商品，資料檔沒有變動")
    if args.dry_run:
        for it in items:
            print(f"  {it['category']:8} {it['subcategory']:18} {it['price']:>7}  {it['name']}")
        return
    merged = save_store(store, items)
    print(f"[import] 完成：{store} {existing} → {len(items)} 件，二手資料共 {len(merged)} 件。重新整理家具查詢頁就看得到")


if __name__ == "__main__":
    main()
