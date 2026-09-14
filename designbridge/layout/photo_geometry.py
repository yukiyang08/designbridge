#!/usr/bin/env python3
"""
photo_geometry.py
-----------------
從使用者上傳照片的 depth + segmentation 反推「地板平面」的影像幾何，讓 Layout Agent
的俯視座標可以直接落回**原始照片的真實地板位置**，而不是投影到一個憑空捏造的房間盒子。

核心觀察：
  地板是一個平面 → 俯視平面圖到影像是一個 **homography**（單應變換），
  完全由地板在影像中的四個角決定，不需要 metric 3D 重建、不需要估焦距。

  又因為相機 roll≈0 時，地板平面上「同一影像列 v」就是「同一景深」，
  所以可見地板區域在影像中是梯形、在俯視圖中是矩形 —— 四點對應即為精確解。

兩條求解路徑（`resolve_floor_geometry` 依序嘗試）：

  1. `fit_floor_geometry` —— 直接找牆腳線（floor/wall 交線）。最準，但真實居家照片
     裡地板常被家具團團圍住，整條牆腳線都看不到，成功率有限。
  2. `estimate_camera_geometry` —— 改由深度分佈重建：消失線由地板/天花板兩片平行
     平面的 disparity 解出；看不見的遠牆腳線則用「遠牆的 disparity 代回地板平面」
     反求。相機無 roll/yaw 時，俯視上往深處的平行線交會於主消失點 (cx, v_h)，
     梯形即完全確定。

垂直方向（家具高度）用 single-view metrology 的標準結果：
  地板點 (u, v) 抬高 h 公尺後 → v' = v_hor(u) + (v - v_hor(u)) * (1 - h / eye_height)
  其中 v_hor 是地板的消失線，eye_height 為相機高度（一般室內照片約 1.4~1.6 m，
  見 Config.LAYOUT_CAMERA_EYE_HEIGHT）。此式假設影像中的鉛直線仍為鉛直（俯仰角不大），
  對一般室內照片成立。

俯視座標慣例與 layout_agent 一致：
  x ∈ [0,1] 左→右；y ∈ [0,1] 上(遠牆)→下(近相機側)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


# ── ADE20K 標籤分類（UPerNet segmentation 的 present_labels）────────────────────

FLOOR_LABELS: frozenset[str] = frozenset({
    "floor", "flooring", "rug", "carpet", "floor mat", "mat",
    "ground", "earth", "road", "path", "stage",
})

WALL_LABELS: frozenset[str] = frozenset({
    "wall", "windowpane", "window", "door", "double door", "screen door",
    "column", "pillar", "pole", "railing", "bannister", "stairs", "stairway",
    "step", "fireplace", "radiator",
})

CEILING_LABELS: frozenset[str] = frozenset({"ceiling", "sky"})

# 用來量「遠牆有多遠」的表面。**不能**含 windowpane / door：窗外與門外是室外或別的
# 房間，深度遠超過本房間，會把遠牆估到天邊去，牆腳線也就跟著跑掉。
WALL_SURFACE_LABELS: frozenset[str] = frozenset({"wall", "curtain"})

# 房間「建築結構」= 重新規劃佈局時一定保留的部分；其餘（家具、擺設）預設會被清空，
# 但 build_empty_room_disparity 的 preserve_labels 可以額外指定要原封不動保留的家具類別。
ARCHITECTURE_LABELS: frozenset[str] = FLOOR_LABELS | WALL_LABELS | CEILING_LABELS

# 佈局規劃用的家具 type（scene_graph_to_depth.normalize_furniture_type 的輸出）
# → 這類家具在 ADE20K segmentation 裡的 label 名稱。
# 使用者沒要求變動的家具靠這張表找出它在照片裡的像素，直接保留原始深度，
# 而不是清掉再用合成長方體重畫。
FURNITURE_SEG_LABELS: dict[str, frozenset[str]] = {
    "bed": frozenset({"bed"}),
    "bunk_bed": frozenset({"bed"}),
    "sofa": frozenset({"sofa", "couch", "lounge"}),
    "loveseat": frozenset({"sofa", "couch"}),
    "armchair": frozenset({"armchair"}),
    "chair": frozenset({"chair", "swivel chair", "seat"}),
    "table": frozenset({"table"}),
    "coffee_table": frozenset({"coffee table", "cocktail table", "table"}),
    "dining_table": frozenset({"table"}),
    "side_table": frozenset({"table"}),
    "nightstand": frozenset({"table"}),
    "desk": frozenset({"desk"}),
    "cabinet": frozenset({"cabinet"}),
    "tv_unit": frozenset({"cabinet", "sideboard", "buffet", "counter"}),
    "wardrobe": frozenset({"wardrobe", "closet", "press"}),
    "dresser": frozenset({"chest of drawers", "chest", "bureau", "dresser"}),
    "bookshelf": frozenset({"bookcase"}),
    "shelf": frozenset({"shelf"}),
    "lamp": frozenset({"lamp"}),
    "plant": frozenset({"plant", "potted plant", "flora", "flower"}),
    "tv": frozenset({"television receiver", "television", "tv", "monitor", "crt screen", "screen"}),
    "mirror": frozenset({"mirror"}),
    "curtain": frozenset({"curtain", "drape", "drapery", "mantle", "pall"}),
}


# 原地保留的家具在 id map 裡的起始 id（1/2/3 保留給 floor/ceiling/wall，
# 4 起是投影進來的合成家具，所以保留區另外從 100 起算避免撞號）
PRESERVED_ID_BASE = 100


def seg_labels_for_furniture(ftypes) -> frozenset[str]:
    """一組家具 type → 對應的 segmentation label 名稱集合（查不到的忽略）。"""
    out: set[str] = set()
    for t in ftypes:
        out |= FURNITURE_SEG_LABELS.get(t, frozenset())
    return frozenset(out)


# ── segmentation 讀取 ─────────────────────────────────────────────────────────

def load_label_map(seg_path: str | Path, seg_meta_path: str | Path) -> tuple[np.ndarray, dict[int, str]]:
    """讀取 vision.run_segmentation 產生的 16-bit label map 與 meta。"""
    import json

    from PIL import Image

    labels = np.array(Image.open(str(seg_path)), dtype=np.int32)
    meta = json.loads(Path(seg_meta_path).read_text(encoding="utf-8"))
    raw = meta.get("present_labels") or meta.get("labels") or {}
    id_to_label = {int(k): str(v).lower().strip() for k, v in raw.items()}
    return labels, id_to_label


def mask_for_labels(
    labels: np.ndarray, id_to_label: dict[int, str], wanted: frozenset[str]
) -> np.ndarray:
    """回傳 label 名稱命中 `wanted` 的像素遮罩。名稱可能是 'wall, walls' 這種逗號別名列表。"""
    mask = np.zeros(labels.shape, dtype=bool)
    for lid, name in id_to_label.items():
        aliases = {a.strip() for a in name.split(",") if a.strip()}
        if aliases & wanted:
            mask |= labels == lid
    return mask


# ── 幾何小工具（純 NumPy）──────────────────────────────────────────────────────

def _fit_boundary_line(
    t: np.ndarray, s: np.ndarray, usable: np.ndarray, fallback: float
) -> tuple[float, float]:
    """擬合 s ≈ a*t + b，只用 `usable` 標記的樣本（排除被畫面截斷或屬於別條邊的點）。

    可用樣本太少代表該條牆腳線根本不在畫面內 → 回傳 (0, fallback)，
    亦即直接以畫面邊界當那一側的界線。
    """
    valid = usable
    if valid.sum() < max(12, int(0.10 * len(t))):
        return 0.0, float(fallback)
    tv, sv = t[valid], s[valid]
    coef = np.array([0.0, float(fallback)])
    for _ in range(2):
        design = np.stack([tv, np.ones_like(tv)], axis=1)
        coef, *_ = np.linalg.lstsq(design, sv, rcond=None)
        resid = sv - design @ coef
        sigma = float(resid.std())
        if sigma < 1e-6:
            break
        keep = np.abs(resid) <= 2.0 * sigma
        if keep.sum() < 12 or keep.all():
            break
        tv, sv = tv[keep], sv[keep]
    return float(coef[0]), float(coef[1])


def _adjacent(mask: np.ndarray, coords: np.ndarray, axis_index: np.ndarray,
              *, along_rows: bool, before: bool, reach: int = 8) -> np.ndarray:
    """檢查每個邊界樣本「外側」reach 個像素內是否碰到 mask（用來辨認真正的牆腳線）。"""
    out = np.zeros(len(coords), dtype=bool)
    limit = mask.shape[1] if along_rows else mask.shape[0]
    for i, (fixed, edge) in enumerate(zip(axis_index, coords)):
        e = int(edge)
        lo, hi = (max(0, e - reach), e) if before else (e + 1, min(limit, e + 1 + reach))
        if lo >= hi:
            continue
        strip = mask[int(fixed), lo:hi] if along_rows else mask[lo:hi, int(fixed)]
        out[i] = bool(strip.any())
    return out


def _meet(l1: np.ndarray, l2: np.ndarray) -> np.ndarray | None:
    """兩條齊次直線的交點，回傳 (u, v)；平行時 None。"""
    p = np.cross(l1, l2)
    if abs(p[2]) < 1e-9:
        return None
    return np.array([p[0] / p[2], p[1] / p[2]])


def _join(p1: np.ndarray, p2: np.ndarray) -> np.ndarray:
    """兩點連成的齊次直線。"""
    return np.cross(np.array([p1[0], p1[1], 1.0]), np.array([p2[0], p2[1], 1.0]))


def _horizon_from_parallel_planes(
    floor: tuple[float, float, float], ceiling: tuple[float, float, float] | None
) -> np.ndarray | None:
    """地板與天花板互相平行 → 兩者共用同一條消失線，可解出 disparity 的無限遠值 t。

    Depth-Anything 輸出經 min-max 正規化後為 disp = s/Z + t，室內場景沒有無限遠點，
    所以 t ≠ 0，不能直接把 disp=0 當消失線。有天花板時這條式子給出封閉解：
        t = (B_c*C_f - B_f*C_c) / (B_c - B_f)
    回傳齊次直線 (A_f, B_f, C_f - t)。天花板不可用時回傳 None。
    """
    if ceiling is None:
        return None
    a_f, b_f, c_f = floor
    a_c, b_c, c_c = ceiling
    if abs(b_c - b_f) < 1e-6:
        return None
    t = (b_c * c_f - b_f * c_c) / (b_c - b_f)
    return np.array([a_f, b_f, c_f - t])


def _horizon_v_from_line(line: np.ndarray, u: np.ndarray | float, fallback_h: int) -> np.ndarray:
    """齊次消失線在欄位 u 處的影像列 v。"""
    a, b, c = line
    u_arr = np.asarray(u, dtype=np.float64)
    if abs(b) < 1e-12:
        return np.full(np.shape(u_arr), -float(fallback_h), dtype=np.float64)
    return -(a * u_arr + c) / b


def _floor_quad_from_mask(
    mask: np.ndarray, wall_mask: np.ndarray, room_mask: np.ndarray, horizon: np.ndarray
) -> tuple[np.ndarray, dict[str, bool]] | None:
    """從地板遮罩解出地板矩形的四個角，回傳 ([遠左, 遠右, 近右, 近左], 各邊是否為真牆腳線)。

    利用 roll≈0 時「影像同一列 = 地板同一景深」的性質：
      - 遠邊 = 遠牆腳線，對每一欄取最上方地板像素做直線擬合
      - 左右邊 = 左右牆腳線，對每一列取最左/最右地板像素做直線擬合，
        並外插到畫面外的真實牆位置
      - 近邊 = 可見地板的最下緣（相機背後的牆看不到，只能以此為界）

    關鍵：只採用「外側緊鄰牆面」的邊界樣本。地板邊界也可能是被家具擋住造成的
    （真實照片幾乎必然如此），那種樣本會把牆腳線拉歪，必須剔除。
    某一側完全找不到牆腳線時退回畫面邊界，此時該側的 x 只代表「可見地板邊緣」。
    """
    h, w = mask.shape
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size < 16 or cols.size < 16:
        return None

    row_idx = rows.astype(np.float64)
    u_min = np.array([float(np.flatnonzero(mask[r])[0]) for r in rows])
    u_max = np.array([float(np.flatnonzero(mask[r])[-1]) for r in rows])
    col_idx = cols.astype(np.float64)
    v_top = np.array([float(np.flatnonzero(mask[:, c])[0]) for c in cols])

    v_near = float(rows[-1])
    v_far0 = float(rows[0])
    margin = max(4.0, 0.03 * w)

    wall_l = _adjacent(wall_mask, u_min, row_idx, along_rows=True, before=True)
    wall_r = _adjacent(wall_mask, u_max, row_idx, along_rows=True, before=False)
    wall_f = _adjacent(wall_mask, v_top, col_idx, along_rows=False, before=True)

    # 三條牆腳線（左/右/遠）互相污染彼此的樣本：某一欄最上方的地板像素，
    # 靠畫面兩側時其實落在側牆腳線上而非遠牆腳線上，反之亦然。
    # 先用「跳過最上方 1/4 列」的側線初值，再交替剔除對方的樣本收斂。
    lower = row_idx >= v_far0 + 0.25 * (v_near - v_far0)
    a_l, b_l = _fit_boundary_line(row_idx, u_min, wall_l & lower, 0.0)
    a_r, b_r = _fit_boundary_line(row_idx, u_max, wall_r & lower, float(w - 1))
    a_f, b_f = 0.0, v_far0
    got_l = got_r = got_f = False

    for _ in range(2):
        # 遠邊：只取「明顯落在左右牆腳線之間」的欄位
        inside = (
            wall_f
            & (col_idx > a_l * v_top + b_l + margin)
            & (col_idx < a_r * v_top + b_r - margin)
        )
        got_f = bool(inside.sum() >= max(12, int(0.10 * len(col_idx))))
        a_f, b_f = _fit_boundary_line(col_idx, v_top, inside, v_far0)
        # 側邊：剔除落在遠牆腳線之上的列（牆腳線相鄰性已濾掉家具造成的假邊界）
        use_l = wall_l & (row_idx >= a_f * u_min + b_f)
        use_r = wall_r & (row_idx >= a_f * u_max + b_f)
        got_l = bool(use_l.sum() >= max(12, int(0.10 * len(row_idx))))
        got_r = bool(use_r.sum() >= max(12, int(0.10 * len(row_idx))))
        a_l, b_l = _fit_boundary_line(row_idx, u_min, use_l, 0.0)
        a_r, b_r = _fit_boundary_line(row_idx, u_max, use_r, float(w - 1))

    if not (got_l or got_r):
        return None

    # 齊次直線：u = a*v + b → (1, -a, -b)；v = a_f*u + b_f → (a_f, -1, b_f)
    line_far = np.array([a_f, -1.0, b_f])
    line_near = np.array([0.0, 1.0, -v_near])
    line_left = np.array([1.0, -a_l, -b_l])
    line_right = np.array([1.0, -a_r, -b_r])

    # 只看得到單邊牆腳線時（另一側被家具擋住或出框），用地板消失線把已知那條側牆線
    # 「平移」到另一側：俯視圖上平行的兩條線，在影像上交於消失線上的同一個消失點。
    if got_l != got_r:
        known = line_left if got_l else line_right
        # 錨點取「遠牆腳線附近、地板層區域（含站在地板上的家具）的最外緣」。
        # 用畫面邊界會讓俯視範圍超出房間、家具被往內擠；只用可見地板又會被舊家具的
        # 剪影卡住，而舊家具正是要被換掉的東西 —— 兩者取中才是房間真正的橫向範圍下界。
        v_far_mid = a_f * (w / 2.0) + b_f
        band_lo = int(max(0, np.floor(v_far_mid)))
        band_hi = int(min(h, np.ceil(v_far_mid + 0.10 * max(v_near - v_far_mid, 1.0))) + 1)
        band_cols = np.flatnonzero(room_mask[band_lo:band_hi].any(axis=0))
        if got_l:
            edge_u = float(band_cols[-1]) if band_cols.size else w - 1.0
            edge_u = min(edge_u, w - 1.0)
        else:
            edge_u = float(band_cols[0]) if band_cols.size else 0.0
            edge_u = max(edge_u, 0.0)
        vanish = _meet(known, horizon)
        anchor = _meet(line_far, np.array([1.0, 0.0, -edge_u]))
        if vanish is not None and anchor is not None:
            derived = _join(vanish, anchor)
            if got_l:
                line_right = derived
            else:
                line_left = derived

    corners = [
        _meet(line_far, line_left), _meet(line_far, line_right),
        _meet(line_near, line_right), _meet(line_near, line_left),
    ]
    if any(c is None for c in corners):
        return None

    quad = np.stack(corners)
    # 極端外插無意義，夾在畫面的三倍範圍內
    quad[:, 0] = np.clip(quad[:, 0], -2.0 * w, 3.0 * w)
    quad[:, 1] = np.clip(quad[:, 1], -2.0 * h, 3.0 * h)
    far_left, far_right, near_right, near_left = quad

    far_width = far_right[0] - far_left[0]
    near_width = near_right[0] - near_left[0]
    if far_width <= 1.0 or near_width <= 1.0:
        return None
    # 透視：遠邊必須比近邊窄，否則牆腳線擬合有誤
    if far_width >= near_width * 0.98:
        return None
    if near_left[1] - far_left[1] < 0.05 * h:
        return None
    return quad, {"far": got_f, "left": got_l, "right": got_r}


def _homography_from_points(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """四點 DLT：回傳把 src (4,2) 映射到 dst (4,2) 的 3x3 homography。"""
    rows: list[list[float]] = []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1.0, 0.0, 0.0, 0.0, -u * x, -u * y, -u])
        rows.append([0.0, 0.0, 0.0, x, y, 1.0, -v * x, -v * y, -v])
    _, _, vt = np.linalg.svd(np.asarray(rows, dtype=np.float64))
    h = vt[-1].reshape(3, 3)
    if abs(h[2, 2]) > 1e-12:
        h = h / h[2, 2]
    return h


def _fit_plane_disparity(
    disp: np.ndarray, mask: np.ndarray, *, trim_sigma: float = 2.0, passes: int = 2
) -> tuple[float, float, float] | None:
    """在遮罩區域擬合 disp ≈ A*u + B*v + C（平面在 disparity 空間對像素座標為線性）。

    做 robust trimming，因為 segmentation 的地板遮罩邊緣常沾到家具腳部。
    """
    if mask is None or not mask.any():
        return None
    vs, us = np.nonzero(mask)
    if us.size < 200:
        return None
    z = disp[vs, us].astype(np.float64)
    u = us.astype(np.float64)
    v = vs.astype(np.float64)

    coef: np.ndarray | None = None
    for _ in range(max(1, passes)):
        design = np.stack([u, v, np.ones_like(u)], axis=1)
        coef, *_ = np.linalg.lstsq(design, z, rcond=None)
        resid = z - design @ coef
        sigma = float(resid.std())
        if sigma < 1e-6:
            break
        keep = np.abs(resid) <= trim_sigma * sigma
        if keep.sum() < 200 or keep.all():
            break
        u, v, z = u[keep], v[keep], z[keep]

    if coef is None:
        return None
    return float(coef[0]), float(coef[1]), float(coef[2])


# ── 主結構 ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PhotoFloorGeometry:
    """從原始照片解出的地板影像幾何。"""

    homography: np.ndarray          # 3x3：俯視 (x,y) ∈ [0,1]² → 影像 (u,v)
    disp_plane: tuple[float, float, float]  # 地板 disparity = A*u + B*v + C
    horizon: np.ndarray             # 齊次消失線 (a, b, c)，用來換算家具高度
    image_size: tuple[int, int]     # (width, height)
    eye_height: float               # 假設的相機高度（公尺）
    floor_quad: np.ndarray          # 4x2 影像座標 [遠左, 遠右, 近右, 近左]
    floor_coverage: float           # 地板佔畫面比例（診斷用）
    disp_range: tuple[float, float] = (0.0, 255.0)  # 照片實際出現的 disparity 範圍
    horizon_source: str = ""        # 消失線的估計來源（診斷用）

    def plan_to_pixel(self, xy: np.ndarray) -> np.ndarray:
        """俯視座標 (N,2) → 影像像素 (N,2)。"""
        pts = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        homo = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
        proj = homo @ self.homography.T
        wcoord = np.where(np.abs(proj[:, 2]) < 1e-9, 1e-9, proj[:, 2])
        return np.stack([proj[:, 0] / wcoord, proj[:, 1] / wcoord], axis=1)

    def horizon_v(self, u: np.ndarray | float) -> np.ndarray:
        """地板消失線在欄位 u 處的影像列 v。"""
        return _horizon_v_from_line(self.horizon, u, self.image_size[1])

    def lift(self, uv: np.ndarray, height_m: float) -> np.ndarray:
        """把地板上的影像點 (N,2) 抬高 height_m 公尺，回傳新的影像點 (N,2)。"""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        v_hor = self.horizon_v(uv[:, 0])
        ratio = 1.0 - float(height_m) / max(self.eye_height, 1e-3)
        v_top = v_hor + (uv[:, 1] - v_hor) * ratio
        return np.stack([uv[:, 0], v_top], axis=1)

    def floor_disparity(self, uv: np.ndarray) -> np.ndarray:
        """地板平面在影像點 (N,2) 的 disparity（近亮遠暗）。

        夾在照片實際出現的 disparity 範圍內：室內沒有無限遠點，外插到消失線附近時
        若放任它掉到 0，會在深度圖上留下「比整張照片最遠處還遠」的黑洞。
        """
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        a, b, c = self.disp_plane
        lo, hi = self.disp_range
        return np.clip(a * uv[:, 0] + b * uv[:, 1] + c, lo, hi)

    def floor_disparity_grid(self) -> np.ndarray:
        """整張影像大小的地板平面 disparity（外插到畫面各處）。"""
        w, h = self.image_size
        a, b, c = self.disp_plane
        lo, hi = self.disp_range
        gy, gx = np.mgrid[0:h, 0:w]
        return np.clip(a * gx + b * gy + c, lo, hi)


def fit_floor_geometry(
    depth_path: str | Path,
    seg_path: str | Path,
    seg_meta_path: str | Path,
    *,
    eye_height: float = 1.5,
    min_floor_coverage: float = 0.04,
) -> PhotoFloorGeometry | None:
    """從照片的 depth + segmentation 解出地板幾何。無法可靠求解時回傳 None。"""
    from PIL import Image

    depth_img = Image.open(str(depth_path)).convert("L")
    disp = np.asarray(depth_img, dtype=np.float32)
    h_img, w_img = disp.shape

    labels, id_to_label = load_label_map(seg_path, seg_meta_path)
    if labels.shape != disp.shape:
        labels = np.asarray(
            Image.fromarray(labels.astype(np.int32), mode="I").resize(
                (w_img, h_img), Image.NEAREST
            ),
            dtype=np.int32,
        )

    floor_mask = mask_for_labels(labels, id_to_label, FLOOR_LABELS)
    coverage = float(floor_mask.mean())
    if coverage < min_floor_coverage:
        print(f"[photo_geometry] 地板佔比僅 {coverage:.1%}（< {min_floor_coverage:.0%}），無法錨定")
        return None

    plane = _fit_plane_disparity(disp, floor_mask)
    if plane is None:
        print("[photo_geometry] 地板深度平面擬合失敗，無法錨定")
        return None

    # 地板遮罩常被家具切碎 → 閉運算 + 補洞，讓邊界貼近真實可見地板梯形
    filled = floor_mask
    try:
        from scipy import ndimage as ndi

        struct = ndi.generate_binary_structure(2, 2)
        filled = ndi.binary_closing(floor_mask, structure=struct, iterations=4)
        filled = ndi.binary_fill_holes(filled)
        largest = _largest_component(filled)
        if largest is not None:
            filled = largest
    except ImportError:
        pass

    # 消失線的初估：地板/天花板平行 → 封閉解；沒有天花板時退回 disparity=0 等值線
    # （後者偏低，因為室內沒有真正的無限遠點，僅作為求解側牆線時的粗略參考）。
    ceiling_mask = mask_for_labels(labels, id_to_label, CEILING_LABELS)
    horizon = _horizon_from_parallel_planes(plane, _fit_plane_disparity(disp, ceiling_mask))
    horizon_source = "floor+ceiling"
    if horizon is None:
        horizon = np.array(plane, dtype=np.float64)
        horizon_source = "disparity_zero"

    wall_mask = mask_for_labels(labels, id_to_label, WALL_LABELS)
    fitted = _floor_quad_from_mask(filled, wall_mask, ~(wall_mask | ceiling_mask), horizon)
    if fitted is None:
        print("[photo_geometry] 地板牆腳線擬合失敗（找不到可靠的牆/地交線），無法錨定")
        return None
    quad, edges_found = fitted

    area = 0.5 * abs(
        np.dot(quad[:, 0], np.roll(quad[:, 1], -1)) - np.dot(quad[:, 1], np.roll(quad[:, 0], -1))
    )
    if area < 0.02 * w_img * h_img:
        print("[photo_geometry] 地板四邊形過小，無法錨定")
        return None

    # 俯視 (x, y)：y=0 為遠牆、y=1 為近相機側（與 layout_agent 慣例一致）
    plan_corners = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    homography = _homography_from_points(plan_corners, quad)

    # 兩側牆腳線都找到時，四邊形確實是俯視矩形的像，可由 homography 解出精確消失線；
    # 只有單側時四邊形帶剪切，改用平面法或初估值。
    # 直線的變換是 l' = H^{-T} l，俯視的無窮遠線 (0,0,1) 對應到 H⁻¹ 的第三列（不是 H 的）。
    if edges_found["left"] and edges_found["right"]:
        try:
            horizon = np.asarray(np.linalg.inv(homography)[2], dtype=np.float64)
            horizon_source = "homography"
        except np.linalg.LinAlgError:
            pass

    v_far = float(quad[:, 1].min())
    v_hor = float(np.mean(_horizon_v_from_line(horizon, quad[:, 0], h_img)))
    if not (-2.0 * h_img < v_hor < v_far):
        # 消失線必須在可見地板上方，否則家具會往下長。夾回可信區間而非整個放棄，
        # 因為家具的落點（homography）仍然可用，只有高度尺度受影響。
        clamped = min(v_far - 0.02 * h_img, max(-1.0 * h_img, v_hor))
        print(f"[photo_geometry] 消失線 v={v_hor:.0f} 不合理，夾到 {clamped:.0f}")
        horizon = np.array([0.0, 1.0, -clamped])
        horizon_source += "+clamped"
        v_hor = clamped

    geom = PhotoFloorGeometry(
        homography=homography,
        disp_plane=plane,
        disp_range=(float(disp.min()), float(disp.max())),
        horizon=horizon,
        image_size=(w_img, h_img),
        eye_height=float(eye_height),
        floor_quad=quad,
        floor_coverage=coverage,
        horizon_source=horizon_source,
    )

    found = ",".join(k for k, v in edges_found.items() if v) or "無"
    print(
        f"[photo_geometry] 地板錨定成功：佔比 {coverage:.1%}，牆腳線 {found}，"
        f"四角 {[tuple(np.round(p, 1)) for p in quad]}，"
        f"消失線 v≈{v_hor:.0f}（{horizon_source}）"
    )
    return geom


def _largest_component(mask: np.ndarray) -> np.ndarray | None:
    """取最大連通區域（去掉牆上鏡面反射等雜訊區塊）。"""
    from scipy import ndimage as ndi

    labeled, n = ndi.label(mask)
    if n <= 1:
        return mask if n == 1 else None
    sizes = ndi.sum(mask, labeled, index=range(1, n + 1))
    return labeled == (int(np.argmax(sizes)) + 1)


def resolve_floor_geometry(
    depth_path: str | Path,
    seg_path: str | Path,
    seg_meta_path: str | Path,
    *,
    eye_height: float = 1.5,
) -> PhotoFloorGeometry | None:
    """依可靠度依序嘗試：牆腳線 homography → 由深度重建地板梯形。都失敗回傳 None。"""
    geom = None
    try:
        geom = fit_floor_geometry(depth_path, seg_path, seg_meta_path, eye_height=eye_height)
    except Exception as e:
        print(f"[photo_geometry] 牆腳線解算例外（{type(e).__name__}: {e}），改用相機估計")

    if geom is not None:
        # 交叉驗證：牆腳線解出的消失線若與地板/天花板平面法差太多，代表牆腳線擬合
        # 是被家具剪影帶偏的，寧可退到相機估計。
        cross = _ceiling_horizon_v(depth_path, seg_path, seg_meta_path)
        if cross is not None:
            v_h = float(np.mean(geom.horizon_v(np.array([geom.image_size[0] / 2.0]))))
            if abs(v_h - cross) > 0.15 * geom.image_size[1]:
                print(
                    f"[photo_geometry] 牆腳線消失線 v={v_h:.0f} 與平面法 v={cross:.0f} 不一致，"
                    f"改用相機估計"
                )
                geom = None
    if geom is not None:
        return geom

    return estimate_camera_geometry(
        depth_path, seg_path, seg_meta_path, eye_height=eye_height
    )


def _ceiling_horizon_v(
    depth_path: str | Path, seg_path: str | Path, seg_meta_path: str | Path
) -> float | None:
    """地板/天花板平行平面法解出的消失線 v（畫面中央處）。天花板不可見時 None。"""
    from PIL import Image

    disp = np.asarray(Image.open(str(depth_path)).convert("L"), dtype=np.float32)
    labels, id_to_label = _load_labels_matched(seg_path, seg_meta_path, disp.shape)
    line = _horizon_from_parallel_planes(
        _fit_plane_disparity(disp, mask_for_labels(labels, id_to_label, FLOOR_LABELS)) or (0, 0, 0),
        _fit_plane_disparity(disp, mask_for_labels(labels, id_to_label, CEILING_LABELS)),
    )
    if line is None:
        return None
    v = float(np.mean(_horizon_v_from_line(line, np.array([disp.shape[1] / 2.0]), disp.shape[0])))
    return v if -disp.shape[0] < v < 2 * disp.shape[0] else None


def estimate_camera_geometry(
    depth_path: str | Path,
    seg_path: str | Path,
    seg_meta_path: str | Path,
    *,
    eye_height: float = 1.5,
) -> PhotoFloorGeometry | None:
    """次選路徑：牆腳線看不到時，純粹由照片的深度分佈重建地板梯形。

    真實居家照片裡地板幾乎總是被家具團團圍住，`fit_floor_geometry` 需要的牆/地交線
    常常整條都看不到。但兩個關鍵量仍然量得到：

      - **消失線 v_h**：地板與天花板互相平行 → 兩片 disparity 平面給出封閉解。
      - **遠牆腳線 v_far**：遠牆的 disparity 是量得到的（牆在家具上方露出來），
        再把這個距離代回地板平面，就得到「地板退到跟遠牆一樣遠」的那一列 ——
        那正是被家具擋住、看不見的遠牆腳線。

    有了這兩條線，地板梯形就完全確定：相機無 roll/yaw 時，俯視上「往深處延伸」的
    平行線族交會於主消失點 (cx, v_h)，兩條側邊即由畫面左右緣的遠角連向該點。
    俯視 x/y 因此涵蓋「畫面內看得到的整片地板」，家具不會被投影到框外。

    唯一的假設是相機高度（換算家具高度用），以及 roll≈0、無 yaw、主點置中。
    """
    from PIL import Image

    disp = np.asarray(Image.open(str(depth_path)).convert("L"), dtype=np.float32)
    h_img, w_img = disp.shape
    labels, id_to_label = _load_labels_matched(seg_path, seg_meta_path, disp.shape)

    floor_mask = mask_for_labels(labels, id_to_label, FLOOR_LABELS)
    floor_plane = _fit_plane_disparity(disp, floor_mask)
    if floor_plane is None:
        print("[photo_geometry] 看不到地板，無法從照片重建地板梯形")
        return None
    a_p, b_p, c_p = floor_plane
    if abs(b_p) < 1e-6:
        print("[photo_geometry] 地板平面對影像列無變化（退化），無法重建")
        return None

    cx = w_img / 2.0
    ceiling_plane = _fit_plane_disparity(disp, mask_for_labels(labels, id_to_label, CEILING_LABELS))
    horizon_line = _horizon_from_parallel_planes(floor_plane, ceiling_plane)
    source = "floor+ceiling"
    v_h = h_img / 2.0
    if horizon_line is not None:
        v_h = float(_horizon_v_from_line(horizon_line, np.array([cx]), h_img)[0])
        if not (0.0 < v_h < 0.95 * h_img):
            horizon_line = None
    if horizon_line is None:
        v_h = h_img / 2.0          # 天花板不可見 → 退回「相機水平」假設
        source = "level_camera"

    # 遠牆腳線：取遠牆的 disparity（robust 下界），映射回地板平面所在的影像列
    wall_disp = disp[mask_for_labels(labels, id_to_label, WALL_SURFACE_LABELS)]
    v_floor_top = float(np.flatnonzero(floor_mask.any(axis=1))[0])
    if wall_disp.size >= 200:
        d_far = float(np.percentile(wall_disp, 10.0))
        v_far = (d_far - c_p - a_p * cx) / b_p
        source += "+wall_depth"
    else:
        v_far = v_floor_top
        source += "+floor_top"
    # 必須在消失線下方，且不得比實際看得到的地板還低（往深處只會更高）
    v_far = float(np.clip(v_far, v_h + 0.02 * h_img, min(v_floor_top, h_img - 2.0)))

    v_near = float(h_img - 1)
    if v_near - v_far < 0.05 * h_img:
        print("[photo_geometry] 可用地板帶過窄，無法重建地板梯形")
        return None

    # 俯視上往深處的平行線交會於主消失點 (cx, v_h)；兩側邊由**近**邊的畫面左右緣連過去。
    # 從俯視看，可見範圍是個離相機越遠越寬的扇形，所以能完整入鏡的最大矩形，其寬度
    # 由最近那一邊決定。若改用遠邊的畫面寬度當房間寬，近處的家具會被推到畫面外。
    vp = np.array([cx, v_h])
    overflow = 0.10 * w_img          # 容許略微超出畫面，多涵蓋一點房間兩側
    near_left = np.array([-overflow, v_near])
    near_right = np.array([w_img - 1.0 + overflow, v_near])
    line_far = np.array([0.0, 1.0, -v_far])
    far_left = _meet(_join(near_left, vp), line_far)
    far_right = _meet(_join(near_right, vp), line_far)
    if far_left is None or far_right is None or far_right[0] <= far_left[0]:
        print("[photo_geometry] 側邊求解退化，無法重建地板梯形")
        return None

    quad = np.stack([far_left, far_right, near_right, near_left])
    plan_corners = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])

    print(
        f"[photo_geometry] 由深度重建地板梯形（{source}）：消失線 v≈{v_h:.0f}，"
        f"遠牆腳線 v≈{v_far:.0f}，可見地板起始 v={v_floor_top:.0f}"
    )
    return PhotoFloorGeometry(
        homography=_homography_from_points(plan_corners, quad),
        disp_plane=floor_plane,
        disp_range=(float(disp.min()), float(disp.max())),
        horizon=np.array([0.0, 1.0, -v_h]),
        image_size=(w_img, h_img),
        eye_height=float(eye_height),
        floor_quad=quad,
        floor_coverage=float(floor_mask.mean()),
        horizon_source=f"camera:{source}",
    )


def _load_labels_matched(
    seg_path: str | Path, seg_meta_path: str | Path, shape: tuple[int, int]
) -> tuple[np.ndarray, dict[int, str]]:
    """讀 label map，必要時 resize 到與深度圖同尺寸。"""
    from PIL import Image

    labels, id_to_label = load_label_map(seg_path, seg_meta_path)
    if labels.shape != shape:
        labels = np.asarray(
            Image.fromarray(labels.astype(np.int32), mode="I").resize(
                (shape[1], shape[0]), Image.NEAREST
            ),
            dtype=np.int32,
        )
    return labels, id_to_label


def _harmonic_fill(
    values: np.ndarray, holes: np.ndarray, *, passes: int = 7, sigma0: float = 48.0
) -> np.ndarray:
    """把 `holes` 區域填成平滑（近似調和）的曲面，`holes` 外的已知值固定不動。

    最近鄰填補會在大面積的洞裡留下 Voronoi 楔形（從洞緣輻射出去的扇形），當成
    ControlNet 條件時 diffusion 會忠實地把那些假邊界畫成真的幾何。這裡改用由粗到細
    的高斯平滑、每一輪重新壓回已知值，收斂到沒有接縫的內插結果。
    """
    if not holes.any():
        return values

    known = ~holes
    out = values.astype(np.float32, copy=True)

    try:
        from scipy.ndimage import gaussian_filter
    except ImportError:
        return out

    sigma = float(sigma0)
    for _ in range(max(1, passes)):
        num = gaussian_filter(np.where(known, out, 0.0), sigma, mode="nearest")
        den = gaussian_filter(known.astype(np.float32), sigma, mode="nearest")
        blurred = np.divide(num, den, out=out.copy(), where=den > 1e-6)
        out = np.where(known, values, blurred).astype(np.float32)
        sigma = max(sigma / 2.0, 1.0)

    return out


def build_empty_room_disparity(
    depth_path: str | Path,
    seg_path: str | Path,
    seg_meta_path: str | Path,
    geom: PhotoFloorGeometry,
    preserve_labels: frozenset[str] = frozenset(),
    preserve_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[int, str]]:
    """把照片深度圖裡的舊家具清掉，回傳 (清空後的 disparity, id map, 保留家具的 id→type)。

    外殼 id：1=floor, 2=ceiling, 3=wall。保留窗、門、牆角等建築結構，
    這正是「讓成圖維持原始空間配置」的關鍵。

    使用者沒要求變動的家具不該被清掉再用合成長方體重畫——那會丟失照片裡的真實幾何
    （床頭板、被褥起伏），ControlNet 鎖住的就變成那個假方盒。`preserve_labels` 指定的
    類別、或 `preserve_mask` 指定的實例像素，深度原封不動保留，id 從 PRESERVED_ID_BASE 起算。

    其餘舊家具讓出來的像素：屬於地板的用解析地板平面填（家具搬走後露出的就是地板），
    屬於牆／天花板的用調和填補。
    """
    from PIL import Image

    disp = np.asarray(Image.open(str(depth_path)).convert("L"), dtype=np.float32)
    labels, id_to_label = _load_labels_matched(seg_path, seg_meta_path, disp.shape)

    floor_mask = mask_for_labels(labels, id_to_label, FLOOR_LABELS)
    ceiling_mask = mask_for_labels(labels, id_to_label, CEILING_LABELS)
    wall_mask = mask_for_labels(labels, id_to_label, WALL_LABELS)
    keep = floor_mask | ceiling_mask | wall_mask

    shell = np.zeros(disp.shape, dtype=np.int32)
    shell[wall_mask] = 3
    shell[ceiling_mask] = 2
    shell[floor_mask] = 1

    # 要原地保留的家具：逐類別配一個 id，深度值完全不動。
    # 地板 label 同時含 rug/carpet，保留家具絕不能蓋掉建築結構，故排除既有 keep 區。
    preserved_id_to_type: dict[int, str] = {}
    if preserve_labels:
        next_pid = PRESERVED_ID_BASE
        for lid, name in id_to_label.items():
            aliases = {a.strip() for a in str(name).split(",") if a.strip()}
            if not (aliases & preserve_labels):
                continue
            m = (labels == lid) & ~keep
            if not m.any():
                continue
            shell[m] = next_pid
            keep |= m
            preserved_id_to_type[next_pid] = sorted(aliases)[0]
            next_pid += 1
    if preserve_mask is not None and preserve_mask.any():
        m = preserve_mask & ~keep
        if m.any():
            pid = PRESERVED_ID_BASE + len(preserved_id_to_type)
            shell[m] = pid
            keep |= m
            preserved_id_to_type[pid] = "preserved_instance"

    clean = disp.copy()
    holes = ~keep
    if holes.any():
        # 最近鄰只用來決定「這個洞屬於哪個表面」（靠地板的算地板、靠牆的算牆），
        # 不用它的深度值——大面積的洞用最近鄰填會留下輻射狀的 Voronoi 楔形。
        try:
            from scipy import ndimage as ndi

            idx = tuple(ndi.distance_transform_edt(
                holes, return_distances=False, return_indices=True
            ))
            shell = shell[idx]
            clean = disp[idx]
        except ImportError:
            print("[photo_geometry] scipy 不可用，舊家具深度僅以地板平面覆蓋")

    # 地板（含家具搬走後露出來的部分）一律改用解析平面：這是精確解，
    # 同時抹掉舊家具在地板上留下的深度凹凸。
    floor_area = shell == 1
    clean = np.where(
        floor_area, geom.floor_disparity_grid().astype(np.float32), clean
    ).astype(np.float32)

    # 牆／天花板上的洞沒有解析式可用，改以調和填補取代最近鄰，避免假的楔形邊界。
    _smooth_holes = holes & ~floor_area
    if _smooth_holes.any():
        clean = _harmonic_fill(clean, _smooth_holes)

    # 保留區的深度必須是照片原值：上面的地板平面覆蓋與調和填補都不得動到它。
    if preserved_id_to_type:
        preserved_area = shell >= PRESERVED_ID_BASE
        clean = np.where(preserved_area, disp, clean).astype(np.float32)

    return clean, shell, preserved_id_to_type
