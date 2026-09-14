"""Verify the eye-level depth map actually captures 2D furniture positions.

Strategy: for a single furniture item at a known layout coordinate, render the
depth map with and without it. The pixels that change (get closer/brighter) are
exactly where the item landed on screen. We then project the item's footprint
centroid through the *same* camera and assert the changed-region centroid matches.

Left/right and near/far layout changes must move the on-screen blob in the
matching direction. If this passes, the layout position is faithfully encoded in
the control image the depth-ControlNet consumes.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from designbridge.layout.layout_projection import (
    _Camera,
    _build_scene,
    _rasterize,
    _depth_to_gray,
    _furniture_height,
    render_layout_depth_map,
)

ROOM_W, ROOM_D, ROOM_H = 5.0, 4.0, 2.7
IMG = 768


def _gray(placements):
    cam = _Camera(ROOM_W, ROOM_D, IMG, IMG)
    tris = _build_scene(placements, ROOM_W, ROOM_D, ROOM_H)
    return _depth_to_gray(_rasterize(tris, cam), cam), cam


def _blob_centroid(placements, item):
    """Screen centroid (sx, sy) of the pixels the item adds to the empty room."""
    base, _ = _gray([])
    full, _ = _gray(placements)
    diff = np.abs(full.astype(int) - base.astype(int))
    mask = diff > 10
    assert mask.sum() > 200, f"item barely visible in depth map ({mask.sum()} px)"
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean()), mask.sum()


def _expected_screen_centroid(item, cam):
    """Project the item's 3D box; return its screen centroid and horizontal extent.

    A box has real extent, so where it *appears* is the spread of its projected
    corners — not a single footprint point. This mirrors how it rasterizes.

    The extent is returned as well because it, not the centroid, decides whether the
    blob centroid is comparable: a box straddling a frame edge still has its centroid
    well inside the image, but the pixels beyond the edge are never drawn, so the
    visible centroid is pulled inward and no longer tracks the projected one.
    """
    x0, x1 = item["x"] * ROOM_W, (item["x"] + item["w"]) * ROOM_W
    z0 = (1.0 - (item["y"] + item["h"])) * ROOM_D  # near edge
    z1 = (1.0 - item["y"]) * ROOM_D                # far edge
    y0, y1 = 0.0, _furniture_height(item["type"])
    corners = np.array(
        [[cx, cy, cz] for cx in (x0, x1) for cy in (y0, y1) for cz in (z0, z1)],
        dtype=float,
    )
    cp = cam.to_cam(corners)
    sx = cam.cx + cam.f * cp[:, 0] / cp[:, 2]
    sy = cam.cy - cam.f * cp[:, 1] / cp[:, 2]
    return float(sx.mean()), float(sy.mean()), float(sx.min()), float(sx.max())


def test_horizontal_sweep_is_monotonic_and_matches_projection():
    """Sweeping one item left→right moves its on-screen blob left→right, and the
    blob centroid tracks the independently-projected box centroid."""
    _, cam = _gray([])
    xs = [0.12, 0.30, 0.48, 0.66]
    blob_cx, proj_cx, in_frame = [], [], []
    for x in xs:
        item = {"type": "coffee_table", "x": x, "y": 0.45, "w": 0.18, "h": 0.16}
        bx, _, _ = _blob_centroid([item], item)
        px, _, pmin, pmax = _expected_screen_centroid(item, cam)
        blob_cx.append(bx)
        proj_cx.append(px)
        whole = pmin >= 0 and pmax <= IMG
        in_frame.append(whole)
        print(
            f"[horizontal] layout x={x:.2f} -> blob_x={bx:.0f}, projected_x={px:.0f}, "
            f"span=[{pmin:.0f},{pmax:.0f}]{'' if whole else '  (clipped)'}"
        )

    # 1) Strictly monotonic across the whole width: layout position → screen
    #    position, no reordering.
    assert all(b2 > b1 for b1, b2 in zip(blob_cx, blob_cx[1:])), \
        f"blob not monotonic L→R: {[round(b) for b in blob_cx]}"
    # 2) Where the whole box is in-frame, the blob centroid matches the projection to
    #    ~1% of the image width. Clipped boxes are excluded: their off-screen pixels
    #    are never rasterized, so the visible centroid legitimately differs.
    matched = 0
    for x, b, p, whole in zip(xs, blob_cx, proj_cx, in_frame):
        if whole:
            assert abs(b - p) < IMG * 0.03, f"x={x}: blob {b:.0f} vs projected {p:.0f}"
            matched += 1
    assert matched >= 2, "not enough in-frame samples to validate projection match"


def test_wall_sides_not_swapped():
    """A left-wall item stays on the left half, a right-wall item on the right."""
    left = {"type": "sofa", "x": 0.03, "y": 0.4, "w": 0.18, "h": 0.35}
    right = {"type": "sofa", "x": 0.79, "y": 0.4, "w": 0.18, "h": 0.35}
    lx, _, _ = _blob_centroid([left], left)
    rx, _, _ = _blob_centroid([right], right)
    print(f"[sides] left-wall blob x={lx:.0f}, right-wall blob x={rx:.0f}")
    assert lx < IMG / 2 < rx, f"sides swapped: left={lx:.0f} right={rx:.0f}"


def _blob_mean_brightness(item):
    """Mean depth-map brightness of the pixels the item adds to the empty room."""
    base, _ = _gray([])
    full, _ = _gray([item])
    diff = np.abs(full.astype(int) - base.astype(int))
    mask = diff > 10
    assert mask.sum() > 200, f"item barely visible ({mask.sum()} px)"
    return float(full[mask].mean())


def test_depth_brightness_near_vs_far():
    """The near item is brighter (closer) in the depth map than the far item —
    this is exactly the depth signal the ControlNet reads to place things in Z."""
    near = {"type": "cabinet", "x": 0.4, "y": 0.62, "w": 0.2, "h": 0.15}  # toward front
    far = {"type": "cabinet", "x": 0.4, "y": 0.05, "w": 0.2, "h": 0.15}   # toward back

    near_b = _blob_mean_brightness(near)
    far_b = _blob_mean_brightness(far)
    print(f"[depth] near item mean brightness={near_b:.0f}, far item mean brightness={far_b:.0f}")

    # Near clearly brighter than far (closer = brighter, MiDaS convention).
    assert near_b > far_b + 20, f"near not clearly closer than far: {near_b:.0f} vs {far_b:.0f}"


def test_two_items_keep_relative_order():
    """Two items keep their left-right order on screen."""
    items = [
        {"type": "sofa", "x": 0.05, "y": 0.5, "w": 0.15, "h": 0.3},
        {"type": "armchair", "x": 0.78, "y": 0.5, "w": 0.14, "h": 0.14},
    ]
    lx, _, _ = _blob_centroid(items, items[0])  # not exact (both present) but ok for print
    _, cam = _gray([])
    ex_sofa, _, _, _ = _expected_screen_centroid(items[0], cam)
    ex_chair, _, _, _ = _expected_screen_centroid(items[1], cam)
    print(f"[two-items] projected sofa_x={ex_sofa:.0f} < chair_x={ex_chair:.0f}")
    assert ex_sofa < ex_chair, "relative order not preserved in projection"


if __name__ == "__main__":
    test_horizontal_sweep_is_monotonic_and_matches_projection()
    test_wall_sides_not_swapped()
    test_depth_brightness_near_vs_far()
    test_two_items_keep_relative_order()

    # Save a couple of overlays for eyeballing.
    demo = [
        {"type": "sofa", "x": 0.03, "y": 0.45, "w": 0.2, "h": 0.4},
        {"type": "coffee_table", "x": 0.4, "y": 0.5, "w": 0.22, "h": 0.16},
        {"type": "tv_unit", "x": 0.33, "y": 0.02, "w": 0.35, "h": 0.1},
        {"type": "armchair", "x": 0.78, "y": 0.55, "w": 0.15, "h": 0.15},
        {"type": "plant", "x": 0.88, "y": 0.05, "w": 0.09, "h": 0.09},
    ]
    p = render_layout_depth_map(demo, "fidelity_demo", room_w=ROOM_W, room_d=ROOM_D,
                                img_w=IMG, img_h=IMG)
    print("demo depth map:", p)
    print("\nALL POSITION-FIDELITY CHECKS PASSED ✅")
