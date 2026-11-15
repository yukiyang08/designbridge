"""二手家具資料檔（secondhand_tw.json + secondhand_embeddings.npz）的共用工具。

多個店家共用同一份資料檔：每次只換掉某一家的商品，其他店家不動；
商品圖向量依圖片網址沿用，只替新商品下載圖片算 CLIP，不用整份重跑。
"""

from __future__ import annotations

import io
import json
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "designbridge" / "furniture_kb"
JSON_PATH = KB_DIR / "secondhand_tw.json"
NPZ_PATH = KB_DIR / "secondhand_embeddings.npz"
DIM = 512
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}

CATEGORIES = ("sofa", "chair", "table", "storage", "bed")

# 名稱 → (category, subcategory)，由上往下第一個符合的為準；跟 furniture_kb._SUBCATEGORY_RULES 同一套細分類
RULES: list[tuple[str, str, str]] = [
    (r"沙發床", "sofa", "sofa-bed"),
    (r"桌椅組|桌椅套組|\d桌\d椅", "table", "table-chair-set"),
    # 「三人座沙發椅」是沙發，先排除多人座才判斷單椅
    (r"(雙人|兩人|二人|三人|四人|L型).*沙發|沙發.*(雙人|三人|L型)", "sofa", "sofa"),
    (r"單人沙發|沙發椅|扶手沙發|主人椅|休閒椅|扶手椅|躺椅|搖椅", "chair", "armchair"),
    (r"沙發", "sofa", "sofa"),
    (r"吧台椅|吧檯椅|高腳椅|高腳餐椅", "chair", "bar-stool"),
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
    (r"吧台桌|吧檯桌", "table", "dining-table"),
    (r"茶几|茶幾|邊桌|邊几|和室桌|矮桌|咖啡桌|桌", "table", "coffee-side-table"),
    (r"床架|床組|床底|雙人床|單人床|床", "bed", "bed-frame"),
    # 燈具（ESG.STYLE 有二手燈具）
    (r"吊燈", "lamp", "pendant-lamp"),
    (r"吸頂燈|天花板燈", "lamp", "ceiling-lamp"),
    (r"落地燈|立燈", "lamp", "floor-lamp"),
    (r"桌燈|檯燈|閱讀燈|台燈", "lamp", "table-lamp"),
    (r"壁燈", "lamp", "wall-lamp"),
    (r"燈", "lamp", "table-lamp"),
]

# 使用者填的中文分類 → category
CATEGORY_ALIASES = {
    "沙發": "sofa", "椅子": "chair", "椅": "chair", "桌子": "table", "桌": "table",
    "收納": "storage", "櫃子": "storage", "櫃": "storage", "床": "bed",
}


def classify(name: str, default: str = "", keep_default: bool = False) -> tuple[str, str] | None:
    """名稱比對細分類；比不到就用 default 大類（細分類留空），都沒有回傳 None。
    keep_default：大類以 default 為準（使用者自己填的分類），名稱只用來找細分類。"""
    clean = re.sub(r"【[^】]*】", "", name)   # 「【二手品】」這類標籤不算
    for pattern, cat, sub in RULES:
        if re.search(pattern, clean) and not (keep_default and default in CATEGORIES and cat != default):
            return cat, sub
    return (default, "") if default in CATEGORIES else None


def normalize_category(value: str) -> str:
    v = (value or "").strip()
    return v.lower() if v.lower() in CATEGORIES else CATEGORY_ALIASES.get(v, "")


def load_items() -> list[dict]:
    try:
        return json.loads(JSON_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def replace_store(brand: str, items: list[dict]) -> list[dict]:
    """把 brand 這家的商品整批換成 items（下架的就會消失），其他店家保留；回傳合併後的清單並存檔。"""
    merged = [it for it in load_items() if it.get("brand") != brand] + items
    JSON_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return merged


def _load_clip():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer("clip-ViT-B-32")


def _download(url: str):
    from PIL import Image
    # urllib 走系統憑證庫：有些店家網站缺中繼憑證，certifi 驗不過
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=20) as r:
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def sync_embeddings(items: list[dict]) -> None:
    """依 items 順序重建向量檔：舊檔裡同一張圖片的向量直接沿用，新圖片才下載算 CLIP。
    下載失敗的補零向量（比對時相似度 0，不會被推薦）。"""
    old: dict[str, np.ndarray] = {}
    try:
        prev_items = json.loads(JSON_PATH.with_suffix(".prev.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        prev_items = None
    if NPZ_PATH.exists():
        matrix = np.load(str(NPZ_PATH))["embeddings"].astype("float32")
        source = prev_items if prev_items is not None else items
        if len(source) == len(matrix):
            old = {it.get("image_url"): matrix[i] for i, it in enumerate(source) if matrix[i].any()}

    model = None
    out = np.zeros((len(items), DIM), dtype="float32")
    fails = 0
    for i, it in enumerate(items):
        url = it.get("image_url") or ""
        if url in old:
            out[i] = old[url]
            continue
        try:
            model = model or _load_clip()
            emb = model.encode(_download(url), convert_to_numpy=True).astype("float32")
            out[i] = emb / (np.linalg.norm(emb) or 1)
            print(f"  [{i + 1}/{len(items)}] 新圖片 OK  {it.get('name', '')[:30]}")
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"  [{i + 1}/{len(items)}] 圖片失敗  {it.get('name', '')[:30]}：{e}", file=sys.stderr)
    np.savez(str(NPZ_PATH), embeddings=out)
    reused = sum(1 for it in items if it.get("image_url") in old)
    print(f"[secondhand] 向量 {len(items)} 筆（沿用 {reused}、新算 {len(items) - reused - fails}、失敗 {fails}）→ {NPZ_PATH.name}")


def save_store(brand: str, items: list[dict]) -> list[dict]:
    """換掉 brand 的商品並同步向量；向量沿用要對照舊的商品順序，所以先留一份舊清單。"""
    prev = JSON_PATH.with_suffix(".prev.json")
    prev.write_text(json.dumps(load_items(), ensure_ascii=False), encoding="utf-8")
    try:
        merged = replace_store(brand, items)
        sync_embeddings(merged)
    finally:
        prev.unlink(missing_ok=True)
    return merged
