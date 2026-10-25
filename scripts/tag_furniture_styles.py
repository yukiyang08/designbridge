#!/usr/bin/env python3
"""
用已算好的 CLIP 圖片向量替家具標風格（style_tags），不用重新下載圖片。

每個風格寫一段英文描述轉成 CLIP 文字向量，跟商品圖片向量比相似度，
softmax 後機率 ≥ MIN_PROB 的風格都標上（至少標最像的 1 個）。日式、無印、北歐的描述
彼此很像，日式幾乎贏不了第一名，所以某個風格的相似度在全部商品中特別突出
（z-score ≥ Z_EXTRA）時也補標上；每件最多 MAX_TAGS 個。
「奶油溫馨」「現代輕奢」容易吸到顏色鮮豔的家具：另外放一個不輸出的「鮮豔色」誘餌類別一起比，
並用商品名稱的顏色把明顯是鮮豔色的商品排除在這兩個風格之外。
標籤用 style_kb/styles.py 的 style_id，跟生成流程選的風格同一套。

用法（在 build_ikea_embeddings.py 之後執行；會直接改寫 {brand}_tw.json 的 style_tags）：
    python scripts/tag_furniture_styles.py
    python scripts/tag_furniture_styles.py --brand scanteak
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np

KB_DIR = Path(__file__).parent.parent / "designbridge" / "furniture_kb"
BRANDS = ("ikea", "scanteak", "hola")   # 跟 designbridge/pricing/furniture_kb.py 的 _BRANDS 一致

# style_id → CLIP 文字描述（對應 style_kb/styles.py；「其他」不標）
STYLE_PROMPTS = {
    "modern": "a modern minimalist piece of furniture with clean lines and neutral grey, white or black colors",
    "country": "a cozy piece of furniture in creamy off-white, ivory, beige and oatmeal tones, a soft warm neutral palette",
    "classic": "a simple muji style piece of furniture in light natural wood and plain beige fabric",
    "nordic": "a scandinavian nordic piece of furniture in light wood with a bright natural airy feel",
    "industrial": "an industrial style piece of furniture with black metal frame, dark wood and raw materials",
    "japanese": "a japanese zen style piece of furniture, low profile, natural wood, calm and minimal",
    "american": "a classic american style piece of furniture with traditional details, rich wood and tufted upholstery",
    "luxury": "a glamorous light-luxury piece of furniture with gold or brass details, marble, smoked glass or fine leather, elegant and upscale",
}
# 只參與比較、不會輸出成標籤的誘餌類別：鮮豔色的家具被吸過來，就不會硬塞進奶油溫馨
DECOY_PROMPTS = {
    "_colorful": "a brightly colored piece of furniture in vivid blue, green, orange, yellow, red or pink",
}
# 名稱顏色是鮮豔色、又沒有米白奶油這類中性色字樣時，不標這些以中性色為主的風格
_VIVID_RE = re.compile(r"藍|綠|橘|黃|紅|粉|紫|土耳其|彩色|多彩|花色|撞色")
_NEUTRAL_RE = re.compile(r"米|白|奶|杏|燕麥|象牙|淺灰|原木|自然")
_NEUTRAL_ONLY_STYLES = {"country", "luxury"}
# 輕奢的描述（黃銅、玻璃、大理石）本來就是燈具的材質，跟全部家具比會被燈具佔滿；
# 這類風格不參與第一名的競爭，只在同類別裡特別突出時才標
_PER_CATEGORY_ONLY_STYLES = {"luxury"}
_MIN_GROUP = 10   # 同類別少於這個件數時，改跟全部商品比
MIN_PROB = 0.25
MAX_TAGS = 2
LOGIT_SCALE = 100.0   # CLIP 的 logit scale，讓 softmax 拉開差距
Z_EXTRA = 1.8


def style_text_matrix() -> tuple[list[str], np.ndarray]:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("clip-ViT-B-32")
    prompts = {**STYLE_PROMPTS, **DECOY_PROMPTS}
    ids = list(prompts)
    emb = model.encode([prompts[i] for i in ids], convert_to_numpy=True).astype("float32")
    emb /= np.linalg.norm(emb, axis=1, keepdims=True)
    return ids, emb


def tag_brand(brand: str, ids: list[str], text: np.ndarray) -> None:
    kb_path = KB_DIR / f"{brand}_tw.json"
    emb_path = KB_DIR / f"{brand}_embeddings.npz"
    items = json.loads(kb_path.read_text(encoding="utf-8"))
    images = np.load(str(emb_path))["embeddings"].astype("float32")
    if len(images) != len(items):
        raise SystemExit(f"{brand}: 商品 {len(items)} 件與向量 {len(images)} 筆不符，請先執行 build_ikea_embeddings.py --brand {brand}")

    sims = images @ text.T
    valid = images.any(axis=1)

    def zscore(mask: np.ndarray) -> np.ndarray:
        ref = sims[mask & valid]
        return (sims - ref.mean(axis=0)) / ref.std(axis=0)

    # 同類別內的 z-score：沙發跟沙發比、燈跟燈比，補標的風格才不會集中在某一類
    z_all = zscore(np.ones(len(items), dtype=bool))
    z = z_all.copy()
    cats = np.array([item.get("category") or "" for item in items])
    for cat in set(cats):
        mask = cats == cat
        if (mask & valid).sum() >= _MIN_GROUP:
            z[mask] = zscore(mask)[mask]
    logits = LOGIT_SCALE * sims
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)
    for item, p, zs, img in zip(items, probs, z, images):
        if not img.any():          # 圖片下載失敗的零向量，不標
            item["style_tags"] = []
            continue
        vivid = bool(item.get("color")) and _VIVID_RE.search(item["color"]) and not _NEUTRAL_RE.search(item["color"])
        allowed = [k for k in range(len(ids)) if ids[k] in STYLE_PROMPTS and not (vivid and ids[k] in _NEUTRAL_ONLY_STYLES)]
        order = [k for k in np.argsort(-p) if k in allowed and ids[k] not in _PER_CATEGORY_ONLY_STYLES]
        tags = [ids[k] for k in order if p[k] >= MIN_PROB] or [ids[order[0]]]
        tags += [ids[k] for k in np.argsort(-zs) if k in allowed and zs[k] >= Z_EXTRA and ids[k] not in tags]
        item["style_tags"] = tags[:MAX_TAGS]

    kb_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = Counter(t for i in items for t in i["style_tags"])
    print(f"{brand}: {len(items)} 件  " + "、".join(f"{k} {v}" for k, v in counts.most_common()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", choices=BRANDS, help="只標某個品牌（預設全部）")
    args = parser.parse_args()
    ids, text = style_text_matrix()
    for brand in ([args.brand] if args.brand else BRANDS):
        tag_brand(brand, ids, text)


if __name__ == "__main__":
    main()
