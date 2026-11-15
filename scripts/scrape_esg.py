#!/usr/bin/env python3
"""
ESG.STYLE 循環寄售平台（shop.esg.style/ESG_Product）二手家具爬蟲

平台共約 20 頁、每頁 6 件（nopCommerce 架構），以 SSR 渲染，
直接 GET 每一頁 HTML 後解析商品清單；再進商品詳情頁取原價與商品編號。
抓完後整批換掉 secondhand_tw.json 裡屬於「ESG.STYLE」的商品，向量一起更新。

用法：
    python scripts/scrape_esg.py               # 全部抓，寫入 secondhand_tw.json
    python scripts/scrape_esg.py --dry-run     # 只列出抓到的商品，不寫檔
    python scripts/scrape_esg.py --limit 3     # 只抓前 3 頁（測試用）

抓完後家具查詢頁重新整理即可看到「ESG.STYLE · 二手」品牌；
推薦系統（quotation.py + secondhand.py）會自動在估價時附上。
"""

from __future__ import annotations

import argparse
import html as htmllib
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from secondhand_store import classify, save_store

BASE_URL = "https://shop.esg.style"
LISTING_PATH = "/ESG_Product"
BRAND = "ESG.STYLE"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}
_REQUEST_GAP = 0.5   # 每次請求後等待秒數（禮貌性延遲）


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="ignore")


# ── 清單頁解析 ─────────────────────────────────────────────────────────────────

def _total_pages(html: str) -> int:
    """從分頁 HTML 讀出最後一頁的頁碼；解析失敗回傳 1（只抓第一頁）。"""
    # nopCommerce 分頁：<li class=last-page><a href="...pagenumber=N">尾頁</a>
    m = re.search(r'class=last-page><a href="[^"]+pagenumber=(\d+)"', html)
    if m:
        return int(m.group(1))
    # 備援：直接找最大 pagenumber
    nums = re.findall(r'pagenumber=(\d+)', html)
    return max((int(n) for n in nums), default=1)


def _parse_listing_page(html: str) -> list[dict]:
    """
    解析清單頁，回傳 list[dict]，每筆含：
      name, slug (相對路徑), image_url, price, original_price

    nopCommerce SSR 輸出的 HTML attribute 不帶引號，結構如下（已確認）：
      href=/<slug> title="顯示明細 <name>"> <img src=<img_url> ...>
      <span class=actual-price>$<price></span>
      <span class=old-price>$<orig></span>  ← 若有折扣
    """
    # 步驟 1：找所有商品的 (slug, name, image_url)
    slug_re = re.compile(
        r'href=(/[^\s>]+)\s+title="(?:顯示明細\s+)?([^"]+)">'
        r'[^<]*<img[^>]+src=(https://shop\.esg\.style/images/thumbs/[^\s>"]+)',
        re.S,
    )
    matches = slug_re.findall(html)

    # 步驟 2：依序找所有 (actual_price, old_price) 組合
    # nopCommerce HTML（實際順序）：
    #   <span class="price old-price">$4,500.00</span>
    #   <span class="price actual-price">$2,750.00</span>
    # 無折扣時只有 actual-price。
    prices: list[tuple[int, int]] = []
    for pm in re.finditer(
        r'<div[^>]*class=prices>'
        r'(?:<span\s+class="price\s+old-price">\$([\d,]+\.?\d*)</span>\s*)?'
        r'<span\s+class="price\s+actual-price">\$([\d,]+\.?\d*)</span>',
        html, re.S,
    ):
        old_str = pm.group(1)
        actual_str = pm.group(2)
        actual = int(float(actual_str.replace(",", ""))) if actual_str else 0
        old = int(float(old_str.replace(",", ""))) if old_str else 0
        prices.append((actual, old))

    # 步驟 3：合併（slug/name/img 與 price 一對一對應清單商品）
    items = []
    price_idx = 0
    for slug, name, img_url in matches:
        name = htmllib.unescape(name).strip()
        if "已預訂" in name:
            # 已預訂的商品仍佔一個 actual-price，要消耗掉索引
            price_idx += 1
            continue
        actual, old = prices[price_idx] if price_idx < len(prices) else (0, 0)
        price_idx += 1
        items.append({
            "slug": slug,
            "name": name,
            "image_url": img_url,
            "price": actual,
            "original_price": old if old > actual else 0,
        })
    return items


# ── 詳情頁解析 ─────────────────────────────────────────────────────────────────

def _parse_detail(html: str) -> dict:
    """
    商品詳情頁：取商品編號（nopCommerce 後台 ID）與尺寸。
    欄位不保證一定有，失敗就留空。
    """
    out: dict = {}

    # 商品品牌＆編號（nopCommerce 自訂屬性），格式：0000000082
    code_m = re.search(r'商品品牌＆編號:[^<]*</\w+>\s*<[^>]+>([^<]+)<', html)
    if not code_m:
        # 備援：直接找 7 位以上數字串（ESG 商品編號格式）
        code_m = re.search(r'\b(0{3,}\d{4,})\b', html)
    if code_m:
        out["product_code"] = code_m.group(1).strip()

    # 尺寸從名稱或頁面描述抓（格式：寬x深 或 寬x深x高，cm）
    # 詳情頁一樣，依清單頁已取得的名稱解析即可，這裡只補 fallback
    return out


# ── 尺寸解析 ───────────────────────────────────────────────────────────────────

_DIM_RE = re.compile(r'(\d+)\s*[xX×]\s*(\d+)(?:\s*[xX×]\s*(\d+))?')


def _parse_dims(name: str) -> dict:
    """
    從商品名稱提取尺寸（cm）。
    - 兩個數字：寬x高（桌/床）或 寬x深，採用「寬x深x高」順序
    - 三個數字：寬x深x高
    回傳含 width_cm / depth_cm / height_cm 的 dict（有多少填多少）。
    """
    m = _DIM_RE.search(name)
    if not m:
        return {}
    a, b, c = m.group(1), m.group(2), m.group(3)
    out = {"width_cm": float(a)}
    if c:
        out["depth_cm"] = float(b)
        out["height_cm"] = float(c)
    else:
        # 兩個數字：慣例 寬x高（桌面、床）→ 存成 width x height
        out["height_cm"] = float(b)
    return out


# ── 主爬蟲 ────────────────────────────────────────────────────────────────────

# 以下商品在清單頁就能認出是不適合推薦的品項（配件、耗材、小物）
_SKIP_RE = re.compile(
    r'(托盤|托架|飾板|燈泡|抱枕套|枕套|床單|被套|毛巾|地墊|門墊|'
    r'廚具|流理台|瓦斯爐|電磁爐|電鍋|烤箱|微波|冰箱|洗衣機|冷氣|'
    r'電視機(?!櫃)|手機|電腦螢幕|印表機|'
    r'零件|配件|替換|框架|門板|層板|抽屜面板)'
)


def scrape(limit_pages: int = 0) -> list[dict]:
    """
    爬取所有（或前 limit_pages 頁）清單頁，
    回傳符合格式的二手家具商品清單。
    """
    # 先拿第一頁，讀總頁數
    first_page = _get(f"{BASE_URL}{LISTING_PATH}")
    time.sleep(_REQUEST_GAP)
    total = _total_pages(first_page)
    print(f"[esg] 共 {total} 頁")

    if limit_pages:
        total = min(total, limit_pages)

    pages_html = [first_page]
    for page_num in range(2, total + 1):
        url = f"{BASE_URL}{LISTING_PATH}?pagenumber={page_num}"
        pages_html.append(_get(url))
        time.sleep(_REQUEST_GAP)
        if page_num % 5 == 0:
            print(f"[esg]   已抓 {page_num}/{total} 頁")

    # 解析所有清單頁
    raw_items: list[dict] = []
    seen_slugs: set[str] = set()
    for html in pages_html:
        for it in _parse_listing_page(html):
            if it["slug"] in seen_slugs:
                continue
            if _SKIP_RE.search(it["name"]):
                print(f"  略過（非家具）：{it['name'][:50]}")
                continue
            seen_slugs.add(it["slug"])
            raw_items.append(it)

    print(f"[esg] 清單頁解析：{len(raw_items)} 件可用商品")

    # 進詳情頁補商品編號（慢，可略）
    products: list[dict] = []
    skipped_classify = 0
    for i, it in enumerate(raw_items, 1):
        name = it["name"]
        cls = classify(name, default="")
        if cls is None:
            print(f"  略過（分類不明）：{name[:50]}")
            skipped_classify += 1
            continue

        # 詳情頁：取商品編號
        detail_url = f"{BASE_URL}{it['slug']}"
        try:
            detail_html = _get(detail_url)
            detail = _parse_detail(detail_html)
            time.sleep(_REQUEST_GAP)
        except OSError as e:
            print(f"  詳情頁讀取失敗 {it['slug']}：{e}", file=sys.stderr)
            detail = {}

        product_code = detail.get("product_code") or re.search(r'\d{7,}', it["slug"])
        if product_code is None:
            # 以 slug 的 hash 為 id
            import hashlib
            product_code = hashlib.md5(it["slug"].encode()).hexdigest()[:10]
        elif hasattr(product_code, "group"):
            product_code = product_code.group()

        item_id = f"esg-{product_code}"
        entry: dict = {
            "id": item_id,
            "name": name,
            "category": cls[0],
            "subcategory": cls[1],
            "brand": BRAND,
            "condition": "二手",
            "product_code": str(product_code),
            "price": it["price"],
            "currency": "TWD",
            "url": detail_url,
            "image_url": it["image_url"],
        }
        if it["original_price"]:
            entry["original_price"] = it["original_price"]
        entry.update(_parse_dims(name))

        products.append(entry)
        if i % 20 == 0:
            print(f"[esg]   已處理 {i}/{len(raw_items)} 件")

    print(f"[esg] 完成：{len(products)} 件（略過分類不明 {skipped_classify} 件）")
    return products


# ── 入口 ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="爬取 ESG.STYLE 二手家具")
    ap.add_argument("--dry-run", action="store_true", help="只列出商品，不寫檔")
    ap.add_argument("--limit", type=int, default=0, metavar="N", help="只抓前 N 頁（測試用）")
    args = ap.parse_args()

    products = scrape(limit_pages=args.limit)

    # 依分類統計
    by_cat: dict[str, int] = {}
    for p in products:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    print(f"[esg] 分類統計：{by_cat}")

    if args.dry_run:
        for p in products:
            print(
                f"  {p['category']:8} {p['subcategory']:18} "
                f"{p['price']:>7}  {p['name'][:45]}"
            )
        print("（dry-run：未寫入資料檔）")
        return

    merged = save_store(BRAND, products)
    print(
        f"[esg] 寫入完成：ESG.STYLE {len(products)} 件，"
        f"二手資料共 {len(merged)} 件。\n"
        f"      重新整理家具查詢頁即可看到「ESG.STYLE · 二手」品牌。"
    )


if __name__ == "__main__":
    main()
