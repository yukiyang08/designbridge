"""離線建立 IKEA 商品 3D 模型庫（product_meshes 的資料來源）。

兩種來源：
  official（預設，免費）：下載 IKEA 官方 3D 檢視器的模型，本身就是真實尺寸，只需置中
  hunyuan（每件 $0.48）：商品頁抓尺寸 → 商品圖丟 fal Hunyuan3D 生成 → 擺正、縮放到真實尺寸
都輸出 {sku}.glb（前端）與 {sku}_lo.npz（深度投影），寫進 manifest.json。

用法：
  python -m designbridge.layout.product_mesh_build                          # 官方模型，有的全部下載
  python -m designbridge.layout.product_mesh_build --source hunyuan --category sofa --limit 3
  python -m designbridge.layout.product_mesh_build --skus 50541595 --force
  python -m designbridge.layout.product_mesh_build --renormalize            # 只重跑擺正/縮放，不重新生成
  python -m designbridge.layout.product_mesh_build --set-yaw 50541595=180   # 人工修正正面方向
  python -m designbridge.layout.product_mesh_build --preview                # 四視角縮圖供檢查方向
"""

from __future__ import annotations

import argparse
import html as html_lib
import io
import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Any

import numpy as np

from designbridge.core.config import Config

KB_PATH = Path(__file__).parent.parent / "furniture_kb" / "ikea_tw.json"
HUNYUAN_ENDPOINT = "fal-ai/hunyuan3d/v2"
# IKEA 官方 3D 檢視器（rotera）的資料端點；client id 寫在 ikea.com 前端程式裡
ROTERA_BASE = "https://web-api.ikea.com/tw/zh/rotera"
ROTERA_CLIENT_ID = "4863e7d2-1428-4324-890b-ae5dede24fc6"
OFFICIAL_SOURCE = "ikea_rotera"
LO_FACE_COUNT = 6000
# 官方模型的面數本來就控制得不錯（中位數約 9k），大多不減面；減面會把細結構跟
# 分開的零件拉出大片錯誤三角形。只有超過這個數的少數大型組合才減
OFFICIAL_LO_FACE_COUNT = 80000
# 地毯是平面，image-to-3D 只會生出垃圾；也不進深度圖
SKIP_CATEGORIES = {"rug"}
# 背面要靠牆、以「最高的那一側＝椅背/床頭」判斷正面的類別
BACKREST_CATEGORIES = {"sofa", "chair", "bed"}
DEFAULT_HEIGHT_M = {"sofa": 0.85, "chair": 0.85, "bed": 0.9, "table": 0.75,
                    "storage": 1.2, "lamp": 1.5}


# ── 商品資料 ─────────────────────────────────────────────────────────────────

def sku_from_url(url: str) -> str:
    m = re.search(r"(\d{8})/?(?:[?#].*)?$", url or "")
    return m.group(1) if m else ""


def parse_dims_cm(page_html: str) -> dict[str, float]:
    """商品頁「尺寸」區塊的 {標籤: 公分}。頁面下方還有其他商品的尺寸，只取第一個區塊。"""
    text = re.sub(r"<[^>]+>", "|", page_html)
    text = html_lib.unescape(re.sub(r"\s+", " ", text))
    text = re.sub(r"(\| ?)+", "|", text)
    start = text.find("|尺寸|")
    if start < 0:
        return {}
    block = text[start + 3:start + 1200]
    # 後面緊接的是平整包裝（紙箱）尺寸，不能混進來
    end = re.search(r"\|[^|]*包裝|\|Close\|", block)
    if end:
        block = block[:end.start()]
    dims: dict[str, float] = {}
    for label, val in re.findall(r"\|([^|:：]{1,12})[:：]\s*\|?\s*(\d+(?:\.\d+)?)\s*公分", block):
        dims.setdefault(label.strip(), float(val))
    return dims


def dims_to_m(dims_cm: dict[str, float], category: str) -> list[float | None] | None:
    """{標籤: 公分} → [寬, 深, 高]（公尺）。寬 = 沿牆方向／較長邊。

    高度可能是 None（只有床墊尺寸的床框），此時由模型本身的比例決定。
    """
    d = dims_cm
    height = d.get("高度") or d.get("總高度") or d.get("床頭板高度")
    diameter = d.get("燈罩直徑") or d.get("直徑") or d.get("底座直徑")
    if category == "bed":
        w, dep = d.get("寬度"), d.get("長度") or d.get("深度")
        if not (w and dep) and d.get("床墊寬度") and d.get("床墊長度"):
            # 只標床墊尺寸：床框每邊約多 5 公分
            w, dep = d["床墊寬度"] + 10, d["床墊長度"] + 10
    elif "寬度" in d and "深度" in d:
        w, dep = d["寬度"], d["深度"]
    elif "長度" in d and "寬度" in d:
        w, dep = max(d["長度"], d["寬度"]), min(d["長度"], d["寬度"])
    elif diameter:
        w = dep = diameter
    else:
        w, dep = d.get("寬度") or d.get("長度"), d.get("深度")
    if not (w and dep):
        return None
    return [round(w / 100, 3), round(dep / 100, 3), round(height / 100, 3) if height else None]


def fetch_dims(url: str) -> dict[str, float]:
    import requests

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    resp.raise_for_status()
    return parse_dims_cm(resp.text)


def _product_png(image_url: str) -> bytes:
    """抓商品圖（先試較大的 S5），轉成白底 PNG。"""
    import requests
    from PIL import Image

    for url in (image_url.replace("_S4.", "_S5."), image_url):
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            bg.alpha_composite(img)
            buf = io.BytesIO()
            bg.convert("RGB").save(buf, format="PNG")
            return buf.getvalue()
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError(f"商品圖下載失敗：{image_url}")


def _rotera_get(path: str):
    import requests

    return requests.get(f"{ROTERA_BASE}/{path}", timeout=60, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json;version=2",
        "x-client-id": ROTERA_CLIENT_ID,
    })


def official_model_exists(sku: str) -> bool:
    resp = _rotera_get(f"data/exists/{sku}/")
    return resp.status_code == 200 and bool(resp.json().get("exists"))


def download_official_glb(sku: str, out_path: Path) -> bool:
    """官方模型是 Draco 壓縮＋WebP 貼圖的 GLB，讀取需要 DracoPy。

    exists 說有、檔案卻 404 的情況存在（部分燈具），回傳 False 當作沒有官方模型。
    """
    resp = _rotera_get(f"static/models/{sku}-mini.glb")
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
    return True


def generate_raw_glb(image_url: str, out_path: Path, seed: int = 0) -> None:
    import fal_client
    import requests

    os.environ["FAL_KEY"] = Config.FAL_KEY
    uploaded = fal_client.upload(_product_png(image_url), content_type="image/png")
    result = fal_client.subscribe(HUNYUAN_ENDPOINT, arguments={
        "input_image_url": uploaded, "textured_mesh": True, "seed": seed,
    }, with_logs=False)
    resp = requests.get(result["model_mesh"]["url"], timeout=180)
    resp.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)


# ── 擺正與縮放（glTF 座標：Y 上、正面 +Z）──────────────────────────────────────

def _rot_y(deg: float) -> np.ndarray:
    t = math.radians(deg)
    c, s = math.cos(t), math.sin(t)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


def _xz_after(v: np.ndarray, deg: float) -> np.ndarray:
    return (v @ _rot_y(deg)[:3, :3].T)[:, [0, 2]]


def align_yaw(v: np.ndarray) -> float:
    """讓俯視外框面積最小的旋轉角（0~90°）—— 家具多半是方的，這樣邊會對齊軸。"""
    pts = v[:, [0, 2]]
    try:
        from scipy.spatial import ConvexHull
        pts = pts[ConvexHull(pts).vertices]
    except Exception:  # noqa: BLE001
        pass
    best, best_area = 0.0, float("inf")
    for deg in np.arange(0.0, 90.0, 1.0):
        xz = _xz_after(np.c_[pts[:, 0], np.zeros(len(pts)), pts[:, 1]], deg)
        ext = xz.max(axis=0) - xz.min(axis=0)
        area = float(ext[0] * ext[1])
        if area < best_area - 1e-9:
            best, best_area = float(deg), area
    return best


def bed_turn(v: np.ndarray, base_deg: float) -> float:
    """床：長邊沿 Z（往相機延伸），床頭那端（尾端帶狀區較高）在 -Z。

    床頭板常常只比床墊高一點，「最高的部分」會被整片床墊稀釋，所以改比兩端的高度。
    """
    best_k, best_h = 0, -float("inf")
    for k in range(4):
        r = v @ _rot_y(base_deg + 90 * k)[:3, :3].T
        ext = r.max(axis=0) - r.min(axis=0)
        if ext[2] < ext[0]:
            continue
        zmin = r[:, 2].min()
        band = r[:, 2] < zmin + 0.12 * ext[2]
        h = float(np.percentile(r[band, 1], 90)) if band.any() else -float("inf")
        if h > best_h:
            best_k, best_h = k, h
    return 90.0 * best_k


def backrest_turn(v: np.ndarray, base_deg: float) -> float:
    """再轉 0/90/180/270 讓椅背/床頭落在 -Z，正面朝 +Z。

    椅背是家具最高的部分：取高度前 25% 的頂點，它們的水平重心偏向哪一側，哪一側就是背。
    """
    y = v[:, 1]
    high = v[y > y.min() + 0.75 * (y.max() - y.min())]
    if len(high) == 0:
        return 0.0
    best_k, best_off = 0, float("inf")
    for k in range(4):
        rot = _rot_y(base_deg + 90 * k)[:3, :3]
        z_all = (v @ rot.T)[:, 2]
        center, extent = (z_all.max() + z_all.min()) / 2, max(z_all.max() - z_all.min(), 1e-9)
        off = float(((high @ rot.T)[:, 2].mean() - center) / extent)
        if off < best_off:
            best_k, best_off = k, off
    return 90.0 * best_k


def normalize_transform(v: np.ndarray, category: str, dims_m: list[float] | None,
                        extra_yaw: float = 0.0, trust_geometry: bool = False) -> tuple[np.ndarray, float]:
    """回傳 (4x4 轉換, 總 yaw)。轉換後：底面中心在原點、X=寬、Z=深、Y=高（公尺），正面朝 +Z。

    trust_geometry：官方模型已是真實尺寸與固定朝向，不自動旋轉、不縮放，只置中。
    """
    if trust_geometry:
        rot = _rot_y(extra_yaw)
        r = v @ rot[:3, :3].T
        lo, hi = r.min(axis=0), r.max(axis=0)
        t = np.eye(4)
        t[:3, 3] = -np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        return t @ rot, extra_yaw % 360.0
    yaw = align_yaw(v)
    if category == "bed":
        yaw += bed_turn(v, yaw)
    elif category in BACKREST_CATEGORIES:
        yaw += backrest_turn(v, yaw)
    else:
        xz = _xz_after(v, yaw)
        ext = xz.max(axis=0) - xz.min(axis=0)
        if ext[0] < ext[1]:   # 寬 = 較長邊
            yaw += 90.0
    yaw += extra_yaw
    rot = _rot_y(yaw)
    r = v @ rot[:3, :3].T
    lo, hi = r.min(axis=0), r.max(axis=0)
    ext = np.maximum(hi - lo, 1e-6)
    if dims_m:
        sx, sz = dims_m[0] / ext[0], dims_m[1] / ext[2]
        # 沒有高度時沿用模型自己的比例
        sy = dims_m[2] / ext[1] if dims_m[2] else (sx + sz) / 2
        scale = np.array([sx, sy, sz])
    else:
        scale = np.full(3, DEFAULT_HEIGHT_M.get(category, 0.8) / ext[1])
    center = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    t = np.eye(4)
    t[:3, 3] = -center
    s = np.diag([*scale, 1.0])
    return s @ t @ rot, yaw % 360.0


def _scene_meshes(scene: Any) -> list:
    """場景內每個幾何（已套 node 轉換）。"""
    out = []
    for node in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node]
        geom = scene.geometry[geom_name].copy()
        geom.apply_transform(transform)
        out.append(geom)
    return out


def _vertex_colors(mesh: Any) -> np.ndarray:
    try:
        visual = mesh.visual
        # 貼圖 → 在每個頂點的 UV 取樣；本來就是顏色的直接用（ColorVisuals 沒有 to_color）
        cols = visual.to_color().vertex_colors if hasattr(visual, "to_color") else visual.vertex_colors
        if cols is not None and len(cols) == len(mesh.vertices):
            return np.asarray(cols)[:, :3].astype(np.uint8)
    except Exception:  # noqa: BLE001
        pass
    return np.full((len(mesh.vertices), 3), 170, dtype=np.uint8)


def _simplify_part(v: np.ndarray, f: np.ndarray, c: np.ndarray, target: int):
    """單一零件減面。先焊接頂點：Draco 解出來的網格在 UV 接縫處是斷開的，
    不焊接的話減面會沿著裂縫拉出橫跨整件家具的大三角形。"""
    try:
        import fast_simplification
        import trimesh
        from scipy.spatial import cKDTree
    except ImportError:
        print("⚠️ 未安裝 fast-simplification，lo 網格不減面（深度投影會較慢）")
        return v, f, c
    m = trimesh.Trimesh(vertices=v, faces=f, process=False)
    m.merge_vertices(merge_tex=True, merge_norm=True)
    if len(m.faces) <= target:
        v2, f2 = np.asarray(m.vertices), np.asarray(m.faces)
    else:
        v2, f2 = fast_simplification.simplify(
            np.asarray(m.vertices, dtype=np.float32), np.asarray(m.faces, dtype=np.int32),
            target_reduction=1.0 - target / len(m.faces),
        )
    _, nn = cKDTree(v).query(v2)
    return v2, f2, c[nn]


def build_lo(scene: Any, face_count: int = LO_FACE_COUNT) -> dict[str, np.ndarray]:
    """減面 + 頂點色，並從 glTF（Y 上、正面 +Z）轉成投影用世界座標（Z 上、正面 -Y）。

    超過 face_count 才減，而且每個零件各自按比例減，不跨零件合併。
    """
    parts = [(np.asarray(m.vertices), np.asarray(m.faces), _vertex_colors(m)) for m in _scene_meshes(scene)]
    total = sum(len(f) for _, f, _ in parts)
    if total > face_count:
        ratio = face_count / total
        parts = [_simplify_part(v, f, c, max(12, int(len(f) * ratio))) for v, f, c in parts]
    verts, faces, cols, offset = [], [], [], 0
    for v_p, f_p, c_p in parts:
        verts.append(v_p)
        faces.append(np.asarray(f_p) + offset)
        cols.append(c_p)
        offset += len(v_p)
    v = np.concatenate(verts)
    f = np.concatenate(faces)
    c = np.concatenate(cols)

    world = np.stack([v[:, 0], -v[:, 2], v[:, 1]], axis=1)
    return {"vertices": world.astype(np.float32), "faces": f.astype(np.int32), "colors": c.astype(np.uint8)}


def normalize_glb(raw_path: Path, out_dir: Path, sku: str, category: str,
                  dims_m: list[float] | None, extra_yaw: float = 0.0,
                  trust_geometry: bool = False, face_count: int = LO_FACE_COUNT) -> dict[str, Any]:
    import trimesh

    scene = trimesh.load(str(raw_path), force="scene")
    v = np.concatenate([np.asarray(m.vertices) for m in _scene_meshes(scene)])
    if not np.ptp(v, axis=0).any():
        raise RuntimeError("模型頂點全為 0（Draco 未解碼？請 pip install DracoPy）")
    transform, yaw = normalize_transform(v, category, dims_m, extra_yaw, trust_geometry)
    scene.apply_transform(transform)

    out_dir.mkdir(parents=True, exist_ok=True)
    if trust_geometry and np.allclose(transform, np.eye(4), atol=0.01):
        # 官方模型本來就置中落地；直接用原檔，保留 Draco 壓縮（trimesh 重存會大近 10 倍）
        shutil.copyfile(raw_path, out_dir / f"{sku}.glb")
    else:
        scene.export(str(out_dir / f"{sku}.glb"))
    lo = build_lo(scene, face_count)
    np.savez_compressed(out_dir / f"{sku}_lo.npz", **lo)
    ext = lo["vertices"].max(axis=0) - lo["vertices"].min(axis=0)
    return {"yaw": round(yaw, 1), "faces_lo": int(len(lo["faces"])),
            "mesh_dims_m": [round(float(x), 3) for x in ext]}


# ── 檢查用縮圖 ────────────────────────────────────────────────────────────────

def render_preview(sku: str, out_dir: Path, size: int = 320) -> Path:
    """四個角度（正面、右、背、左）各一格，正面那格應該看到座面/抽屜/門片。"""
    from PIL import Image, ImageDraw

    from designbridge.layout.camera_projection import CameraParams, LookAtCamera
    from designbridge.layout.product_meshes import ProductMesh
    from designbridge.layout.scene_graph_to_depth import rasterize_mesh

    data = np.load(out_dir / f"{sku}_lo.npz")
    v = data["vertices"]
    mesh = ProductMesh(sku, v, data["faces"], data["colors"],
                       tuple(float(x) for x in v.max(axis=0) - v.min(axis=0)))
    span = max(mesh.dims)
    # 相機站在模型正前方、略高往下看；房間只是讓相機有座標系，不畫牆
    room = span * 4.0
    params = CameraParams(eye_height=span * 0.9, setback=span * 1.2, target_h=mesh.dims[2] / 2,
                          target_depth_frac=(span * 1.2) / room, fov_v_deg=40.0)
    tiles = []
    for yaw, label in ((0, "front"), (90, "right"), (180, "back"), (-90, "left")):
        cam = LookAtCamera(room, room, size, size, params)
        zbuf = np.full((size, size), np.inf)
        idbuf = np.zeros((size, size), np.int32)
        colbuf = np.full((size, size, 3), 245.0, np.float32)
        rasterize_mesh(zbuf, idbuf, colbuf, cam, mesh, room / 2, span * 1.2, yaw, 1)
        tile = Image.fromarray(colbuf.clip(0, 255).astype(np.uint8))
        ImageDraw.Draw(tile).text((6, 6), label, fill=(200, 0, 0))
        tiles.append(tile)
    sheet = Image.new("RGB", (size * 4, size), (255, 255, 255))
    for i, t in enumerate(tiles):
        sheet.paste(t, (i * size, 0))
    path = out_dir / "preview" / f"{sku}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


# ── CLI ───────────────────────────────────────────────────────────────────────

def _load_manifest(out_dir: Path) -> dict[str, dict]:
    p = out_dir / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def _save_manifest(out_dir: Path, manifest: dict[str, dict]) -> None:
    p = out_dir / "manifest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def build_one(product: dict, out_dir: Path, manifest: dict[str, dict], *,
              force: bool = False, renormalize: bool = False, source: str = "official") -> bool:
    """建好（或已存在）回傳 True；官方沒有這件的模型回傳 False。"""
    sku = sku_from_url(product.get("url", ""))
    if not sku:
        print(f"⚠️ 無法從網址取得 SKU：{product.get('url')}")
        return False
    entry = manifest.get(sku) or {}
    official = source == "official"
    src_name = OFFICIAL_SOURCE if official else HUNYUAN_ENDPOINT
    raw = out_dir / "raw" / (f"{sku}_official.glb" if official else f"{sku}.glb")
    # 已經是同一來源就跳過；官方模型可以取代先前生成的
    if entry.get("ready") and entry.get("source") == src_name and not (force or renormalize):
        print(f"[skip] {sku} 已建好")
        return True
    if official and not raw.is_file() and not official_model_exists(sku):
        print(f"[none] {sku} 官方沒有 3D 模型")
        return False

    entry.update({"sku": sku, "name": product.get("name", ""), "category": product.get("category", ""),
                  "price": product.get("price"), "url": product.get("url"),
                  "image_url": product.get("image_url"), "source": src_name})
    if official:
        if not raw.is_file() or (force and not renormalize):
            print(f"[get] {sku} {entry['name'][:30]} ← IKEA 官方模型")
            if not download_official_glb(sku, raw):
                print(f"[none] {sku} 官方標示有模型，但檔案不存在")
                return False
        entry.update(normalize_glb(raw, out_dir, sku, entry["category"], None,
                                   float(entry.get("manual_yaw", 0.0)), trust_geometry=True,
                                   face_count=OFFICIAL_LO_FACE_COUNT))
        # 官方幾何本身就是商品尺寸，不必再抓商品頁
        entry["dims_m"] = list(entry["mesh_dims_m"])
        entry.pop("dims_estimated", None)
        entry["ready"] = True
        manifest[sku] = entry
        _save_manifest(out_dir, manifest)
        print(f"[ok] {sku} dims={entry['dims_m']} faces={entry['faces_lo']}")
        return True

    if "dims_cm" not in entry or force:
        try:
            entry["dims_cm"] = fetch_dims(product["url"])
        except Exception as e:  # noqa: BLE001
            print(f"⚠️ {sku} 尺寸抓取失敗（{e}）")
            entry["dims_cm"] = {}
    entry["dims_m"] = dims_to_m(entry["dims_cm"], entry["category"])
    entry.pop("dims_estimated", None)
    if not entry["dims_m"]:
        print(f"⚠️ {sku} 沒有完整尺寸 {entry['dims_cm']}，只依類別預設高度等比縮放")

    if not raw.is_file() or (force and not renormalize):
        print(f"[gen] {sku} {entry['name'][:30]} → {HUNYUAN_ENDPOINT}")
        generate_raw_glb(product["image_url"], raw)

    entry.update(normalize_glb(raw, out_dir, sku, entry["category"], entry["dims_m"],
                               float(entry.get("manual_yaw", 0.0))))
    if not entry["dims_m"] or entry["dims_m"][2] is None:
        entry["dims_m"] = list(entry["mesh_dims_m"])
        entry["dims_estimated"] = True
    entry["ready"] = True
    manifest[sku] = entry
    _save_manifest(out_dir, manifest)
    print(f"[ok] {sku} dims={entry['dims_m']} yaw={entry['yaw']} faces={entry['faces_lo']}")
    return True


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("official", "hunyuan"), default="official",
                    help="official = IKEA 官方模型（免費，預設）；hunyuan = fal 生成（每件 $0.48）")
    ap.add_argument("--category", action="append", help="只建這些類別（可重複）")
    ap.add_argument("--skus", nargs="*", default=[])
    ap.add_argument("--limit", type=int, default=0, help="每個類別最多幾件（0 = 不限）")
    ap.add_argument("--force", action="store_true", help="重新抓尺寸並重新生成模型")
    ap.add_argument("--renormalize", action="store_true", help="用既有 raw GLB 重跑擺正/縮放")
    ap.add_argument("--set-yaw", nargs="*", default=[], metavar="SKU=DEG",
                    help="在自動擺正後再多轉幾度，修正正面方向")
    ap.add_argument("--preview", action="store_true", help="輸出四視角縮圖到 meshes/preview/")
    args = ap.parse_args()

    out_dir = Path(Config.PRODUCT_MESH_DIR)
    manifest = _load_manifest(out_dir)
    products = json.loads(KB_PATH.read_text(encoding="utf-8"))
    by_sku = {sku_from_url(p.get("url", "")): p for p in products}

    if args.set_yaw:
        for spec in args.set_yaw:
            sku, deg = spec.split("=", 1)
            if sku not in manifest:
                print(f"⚠️ manifest 沒有 {sku}")
                continue
            manifest[sku]["manual_yaw"] = float(deg)
            src = "official" if manifest[sku].get("source") == OFFICIAL_SOURCE else "hunyuan"
            build_one(by_sku[sku], out_dir, manifest, renormalize=True, source=src)
            print(f"[preview] {render_preview(sku, out_dir)}")
        return

    if args.skus:
        todo = [by_sku[s] for s in args.skus if s in by_sku]
    else:
        todo, per_cat = [], {}
        for p in products:
            cat = p.get("category", "")
            # 地毯只是生成不好；官方有模型的照樣下載
            if (args.source == "hunyuan" and cat in SKIP_CATEGORIES) or (args.category and cat not in args.category):
                continue
            if args.limit and per_cat.get(cat, 0) >= args.limit:
                continue
            per_cat[cat] = per_cat.get(cat, 0) + 1
            todo.append(p)

    if args.preview and not (args.force or args.renormalize) and not args.skus and not args.category:
        for sku, e in manifest.items():
            if e.get("ready"):
                print(f"[preview] {render_preview(sku, out_dir)}")
        return

    built = missing = failed = 0
    for p in todo:
        try:
            if build_one(p, out_dir, manifest, force=args.force, renormalize=args.renormalize,
                         source=args.source):
                built += 1
                if args.preview:
                    print(f"[preview] {render_preview(sku_from_url(p['url']), out_dir)}")
            else:
                missing += 1
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"⚠️ {p.get('url')} 失敗：{e}")
    print(f"完成：{built} 件可用，{missing} 件沒有官方模型，{failed} 件失敗")


if __name__ == "__main__":
    main()
