# designbridge/layout_agent.py
"""Layout Agent: furniture placement planning with hard and soft constraints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from designbridge.core.config import Config
from designbridge.layout.layout_items import FURNITURE_SIZES, FurnitureItem, _normalize_ftype, _parse_llm_layout
from designbridge.layout.layout_enforce import _LAYOUT_ENFORCERS, _apply_hard_constraints, _build_semantic_gap_map, _clip_to_room, _enforce_immutable, _enforce_move_ops, _inject_bunk_bed_ladder, _is_underlay_type, _movable_indices, _optimize_positions, _overlaps, _push_apart, _score_soft_constraints, _touched_types, _weighted_score
from designbridge.layout.floorplan_render import _generate_floor_plan
from designbridge.layout.projected_depth import _generate_projected_depth
from designbridge.layout.layout_constraints import get_layout_constraint_registry


# ─────────────────────────── LLM Interface ───────────────────────────

def _call_llm_layout(prompt: str) -> list[FurnitureItem]:
    from designbridge.render.llm import call_llm

    text = call_llm(prompt, json_mode=True)
    data = _parse_llm_layout(text)
    furniture_list = (data or {}).get("furniture") or []
    if not furniture_list:
        return []

    items: list[FurnitureItem] = []
    for f in furniture_list:
        ftype = _normalize_ftype(f.get("type", "default"))
        if ftype == "default":
            print(f"[layout_agent] skip unknown furniture type: {f.get('type')!r}")
            continue
        x = max(0.0, min(0.95, float(f.get("x", 0.1))))
        y = max(0.0, min(0.95, float(f.get("y", 0.1))))
        # LLM 常把同一件家具用不同名字列兩次（"sofa" + "sofa_against_wall"）— 同型別、位置相近就去重
        if any(d.type == ftype and abs(d.x - x) < 0.06 and abs(d.y - y) < 0.06 for d in items):
            continue
        dw, dh = FURNITURE_SIZES.get(ftype, FURNITURE_SIZES["default"])
        items.append(
            FurnitureItem(
                id=str(f.get("id", f"{ftype}_{len(items)+1}")),
                type=ftype,
                x=x,
                y=y,
                w=float(f.get("w", dw)),
                h=float(f.get("h", dh)),
                rotation=float(f.get("rotation", 0)),
            )
        )
    return items


# ───────────────────────── Default Fallback Layouts ───────────────────────────

def _default_layout(room_type: str) -> list[FurnitureItem]:
    presets: dict[str, list[FurnitureItem]] = {
        "living_room": [
            FurnitureItem("sofa_1", "sofa", 0.10, 0.58, 0.30, 0.13),
            FurnitureItem("coffee_table_1", "coffee_table", 0.18, 0.46, 0.15, 0.10),
            FurnitureItem("tv_unit_1", "tv_unit", 0.28, 0.08, 0.22, 0.07),
            FurnitureItem("armchair_1", "armchair", 0.52, 0.52, 0.11, 0.11),
            FurnitureItem("rug_1", "rug", 0.08, 0.42, 0.38, 0.24),
            FurnitureItem("plant_1", "plant", 0.76, 0.10, 0.06, 0.06),
        ],
        "bedroom": [
            FurnitureItem("bed_1", "bed", 0.30, 0.28, 0.22, 0.28),
            FurnitureItem("wardrobe_1", "wardrobe", 0.08, 0.08, 0.18, 0.08),
            FurnitureItem("nightstand_1", "nightstand", 0.24, 0.35, 0.07, 0.07),
            FurnitureItem("nightstand_2", "nightstand", 0.55, 0.35, 0.07, 0.07),
            FurnitureItem("dresser_1", "dresser", 0.68, 0.08, 0.14, 0.09),
        ],
        "kitchen": [
            FurnitureItem("cabinet_1", "cabinet", 0.05, 0.05, 0.30, 0.08),
            FurnitureItem("shelf_1", "shelf", 0.65, 0.05, 0.18, 0.05),
        ],
        "dining_room": [
            FurnitureItem("dining_table_1", "dining_table", 0.30, 0.38, 0.20, 0.15),
            FurnitureItem("chair_1", "chair", 0.22, 0.40, 0.08, 0.08),
            FurnitureItem("chair_2", "chair", 0.52, 0.40, 0.08, 0.08),
            FurnitureItem("chair_3", "chair", 0.35, 0.30, 0.08, 0.08),
            FurnitureItem("chair_4", "chair", 0.35, 0.52, 0.08, 0.08),
        ],
        "study": [
            FurnitureItem("desk_1", "desk", 0.32, 0.08, 0.16, 0.09),
            FurnitureItem("chair_1", "chair", 0.37, 0.18, 0.08, 0.08),
            FurnitureItem("bookshelf_1", "bookshelf", 0.08, 0.08, 0.10, 0.05),
            FurnitureItem("bookshelf_2", "bookshelf", 0.08, 0.15, 0.10, 0.05),
            FurnitureItem("armchair_1", "armchair", 0.65, 0.55, 0.11, 0.11),
            FurnitureItem("side_table_1", "side_table", 0.62, 0.53, 0.07, 0.07),
        ],
    }
    return list(presets.get(room_type, presets["living_room"]))


# ─────────────────────────── Main Entry Point ───────────────────────────

def _format_existing_layout(existing_layout: dict | None) -> str:
    """Turn photo-extracted layout (depth_to_layout output) into readable current-arrangement text.

    Gives the LLM the current furniture positions so it can adjust from the real layout
    (e.g. "sofa is on the right") instead of re-planning from scratch.
    """
    if not existing_layout:
        return "（無現有佈局資料，請依需求自由規劃家具位置）"
    candidates = existing_layout.get("furniture_candidates") or []
    if not candidates:
        return "（無法從照片辨識既有家具，請依需求自由規劃）"
    lines = []
    for c in candidates:
        t = c.get("type", "unknown")
        pos = c.get("position", "unknown")
        size = c.get("size_ratio", 0.0)
        conf = c.get("confidence", "")
        lines.append(f"- {t} 目前位於 {pos}（畫面佔比 {size:.0%}，可信度 {conf}）")
    return "\n".join(lines)


_DISPLAY_NAMES: dict[str, str] = {
    "tv_unit": "TV console",
    "nightstand": "nightstand",
    "ceiling_lamp": "pendant ceiling light",
    "pendant_light": "pendant ceiling light",
    "wall_lamp": "wall sconce",
    "wall_shelf": "wall-mounted shelf",
    "lamp": "floor lamp",
}


def _display_name(ftype: str) -> str:
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    key = normalize_furniture_type(ftype)
    if key in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[key]
    return key.replace("_", " ")


def _describe_ceiling_position(item: "FurnitureItem") -> str:
    """吊掛／壁掛物件的左右方位（沒有地板 footprint，深度投影管不到，只能用文字）。
    x：0 左→1 右。落地家具的方位一律交給 renderer.py 的 _furniture_to_spatial_text
    （用真實座標算，這裡不再重算一次，避免兩邊對不上互相矛盾）。"""
    cx = item.x + item.w / 2.0
    lateral = "on the left" if cx < 0.34 else ("on the right" if cx > 0.66 else "in the centre")
    return f"overhead {lateral}"


_WALL_ZH: dict[str, str] = {
    "far": "遠牆（畫面深處）", "near": "近牆（觀看者側）",
    "left": "左牆", "right": "右牆",
}


def _format_openings(openings: Any, kind: str) -> str:
    """Window/door boxes → prose with the actual plan coordinates spelled out.

    Dumping the raw JSON left the planner to parse `{"x":0.0,"y":0.3,...}` itself; giving
    it the coordinate range in the same frame as the output schema is what makes
    "move the desk next to the window" resolvable rather than guessed.
    """
    if not openings:
        return f"（照片判讀不到{kind}位置——規劃時不要假設任何一面牆上有{kind}）"
    lines: list[str] = []
    for op in openings:
        if not isinstance(op, dict):
            continue
        x, y = float(op.get("x", 0.0)), float(op.get("y", 0.0))
        w, h = float(op.get("w", 0.1)), float(op.get("h", 0.1))
        wall = _WALL_ZH.get(str(op.get("wall") or ""), "牆面")
        lines.append(
            f"- {wall}：俯視座標 x {x:.2f}~{x + w:.2f}、y {y:.2f}~{y + h:.2f}"
        )
    return "\n".join(lines) if lines else f"（無{kind}資料）"


def _format_move_ops(move_ops: Any) -> str:
    """must_move 清單 → 給 LLM 讀的條列文字。"""
    if not move_ops:
        return "無"
    lines: list[str] = []
    for op in move_ops:
        if not isinstance(op, dict):
            lines.append(f"- {op}")
            continue
        target = str(op.get("target") or "").strip()
        if not target:
            continue
        qualifier = str(op.get("qualifier") or "").strip()
        dest = str(op.get("to") or "").strip() or "使用者指定的新位置"
        which = f"（指定：{qualifier}）" if qualifier else ""
        lines.append(f"- {target}{which} → 移到 {dest}")
    return "\n".join(lines) if lines else "無"


def _classify_preserved(
    items: list["FurnitureItem"], constraints: dict[str, Any] | None = None
) -> frozenset[str]:
    """哪些家具 type 應該原地保留照片裡的真實深度。

    規則：出現在規劃結果裡、且使用者完全沒提到要動的那些。使用者沒說要動的東西
    就不該被清掉再用合成長方體近似——那會丟失照片裡的真實幾何。

    這條規則同時吸收了 LA 的漂移：即使 LLM 擅自把沒被要求變動的家具挪了位置，
    保留原始像素會讓那個漂移不生效，正是我們要的行為。
    """
    from designbridge.layout.scene_graph_to_depth import normalize_furniture_type

    touched = _touched_types(constraints)
    planned = {normalize_furniture_type(it.type) for it in items}
    return frozenset(planned - touched)


def _build_layout_prompt(
    items: list["FurnitureItem"], constraints: dict[str, Any] | None = None
) -> str:
    """由規劃結果生成 additive 的佈局描述。

    只描述 diffusion 沒有其他管道能得知的東西：
      - 吊掛／壁掛物件：不進深度投影（沒有地板 footprint），文字是唯一通道
      - 使用者要求新增的家具：深度圖有了，但文字加強能顯著提高出現率（只提物件名稱，
        不重複算方位——renderer.py 的 _furniture_to_spatial_text 已經用真實座標算過
        一次全部落地家具的方位，這裡再用粗略的三區間估一次只會兩邊對不上、互相矛盾）
    既有的落地家具不列舉——深度圖已經精確控制它們，長清單只會稀釋 prompt。
    """
    from designbridge.layout.scene_graph_to_depth import is_floor_standing, normalize_furniture_type

    constraints = constraints or {}
    # 保持 must_add 的原始順序並去重，否則 prompt 每次生成的字序會不一樣
    must_add: list[str] = []
    for s in constraints.get("must_add") or []:
        key = normalize_furniture_type(s)
        if key not in must_add:
            must_add.append(key)

    hanging: list[str] = []
    floor_by_type: dict[str, list[FurnitureItem]] = {}
    for item in items:
        if not is_floor_standing(item.type):
            hanging.append(
                f"a {_display_name(item.type)} {_describe_ceiling_position(item)}"
            )
        else:
            floor_by_type.setdefault(normalize_furniture_type(item.type), []).append(item)

    # 每個 must_add 類型只講一次：正規化會讓 low_cabinet 與 cabinet 撞在一起，
    # 全部列出來會把同一個需求重複描述。優先取原始 type 完全吻合的那件。
    added: list[str] = []
    for key in must_add:
        candidates = floor_by_type.get(key)
        if not candidates:
            continue
        chosen = next((it for it in candidates if it.type == key), candidates[0])
        added.append(f"a {_display_name(chosen.type)}")

    parts: list[str] = []
    if added:
        parts.append("The room must include " + ", ".join(added) + ".")
    if hanging:
        parts.append("Also visible: " + ", ".join(hanging) + ".")
    return " ".join(parts)


def run_layout_agent(
    structured_requirement: dict[str, Any],
    task_id: str,
    existing_layout: dict[str, Any] | None = None,
    vision_features: dict[str, Any] | None = None,
    output_size: tuple[int, int] | None = None,
    image_path: str | None = None,
) -> dict[str, Any]:
    """
    Run layout planning. Returns a partial state dict (scene_graph, intermediate_outputs).
    NOTE: intermediate_outputs is NOT pre-merged — callers must merge with existing state.
    NOTE: layout_prompt only carries what the depth projection cannot express — hanging /
          wall-mounted pieces and the user's explicitly requested additions. Enumerating
          every floor piece degrades diffusion quality, so it is deliberately left out.
          Floor plan PNG is used for ControlNet only when ENABLE_LAYOUT_CONTROLNET=true.
    existing_layout: photo-extracted current arrangement (state["layout_from_depth"]); when
          present, the planner adjusts from it rather than re-planning from scratch.
    vision_features: state["vision_features"] — depth/segmentation of the uploaded photo.
          When available the projected depth is anchored to the photo's own floor plane
          instead of a synthetic camera, so the render keeps the original spatial layout.
    output_size: (width, height) the renderer will request from the image model. The projected
          depth map must be built at this same aspect ratio, or the ControlNet control image gets
          mismatched against the render canvas and the uncovered margins render as unconstrained
          (unrelated) content instead of room geometry. Defaults to a square canvas.
    """
    from designbridge.core.prompts import LAYOUT_AGENT_PROMPT, LAYOUT_REFINEMENT_PROMPT
    from designbridge.core.timing import log_stage

    layout_registry = get_layout_constraint_registry()
    meta = structured_requirement.get("meta") or {}
    space_info = structured_requirement.get("space_info") or {}
    constraints = structured_requirement.get("layout_constraints") or {}
    user_description = (
        structured_requirement.get("design_description")
        or structured_requirement.get("user_description_raw")
        or ""
    )
    room_type = meta.get("room_type", "living_room")
    max_iter = Config.LAYOUT_MAX_ITER
    existing_layout_text = _format_existing_layout(existing_layout)

    def _build_prompt(extra: str = "") -> str:
        return LAYOUT_AGENT_PROMPT.format(
            room_type=room_type,
            width=space_info.get("estimated_size", {}).get("width", 5.0),
            depth=space_info.get("estimated_size", {}).get("depth", 4.0),
            windows=_format_openings(space_info.get("windows"), "窗戶"),
            doors=_format_openings(space_info.get("doors"), "門"),
            must_keep=", ".join(constraints.get("must_keep") or []) or "無",
            must_add=", ".join(constraints.get("must_add") or []) or "無",
            must_remove=", ".join(constraints.get("must_remove") or []) or "無",
            must_move=_format_move_ops(constraints.get("must_move")),
            immutable_regions=json.dumps(
                constraints.get("immutable_regions") or [], ensure_ascii=False
            ),
            existing_layout=existing_layout_text,
            user_description=user_description + ("\n" + extra if extra else ""),
        )

    # Initial layout from LLM — the only network-bound step in this function; everything
    # below is local numpy/pycairo, so if /api/generate-layout feels slow this is where to look.
    try:
        with log_stage("layout_agent.llm_layout", task_id=task_id):
            items = _call_llm_layout(_build_prompt())
        if not items:
            raise ValueError("empty response")
    except Exception as e:
        print(f"⚠️ LLM layout failed ({e}), using default layout")
        items = _default_layout(room_type)

    best_items: list[FurnitureItem] = []
    best_score = -1.0
    scores: dict[str, float] = {}
    scores_history: list[float] = []
    SCORE_THRESHOLD = 0.65

    # `photo_anchored` decides whether untouched furniture is frozen: with a photo those
    # pieces keep their original depth pixels regardless of what the plan says.
    _vf_probe = vision_features or {}
    photo_anchored = bool(
        Config.LAYOUT_PHOTO_ANCHORED_DEPTH
        and all(
            _vf_probe.get(k) and Path(str(_vf_probe[k])).is_file()
            for k in ("depth", "segmentation", "segmentation_meta")
        )
    )

    def _settle(seq: list[FurnitureItem]) -> list[FurnitureItem]:
        """Hard constraints and enforcers, in the order that keeps each other's work."""
        seq = _apply_hard_constraints(seq, constraints)
        seq = _enforce_move_ops(seq, constraints, space_info)
        immutable = constraints.get("immutable_regions") or []
        if immutable:
            seq = _enforce_immutable(seq, immutable)
        seq = _clip_to_room(seq)
        seq = _inject_bunk_bed_ladder(seq)
        seq = _push_apart(seq)
        for card in layout_registry.load():
            fn = _LAYOUT_ENFORCERS.get(card.enforce)
            if fn:
                seq = fn(seq, space_info, card.parameters)
        from designbridge.layout.special_constraints import apply_special_layout_constraints
        seq = apply_special_layout_constraints(seq, structured_requirement)
        # The enforcers above snap pieces to walls and push them off doors, which can
        # create overlaps the earlier `_push_apart` had already resolved. Without this
        # second pass those survive into the scene graph and `collision_free` reports
        # False on a layout nothing tried to fix.
        seq = _push_apart(seq)
        return _clip_to_room(seq)

    # One LLM call for the semantics (which pieces, roughly where), then a numeric search
    # for the geometry. Re-prompting the LLM with five scalars — the old refinement loop —
    # cost a round trip per iteration and gave it nothing to act on; the optimizer
    # evaluates thousands of candidates in a fraction of that and is reproducible.
    def _clone(seq: list[FurnitureItem]) -> list[FurnitureItem]:
        """Copy preserving `pinned`, which `to_dict` deliberately does not serialize."""
        out = [FurnitureItem(**it.to_dict()) for it in seq]
        for src, dst in zip(seq, out):
            dst.pinned = src.pinned
        return out

    items = _settle(items)
    baseline = _clone(items)
    before = _weighted_score(_score_soft_constraints(items, space_info))
    scores_history.append(before)

    movable = _movable_indices(items, constraints, photo_anchored)
    with log_stage("layout_agent.optimize_positions", task_id=task_id):
        items, _obj, accepted = _optimize_positions(
            items, space_info, movable, steps=Config.LAYOUT_OPTIMIZER_STEPS
        )
    items = _settle(items)
    total = _weighted_score(_score_soft_constraints(items, space_info))

    # The optimizer maximises the objective, but `_settle` runs again afterwards to
    # re-pin move targets and re-apply the wall/gap enforcers, and those can undo part of
    # the gain. Measure both layouts after the same settling and keep the better one, so
    # optimising can never hand back something worse than it was given.
    if total < before:
        print(f"[layout_agent] optimizer 後 settle 反而變差（{before:.3f} → {total:.3f}），保留原佈局")
        items = baseline
        total = before

    scores = _score_soft_constraints(items, space_info)
    total = _weighted_score(scores)
    scores_history.append(total)
    best_score = total
    best_items = _clone(items)

    print(
        f"[layout_agent] optimizer: {len(movable)}/{len(items)} 件可動"
        f"（{'照片錨定，其餘凍結' if photo_anchored else '無照片，全部可動'}）"
        f" steps={Config.LAYOUT_OPTIMIZER_STEPS} accepted={accepted}"
        f"  score {before:.3f} → {total:.3f}"
    )
    print(
        f"[layout_agent] circ={scores['circulation']:.2f} bal={scores['balance']:.2f} "
        f"foc={scores['focal_point']:.2f} light={scores['natural_light']:.2f} "
        f"erg={scores['ergonomics']:.2f}"
    )

    # Optional: fall back to the old LLM refinement when the optimizer cannot reach the
    # threshold. Off by default — a low score usually means the *initial plan* was wrong
    # (missing or mis-sized pieces), which another geometric nudge cannot fix either.
    if Config.LAYOUT_LLM_REFINE and total < SCORE_THRESHOLD:
        for _ in range(max(0, max_iter - 1)):
            try:
                refined = _call_llm_layout(
                    _build_prompt(LAYOUT_REFINEMENT_PROMPT.format(**scores))
                )
            except Exception:
                break
            if not refined:
                break
            refined = _settle(refined)
            refined, _o, _a = _optimize_positions(
                refined, space_info,
                _movable_indices(refined, constraints, photo_anchored),
                steps=Config.LAYOUT_OPTIMIZER_STEPS,
            )
            refined = _settle(refined)
            scores = _score_soft_constraints(refined, space_info)
            total = _weighted_score(scores)
            scores_history.append(total)
            print(f"[layout_agent] llm refine → score={total:.3f}")
            if total > best_score:
                best_score = total
                best_items = _clone(refined)
            if total >= SCORE_THRESHOLD:
                break

    acceptance_rate = (
        sum(1 for s in scores_history if s >= SCORE_THRESHOLD) / len(scores_history)
        if scores_history else 0.0
    )
    print(
        f"[layout_agent] passes={len(scores_history)} "
        f"best={best_score:.3f} acceptance_rate={acceptance_rate:.2%}"
    )

    from designbridge.layout.special_constraints import verify_special_constraints
    special_satisfaction = verify_special_constraints(best_items, structured_requirement)
    infeasible_constraints = [k for k, v in special_satisfaction.items() if not v]
    feasible = not infeasible_constraints
    if infeasible_constraints:
        print(
            f"[layout_agent] ⚠️  infeasible after convergence: {infeasible_constraints}"
        )

    # Hard constraint satisfaction report
    must_keep_set = {s.lower().replace(" ", "_") for s in (constraints.get("must_keep") or [])}
    must_add_set = {s.lower().replace(" ", "_") for s in (constraints.get("must_add") or [])}
    must_remove_set = {s.lower().replace(" ", "_") for s in (constraints.get("must_remove") or [])}
    existing = {item.type for item in best_items}

    _lc_params = {c.enforce: c.parameters for c in layout_registry.load()}
    _wa_params = _lc_params.get("wall_anchor", {})
    _wall_anchored = set(_wa_params.get("wall_anchored", []))
    _snap_threshold = float(_wa_params.get("snap_threshold", 0.12))
    _gap_map = _build_semantic_gap_map(_lc_params.get("semantic_gaps", {}))

    constraint_check = {
        "must_keep_satisfied": all(t in existing for t in must_keep_set),
        "must_add_satisfied": all(t in existing for t in must_add_set),
        "must_remove_satisfied": all(t not in existing for t in must_remove_set),
        "collision_free": not any(
            _overlaps(best_items[i], best_items[j])
            for i in range(len(best_items))
            for j in range(i + 1, len(best_items))
            if not (_is_underlay_type(best_items[i].type) or _is_underlay_type(best_items[j].type))
        ),
        "wall_anchored": all(
            min(item.x, 1.0 - item.x - item.w, item.y, 1.0 - item.y - item.h) <= _snap_threshold
            for item in best_items if item.type in _wall_anchored
        ),
        "semantic_gaps_met": not any(
            _overlaps(best_items[i], best_items[j],
                      margin=_gap_map.get(frozenset({best_items[i].type, best_items[j].type}), 0.0))
            for i in range(len(best_items))
            for j in range(i + 1, len(best_items))
            if frozenset({best_items[i].type, best_items[j].type}) in _gap_map
        ),
    }

    size = space_info.get("estimated_size") or {}
    _fp_room_w = float(size.get("width", 4.0))
    _fp_room_d = float(size.get("depth", 4.0))
    floor_plan_path = _generate_floor_plan(best_items, task_id, room_type, _fp_room_w, _fp_room_d)

    preserve_types = _classify_preserved(best_items, constraints)
    if preserve_types:
        print(f"[layout_agent] 原地保留（使用者未要求變動）：{sorted(preserve_types)}")

    # 同類多件時，preserve_types 幫不上忙（整個類別要嘛全保留要嘛全重畫）。
    # 針對 must_move 再做一次實例級分離，把「沒被指名的那幾件」也鎖回原位。
    preserve_mask = None
    _vf = vision_features or {}
    _seg, _meta = _vf.get("segmentation"), _vf.get("segmentation_meta")
    if constraints.get("must_move") and _seg and _meta:
        if Path(str(_seg)).is_file() and Path(str(_meta)).is_file():
            try:
                from designbridge.layout.instance_select import build_preserve_mask

                preserve_mask, _notes = build_preserve_mask(
                    constraints["must_move"], _seg, _meta, image_path=image_path
                )
                for n in _notes:
                    print(f"[layout_agent] 實例分離 — {n}")
            except Exception as e:
                print(f"⚠️ 實例級保留失敗（{e}），退回語意級")

    projected_depth_path, projected_seg_path, projection_mode = _generate_projected_depth(
        best_items, space_info, task_id,
        vision_features=vision_features,
        output_size=output_size,
        preserve_types=preserve_types,
        preserve_mask=preserve_mask,
    )

    layout_prompt = _build_layout_prompt(best_items, constraints)
    if layout_prompt:
        print(f"[layout_agent] layout_prompt: {layout_prompt}")

    scene_graph: dict[str, Any] = {
        "furniture_placements": [item.to_dict() for item in best_items],
        "layout_prompt": layout_prompt,
        "layout_constraints_met": constraint_check,
        "soft_constraint_scores": scores,
        "weighted_score": best_score,
        "floor_plan_path": floor_plan_path,
        # Carry the REAL room dimensions used to draw the plan so the Step-2 renderer
        # projects the layout at the correct aspect ratio (otherwise it falls back to
        # the requirement analyzer's guessed size and the layout gets distorted).
        "room_w": _fp_room_w,
        "room_d": _fp_room_d,
        "projected_depth_path": projected_depth_path,
        "projected_seg_path": projected_seg_path,
        "projection_mode": projection_mode,
        "feasible": feasible,
        "infeasible_constraints": infeasible_constraints,
    }

    return {
        "scene_graph": scene_graph,
        "intermediate_outputs": {
            "layout_agent": {
                "status": "ok" if feasible else "infeasible",
                "furniture_count": len(best_items),
                "weighted_score": best_score,
                "soft_scores": scores,
                "constraint_check": constraint_check,
                "floor_plan_path": floor_plan_path,
                "projection_mode": projection_mode,
                "scores_history": scores_history,
                "acceptance_rate": round(acceptance_rate, 3),
                "iterations_run": len(scores_history),
                "feasible": feasible,
                "infeasible_constraints": infeasible_constraints,
            }
        },
    }
