#!/usr/bin/env python3
"""爬取「台式復古風」精選文章裡的案例圖片（非 100室內設計）。

來源是編輯已經人工篩過、明確在談磨石子/花磚/鐵窗花/台式復古的文章，
而不是靠分類/屋況標籤去猜，所以圖片精準度比分類爬蟲高很多。

Usage (from project root):
    python -m style_kb.scrapper.scraper_articles
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

sys.stdout.reconfigure(encoding="utf-8")

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "raw" / "taiwan_retro_articles"
REQUEST_TIMEOUT = 15
REQUEST_INTERVAL = 1.0
MIN_FILE_SIZE = 100 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# 精選文章：searchome 官網維護中，改用 housetube.tw 鏡射版；另補幸福空間專欄
# （sh/25483、sh/3905 頁面沒有 hmgcdn 內文圖，已剔除；hhh 專欄只留圖片網址
#   跟導覽推薦區塊區分得開的 5968，避免混入不相關文章的縮圖）
ARTICLES: list[dict] = [
    {"url": "https://home.housetube.tw/sh/17549", "title": "老屋常見的磨石子和水磨石變身時髦建材"},
    {"url": "https://home.housetube.tw/sh/19952", "title": "時髦不老派的復古台式風！5個質感設計提案"},
    {"url": "https://home.housetube.tw/sh/26241", "title": "跨時空混搭拒絕樣板房！台式老靈魂到侘寂摩登"},
    {"url": "https://home.housetube.tw/sh/25156", "title": "五十年老屋重獲新生！都市綠景"},
    {"url": "https://home.housetube.tw/sh/25309", "title": "48年高齡老屋改造計畫"},
    {"url": "https://home.housetube.tw/sh/24606", "title": "北台灣50年老屋翻新，為古董傢俱而築的時光之居"},
    {"url": "https://home.housetube.tw/sh/14830", "title": "低預算高品質重點裝修把中古屋變新品"},
    {"url": "https://home.housetube.tw/sh/26599", "title": "光與木質的療癒改造，小坪數老屋北歐風"},
    {"url": "https://home.housetube.tw/sh/23904", "title": "傳承老台味與人情味！台式復古與現代設計接軌"},
    {"url": "https://home.housetube.tw/sh/24002", "title": "25坪老屋翻新，小夫妻入住與幸福最近的距離"},
    {"url": "https://home.housetube.tw/sh/24860", "title": "侘寂風老屋改造，簡中求美創造多變空間"},
    {"url": "https://home.housetube.tw/sh/25318", "title": "以侘寂詩意構築現代人嚮往的生活居所"},
    {"url": "https://hhh.com.tw/columns/detail/5968", "title": "就愛懷舊滄桑感！4元素醞釀老宅復古風"},
    {"url": "https://home.housetube.tw/sh/16474", "title": "餐飲業屋主的夢幻北歐風紓壓宅！水磨石打造IG網美質感"},
    {"url": "https://home.housetube.tw/sh/26756", "title": "25坪老屋翻新擁抱3房"},
    {"url": "https://home.housetube.tw/sh/21405", "title": "史上最強老屋翻新案例！二次合作重新演繹高齡老屋"},
]

# 每個網域的內文圖片 CDN 規則（排除 logo/icon/導覽/頭像/YouTube 縮圖）
# searchome CDN 網址偶爾會有 doc 前多一個斜線 (.com//article/...)，用 /+ 容錯
DOMAIN_IMG_PATTERNS: dict[str, re.Pattern] = {
    "home.housetube.tw": re.compile(r"https://searchome\.hmgcdn\.com/+article/doc\d+/[\w.]+\.(?:jpg|jpeg|png)"),
    "hhh.com.tw": re.compile(r"https://static\.hhh\.com\.tw/upload/_hcolumn/content_[\w.]+\.(?:jpg|jpeg|png)"),
}


def _create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _collect_images(session: requests.Session, article: dict) -> list[dict]:
    url = article["url"]
    domain = urlparse(url).netloc
    pattern = DOMAIN_IMG_PATTERNS.get(domain)
    if pattern is None:
        print(f"  ⚠️  未知網域，跳過: {domain}")
        return []

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ❌ 請求失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    found = set()
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if pattern.match(src):
            found.add(src)
    # fallback: 部分頁面圖片在 inline script/JSON 裡，直接對全文做 regex
    for m in pattern.finditer(resp.text):
        found.add(m.group(0))

    return [
        {"url": u, "article_title": article["title"], "article_url": url}
        for u in sorted(found)
    ]


def _download_image(session: requests.Session, image_info: dict, output_dir: Path) -> bool:
    url = image_info["url"]
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    output_path = output_dir / filename
    if output_path.exists():
        return True

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        print(f"      ❌ 下載失敗: {e}")
        return False

    if len(resp.content) < MIN_FILE_SIZE:
        return False

    output_path.write_bytes(resp.content)
    meta_path = output_dir / f"{output_path.stem}_meta.json"
    meta_path.write_text(json.dumps(image_info, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    session = _create_session()

    total_images = 0
    total_success = 0

    for article in ARTICLES:
        print(f"\n📄 {article['title']}")
        print(f"   {article['url']}")
        images = _collect_images(session, article)
        print(f"   → 找到 {len(images)} 張內文圖片")

        for img_info in images:
            if _download_image(session, img_info, OUTPUT_DIR):
                total_success += 1
            total_images += 1
            time.sleep(0.3)

        time.sleep(REQUEST_INTERVAL)

    print(f"\n✅ 完成：下載 {total_success}/{total_images} 張")
    print(f"📁 輸出：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
