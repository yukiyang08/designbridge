"""換風格 A/B 實測：同一 plan／seed 下比較 ControlNet 與 img2img，輸出 docs/style_swap_ab/。

會呼叫 fal（有費用）：2 張基準圖 + 5 組 × 3 種方法 = 17 次生成。
用法：PYTHONUTF8=1 python scripts/ab_style_swap.py [--report-only]
"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

OUT = ROOT / "docs" / "style_swap_ab"
IMG = OUT / "images"
RAW = OUT / "results.json"
SEED = 42
STRENGTH = 0.85
CN_BACKEND = "flux_controlnet_depth_fal"

LAYOUT_PROMPT = (
    "客廳,約 5 公尺寬、4 公尺深。沙發靠左側牆面,面向右牆;電視櫃靠右側牆,位在沙發正對面;"
    "茶几放在沙發與電視櫃之間的中央;沙發右側放一張邊几,電視櫃旁邊放一盆盆栽。"
    "窗戶在正對面的牆上,保持窗前和中央走道淨空。"
)
BASES = {
    "A": dict(label="文字＋家具位置（投影深度）", kw=dict(
        text_prompt=LAYOUT_PROMPT, style_profile_id="modern", seed=SEED, output_aspect="16:9")),
    "B": dict(label="真實照片（照片深度）", kw=dict(
        text_prompt="明亮的客廳", style_profile_id="modern", seed=SEED, output_aspect="auto",
        initial_image_path="frontend/src/assets/rooms/living_room.jpg")),
}
GROUPS = [("A", "industrial"), ("A", "luxury"), ("A", "country"), ("B", "industrial"), ("B", "luxury")]
METHODS = {
    "cn_lora": ("ControlNet（正式，含風格 LoRA）", {}),
    "cn_nolora": ("ControlNet（無 LoRA）", {"disable_lora": True}),
    "i2i": (f"img2img {STRENGTH}（無 LoRA）", {"img2img_strength_override": STRENGTH}),
}
STYLE_ZH = {"industrial": "工業風", "luxury": "奢華風", "country": "鄉村風"}
TIMING = re.compile(r"\[timing\](?:\[[^\]]*\])? ([\w.]+): ([\d.]+)s")
NODES = ["requirement_analyzer", "visual_preprocessing", "layout_and_style_agent", "composer", "renderer", "clip_evaluator"]


class Tee:
    """同時印到終端機並留一份，之後依呼叫切出各階段 [timing] 行。"""
    def __init__(self, stream):
        self.stream, self.buf = stream, []

    def write(self, s):
        self.stream.write(s)
        self.buf.append(s)
        return len(s)

    def flush(self):
        self.stream.flush()


def thumb(src, name):
    im = Image.open(src).convert("RGB")
    im.thumbnail((800, 800))
    im.save(IMG / f"{name}.jpg", quality=85)
    return f"images/{name}.jpg"


def _depth(path):
    from designbridge.core.config import Config
    from designbridge.layout.vision import run_depth_estimation
    p, _ = run_depth_estimation(str(path), model_name=Config.DEPTH_MODEL, out_dir=Path(tempfile.gettempdir()) / "ab_depth")
    return np.asarray(Image.open(p).convert("L").resize((256, 144)), dtype=float)


def metrics(base, res):
    """結構相關：兩張圖深度圖的 Pearson 相關；像素變化：RGB 平均絕對差 / 255。皆為輔助指標。"""
    corr = float(np.corrcoef(_depth(base).ravel(), _depth(res).ravel())[0, 1])
    rgb = lambda p: np.asarray(Image.open(p).convert("RGB").resize((256, 144)), dtype=float)
    return corr, float(np.abs(rgb(base) - rgb(res)).mean() / 255)


def run():
    tee = Tee(sys.stdout)
    sys.stdout = tee
    import routers.generate as G
    from routers.common import DesignRequest
    G._save_history = lambda *a, **k: None   # 不污染使用者的歷史紀錄

    def call(kw):
        mark, t0 = len(tee.buf), time.perf_counter()
        try:
            resp, err = G.generate_design(DesignRequest(**kw)), None
        except Exception as e:
            resp, err = None, str(e)
        wall = time.perf_counter() - t0
        timings = {}
        for lab, sec in TIMING.findall("".join(tee.buf[mark:])):
            timings[lab] = timings.get(lab, 0) + float(sec)
        if not resp:
            return None, dict(error=err, wall=wall, timings=timings)
        gp = (resp.get("render_result") or {}).get("generation_params") or {}
        return resp, dict(
            path=resp["generated_image_path"], backend=gp.get("backend"), elapsed=float(resp["elapsed_time"].rstrip("s")),
            wall=wall, timings=timings, depth_scale=gp.get("depth_conditioning_scale"), strength=gp.get("img2img_strength"),
            loras=[l["path"].rsplit("/", 1)[-1] for l in gp.get("loras") or []], seed=gp.get("seed"), prompt=gp.get("prompt_preview"),
        )

    data = dict(config=dict(seed=SEED, strength=STRENGTH, started=time.strftime("%Y-%m-%d %H:%M:%S")), bases={}, groups=[])
    save = lambda: RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    IMG.mkdir(parents=True, exist_ok=True)
    full = {}
    for k, b in BASES.items():
        print(f"\n@@ 基準圖 {k}：{b['label']}")
        full[k], r = call(b["kw"])
        if "path" in r:
            r["img"] = thumb(r["path"], f"base_{k}")
        data["bases"][k] = dict(label=b["label"], **r)
        save()
    bad = [k for k, v in data["bases"].items() if v.get("backend") != CN_BACKEND]
    if bad:
        print(f"@@ BASE_NOT_CONTROLNET {bad}：基準圖沒走 ControlNet，中止（見 {RAW}）")
        sys.exit(2)

    for bk, style in GROUPS:
        base = full[bk]
        plan = {k: v for k, v in base.items() if k != "style_params"}   # 與前端 swapStyle 一致
        g = dict(base=bk, style=style, runs={})
        data["groups"].append(g)
        for mk, (label, extra) in METHODS.items():
            print(f"\n@@ {bk}/{style}/{mk}")
            kw = dict(text_prompt="", style_profile_id=style, output_aspect=BASES[bk]["kw"]["output_aspect"], plan=plan, **extra)
            if mk == "i2i":
                kw["img2img_base_image_override"] = base["generated_image_path"]
            _, r = call(kw)
            if "path" in r:
                r["img"] = thumb(r["path"], f"{bk}_{style}_{mk}")
                r["corr"], r["diff"] = metrics(base["generated_image_path"], r["path"])
            g["runs"][mk] = dict(label=label, **r)
            save()
    print("@@ DONE")


def build_report():
    d = json.loads(RAW.read_text(encoding="utf-8"))
    s = lambda x: "—" if x is None else f"{x:.1f}s"
    t = lambda r, k: s(r.get("timings", {}).get(k))
    img = lambda r: f'<img src="{r["img"]}" width="300">' if r.get("img") else f'失敗：{r.get("error", "?")}'
    L = ["# 換風格 A/B 實測：ControlNet vs img2img", "",
         f"測試時間：{d['config']['started']}　seed：{d['config']['seed']}　img2img 強度：{d['config']['strength']}", "",
         "## 1. 測試設定", "",
         "- 每組在**同一張基準圖、同一個 plan、同一個 seed、同一份新版換風格 prompt**下，只換「生圖方法」。",
         "- ControlNet：fal `flux-general` + Depth ControlNet + Canny 邊緣；強度由程式上限決定（投影深度 0.3、照片深度 ≤0.65）。",
         "- img2img：fal `flux-general/image-to-image`，以基準圖為起始圖，prompt 只靠 `_STYLE_LOOK` 描述。",
         "- 「ControlNet（正式）」含該風格的 LoRA，是目前上線的做法；「無 LoRA」與 img2img 的條件一致，是公平比較的主組。",
         "- 結構相關 / 像素變化是輔助指標：前者越高代表與基準圖的空間結構越接近，後者越高代表畫面改變越多。不能取代肉眼判斷。",
         "- 耗時來自後端 `[timing]` 紀錄；「總耗時」是整段 `/api/generate`，渲染節點內含生圖呼叫與補跑深度。", ""]
    L += ["## 2. 基準圖", "", "| 基準 | 說明 | 圖 | backend | 總耗時 |", "|---|---|---|---|---|"]
    for k, b in d["bases"].items():
        L.append(f"| {k} | {b['label']}（現代風） | {img(b)} | {b.get('backend', '—')} | {s(b.get('elapsed'))} |")
    L += ["", "## 3. 五組結果", ""]
    for i, g in enumerate(d["groups"], 1):
        runs, base = g["runs"], d["bases"][g["base"]]
        cols = list(runs.values())
        L += [f"### 組 {i}：基準 {g['base']}（{base['label']}）→ {STYLE_ZH[g['style']]}", "",
              "| 項目 | 基準圖 | " + " | ".join(r["label"] for r in cols) + " |", "|---|---|" + "---|" * len(cols)]
        row = lambda name, first, f: L.append(f"| {name} | {first} | " + " | ".join(f(r) for r in cols) + " |")
        row("圖片", img(base), img)
        row("backend", "", lambda r: r.get("backend", "—"))
        row("總耗時", "", lambda r: s(r.get("elapsed")))
        row("渲染節點", "", lambda r: t(r, "renderer"))
        row("　└ 生圖呼叫", "", lambda r: s(next((v for k, v in r.get("timings", {}).items() if k.startswith("renderer.flux")), None)))
        row("　└ 補跑深度", "", lambda r: t(r, "renderer.post_depth_estimation"))
        row("風格/合成節點", "", lambda r: s(sum(r.get("timings", {}).get(k, 0) for k in ("layout_and_style_agent", "composer")) or None))
        row("CLIP 評分", "", lambda r: t(r, "clip_evaluator"))
        row("結構相關（↑越像）", "", lambda r: "—" if "corr" not in r else f"{r['corr']:.2f}")
        row("像素變化（↑改變多）", "", lambda r: "—" if "diff" not in r else f"{r['diff']:.2f}")
        row("參數", "", lambda r: f"深度強度 {r['depth_scale']}" if r.get("depth_scale") is not None else f"strength {r.get('strength')}")
        row("LoRA", "", lambda r: ", ".join(r.get("loras") or []) or "無")
        L.append("")
    # 各階段耗時彙總（5 組平均）
    ms = list(METHODS)
    inner = sorted({k for g in d["groups"] for r in g["runs"].values() for k in r.get("timings", {}) if k.startswith("renderer.")})
    L += ["## 4. 各階段耗時彙總（5 組平均）", "", "| 階段 | " + " | ".join(METHODS[m][0] for m in ms) + " |", "|---|" + "---|" * len(ms)]
    def avg(m, k):
        v = [g["runs"][m]["timings"][k] for g in d["groups"] if m in g["runs"] and k in g["runs"][m].get("timings", {})]
        return s(sum(v) / len(v)) if v else "—"
    tot = lambda m: [g["runs"][m]["elapsed"] for g in d["groups"] if g["runs"].get(m, {}).get("elapsed")]
    L.append("| 總耗時 | " + " | ".join(s(sum(tot(m)) / len(tot(m)) if tot(m) else None) for m in ms) + " |")
    for k in NODES:
        L.append(f"| {k} | " + " | ".join(avg(m, k) for m in ms) + " |")
    for k in inner:
        L.append(f"| 　└ {k} | " + " | ".join(avg(m, k) for m in ms) + " |")
    L += ["", "## 5. 觀察與結論", "", "<!--OBS-->", "", "## 附錄：實際送出的 prompt（第 1 組）", ""]
    for r in d["groups"][0]["runs"].values():
        L += [f"**{r['label']}**", "", "```", (r.get("prompt") or "(無)").strip(), "```", ""]
    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    print(f"報告：{OUT / 'report.md'}")


if __name__ == "__main__":
    if "--report-only" not in sys.argv:
        run()
    build_report()
