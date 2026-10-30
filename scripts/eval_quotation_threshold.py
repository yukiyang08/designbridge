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

    # 沿用同一批裁切圖重新比對；--config 比較不同推薦設定，compare 算不需人工標註的指標
    python scripts/eval_quotation_threshold.py rematch --config base --out-csv cfg_base.csv
    python scripts/eval_quotation_threshold.py rematch --config style --style-bonus 0.02 --out-csv cfg_style.csv
    python scripts/eval_quotation_threshold.py compare artifacts/eval_quotation/cfg_base.csv artifacts/eval_quotation/cfg_style.csv

    # 人工標註：產生盲標網頁（瀏覽器直接開），標完匯出 labels.csv 再計分
    python scripts/eval_quotation_threshold.py labelpage --csv artifacts/eval_quotation/cfg_abc.csv
    python scripts/eval_quotation_threshold.py score --csv artifacts/eval_quotation/cfg_abc.csv --labels labels.csv
    # 新候選先用 Gemini 依同一套規則暫標（auto_1~auto_3 記錄哪些是自動標的），再人工抽查
    python scripts/eval_quotation_threshold.py autolabel --csv artifacts/eval_quotation/candidates_v2.csv
    python scripts/eval_quotation_threshold.py score --csv artifacts/eval_quotation/candidates_v2.csv
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


def _fieldnames(auto: bool = False) -> list[str]:
    cols = ["image", "item_id", "detected_name", "category", "crop"]
    for k in range(1, TOP_K + 1):
        cols += [f"name_{k}", f"sim_{k}", f"price_{k}", f"url_{k}", f"image_url_{k}", f"hit_{k}"]
        if auto:
            cols += [f"brand_{k}", f"auto_{k}"]
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


CONFIGS = ("base", "abc", "style")   # 原本的大類別比對 / 加細分類篩選、同系列去重、排除桌椅組 / 再加風格加分


def _image_styles(image_paths: set[str]) -> dict[str, tuple[str, str]]:
    """測試圖的渲染風格：歷史紀錄有記錄就用，沒有（較早生成的圖）就用 CLIP 從整張圖推斷。
    回傳 {圖片路徑: (style_id, 來源)}。"""
    import json

    import numpy as np
    from PIL import Image

    from designbridge.pricing.quotation import get_clip_embedding

    sys.path.insert(0, str(ROOT / "scripts"))
    from tag_furniture_styles import STYLE_PROMPTS, style_text_matrix

    history = json.loads((ROOT / "artifacts" / "history.json").read_text(encoding="utf-8"))
    recorded = {Path(r.get("generated_image_path") or "").name: (r.get("style_params") or {}).get("style_profile_id")
                for r in history}
    ids, text = style_text_matrix()
    out = {}
    for path in image_paths:
        sid = recorded.get(Path(path).name)
        if sid in STYLE_PROMPTS:
            out[path] = (sid, "history")
            continue
        emb = np.array(get_clip_embedding(Image.open(path).convert("RGB")), dtype="float32")
        scores = text @ (emb / np.linalg.norm(emb))
        best = max((k for k in range(len(ids)) if ids[k] in STYLE_PROMPTS), key=lambda k: scores[k])
        out[path] = (ids[best], "clip")
    return out


def rematch(args) -> None:
    """沿用同一批裁切圖與類別，用目前的本地商品庫重新比對 top-3（hit 欄位留空待人工標註）。

    --config base：只依大類別取相似度最高的 3 件（原本的做法）
    --config abc：加上細分類篩選、同系列去重、排除桌椅組
    --config style：abc 再加渲染圖風格加分
    """
    from PIL import Image

    from designbridge.pricing.furniture_kb import _find_top_k_local, _load_local_kb, recommend_products
    from designbridge.pricing.quotation import get_clip_embedding

    out = Path(args.out)
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        src_rows = list(csv.DictReader(f))
    styles = _image_styles({r["image"] for r in src_rows}) if args.config == "style" else {}
    local = {item.get("url"): item for item in _load_local_kb()}

    rows = []
    for r in src_rows:
        row = {k: r[k] for k in ("image", "item_id", "detected_name", "category", "crop")}
        style_id, style_src = styles.get(r["image"], ("", ""))
        row["image_style"] = f"{style_id}({style_src})" if style_id else ""
        crop_path = out / r["crop"]
        if crop_path.exists():
            emb = get_clip_embedding(Image.open(crop_path).convert("RGB"))
            # 用本地向量搜尋：Supabase 要重新上傳才會跟本地商品庫一致；門檻 0 才算得出低門檻的數字
            if args.config == "base":
                hits = _find_top_k_local(emb, r["category"], TOP_K, 0.0)
            else:
                hits = recommend_products(emb, r["category"], detected_name=r["detected_name"], style_id=style_id,
                                          top_k=TOP_K, min_similarity=0.0, style_bonus=args.style_bonus,
                                          search=_find_top_k_local)
            for k, h in enumerate(hits[:TOP_K], 1):
                info = {**local.get(h.get("url"), {}), **h}
                row.update({
                    f"name_{k}": h.get("name") or "", f"sim_{k}": round(float(h.get("similarity") or 0), 4),
                    f"price_{k}": int(h.get("price") or 0), f"url_{k}": h.get("url") or "",
                    f"image_url_{k}": h.get("image_url") or "", f"hit_{k}": "", f"brand_{k}": h.get("brand") or "",
                    f"subcat_{k}": info.get("subcategory") or "", f"style_{k}": ",".join(info.get("style_tags") or []),
                })
        rows.append(row)

    extra = [c for k in range(1, TOP_K + 1) for c in (f"subcat_{k}", f"style_{k}")] + ["image_style"]
    csv_path = out / args.out_csv
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=_fieldnames(auto=True) + extra)
        w.writeheader()
        w.writerows(rows)
    print(f"✅ {len(rows)} 件家具重新比對（{args.config}）→ {csv_path}")


def compare(args) -> None:
    """不需人工標註的指標：覆蓋率、細分類吻合率、3 個推薦的款式數、風格一致率。"""
    from designbridge.pricing.furniture_kb import subcategories_for

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    print(f"門檻 {args.threshold}")
    print(f"{'設定':<28} | 覆蓋率 | 第1名細分類吻合 | 前3名有吻合 | 平均款式數 | 第1名風格一致")
    for path in args.csvs:
        with open(path, newline="", encoding="utf-8-sig") as f:
            rows = [r for r in csv.DictReader(f) if num(r.get("sim_1")) is not None]
        def shown(r):
            return [k for k in range(1, TOP_K + 1) if num(r.get(f"sim_{k}")) is not None and num(r[f"sim_{k}"]) >= args.threshold]
        covered = [r for r in rows if shown(r)]
        with_sub = [r for r in covered if subcategories_for(r["category"], r["detected_name"])]
        top1_sub = sum(r.get(f"subcat_{shown(r)[0]}") in subcategories_for(r["category"], r["detected_name"]) for r in with_sub)
        any_sub = sum(any(r.get(f"subcat_{k}") in subcategories_for(r["category"], r["detected_name"]) for k in shown(r))
                      for r in with_sub)
        models = [len({(r.get(f"brand_{k}"), r.get(f"name_{k}", "").split(" ")[0]) for k in range(1, TOP_K + 1)
                       if r.get(f"name_{k}")}) for r in covered]
        styled = [r for r in covered if r.get("image_style")]
        style_hit = sum(r["image_style"].split("(")[0] in (r.get(f"style_{shown(r)[0]}") or "").split(",") for r in styled)
        pct = lambda a, b: f"{a / b:.1%} ({a}/{b})" if b else "-"
        print(f"{Path(path).stem:<28} | {len(covered) / len(rows):.1%} | {pct(top1_sub, len(with_sub)):>14} | "
              f"{pct(any_sub, len(with_sub)):>12} | {sum(models) / max(1, len(models)):>9.2f} | {pct(style_hit, len(styled))}")


def autolabel(args) -> None:
    """尚未標註的候選交給 Gemini 判斷（規則同人工：類別相同、造型可替代即命中，不看顏色）。"""
    from designbridge.render.llm import call_llm

    path = Path(args.csv)
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        # 保留原檔的其他欄位（例如校準用的人工標註）
        fields = list(reader.fieldnames or []) + [c for c in _fieldnames(auto=True) if c not in (reader.fieldnames or [])]
    prompt = ("左圖是室內效果圖中裁切出的一件家具，右圖是一件商品照。"
              "請判斷右邊的商品能不能拿來替代左邊的家具：類別相同、造型可以替代就算命中，顏色不列入判斷。"
              "只回答一個字：1（命中）或 0（不命中）。")
    done = 0
    for r in rows:
        crop = path.parent / r["crop"]
        for k in range(1, TOP_K + 1):
            if not r.get(f"url_{k}") or r.get(f"hit_{k}") not in (None, ""):
                continue
            try:
                ans = call_llm(prompt, images=[str(crop), r[f"image_url_{k}"]], max_tokens=20, temperature=0.0).strip()
                r[f"hit_{k}"] = "1" if ans.startswith("1") else "0"
                r[f"auto_{k}"] = "1"
                done += 1
            except Exception as e:
                print(f"⚠️  {r['item_id']} 候選 {k} 判斷失敗：{e}")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"✅ Gemini 暫標 {done} 個候選 → {path}")


LABEL_MIN_SIM = 0.65   # 評估的最低門檻；更低的候選任何門檻都不會推薦，不用標
REPEAT_COUNT = 15      # 隨機重複出現的候選數，用來算標註者前後一致率


def labelpage(args) -> None:
    """產生盲標網頁：不顯示相似度、品牌與名次，順序打亂，結尾混入重複候選；進度存在瀏覽器。"""
    import json
    import random

    path = Path(args.csv)
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    tasks = []
    for r in rows:
        cands = []
        for k in range(1, TOP_K + 1):
            try:
                sim = float(r.get(f"sim_{k}") or "")
            except ValueError:
                continue
            if sim >= LABEL_MIN_SIM and r.get(f"image_url_{k}"):
                cands.append({"k": k, "img": r[f"image_url_{k}"], "name": r.get(f"name_{k}") or ""})
        if cands:
            tasks.append({"id": r["item_id"], "name": r["detected_name"], "crop": r["crop"], "cands": cands})
    rng = random.Random(args.seed)
    rng.shuffle(tasks)
    for t in tasks:
        rng.shuffle(t["cands"])   # 名次也打亂，避免知道哪個是第 1 名
    pool = [(t, c) for t in tasks for c in t["cands"]]
    repeats = [{"id": t["id"], "name": t["name"], "crop": t["crop"], "cands": [c], "repeat": True}
               for t, c in rng.sample(pool, min(REPEAT_COUNT, len(pool)))]
    # 重複題分散插在後半段，不會連著出現在原題後面
    half = len(tasks) // 2
    order = tasks[:half] + tasks[half:]
    for rep_task in repeats:
        order.insert(rng.randint(half, len(order)), rep_task)

    data = json.dumps(order, ensure_ascii=False)
    total = sum(len(t["cands"]) for t in order)
    html_text = _LABEL_HTML.replace("__DATA__", data).replace("__TOTAL__", str(total)).replace("__KEY__", path.stem + "_v2")
    out = path.parent / f"label_{path.stem}.html"
    out.write_text(html_text, encoding="utf-8")
    print(f"✅ {len(tasks)} 件家具、{total} 個判斷（含重複 {len(repeats)} 個）→ {out}")


_LABEL_HTML = r"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>家具推薦標註</title>
<style>
:root { --bg:#f6f4ef; --card:#fff; --text:#2a2622; --soft:#6f6860; --line:#e2ddd3; --ok:#2f7d4f; --no:#b2463b; --accent:#3d5a80; }
* { box-sizing:border-box; } body { margin:0; background:var(--bg); color:var(--text); font-family:system-ui,"Noto Sans TC",sans-serif; }
header { position:sticky; top:0; z-index:2; background:var(--card); border-bottom:1px solid var(--line); padding:10px 16px; display:flex; flex-wrap:wrap; gap:12px; align-items:center; }
header h1 { font-size:16px; margin:0; } .bar { flex:1 1 200px; height:8px; background:var(--line); border-radius:4px; overflow:hidden; } .bar i { display:block; height:100%; background:var(--accent); }
button { font:inherit; cursor:pointer; } .btn { padding:6px 14px; border:1px solid var(--line); border-radius:999px; background:#fff; }
.rules { max-width:1100px; margin:12px auto 0; padding:10px 16px; font-size:13px; color:var(--soft); line-height:1.7; }
main { max-width:1100px; margin:0 auto; padding:16px; }
.task { display:grid; grid-template-columns:260px 1fr; gap:16px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; }
.target img { width:100%; max-height:260px; object-fit:contain; background:#eee; border-radius:8px; } .target p { margin:8px 0 0; font-weight:600; }
.cands { display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; }
.cand { border:2px solid var(--line); border-radius:10px; padding:10px; display:flex; flex-direction:column; gap:8px; }
.cand.focus { border-color:var(--accent); } .cand img { width:100%; height:170px; object-fit:contain; background:#fafafa; border-radius:6px; }
.cand .nm { font-size:12px; color:var(--soft); min-height:2.4em; }
.row { display:flex; gap:6px; } .row button { flex:1; padding:6px 0; border:1px solid var(--line); border-radius:6px; background:#fff; font-size:13px; }
.row button.on.y { background:var(--ok); border-color:var(--ok); color:#fff; } .row button.on.n { background:var(--no); border-color:var(--no); color:#fff; }
.bad-btn { margin-top:8px; font-size:12px; padding:4px 10px; border:1px solid var(--line); border-radius:999px; background:#fff; color:var(--soft); }
.bad-btn.on { background:var(--no); color:#fff; border-color:var(--no); } .task.bad .cands { opacity:.35; pointer-events:none; }
.cand.todo { border-color:#d9a400; } .todo-tip { font-size:12px; color:#9a7400; }
nav { display:flex; justify-content:space-between; align-items:center; margin-top:14px; font-size:13px; color:var(--soft); }
.keys { font-size:12px; color:var(--soft); } kbd { border:1px solid var(--line); border-radius:4px; padding:0 4px; background:#fff; }
@media (max-width:700px) { .task { grid-template-columns:1fr; } }
</style></head><body>
<header><h1>家具推薦標註</h1><div class="bar"><i id="bar"></i></div><span id="count"></span>
<button class="btn" id="jumpBtn">跳到未完成</button><button class="btn" id="exportBtn">匯出 CSV</button><button class="btn" id="clearBtn">清除進度</button></header>
<div class="rules"><b>命中</b>：商品跟左邊的家具類別相同、造型可以替代（不看顏色）。<b>顏色</b>：商品顏色跟左邊家具接近。
左邊裁切圖看不出是什麼家具（或框錯東西）時，按圖下方的「看不出是什麼家具」，這件不計入命中率。
每件家具的候選都標完會自動跳到下一件。進度自動存在這個瀏覽器；標到一半也可以先匯出 CSV。</div>
<main><div id="task"></div>
<nav><button class="btn" id="prev">← 上一件</button><span class="keys">鍵盤：<kbd>1</kbd>/<kbd>2</kbd> 命中/不中、<kbd>3</kbd>/<kbd>4</kbd> 顏色接近/不接近、<kbd>Tab</kbd> 換候選、<kbd>←</kbd><kbd>→</kbd> 換家具</span><button class="btn" id="next">下一件 →</button></nav></main>
<script>
const TASKS = __DATA__, TOTAL = __TOTAL__, KEY = "label___KEY__";
let labels = {}; try { labels = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
let idx = 0, focus = 0;
const keyOf = (t, c) => `${t.id}|${c.k}|${t.repeat ? "r" : "o"}`;
function save() { try { localStorage.setItem(KEY, JSON.stringify(labels)); } catch (e) {} }
const badKey = t => `${t.id}|bad`;
const isBad = t => !!(labels[badKey(t)] || {}).bad;
const unfinished = (t, c) => { if (isBad(t)) return false; const v = labels[keyOf(t, c)]; return !v || v.hit === undefined || v.color === undefined; };
function doneCount() { return TASKS.reduce((n, t) => n + t.cands.filter(c => !unfinished(t, c)).length, 0); }
function firstUnfinished(from = 0) {
  // 從目前這件之後往後找，找不到再從頭找（標到一半跳過的候選才找得回來）
  for (let n = 0; n < TASKS.length; n++) { const i = (from + n) % TASKS.length; if (TASKS[i].cands.some(c => unfinished(TASKS[i], c))) return i; }
  return -1;
}
function render() {
  const t = TASKS[idx]; const n = doneCount();
  document.getElementById("bar").style.width = (100 * n / TOTAL) + "%";
  document.getElementById("count").textContent = `${n} / ${TOTAL}　（第 ${idx + 1} / ${TASKS.length} 件）`;
  const cands = t.cands.map((c, i) => { const v = labels[keyOf(t, c)] || {}; const todo = unfinished(t, c);
    const b = (f, val, txt, cls) => `<button class="${cls} ${v[f] === val ? "on" : ""}" data-i="${i}" data-f="${f}" data-v="${val}">${txt}</button>`;
    return `<div class="cand ${i === focus ? "focus" : ""} ${todo && (v.hit !== undefined || v.color !== undefined) ? "todo" : ""}"><img src="${c.img}" alt=""><div class="nm">${c.name}</div>
      ${todo && (v.hit !== undefined || v.color !== undefined) ? '<div class="todo-tip">還差一項沒標</div>' : ""}
      <div class="row">${b("hit", 1, "命中", "y")}${b("hit", 0, "不中", "n")}</div>
      <div class="row">${b("color", 1, "顏色接近", "y")}${b("color", 0, "不接近", "n")}</div></div>`; }).join("");
  document.getElementById("task").innerHTML = `<div class="task ${isBad(t) ? "bad" : ""}"><div class="target"><img src="${t.crop}" alt=""><p>${t.name}</p><button class="bad-btn ${isBad(t) ? "on" : ""}" id="badBtn">看不出是什麼家具</button></div><div class="cands">${cands}</div></div>`;
}
function set(i, f, v) {
  const t = TASKS[idx], c = t.cands[i], k = keyOf(t, c);
  labels[k] = { ...(labels[k] || {}), [f]: v }; save();
  const all = t.cands.every(cc => { const x = labels[keyOf(t, cc)]; return x && x.hit !== undefined && x.color !== undefined; });
  if (labels[k].hit !== undefined && labels[k].color !== undefined && focus < t.cands.length - 1) focus++;
  if (all && idx < TASKS.length - 1) { idx++; focus = 0; }
  render();
}
document.getElementById("task").addEventListener("click", e => {
  if (e.target.id === "badBtn") { const t = TASKS[idx]; const on = !isBad(t); labels[badKey(t)] = { bad: on }; save();
    if (on && idx < TASKS.length - 1) { idx++; focus = 0; } render(); return; }
  const b = e.target.closest("button[data-f]"); if (b) { focus = +b.dataset.i; set(+b.dataset.i, b.dataset.f, +b.dataset.v); } });
document.getElementById("jumpBtn").onclick = () => {
  const i = firstUnfinished(idx + 1);
  if (i < 0) { alert("全部都標完了，可以按「匯出 CSV」"); return; }
  idx = i; focus = Math.max(0, TASKS[i].cands.findIndex(c => unfinished(TASKS[i], c))); render();
};
document.getElementById("clearBtn").onclick = () => {
  if (!confirm("確定清除全部標註進度？清除前建議先匯出 CSV。")) return;
  labels = {}; save(); idx = 0; focus = 0; render();
};
document.getElementById("prev").onclick = () => { if (idx > 0) { idx--; focus = 0; render(); } };
document.getElementById("next").onclick = () => { if (idx < TASKS.length - 1) { idx++; focus = 0; render(); } };
document.addEventListener("keydown", e => {
  const m = { "1": ["hit", 1], "2": ["hit", 0], "3": ["color", 1], "4": ["color", 0] }[e.key];
  if (m) set(focus, m[0], m[1]);
  else if (e.key === "Tab") { e.preventDefault(); focus = (focus + 1) % TASKS[idx].cands.length; render(); }
  else if (e.key === "ArrowRight") document.getElementById("next").click();
  else if (e.key === "ArrowLeft") document.getElementById("prev").click();
});
document.getElementById("exportBtn").onclick = () => {
  const lines = ["item_id,k,hit,color,repeat"];
  for (const [k, v] of Object.entries(labels)) { const [id, kk, r] = k.split("|");
    if (kk === "bad") { if (v.bad) lines.push([id, 0, "x", "", 0].join(",")); continue; }
    if (v.hit !== undefined) lines.push([id, kk, v.hit, v.color ?? "", r === "r" ? 1 : 0].join(",")); }
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + lines.join("\n")], { type: "text/csv" }));
  a.download = "labels.csv"; a.click();
};
idx = Math.max(0, firstUnfinished()); render();
</script></body></html>
"""


def score(args) -> None:
    with open(args.csv, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if args.labels:
        rows = _apply_labels(rows, Path(args.labels), strict=args.strict)

    def num(v: str) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    bad = [r for r in rows if r.get("_bad")]
    rows = [r for r in rows if not r.get("_bad")]
    if bad:
        print(f"裁切圖看不出是什麼家具 {len(bad)} 件，未計入")
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
        # 推薦有重新排序（風格加分）時第 1 名不一定最高分，Top-1 看達門檻的候選中排第一的
        shown = [[(s, h) for s, h in c if s >= t] for c in items]
        covered = [c for c in shown if c]
        top1 = sum(c[0][1] for c in covered)
        top3 = sum(any(h for _, h in c) for c in covered)
        cov = len(covered) / len(items)
        rate = lambda x: f"{x / len(covered):.1%} ({x}/{len(covered)})" if covered else "-"
        print(f"{t:>6.2f} | {cov:>7.1%} | {rate(top1):>12} | {rate(top3):>12}")


def _apply_labels(rows: list[dict], path: Path, strict: bool) -> list[dict]:
    """把標註網頁匯出的 labels.csv 填回 hit 欄位；strict 時命中要同時顏色接近。順便印出重複一致率。"""
    with open(path, newline="", encoding="utf-8-sig") as f:
        labels = list(csv.DictReader(f))
    bad = {l["item_id"] for l in labels if l["hit"] == "x"}
    labels = [l for l in labels if l["item_id"] not in bad]
    orig = {(l["item_id"], l["k"]): l for l in labels if l["repeat"] == "0"}
    reps = [(orig.get((l["item_id"], l["k"])), l) for l in labels if l["repeat"] == "1"]
    reps = [(o, r) for o, r in reps if o]
    if reps:
        same_hit = sum(o["hit"] == r["hit"] for o, r in reps)
        same_color = sum(o["color"] == r["color"] for o, r in reps)
        print(f"重複標註一致率：命中 {same_hit / len(reps):.1%}（{same_hit}/{len(reps)}），"
              f"顏色 {same_color / len(reps):.1%}（{same_color}/{len(reps)}）")
    print("命中標準：" + ("嚴格（造型可替代且顏色接近）" if strict else "寬鬆（造型可替代，不看顏色）"))
    for r in rows:
        if r["item_id"] in bad:
            r["_bad"] = "1"
            continue
        for k in range(1, TOP_K + 1):
            l = orig.get((r["item_id"], str(k)))
            if l:
                r[f"hit_{k}"] = "1" if l["hit"] == "1" and (not strict or l["color"] == "1") else "0"
            else:
                try:
                    low = float(r.get(f"sim_{k}") or "") < LABEL_MIN_SIM
                except ValueError:
                    low = False
                if low:
                    r[f"hit_{k}"] = "0"   # 低於最低門檻的候選沒有標，任何門檻都不會推薦，不影響計分
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="跑偵測並輸出候選表")
    pe.add_argument("--images", nargs="+", default=[str(ROOT / "artifacts" / "render")], help="圖片檔或資料夾")
    pe.add_argument("--limit", type=int, default=0, help="最多處理幾張圖（0 = 全部）")
    pe.add_argument("--out", default=str(DEFAULT_OUT))
    pe.add_argument("--overwrite", action="store_true", help="覆蓋既有的 candidates.csv")
    pe.set_defaults(func=extract)

    pr = sub.add_parser("rematch", help="沿用裁切圖，用目前商品庫重新比對")
    pr.add_argument("--csv", default=str(DEFAULT_OUT / "candidates.csv"), help="提供裁切圖與偵測結果的候選表")
    pr.add_argument("--out", default=str(DEFAULT_OUT))
    pr.add_argument("--out-csv", default="candidates_v2.csv")
    pr.add_argument("--config", choices=CONFIGS, default="style")
    pr.add_argument("--style-bonus", type=float, default=0.02)
    pr.set_defaults(func=rematch)

    pc = sub.add_parser("compare", help="比較不同設定的覆蓋率、細分類吻合率等（不需人工標註）")
    pc.add_argument("csvs", nargs="+")
    pc.add_argument("--threshold", type=float, default=0.75)
    pc.set_defaults(func=compare)

    pa = sub.add_parser("autolabel", help="用 Gemini 暫標尚未標註的候選")
    pa.add_argument("--csv", default=str(DEFAULT_OUT / "candidates_v2.csv"))
    pa.set_defaults(func=autolabel)

    ps = sub.add_parser("score", help="讀標註後的候選表計算各門檻結果")
    ps.add_argument("--csv", default=str(DEFAULT_OUT / "candidates.csv"))
    ps.add_argument("--thresholds", nargs="+", type=float, default=[0.65, 0.70, 0.75, 0.80, 0.85])
    ps.add_argument("--labels", help="標註網頁匯出的 labels.csv")
    ps.add_argument("--strict", action="store_true", help="命中要同時顏色接近")
    ps.set_defaults(func=score)

    pl = sub.add_parser("labelpage", help="產生盲標用的標註網頁")
    pl.add_argument("--csv", default=str(DEFAULT_OUT / "cfg_abc.csv"))
    pl.add_argument("--seed", type=int, default=20261025)
    pl.set_defaults(func=labelpage)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
