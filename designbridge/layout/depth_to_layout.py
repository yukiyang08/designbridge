#!/usr/bin/env python3
"""
depth_to_layout.py
------------------
從 DesignBridge vision pipeline 產出的 depth.png 萃取空間佈局 JSON。

輸出格式與 DesignBridge structured_requirement / layout_agent 相容：
  - room_zones      : 依深度分層的空間區域
  - furniture_hints : 從深度異常區推測的可能家具候選
  - spatial_metrics : 空間量化指標（寬深比、開放度等）
  - layout_json     : 完整佈局建議 JSON（可直接丟給 Layout Agent）

用法：
  python depth_to_layout.py depth.png
  python depth_to_layout.py depth.png --out layout.json --vis
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


# ──────────────────────────────────────────────
# 1. 載入深度圖
# ──────────────────────────────────────────────

def load_depth(path: str) -> np.ndarray:
    """
    讀取深度圖，回傳 float32 陣列，數值已正規化到 [0, 1]。
    0 = 最近（前景）, 1 = 最遠（背景 / 牆壁）

    注意：vision.run_depth_estimation 存的是 Depth-Anything 的 disparity 視覺化，
    慣例是「近=亮(255)、遠=暗(0)」，與本模組（及下游 ZONE_THRESHOLDS、
    _guess_furniture、compute_spatial_metrics）採用的 0=近 慣例相反，
    因此在此反相。少了這一步，foreground/background 會整組顛倒，
    萃取出的 furniture_candidates 位置語意也會全錯。
    """
    img = Image.open(path).convert("L")          # 轉灰階
    arr = np.array(img, dtype=np.float32) / 255.0
    return 1.0 - arr


# ──────────────────────────────────────────────
# 2. 深度分層（Depth Slicing）
# ──────────────────────────────────────────────

ZONE_THRESHOLDS = {
    "foreground":   (0.00, 0.30),   # 最近：地板前半、大型落地家具
    "mid_near":     (0.30, 0.55),   # 中近：沙發、茶几、主要家具
    "mid_far":      (0.55, 0.75),   # 中遠：牆邊家具、書架、TV 牆
    "background":   (0.75, 1.00),   # 最遠：牆面、門窗
}

def slice_zones(depth: np.ndarray) -> dict:
    """將深度圖切成四個距離層，回傳每層的遮罩與統計。"""
    h, w = depth.shape
    total = h * w
    zones = {}
    for name, (lo, hi) in ZONE_THRESHOLDS.items():
        mask = (depth >= lo) & (depth < hi)
        pixel_count = int(mask.sum())
        zones[name] = {
            "depth_range": [round(lo, 2), round(hi, 2)],
            "pixel_ratio": round(pixel_count / total, 4),
            "mask": mask,          # 僅內部使用，不輸出 JSON
        }
    return zones


# ──────────────────────────────────────────────
# 3. 區域重心 → 位置標籤
# ──────────────────────────────────────────────

def centroid_to_position(cy: float, cx: float, h: float, w: float) -> str:
    """把像素重心轉成語義位置字串，例如 'center-left'。"""
    row = "top" if cy < h / 3 else ("bottom" if cy > 2 * h / 3 else "center")
    col = "left" if cx < w / 3 else ("right" if cx > 2 * w / 3 else "center")
    if row == "center" and col == "center":
        return "center"
    return f"{row}-{col}" if row != "center" else col


# ──────────────────────────────────────────────
# 4. 找家具候選區（深度突變區）
# ──────────────────────────────────────────────

def detect_furniture_blobs(depth: np.ndarray, zones: dict) -> list:
    """
    在 mid_near 層中用簡單的連通區域分析找出家具候選。
    回傳候選清單，每項包含位置、相對大小、深度均值。
    """
    try:
        from scipy import ndimage as ndi
    except ImportError:
        # scipy 不可用時回傳粗略估計
        return _furniture_fallback(depth, zones)

    h, w = depth.shape
    mask = zones["mid_near"]["mask"] | zones["mid_far"]["mask"]

    # 侵蝕再膨脹（去雜訊）
    struct = ndi.generate_binary_structure(2, 2)
    cleaned = ndi.binary_opening(mask, structure=struct, iterations=3)

    labeled, n_blobs = ndi.label(cleaned)
    blobs = []
    for i in range(1, n_blobs + 1):
        region = labeled == i
        pixel_count = int(region.sum())
        if pixel_count < (h * w * 0.005):   # 太小忽略（< 0.5%）
            continue

        ys, xs = np.where(region)
        cy, cx = float(ys.mean()), float(xs.mean())
        bh = int(ys.max() - ys.min())
        bw = int(xs.max() - xs.min())
        aspect = round(bw / bh, 2) if bh > 0 else 1.0
        mean_depth = float(depth[region].mean())

        blobs.append({
            "position": centroid_to_position(cy, cx, h, w),
            "centroid_norm": [round(cy / h, 3), round(cx / w, 3)],
            "bbox_norm": [
                round(float(ys.min()) / h, 3),
                round(float(xs.min()) / w, 3),
                round(float(ys.max()) / h, 3),
                round(float(xs.max()) / w, 3),
            ],
            "size_ratio": round(pixel_count / (h * w), 4),
            "aspect_ratio": aspect,
            "mean_depth": round(mean_depth, 3),
            "furniture_hint": _guess_furniture(aspect, mean_depth, cy / h),
        })

    # 依大小排序
    blobs.sort(key=lambda b: b["size_ratio"], reverse=True)
    return blobs[:8]   # 最多回傳 8 個主要區域


def _furniture_fallback(depth: np.ndarray, zones: dict) -> list:
    """scipy 不可用時的簡化版本（格狀掃描）。"""
    h, w = depth.shape
    grid_r, grid_c = 3, 4
    blobs = []
    for r in range(grid_r):
        for c in range(grid_c):
            r0, r1 = r * h // grid_r, (r + 1) * h // grid_r
            c0, c1 = c * w // grid_c, (c + 1) * w // grid_c
            patch = depth[r0:r1, c0:c1]
            mean_d = float(patch.mean())
            if 0.25 < mean_d < 0.75:
                blobs.append({
                    "position": centroid_to_position(
                        (r0 + r1) / 2, (c0 + c1) / 2, h, w
                    ),
                    "centroid_norm": [
                        round((r0 + r1) / 2 / h, 3),
                        round((c0 + c1) / 2 / w, 3),
                    ],
                    "bbox_norm": [
                        round(r0 / h, 3), round(c0 / w, 3),
                        round(r1 / h, 3), round(c1 / w, 3),
                    ],
                    "size_ratio": round(1 / (grid_r * grid_c), 4),
                    "aspect_ratio": round((c1 - c0) / max(r1 - r0, 1), 2),
                    "mean_depth": round(mean_d, 3),
                    "furniture_hint": _guess_furniture(
                        (c1 - c0) / max(r1 - r0, 1), mean_d,
                        (r0 + r1) / 2 / h
                    ),
                })
    return blobs


def _guess_furniture(aspect: float, mean_depth: float, norm_y: float) -> str:
    """根據形狀與深度粗略猜測家具類型。"""
    if norm_y > 0.7 and mean_depth < 0.35:
        return "floor_object"          # 地板前景
    if aspect > 2.5 and mean_depth > 0.6:
        return "shelving_or_tv_unit"   # 寬扁 + 較遠 → 牆邊層架或電視牆
    if aspect > 2.0:
        return "sofa_or_bed"           # 寬矮 → 沙發 / 床
    if 0.8 < aspect < 1.3 and mean_depth < 0.5:
        return "table_or_ottoman"      # 接近正方 + 中近 → 桌子 / 腳凳
    if aspect < 0.6:
        return "tall_furniture"        # 高瘦 → 落地燈 / 書架立柱
    return "unknown_furniture"


# ──────────────────────────────────────────────
# 5. 空間指標
# ──────────────────────────────────────────────

def compute_spatial_metrics(depth: np.ndarray, zones: dict) -> dict:
    """計算空間開放度、深度變異等量化指標。"""
    h, w = depth.shape

    # 深度梯度 → 空間複雜度
    gy = np.gradient(depth, axis=0)
    gx = np.gradient(depth, axis=1)
    grad_mag = np.sqrt(gy**2 + gx**2)

    # 左右深度差（判斷空間是否對稱）
    left_mean  = float(depth[:, :w//2].mean())
    right_mean = float(depth[:, w//2:].mean())

    # 上下深度差（判斷透視強度）
    top_mean    = float(depth[:h//2, :].mean())
    bottom_mean = float(depth[h//2:, :].mean())

    openness = float(zones["background"]["pixel_ratio"] + zones["mid_far"]["pixel_ratio"])

    return {
        "openness_score":        round(openness, 4),          # 越高越空曠
        "complexity_score":      round(float(grad_mag.mean()), 4),  # 深度變化越大越複雜
        "depth_mean":            round(float(depth.mean()), 4),
        "depth_std":             round(float(depth.std()), 4),
        "left_right_symmetry":   round(1 - abs(left_mean - right_mean), 4),
        "perspective_strength":  round(abs(top_mean - bottom_mean), 4),
        "foreground_ratio":      round(zones["foreground"]["pixel_ratio"], 4),
        "mid_ratio":             round(
            zones["mid_near"]["pixel_ratio"] + zones["mid_far"]["pixel_ratio"], 4
        ),
        "background_ratio":      round(zones["background"]["pixel_ratio"], 4),
    }


# ──────────────────────────────────────────────
# 6. 組合成佈局 JSON
# ──────────────────────────────────────────────

def build_layout_json(
    depth_path: str,
    depth: np.ndarray,
    zones: dict,
    blobs: list,
    metrics: dict,
) -> dict:
    """組裝符合 DesignBridge Layout Agent 輸入格式的 JSON。"""

    h, w = depth.shape

    # 推測空間類型
    space_type = "unknown"
    if metrics["openness_score"] > 0.55:
        space_type = "open_plan"
    elif metrics["complexity_score"] > 0.08:
        space_type = "cluttered"
    else:
        space_type = "standard_room"

    # 推測攝影機視角
    perspective = "eye_level"
    if metrics["perspective_strength"] > 0.15:
        perspective = "slight_high_angle"
    elif metrics["perspective_strength"] < 0.05:
        perspective = "flat_frontal"

    # 動線寬度估計（foreground 空曠度）
    circulation_score = 1.0 - metrics["foreground_ratio"]

    # 家具候選
    furniture_candidates = []
    for b in blobs:
        furniture_candidates.append({
            "type":       b["furniture_hint"],
            "position":   b["position"],
            "bbox_norm":  b["bbox_norm"],
            "size_ratio": b["size_ratio"],
            "confidence": "high" if b["size_ratio"] > 0.05 else "low",
        })

    # 空間分區（三欄 × 三列九宮格，描述各格深度特徵）
    grid_zones = []
    for row_i, row_label in enumerate(["top", "center", "bottom"]):
        for col_i, col_label in enumerate(["left", "center", "right"]):
            r0 = row_i * h // 3;  r1 = (row_i + 1) * h // 3
            c0 = col_i * w // 3;  c1 = (col_i + 1) * w // 3
            patch = depth[r0:r1, c0:c1]
            grid_zones.append({
                "grid_id":    f"{row_label}_{col_label}",
                "depth_mean": round(float(patch.mean()), 3),
                "depth_std":  round(float(patch.std()), 3),
                "zone_label": _depth_to_zone_label(float(patch.mean())),
            })

    layout_json = {
        "source": {
            "depth_map": str(depth_path),
            "image_size": {"height": h, "width": w},
        },
        "space_analysis": {
            "space_type":         space_type,
            "camera_perspective": perspective,
            "circulation_score":  round(circulation_score, 3),
            "spatial_metrics":    metrics,
        },
        "depth_zones": {
            name: {
                "depth_range": info["depth_range"],
                "pixel_ratio": info["pixel_ratio"],
            }
            for name, info in zones.items()
        },
        "grid_analysis": grid_zones,
        "furniture_candidates": furniture_candidates,
        "layout_recommendation": _make_recommendation(
            space_type, metrics, blobs, furniture_candidates
        ),
    }
    return layout_json


def _depth_to_zone_label(mean_d: float) -> str:
    for name, (lo, hi) in ZONE_THRESHOLDS.items():
        if lo <= mean_d < hi:
            return name
    return "background"


def _make_recommendation(
    space_type: str,
    metrics: dict,
    blobs: list,
    candidates: list,
) -> dict:
    """依分析結果給出簡易佈局建議。"""
    suggestions = []

    circulation_score = 1.0 - metrics["foreground_ratio"]
    if circulation_score < 0.3:
        suggestions.append({
            "priority": "high",
            "action":   "clear_foreground",
            "reason":   "前景佔用率高，動線受阻，建議移除或縮小前景家具",
        })
    if metrics["left_right_symmetry"] < 0.85:
        suggestions.append({
            "priority": "medium",
            "action":   "balance_sides",
            "reason":   "左右深度不對稱，可考慮在較淺側補充對稱家具",
        })
    if metrics["openness_score"] < 0.3 and space_type != "cluttered":
        suggestions.append({
            "priority": "medium",
            "action":   "reduce_mid_furniture",
            "reason":   "中景密度高，可減少中景家具以提升空間感",
        })
    if not suggestions:
        suggestions.append({
            "priority": "low",
            "action":   "maintain_layout",
            "reason":   "目前空間分佈合理，建議微調細節即可",
        })

    # 推測主要功能區
    main_zones = []
    for c in candidates[:3]:
        if c["confidence"] == "high":
            main_zones.append({
                "furniture": c["type"],
                "position":  c["position"],
                "keep":      True,
            })

    return {
        "edit_scope_suggestion": _suggest_edit_scope(metrics),
        "layout_suggestions":    suggestions,
        "anchor_furniture":      main_zones,
        "routing_hint":          _routing_hint(metrics),
    }


def _suggest_edit_scope(metrics: dict) -> float:
    """根據空間複雜度建議 edit_scope 值。"""
    if metrics["complexity_score"] > 0.10:
        return 0.8   # 複雜 → 大改
    if metrics["openness_score"] > 0.6:
        return 0.4   # 空曠 → 中改
    return 0.5


def _routing_hint(metrics: dict) -> str:
    """給 Design Director 的路由建議。"""
    if metrics["complexity_score"] > 0.10 and metrics["openness_score"] < 0.35:
        return "layout_and_style"
    if metrics["complexity_score"] > 0.08:
        return "layout"
    return "style"


# ──────────────────────────────────────────────
# 7. 可選視覺化
# ──────────────────────────────────────────────

def visualize(depth: np.ndarray, blobs: list, out_path: str):
    """輸出視覺化圖（需要 matplotlib）。"""
    try:
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt
    except ImportError:
        print("⚠️  matplotlib 未安裝，跳過視覺化。")
        return

    h, w = depth.shape
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 左：深度圖 + 家具 bbox
    ax = axes[0]
    ax.imshow(depth, cmap="plasma", vmin=0, vmax=1)
    ax.set_title("Depth Map + Furniture Candidates")
    colors = ["red", "lime", "cyan", "yellow", "orange", "magenta", "white", "pink"]
    for i, b in enumerate(blobs):
        y0, x0, y1, x1 = b["bbox_norm"]
        rect = mpatches.Rectangle(
            (x0 * w, y0 * h), (x1 - x0) * w, (y1 - y0) * h,
            linewidth=2, edgecolor=colors[i % len(colors)], facecolor="none"
        )
        ax.add_patch(rect)
        ax.text(
            x0 * w + 3, y0 * h + 12,
            f"{b['furniture_hint']}\n({b['size_ratio']:.2%})",
            color=colors[i % len(colors)], fontsize=7,
            bbox=dict(facecolor="black", alpha=0.4, pad=1),
        )
    ax.axis("off")

    # 右：深度分層熱圖
    zone_map = np.zeros_like(depth)
    for val, (name, (lo, hi)) in enumerate(ZONE_THRESHOLDS.items(), 1):
        zone_map[(depth >= lo) & (depth < hi)] = val

    ax2 = axes[1]
    im = ax2.imshow(zone_map, cmap="tab10", vmin=0, vmax=5)
    ax2.set_title("Depth Zone Map\n(1=fg 2=mid_near 3=mid_far 4=bg)")
    ax2.axis("off")
    plt.colorbar(im, ax=ax2, fraction=0.03)

    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"✅ 視覺化圖已存：{out_path}")


# ──────────────────────────────────────────────
# 8. 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="從 DesignBridge depth.png 萃取佈局 JSON"
    )
    parser.add_argument("depth_map", help="深度圖路徑（depth.png）")
    parser.add_argument(
        "--out", default=None,
        help="輸出 JSON 路徑（預設：與輸入同目錄的 layout.json）"
    )
    parser.add_argument(
        "--vis", action="store_true",
        help="同時輸出視覺化圖（需要 matplotlib）"
    )
    parser.add_argument(
        "--pretty", action="store_true", default=True,
        help="格式化輸出 JSON（預設開啟）"
    )
    args = parser.parse_args()

    depth_path = Path(args.depth_map)
    if not depth_path.exists():
        print(f"❌ 找不到深度圖：{depth_path}")
        sys.exit(1)

    out_path = Path(args.out) if args.out else depth_path.parent / "layout.json"

    print(f"🔍 載入深度圖：{depth_path}")
    depth = load_depth(str(depth_path))
    print(f"   尺寸：{depth.shape[1]}×{depth.shape[0]}，深度範圍：[{depth.min():.3f}, {depth.max():.3f}]")

    print("📐 深度分層分析...")
    zones = slice_zones(depth)
    for name, info in zones.items():
        print(f"   {name:12s}  {info['pixel_ratio']:6.2%}")

    print("🛋️  家具候選偵測...")
    blobs = detect_furniture_blobs(depth, zones)
    print(f"   找到 {len(blobs)} 個候選區域")
    for b in blobs:
        print(f"   [{b['position']:15s}] {b['furniture_hint']} (size={b['size_ratio']:.2%})")

    print("📊 計算空間指標...")
    metrics = compute_spatial_metrics(depth, zones)

    print("🏗️  組裝佈局 JSON...")
    layout = build_layout_json(str(depth_path), depth, zones, blobs, metrics)

    # 輸出 JSON
    indent = 2 if args.pretty else None
    out_path.write_text(json.dumps(layout, ensure_ascii=False, indent=indent), encoding="utf-8")
    print(f"\n✅ 佈局 JSON 已存：{out_path}")

    # 路由建議
    rec = layout["layout_recommendation"]
    print(f"\n💡 分析摘要")
    print(f"   空間類型      : {layout['space_analysis']['space_type']}")
    print(f"   開放度分數    : {metrics['openness_score']:.2%}")
    print(f"   複雜度分數    : {metrics['complexity_score']:.4f}")
    print(f"   建議 edit_scope: {rec['edit_scope_suggestion']}")
    print(f"   路由建議      : {rec['routing_hint']}")
    print(f"   佈局建議      :")
    for s in rec["layout_suggestions"]:
        print(f"     [{s['priority'].upper()}] {s['action']} — {s['reason']}")

    if args.vis:
        vis_path = str(out_path.parent / (out_path.stem + "_vis.png"))
        visualize(depth, blobs, vis_path)

    return layout


if __name__ == "__main__":
    main()