#!/usr/bin/env python3
"""用 Gemini Vision 審查本機爬下來的圖：評品質（看得出整體格局者高分）＋分風格。

不需先上傳 Supabase，結果存在 raw/gemini_review.json（已評過的不重跑）。

Usage (from project root):
    python -m style_kb.collection.gemini_review --sample 30        # 校準：隨機抽 30 張
    python -m style_kb.collection.gemini_review                    # 跑完全部衛浴＋廚房
    python -m style_kb.collection.gemini_review --html-only --open # 只重產審查頁
    python -m style_kb.collection.gemini_review --upload           # 預覽要上傳哪些（套用人工修改）
    python -m style_kb.collection.gemini_review --upload --commit  # 實際寫入 style_images
    python -m style_kb.collection.gemini_review --db --limit 20    # 審 DB 裡的舊圖，結果直接寫回
"""

from __future__ import annotations

import argparse
import html
import json
import random
import sys
import threading
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from style_kb.collection.generate_captions import STYLE_REF, VALID_STYLES

RAW_DIR = Path(__file__).resolve().parent.parent / "raw" / "100interior_images"
RESULT_PATH = RAW_DIR.parent / "gemini_review.json"
HTML_PATH = RAW_DIR.parent / "gemini_review.html"
OVERRIDES_PATH = RAW_DIR.parent / "gemini_overrides.json"  # 審查頁「匯出我的修改」的檔案
SPACE_ZH = {"living_room": "客廳", "dining_room": "餐廳", "kitchen": "廚房", "bathroom": "浴室",
            "bedroom": "臥室", "study": "書房", "foyer": "玄關", "hallway": "走道",
            "office": "辦公室", "balcony": "陽台", "other": "其他"}
SPACE_EN = {v: k for k, v in SPACE_ZH.items()}
SPACES = {3: "bathroom", 5: "kitchen", 11: "balcony"}  # 100.com.tw space_id → 預期空間
# 開放式格局常一張拍到兩區，不算空間不符
SPACE_COMPAT = {"kitchen": {"dining_room"}, "dining_room": {"kitchen", "living_room"},
                "living_room": {"dining_room"}}

# 總分權重；硬淘汰條件見 compute_score
W_LAYOUT, W_STYLE, W_QUALITY = 0.45, 0.35, 0.20
PASS_SCORE = 6.0
MIN_LAYOUT = 7  # 只拍到角落/局部（中景常給 5-6）就不收
LOW_STYLE_CONF = 0.6

PROMPT = f"""You are curating a reference-image library for an interior-design AI.
Good references show the WHOLE room: you can read the layout (walls, floor, where the main
fixtures sit relative to each other) and the design style. Close-ups and detail shots are useless.

Style definitions (choose style_id from these keys only):
{STYLE_REF}

The source website tagged this photo as space="{{space}}", style="{{site_style}}".
That tag is only a hint; site style labels do NOT match our definitions, judge from the image.
"modern" is NOT a default for any clean contemporary room: pick it only when no other style's
signature cues (wood tones and softness for nordic/japanese, molding for american, metal/marble
glam for luxury, raw concrete/metal for industrial, cream rounded forms for country, etc.) are present.

First describe what you see, then rate. Return JSON only:
{{{{
  "description": "<one sentence: what the photo shows and from how far>",
  "space": "<{'|'.join(SPACE_ZH)}>",
  "shot_type": "<wide|medium|close_up|detail>",
  "layout_visibility": <0-10, how well the room's overall layout can be read>,
  "style_clarity": <0-10, how clearly a design style is expressed by materials/colors/furniture>,
  "photo_quality": <0-10, sharpness, exposure, composition>,
  "has_people": <bool>,
  "has_animals": <bool>,
  "has_text_or_watermark": <bool, large text, logos, collage layouts; ignore small corner watermarks>,
  "style_id": "<one of: {'/'.join(VALID_STYLES)}>",
  "style_confidence": <0-1>,
  "style_id_2": "<second most likely style_id>",
  "style_confidence_2": <0-1>,
  "style_reason": "<one short sentence citing the visual cues>"
}}}}
Scoring guide for layout_visibility: wide shot showing most of the room 8-10; medium shot
showing a full wall/counter run 5-7; partial corner 3-4; close-up or single object 0-2."""


def compute_score(r: dict, expected_space: str) -> tuple[float, list[str]]:
    """回傳 (分數, 淘汰原因)；有淘汰原因時分數照算但不通過。"""
    reasons = []
    if r.get("has_people"):
        reasons.append("有人")
    if r.get("has_animals"):
        reasons.append("有動物")
    if r.get("has_text_or_watermark"):
        reasons.append("文字/拼貼")
    if r.get("shot_type") in ("close_up", "detail"):
        reasons.append("近照/特寫")
    if float(r.get("layout_visibility", 0)) < MIN_LAYOUT:
        reasons.append("看不出整體格局")
    got = r.get("space")
    if expected_space != "other" and got != expected_space and got not in SPACE_COMPAT.get(expected_space, ()):
        reasons.append(f"空間不符({r.get('space')})")
    score = (W_LAYOUT * float(r.get("layout_visibility", 0))
             + W_STYLE * float(r.get("style_clarity", 0))
             + W_QUALITY * float(r.get("photo_quality", 0)))
    return round(score, 2), reasons


def _targets(space_ids: set[int]) -> list[tuple[Path, dict]]:
    out = []
    for meta_path in sorted(RAW_DIR.glob("*_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        img = meta_path.with_name(meta_path.name[: -len("_meta.json")] + ".jpg")
        if meta.get("space_id") in space_ids and img.exists():
            out.append((img, meta))
    return out


def _judge(r: dict, expected: str) -> dict:
    r["score"], r["reject_reasons"] = compute_score(r, expected)
    r["passed"] = not r["reject_reasons"] and r["score"] >= PASS_SCORE
    r["expected_space"] = expected
    return r


def _review_bytes(client, model: str, data: bytes, mime: str, expected: str, site_style: str) -> dict:
    from google.genai import types

    prompt = PROMPT.format(space=expected, site_style=site_style)
    resp = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=data, mime_type=mime), prompt],
        config=types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json"),
    )
    r = json.loads(resp.text)
    if r.get("style_id") not in VALID_STYLES:
        r["style_id"] = "other"
    r["site_style"] = site_style
    return _judge(r, expected)


def _review_one(client, model: str, img: Path, meta: dict) -> dict:
    r = _review_bytes(client, model, img.read_bytes(), "image/jpeg",
                      SPACES[meta["space_id"]], meta.get("style", ""))
    r["image_url"] = meta.get("url", "")
    r["work_url"] = meta.get("work_url", "")
    return r


def db_fields(r: dict, override: dict | None, current_style: str, old_flags: dict | None) -> dict:
    """轉成 review_server 看得懂的格式：通過＝1.0，不通過 <1 會出現在 --flagged-only。"""
    override = override or {}
    passed = override.get("keep", r["passed"])
    reasons = r["reject_reasons"]
    flags = {k: v for k, v in (old_flags or {}).items()
             if k not in ("style_mismatch_reason", "suggested_styles")}
    flags.update({
        "gemini_review": r,
        "human_override": override or None,
        "person_detected": bool(r.get("has_people")),
        "animal_detected": bool(r.get("has_animals")),
        "is_closeup": r.get("shot_type") in ("close_up", "detail"),
        "no_layout": "看不出整體格局" in reasons,
        "space_mismatch": any(x.startswith("空間不符") for x in reasons),
        "text_overlay": bool(r.get("has_text_or_watermark")),
    })
    if r["style_id"] != current_style:
        flags["style_mismatch_reason"] = r.get("style_reason", "")
        flags["suggested_styles"] = [x for x in (r["style_id"], r.get("style_id_2")) if x and x != current_style]
    return {
        "quality_score": 1.0 if passed else min(0.99, round(r["score"] / 10, 3)),
        "quality_flags": flags,
    }


def run(sample: int | None, space_ids: set[int], workers: int) -> None:
    from designbridge.core.config import Config
    from designbridge.render.llm import get_gemini_client

    results = json.loads(RESULT_PATH.read_text(encoding="utf-8")) if RESULT_PATH.exists() else {}
    todo = [(img, m) for img, m in _targets(space_ids) if img.name not in results]
    if sample:
        todo = random.Random(0).sample(todo, min(sample, len(todo)))
    print(f"待審 {len(todo)} 張（已審 {len(results)}），模型 {Config.GEMINI_MODEL}")

    client = get_gemini_client()
    lock = threading.Lock()

    def work(item):
        img, meta = item
        try:
            r = _review_one(client, Config.GEMINI_MODEL, img, meta)
        except Exception as exc:
            print(f"  ❌ {img.name}: {exc}")
            return
        with lock:
            results[img.name] = r
            # 每張都存，中斷可續跑
            RESULT_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
            flag = "✅" if r["passed"] else "✖"
            print(f"  [{len(results)}] {flag} {r['score']:4.1f} {r['style_id']:10} {img.name} {' '.join(r['reject_reasons'])}")

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(work, todo))


def build_html(space: str | None = None) -> None:
    results = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    if space:
        results = {k: v for k, v in results.items() if v.get("expected_space") == space}
    groups: dict[str, list] = {}
    for name, r in results.items():
        if r["reject_reasons"]:
            key = "✖ 淘汰"
        elif r.get("style_confidence", 0) < LOW_STYLE_CONF:
            key = "? 風格不確定"
        else:
            key = r["style_id"]
        groups.setdefault(key, []).append((name, r))

    order = sorted(groups, key=lambda k: (k.startswith(("✖", "?")), k))
    parts = [f"""<!doctype html><meta charset=utf-8><title>Gemini 審查</title><style>
body{{font-family:sans-serif;margin:16px;background:#f6f4f1;color:#222}}h2{{margin:28px 0 8px}}
.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px}}
figure{{margin:0;background:#fff;border-radius:6px;overflow:hidden}}figure.fail{{opacity:.55}}
img{{width:100%;height:180px;object-fit:cover;display:block}}
figcaption{{font-size:12px;padding:6px;line-height:1.45}}.s{{font-weight:700;font-size:15px}}
.r{{color:#b3261e}}.m{{color:#777}}figure.edited{{outline:3px solid #2b6cb0}}
.ctl{{display:flex;gap:6px;padding:6px 6px 0}}.ctl button{{flex:1;cursor:pointer;padding:4px;border:1px solid #ccc;border-radius:4px;background:#fff}}
figure:not(.fail) .ctl button{{background:#e6f4ea}}figure.fail .ctl button{{background:#fde8e8}}
#bar{{position:sticky;top:0;background:#f6f4f1;padding:8px 0;z-index:1;display:flex;gap:12px;align-items:center}}</style>
<h1>Gemini 審查（{len(results)} 張，通過門檻 {PASS_SCORE}）</h1>
<div id=bar><span id=cnt></span><button onclick=exp()>匯出我的修改</button>
<span class=m>點按鈕切換保留／打叉，下拉改風格；藍框＝你改過的。存在瀏覽器裡，關掉再開還在。</span></div>"""]
    opts = "".join(f"<option>{s}</option>" for s in VALID_STYLES)
    for key in order:
        items = sorted(groups[key], key=lambda x: -x[1]["score"])
        passed = sum(r["passed"] for _, r in items)
        parts.append(f"<h2>{html.escape(key)}（{len(items)} 張，通過 {passed}）</h2><div class=g>")
        for name, r in items:
            src = (RAW_DIR / name).resolve().as_uri()
            parts.append(
                f"<figure data-n='{name}' data-p='{int(r['passed'])}' data-s='{r['style_id']}'>"
                f"<a href='{src}' target=_blank><img loading=lazy src='{src}'></a>"
                f"<div class=ctl><button onclick=tog(this)></button><select onchange=sty(this)>{opts}</select></div>"
                f"<figcaption><span class=s>{r['score']}</span> "
                f"格局{r.get('layout_visibility')} 風格{r.get('style_clarity')} 畫質{r.get('photo_quality')} · {r.get('shot_type')}<br>"
                f"<b>{r['style_id']}</b> {r.get('style_confidence')} / {r.get('style_id_2')} {r.get('style_confidence_2')} <span class=m>(站上：{html.escape(r['site_style'])}・{r['expected_space']})</span><br>"
                f"<span class=r>{html.escape(' '.join(r['reject_reasons']))}</span>"
                f"<span class=m>{html.escape(r.get('style_reason', ''))}<br>{html.escape(r.get('description', ''))}</span><br>"
                f"<span class=m>{name}</span> <a href='{r['work_url']}' target=_blank>原案例</a></figcaption></figure>"
            )
        parts.append("</div>")
    # 人工修改存 localStorage，匯出成 gemini_overrides.json 給上傳腳本讀
    parts.append("""<script>
const K='gemini_overrides',ov=JSON.parse(localStorage.getItem(K)||'{}');
function cur(f){const o=ov[f.dataset.n]||{};return{keep:o.keep??f.dataset.p==='1',style:o.style??f.dataset.s}}
function paint(f){const c=cur(f);f.classList.toggle('fail',!c.keep);f.classList.toggle('edited',!!ov[f.dataset.n]);
 f.querySelector('.ctl button').textContent=c.keep?'✓ 保留':'✗ 打叉';f.querySelector('select').value=c.style}
function set(f,k,v){const n=f.dataset.n,o=ov[n]||{};o[k]=v;
 if(o.keep===(f.dataset.p==='1'))delete o.keep;if(o.style===f.dataset.s)delete o.style;
 Object.keys(o).length?ov[n]=o:delete ov[n];localStorage.setItem(K,JSON.stringify(ov));paint(f);count()}
function tog(b){const f=b.closest('figure');set(f,'keep',!cur(f).keep)}
function sty(s){set(s.closest('figure'),'style',s.value)}
function count(){const fs=[...document.querySelectorAll('figure')];
 document.getElementById('cnt').textContent=`保留 ${fs.filter(f=>cur(f).keep).length} / ${fs.length}，你改了 ${Object.keys(ov).length} 張`}
function exp(){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(ov,null,1)],{type:'application/json'}));
 a.download='gemini_overrides.json';a.click()}
document.querySelectorAll('figure').forEach(paint);count();
</script>""")
    HTML_PATH.write_text("".join(parts), encoding="utf-8")
    print(f"📄 {HTML_PATH}")


def upload(commit: bool) -> None:
    """只寫 DB、不傳檔：image_url 直接用 100 CDN 原圖網址。"""
    from collections import Counter

    from style_kb.scrapper.dedup import fetch_manifest_from_supabase, image_asset_key, is_duplicate

    results = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    overrides = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8")) if OVERRIDES_PATH.exists() else {}
    manifest = fetch_manifest_from_supabase()
    manifest = {k: set(v) for k, v in manifest.items()}

    rows, dup = [], 0
    for name, r in results.items():
        o = overrides.get(name, {})
        if not o.get("keep", r["passed"]):
            continue
        meta = json.loads((RAW_DIR / f"{Path(name).stem}_meta.json").read_text(encoding="utf-8"))
        if is_duplicate(image_key=image_asset_key(meta["url"]), image_id=meta.get("image_id"), manifest=manifest):
            dup += 1
            continue
        # 統一成 jpg 縮圖網址：舊 meta 是 .avif，caption 腳本會依副檔名判 mime
        url = meta["url"].split("!")[0] + "!t1000.jpg"
        style = o.get("style", r["style_id"])
        rows.append({
            "style_id": style,
            "image_path": f"external/{name}",  # NOT NULL；external/ 表示不在 Storage
            "image_url": url,
            "space": SPACE_ZH[r["expected_space"]],
            "source_meta": meta,
            **db_fields(r, o, style, None),
            "ai_style_confidence": 1.0 if "style" in o else r.get("style_confidence"),
        })

    print(f"要上傳 {len(rows)} 張（已在 DB 跳過 {dup}）")
    for (sid, sp), n in sorted(Counter((x["style_id"], x["space"]) for x in rows).items()):
        print(f"  {sid:11} {sp} {n}")
    if not commit:
        print("加 --commit 實際寫入")
        return

    from supabase import create_client
    import os
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    for i in range(0, len(rows), 50):
        client.table("style_images").insert(rows[i:i + 50]).execute()
        print(f"  已寫入 {min(i + 50, len(rows))}/{len(rows)}")


def _fetch_image(row: dict) -> tuple[bytes, str]:
    import httpx

    # source_meta.url 比 R2 鏡像可靠；100 CDN 統一取 jpg 縮圖（舊網址是 .avif）
    url = (row.get("source_meta") or {}).get("url") or row["image_url"]
    if "100.com.tw" in url:
        url = url.split("!")[0] + "!t1000.jpg"
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    if resp.status_code != 200 and url != row["image_url"]:
        resp = httpx.get(row["image_url"], timeout=30, follow_redirects=True)
    resp.raise_for_status()
    mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
    return resp.content, mime if mime.startswith("image/") else "image/jpeg"


def db_review(limit: int | None, workers: int) -> None:
    """審 DB 裡的圖並直接寫回；已有 gemini_review 的只轉格式不重打 API，可續跑。"""
    import os

    from supabase import create_client

    from designbridge.core.config import Config
    from designbridge.render.llm import get_gemini_client

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows, off = [], 0
    while True:
        b = (sb.table("style_images").select("id,style_id,space,image_url,source_meta,quality_flags")
             .order("id").range(off, off + 999).execute().data)
        rows += b
        off += 1000
        if len(b) < 1000:
            break

    reformat = [x for x in rows if (x["quality_flags"] or {}).get("gemini_review")
                and "no_layout" not in x["quality_flags"]]
    for x in reformat:  # 先前上傳的衛浴/廚房：用存著的評分重算，人工修改沿用
        fl = x["quality_flags"]
        r = _judge(fl["gemini_review"], fl["gemini_review"]["expected_space"])
        sb.table("style_images").update(
            db_fields(r, fl.get("human_override"), x["style_id"], None)).eq("id", x["id"]).execute()
    print(f"轉格式 {len(reformat)} 筆")

    todo = [x for x in rows if not (x["quality_flags"] or {}).get("gemini_review")]
    if limit:
        todo = todo[:limit]
    print(f"待審 {len(todo)} 張，模型 {Config.GEMINI_MODEL}")
    client = get_gemini_client()
    lock, done = threading.Lock(), [0, 0]

    def work(x):
        try:
            data, mime = _fetch_image(x)
            r = _review_bytes(client, Config.GEMINI_MODEL, data, mime,
                              SPACE_EN.get(x.get("space") or "", "other"), x["style_id"] or "")
            sb.table("style_images").update(
                db_fields(r, None, x["style_id"], x["quality_flags"])).eq("id", x["id"]).execute()
        except Exception as exc:
            print(f"  ❌ {x['id'][:8]}: {str(exc)[:120]}")
            return
        with lock:
            done[0] += 1
            done[1] += r["passed"]
            if done[0] % 25 == 0 or not r["passed"]:
                print(f"  [{done[0]}/{len(todo)} 通過{done[1]}] {'✅' if r['passed'] else '✖'} {r['score']:4.1f} "
                      f"{x['style_id']}→{r['style_id']} {x['id'][:8]} {' '.join(r['reject_reasons'])}")

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(work, todo))
    print(f"完成：審 {done[0]} 張，通過 {done[1]}")


def main() -> None:
    p = argparse.ArgumentParser(description="Gemini 審查本機圖片：品質評分＋風格分類")
    p.add_argument("--sample", type=int, default=None, help="隨機抽 N 張（校準用）")
    p.add_argument("--space", choices=["衛浴", "廚房", "陽臺", "all"], default="all")
    p.add_argument("--db", action="store_true", help="審 Supabase 裡的圖，結果寫回 quality_score/quality_flags")
    p.add_argument("--limit", type=int, default=None, help="--db 時最多審幾張")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--html-only", action="store_true")
    p.add_argument("--open", action="store_true")
    p.add_argument("--upload", action="store_true", help="把通過的圖寫進 style_images（預設只預覽）")
    p.add_argument("--commit", action="store_true", help="搭配 --upload 實際寫入")
    a = p.parse_args()

    if a.upload:
        upload(a.commit)
        return
    if a.db:
        db_review(a.limit, a.workers)
        return

    if not a.html_only:
        ids = set(SPACES) if a.space == "all" else {{"衛浴": 3, "廚房": 5, "陽臺": 11}[a.space]}
        run(a.sample, ids, a.workers)
    build_html(None if a.space == "all" else SPACES[{"衛浴": 3, "廚房": 5, "陽臺": 11}[a.space]])
    if a.open:
        webbrowser.open(HTML_PATH.as_uri())


if __name__ == "__main__":
    main()
