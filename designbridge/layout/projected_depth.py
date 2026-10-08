"""Project a scene graph into a ControlNet depth/seg map."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from designbridge.layout.layout_items import FurnitureItem, _DEPTH_SKIP_TYPES
from designbridge.layout.layout_enforce import _clip_to_room
from designbridge.layout.floorplan_render import _generate_floor_plan


def _write_projection_meta(res: dict, task_id: str) -> None:
    """把投影後每件家具在影像上的實際位置寫到深度圖旁邊。

    深度圖本身是灰階、不帶身分；renderer 靠這份 JSON 才能讓 prompt 裡的「沙發在左邊」
    對準深度圖上真正屬於沙發的那一塊，並剔除投影後根本不在畫面內的家具。
    """
    instances = (res.get("meta") or {}).get("instances")
    if not instances:
        return
    out = Path(Config.ARTIFACTS_DIR) / "layout" / f"{task_id}_projection.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps({"instances": instances}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        print(f"⚠️ 投影 meta 寫入失敗（{e}）")


def _generate_projected_depth(
    items: list[FurnitureItem],
    space_info: dict,
    task_id: str,
    vision_features: dict[str, Any] | None = None,
    output_size: tuple[int, int] | None = None,
    preserve_types: frozenset[str] = frozenset(),
    preserve_mask: Any = None,
) -> tuple[str | None, str | None, str]:
    """Project furniture boxes into a perspective depth map (+ segmentation) for ControlNet.

    Three modes, in priority order — the first two composite the furniture onto the
    photo's own depth map, so camera angle, room proportions and the architecture
    (windows, doors, corners) all come from the original photo:

      1. photo_anchored — the floor/wall junction is visible, so the plan→image mapping
         is a homography fitted straight to it. Most accurate.
      2. photo_camera   — the junction is hidden behind furniture (the common case for
         real interiors); the floor trapezoid is reconstructed from the depth map's
         vanishing line and far-wall distance instead.
      3. synthetic      — no usable photo geometry: fall back to the fixed pinhole camera
         over an empty room box sized from space_info.

    Returns (depth_path, seg_path, mode).
    """
    if not Config.ENABLE_LAYOUT_DEPTH_PROJECTION:
        return None, None, "disabled"

    out_dir = Path(Config.ARTIFACTS_DIR) / "layout"
    depth_out = out_dir / f"{task_id}_projected_depth.png"
    seg_out = out_dir / f"{task_id}_projected_seg.png"
    placements = [item.to_dict() for item in items]

    vision = vision_features or {}
    photo_depth = vision.get("depth")
    photo_seg = vision.get("segmentation")
    photo_seg_meta = vision.get("segmentation_meta")
    can_anchor = (
        Config.LAYOUT_PHOTO_ANCHORED_DEPTH
        and all(p and Path(str(p)).is_file() for p in (photo_depth, photo_seg, photo_seg_meta))
    )

    if can_anchor:
        try:
            from designbridge.layout.scene_graph_to_depth import project_layout_onto_photo

            res = project_layout_onto_photo(
                placements,
                str(photo_depth), str(photo_seg), str(photo_seg_meta),
                depth_out,
                seg_out_path=seg_out,
                eye_height=Config.LAYOUT_CAMERA_EYE_HEIGHT,
                output_size=output_size,
                preserve_types=preserve_types,
                preserve_mask=preserve_mask,
            )
            if res is not None:
                mode = "photo_anchored"
                if str((res.get("meta") or {}).get("horizon_source", "")).startswith("camera:"):
                    mode = "photo_camera"
                _write_projection_meta(res, task_id)
                return res.get("depth_path"), res.get("seg_path"), mode
            print("[layout_agent] 照片地板幾何無法求解，退回合成相機投影")
        except Exception as e:
            print(f"⚠️ Photo-anchored depth projection failed ({e}), falling back to synthetic camera")

    try:
        from designbridge.layout.scene_graph_to_depth import (
            normalize_furniture_type,
            project_scene_graph_to_depth,
        )

        # 用正規化後的 type 比對——原本直接比 i.type，"platform_bed"/"floor_lamp" 這類
        # LLM 自由文字標籤永遠對不上短鍵，會被整件排除在深度圖之外。
        anchor_items = [
            i for i in items
            if normalize_furniture_type(i.type) not in _DEPTH_SKIP_TYPES
        ] or items
        res = project_scene_graph_to_depth(
            [item.to_dict() for item in anchor_items],
            space_info,
            depth_out,
            image_size=output_size or (1024, 1024),
            seg_out_path=seg_out,
            camera_overrides={
                "hfov_deg": Config.LAYOUT_PROJECTION_HFOV,
                "pitch_deg": Config.LAYOUT_PROJECTION_PITCH,
                "setback": Config.LAYOUT_PROJECTION_SETBACK,
            },
        )
        _write_projection_meta(res, task_id)
        return res.get("depth_path"), res.get("seg_path"), "synthetic"
    except Exception as e:
        print(f"⚠️ Projected depth generation failed: {e}")
        return None, None, "failed"


def reproject_scene_graph(
    scene_graph: dict[str, Any],
    space_info: dict[str, Any],
    task_id: str,
    output_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Re-run the floor-plan/depth-projection step against `furniture_placements` that
    may have been hand-edited by the user in the 3D preview (drag to reposition).

    This is pure NumPy rasterization, not an LLM call — cheap to redo. It has to be
    redone whenever we resume from a pre-seeded scene_graph, because `projected_depth_path`
    is what actually reaches ControlNet; skipping this would silently render the
    original AI-planned positions even after the user dragged furniture around.
    """
    placements = scene_graph.get("furniture_placements") or []
    items = [
        FurnitureItem(
            id=str(p.get("id", "")),
            type=str(p.get("type", "default")),
            x=float(p.get("x", 0)), y=float(p.get("y", 0)),
            w=float(p.get("w", 0.1)), h=float(p.get("h", 0.1)),
            rotation=float(p.get("rotation", 0.0)),
        )
        for p in placements
    ]
    items = _clip_to_room(items)

    # 房間尺寸沿用 Step 1 畫平面圖時用的那組；缺了就退回 space_info。用預設 4x4 會讓
    # 重新投影的長寬比與使用者當初看到的 3D 預覽對不上，家具位置整體偏移。
    _size = (space_info or {}).get("estimated_size") or {}
    room_w = float(scene_graph.get("room_w") or _size.get("width", 4.0) or 4.0)
    room_d = float(scene_graph.get("room_d") or _size.get("depth", 4.0) or 4.0)
    room_type = str(scene_graph.get("room_type") or "living_room")

    floor_plan_path = _generate_floor_plan(
        items, task_id, room_type=room_type, room_w=room_w, room_d=room_d
    )
    projected_depth_path, projected_seg_path, projection_mode = _generate_projected_depth(
        items, space_info, task_id, output_size=output_size or (1024, 1024)
    )

    return {
        **scene_graph,
        "furniture_placements": [item.to_dict() for item in items],
        "floor_plan_path": floor_plan_path,
        "projected_depth_path": projected_depth_path,
        "projected_seg_path": projected_seg_path,
        "projection_mode": projection_mode,
    }
