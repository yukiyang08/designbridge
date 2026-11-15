#!/usr/bin/env python3
"""生成圖片品質審查 HTML 頁面。

從 Supabase 拉取 quality_score < 1.0 的圖片，生成一個本地 HTML 檔案。
在瀏覽器中開啟，人工審查後勾選要刪除的圖片，複製 ID 清單給 purge_rejected.py 使用。

Usage (from project root):
    python -m style_kb.collection.generate_review              # 生成 review.html（預設輸出路徑）
    python -m style_kb.collection.generate_review --out my.html
    python -m style_kb.collection.generate_review --all        # 含 score=1.0 的圖（全部已處理）
    python -m style_kb.collection.generate_review --style modern
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")
load_dotenv()


def get_supabase():
    from supabase import create_client
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


def fetch_rows(style: str | None, show_all: bool) -> list[dict]:
    client = get_supabase()
    PAGE = 1000
    all_rows: list[dict] = []
    offset = 0
    while True:
        q = (client.table("style_images")
             .select("id, image_url, source_meta, style_id, quality_score, quality_flags, width, height, file_size_kb, caption_en2, space, ai_style_confidence, caption_model")
             .order("quality_score", desc=False))
        if not show_all:
            # 「有問題的」= 舊的技術性 quality_score 過低，或新的 AI 語意判斷標記為不適合
            # （近景特寫 / 風格明顯不符 / 信心分數偏低），兩種來源合併篩選。
            q = q.or_(
                "quality_score.lt.1,"
                "ai_style_confidence.lt.0.5,"
                "quality_flags->>is_closeup.eq.true"
            )
        if style:
            q = q.eq("style_id", style)
        batch = (q.range(offset, offset + PAGE - 1).execute()).data or []
        all_rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return all_rows


def fetch_style_counts() -> dict[str, int]:
    """從 DB 取得各風格的真實總張數（分頁抓全部）。"""
    PAGE = 1000
    counts: dict[str, int] = {}
    offset = 0
    while True:
        batch = (get_supabase()
                 .table("style_images")
                 .select("style_id")
                 .range(offset, offset + PAGE - 1)
                 .execute()).data or []
        for r in batch:
            sid = r.get("style_id") or "other"
            counts[sid] = counts.get(sid, 0) + 1
        if len(batch) < PAGE:
            break
        offset += PAGE
    return counts


FLAG_LABELS = {
    "person_detected":  ("人物", "#ef4444"),
    "animal_detected":  ("動物", "#f97316"),
    "severe_blur":      ("極度模糊", "#8b5cf6"),
    "blur":             ("模糊", "#a78bfa"),
    "very_low_res":     ("解析度極低", "#dc2626"),
    "low_res":          ("解析度偏低", "#fb923c"),
    "bad_ratio":        ("比例異常", "#0ea5e9"),
    "too_small_kb":     ("檔案太小", "#64748b"),
    "corrupt":          ("損毀", "#1e293b"),
    "is_closeup":       ("近景特寫", "#eab308"),
    "no_layout":        ("看不出格局", "#ca8a04"),
    "space_mismatch":   ("空間不符", "#0891b2"),
    "text_overlay":     ("文字/拼貼", "#475569"),
}


def build_html(rows: list[dict], generated_at: str, db_style_counts: dict[str, int] | None = None) -> str:
    # 整理 rows 為前端用的 JSON
    cards = []
    all_flags: set[str] = set()

    for r in rows:
        flags = r.get("quality_flags") or {}
        active_flags = [k for k, v in flags.items()
                        if v is True and k in FLAG_LABELS]
        all_flags.update(active_flags)
        orient = flags.get("orientation", "")
        # source_meta.url（原始來源）比 image_url（R2 鏡像，部分資料夾已失效如 american/japanese）
        # 更可靠，實測 20 筆抽樣 R2 只有 80% 存活、source_meta.url 100% 存活，優先用它顯示
        source_url = (r.get("source_meta") or {}).get("url") or ""
        cards.append({
            "id":         r["id"],
            "url":        source_url or r["image_url"],
            "style":      r["style_id"] or "other",
            "score":      r.get("quality_score") or 0,
            "w":          r.get("width") or 0,
            "h":          r.get("height") or 0,
            "kb":         r.get("file_size_kb") or 0,
            "orient":     orient,
            "flags":      active_flags,
            "lap":        (r.get("quality_flags") or {}).get("laplacian", ""),
            "caption":    r.get("caption_en2") or "",
            "aiStyle":    r.get("style_id") or "other",
            "spaceType":  r.get("space") or "",
            "confidence": r.get("ai_style_confidence"),
            "hasAI":      bool(r.get("caption_model")) or r.get("ai_style_confidence") is not None,
            "mismatchReason": (r.get("quality_flags") or {}).get("style_mismatch_reason") or "",
            "suggestedStyles": (r.get("quality_flags") or {}).get("suggested_styles") or [],
        })

    flag_options_html = ""
    for key in sorted(all_flags):
        label, color = FLAG_LABELS.get(key, (key, "#888"))
        flag_options_html += (
            f'<button class="filter-btn" data-flag="{key}" '
            f'style="--fc:{color}">{label}</button>\n'
        )

    STYLE_ZH = {
        "modern": "現代風", "nordic": "北歐風", "japanese": "日式風",
        "industrial": "工業風", "american": "美式風", "classic": "古典風",
        "luxury": "奢華風", "country": "鄉村風", "other": "其他",
    }

    # 用 DB 真實總數；若沒傳入則 fallback 到 cards 內計算
    style_counts: dict[str, int] = db_style_counts or {}
    if not style_counts:
        for c in cards:
            s = c["style"] or "other"
            style_counts[s] = style_counts.get(s, 0) + 1

    style_btns_html = ""
    for sid, cnt in sorted(style_counts.items(), key=lambda x: -x[1]):
        label = STYLE_ZH.get(sid, sid)
        style_btns_html += (
            f'<button class="style-btn" data-style="{sid}">'
            f'{label} <span class="style-cnt">{cnt}</span></button>\n'
        )

    cards_json = json.dumps(cards, ensure_ascii=False)
    flag_labels_json = json.dumps(
        {k: {"label": v[0], "color": v[1]} for k, v in FLAG_LABELS.items()},
        ensure_ascii=False
    )

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DesignBridge 圖片品質審查</title>
<style>
*{{ box-sizing:border-box; margin:0; padding:0 }}
body{{ font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      background:#0f172a; color:#e2e8f0; min-height:100vh }}

/* ── Header ── */
.header{{ background:#1e293b; padding:16px 24px; border-bottom:1px solid #334155;
         display:flex; align-items:center; gap:16px; flex-wrap:wrap; position:sticky;
         top:0; z-index:100 }}
.header h1{{ font-size:18px; font-weight:700; color:#f1f5f9 }}
.stat{{ font-size:13px; color:#94a3b8 }}
.stat b{{ color:#f1f5f9 }}

/* ── Style tabs ── */
.style-tabs{{ background:#0f172a; padding:10px 24px; border-bottom:1px solid #1e293b;
             display:flex; gap:6px; flex-wrap:wrap; align-items:center; overflow-x:auto }}
.style-tabs label{{ font-size:12px; color:#475569; margin-right:4px; white-space:nowrap }}
.style-btn{{
  padding:5px 14px; border-radius:8px; border:1.5px solid #334155;
  background:transparent; color:#94a3b8; cursor:pointer;
  font-size:12px; font-weight:500; transition:all .15s; white-space:nowrap;
  display:flex; align-items:center; gap:6px;
}}
.style-btn:hover{{ border-color:#6366f1; color:#c7d2fe }}
.style-btn.active{{ background:#6366f1; border-color:#6366f1; color:#fff }}
.style-cnt{{ background:rgba(255,255,255,.15); border-radius:99px;
             padding:1px 6px; font-size:10px; font-weight:700 }}
.style-btn.active .style-cnt{{ background:rgba(255,255,255,.25) }}

/* ── Flag filters ── */
.filters{{ background:#1e293b; padding:10px 24px; border-bottom:1px solid #334155;
          display:flex; gap:8px; flex-wrap:wrap; align-items:center }}
.filters label{{ font-size:13px; color:#94a3b8; margin-right:4px }}
.filter-btn{{
  padding:4px 12px; border-radius:99px; border:1.5px solid currentColor;
  background:transparent; color:var(--fc,#888); cursor:pointer;
  font-size:12px; font-weight:500; transition:all .15s
}}
.filter-btn:hover,.filter-btn.active{{ background:var(--fc,#888); color:#fff }}
.filter-btn[data-flag="all"]{{ color:#94a3b8; border-color:#94a3b8 }}
.filter-btn[data-flag="all"].active{{ background:#334155; color:#f1f5f9 }}

/* ── Sort ── */
.sort-row{{ display:flex; gap:8px; align-items:center }}
.sort-row select{{
  background:#334155; color:#e2e8f0; border:1px solid #475569;
  border-radius:6px; padding:4px 8px; font-size:13px
}}

/* ── Grid ── */
.grid{{ display:grid;
  grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:12px; padding:16px 24px; }}

/* ── Card ── */
.card{{
  background:#1e293b; border-radius:10px; overflow:hidden;
  border:2px solid transparent; transition:border-color .15s;
  cursor:pointer; user-select:none;
}}
.card.selected{{ border-color:#6366f1 }}
.card.hidden{{ display:none }}
.thumb-wrap{{ position:relative; aspect-ratio:4/3; background:#0f172a; overflow:hidden }}
.thumb-wrap img{{ width:100%; height:100%; object-fit:cover; display:block;
                  transition:opacity .2s; opacity:.92 }}
.card.selected .thumb-wrap img{{ opacity:1 }}
.check-badge{{
  position:absolute; top:8px; right:8px; width:22px; height:22px;
  border-radius:50%; background:#1e293b; border:2px solid #64748b;
  display:flex; align-items:center; justify-content:center;
  transition:all .15s;
}}
.card.selected .check-badge{{ background:#6366f1; border-color:#6366f1 }}
.check-badge svg{{ display:none }}
.card.selected .check-badge svg{{ display:block }}
.score-badge{{
  position:absolute; bottom:8px; left:8px; padding:2px 8px;
  border-radius:99px; font-size:11px; font-weight:700;
  backdrop-filter:blur(4px);
}}
.conf-badge{{
  position:absolute; bottom:8px; right:8px; padding:2px 8px;
  border-radius:99px; font-size:11px; font-weight:700;
  backdrop-filter:blur(4px);
}}

/* ── Card body ── */
.card-body{{ padding:10px 12px }}
.card-style{{ font-size:11px; color:#94a3b8; text-transform:uppercase;
             letter-spacing:.05em; margin-bottom:4px }}
.card-meta{{ font-size:11px; color:#64748b; margin-bottom:6px }}
.flags{{ display:flex; flex-wrap:wrap; gap:4px }}
.flag-tag{{
  padding:2px 7px; border-radius:4px; font-size:10px; font-weight:600;
  color:#fff;
}}

/* ── Sticky bottom bar ── */
.bottom-bar{{
  position:fixed; bottom:0; left:0; right:0;
  background:#1e293b; border-top:1px solid #334155;
  padding:12px 24px; display:flex; align-items:center; gap:12px;
  z-index:200;
}}
.bottom-bar .count{{ font-size:14px; color:#94a3b8 }}
.bottom-bar .count b{{ color:#f1f5f9 }}
.btn{{
  padding:8px 18px; border-radius:8px; border:none; cursor:pointer;
  font-size:13px; font-weight:600; transition:all .15s
}}
.btn-primary{{ background:#6366f1; color:#fff }}
.btn-primary:hover{{ background:#4f46e5 }}
.btn-danger{{ background:#ef4444; color:#fff }}
.btn-danger:hover{{ background:#dc2626 }}
.btn-ghost{{ background:#334155; color:#e2e8f0 }}
.btn-ghost:hover{{ background:#475569 }}
.copy-output{{
  flex:1; background:#0f172a; border:1px solid #334155; border-radius:6px;
  padding:6px 10px; font-size:12px; font-family:monospace; color:#94a3b8;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}

/* scrollbar */
::-webkit-scrollbar{{ width:6px; height:6px }}
::-webkit-scrollbar-track{{ background:#0f172a }}
::-webkit-scrollbar-thumb{{ background:#334155; border-radius:3px }}

body{{ padding-bottom:64px }}

/* ── AI Review Panel ── */
.ai-panel{{ border-top:1px solid #1e293b }}
.ai-toggle{{
  width:100%; background:none; border:none; color:#475569;
  padding:6px 12px; font-size:11px; cursor:pointer;
  text-align:left; display:flex; justify-content:space-between;
  align-items:center; transition:color .15s; gap:4px
}}
.ai-toggle:hover{{ color:#94a3b8; background:#ffffff08 }}
.ai-toggle.has-data{{ color:#818cf8 }}
.ai-content{{ display:none; padding:8px 12px; flex-direction:column; gap:6px }}
.ai-content.open{{ display:flex }}
.ai-row{{ display:flex; align-items:center; gap:6px }}
.ai-lbl{{ font-size:10px; color:#64748b; width:46px; flex-shrink:0 }}
.ai-sel{{
  flex:1; background:#0f172a; border:1px solid #334155;
  color:#e2e8f0; border-radius:4px; padding:3px 6px; font-size:11px
}}
.ai-conf{{ font-size:10px; color:#64748b; white-space:nowrap }}
.suggest-chip{{
  background:transparent; border:1px solid #334155; color:#94a3b8;
  border-radius:99px; padding:2px 9px; font-size:10px; cursor:pointer;
}}
.suggest-chip:hover{{ border-color:#6366f1; color:#c7d2fe }}
.suggest-chip.current{{ background:#6366f1; border-color:#6366f1; color:#fff }}
.ai-caption{{
  width:100%; background:#0f172a; border:1px solid #334155;
  color:#cbd5e1; border-radius:4px; padding:4px 6px;
  font-size:11px; resize:vertical; min-height:56px; font-family:inherit
}}
.ai-actions{{ display:flex; gap:6px; margin-top:2px }}
.btn-ai-save{{
  flex:1; background:#6366f1; color:#fff; border:none;
  border-radius:4px; padding:5px; font-size:11px; cursor:pointer
}}
.btn-ai-save:hover{{ background:#4f46e5 }}
.btn-ai-accept{{
  background:#059669; color:#fff; border:none;
  border-radius:4px; padding:5px 8px; font-size:11px;
  cursor:pointer; white-space:nowrap
}}
.btn-ai-accept:hover{{ background:#047857 }}
.no-ai-label{{ font-size:11px; color:#334155; padding:6px 12px }}
</style>
</head>
<body>

<div class="header">
  <h1>DesignBridge 圖片品質審查</h1>
  <span class="stat">顯示 <b id="total-count">0</b> 張</span>
  <span class="stat">已選 <b id="sel-count">0</b> 張</span>
  <span class="stat" style="margin-left:auto;font-size:11px;color:#475569">
    生成於 {generated_at}
  </span>
</div>

<div class="style-tabs">
  <label>風格：</label>
  <button class="style-btn active" data-style="all">全部風格</button>
  {style_btns_html}
</div>

<div class="filters">
  <label>問題篩選：</label>
  <button class="filter-btn active" data-flag="all">全部</button>
  {flag_options_html}
  <div class="sort-row" style="margin-left:auto">
    <label style="font-size:13px;color:#94a3b8">排序：</label>
    <select id="sort-select">
      <option value="score-asc">分數低→高</option>
      <option value="score-desc">分數高→低</option>
      <option value="conf-asc">AI 信心低→高</option>
      <option value="conf-desc">AI 信心高→低</option>
      <option value="style">風格</option>
    </select>
  </div>
</div>

<div class="grid" id="grid"></div>

<div class="bottom-bar">
  <span class="count">已選 <b id="bot-count">0</b> 張</span>
  <button class="btn btn-ghost" onclick="selectAll()">全選目前顯示</button>
  <button class="btn btn-ghost" onclick="deselectAll()">取消全選</button>
  <button class="btn btn-primary" onclick="copyIds()">複製選中 IDs</button>
  <input class="copy-output" id="copy-output" readonly
         placeholder="複製後貼到 purge_rejected.py --ids 後面">
  <button class="btn btn-danger" onclick="copyPurgeCmd()">複製刪除指令</button>
  <button class="btn btn-danger" onclick="deleteSelected()">直接刪除（永久，不能復原）</button>
</div>

<script>
let CARDS = {cards_json};
const FLAG_LABELS = {flag_labels_json};

let activeFlag = "all";
let activeStyle = "all";
let visibleIds = new Set();
let selectedIds = new Set();

function thumbUrl(url) {{
  return url;
}}

function scoreColor(s) {{
  if (s >= 0.8) return "#22c55e";
  if (s >= 0.5) return "#f59e0b";
  return "#ef4444";
}}

function renderGrid() {{
  const sort = document.getElementById("sort-select").value;
  let data = [...CARDS];

  if (activeStyle !== "all")
    data = data.filter(c => (c.style || "other") === activeStyle);
  if (activeFlag !== "all")
    data = data.filter(c => c.flags.includes(activeFlag));

  if (sort === "score-asc")  data.sort((a,b) => a.score - b.score);
  if (sort === "score-desc") data.sort((a,b) => b.score - a.score);
  if (sort === "style")      data.sort((a,b) => a.style.localeCompare(b.style));
  // 沒有 ai_style_confidence 的圖（還沒跑過 AI 判斷）固定排最後，不管哪個方向
  if (sort === "conf-asc")
    data.sort((a,b) => (a.confidence ?? 999) - (b.confidence ?? 999));
  if (sort === "conf-desc")
    data.sort((a,b) => (b.confidence ?? -999) - (a.confidence ?? -999));

  visibleIds = new Set(data.map(c => c.id));
  document.getElementById("total-count").textContent = data.length;

  const grid = document.getElementById("grid");
  grid.innerHTML = "";

  data.forEach(card => {{
    const isSel = selectedIds.has(card.id);
    const flagsHtml = card.flags.map(f => {{
      const info = FLAG_LABELS[f] || {{label: f, color:"#888"}};
      return `<span class="flag-tag" style="background:${{info.color}}">${{info.label}}</span>`;
    }}).join("");

    const div = document.createElement("div");
    div.className = "card" + (isSel ? " selected" : "");
    div.dataset.id = card.id;
    div.innerHTML = `
      <div class="thumb-wrap">
        <img src="${{thumbUrl(card.url)}}" loading="lazy" alt="${{card.style}}"
             onerror="this.style.display='none'">
        <div class="check-badge">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M2 6l3 3 5-5" stroke="#fff" stroke-width="2"
                  stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
        <span class="score-badge"
              style="background:${{scoreColor(card.score)}}22;color:${{scoreColor(card.score)}};
                     border:1px solid ${{scoreColor(card.score)}}44">
          ${{card.score.toFixed(2)}}
        </span>
        ${{card.confidence != null ? `
        <span class="conf-badge" title="${{card.mismatchReason || 'AI 風格符合信心'}}"
              style="background:${{scoreColor(card.confidence)}}22;color:${{scoreColor(card.confidence)}};
                     border:1px solid ${{scoreColor(card.confidence)}}44">
          AI ${{Math.round(card.confidence*100)}}%
        </span>` : ""}}
      </div>
      <div class="card-body">
        <div class="card-style">${{card.style}} · ${{card.orient}}</div>
        <div class="card-meta">${{card.w}}×${{card.h}} · ${{card.kb}}KB
          ${{card.lap !== "" ? "· blur=" + card.lap : ""}}</div>
        <div class="flags">${{flagsHtml}}</div>
      </div>`;

    div.addEventListener("click", () => toggleCard(card.id));
    grid.appendChild(div);
    div.appendChild(buildAIPanel(card));
  }});

  updateCount();
}}

function toggleCard(id) {{
  if (selectedIds.has(id)) selectedIds.delete(id);
  else selectedIds.add(id);
  const el = document.querySelector(`.card[data-id="${{id}}"]`);
  if (el) el.classList.toggle("selected", selectedIds.has(id));
  updateCount();
}}

function selectAll() {{
  visibleIds.forEach(id => selectedIds.add(id));
  document.querySelectorAll(".card").forEach(el => {{
    if (visibleIds.has(el.dataset.id)) el.classList.add("selected");
  }});
  updateCount();
}}

function deselectAll() {{
  selectedIds.clear();
  document.querySelectorAll(".card").forEach(el => el.classList.remove("selected"));
  updateCount();
}}

function updateCount() {{
  const n = selectedIds.size;
  document.getElementById("sel-count").textContent = n;
  document.getElementById("bot-count").textContent = n;
}}

function copyIds() {{
  const ids = [...selectedIds].join(",");
  navigator.clipboard.writeText(ids).catch(() => {{}});
  document.getElementById("copy-output").value = ids || "（尚未選取）";
}}

function copyPurgeCmd() {{
  const ids = [...selectedIds].join(",");
  if (!ids) {{ alert("請先選取要刪除的圖片"); return; }}
  const cmd = `python -m style_kb.collection.purge_rejected --ids ${{ids}}`;
  navigator.clipboard.writeText(cmd).catch(() => {{}});
  document.getElementById("copy-output").value = cmd;
}}

async function deleteSelected() {{
  const ids = [...selectedIds];
  if (!ids.length) {{ alert("請先選取要刪除的圖片"); return; }}
  if (!confirm(`確定要永久刪除這 ${{ids.length}} 張圖片嗎？會同時刪除 Storage 檔案跟資料庫紀錄，無法復原。`)) return;

  let ok = 0, fail = 0;
  for (const id of ids) {{
    try {{
      const r = await fetch("/delete", {{
        method: "POST", headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{ id }}),
      }});
      const j = await r.json();
      if (j.ok) ok++; else fail++;
    }} catch (e) {{ fail++; }}
  }}

  CARDS = CARDS.filter(c => !ids.includes(c.id));
  selectedIds.clear();
  updateCount();
  renderGrid();
  alert(`刪除完成：成功 ${{ok}} 張，失敗 ${{fail}} 張`);
}}

// ── AI Panel ─────────────────────────────────────────────────────────────────
const SPACE_OPT = ["客廳","臥室","廚房","浴室","餐廳","書房","走道","玄關","陽台","辦公室","其他"];
const STYLE_OPT = ["modern","nordic","japanese","industrial","american","classic","luxury","country","other"];
const STYLE_ZH2 = {{modern:"現代",nordic:"北歐",japanese:"日式",industrial:"工業",american:"美式",classic:"古典",luxury:"奢華",country:"鄉村",other:"其他"}};
const aiState = {{}};

function buildAIPanel(card) {{
  const wrap = document.createElement("div");
  wrap.className = "ai-panel";
  wrap.addEventListener("click", e => e.stopPropagation());

  if (!card.hasAI) {{
    const lbl = document.createElement("span");
    lbl.className = "no-ai-label";
    lbl.textContent = "尚未 AI 標記";
    wrap.appendChild(lbl);
    return wrap;
  }}

  aiState[card.id] = {{ caption_en2: card.caption, space: card.spaceType, style_id: card.aiStyle }};

  const parts = [STYLE_ZH2[card.aiStyle]||card.aiStyle, card.spaceType].filter(Boolean).join(" · ");
  const toggle = document.createElement("button");
  toggle.className = "ai-toggle has-data";
  toggle.innerHTML = `<span>AI · ${{parts}}</span><span style="font-size:9px">▾</span>`;
  const content = document.createElement("div");
  content.className = "ai-content";
  toggle.onclick = () => content.classList.toggle("open");
  wrap.appendChild(toggle);

  // Space row
  const spaceRow = document.createElement("div");
  spaceRow.className = "ai-row";
  const spLbl = document.createElement("span"); spLbl.className = "ai-lbl"; spLbl.textContent = "空間";
  const spSel = document.createElement("select"); spSel.className = "ai-sel";
  SPACE_OPT.forEach(s => {{ const o = document.createElement("option"); o.value=s; o.textContent=s; if(s===card.spaceType) o.selected=true; spSel.appendChild(o); }});
  spSel.onchange = () => aiState[card.id].space = spSel.value;
  spaceRow.appendChild(spLbl); spaceRow.appendChild(spSel);
  content.appendChild(spaceRow);

  // AI Style row
  const styleRow = document.createElement("div");
  styleRow.className = "ai-row";
  const stLbl = document.createElement("span"); stLbl.className = "ai-lbl"; stLbl.textContent = "AI 風格";
  const stSel = document.createElement("select"); stSel.className = "ai-sel";
  STYLE_OPT.forEach(s => {{ const o = document.createElement("option"); o.value=s; o.textContent=STYLE_ZH2[s]||s; if(s===card.aiStyle) o.selected=true; stSel.appendChild(o); }});
  stSel.onchange = () => aiState[card.id].style_id = stSel.value;
  const confSpan = document.createElement("span"); confSpan.className = "ai-conf";
  confSpan.textContent = card.confidence != null ? Math.round(card.confidence*100)+"%" : "";
  if (card.mismatchReason) confSpan.title = card.mismatchReason;
  styleRow.appendChild(stLbl); styleRow.appendChild(stSel); styleRow.appendChild(confSpan);
  content.appendChild(styleRow);

  // AI 建議風格（點一下直接套用到上面的下拉選單，不用自己找）
  if (card.suggestedStyles && card.suggestedStyles.length) {{
    const sugRow = document.createElement("div");
    sugRow.className = "ai-row";
    const sugLbl = document.createElement("span"); sugLbl.className = "ai-lbl"; sugLbl.textContent = "AI 建議";
    sugRow.appendChild(sugLbl);
    card.suggestedStyles.forEach(s => {{
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "suggest-chip" + (s === card.aiStyle ? " current" : "");
      chip.textContent = STYLE_ZH2[s] || s;
      chip.onclick = () => {{ stSel.value = s; aiState[card.id].style_id = s;
        sugRow.querySelectorAll(".suggest-chip").forEach(c => c.classList.toggle("current", c===chip)); }};
      sugRow.appendChild(chip);
    }});
    content.appendChild(sugRow);
  }}

  // Caption textarea
  const ta = document.createElement("textarea");
  ta.className = "ai-caption"; ta.rows = 3; ta.value = card.caption || "";
  ta.oninput = () => aiState[card.id].caption_en2 = ta.value;
  content.appendChild(ta);

  // Action buttons
  const actions = document.createElement("div");
  actions.className = "ai-actions";

  const saveBtn = document.createElement("button");
  saveBtn.className = "btn-ai-save";
  saveBtn.textContent = "儲存";
  saveBtn.onclick = async () => {{
    saveBtn.disabled = true; saveBtn.textContent = "儲存中...";
    const ok = await doSaveAI(card.id);
    saveBtn.textContent = ok ? "✓ 已儲存" : "❌ 失敗";
    setTimeout(() => {{ saveBtn.textContent = "儲存"; saveBtn.disabled = false; }}, 1500);
  }};

  actions.appendChild(saveBtn);
  content.appendChild(actions);
  wrap.appendChild(content);
  return wrap;
}}

async function doSaveAI(id) {{
  const state = aiState[id];
  if (!state) return false;
  try {{
    const r = await fetch("/save", {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ id, ...state }}),
    }});
    return (await r.json()).ok;
  }} catch(e) {{ console.error("save error:", e); return false; }}
}}

// Style tabs
document.querySelectorAll(".style-btn").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".style-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeStyle = btn.dataset.style;
    renderGrid();
  }});
}});

// Flag filter buttons
document.querySelectorAll(".filter-btn").forEach(btn => {{
  btn.addEventListener("click", () => {{
    document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    activeFlag = btn.dataset.flag;
    renderGrid();
  }});
}});

document.getElementById("sort-select").addEventListener("change", renderGrid);

renderGrid();
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成圖片品質審查 HTML")
    parser.add_argument("--out",   type=str, default="review.html", help="輸出 HTML 路徑")
    parser.add_argument("--style", type=str, default=None, help="只看指定風格")
    parser.add_argument("--flagged-only", action="store_true", help="只顯示有問題的圖（quality_score < 1.0）")
    parser.add_argument("--open",  action="store_true", help="生成後自動開啟瀏覽器")
    args = parser.parse_args()

    print("從 Supabase 拉取資料...")
    rows = fetch_rows(args.style, show_all=not args.flagged_only)
    db_counts = fetch_style_counts()
    print(f"共 {len(rows)} 筆圖片，DB 各風格總數：{db_counts}")

    if not rows:
        print("沒有需要審查的圖片（可能還沒跑 quality_filter_supabase）")
        return

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = build_html(rows, generated_at, db_counts)

    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 審查頁面已生成：{out_path.resolve()}")
    print(f"   用瀏覽器開啟後，勾選要刪除的圖片，點「複製刪除指令」")

    if args.open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    main()
