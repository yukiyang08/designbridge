#!/usr/bin/env python3
"""
HOLA 和樂家居家具爬蟲 (www.hola.com.tw)

HOLA 的商品網址沒有分類（/p/商品編號），全站約 5,000 件又混了食品、寢具、雜貨，
所以從家具分類頁（newCategoryData，含分頁）收集商品編號，再逐頁讀商品頁的
holaRevisionProductData 取得名稱、價格、主圖、尺寸與材質。

用法：
    python scripts/scrape_hola.py               # 全部，寫入 hola_tw.json
    python scripts/scrape_hola.py --limit 4 --output tmp.json   # 每個分類只抓 4 件（測試用）
抓完重建向量並標風格：
    python scripts/build_ikea_embeddings.py --brand hola --rebuild
    python scripts/tag_furniture_styles.py --brand hola
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import requests

from furniture_fields import color_of, series_of

BASE = "https://www.hola.com.tw"
BRAND = "HOLA"
OUTPUT_PATH = Path(__file__).parent.parent / "designbridge" / "furniture_kb" / "hola_tw.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}
_REQUEST_GAP = 0.5

# 分類代碼 → category；燈具混在「裝飾品｜桌燈｜造型蠟燭」裡，只收名稱有「燈」的
CATEGORIES: dict[str, str] = {
    "EC_30000026": "sofa",      # 沙發
    "EC_30000030": "chair",     # 椅子｜單椅｜凳子
    "EC_30000027": "table",     # 桌子｜餐桌｜邊几
    "EC_30000028": "storage",   # 櫃子｜層架｜穿衣鏡
    "EC_30122088": "bed",       # 床架
    "EC_30000017": "rug",       # 地毯
    "EC_30000025": "lamp",      # 裝飾品｜桌燈｜造型蠟燭
}

_EXCLUDE_RE = re.compile(r"(鏡|沙發套|椅套|坐墊|座墊|椅墊|抱枕|保護套|清潔|蠟燭|燈泡|燈芯絨|鑰匙圈|衣帽架)")
# 模組沙發單獨販售的零件（扶手、單人座、轉角），跟 IKEA 一樣不收
_MODULE_PART_RE = re.compile(r"[左右]?扶手|單人座|轉角|中間座")

# category → [(名稱關鍵字, category, subcategory)]，由上往下第一個符合的為準
_RULES: dict[str, list[tuple[str, str, str]]] = {
    "sofa": [(r"腳凳|椅凳", "chair", "footstool"), (r"單人沙發|1人", "chair", "armchair"),
             (r"沙發床", "sofa", "sofa-bed"), (r".", "sofa", "sofa")],
    "chair": [(r"吧台椅|吧檯椅|高腳", "chair", "bar-stool"), (r"辦公椅|書桌椅|電腦椅", "chair", "desk-chair"),
              (r"腳凳|椅凳|凳", "chair", "stool"), (r"長椅|長凳", "chair", "bench"),
              (r"餐椅", "chair", "dining-chair"), (r"單椅|休閒椅|扶手椅|躺椅|搖椅", "chair", "armchair"),
              (r".", "chair", "dining-chair")],
    "table": [(r"餐桌", "table", "dining-table"), (r"書桌|工作桌|電腦桌", "table", "desk"),
              (r".", "table", "coffee-side-table")],   # 其餘多為邊几、茶几、咖啡桌
    "storage": [(r"電視櫃", "storage", "tv-bench"), (r"書櫃|書架", "storage", "bookcase"),
                (r"床頭櫃|床邊櫃", "storage", "bedside-table"), (r"斗櫃|抽屜櫃", "storage", "chest-of-drawers"),
                (r"衣櫃|衣櫥", "storage", "wardrobe"), (r"層架|置物架|展示架|格櫃", "storage", "open-storage"),
                (r".", "storage", "sideboard")],
    "bed": [(r".", "bed", "bed-frame")],
    "rug": [(r"走道|長毯", "rug", "runner"), (r".", "rug", "rug")],
    "lamp": [(r"落地燈|立燈", "lamp", "floor-lamp"), (r"吊燈", "lamp", "pendant-lamp"), (r"壁燈", "lamp", "wall-lamp"),
             (r"燈", "lamp", "table-lamp")],
}


def _embedded_json(page: str, marker: str) -> Optional[dict]:
    """頁面裡用 template literal 包住的 JSON（多一層 JS 字串跳脫，要先解一層）。"""
    i = page.find(marker)
    if i < 0:
        return None
    start = page.find("`", i)
    end = page.find("`", start + 1)
    if start < 0 or end < 0:
        return None
    text = page[start + 1:end].encode().decode("unicode_escape").encode("latin1").decode("utf-8", "ignore")
    data = json.loads(text, strict=False)
    return data.get("data", data)


def _money(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def parse_dims(text: str) -> dict[str, float]:
    """「長80，寬57，高92公分」「W120xD60xH75cm」「120*60*75」→ {寬度, 深度, 高度}。
    長＝沿牆方向的寬、寬＝深（HOLA 的家具都是這樣標）；只標直徑的燈具寬深相同。"""
    out: dict[str, float] = {}
    nums = {k: float(v) for k, v in re.findall(r"(長|寬|高|深|直徑|徑|W|D|H)\s*[:：]?\s*(\d+(?:\.\d+)?)", text, re.I)}
    if nums:
        width = nums.get("長") or nums.get("W") or nums.get("w")
        depth = nums.get("深") or nums.get("D") or nums.get("d") or (nums.get("寬") if width else None)
        if not width:
            width = nums.get("寬")
        dia = nums.get("直徑") or nums.get("徑")
        if dia and not width:
            width = depth = dia
        height = nums.get("高") or nums.get("H") or nums.get("h")
        for key, val in (("寬度", width), ("深度", depth), ("高度", height)):
            if val:
                out[key] = val
        return out
    triple = re.search(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)", text)
    if triple:
        out = dict(zip(("寬度", "深度", "高度"), map(float, triple.groups())))
    return out


def list_skus(limit: int = 0) -> list[tuple[str, str]]:
    """各家具分類頁逐頁收集 (sku, category)，同一件出現在多個分類只留第一個；limit 為每個分類上限。"""
    seen: dict[str, str] = {}
    for code, category in CATEGORIES.items():
        page = 0
        count = 0
        while True:
            r = requests.get(f"{BASE}/c/{code}", params={"page": page} if page else None, headers=HEADERS, timeout=40)
            data = _embedded_json(r.text, "newCategoryData = (") or {}
            for p in data.get("products") or []:
                sku = p.get("sku")
                if limit and count >= limit:
                    break
                if sku and sku not in seen and (category != "lamp" or re.search(r"燈(?!芯)", p.get("name") or "")):
                    seen[sku] = category
                    count += 1
            pages = (data.get("pagination") or {}).get("numberOfPages") or 1
            page += 1
            time.sleep(_REQUEST_GAP)
            if page >= pages or (limit and count >= limit):
                break
    return list(seen.items())


def fetch_product(sku: str) -> Optional[dict]:
    try:
        r = requests.get(f"{BASE}/p/{sku}", headers=HEADERS, timeout=40)
        return _embedded_json(r.text, "holaRevisionProductData = ") if r.ok else None
    except Exception:
        return None


def build_item(sku: str, category: str, d: dict) -> Optional[dict]:
    name = (d.get("name") or "").strip()
    if not name or _EXCLUDE_RE.search(name):
        return None
    if "模組" in name and _MODULE_PART_RE.search(name):
        return None
    cls = next(((c, s) for pat, c, s in _RULES[category] if re.search(pat, name)), None)
    if not cls:
        return None
    specs = {(x.get("title") or "").strip("：: "): (x.get("dsr") or "").strip()
             for x in ((d.get("specificationDescription") or {}).get("add") or [])}
    dims = parse_dims(specs.get("尺寸", ""))
    price = _money(d.get("secondPrice")) or _money(d.get("firstPrice"))   # 有優惠價用優惠價
    image = d.get("defaultImage") or ((d.get("images") or [""])[0])
    if not price or not image:
        return None
    return {
        "name": name,
        "category": cls[0],
        "subcategory": cls[1],
        "brand": BRAND,
        "series": series_of(name),
        "product_code": sku,
        "color": color_of(name),
        "price": price,
        "currency": "TWD",
        "width_cm": dims.get("寬度"),
        "depth_cm": dims.get("深度"),
        "height_cm": dims.get("高度"),
        "dims": dims,
        "material": specs.get("材質") or None,
        "url": f"{BASE}/p/{sku}",
        "image_url": image,
        "style_tags": [],   # 由 scripts/tag_furniture_styles.py 用 CLIP 向量標
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HOLA 和樂家居家具爬蟲")
    parser.add_argument("--limit", type=int, default=0, help="每個分類最多抓幾件（0 = 全部）")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    targets = list_skus(args.limit)
    print(f"分類頁收集到 {len(targets)} 件商品")
    items, skipped = [], []
    for i, (sku, category) in enumerate(targets, 1):
        d = fetch_product(sku)
        item = build_item(sku, category, d) if d else None
        if item:
            items.append(item)
        else:
            skipped.append((d or {}).get("name") or sku)
        if i % 50 == 0:
            print(f"  進度 {i}/{len(targets)}")
        time.sleep(_REQUEST_GAP)

    args.output.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成！共 {len(items)} 件，已存到：{args.output}")
    for cat, cnt in sorted(Counter(i["category"] for i in items).items()):
        subs = Counter(i["subcategory"] for i in items if i["category"] == cat)
        print(f"  {cat}: {cnt} 件  " + "、".join(f"{s} {n}" for s, n in subs.most_common()))
    print(f"有尺寸 {sum(1 for i in items if i['width_cm'])} 件；略過 {len(skipped)} 件：" + "、".join(skipped))


if __name__ == "__main__":
    main()
