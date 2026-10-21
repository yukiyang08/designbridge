#!/usr/bin/env python3
"""
估價相似度門檻評估：對生成圖跑家具偵測，門檻設 0 輸出每件家具 top-3 候選，人工標註後計算各門檻的覆蓋率與命中率。

用法：
    # 1. 抽取候選（預設讀 artifacts/render 中的成品圖）
    python scripts/eval_quotation_threshold.py extract --limit 15
    python scripts/eval_quotation_threshold.py extract --images a.png b.png artifacts/render

    # 2. 開 review.html 對照裁切圖與商品圖，在 candidates.csv 的 hit_1~hit_3 填 1（命中）或 0

    # 3. 計分
    python scripts/eval_quotation_threshold.py score
    python scripts/eval_quotation_threshold.py score --thresholds 0.6 0.7 0.75 0.8
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
DEFAULT_OUT = ROOT / "artifacts" / "eval_quotation"
TOP_K = 3
# 只收 uuid.png / uuid_hash.png 成品圖，排除 debug、mask、測試圖
_RENDER_NAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(_[0-9a-f]{8})?\.png$")


def _collect_images(paths: list[str]) -> list[Path]:
    images: list[Path] = []
    for p in map(Path, paths):
        if p.is_dir():
            images += sorted(f for f in p.iterdir() if _RENDER_NAME.match(f.name))
        elif p.is_file():
            images.append(p)
        else:
            print(f"⚠️  找不到：{p}")
    return images


def _fieldnames() -> list[str]:
    cols = ["image", "item_id", "detected_name", "category", "crop"]
    for k in range(1, TOP_K + 1):
        cols += [f"name_{k}", f"sim_{k}", f"price_{k}", f"url_{k}", f"image_url_{k}", f"hit_{k}"]
    return cols


def extract(args) -> None:
    from PIL import Image

    from designbridge.pricing.furniture_kb import find_top_k_by_embedding
    from designbridge.pricing.quotation import crop_image_by_bbox, detect_furniture_gemini, get_clip_embedding

    images = _collect_images(args.images)[: args.limit or None]
    if not images:
        print("❌ 沒有可用的圖片")
        return

    out = Path(args.out)
    crop_dir = out / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for n, img_path in enumerate(images, 1):
        print(f"[{n}/{len(images)}] {img_path.name}")
        detected = detect_furniture_gemini(str(img_path))
        if not detected:
            print("   偵測不到家具，略過")
            continue
        img = Image.open(img_path).convert("RGB")
        for i, raw in enumerate(detected):
            bbox = raw.get("bbox") or []
            # LLM 偶爾回傳上下顛倒的 bbox，比照正式流程略過該件
            try:
                crop = crop_image_by_bbox(img, bbox) if len(bbox) == 4 else None
            except ValueError:
                crop = None
            if crop is None:
                continue
            # 與正式流程一致：shelf 併入 storage
            category = "storage" if raw.get("category") == "shelf" else (raw.get("category") or "")
            item_id = f"{img_path.stem}_{i}"
            crop_path = crop_dir / f"{item_id}.jpg"
            crop.save(crop_path, quality=90)

            # 門檻設 0 才拿得到低分候選，否則算不出低門檻的數字
            hits = find_top_k_by_embedding(get_clip_embedding(crop), category=category, top_k=TOP_K, min_similarity=0.0)
            row = {
                "image": str(img_path),
                "item_id": item_id,
                "detected_name": raw.get("name_zh") or raw.get("name_en") or "",
                "category": category,
                "crop": crop_path.relative_to(out).as_posix(),
            }
            for k, h in enumerate(hits[:TOP_K], 1):
                row.update({
                    f"name_{k}": h.get("name") or "",
                    f"sim_{k}": round(float(h.get("similarity") or 0), 4),
                    f"price_{k}": int(h.get("price") or 0),
                    f"url_{k}": h.get("url") or "",
                    f"image_url_{k}": h.get("image_url") or "",
                })
            rows.append(row)
            print(f"   {row['detected_name']}（{category}）→ " + ", ".join(str(row.get(f"sim_{k}", "-")) for k in range(1, TOP_K + 1)))

    csv_path = out / "candidates.csv"
    if csv_path.exists() and not args.overwrite:
        csv_path = out / "candidates_new.csv"
        print(f"⚠️  candidates.csv 已存在（可能已標註），改寫到 {csv_path.name}；要覆蓋請加 --overwrite")
    # utf-8-sig 讓 Excel 直接開不會亂碼
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=_fieldnames())
        w.writeheader()
        w.writerows(rows)
    _write_review_html(rows, out / "review.html")
    print(f"\n✅ {len(rows)} 件家具 → {csv_path}")
    print(f"   對照頁面：{out / 'review.html'}")


def _write_review_html(rows: list[dict], path: Path) -> None:
    e = lambda v: html.escape(str(v or ""))
    trs = []
    for r in rows:
        cands = "".join(
            f'<td><img src="{e(r.get(f"image_url_{k}"))}"><br>{e(r.get(f"name_{k}"))}<br>'
            f'<b>{e(r.get(f"sim_{k}"))}</b> · NT${e(r.get(f"price_{k}"))}</td>'
            for k in range(1, TOP_K + 1)
        )
        trs.append(
            f'<tr><td>{e(r["item_id"])}<br>{e(r["detected_name"])}<br>{e(r["category"])}</td>'
            f'<td><img src="{e(r["crop"])}"></td>{cands}</tr>'
        )
    head = "".join(f"<th>候選 {k}</th>" for k in range(1, TOP_K + 1))
    path.write_text(
        '<!doctype html><meta charset="utf-8"><title>估價候選對照</title>'
        "<style>body{font-family:sans-serif}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:6px;"
        "vertical-align:top;font-size:13px;max-width:200px}img{max-width:180px;max-height:180px}</style>"
        f"<table><tr><th>家具</th><th>裁切圖</th>{head}</tr>{''.join(trs)}</table>",
        encoding="utf-8",
    )


def score(args) -> None:
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    def num(v: str) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    items = []
    for r in rows:
        sims = [num(r.get(f"sim_{k}")) for k in range(1, TOP_K + 1)]
        hits = [num(r.get(f"hit_{k}")) for k in range(1, TOP_K + 1)]
        # 有候選的名次都要標註，否則不計入
        if any(s is not None and h is None for s, h in zip(sims, hits)):
            continue
        items.append([(s, h == 1) for s, h in zip(sims, hits) if s is not None])

    skipped = len(rows) - len(items)
    # 商品庫沒有對應類別（窗簾、other）的家具任何門檻都不會有候選，不計入覆蓋率分母
    no_kb = sum(1 for c in items if not c)
    items = [c for c in items if c]
    if not items:
        print("❌ 沒有已標註完成的資料（hit_1~hit_3 請填 1 或 0）")
        return
    print(f"已標註 {len(items)} 件" + (f"（{skipped} 件未標註完成，未計入）" if skipped else ""))
    if no_kb:
        print(f"另有 {no_kb} 件商品庫無對應類別，未計入")
    print(f"\n{'門檻':>6} | {'覆蓋率':>8} | {'Top-1 命中率':>12} | {'Top-3 命中率':>12}")
    print("-" * 50)
    for t in args.thresholds:
        # 覆蓋：至少 1 個候選達門檻；命中率的分母是有覆蓋的件數（使用者實際看到推薦的部分）
        covered = [c for c in items if c and c[0][0] >= t]
        top1 = sum(c[0][1] for c in covered)
        top3 = sum(any(h for s, h in c if s >= t) for c in covered)
        cov = len(covered) / len(items)
        rate = lambda x: f"{x / len(covered):.1%} ({x}/{len(covered)})" if covered else "-"
        print(f"{t:>6.2f} | {cov:>7.1%} | {rate(top1):>12} | {rate(top3):>12}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="跑偵測並輸出候選表")
    pe.add_argument("--images", nargs="+", default=[str(ROOT / "artifacts" / "render")], help="圖片檔或資料夾")
    pe.add_argument("--limit", type=int, default=0, help="最多處理幾張圖（0 = 全部）")
    pe.add_argument("--out", default=str(DEFAULT_OUT))
    pe.add_argument("--overwrite", action="store_true", help="覆蓋既有的 candidates.csv")
    pe.set_defaults(func=extract)

    ps = sub.add_parser("score", help="讀標註後的候選表計算各門檻結果")
    ps.add_argument("--csv", default=str(DEFAULT_OUT / "candidates.csv"))
    ps.add_argument("--thresholds", nargs="+", type=float, default=[0.65, 0.70, 0.75, 0.80, 0.85])
    ps.set_defaults(func=score)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
