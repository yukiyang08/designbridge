"""Render the ControlNet floor-plan PNG (pycairo, PIL fallback)."""

from __future__ import annotations

from pathlib import Path

from designbridge.core.config import Config
from designbridge.layout.layout_items import FurnitureItem


# ─────────────────────────── Floor Plan Image ───────────────────────────

_FURNITURE_LABEL_MAP: dict[str, str] = {
    "sofa": "Sofa", "loveseat": "Loveseat", "coffee_table": "Coffee Table",
    "tv_unit": "TV Unit", "tv": "TV", "dining_table": "Dining Table",
    "chair": "Chair", "armchair": "Armchair", "bed": "Bed",
    "bunk_bed": "Bunk Bed", "bunk_ladder": "Ladder",
    "wardrobe": "Wardrobe", "desk": "Desk", "bookshelf": "Bookshelf",
    "side_table": "Side Table", "nightstand": "Nightstand",
    "lamp": "Lamp", "rug": "Rug", "plant": "Plant",
    "cabinet": "Cabinet", "dresser": "Dresser", "shelf": "Shelf",
}

_ROOM_LABEL_MAP: dict[str, str] = {
    "living_room": "LIVING ROOM", "bedroom": "BEDROOM",
    "kitchen": "KITCHEN", "dining_room": "DINING ROOM", "study": "STUDY",
}


def _generate_floor_plan(
    items: list[FurnitureItem],
    task_id: str,
    room_type: str = "living_room",
    room_w: float = 4.0,
    room_d: float = 4.0,
) -> str | None:
    out = Path(Config.ARTIFACTS_DIR) / "layout" / f"{task_id}_floor_plan.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        import cairo
        import math

        W, H = 900, 980   # extra height for title + legend below
        M = 90            # outer margin
        R = 720           # room box size (square)
        WT = 20           # wall thickness
        RI = R - 2 * WT  # interior room span (680px)

        px_per_m_w = RI / room_w

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
        ctx = cairo.Context(surface)
        ctx.set_antialias(cairo.ANTIALIAS_BEST)

        def text(s: str, x: float, y: float, size: float = 9, bold: bool = False, center: bool = False):
            ctx.select_font_face(
                "Arial",
                cairo.FONT_SLANT_NORMAL,
                cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL,
            )
            ctx.set_font_size(size)
            if center:
                ext = ctx.text_extents(s)
                x -= ext.width / 2
            ctx.move_to(x, y)
            ctx.show_text(s)

        # ── White background ──────────────────────────────────────────
        ctx.set_source_rgb(1, 1, 1)
        ctx.paint()

        # ── Outer border / title area ─────────────────────────────────
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.5)
        ctx.rectangle(M - 10, M - 40, R + 20, R + 20 + 60)  # full drawing frame
        ctx.stroke()

        # Title bar at top of drawing frame
        ctx.set_source_rgb(0, 0, 0)
        ctx.rectangle(M - 10, M - 40, R + 20, 36)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        room_label = _ROOM_LABEL_MAP.get(room_type, room_type.upper().replace("_", " "))
        text(f"FLOOR PLAN — {room_label}", M, M - 12, size=14, bold=True)
        size_label = f"{room_w:.1f}m × {room_d:.1f}m  ({room_w * room_d:.1f} m²)"
        ctx.set_source_rgb(0.85, 0.85, 0.85)
        text(size_label, M + R - 4, M - 12, size=10)

        # ── Solid black walls ─────────────────────────────────────────
        ctx.set_source_rgb(0.08, 0.08, 0.08)
        ctx.rectangle(M, M, R, R)
        ctx.fill()

        # ── Interior floor (white) ────────────────────────────────────
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(M + WT, M + WT, RI, RI)
        ctx.fill()

        # ── Fine grid (every meter) ───────────────────────────────────
        ctx.set_source_rgba(0.82, 0.82, 0.82, 1)
        ctx.set_line_width(0.6)
        grid_step_w = RI / room_w
        grid_step_d = RI / room_d
        for i in range(1, int(room_w)):
            gx = M + WT + i * grid_step_w
            ctx.move_to(gx, M + WT); ctx.line_to(gx, M + WT + RI); ctx.stroke()
        for j in range(1, int(room_d)):
            gy = M + WT + j * grid_step_d
            ctx.move_to(M + WT, gy); ctx.line_to(M + WT + RI, gy); ctx.stroke()

        # ── Door — bottom center (gap in wall + swing arc) ────────────
        dcx = M + WT + RI / 2
        door_px = min(80.0, px_per_m_w * 0.9)  # ~0.9m door
        bot_y = float(M + R - WT)
        # Erase gap
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(dcx - door_px / 2, bot_y, door_px, WT + 1)
        ctx.fill()
        # Swing
        hinge = dcx - door_px / 2
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.2)
        ctx.move_to(hinge, bot_y); ctx.line_to(hinge, bot_y - door_px); ctx.stroke()
        ctx.set_dash([4, 3])
        ctx.arc(hinge, bot_y, door_px, -math.pi / 2, 0)
        ctx.stroke()
        ctx.set_dash([])
        # Label
        ctx.set_source_rgb(0.3, 0.3, 0.3)
        text("D", dcx - 3, bot_y + WT + 12, size=8)

        # ── Window — top center (three-line convention) ───────────────
        wcx = M + WT + RI / 2
        win_px = min(100.0, px_per_m_w * 1.2)
        # erase wall gap
        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(wcx - win_px / 2, M, win_px, WT)
        ctx.fill()
        # three lines (standard window symbol)
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.2)
        for offset in (-win_px / 2, 0.0, win_px / 2):
            ctx.move_to(wcx + offset, M); ctx.line_to(wcx + offset, M + WT); ctx.stroke()
        ctx.set_line_width(0.8)
        ctx.move_to(wcx - win_px / 2, M + WT / 2)
        ctx.line_to(wcx + win_px / 2, M + WT / 2)
        ctx.stroke()
        # Label
        ctx.set_source_rgb(0.3, 0.3, 0.3)
        text("W", wcx - 3, M - 4, size=8)

        # ── Room dimension ticks (outside walls) ─────────────────────
        ctx.set_source_rgb(0.2, 0.2, 0.2)
        ctx.set_line_width(0.8)
        tick = 6
        # Bottom: width
        dim_y = M + R + 16
        ctx.move_to(M, dim_y - tick); ctx.line_to(M, dim_y + tick); ctx.stroke()
        ctx.move_to(M + R, dim_y - tick); ctx.line_to(M + R, dim_y + tick); ctx.stroke()
        ctx.move_to(M, dim_y); ctx.line_to(M + R, dim_y); ctx.stroke()
        ctx.set_source_rgb(0, 0, 0)
        text(f"{room_w:.1f} m", M + R / 2, dim_y + 13, size=9, center=True)
        # Right: depth
        dim_x = M + R + 16
        ctx.set_source_rgb(0.2, 0.2, 0.2)
        ctx.move_to(dim_x - tick, M); ctx.line_to(dim_x + tick, M); ctx.stroke()
        ctx.move_to(dim_x - tick, M + R); ctx.line_to(dim_x + tick, M + R); ctx.stroke()
        ctx.move_to(dim_x, M); ctx.line_to(dim_x, M + R); ctx.stroke()
        ctx.save()
        ctx.translate(dim_x + 14, M + R / 2)
        ctx.rotate(-math.pi / 2)
        ctx.set_source_rgb(0, 0, 0)
        text(f"{room_d:.1f} m", 0, 0, size=9, center=True)
        ctx.restore()

        # ── Furniture (rugs drawn first as floor layer) ───────────────
        ordered = [i for i in items if i.type == "rug"] + [i for i in items if i.type != "rug"]
        for item in ordered:
            fx1 = M + WT + item.x * RI
            fy1 = M + WT + item.y * RI
            fw  = item.w * RI
            fh  = item.h * RI
            fcx = fx1 + fw / 2
            fcy = fy1 + fh / 2
            fx2 = fx1 + fw
            fy2 = fy1 + fh
            fw_r, fh_r = max(4.0, fw), max(4.0, fh)

            # Real-world size in meters
            rw = item.w * room_w
            rd = item.h * room_d

            if item.type in ("chair", "armchair"):
                rad = max(5.0, min(fw, fh) / 2 - 1)
                ctx.set_source_rgb(0.94, 0.94, 0.94)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.2)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.stroke()
                if item.type == "armchair":
                    ctx.set_line_width(2.0)
                    ctx.arc(fcx, fcy, rad + 5, math.pi, 2 * math.pi); ctx.stroke()

            elif item.type == "plant":
                rad = max(5.0, min(fw, fh) / 2 - 1)
                ctx.set_source_rgb(0.9, 0.9, 0.9)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.2)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.stroke()
                ctx.set_line_width(0.8)
                ctx.move_to(fcx, fy1 + 2); ctx.line_to(fcx, fy2 - 2); ctx.stroke()
                ctx.move_to(fx1 + 2, fcy); ctx.line_to(fx2 - 2, fcy); ctx.stroke()

            elif item.type == "lamp":
                rad = max(4.0, min(fw, fh) / 2)
                ctx.set_source_rgb(0.9, 0.9, 0.9)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.2)
                ctx.arc(fcx, fcy, rad, 0, 2 * math.pi); ctx.stroke()

            elif item.type == "rug":
                ctx.set_source_rgb(0.92, 0.92, 0.92)
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.fill()
                ctx.set_source_rgb(0.5, 0.5, 0.5)
                ctx.set_line_width(0.8)
                ctx.set_dash([5, 3])
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.stroke()
                pad = min(6.0, fw * 0.08)
                ctx.rectangle(fx1 + pad, fy1 + pad, fw_r - pad * 2, fh_r - pad * 2); ctx.stroke()
                ctx.set_dash([])

            else:
                # Standard rectangular furniture — white fill, black outline
                ctx.set_source_rgb(0.96, 0.96, 0.96)
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(1.5)
                ctx.rectangle(fx1, fy1, fw_r, fh_r); ctx.stroke()

                ctx.set_source_rgb(0, 0, 0)
                ctx.set_line_width(0.8)

                if item.type == "sofa" and fw > 35:
                    n = max(2, int(fw / 28))
                    for k in range(1, n):
                        lx = fx1 + k * fw / n
                        ctx.move_to(lx, fy1 + 3); ctx.line_to(lx, fy2 - 3); ctx.stroke()
                    bk_y = fy1 + fh * 0.30
                    ctx.set_line_width(1.5)
                    ctx.move_to(fx1 + 1, bk_y); ctx.line_to(fx2 - 1, bk_y); ctx.stroke()

                elif item.type in ("bed", "bunk_bed") and fw > 28:
                    hb_h = max(4.0, fh * 0.14)
                    ctx.set_source_rgb(0.2, 0.2, 0.2)
                    ctx.rectangle(fx1, fy1, fw_r, hb_h); ctx.fill()
                    pl_w = fw * 0.38
                    pl_h = max(4.0, fh * 0.22)
                    pl_y = fy1 + hb_h + 4
                    ctx.set_source_rgb(1, 1, 1)
                    ctx.rectangle(fx1 + 3, pl_y, pl_w, pl_h); ctx.fill()
                    ctx.set_source_rgb(0, 0, 0)
                    ctx.set_line_width(0.8)
                    ctx.rectangle(fx1 + 3, pl_y, pl_w, pl_h); ctx.stroke()
                    if fw > 50:
                        ctx.set_source_rgb(1, 1, 1)
                        ctx.rectangle(fx2 - pl_w - 3, pl_y, pl_w, pl_h); ctx.fill()
                        ctx.set_source_rgb(0, 0, 0)
                        ctx.rectangle(fx2 - pl_w - 3, pl_y, pl_w, pl_h); ctx.stroke()

                elif item.type in ("desk", "dining_table", "coffee_table") and fw > 24:
                    ctx.set_line_width(0.6)
                    ctx.move_to(fcx, fy1 + 2); ctx.line_to(fcx, fy2 - 2); ctx.stroke()
                    ctx.move_to(fx1 + 2, fcy); ctx.line_to(fx2 - 2, fcy); ctx.stroke()

                elif item.type == "wardrobe" and fw > 24:
                    ctx.set_line_width(1.2)
                    ctx.move_to(fcx, fy1); ctx.line_to(fcx, fy2); ctx.stroke()
                    ctx.set_source_rgb(0, 0, 0)
                    ctx.arc(fcx - 5, fcy, 2.5, 0, 2 * math.pi); ctx.fill()
                    ctx.arc(fcx + 5, fcy, 2.5, 0, 2 * math.pi); ctx.fill()

                elif item.type in ("bookshelf", "shelf", "cabinet") and fh > 12:
                    n = max(2, int(fh / 10))
                    for k in range(1, n):
                        sy = fy1 + k * fh / n
                        ctx.move_to(fx1 + 1, sy); ctx.line_to(fx2 - 1, sy); ctx.stroke()

                elif item.type == "tv_unit" and fw > 24:
                    ctx.set_source_rgb(0.15, 0.15, 0.15)
                    ctx.rectangle(fx1 + fw * 0.12, fy1 + fh * 0.12, fw * 0.76, fh * 0.76)
                    ctx.fill()

                elif item.type == "dresser" and fw > 20:
                    n = max(2, int(fw / 18))
                    for k in range(1, n):
                        lx = fx1 + k * fw / n
                        ctx.move_to(lx, fy1); ctx.line_to(lx, fy2); ctx.stroke()
                    ctx.arc(fcx, fcy, 2.5, 0, 2 * math.pi); ctx.fill()

            # ── Furniture label + real-world size ─────────────────────
            if fw >= 20 and fh >= 12:
                label = _FURNITURE_LABEL_MAP.get(item.type, item.type.replace("_", " ").title())
                fs_name = max(7.5, min(10.0, fw / 6.5))
                fs_dim  = max(6.5, min(8.5,  fw / 7.5))

                ctx.set_source_rgb(0.05, 0.05, 0.05)
                # If enough vertical space show name + dims on separate lines
                if fh >= 26:
                    text(label, fcx, fcy - 1, size=fs_name, center=True)
                    dim_str = f"{rw:.2f}×{rd:.2f}m"
                    ctx.set_source_rgb(0.35, 0.35, 0.35)
                    text(dim_str, fcx, fcy + fs_dim + 2, size=fs_dim, center=True)
                else:
                    short = label if len(label) <= 7 else label[:6] + "."
                    text(short, fcx, fcy + 3, size=fs_name, center=True)

        # ── North arrow (top-right, inside title) ─────────────────────
        na_x, na_y = M + R - 8, M - 24
        ctx.set_source_rgb(1, 1, 1)
        ctx.move_to(na_x, na_y - 10); ctx.line_to(na_x - 6, na_y + 6); ctx.line_to(na_x + 6, na_y + 6)
        ctx.close_path(); ctx.fill()
        ctx.set_source_rgb(0.9, 0.9, 0.9)
        text("N", na_x, na_y + 16, size=9, bold=True, center=True)

        # ── Scale bar (bottom, inside frame) ─────────────────────────
        sb_x = M
        sb_y = M + R + 38
        sb_w = int(px_per_m_w)  # 1 meter in pixels
        ctx.set_source_rgb(0, 0, 0)
        ctx.set_line_width(1.5)
        ctx.move_to(sb_x, sb_y); ctx.line_to(sb_x + sb_w, sb_y); ctx.stroke()
        ctx.set_line_width(1)
        for tick_x in (sb_x, sb_x + sb_w):
            ctx.move_to(tick_x, sb_y - 4); ctx.line_to(tick_x, sb_y + 4); ctx.stroke()
        text("0", sb_x - 3, sb_y + 13, size=8)
        text("1 m", sb_x + sb_w - 6, sb_y + 13, size=8)
        ctx.set_source_rgb(0.4, 0.4, 0.4)
        text("SCALE 1:?  (indicative)", sb_x + sb_w + 16, sb_y + 4, size=7)

        # ── Legend ────────────────────────────────────────────────────
        lx, ly = M + R - 200, M + R + 10
        ctx.set_source_rgb(0.3, 0.3, 0.3)
        text("D = Door  |  W = Window  |  Grid = 1 m", lx, ly + 30, size=7.5)

        surface.write_to_png(str(out))
        print(f"[layout_agent] Floor plan saved (pycairo B&W): {out}")
        return str(out)

    except Exception as e:
        print(f"⚠️ pycairo floor plan failed ({e}), falling back to PIL")

    # Fallback: PIL raster
    try:
        from PIL import Image, ImageDraw, ImageFont

        SIZE, MARGIN = 640, 52
        ROOM = SIZE - 2 * MARGIN
        WALL = 10
        img = Image.new("RGB", (SIZE, SIZE), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN],
                       fill=(30, 30, 30), outline=(0, 0, 0), width=WALL)
        draw.rectangle([MARGIN + WALL, MARGIN + WALL,
                        SIZE - MARGIN - WALL, SIZE - MARGIN - WALL],
                       fill=(255, 255, 255))
        try:
            font_sm = font_md = None
            for fp in ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
                if Path(fp).exists():
                    font_sm = ImageFont.truetype(fp, 9)
                    font_md = ImageFont.truetype(fp, 13)
                    break
            if font_sm is None:
                font_sm = font_md = ImageFont.load_default()
        except Exception:
            font_sm = font_md = ImageFont.load_default()
        ROOM_I = ROOM - 2 * WALL
        for item in items:
            x1 = int(MARGIN + WALL + item.x * ROOM_I)
            y1 = int(MARGIN + WALL + item.y * ROOM_I)
            x2 = max(x1 + 6, int(MARGIN + WALL + (item.x + item.w) * ROOM_I))
            y2 = max(y1 + 6, int(MARGIN + WALL + (item.y + item.h) * ROOM_I))
            draw.rectangle([x1, y1, x2, y2], fill=(240, 240, 240), outline=(0, 0, 0), width=1)
            label = _FURNITURE_LABEL_MAP.get(item.type, item.type.replace("_", " ").title())
            short = label if len(label) <= 8 else label[:7] + "."
            if x2 - x1 >= 18 and y2 - y1 >= 10:
                draw.text(((x1 + x2) // 2, (y1 + y2) // 2), short,
                          fill=(0, 0, 0), anchor="mm", font=font_sm)
        room_label = _ROOM_LABEL_MAP.get(room_type, room_type.upper().replace("_", " "))
        draw.text((MARGIN + WALL + 6, MARGIN + WALL + 6), room_label, fill=(0, 0, 0), font=font_md)
        img.save(str(out))
        print(f"[layout_agent] Floor plan saved (PIL fallback): {out}")
        return str(out)
    except Exception as e:
        print(f"⚠️ Floor plan generation failed: {e}")
        return None
