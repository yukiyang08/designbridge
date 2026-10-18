"""img2img 參數掃描：負向 prompt／步數／guidance 能否把風格推上去，輸出 docs/experiments/style_swap_ab/params_report.md。

會呼叫 fal（有費用）：1 張基準圖 + 2 風格 × 6 種條件 = 13 次生成。
用法：PYTHONUTF8=1 python scripts/ab_img2img_params.py [--report-only]
"""
import json
import sys
import time

from ab_style_swap import BASES, CN_BACKEND, OUT, SEED, STRENGTH, STYLE_ZH, TIMING, Tee, metrics
from PIL import Image

IMG = OUT / "params_images"
RAW = OUT / "params_results.json"
STYLES = ["industrial", "luxury"]
NEG = {
    "industrial": "white walls, bright daylight, light beige fabric sofa, airy pastel room, bright white curtains",
    "luxury": "plain white walls, casual minimalist decor, light beige fabric sofa, bare plain ceiling, rustic wood",
}
STEPS, CFG = 28, 5.5
VARIANTS = {   # key: (標籤, 是否 img2img, 額外參數 builder)
    "cn_ref": ("ControlNet 參考（無 LoRA）", lambda s: {"disable_lora": True}),
    "i2i_base": (f"img2img {STRENGTH}（原設定）", lambda s: {}),
    "i2i_neg": ("＋負向 prompt", lambda s: {"img2img_negative_prompt_override": NEG[s]}),
    "i2i_steps": (f"步數 {STEPS}", lambda s: {"img2img_steps_override": STEPS}),
    "i2i_cfg": (f"guidance {CFG}", lambda s: {"img2img_guidance_override": CFG}),
    "i2i_all": ("三者合用", lambda s: {"img2img_negative_prompt_override": NEG[s],
                                     "img2img_steps_override": STEPS, "img2img_guidance_override": CFG}),
}


def thumb(src, name):
    im = Image.open(src).convert("RGB")
    im.thumbnail((800, 800))
    im.save(IMG / f"{name}.jpg", quality=85)
    return f"params_images/{name}.jpg"


def run():
    tee = Tee(sys.stdout)
    sys.stdout = tee
    import routers.generate as G
    from routers.common import DesignRequest
    G._save_history = lambda *a, **k: None   # 不污染歷史紀錄

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
            return None, dict(error=err, timings=timings)
        gp = (resp.get("render_result") or {}).get("generation_params") or {}
        return resp, dict(path=resp["generated_image_path"], backend=gp.get("backend"), elapsed=float(resp["elapsed_time"].rstrip("s")),
                          timings=timings, seed=gp.get("seed"), strength=gp.get("img2img_strength"), prompt=gp.get("prompt_preview"),
                          steps=gp.get("img2img_num_steps"), guidance=gp.get("img2img_guidance_scale"),
                          negative=gp.get("img2img_negative_prompt"), depth_scale=gp.get("depth_conditioning_scale"))

    data = dict(config=dict(seed=SEED, strength=STRENGTH, steps=STEPS, cfg=CFG, neg=NEG, started=time.strftime("%Y-%m-%d %H:%M:%S")), groups=[])
    save = lambda: RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    IMG.mkdir(parents=True, exist_ok=True)
    b = BASES["A"]
    print("\n@@ 基準圖 A")
    base, br = call(b["kw"])
    if "path" not in br or br.get("backend") != CN_BACKEND:
        print(f"@@ BASE_FAIL {br}")
        sys.exit(2)
    br["img"] = thumb(br["path"], "base_A")
    data["base"] = dict(label=b["label"], **br)
    save()
    plan = {k: v for k, v in base.items() if k != "style_params"}
    for style in STYLES:
        g = dict(style=style, runs={})
        data["groups"].append(g)
        for vk, (label, extra) in VARIANTS.items():
            print(f"\n@@ {style}/{vk}")
            kw = dict(text_prompt="", style_profile_id=style, output_aspect="16:9", plan=plan, **extra(style))
            if vk != "cn_ref":
                kw.update(img2img_base_image_override=base["generated_image_path"], img2img_strength_override=STRENGTH, seed=SEED)
            _, r = call(kw)
            if "path" in r:
                r["img"] = thumb(r["path"], f"{style}_{vk}")
                r["corr"], r["diff"] = metrics(base["generated_image_path"], r["path"])
            g["runs"][vk] = dict(label=label, **r)
            save()
    print("@@ DONE")


def build_report():
    d = json.loads(RAW.read_text(encoding="utf-8"))
    s = lambda x: "—" if x is None else f"{x:.1f}s"
    img = lambda r: f'<img src="{r["img"]}" width="260">' if r.get("img") else f'失敗：{r.get("error", "?")}'
    c = d["config"]
    L = ["# img2img 參數掃描：負向 prompt／步數／guidance", "",
         f"測試時間：{c['started']}　seed：{c['seed']}（img2img 組這次有真正送給 fal）　strength：{c['strength']}", "",
         "## 1. 測試設定", "",
         "- 基準圖：文字＋家具位置的現代風客廳（投影深度），重新生成了一張，因此**不能與 report.md 的圖直接比較**。",
         f"- 風格：工業風、奢華風。每種風格各 6 個條件，img2img 組都使用同一張基準圖、同一個 plan、同一個 seed {c['seed']}。",
         f"- 步數預設 20 → 調成 {c['steps']}；guidance 預設 3.5 → 調成 {c['cfg']}；負向 prompt 見下。",
         "- 「ControlNet 參考」只是當作風格強度的目標對照（正式做法、不含 LoRA）。",
         "- 結構相關／像素變化是輔助指標，定義同 report.md。",
         "- 注意：基準 A 的 composer 會用 LLM 合成 prompt，各次措辭略有不同（風格關鍵詞相同）。", ""]
    for k, v in c["neg"].items():
        L.append(f"- 負向 prompt（{STYLE_ZH[k]}）：`{v}`")
    L += ["", "## 2. 基準圖", "", f'<img src="{d["base"]["img"]}" width="360">　耗時 {s(d["base"].get("elapsed"))}、backend {d["base"].get("backend")}', "", "## 3. 結果", ""]
    for g in d["groups"]:
        cols = list(g["runs"].values())
        L += [f"### {STYLE_ZH[g['style']]}", "", "| 項目 | " + " | ".join(r["label"] for r in cols) + " |", "|---|" + "---|" * len(cols)]
        row = lambda name, f: L.append(f"| {name} | " + " | ".join(f(r) for r in cols) + " |")
        row("圖片", img)
        row("backend", lambda r: r.get("backend", "—"))
        row("總耗時", lambda r: s(r.get("elapsed")))
        row("生圖呼叫", lambda r: s(next((v for k, v in r.get("timings", {}).items() if k.startswith("renderer.flux")), None)))
        row("結構相關（↑越像基準）", lambda r: "—" if "corr" not in r else f"{r['corr']:.2f}")
        row("像素變化（↑改變多）", lambda r: "—" if "diff" not in r else f"{r['diff']:.2f}")
        row("步數 / guidance", lambda r: f"{r.get('steps') or 20} / {r.get('guidance') or 3.5}" if r.get("strength") is not None else "—")
        L.append("")
    L += ["## 4. 觀察與結論", "", "<!--OBS-->", ""]
    (OUT / "params_report.md").write_text("\n".join(L), encoding="utf-8")
    print(f"報告：{OUT / 'params_report.md'}")


if __name__ == "__main__":
    if "--report-only" not in sys.argv:
        run()
    build_report()
