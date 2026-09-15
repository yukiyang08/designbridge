"""Text2Room panoramic room extension via outpainting.

Strategy: instead of warping a 3D mesh (which causes wireframe grid artefacts),
we directly outpaint the image edges with FLUX Fill; FLUX freely imagines what
continues the scene.

Coverage is computed against the standard 2:1 equirectangular width (the shape
a sphere UV-map expects), not an angular guess — see ``run_text2room_loop``.
Each side is extended in a single FLUX Fill call sized to reach that width,
then one more call repaints the wrap-around seam (where the far edge of the
right extension meets the far edge of the left extension) using both edges as
context, so the seam is generated content instead of the old mirror-pad.
Total: 3 fal.ai calls per panorama, regardless of how much width is needed.

Toggle with DESIGNBRIDGE_ENABLE_TEXT2ROOM=true (default: false).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


# ── Single-side outpaint step ─────────────────────────────────────────────────

def _outpaint_side(
    current: Image.Image,
    direction: str,       # "left" or "right"
    extend_w: int,        # pixels to add on that side
    prompt: str,
    out_dir: Path,
    step_name: str,
) -> "Image.Image | None":
    """Extend current panorama on one side using FLUX Fill outpainting.

    Creates a wider canvas with current image on the appropriate side and a
    blurred mirror of its edge on the other; FLUX Fill repaints that strip with
    new scene content.  Returns the full extended image, or None on failure.
    """
    from designbridge.render.inpaint import (
        build_outpaint_prompt,
        make_context_fill,
        run_fal_outpainting,
    )

    W, H = current.size
    new_W = W + extend_w

    # Canvas seeded with blurred mirrored edges rather than flat grey, so FLUX
    # has the room's colour and lighting as context instead of only the prompt
    if direction == "right":
        canvas = make_context_fill(current, right=extend_w)
    else:
        canvas = make_context_fill(current, left=extend_w)

    # Mask: 255 = area to fill, 0 = area to keep
    # Feather ~15px into the existing image so the seam blends smoothly
    feather = 15
    mask_arr = np.zeros((H, new_W), dtype=np.uint8)

    if direction == "right":
        mask_arr[:, max(0, W - feather):] = 255
    else:  # left
        mask_arr[:, : extend_w + feather] = 255

    mask = Image.fromarray(mask_arr, mode="L")

    canvas_path = out_dir / f"step_{step_name}_canvas.png"
    out_path    = out_dir / f"step_{step_name}_extended.png"
    canvas.save(str(canvas_path))

    result = run_fal_outpainting(
        canvas=canvas,
        mask=mask,
        prompt=build_outpaint_prompt(prompt),
        out_dir=out_dir,
        tag=f"step_{step_name}",
    )
    if result is None:
        print(f"[text2room] outpaint {step_name} failed")
        return None
    result.save(str(out_path))
    # FLUX Fill may resize the output; crop/pad back to new_W × H
    if result.size != (new_W, H):
        result = result.resize((new_W, H), Image.LANCZOS)
    return result


# ── Seam bridge ───────────────────────────────────────────────────────────────

def _bridge_seam(
    current_left: Image.Image,
    current_right: Image.Image,
    orig_w: int,
    prompt: str,
    out_dir: Path,
) -> "tuple[Image.Image, Image.Image] | None":
    """Repaint the wrap-around seam so it's generated content, not a mirror.

    Once wrapped on a sphere, the far (outer) edge of ``current_right``'s
    extension sits right next to the far edge of ``current_left``'s extension
    — that join is the one place nothing has "seen" both sides. This takes a
    slice from each far edge, places them side by side on one small canvas,
    and re-paints a band straddling the join with both slices as context, so
    FLUX bridges them into one continuous wall instead of leaving two
    independently-imagined edges to meet raw.

    Returns the same two images with their far edges patched in place, or
    None on failure (caller should fall back to mirror-padding that gap).
    """
    from designbridge.render.inpaint import build_outpaint_prompt, run_fal_outpainting

    H = current_left.height
    right_ext = current_right.width - orig_w
    left_ext  = current_left.width - orig_w
    if right_ext <= 0 or left_ext <= 0:
        return None

    # How much of each far edge to bring in as context. Bounded by what's
    # actually available (the extension itself) so this never reaches back
    # into the original photo.
    bw = max(64, min(right_ext, left_ext, H // 2))

    right_tail = current_right.crop((current_right.width - bw, 0, current_right.width, H))
    left_head  = current_left.crop((0, 0, bw, H))

    canvas = Image.new("RGB", (bw * 2, H))
    canvas.paste(right_tail, (0, 0))
    canvas.paste(left_head, (bw, 0))

    # Repaint the middle half (straddling the true join at x=bw), feathered
    # 15px into each side — same convention as _outpaint_side — so ~a
    # quarter-canvas of real pixels on each end anchors FLUX, not just a thin
    # strip. Everything outside the feathered band is left untouched (mask=0).
    feather = 15
    fill_x0 = bw // 2
    fill_x1 = bw + bw // 2
    mask_arr = np.zeros((H, bw * 2), dtype=np.uint8)
    mask_arr[:, max(0, fill_x0 - feather): fill_x1 + feather] = 255
    mask = Image.fromarray(mask_arr, mode="L")

    canvas.save(str(out_dir / "step_bridge_canvas.png"))
    result = run_fal_outpainting(
        canvas=canvas,
        mask=mask,
        prompt=build_outpaint_prompt(prompt),
        out_dir=out_dir,
        tag="step_bridge",
    )
    if result is None:
        print("[text2room] seam bridge failed, falling back to mirror pad")
        return None
    if result.size != (bw * 2, H):
        result = result.resize((bw * 2, H), Image.LANCZOS)
    result.save(str(out_dir / "step_bridge_extended.png"))

    new_right_tail = result.crop((0, 0, bw, H))
    new_left_head  = result.crop((bw, 0, bw * 2, H))

    current_right = current_right.copy()
    current_right.paste(new_right_tail, (current_right.width - bw, 0))
    current_left = current_left.copy()
    current_left.paste(new_left_head, (0, 0))
    return current_left, current_right


# ── Panorama stitcher ─────────────────────────────────────────────────────────

def _stitch_panorama(
    original: Image.Image,
    left_strip: "Image.Image | None",
    right_strip: "Image.Image | None",
    out_path: Path,
    blend_px: int = 50,
    pad_px: int = 150,
) -> str:
    """Stitch original + side extensions into a single wide panoramic image.

    blend_px: gradient cross-fade width at each seam to hide colour jumps.
    pad_px:   mirrored edge padding so the sphere has no black background
              when the user rotates to the extremes. Pass 0 when the seam
              has already been bridged with real content (see _bridge_seam) —
              padding on top of a bridged seam would paste a mirror over it.
    """
    H = original.height

    def _resize_h(img: Image.Image) -> Image.Image:
        w = max(1, int(img.width * H / img.height))
        return img.resize((w, H), Image.LANCZOS)

    left_r  = _resize_h(left_strip)  if left_strip  is not None else None
    right_r = _resize_h(right_strip) if right_strip is not None else None

    # Hard paste
    parts: list[Image.Image] = []
    if left_r  is not None: parts.append(left_r)
    parts.append(original)
    if right_r is not None: parts.append(right_r)

    total_w = sum(p.width for p in parts)
    pano = Image.new("RGB", (total_w, H))
    x = 0
    for part in parts:
        pano.paste(part, (x, 0))
        x += part.width

    # Cross-fade blend at seams
    arr = np.array(pano, dtype=np.float32)
    seam_xs: list[int] = []
    if left_r  is not None: seam_xs.append(left_r.width)
    if right_r is not None: seam_xs.append((left_r.width if left_r else 0) + original.width)

    half = blend_px // 2
    for sx in seam_xs:
        x0 = max(0, sx - half)
        x1 = min(total_w, sx + half)
        span = x1 - x0
        if span < 2:
            continue
        alpha = np.linspace(0.0, 1.0, span, dtype=np.float32)[np.newaxis, :, np.newaxis]
        left_col  = arr[:, x0:x0 + 1, :]
        right_col = arr[:, x1 - 1:x1, :]
        arr[:, x0:x1, :] = left_col * (1 - alpha) + right_col * alpha

    # Mirror-pad outer edges to fill sphere background when rotating to extremes.
    # Guard pad_px<=0: arr[:, -0:, :] is NOT an empty slice in numpy (-0 == 0), it's
    # the *whole* array, so skipping this block entirely when disabled is required,
    # not just cosmetic.
    if pad_px > 0:
        left_pad  = np.fliplr(arr[:, :pad_px, :])
        right_pad = np.fliplr(arr[:, -pad_px:, :])
        arr = np.concatenate([left_pad, arr, right_pad], axis=1)

    result = Image.fromarray(arr.clip(0, 255).astype(np.uint8))
    result.save(str(out_path), quality=95)
    print(f"[text2room] panorama {result.width}x{H} → {out_path}")
    return str(out_path)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_text2room_loop(
    image_path: str,
    depth_path: str,
    out_dir: str,
    prompt: str = "",
    azimuths_deg: list[float] | None = None,   # kept for API compat, unused
    fov_deg: float = 20.0,                      # unused
    render_w: int = 800,                        # unused
    render_h: int = 600,                        # unused
    mesh_w: int = 512,
    mesh_h: int = 384,
    steps_per_side: int = 1,                    # kept for API compat, unused — see below
) -> "dict | None":
    """Build a room panorama via FLUX Fill outpainting.

    Each side (left / right) is extended in a *single* FLUX Fill call, sized
    so the final width reaches the standard 2:1 equirectangular ratio
    (width = 2 × height) — not the old "guess how many 37°-ish steps" loop.
    A third call then bridges the wrap-around seam using both far edges as
    context. Three fal.ai calls total, independent of how much width is
    needed — ``steps_per_side`` from the old iterative version is no longer
    used (kept as a parameter only so existing callers don't break).

    Also exports a GLB from the initial depth map for the 3D model viewer.

    Returns {"glb": glb_path, "panorama": panorama_path} or None on failure.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    rgb = Image.open(image_path).convert("RGB")
    W, H = rgb.size

    # ── Build initial GLB (for 3D model viewer, unaffected by this change) ──
    depth_arr = np.array(Image.open(depth_path).convert("L"), dtype=np.float32) / 255.0
    from designbridge.render.depth_cloud import depth_to_mesh_glb
    init_glb = str(out_path / "room_mesh.glb")
    depth_to_mesh_glb(rgb, depth_arr, init_glb, side_wing=0.0)

    # Target the standard equirectangular aspect (2:1) rather than an angular
    # guess, and split the shortfall evenly between the two sides.
    target_w = H * 2
    need_per_side = max(0, (target_w - W) // 2)

    current_right = rgb.copy()
    if need_per_side > 0:
        extended = _outpaint_side(current_right, "right", need_per_side, prompt, out_path, "right")
        if extended is not None:
            current_right = extended
            print(f"[text2room] right extend: canvas now {current_right.size}")

    current_left = rgb.copy()
    if need_per_side > 0:
        extended = _outpaint_side(current_left, "left", need_per_side, prompt, out_path, "left")
        if extended is not None:
            current_left = extended
            print(f"[text2room] left extend: canvas now {current_left.size}")

    # Bridge the wrap-around seam with real content; only meaningful once both
    # sides actually gained width. Falls back to the old mirror-pad if it fails.
    bridged = False
    if current_right.width > W and current_left.width > W:
        bridge_result = _bridge_seam(current_left, current_right, W, prompt, out_path)
        if bridge_result is not None:
            current_left, current_right = bridge_result
            bridged = True
            print("[text2room] seam bridged")

    # ── Extract new strips and stitch panorama ────────────────────────────────
    right_strip = (
        current_right.crop((W, 0, current_right.width, H))
        if current_right.width > W else None
    )
    # current_left layout: [left_extensions | original]
    left_strip = (
        current_left.crop((0, 0, current_left.width - W, H))
        if current_left.width > W else None
    )

    if left_strip is None and right_strip is None:
        print("[text2room] all outpaint steps failed, no panorama")
        return {"glb": init_glb, "panorama": None}

    pano_path = _stitch_panorama(
        rgb, left_strip, right_strip, out_path / "panorama.png",
        pad_px=(0 if bridged else 150),
    )

    print(f"[text2room] ✅ glb={init_glb}  panorama={pano_path}")
    return {"glb": init_glb, "panorama": pano_path}
