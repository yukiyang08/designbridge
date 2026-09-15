"""
Test the text2room panorama outpainting path in isolation.

Runs the same code the graph runs, but on a single image, so a change to the
outpaint prompt or canvas fill can be checked without a full generation.

Usage:
    # free: build + save the canvases and print the prompt, no API call
    python scripts/test_text2room.py --dry-run [image_path]

    # real: 2 fal.ai calls (one per side), writes panorama.png
    python scripts/test_text2room.py [image_path]

    # with the design prompt the graph would have passed
    PROMPT="modern living room, warm oak" python scripts/test_text2room.py

Output: artifacts/room_mesh/text2room_test/
"""
import glob
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

# ------ Config ------
args = [a for a in sys.argv[1:] if not a.startswith("--")]
DRY_RUN = "--dry-run" in sys.argv
IMAGE_PATH = args[0] if args else None
PROMPT = os.getenv("PROMPT", "")
OUT_DIR = Path("artifacts/room_mesh/text2room_test")

if IMAGE_PATH is None:
    renders = sorted(glob.glob("artifacts/render/*.png"), key=os.path.getmtime)
    if not renders:
        print("No render images found. Run a design generation first, or pass an image path.")
        sys.exit(1)
    IMAGE_PATH = renders[-1]

img = Image.open(IMAGE_PATH).convert("RGB")
print(f"Input image : {IMAGE_PATH}  {img.size}")
print(f"Design prompt: {PROMPT!r}")
print(f"Output dir  : {OUT_DIR}")
OUT_DIR.mkdir(parents=True, exist_ok=True)

from designbridge.core.config import Config
from designbridge.render.inpaint import build_outpaint_prompt, make_context_fill


def _ENDPOINT_PARAMS(endpoint_id: str) -> set:
    """Ask fal which arguments this endpoint actually accepts.

    Worth checking: flux-pro/v1/fill silently ignores guidance_scale,
    num_inference_steps and negative_prompt rather than erroring on them.
    """
    import json
    import urllib.request
    url = f"https://fal.ai/api/openapi/queue/openapi.json?endpoint_id={endpoint_id}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            doc = json.load(r)
    except Exception as e:
        print(f"(could not fetch endpoint schema: {e})")
        return {"negative_prompt"}   # don't block the run on a network hiccup
    for name, sch in doc.get("components", {}).get("schemas", {}).items():
        if name.endswith("InpaintingInput") or name.endswith("FillInput"):
            return set(sch.get("properties", {}))
    return set()


# ------ What actually gets sent to FLUX ------
ext_prompt = build_outpaint_prompt(PROMPT)
print()
print(f"Endpoint       : {Config.FAL_OUTPAINT_MODEL}")
print("Prompt sent to FLUX:")
print(f"  {ext_prompt}")
print("Negative prompt:")
print(f"  {Config.outpaint_negative_prompt()}")
print(f"guidance_scale: {Config.OUTPAINT_GUIDANCE}  nag_scale: {Config.OUTPAINT_NAG_SCALE}  steps: {Config.OUTPAINT_STEPS}")

if "negative_prompt" not in _ENDPOINT_PARAMS(Config.FAL_OUTPAINT_MODEL):
    print("\n\u274c this endpoint has no negative_prompt \u2014 it cannot suppress watermarks.")
    print("   Set DESIGNBRIDGE_FAL_OUTPAINT_MODEL to one that does.")
    sys.exit(1)
print("\u2705 endpoint accepts negative_prompt")

leaked = [w for w in ("continuation", "extension", "seamless", "panorama") if w in ext_prompt.lower()]
if leaked:
    print(f"\n❌ non-visual words still in the prompt: {leaked}")
    print("   FLUX will likely render these as signage. Check build_outpaint_prompt().")
    sys.exit(1)
print("✅ no non-visual instruction words in the prompt")

# ------ Canvases FLUX will see ------
W, H = img.size
extend_w = max(64, W // 2)
for direction in ("left", "right"):
    canvas = make_context_fill(img, **{direction: extend_w})
    path = OUT_DIR / f"canvas_{direction}.png"
    canvas.save(str(path))
    print(f"canvas {direction:5s}: {canvas.size} → {path}")

if DRY_RUN:
    print("\n--dry-run: stopping before the fal.ai calls.")
    print("Open the canvas_*.png files: the extended strip should carry the room's")
    print("colours with no recognisable furniture, not flat grey.")
    sys.exit(0)

if not Config.FAL_KEY:
    print("\n⚠  FAL_KEY not set — cannot run the real outpainting. Set it in .env.")
    sys.exit(1)

# ------ Depth map (needed for the GLB half of the loop) ------
depth_path = None
task_id = Path(IMAGE_PATH).stem.split("_")[0]
candidate = Path("artifacts/room_mesh") / task_id / "depth.png"
if candidate.is_file():
    depth_path = str(candidate)
    print(f"\nReusing depth: {depth_path}")
else:
    print("\nNo cached depth for this image, running depth estimation...")
    from designbridge.layout.vision import run_depth_estimation
    depth_path, _ = run_depth_estimation(
        IMAGE_PATH, model_name=Config.DEPTH_MODEL, out_dir=OUT_DIR
    )
    print(f"depth → {depth_path}")

# ------ Real run: 2 fal.ai calls ------
print("\nRunning text2room loop (2 fal.ai calls)...")
from designbridge.render.text2room import run_text2room_loop

result = run_text2room_loop(
    image_path=IMAGE_PATH,
    depth_path=depth_path,
    out_dir=str(OUT_DIR),
    prompt=PROMPT,
)

if not result or not result.get("panorama"):
    print("❌ no panorama produced — see the [text2room] log lines above.")
    sys.exit(1)

print(f"\n✅ panorama → {result['panorama']}")
print(f"   glb      → {result.get('glb')}")
print("\nOpen the panorama and check the extended strips on both sides:")
print("no banner text, no signage, no lettering.")
