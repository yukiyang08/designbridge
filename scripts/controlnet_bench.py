"""Bench flux_controlnet_depth_fal across (num_steps, control_end) to find a faster
quality/speed tradeoff than the current default (steps=20, control_end=1.0).

ponytail: reuses the existing production render function directly instead of
reimplementing the fal.ai call — this IS the shortest path to a real answer.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(r"C:\Users\Timothy\Desktop\DesignBridge")
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

from designbridge.render.render_backends import _render_flux_controlnet_depth_fal

OUT_DIR = REPO_ROOT / "docs" / "images" / "controlnet_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DEPTH_PATH = str(REPO_ROOT / "artifacts" / "layout" / "9d56e782-773e-414d-8021-7805cbd43be2_projected_depth.png")
PROMPT = (
    "A modern minimalist living room interior, light oak wood flooring, "
    "a gray fabric sofa, a wooden coffee table, a floor lamp, large window with "
    "soft natural daylight, indoor plant, warm and cozy atmosphere, "
    "interior design photography, photorealistic, 8k, highly detailed"
)

# conditioning_scale=0.3 matches Config.PROJECTED_DEPTH_MAX_CONDITIONING_SCALE, the
# production safety cap for synthetic scene-graph depth maps (renderer.py:538) — the
# first run used 0.7 by mistake, which is why furniture came out as literal boxes and
# the flat depth regions (wall/window) rendered as noise.
CONDITIONING_SCALE = 0.3

# Grid: default is steps=20, control_end=1.0 (~125-154s per PERFORMANCE_NOTES.md).
GRID = [
    (10, 1.0),
    (14, 1.0),
    (20, 1.0),  # baseline/default
    (10, 0.7),
    (14, 0.7),
]

results = []
log_path = OUT_DIR / "results_cs0.3.json"

for steps, control_end in GRID:
    name = f"cs0.3_steps{steps}_end{control_end}"
    out_path = OUT_DIR / f"{name}.png"
    print(f"=== running {name} ===", flush=True)
    t0 = time.time()
    ok = _render_flux_controlnet_depth_fal(
        PROMPT,
        DEPTH_PATH,
        out_path,
        conditioning_scale=CONDITIONING_SCALE,
        control_end=control_end,
        num_steps=steps,
        guidance_scale=3.5,
    )
    elapsed = time.time() - t0
    row = {"name": name, "steps": steps, "control_end": control_end, "conditioning_scale": CONDITIONING_SCALE, "ok": ok, "elapsed_s": round(elapsed, 1)}
    results.append(row)
    print(f"=== {name}: ok={ok} elapsed={elapsed:.1f}s ===", flush=True)
    log_path.write_text(json.dumps(results, indent=2))

print("DONE", flush=True)
print(json.dumps(results, indent=2))
