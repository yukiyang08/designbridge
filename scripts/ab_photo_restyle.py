"""入口二（改造現有空間）換風格參數掃描：同一張照片、同一個風格，只改深度／邊緣的約束強度。

重現前端 restylePhoto 送的那一包（restyle=True + initial_image_path），逐組改 Config 後呼叫
真正的 /api/generate 函式，量「生出來的圖還像不像原照片」。會呼叫 fal（有費用），每組 1 次生成。

用法（專案根目錄）：
  PYTHONUTF8=1 python scripts/ab_photo_restyle.py [--photo 路徑] [--style industrial] [--report-only]

結果寫進 docs/experiments/PHOTO_RESTYLE_PARAM_TEST.md 的 <!--RESULTS--> 之後。
"""
import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PIL import Image

# 重用換風格 A/B 腳本：stdout 攔截（切 [timing] 行）與「結構相關／像素變化」兩個指標
from ab_style_swap import TIMING, Tee, metrics

OUT = ROOT / "docs" / "experiments"
IMG = OUT / "images" / "photo_restyle"
RAW = IMG / "results.json"
DOC = OUT / "PHOTO_RESTYLE_PARAM_TEST.md"
MARK = "<!--RESULTS-->"
DEFAULT_PHOTO = "frontend/src/assets/rooms/living_room.jpg"

# 四組參數：先各自單獨動一個旋鈕，確認是哪一個在起作用，最後一組才全開
PARAMS = [
    ("P0 現狀", "線上目前的值", dict(cap=0.65, end=0.70, edge=0.30, steps=20)),
    ("P1 提高深度上限", "只動 REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE", dict(cap=0.78, end=0.70, edge=0.30, steps=20)),
    ("P2 延長深度控制", "只動 REAL_PHOTO_DEPTH_CONTROL_END", dict(cap=0.65, end=0.85, edge=0.30, steps=20)),
    ("P3 四項全上", "深度上限＋控制結束＋邊緣強度＋步數", dict(cap=0.78, end=0.85, edge=0.45, steps=28)),
]


def apply_params(p):
    from designbridge.core.config import Config

    Config.REAL_PHOTO_DEPTH_MAX_CONDITIONING_SCALE = p["cap"]
    Config.REAL_PHOTO_DEPTH_CONTROL_END = p["end"]
    Config.EDGE_CONDITIONING_SCALE = p["edge"]
    Config.FAL_CONTROLNET_STEPS = p["steps"]


def thumb(src, name):
    im = Image.open(src).convert("RGB")
    im.thumbnail((800, 800))
    im.save(IMG / f"{name}.jpg", quality=85)
    return f"images/photo_restyle/{name}.jpg"


def ensure_in_artifacts(photo: str) -> str:
    """check_request_paths 只收 artifacts/ 底下的路徑，測試圖先複製進去。"""
    src = Path(photo).resolve()
    if not src.is_file():
        sys.exit(f"找不到照片：{photo}")
    if src.is_relative_to((ROOT / "artifacts").resolve()):
        return str(src)
    dest = ROOT / "artifacts" / "uploads" / f"ab_photo_restyle_{src.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return str(dest)


def run(photo: str, style: str):
    from style_kb.styles import STYLES

    style_zh = dict(STYLES).get(style, style)
    tee = Tee(sys.stdout)
    sys.stdout = tee

    import routers.generate as G
    from routers.common import DesignRequest

    G._save_history = lambda *a, **k: None   # 不污染使用者的歷史紀錄

    def call(params):
        apply_params(params)
        # 跟 photoLayout.js 的 restylePhoto 送的欄位一致：只有描述、風格、底圖、restyle
        req = DesignRequest(
            text_prompt=f"{style_zh}風格的室內設計",
            style_profile_id=style,
            initial_image_path=photo,
            restyle=True,
            output_aspect="auto",
        )
        mark, t0 = len(tee.buf), time.perf_counter()
        try:
            # user_id 給空字串：直接呼叫函式時依賴注入不會執行，空值也跳過管理員檢查
            resp, err = G.generate_design(req, user_id=""), None
        except Exception as e:  # noqa: BLE001
            resp, err = None, str(e)
        wall = time.perf_counter() - t0
        timings = {}
        for lab, sec in TIMING.findall("".join(tee.buf[mark:])):
            timings[lab] = timings.get(lab, 0) + float(sec)
        if not resp:
            return dict(error=err, wall=wall, timings=timings)
        gp = (resp.get("render_result") or {}).get("generation_params") or {}
        return dict(
            path=resp["generated_image_path"], backend=gp.get("backend"), wall=wall, timings=timings,
            elapsed=float(resp["elapsed_time"].rstrip("s")), depth_scale=gp.get("depth_conditioning_scale"),
            control_end=gp.get("controlnet_control_end"), steps=gp.get("controlnet_steps"),
            edge_scale=gp.get("edge_conditioning_scale"), prompt=gp.get("prompt_preview"),
        )

    IMG.mkdir(parents=True, exist_ok=True)
    data = dict(
        config=dict(photo=photo, style=style, style_zh=style_zh, started=time.strftime("%Y-%m-%d %H:%M:%S")),
        base=dict(img=thumb(photo, "base")),
        runs=[],
    )
    save = lambda: RAW.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    save()

    for key, note, params in PARAMS:
        print(f"\n@@ {key}：{params}")
        r = call(params)
        if "path" in r:
            r["img"] = thumb(r["path"], key.split()[0])
            r["corr"], r["diff"] = metrics(photo, r["path"])
        data["runs"].append(dict(key=key, note=note, params=params, **r))
        save()
    print("@@ DONE")


def build_report():
    d = json.loads(RAW.read_text(encoding="utf-8"))
    c = d["config"]
    runs = d["runs"]
    img = lambda r: f'<img src="{r["img"]}" width="280">' if r.get("img") else f'失敗：{r.get("error", "?")}'
    num = lambda v, f="{:.2f}": "—" if v is None else f.format(v)

    L = [f"測試時間：{c['started']}　照片：`{c['photo']}`　風格：{c['style_zh']}（{c['style']}）", "",
         "### 原照片", "", f'<img src="{d["base"]["img"]}" width="280">', "",
         "### 四組結果", "",
         "| 項目 | " + " | ".join(r["key"] for r in runs) + " |",
         "|---|" + "---|" * len(runs)]
    row = lambda name, f: L.append(f"| {name} | " + " | ".join(f(r) for r in runs) + " |")
    row("圖", img)
    row("深度上限 / 控制結束", lambda r: f"{r['params']['cap']} / {r['params']['end']}")
    row("邊緣強度 / 步數", lambda r: f"{r['params']['edge']} / {r['params']['steps']}")
    row("backend", lambda r: r.get("backend") or "—")
    row("實際 depth_scale", lambda r: num(r.get("depth_scale")))
    row("結構相關（↑越像原照片）", lambda r: num(r.get("corr")))
    row("像素變化（↑改得越多）", lambda r: num(r.get("diff")))
    row("總耗時", lambda r: num(r.get("elapsed"), "{:.1f}s"))
    L += ["", "> 結構相關是兩張圖深度圖的 Pearson 相關，只是輔助指標：**最終以肉眼判斷「還是不是同一個房間」為準**。", "",
          "### 送出的 prompt（P0）", "", "```", (runs[0].get("prompt") or "(無)").strip() if runs else "(無)", "```", ""]

    doc = DOC.read_text(encoding="utf-8")
    DOC.write_text(doc.split(MARK)[0] + MARK + "\n\n" + "\n".join(L), encoding="utf-8")
    print(f"報告：{DOC}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", default=DEFAULT_PHOTO)
    ap.add_argument("--style", default="industrial")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    if not a.report_only:
        run(ensure_in_artifacts(a.photo), a.style)
    build_report()
