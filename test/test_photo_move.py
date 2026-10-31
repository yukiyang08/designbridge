"""照片入口在原圖上搬家具（photo_move）。離線：地板幾何、inpaint、SAM 2 都用假的。"""
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from designbridge.layout import photo_move as pm

W, H = 200, 160


class FakeGeom:
    """沒有透視的地板：俯視 x → 影像 u，俯視 y（遠→近）→ 影像 v 下半部。"""
    image_size = (W // 2, H // 2)   # 故意跟照片不同解析度，驗證有換算

    def plan_to_pixel(self, xy):
        xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        return np.stack([xy[:, 0] * W / 2, H / 4 + xy[:, 1] * H / 4], axis=1)

    def lift(self, uv, height_m):
        uv = np.asarray(uv, dtype=float).reshape(-1, 2)
        return np.stack([uv[:, 0], uv[:, 1] - height_m * 10], axis=1)


def _item(i, x, y=0.5, w=0.2, h=0.2, **kw):
    return {"id": i, "type": "sofa", "x": x, "y": y, "w": w, "h": h, **kw}


def test_diff_layout_moved_removed_added():
    base = [_item("a", 0.1), _item("b", 0.5), _item("c", 0.7)]
    now = [_item("a", 0.1), _item("b", 0.3), _item("d", 0.4)]
    moved, removed, added = pm.diff_layout(base, now)
    assert [(o["id"], n["x"]) for o, n in moved] == [("b", 0.3)]
    assert [p["id"] for p in removed] == ["c"]
    assert [p["id"] for p in added] == ["d"]


def test_moved_box_follows_floor_anchor():
    old, new = _item("a", 0.1), _item("a", 0.4)
    box, s = pm.moved_box(FakeGeom(), old, new, (20, 100, 60, 140), (2.0, 2.0))
    assert s == pytest.approx(1.0)
    assert box == pytest.approx((80.0, 100.0, 120.0, 140.0))   # 俯視右移 0.3 → 影像右移 0.3*W


def _photo(tmp_path):
    img = np.full((H, W, 3), 200, dtype=np.uint8)
    img[100:140, 20:60] = (255, 0, 0)            # 紅色「沙發」
    p = tmp_path / "photo.png"
    Image.fromarray(img).save(p)
    return str(p)


def _fake_inpaint(calls):
    def run(src, mask, prompt, out):
        calls.append((prompt, np.asarray(mask) > 0))
        img = np.asarray(Image.open(src).convert("RGB")).copy()
        img[np.asarray(mask.resize((W, H))) > 0] = (90, 90, 90)   # 補成灰色背景
        Image.fromarray(img).save(out)
        return True
    return run


def test_move_pastes_same_pixels_at_new_place_and_clears_old(tmp_path):
    photo, calls = _photo(tmp_path), []
    detected = [_item("a", 0.1, image_box=[0.1, 100 / H, 0.3, 140 / H])]
    res = pm.move_furniture_in_photo(
        photo, FakeGeom(), detected, [_item("a", 0.1)], [_item("a", 0.4)],
        Path(tmp_path), "t", inpaint=_fake_inpaint(calls),
    )
    out = np.asarray(Image.open(res["image_path"]).convert("RGB"))
    assert res["pasted"] == 1 and len(calls) == 1
    assert tuple(out[120, 100]) == (255, 0, 0)     # 新位置是原本那塊紅色
    assert tuple(out[120, 40]) == (90, 90, 90)     # 舊位置已補成背景
    assert tuple(out[20, 180]) == (200, 200, 200)  # 房間其他地方完全沒動


def test_no_change_does_nothing(tmp_path):
    calls = []
    res = pm.move_furniture_in_photo(
        _photo(tmp_path), FakeGeom(), [], [_item("a", 0.1)], [_item("a", 0.1)],
        Path(tmp_path), "t", inpaint=_fake_inpaint(calls),
    )
    assert res["image_path"] is None and not calls


def test_added_furniture_is_generated_inside_its_floor_box(tmp_path):
    calls = []
    res = pm.move_furniture_in_photo(
        _photo(tmp_path), FakeGeom(), [], [], [_item("n", 0.6, type="plant")],
        Path(tmp_path), "t", inpaint=_fake_inpaint(calls), height_of=lambda t: 1.0,
    )
    assert res["added"] == 1 and "plant" in calls[-1][0]
    ys, xs = np.nonzero(calls[-1][1])
    # 俯視框 x∈[0.6,0.8] → u∈[120,160]；y∈[0.5,0.7] → 地面 v∈[120,136]，抬高 1m 到 v=100
    assert xs.min() >= 119 and xs.max() <= 161 and ys.min() >= 99 and ys.max() <= 137


def test_api_rejects_photo_without_floor(monkeypatch):
    import pytest as _pt
    from fastapi import HTTPException
    import designbridge.core.nodes as nodes
    import designbridge.layout.photo_geometry as pg
    import routers.floorplan as fp

    monkeypatch.setattr(fp, "_require_artifact_file", lambda *a, **k: None)
    monkeypatch.setattr(nodes, "visual_preprocessing_local",
                        lambda st: {"vision_features": {"depth": "d", "segmentation": "s", "segmentation_meta": "m"}})
    monkeypatch.setattr(pg, "resolve_floor_geometry", lambda *a, **k: None)
    req = fp.PhotoMoveRequest(photo_path="p", image_path="p", detected=[], baseline=[], placements=[])
    with _pt.raises(HTTPException) as e:
        fp.photo_move(req, user_id="")
    assert e.value.status_code == 422
