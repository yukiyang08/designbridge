"""移家具的合成步驟（不打 fal）：像素有搬到新位置、舊位置被補掉、沒動的家具不變。"""

import numpy as np
import pytest

from designbridge.layout.camera_projection import CameraParams
from designbridge.render.move_furniture import _changed_ids, _instance_masks, build_move_composite, fill_holes

SPACE = {"estimated_size": {"width": 5.0, "depth": 4.0, "height": 2.8}}
CAMERA = vars(CameraParams())
SIZE = (256, 256)


def _layout(sofa_x: float) -> list[dict]:
    return [
        {"id": "sofa_1", "type": "sofa", "x": sofa_x, "y": 0.70, "w": 0.30, "h": 0.20},
        {"id": "cabinet_1", "type": "cabinet", "x": 0.40, "y": 0.02, "w": 0.20, "h": 0.10},
    ]


def test_fill_holes_uses_surrounding_color():
    rgb = np.full((64, 64, 3), 120, dtype=np.uint8)
    hole = np.zeros((64, 64), dtype=bool)
    hole[20:40, 20:40] = True
    rgb[hole] = 0
    out = fill_holes(rgb, hole)
    assert np.abs(out[hole].astype(int) - 120).max() <= 2
    assert (out[~hole] == 120).all()


def test_changed_ids_detects_move_and_removal():
    old, new = _layout(0.05), _layout(0.60)[:1]
    moved, turned, removed, added = _changed_ids(old, new, 5.0, 4.0)
    assert moved == ["sofa_1"]
    assert removed == ["cabinet_1"]
    assert added == []


def test_composite_moves_pixels_and_keeps_rest():
    h, w = 120, 200
    image = np.full((h, w, 3), 200, dtype=np.uint8)
    sofa = np.zeros((h, w), dtype=bool); sofa[60:90, 20:60] = True
    cab = np.zeros((h, w), dtype=bool); cab[20:40, 140:180] = True
    image[sofa] = (200, 30, 30)       # 沙發塗紅
    image[cab] = (30, 30, 200)        # 櫃子塗藍
    empty = np.zeros((h, w), dtype=bool)

    # 錨點 (40, 90) → (110, 90)，同一深度不縮放：沙發整塊往右 70px
    out, fill, pasted = build_move_composite(
        image, {"sofa_1": sofa, "cabinet_1": cab}, {"sofa_1": (40, 90, 110, 90, 1.0)}, [], empty, {},
    )
    landed = np.zeros((h, w), dtype=bool); landed[60:90, 90:130] = True
    vacated = sofa & ~landed
    assert (out[landed] == (200, 30, 30)).all()                   # 新位置是原本的沙發像素
    assert out[vacated][:, 1].mean() > 150                        # 舊位置補回背景色
    assert (out[cab] == (30, 30, 200)).all() and not fill[cab].any()   # 沒動的櫃子不重畫
    assert fill[vacated].all()
    assert (pasted == landed).all() and not fill[landed].any()    # 貼上的沙發不進高強度補洞，另外交給低強度那段


def test_blend_feathers_outward_and_protects_pasted():
    from designbridge.render.move_furniture import blend_in

    base = np.full((60, 60, 3), 100, dtype=np.uint8)
    new = np.full((60, 60, 3), 10, dtype=np.uint8)
    mask = np.zeros((60, 60), dtype=bool); mask[20:40, 20:40] = True
    protect = np.zeros((60, 60), dtype=bool); protect[20:40, 41:50] = True
    out = blend_in(base, new, mask, protect=protect)
    assert (out[mask] == 10).all()                                # 遮罩內全用新圖，不往內柔化
    assert 10 < out[30, 18, 0] < 100                              # 遮罩外緣漸淡
    assert (out[protect] == 100).all() and (out[:5] == 100).all()  # 貼上的家具與遠處一律原像素


def test_upscaled_paste_is_sharpened():
    image = np.full((120, 200, 3), 200, dtype=np.uint8)
    sofa = np.zeros((120, 200), dtype=bool); sofa[60:90, 20:60] = True
    image[60:90, 20:60] = np.where((np.arange(40) // 4 % 2)[None, :, None] == 0, 40, 220)   # 條紋材質
    empty = np.zeros((120, 200), dtype=bool)
    plain, _, p1 = build_move_composite(image, {"s": sofa}, {"s": (40, 90, 130, 115, 1.0)}, [], empty, {})
    big, _, p2 = build_move_composite(image, {"s": sofa}, {"s": (40, 90, 130, 115, 1.6)}, [], empty, {})
    contrast = lambda img, m: float(np.abs(np.diff(img[..., 0].astype(int), axis=1))[m[:, 1:]].mean())
    assert contrast(big, p2) > 0.8 * contrast(plain, p1)          # 放大 1.6 倍後條紋對比沒有明顯變糊


def test_occluder_stays_in_front():
    h, w = 120, 200
    image = np.full((h, w, 3), 200, dtype=np.uint8)
    sofa = np.zeros((h, w), dtype=bool); sofa[60:90, 20:60] = True
    chair = np.zeros((h, w), dtype=bool); chair[70:100, 100:115] = True
    image[sofa] = (200, 30, 30)
    image[chair] = (30, 200, 30)
    out, _, _ = build_move_composite(
        image, {"sofa_1": sofa, "chair_1": chair}, {"sofa_1": (40, 90, 110, 90, 1.0)},
        [], np.zeros((h, w), dtype=bool), {"sofa_1": chair},
    )
    assert (out[chair] == (30, 200, 30)).all()


def test_refine_mask_follows_segmentation_not_box():
    from designbridge.render.move_furniture import refine_mask

    box = np.zeros((100, 100), dtype=bool); box[40:70, 40:70] = True
    seg = np.zeros((100, 100), dtype=np.int32)            # 0 = wall
    seg[45:75, 35:60] = 19                                # 真的椅子：偏左下、比方塊窄
    seg[40:70, 62:90] = 15                                # 旁邊的桌子
    m = refine_mask(box, seg, {0: "wall", 15: "table", 19: "chair"})
    assert m[60, 37] and m[72, 50]                        # 方塊外的椅子部分也剪到
    assert not m[50, 80]                                  # 不會帶到桌子
    assert (refine_mask(box, None, {}) == box).all()      # 分割不可用就退回方塊


def test_refine_mask_takes_pillows_with_the_bed():
    from designbridge.render.move_furniture import refine_mask

    box = np.zeros((100, 100), dtype=bool); box[30:80, 20:80] = True
    seg = np.zeros((100, 100), dtype=np.int32)
    seg[45:80, 20:80] = 7                                 # 床
    seg[35:45, 30:70] = 57                                # 枕頭疊在床頭
    seg[50:75, 82:95] = 10                                # 旁邊的床頭櫃：不是附屬物，不能帶走
    m = refine_mask(box, seg, {0: "wall", 7: "bed", 57: "pillow", 10: "cabinet"})
    assert m[40, 50] and m[60, 50]
    assert not m[60, 90]


@pytest.fixture
def no_seg(monkeypatch):
    # 空白測試圖跑語意分割、SAM 2 沒意義又慢，直接走投影方塊
    from designbridge.render import move_furniture as mf
    monkeypatch.setattr(mf._Context, "segmentation", lambda self: (None, {}))
    monkeypatch.setattr(mf, "precise_mask", lambda path, coarse, seg, labels: coarse)


def _plan(tmp_path, placements):
    from PIL import Image
    img = tmp_path / "prev.png"
    Image.new("RGB", SIZE, (200, 200, 200)).save(img)
    return {
        "generated_image_path": str(img),
        "structured_requirement": {"space_info": SPACE},
        "scene_graph": {"furniture_placements": placements, "projection_mode": "synthetic"},
        "render_result": {"generation_params": {"layout_camera": CAMERA, "output_size": {"width": SIZE[0], "height": SIZE[1]}}},
    }


def test_pick_then_drag_back_to_same_anchor_keeps_position(tmp_path, no_seg):
    from designbridge.render.move_furniture import drag_to_placements, pick_furniture

    plan = _plan(tmp_path, _layout(0.30))
    masks = _instance_masks(_layout(0.30), SPACE, CAMERA, SIZE)
    ys, xs = np.nonzero(masks["sofa_1"])
    picked = pick_furniture(plan, xs.mean() / SIZE[0], ys.mean() / SIZE[1])
    assert picked["id"] == "sofa_1"
    assert picked["layer"].startswith("data:image/png;base64,")
    assert 0 < picked["horizon_y"] < picked["anchor"]["y"]   # 地板上的點一定在地平線下方

    same = drag_to_placements(plan, "sofa_1", picked["anchor"]["x"], picked["anchor"]["y"])
    sofa = next(p for p in same if p["id"] == "sofa_1")
    assert abs(sofa["x"] - 0.30) < 0.01 and abs(sofa["y"] - 0.70) < 0.01
    assert all(p.get("front") for p in same)                 # 朝向全部釘住


def test_drag_moves_sofa_and_nothing_else(tmp_path, no_seg):
    from designbridge.render.move_furniture import drag_to_placements, pick_furniture

    plan = _plan(tmp_path, _layout(0.30))
    masks = _instance_masks(_layout(0.30), SPACE, CAMERA, SIZE)
    ys, xs = np.nonzero(masks["sofa_1"])
    a = pick_furniture(plan, xs.mean() / SIZE[0], ys.mean() / SIZE[1])["anchor"]
    moved = drag_to_placements(plan, "sofa_1", a["x"] + 0.15, a["y"])
    sofa, cab = moved
    assert sofa["x"] > 0.35
    assert cab["x"] == 0.40 and cab["y"] == 0.02
    m, turned, removed, added = _changed_ids(_layout(0.30), moved, 5.0, 4.0)
    assert m == ["sofa_1"] and not turned and not removed and not added


def test_drag_into_other_furniture_is_rejected(tmp_path, no_seg):
    from designbridge.render.move_furniture import MoveFurnitureError, _Context, drag_to_placements, pick_furniture

    layout = _layout(0.30) + [{"id": "rug_1", "type": "rug", "x": 0.1, "y": 0.3, "w": 0.6, "h": 0.5}]
    plan = _plan(tmp_path, layout)
    masks = _instance_masks(layout, SPACE, CAMERA, SIZE)
    ys, xs = np.nonzero(masks["sofa_1"])
    picked = pick_furniture(plan, xs.mean() / SIZE[0], ys.mean() / SIZE[1])
    assert [o["id"] for o in picked["obstacles"]] == ["cabinet_1"]   # 地毯不算障礙

    ctx = _Context(plan)
    cab = layout[1]
    u, v, _ = ctx.floor_anchor(ctx.lookat(), {"x": cab["x"], "y": cab["y"], "w": cab["w"], "h": cab["h"]})
    with pytest.raises(MoveFurnitureError):
        drag_to_placements(plan, "sofa_1", u / SIZE[0], v / SIZE[1])   # 拖到櫃子正上方
