"""現行系統各情境生圖耗時：每個情境跑 5 次，輸出 docs/experiments/style_swap_ab/timing_report.md。

會呼叫 fal（有費用）：4 情境 × 5 次 = 20 次生成。直接呼叫 generate_design（不經 HTTP），
並先跑啟動暖機，模擬伺服器已預載模型的狀態。
用法：PYTHONUTF8=1 python scripts/bench_gen_time.py [--report-only]
"""
import json
import statistics as st
import sys
import time

from ab_style_swap import BASES, OUT, TIMING, Tee

RAW = OUT / "timing_results.json"
RUNS = 5
SWAP_STYLES = ["industrial", "luxury", "country", "nordic", "japanese"]
SCENARIOS = {
    "S1": "文字＋家具位置 首次生成（完整流程：需求分析、版面、風格搜尋、composer、渲染、CLIP）",
    "S2": "真實照片 首次生成（含深度估計與分割）",
    "S3": "一鍵換風格（版面基準，ControlNet 正式做法）",
    "S4": "一鍵換風格（照片基準，ControlNet 正式做法）",
}
INNER = ["requirement_analyzer", "visual_preprocessing", "layout_and_style_agent", "composer", "renderer", "clip_evaluator"]


def run():
    tee = Tee(sys.stdout)
    sys.stdout = tee
    import routers.generate as G
    from designbridge.core.warmup import run_startup_warmup
    from routers.common import DesignRequest
    G._save_history = lambda *a, **k: None   # 不污染歷史紀錄
    run_startup_warmup()

    def call(kw):
        mark, t0 = len(tee.buf), time.perf_counter()
        try:
            resp, err = G.generate_design(DesignRequest(**kw)), None
        except Exception as e:
            resp, err = None, str(e)
        timings = {}
        for lab, sec in TIMING.findall("".join(tee.buf[mark:])):
            timings[lab] = timings.get(lab, 0) + float(sec)
        if not resp:
            return None, dict(error=err, timings=timings, wall=time.perf_counter() - t0)
        gp = (resp.get("render_result") or {}).get("generation_params") or {}
        return resp, dict(elapsed=float(resp["elapsed_time"].rstrip("s")), wall=time.perf_counter() - t0,
                          backend=gp.get("backend"), timings=timings, path=resp["generated_image_path"])

    data = dict(started=time.strftime("%Y-%m-%d %H:%M:%S"), runs=RUNS, scenarios={k: dict(desc=v, runs=[]) for k, v in SCENARIOS.items()})
    save = lambda: RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    first = {}
    for sc, base_key in (("S1", "A"), ("S2", "B")):
        for i in range(RUNS):
            print(f"\n@@ {sc} run {i + 1}")
            kw = dict(BASES[base_key]["kw"], seed=100 + i)
            resp, r = call(kw)
            r["note"] = f"seed {100 + i}"
            data["scenarios"][sc]["runs"].append(r)
            if i == 0 and resp:
                first[base_key] = resp
            save()
    for sc, base_key in (("S3", "A"), ("S4", "B")):
        base = first.get(base_key)
        if not base:
            continue
        plan = {k: v for k, v in base.items() if k != "style_params"}
        for i, style in enumerate(SWAP_STYLES[:RUNS]):
            print(f"\n@@ {sc} run {i + 1} {style}")
            _, r = call(dict(text_prompt="", style_profile_id=style, output_aspect=BASES[base_key]["kw"]["output_aspect"], plan=plan))
            r["note"] = style
            data["scenarios"][sc]["runs"].append(r)
            save()
    print("@@ DONE")


def build_report():
    d = json.loads(RAW.read_text(encoding="utf-8"))
    f = lambda x: "—" if x is None else f"{x:.1f}"
    gen = lambda r: next((v for k, v in r["timings"].items() if k.startswith("renderer.flux")), None)
    L = ["# 現行系統生圖耗時實測", "", f"測試時間：{d['started']}　每情境 {d['runs']} 次。單位：秒。", "",
         "## 1. 測試方式", "",
         "- 直接呼叫後端 `generate_design`（不經 HTTP、不含前端），先執行啟動暖機，模擬伺服器已預載本機模型的狀態。",
         "- 全部使用現行正式設定：ControlNet（含風格 LoRA）。首次生成的 seed 為 100–104；換風格依序切到 工業、奢華、鄉村、北歐、日式。",
         "- 換風格的基準圖，是同情境首次生成的第 1 張。",
         "- 耗時來自後端 `[timing]` 紀錄；「生圖呼叫」是 fal 的呼叫時間，「其餘」＝總耗時 − 生圖呼叫。",
         "- fal 的冷啟動與排隊會讓個別次數差異很大，因此同時列出每次的數字與中位數。", "",
         "## 2. 摘要", "", "| 情境 | 說明 | 成功 | 總耗時 中位數 | 最小 | 最大 | 平均 | 生圖呼叫 中位數 | 其餘 中位數 |", "|---|---|---|---|---|---|---|---|---|"]
    for k, sc in d["scenarios"].items():
        ok = [r for r in sc["runs"] if "elapsed" in r]
        if not ok:
            L.append(f"| {k} | {sc['desc']} | 0/{len(sc['runs'])} | — | — | — | — | — | — |")
            continue
        el = [r["elapsed"] for r in ok]
        g = [x for x in (gen(r) for r in ok) if x is not None]
        rest = [r["elapsed"] - gen(r) for r in ok if gen(r) is not None]
        L.append(f"| {k} | {sc['desc']} | {len(ok)}/{len(sc['runs'])} | {st.median(el):.1f} | {min(el):.1f} | {max(el):.1f} | {st.mean(el):.1f} | "
                 f"{f(st.median(g)) if g else '—'} | {f(st.median(rest)) if rest else '—'} |")
    L += ["", "## 3. 每次的數據", ""]
    for k, sc in d["scenarios"].items():
        L += [f"### {k}：{sc['desc']}", "", "| 次 | 備註 | backend | 總耗時 | 生圖呼叫 | 其餘 |", "|---|---|---|---|---|---|"]
        for i, r in enumerate(sc["runs"], 1):
            if "elapsed" not in r:
                L.append(f"| {i} | {r.get('note', '')} | 失敗：{r.get('error', '?')} | — | — | — |")
                continue
            g = gen(r)
            L.append(f"| {i} | {r.get('note', '')} | {r['backend']} | {r['elapsed']:.1f} | {f(g)} | {f(r['elapsed'] - g) if g is not None else '—'} |")
        L.append("")
    L += ["## 4. 各階段耗時（每情境平均）", "", "| 階段 | " + " | ".join(d["scenarios"]) + " |", "|---|" + "---|" * len(d["scenarios"])]
    labels = INNER + sorted({k for sc in d["scenarios"].values() for r in sc["runs"] for k in r.get("timings", {})
                             if k not in INNER and (k.startswith(("renderer.", "visual_preprocessing.", "layout_and_style.", "layout_agent.", "clip_evaluator.")))})
    for lab in labels:
        cells = []
        for sc in d["scenarios"].values():
            v = [r["timings"][lab] for r in sc["runs"] if lab in r.get("timings", {})]
            cells.append(f"{st.mean(v):.1f}" if v else "—")
        if any(c != "—" for c in cells):
            L.append(f"| {'　└ ' if lab not in INNER else ''}{lab} | " + " | ".join(cells) + " |")
    L += ["", "## 5. 觀察", "", "<!--OBS-->", ""]
    (OUT / "timing_report.md").write_text("\n".join(L), encoding="utf-8")
    print(f"報告：{OUT / 'timing_report.md'}")


if __name__ == "__main__":
    if "--report-only" not in sys.argv:
        run()
    build_report()
