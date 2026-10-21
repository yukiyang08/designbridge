import json

import numpy as np
import pytest
import trimesh

from designbridge.core.config import Config
from designbridge.layout import product_meshes
from designbridge.layout.layout_items import FurnitureItem
from designbridge.layout.product_mesh_build import (
    _rot_y,
    dims_to_m,
    normalize_glb,
    normalize_transform,
    parse_dims_cm,
)
from designbridge.layout.scene_graph_to_depth import project_scene_graph_to_depth


def _chair(backrest_at_plus_z: bool = True) -> trimesh.Trimesh:
    """座面 + 一側高椅背；glTF 座標（Y 上）。"""
    seat = trimesh.creation.box(extents=[0.6, 0.45, 0.6])
    seat.apply_translation([0, 0.225, 0])
    back = trimesh.creation.box(extents=[0.6, 0.5, 0.1])
    back.apply_translation([0, 0.7, 0.25 if backrest_at_plus_z else -0.25])
    m = trimesh.util.concatenate([seat, back])
    m.visual.vertex_colors = np.tile([200, 40, 40, 255], (len(m.vertices), 1))
    return m


def test_parse_dims_stops_before_package_dims():
    page = (
        "<h3>尺寸</h3><dl><dt>寬度:</dt><dd>236 公分</dd><dt>深度:</dt><dd>153 公分</dd>"
        "<dt>高度:</dt><dd>90 公分</dd></dl><h4>平整包裝尺寸及重量</h4>"
        "<dt>長度: </dt><dd>157 公分 </dd>"
    )
    dims = parse_dims_cm(page)
    assert dims == {"寬度": 236.0, "深度": 153.0, "高度": 90.0}
    assert dims_to_m(dims, "sofa") == [2.36, 1.53, 0.9]


def test_dims_bed_uses_length_as_depth_and_table_long_side_as_width():
    assert dims_to_m({"長度": 209, "寬度": 176, "床頭板高度": 100}, "bed") == [1.76, 2.09, 1.0]
    assert dims_to_m({"長度": 78, "寬度": 140, "高度": 74}, "table") == [1.4, 0.78, 0.74]
    assert dims_to_m({"寬度": 50}, "storage") is None
    # 只標床墊尺寸的床框：加框邊、高度交給模型比例
    assert dims_to_m({"床墊長度": 200, "床墊寬度": 150}, "bed") == [1.6, 2.1, None]


def test_normalize_puts_backrest_behind_and_scales_to_dims():
    m = _chair(backrest_at_plus_z=True)
    # 生成模型常見的狀況：斜轉 30°、尺度不對
    m.apply_transform(_rot_y(30.0))
    m.apply_scale(3.0)
    t, _ = normalize_transform(np.asarray(m.vertices), "chair", [0.7, 0.8, 1.0])
    v = trimesh.transform_points(m.vertices, t)
    lo, hi = v.min(axis=0), v.max(axis=0)
    np.testing.assert_allclose(hi - lo, [0.7, 1.0, 0.8], atol=0.02)
    assert abs(lo[1]) < 1e-6
    np.testing.assert_allclose([(lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2], [0, 0], atol=1e-6)
    # 椅背（最高的頂點）在 -Z 側 → 正面朝 +Z
    tall = v[:, 1] > 0.9
    assert v[tall, 2].mean() < 0


@pytest.fixture
def mesh_lib(tmp_path, monkeypatch):
    raw = tmp_path / "raw.glb"
    trimesh.Scene(_chair()).export(str(raw))
    info = normalize_glb(raw, tmp_path, "10000001", "chair", [0.7, 0.8, 1.0])
    manifest = {"10000001": {"sku": "10000001", "category": "chair", "name": "TEST",
                             "url": "https://www.ikea.com.tw/zh/products/dining-seating/upholstered-chairs/test-art-10000001",
                             "dims_m": [0.7, 0.8, 1.0], "ready": True, **info}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(Config, "PRODUCT_MESH_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "ENABLE_PRODUCT_MESHES", True)
    return tmp_path


def test_lo_mesh_is_world_z_up_front_minus_y(mesh_lib):
    m = product_meshes.load_mesh("10000001")
    assert m is not None
    np.testing.assert_allclose(m.dims, [0.7, 0.8, 1.0], atol=0.02)
    assert abs(m.vertices[:, 2].min()) < 1e-5
    tall = m.vertices[:, 2] > 0.9
    assert m.vertices[tall, 1].mean() > 0   # 椅背在 +Y（遠離相機），正面朝 -Y
    assert (m.colors[:, 0] > 150).all()


def test_assign_products_resizes_footprint_and_keeps_wall_contact(mesh_lib):
    # 背靠左牆的扶手椅
    item = FurnitureItem(id="a1", type="chair", x=0.02, y=0.4, w=0.12, h=0.15)
    assert product_meshes.assign_products([item], room_w=5.0, room_d=4.0) == 1
    assert item.product_id == "10000001"
    assert item.x == pytest.approx(0.02)
    # 背靠左右牆時，商品的寬沿著 y、深沿著 x
    assert item.w * 5.0 == pytest.approx(0.8)
    assert item.h * 4.0 == pytest.approx(0.7)
    assert item.to_dict()["product_id"] == "10000001"
    assert "product_id" not in FurnitureItem(id="b", type="sofa", x=0, y=0, w=0.1, h=0.1).to_dict()


def test_projection_writes_color_pass_and_product_mask(mesh_lib, tmp_path):
    item = FurnitureItem(id="a1", type="chair", x=0.4, y=0.1, w=0.14, h=0.2)
    product_meshes.assign_products([item], room_w=5.0, room_d=4.0)
    sofa = {"id": "s1", "type": "sofa", "x": 0.05, "y": 0.6, "w": 0.3, "h": 0.13}
    res = project_scene_graph_to_depth(
        [item.to_dict(), sofa], {"estimated_size": {"width": 5.0, "depth": 4.0, "height": 2.8}},
        tmp_path / "t_projected_depth.png", image_size=(256, 256), seg_out_path=tmp_path / "t_seg.png",
    )
    products = res["meta"]["products"]
    assert [p["sku"] for p in products] == ["10000001"]
    pid = products[0]["id"]
    from PIL import Image
    mask = np.array(Image.open(res["product_mask_path"]))
    color = np.array(Image.open(res["color_path"]))
    assert (mask == 255).sum() > 100
    # 只有綁商品的那件被標成商品，沒綁的沙發不算
    assert (res["id_map"][mask == 255] == pid).all()
    assert res["id_to_type"][pid] == "chair"
    # 商品像素用的是模型頂點色（紅），不是外殼的中性色
    px = color[mask == 255].astype(int)
    assert (px[:, 0] > px[:, 1] + 40).mean() > 0.9


def test_projection_without_products_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "ENABLE_PRODUCT_MESHES", False)
    res = project_scene_graph_to_depth(
        [{"id": "s1", "type": "sofa", "x": 0.05, "y": 0.6, "w": 0.3, "h": 0.13, "product_id": "x"}],
        {}, tmp_path / "u_projected_depth.png", image_size=(128, 128),
    )
    assert "color_path" not in res and "products" not in res["meta"]


def test_official_geometry_is_only_centered_not_rotated_or_scaled():
    m = _chair()
    m.apply_translation([0.3, 0.2, -0.1])
    t, yaw = normalize_transform(np.asarray(m.vertices), "chair", None, trust_geometry=True)
    v = trimesh.transform_points(m.vertices, t)
    np.testing.assert_allclose(np.ptp(v, axis=0), np.ptp(m.vertices, axis=0), atol=1e-9)
    assert abs(v[:, 1].min()) < 1e-9 and yaw == 0.0
    # 椅背仍在原本的 +Z 側：官方模型的朝向不動
    assert v[v[:, 1] > 0.9, 2].mean() > 0


def test_official_model_passthrough_and_missing_file(tmp_path, monkeypatch):
    from designbridge.layout import product_mesh_build as b

    raw = tmp_path / "raw" / "10000002_official.glb"
    raw.parent.mkdir()
    chair = _chair()
    chair.apply_translation([0, -chair.bounds[0][1], 0])
    trimesh.Scene(chair).export(str(raw))
    product = {"url": "https://www.ikea.com.tw/zh/products/x/y-art-10000002", "category": "chair", "name": "T"}
    manifest: dict = {}
    assert b.build_one(product, tmp_path, manifest, source="official")
    # 已置中落地的官方模型直接沿用原檔
    assert (tmp_path / "10000002.glb").read_bytes() == raw.read_bytes()
    assert manifest["10000002"]["source"] == b.OFFICIAL_SOURCE

    class _Resp:
        status_code = 404
    monkeypatch.setattr(b, "official_model_exists", lambda sku: True)
    monkeypatch.setattr(b, "_rotera_get", lambda path: _Resp())
    lamp = {"url": "https://www.ikea.com.tw/zh/products/x/z-art-10000003", "category": "lamp", "name": "L"}
    assert b.build_one(lamp, tmp_path, manifest, source="official") is False
    assert "10000003" not in manifest


class _FlatPhotoGeom:
    """固定的「照片」地板幾何：平面圖 [0,1]² 線性對到畫面下半部，深度近亮遠暗。"""
    eye_height = 1.5

    def plan_to_pixel(self, xy):
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        return np.stack([20 + xy[:, 0] * 216, 140 + xy[:, 1] * 110], axis=1)

    def floor_disparity(self, uv):
        return np.clip((np.asarray(uv)[:, 1] - 140) * 2.0, 0, 255)

    def horizon_v(self, u):
        return np.full(np.shape(u), 100.0)


def test_photo_mesh_survives_wall_tie_and_writes_color(mesh_lib):
    from designbridge.layout.scene_graph_to_depth import _add_mesh_on_photo

    mesh = product_meshes.load_mesh("10000001")
    h, w = 256, 256
    # 牆面 disparity 比擬合的地板平面在遠牆處還高：舊作法家具會整件被牆蓋掉
    zbuf = np.full((h, w), 30.0, dtype=np.float32)
    idbuf = np.zeros((h, w), dtype=np.int32)
    colbuf = np.zeros((h, w, 3), dtype=np.float32)
    _add_mesh_on_photo(zbuf, idbuf, colbuf, _FlatPhotoGeom(), mesh, 0.5, 0.05, 0.0, 4.0, 4.0, 7)
    assert (idbuf == 7).sum() > 200
    assert (colbuf[idbuf == 7][:, 0] > 100).mean() > 0.9


def test_projection_meta_keeps_products_and_camera(tmp_path, monkeypatch):
    """renderer 靠這份 meta 決定要不要用商品網格；合併時曾被覆寫掉商品欄位，整條功能靜默失效。"""
    from designbridge.layout.projected_depth import _write_projection_meta

    monkeypatch.setattr(Config, "ARTIFACTS_DIR", str(tmp_path))
    res = {
        "color_path": "c.png", "product_mask_path": "m.png",
        "meta": {"instances": [{"id": 4}], "products": [{"id": 4, "sku": "1"}],
                 "camera": {"fov_v_deg": 60}, "camera_score": 0.9},
    }
    _write_projection_meta(res, "t1")
    meta = json.loads((tmp_path / "layout" / "t1_projection.json").read_text(encoding="utf-8"))
    assert meta["color_path"] == "c.png" and meta["products"] == [{"id": 4, "sku": "1"}]
    assert meta["camera"] == {"fov_v_deg": 60}


def _entry(sku, category, path, dims, name="TEST"):
    return {"sku": sku, "category": category, "name": name, "ready": True, "dims_m": dims,
            "url": f"https://www.ikea.com.tw/zh/products/{path}/x-art-{sku}"}


def test_pick_product_respects_subcategory(tmp_path, monkeypatch):
    """收納類同時有開放層架和封閉櫃：衣櫃不能配到層架，書櫃不能配到封閉櫃。"""
    manifest = {
        "20000001": _entry("20000001", "storage", "sideboard-cabinets/open-storage", [1.0, 0.36, 1.8]),
        "20000002": _entry("20000002", "storage", "sideboard-cabinets/system-cabinets", [1.0, 0.4, 0.9]),
        "20000003": _entry("20000003", "chair", "cushions-throws-and-chairpads/chairpads", [0.4, 0.4, 0.85]),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(Config, "PRODUCT_MESH_DIR", str(tmp_path))
    assert product_meshes.pick_product("wardrobe", 1.0, 0.6) is None, "資料庫沒有衣櫃，不該配到層架"
    assert product_meshes.pick_product("bookshelf", 1.0, 0.36)["sku"] == "20000001"
    assert product_meshes.pick_product("cabinet", 1.0, 0.4)["sku"] == "20000002"
    assert product_meshes.pick_product("chair", 0.4, 0.4) is None, "椅墊不是椅子"


def test_bed_gets_unlocked_mattress_and_foreground_is_unlocked(mesh_lib, tmp_path, monkeypatch):
    from designbridge.layout import scene_graph_to_depth as sgd

    # 床：把測試用的椅子網格當成床框，確認多了床墊、而且床墊不在商品 mask 裡
    entry = json.loads((mesh_lib / "manifest.json").read_text(encoding="utf-8"))
    entry["10000001"].update(category="bed", url="https://www.ikea.com.tw/zh/products/beds/bed-frames/x-art-10000001")
    (mesh_lib / "manifest.json").write_text(json.dumps(entry), encoding="utf-8")
    bed = {"id": "b1", "type": "bed", "x": 0.42, "y": 0.02, "w": 0.16, "h": 0.17, "product_id": "10000001"}
    res = project_scene_graph_to_depth([bed], {"estimated_size": {"width": 5.0, "depth": 4.0, "height": 2.8}},
                                       tmp_path / "bed_projected_depth.png", image_size=(256, 256))
    mattress = [oid for oid, t in res["id_to_type"].items() if t == "_mattress"]
    assert mattress and (res["id_map"] == mattress[0]).any(), "床框要多一塊床墊"
    from PIL import Image
    mask = np.array(Image.open(res["product_mask_path"])) > 0
    assert not mask[res["id_map"] == mattress[0]].any(), "床墊交給 AI 畫，不能被鎖住"

    # 前景：外框貼著畫面下緣又很高的商品不鎖
    idbuf = np.zeros((100, 100), np.int32)
    idbuf[40:100, 30:60] = 7
    idbuf[10:20, 70:80] = 8
    ids = {7: "near", 8: "far"}
    sgd._drop_foreground_products(idbuf, ids)
    assert ids == {8: "far"}
