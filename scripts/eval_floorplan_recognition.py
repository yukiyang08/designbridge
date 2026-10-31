"""平面圖辨識精確度評估：對照人工標註，算單房間家具辨識與整戶房間切分的 precision / recall。

用法（專案根目錄）：
  python scripts/eval_floorplan_recognition.py template ablation_tests/data labels.json   # 產標註骨架，手動填
  python scripts/eval_floorplan_recognition.py run labels.json preds.json [--dir DIR] [--repeat N]   # 呼叫真實辨識，會花 Gemini 費用
  python scripts/eval_floorplan_recognition.py score labels.json preds.json
  python scripts/eval_floorplan_recognition.py selftest   # 不連網，只驗證評分邏輯

比對方式是「類型多重集合」：標註與預測各自數每種類型的件數，取交集當命中，不比位置。
整戶圖的房間中心點有快取（artifacts/cache/room_seeds），--repeat 對 whole 的變異量測不準。
"""
import argparse
import ast
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KNOWN_ROOMS = ("living_room", "bedroom", "kitchen", "dining_room", "study")
IMG_EXT = {".jpg", ".jpeg", ".png"}


def furniture_vocab() -> list[str]:
    # 只解析 AST：直接 import designbridge 會連帶載入 langgraph 等重套件
    tree = ast.parse((ROOT / "designbridge" / "layout" / "layout_items.py").read_text(encoding="utf8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "FURNITURE_SIZES":
            return [k.value for k in node.value.keys]
    return []


def norm_room(t: str) -> str:
    # 系統只輸出 5 種房型，其餘（浴室、陽台…）一律是 other
    return t if t in KNOWN_ROOMS else "other"


def gt_types(lab: dict) -> list[str]:
    if lab["kind"] == "whole":
        return [norm_room(r) for r in lab["rooms"]]
    return list(lab["furniture"])


def score_runs(gt: list[str], runs: list) -> dict:
    """runs 每筆是預測類型清單；None 代表辨識失敗，視為空預測（拉低 recall）。"""
    s = dict(runs=len(runs), fail=0, tp=0, n_pred=0, n_gt=0, exact=0, abs_err=0)
    for pred in runs:
        if pred is None:
            s["fail"] += 1
            pred = []
        s["tp"] += sum((Counter(gt) & Counter(pred)).values())
        s["n_pred"] += len(pred)
        s["n_gt"] += len(gt)
        s["exact"] += int(len(pred) == len(gt))
        s["abs_err"] += abs(len(pred) - len(gt))
    return s


def merge(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b[k] for k in b}


def prf(s: dict) -> tuple[float, float, float]:
    p = s["tp"] / s["n_pred"] if s["n_pred"] else 0.0
    r = s["tp"] / s["n_gt"] if s["n_gt"] else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def cmd_template(a):
    out = Path(a.out)
    if out.exists():
        sys.exit(f"{out} 已存在，不覆蓋（避免洗掉手動標註）")
    data = {
        "_說明": [
            "kind=room：單一房間圖，填 room_type 與 furniture（圖上看得到的每件家具各一筆，可重複，類型從 _家具類型 選）",
            "kind=whole：整戶圖，填 rooms（每個房間一筆房型，從 _房型 選；浴室、陽台、儲藏等填 other；玄關走廊不算房間，不要列）",
            "標註時不要先看系統輸出，避免偏誤",
        ],
        "_家具類型": furniture_vocab(),
        "_房型": [*KNOWN_ROOMS, "other"],
    }
    for p in sorted(Path(a.dir).iterdir()):
        if p.suffix.lower() in IMG_EXT:
            data[p.name] = {"kind": "room", "room_type": "living_room", "furniture": [], "rooms": []}
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf8")
    print(f"已產生 {out}（{len(data) - 3} 張圖），請手動填標註")


def predict(lab: dict, path: str):
    sys.path.insert(0, str(ROOT))
    from designbridge.layout.floorplan_parse import detect_rooms_in_floor_plan, parse_floor_plan_image

    if lab["kind"] == "whole":
        rooms = detect_rooms_in_floor_plan(path)
        return [r["room_type"] for r in rooms] if rooms else None
    res = parse_floor_plan_image(path, f"eval_{Path(path).stem}", room_type=lab.get("room_type", "living_room"))
    return [f["type"] for f in res["furniture_placements"]] if res else None


def cmd_run(a):
    labels = json.loads(Path(a.labels).read_text(encoding="utf8"))
    preds = {}
    for name, lab in labels.items():
        if name.startswith("_"):
            continue
        runs = []
        for i in range(a.repeat):
            t0 = time.perf_counter()
            try:
                runs.append(predict(lab, str(Path(a.dir) / name)))
            except Exception as e:  # 單張失敗不中斷整批
                print(f"  {name} 第 {i + 1} 次例外：{e}")
                runs.append(None)
            print(f"{name} run{i + 1} {time.perf_counter() - t0:.1f}s -> {runs[-1]}", flush=True)
        preds[name] = runs
    Path(a.preds).write_text(json.dumps(preds, ensure_ascii=False, indent=1), encoding="utf8")


def cmd_score(a):
    labels = json.loads(Path(a.labels).read_text(encoding="utf8"))
    preds = json.loads(Path(a.preds).read_text(encoding="utf8"))
    total: dict[str, dict] = {}
    for name, lab in labels.items():
        if name.startswith("_") or name not in preds:
            continue
        if not gt_types(lab):
            print(f"略過 {name}：標註是空的")
            continue
        s = score_runs(gt_types(lab), preds[name])
        p, r, f1 = prf(s)
        print(f"{name:24s} {lab['kind']:5s} 標註{s['n_gt'] // s['runs']:3d} 預測{s['n_pred'] / s['runs']:5.1f} "
              f"命中{s['tp'] / s['runs']:5.1f}  P={p:.2f} R={r:.2f}  失敗{s['fail']}/{s['runs']}")
        total[lab["kind"]] = merge(total.get(lab["kind"], {}), s)
    for kind, s in total.items():
        p, r, f1 = prf(s)
        label = "單房間家具辨識" if kind == "room" else "整戶房間切分"
        print(f"\n[{label}] 共 {s['runs']} 次辨識：成功率 {1 - s['fail'] / s['runs']:.0%}  "
              f"precision {p:.1%}  recall {r:.1%}  F1 {f1:.1%}  "
              f"件數完全相符 {s['exact'] / s['runs']:.0%}  平均件數誤差 {s['abs_err'] / s['runs']:.2f}")


def selftest():
    # 標註 3 件、預測 3 件其中 2 件對 → P=R=2/3
    s = score_runs(["sofa", "sofa", "tv_unit"], [["sofa", "tv_unit", "chair"]])
    assert (s["tp"], s["n_pred"], s["n_gt"], s["exact"]) == (2, 3, 3, 1), s
    assert abs(prf(s)[0] - 2 / 3) < 1e-9 and abs(prf(s)[1] - 2 / 3) < 1e-9
    # 失敗的那次算空預測：recall 減半，fail 記一次
    s = score_runs(["sofa", "tv_unit"], [["sofa", "tv_unit"], None])
    assert (s["tp"], s["n_pred"], s["n_gt"], s["fail"]) == (2, 2, 4, 1), s
    assert prf(s)[1] == 0.5
    # 浴室等不支援的房型一律算 other
    assert gt_types({"kind": "whole", "rooms": ["bathroom", "bedroom"]}) == ["other", "bedroom"]
    print("selftest OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template")
    t.add_argument("dir")
    t.add_argument("out")
    r = sub.add_parser("run")
    r.add_argument("labels")
    r.add_argument("preds")
    r.add_argument("--dir", default=str(ROOT / "ablation_tests" / "data"))
    r.add_argument("--repeat", type=int, default=1)
    sc = sub.add_parser("score")
    sc.add_argument("labels")
    sc.add_argument("preds")
    sub.add_parser("selftest")
    a = ap.parse_args()
    {"template": cmd_template, "run": cmd_run, "score": cmd_score, "selftest": lambda _: selftest()}[a.cmd](a)


if __name__ == "__main__":
    main()
