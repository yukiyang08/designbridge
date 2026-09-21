"""Top-level orchestrator: room program -> RoomPlanResult (partition + openings + SVG)."""

from __future__ import annotations

from pathlib import Path

from designbridge.core.config import Config
from designbridge.roomplan.constants import PING_TO_M2
from designbridge.roomplan.partition import partition_rooms
from designbridge.roomplan.schemas import RoomPlanResult
from designbridge.roomplan.svg_render import render_room_plan_svg
from designbridge.roomplan.walls import derive_walls_and_openings


def generate_room_plan(program: dict, task_id: str) -> RoomPlanResult:
    rooms, bounding_w, bounding_d, warnings = partition_rooms(program)
    walls, doors, windows = derive_walls_and_openings(rooms, bounding_w, bounding_d)

    total_m2 = float(program.get("total_ping", 0) or 0) * PING_TO_M2
    svg_markup = render_room_plan_svg(rooms, walls, doors, windows, bounding_w, bounding_d, total_m2)

    out_dir = Path(Config.ARTIFACTS_DIR) / "room_plan"
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / f"{task_id}.svg"
    svg_path.write_text(svg_markup, encoding="utf-8")

    return RoomPlanResult(
        task_id=task_id,
        program=dict(program),
        total_m2=total_m2,
        bounding_w_m=bounding_w,
        bounding_d_m=bounding_d,
        rooms=rooms,
        walls=walls,
        doors=doors,
        windows=windows,
        svg_path=str(svg_path),
        svg_markup=svg_markup,
        warnings=warnings,
    )
