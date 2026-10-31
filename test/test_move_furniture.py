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


# ── 用自動切分的家具搬（list_instances / move_instances）─────────────────────
# 切分與 AI 重修都換成假的：用投影方塊當「切出來的家具」，_finish_move 只記下收到什麼

def _fake_instances(placements, size=SIZE):
    masks = _instance_masks(placements, SPACE, CAMERA, size)
    out = []
    for k, (pid, m) in enumerate(masks.items()):
        ys, xs = np.nonzero(m)
        y1 = int(ys.max()) + 1
        out.append({
            "index": k, "label": pid.split("_")[0], "mask": m, "movable": True,
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, y1],
            "contact": [float(xs[ys >= y1 - 3].mean()), float(y1 - 1)], "area": int(m.sum()), "depth": 100.0,
        })
    return out


@pytest.fixture
def staged(monkeypatch, tmp_path):
    from PIL import Image

    from designbridge.core.config import Config
    from designbridge.render import furniture_instances as fi
    from designbridge.render import move_furniture as mf

    monkeypatch.setattr(Config, "ARTIFACTS_DIR", str(tmp_path))
    captured = {}

    def finish(ctx, plan, new, composite, fill_mask, pasted, redraw, strength, changed):
        captured.update(new=new, composite=composite, fill=fill_mask, pasted=pasted, changed=changed)
        return {"changed": changed}

    monkeypatch.setattr(mf, "_finish_move", finish)

    def make(placements, camera=True):
        img = tmp_path / "prev.png"
        Image.new("RGB", SIZE, (200, 200, 200)).save(img)
        gen = {"output_size": {"width": SIZE[0], "height": SIZE[1]}, **({"layout_camera": CAMERA} if camera else {})}
        insts = _fake_instances(placements or _layout(0.30))
        monkeypatch.setattr(fi, "segment_furniture", lambda path, size=None, **kw: insts)
        plan = {"generated_image_path": str(img), "structured_requirement": {"space_info": SPACE},
                "scene_graph": {"furniture_placements": placements, "projection_mode": "synthetic"},
                "render_result": {"generation_params": gen}}
        return plan, insts

    return make, captured


def test_list_instances_matches_layout_and_writes_layers(staged):
    from pathlib import Path

    from designbridge.render.move_furniture import list_instances

    make, _ = staged
    plan, _ = make(_layout(0.30))
    data = list_instances(plan)
    got = {i["placement_id"] for i in data["instances"]}
    assert got == {"sofa_1", "cabinet_1"}
    assert all(Path(i["layer_path"]).is_file() and Path(i["patch_path"]).is_file() for i in data["instances"])
    assert 0 < data["horizon_y"] < min(i["anchor"]["y"] for i in data["instances"])


def test_move_instances_shifts_matched_furniture_only(staged):
    from designbridge.render.move_furniture import move_instances

    make, captured = staged
    plan, insts = make(_layout(0.30))
    sofa = next(i for i in insts if i["label"] == "sofa")
    u, v = sofa["contact"]
    move_instances(plan, [{"index": sofa["index"], "x": (u - 25) / SIZE[0], "y": v / SIZE[1]}])
    new = {p["id"]: p for p in captured["new"]}
    assert new["sofa_1"]["x"] < 0.30 and new["cabinet_1"]["x"] == 0.40
    assert captured["changed"]["moved"] == ["sofa_1"]
    assert captured["pasted"].any() and captured["fill"].any()


def test_move_instances_rejects_overlap(staged):
    from designbridge.render.move_furniture import MoveFurnitureError, move_instances

    make, _ = staged
    plan, insts = make(_layout(0.30))
    sofa = next(i for i in insts if i["label"] == "sofa")
    cab = next(i for i in insts if i["label"] == "cabinet")
    with pytest.raises(MoveFurnitureError):
        move_instances(plan, [{"index": sofa["index"], "x": cab["contact"][0] / SIZE[0], "y": cab["contact"][1] / SIZE[1]}])


def test_render_without_layout_uses_default_camera(staged):
    from designbridge.render.move_furniture import list_instances

    make, _ = staged
    plan, _ = make([], camera=False)                     # 沒排家具就生的圖：沒有投影相機也沒有 scene_graph 家具
    data = list_instances(plan)
    assert len(data["instances"]) == 2 and all(i["placement_id"] is None for i in data["instances"])
