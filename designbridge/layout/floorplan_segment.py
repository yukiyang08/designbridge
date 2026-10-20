"""整戶平面圖的房間切割：Gemini 給每間房一個中心點，邊界由牆線決定。

Gemini 直接框房間時框很鬆、類型常標錯，JSON 也常壞；但它讀房名、指出房間大概在哪
很穩。所以只讓它給點，實際邊界用影像處理從牆線算出來。
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

# 統一縮到這個長邊再處理；下面的像素參數都以此解析度為準
_WORK_SIDE = 1240
# 牆是實心深色塊；細線（家具、標註、窗）會被開運算濾掉
_WALL_GRAY = 160
_LINE_GRAY = 200
_WALL_KERNEL = 5
# 兩端接牆、長度超過此比例的平行雙線（窗、落地窗）在認領階段視為隔間
_LONG_LINE = 0.068
# 雙線判定：兩條平行細線間距在此像素內會併成一條粗帶；單線（尺寸線）併不起來
_PAIR_GAP = 9
# 判斷窗戶嵌在牆缺口：檢查線段兩端外側這段距離（像素）內是否仍是同方向的牆
_EXT_NEAR = 4
_EXT_FAR = 30
_PAIR_MIN = 5
_MIN_ROOM_FRAC = 0.001
# 種子離最近室內空地超過圖長邊的此比例就丟掉
_SNAP_FRAC = 0.015
# 貼著屋外（此像素距離內）、面積小於非屋外區域此比例的封閉小區域歸屋外。
# 實測圓形標記 <0.05%、門外弧線 ~0.3%、最小的工作陽台 3.4%
_OUT_REACH = 10
_OUT_POCKET_FRAC = 0.01
# 淹水優先度上限，以建築外框對角線比例表示（約半個門寬）
_OPEN_CAP = 0.03
# 自動補種子的最小區塊面積（佔建築面積比例），擋掉牆角小凹槽
_MIN_AUTO_FRAC = 0.0015
# 補種子時把「比門寬更開闊」的門檻放寬到 cap 的此倍數，小廚房、儲藏室才找得到
_AUTO_CORE = 1.0
# 隔著窗戶線、面積不到旁邊有點區塊此比例的區塊視為那間房的凹處（凸窗、邊條）
_ALCOVE_RATIO = 0.35
_ALCOVE_OPEN = 0.6
# 牆塊外框長邊短於圖長邊的此比例就當成文字丟掉（柱子約 3–5%，數字約 1–2%）
_MIN_WALL_SPAN = 0.025


def _disk(r: int) -> np.ndarray:
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return x * x + y * y <= r * r


def _in_wall_line(lines: np.ndarray, wall: np.ndarray, horizontal: bool) -> np.ndarray:
    """只留嵌在牆缺口裡的線段（窗、落地窗）：兩端都接牆，且至少一端外側沿同一方向
    仍是牆（轉角的落地窗只有一端是）。尺寸線兩端碰到的都是垂直的牆，越過牆厚
    就是隔壁房間的空地，不會被留下。"""
    H, W = wall.shape
    keep = np.zeros_like(lines)
    lab, _ = ndi.label(lines)
    for i, sl in enumerate(ndi.find_objects(lab), 1):
        seg = lab[sl] == i
        if horizontal:
            rows = np.nonzero(seg.any(axis=1))[0] + sl[0].start
            c = int(np.median(rows))
            band = wall[max(0, c - 1):c + 2]
            a, b = sl[1].start, sl[1].stop
            left = band[:, max(0, a - _EXT_FAR):max(0, a - _EXT_NEAR)]
            right = band[:, min(W, b + _EXT_NEAR):min(W, b + _EXT_FAR)]
            touch_l = band[:, max(0, a - _EXT_NEAR - 2):a + 2].any()
            touch_r = band[:, max(0, b - 2):min(W, b + _EXT_NEAR + 2)].any()
        else:
            cols = np.nonzero(seg.any(axis=0))[0] + sl[1].start
            c = int(np.median(cols))
            band = wall[:, max(0, c - 1):c + 2]
            a, b = sl[0].start, sl[0].stop
            left = band[max(0, a - _EXT_FAR):max(0, a - _EXT_NEAR)]
            right = band[min(H, b + _EXT_NEAR):min(H, b + _EXT_FAR)]
            touch_l = band[max(0, a - _EXT_NEAR - 2):a + 2].any()
            touch_r = band[max(0, b - 2):min(H, b + _EXT_NEAR + 2)].any()
        coll_l = left.size and left.mean() >= 0.6
        coll_r = right.size and right.mean() >= 0.6
        if touch_l and touch_r and (coll_l or coll_r):
            keep[sl] |= seg
    return keep


def _is_alcove(comp: np.ndarray, box: tuple, core_lab: np.ndarray, seeded: set[int],
               free: np.ndarray, soft_line: np.ndarray, reach: int) -> bool:
    """comp 是否是隔壁有點房間的凹處（凸窗、被窗線隔開的邊條）：隔著窗戶線與該房相接的
    長度至少是 comp 寬度的 _ALCOVE_OPEN，且面積不到該房 _ALCOVE_RATIO。
    只隔一扇窗相鄰的獨立房間（臥室與餐廳之間的室內窗）相接長度短，不會被併掉。"""
    H, W = comp.shape
    pad = 3 * reach
    sl = tuple(slice(max(0, a.start - pad), min(n, a.stop + pad)) for a, n in zip(box, (H, W)))
    c0, f, soft, cl = comp[sl], free[sl], soft_line[sl], core_lab[sl]
    room = f & ~soft
    own = ndi.binary_dilation(c0, iterations=reach + 3, mask=room)       # 擴到自己房間的窗邊
    cross = ndi.binary_dilation(own, iterations=6, mask=f) & soft         # 跨過的窗線
    clab, cn = ndi.label(cross)
    if not cn:
        return False
    ys, xs = np.nonzero(c0)
    span = max(xs.max() - xs.min(), ys.max() - ys.min()) + 1
    area = int(c0.sum())
    contact: dict[int, int] = {}
    for k, cs in enumerate(ndi.find_objects(clab), 1):
        seg = clab == k
        length = max(cs[0].stop - cs[0].start, cs[1].stop - cs[1].start)
        # 窗邊常疊著窗框、窗簾線，對面房間的核心離窗線較遠，擴兩倍門檻
        other = ndi.binary_dilation(seg, iterations=2 * reach + 6, mask=room | soft)
        for c in set(np.unique(cl[other & ~own]).tolist()) & seeded:
            contact[c] = contact.get(c, 0) + length
    for c, length in contact.items():
        if length >= _ALCOVE_OPEN * span and area < _ALCOVE_RATIO * (core_lab == c).sum():
            return True
    return False


def _largest(mask: np.ndarray) -> np.ndarray:
    lab, n = ndi.label(mask)
    if n <= 1:
        return mask
    return lab == (int(np.argmax(ndi.sum(mask, lab, range(1, n + 1)))) + 1)


def _climb(free: np.ndarray, dist: np.ndarray, y: int, x: int, cap: float) -> tuple[int, int]:
    """沿離牆距離的坡度往上爬，到 cap 或局部最高點為止。
    點若貼著牆，起跑點太低，淹水時會被鄰房從門口先淹進來吃掉；
    門口是兩房之間的鞍部，往上爬不會越過它，所以點一定留在自己房內。"""
    H, W = free.shape
    for _ in range(H + W):
        if dist[y, x] >= cap:
            break
        y0, y1, x0, x1 = max(0, y - 2), min(H, y + 3), max(0, x - 2), min(W, x + 3)
        win = np.where(free[y0:y1, x0:x1], dist[y0:y1, x0:x1], -1)
        k = int(np.argmax(win))
        ny, nx = y0 + k // win.shape[1], x0 + k % win.shape[1]
        if win.flat[k] <= dist[y, x]:
            break
        y, x = ny, nx
    return y, x


def _flood(free: np.ndarray, prio: np.ndarray, markers: dict[int, tuple[int, int]]) -> np.ndarray:
    """標記分水嶺：所有房間從種子同時往外淹，prio 高的像素先淹。
    每間房會先填滿自己離牆遠的內部，最後才在門口這類窄處相遇；
    逐步往外長（BFS）則會讓隔壁沿著牆邊的窄帶從門口一路長進來，切出斜角。"""
    import heapq

    H, W = free.shape
    ok = free.ravel()
    pr = prio.ravel()
    lab = np.zeros(H * W, np.int32)
    heap: list[tuple[float, int, int, int]] = []
    n = 0
    for i, (y, x) in markers.items():
        heap.append((-np.inf, n, y * W + x, i))
        n += 1
    heapq.heapify(heap)
    while heap:
        _, _, idx, i = heapq.heappop(heap)
        if lab[idx]:
            continue
        lab[idx] = i
        y, x = divmod(idx, W)
        for nb, valid in ((idx - W, y > 0), (idx + W, y < H - 1), (idx - 1, x > 0), (idx + 1, x < W - 1)):
            if valid and ok[nb] and not lab[nb]:
                heapq.heappush(heap, (-pr[nb], n, nb, i))
                n += 1
    return lab.reshape(H, W)


def _paired(thin: np.ndarray, length: int, horizontal: bool) -> np.ndarray:
    """長直線中只留平行雙線：窗、落地窗是兩三條平行細線，尺寸線是單線。
    單線若當隔間，會把畫了尺寸標註的房間切成好幾塊。"""
    along = (1, length) if horizontal else (length, 1)
    across = (_PAIR_GAP, 1) if horizontal else (1, _PAIR_GAP)
    thick = (_PAIR_MIN, 1) if horizontal else (1, _PAIR_MIN)
    lines = ndi.binary_opening(thin, structure=np.ones(along))
    band = ndi.binary_closing(lines, structure=np.ones(across))
    return ndi.binary_opening(band, structure=np.ones(thick)) & ndi.binary_dilation(lines, iterations=1)


_DIRS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def _trace_outline(mask: np.ndarray) -> list[tuple[int, int]]:
    """Moore 鄰域追蹤外輪廓，回傳 (y, x) 序列。mask 需為單一實心連通塊。
    停止條件用 Jacob 準則（回到起點且下一步與第一步相同）；只看回到起點，
    遇到一像素寬的頸部會在半路就停。"""
    m = np.pad(mask, 1)
    ys, xs = np.nonzero(m)
    start = (int(ys[0]), int(xs[0]))
    cur, back = start, 6  # 光柵順序第一點，左邊必為背景
    out = [start]
    second = None
    for _ in range(4 * m.size):
        for k in range(1, 9):
            d = (back + k) % 8
            ny, nx = cur[0] + _DIRS[d][0], cur[1] + _DIRS[d][1]
            if m[ny, nx]:
                py, px = cur[0] + _DIRS[(d - 1) % 8][0], cur[1] + _DIRS[(d - 1) % 8][1]
                back = _DIRS.index((py - ny, px - nx))
                nxt = (ny, nx)
                break
        else:
            break  # 孤立點
        if cur == start and second is not None and nxt == second:
            break
        if second is None:
            second = nxt
        cur = nxt
        out.append(cur)
    if len(out) > 1 and out[-1] == start:
        out.pop()
    return [(y - 1, x - 1) for y, x in out]


def _simplify(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    """Douglas–Peucker（迭代版，避免長輪廓遞迴過深）。"""
    if len(pts) < 4:
        return pts
    arr = np.asarray(pts, float)
    keep = np.zeros(len(arr), bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(arr) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        p, q = arr[a], arr[b]
        seg = q - p
        n = np.hypot(*seg)
        rel = arr[a + 1:b] - p
        d = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / n if n else np.hypot(rel[:, 0], rel[:, 1])
        i = int(np.argmax(d))
        if d[i] > eps:
            keep[a + 1 + i] = True
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return [tuple(v) for v in arr[keep]]


def segment_rooms(image_path: str, seeds: list[dict]) -> list[dict[str, Any]] | None:
    """依種子點把平面圖切成房間。

    ``seeds``：``[{room_type, label, point: [y, x]}]``，point 為整張圖 0–1000 座標。
    回傳 ``[{id, room_type, label, x, y, w, h, polygon, anchor}]``，座標皆為 0–1 正規化，
    polygon 為 ``[[x, y], ...]`` 且含外圍牆厚（裁切時才不會把牆塗掉）。
    切不出任何房間時回傳 ``None``。
    """
    im = Image.open(image_path).convert("L")
    # 大圖縮小、小圖放大，牆厚、門寬等像素參數才對得上
    scale = _WORK_SIDE / max(im.size)
    if abs(scale - 1) > 0.05:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    g = np.asarray(im)
    H, W = g.shape

    # 屋外 = 所有線條當屏障時最大的白色連通區（尺寸線不封閉，會被併進來）
    lines = ndi.binary_dilation(g < _LINE_GRAY, iterations=1)
    olab, n = ndi.label(~lines)
    if n == 0:
        return None
    sizes = ndi.sum(~lines, olab, range(1, n + 1))
    outside = olab == (int(np.argmax(sizes)) + 1)

    wall = ndi.binary_opening(g < _WALL_GRAY, structure=np.ones((_WALL_KERNEL, _WALL_KERNEL)))
    # 粗字（尺寸數字、房名）也會留下來；它們是孤立小塊，牆和柱子則長或大
    wl, wn = ndi.label(wall)
    if wn:
        boxes = ndi.find_objects(wl)
        span = np.array([max(b[0].stop - b[0].start, b[1].stop - b[1].start) for b in boxes])
        keep = np.zeros(wn + 1, bool)
        keep[1:] = span >= _MIN_WALL_SPAN * max(H, W)
        wall = keep[wl]

    # 貼著屋外、被細線圍起的小區域也算屋外：窗戶旁的圓形標記、門外入口的開門弧線。
    # 它們不是最大那片白色，會被當成室內，再從窗洞被房間淹進去或被誤認成小房間
    out_id = int(np.argmax(sizes)) + 1
    near_out = ndi.binary_dilation(outside, iterations=_OUT_REACH)
    small = sizes < _OUT_POCKET_FRAC * (~outside).sum()
    pocket_ids = np.unique(olab[near_out & ~outside & ~lines])
    pocket = np.zeros(n + 1, bool)
    pocket[[i for i in pocket_ids if i and i != out_id and small[i - 1]]] = True
    outside |= pocket[olab]
    # 圍住這些區域的細線（圓圈外框、窗線）同樣歸屋外，否則房間會沿著線長出去
    outside |= lines & ~wall & ndi.binary_dilation(outside, iterations=_OUT_REACH // 2)
    free = ~wall & ~outside
    if not free.any():
        return None
    # 建築範圍：非屋外區域中含最多牆的那一塊。被圖框圍住的標題欄也屬非屋外，但牆很少；
    # 只看牆體本身則會被門洞、窗洞切成好幾塊
    if not wall.any():
        return None
    blab, bn = ndi.label(~outside)
    building = blab == (int(np.argmax(ndi.sum(wall, blab, range(1, bn + 1)))) + 1)
    # 尺度用最大一塊相連牆體量：建築範圍含陽台、尺寸線圍出的邊帶，量出來偏大，
    # 上限 cap 一大，窄房間（廁所）裡的種子會爬出門口
    ys, xs = np.nonzero(_largest(wall))
    diag = float(np.hypot(xs.max() - xs.min(), ys.max() - ys.min()))
    long_len = max(10, round(_LONG_LINE * diag))

    thin = ndi.binary_dilation((g < _LINE_GRAY) & ~wall, iterations=1)
    long_lines = (
        _in_wall_line(_paired(thin, long_len, horizontal=True), wall, True)
        | _in_wall_line(_paired(thin, long_len, horizontal=False), wall, False)
    )
    dist = ndi.distance_transform_edt(~wall)
    # 淹水順序：離牆越遠越先；雙線（窗、落地窗）最後才淹，當作弱隔間。
    # 家具的雙線外框（浴缸）也會被標到，但它四周都是同一間房，最後淹也不影響歸屬。
    # 優先度封頂在約半個門寬：比這更開闊的地方視為平地，同一片開放空間裡的多個點
    # （客廳＋餐廳）按先到先得平分；否則較深處的點會淹掉整片。
    cap = _OPEN_CAP * diag
    prio = np.where(ndi.binary_dilation(long_lines, iterations=1), -1.0, np.minimum(dist, cap))

    # 比門寬更開闊的區塊：門口寬度不到門檻，會把房間斷開。種子去重和自動補種子都用它。
    # 門檻用建築範圍量尺度：牆體量出的 cap 偏小，會低於半個門寬，房間從門口連成一片
    bys, bxs = np.nonzero(building)
    bdiag = float(np.hypot(bxs.max() - bxs.min(), bys.max() - bys.min()))
    # 窗戶等雙線也算隔間：室內窗常比門寬，不擋的話兩間房的核心會從窗口連成一塊
    soft_line = ndi.binary_dilation(long_lines, iterations=1)
    core_lab, core_n = ndi.label(free & building & ~soft_line & (dist >= _AUTO_CORE * _OPEN_CAP * bdiag))

    _, (iy, ix) = ndi.distance_transform_edt(~(free & building), return_indices=True)
    markers: dict[int, tuple[int, int]] = {}
    taken: set[tuple[int, int]] = set()
    typed: set[tuple[int, str]] = set()
    placed: list[tuple[bool, int, int, int, dict]] = []
    for i, s in enumerate(seeds, 1):
        try:
            py, px = (float(v) for v in s["point"])
        except (KeyError, TypeError, ValueError):
            continue
        y = min(H - 1, max(0, int(py / 1000 * H)))
        x = min(W - 1, max(0, int(px / 1000 * W)))
        # 點落在牆上或稍微偏到屋外（Gemini 座標常差幾個百分點）就吸到最近的室內空地；
        # 離太遠的才丟掉（門外入口箭頭）
        y2, x2 = int(iy[y, x]), int(ix[y, x])
        jump = np.hypot(y2 - y, x2 - x)
        if jump > _SNAP_FRAC * max(H, W):
            continue
        y, x = _climb(free, dist, y2, x2, cap)
        placed.append((jump > 2, i, y, x, s))
    # 先放原本就在室內的點，再放吸進來的點：吸進來又落在已有點的區塊，多半是門外
    # 箭頭或標在牆外的字（「後陽台入口」），要丟的是它而不是室內那個
    snapped_ids: set[int] = set()
    for snapped, i, y, x, s in sorted(placed, key=lambda t: t[0]):
        # 同一個被牆圍住的區塊裡，沒寫房名的點只留一個：Gemini 對沒寫房名的圖常在一間房
        # 丟好幾個點、類型也亂猜，會把房間切碎。只有圖上寫了不同房名（玄關＋客廳）才切開
        key = (int(core_lab[y, x]), str(s.get("label") or ""))
        if key[0] and key in typed:
            continue
        if snapped and key[0] and any(k[0] == key[0] for k in typed):
            continue
        if (y, x) not in taken:
            taken.add((y, x))
            typed.add(key)
            markers[i] = (y, x)
            if snapped:
                snapped_ids.add(i)

    # Gemini 沒列到的空間（沒寫房名的廚房、儲藏室…）自動補種子，否則會被隔壁從門口吸走。
    # 只看建築牆體範圍內、比門寬更開闊的區塊：門口的寬度不到 2*cap，會把房間斷開。
    seeds = list(seeds)
    seed_px = np.zeros_like(free)
    for y, x in markers.values():
        seed_px[y, x] = True
    reach = max(1, round(_AUTO_CORE * _OPEN_CAP * bdiag))
    min_core = _MIN_AUTO_FRAC * building.sum()
    # 區塊往外沿空地擴一個門檻寬度（涵蓋牆邊、角落）內有點就算已有種子：
    # Gemini 的點常落在門邊或家具旁，不在核心區塊裡；沿空地擴、不穿牆也不穿窗，才不會數到隔壁的點
    seeded_cores: set[int] = set()
    candidates: list[tuple[int, tuple]] = []
    core_seeds: dict[int, list[int]] = {}
    slices = ndi.find_objects(core_lab)
    for c, sl in enumerate(slices, 1):
        if sl is None:
            continue
        comp = core_lab == c
        box = tuple(slice(max(0, a.start - reach), a.stop + reach) for a in sl)
        basin = ndi.binary_dilation(comp[box], iterations=reach, mask=free[box] & ~soft_line[box])
        inside = [i for i, (y, x) in markers.items()
                  if box[0].start <= y < box[0].stop and box[1].start <= x < box[1].stop
                  and basin[y - box[0].start, x - box[1].start]]
        if inside:
            seeded_cores.add(c)
            core_seeds[c] = inside
        elif comp.sum() >= min_core:
            candidates.append((c, sl))
    # 從牆外吸進來、沒寫房名的點落在已有其他點的區塊旁：多半是標在牆上的雜點，拿掉
    for c, ids in core_seeds.items():
        extra = [i for i in ids if i in snapped_ids and not seeds[i - 1].get("label")]
        if extra and len(extra) < len(ids):
            for i in extra:
                markers.pop(i, None)
            core_seeds[c] = [i for i in ids if i not in extra]
    # Gemini 在凸窗、被窗線隔開的邊條裡多放的點（沒寫房名）會把房間切開：
    # 那塊若是隔壁有點房間的凹處，就拿掉這些點，讓它併回那間房
    for c, ids in core_seeds.items():
        if any(seeds[i - 1].get("label") for i in ids):
            continue
        if _is_alcove(core_lab == c, slices[c - 1], core_lab, seeded_cores - {c}, free, soft_line, reach):
            for i in ids:
                markers.pop(i, None)
            seeded_cores.discard(c)
    for c, sl in candidates:
        comp = core_lab == c
        # 只隔著窗戶線緊鄰一塊有點、而且大很多的區塊（凸窗、被窗線隔開的房間邊條）：
        # 是那間房的一部分，不另外成房
        if _is_alcove(comp, sl, core_lab, seeded_cores, free, soft_line, reach):
            continue
        y, x = np.unravel_index(int(np.argmax(np.where(comp, dist, -1))), comp.shape)
        seeds.append({"label": "", "room_type": "other", "space_type": "other", "auto": True})
        markers[len(seeds)] = (int(y), int(x))
    if not markers:
        return None

    lab = _flood(free, prio, markers)

    wall_px = max(2, _WALL_KERNEL + 1)
    rooms: list[dict[str, Any]] = []
    for i in markers:
        reg = lab == i
        if reg.mean() < _MIN_ROOM_FRAC:
            continue
        reg = ndi.binary_fill_holes(ndi.binary_opening(reg, structure=_disk(1)))
        if not reg.any():
            continue
        reg = _largest(reg)
        # 外擴一層牆厚，裁切時保留牆線讓後續家具解析有房間邊界可對照
        shell = ndi.binary_fill_holes(reg | (ndi.binary_dilation(reg, iterations=wall_px) & wall))
        # 外擴的牆可能帶進不相連的碎片；輪廓追蹤從第一個像素起跑，會只追到碎片
        shell = _largest(shell)
        outline = _simplify([(float(x), float(y)) for y, x in _trace_outline(shell)], eps=1.5)
        sy, sx = np.nonzero(shell)
        # 離邊界最遠的點，保證落在房內（L 型房的幾何中心可能在房外），給前端放標籤
        ay, ax = np.unravel_index(int(np.argmax(ndi.distance_transform_edt(reg))), reg.shape)
        seed = seeds[i - 1]
        rooms.append({
            "id": f"room_{len(rooms) + 1}",
            "room_type": seed.get("room_type", "other"),
            "space_type": seed.get("space_type", seed.get("room_type", "other")),
            "label": seed.get("label", ""),
            "x": sx.min() / W,
            "y": sy.min() / H,
            "w": (sx.max() + 1 - sx.min()) / W,
            "h": (sy.max() + 1 - sy.min()) / H,
            "polygon": [[round(x / W, 4), round(y / H, 4)] for x, y in outline],
            "anchor": [round(ax / W, 4), round(ay / H, 4)],
        })
    return rooms or None


def merge_room_shapes(rooms: list[dict], res: int = 1200) -> dict[str, Any]:
    """把幾間房的多邊形聯集成一個（標號辨識判定為同一間房時用），
    回傳新的 x/y/w/h、polygon、anchor。座標皆為 0–1 正規化。"""
    from PIL import ImageDraw

    canvas = Image.new("L", (res, res), 0)
    draw = ImageDraw.Draw(canvas)
    for r in rooms:
        draw.polygon([(x * res, y * res) for x, y in r["polygon"]], fill=255)
    mask = np.asarray(canvas) > 0
    # 兩塊之間沒有牆時邊界會留一條縫，先閉合再取最大塊
    mask = _largest(ndi.binary_fill_holes(ndi.binary_closing(mask, structure=_disk(3))))
    outline = _simplify([(float(x), float(y)) for y, x in _trace_outline(mask)], eps=1.5)
    ys, xs = np.nonzero(mask)
    ay, ax = np.unravel_index(int(np.argmax(ndi.distance_transform_edt(mask))), mask.shape)
    return {
        "x": xs.min() / res, "y": ys.min() / res,
        "w": (xs.max() + 1 - xs.min()) / res, "h": (ys.max() + 1 - ys.min()) / res,
        "polygon": [[round(x / res, 4), round(y / res, 4)] for x, y in outline],
        "anchor": [round(ax / res, 4), round(ay / res, 4)],
    }
