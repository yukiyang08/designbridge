"""
Test outpainting → depth → GLB mesh pipeline.

Usage:
    # Enable outpainting and test with a render image
    DESIGNBRIDGE_ENABLE_MESH_OUTPAINT=1 python scripts/test_outpaint_mesh.py [image_path]

    # Or use the API directly with a custom image
    python scripts/test_outpaint_mesh.py artifacts/render/some_image.png

Output: artifacts/room_mesh/outpaint_test/
"""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
import numpy as np

# ------ Config ------
IMAGE_PATH = sys.argv[1] if len(sys.argv) > 1 else None
BORDER_FRACTION = float(os.getenv("OUTPAINT_BORDER", "0.2"))
OUT_DIR = Path("artifacts/room_mesh/outpaint_test")

# Find a render image if not specified
if IMAGE_PATH is None:
    import glob
    renders = sorted(glob.glob("artifacts/render/*.png"), key=os.path.getmtime)
    if not renders:
        print("No render images found. Run a design generation first, or pass an image path.")
        sys.exit(1)
    IMAGE_PATH = renders[-1]

print(f"Input image: {IMAGE_PATH}")
print(f"Border fraction: {BORDER_FRACTION:.0%} each side")
print(f"Output dir: {OUT_DIR}")
print()

# ------ Step 1: Outpaint ------
from designbridge.core.config import Config
from designbridge.render.inpaint import outpaint_for_depth_mesh

img = Image.open(IMAGE_PATH).convert("RGB")
print(f"Original size: {img.size}")

if not Config.FAL_KEY:
    print("⚠  FAL_KEY not set. Set it in .env or environment to run outpainting.")
    print("   Testing canvas expansion only (no API call)...")
    W, H = img.size
    bx, by = int(W * BORDER_FRACTION), int(H * BORDER_FRACTION)
    expanded = Image.new("RGB", (W + 2*bx, H + 2*by), (128, 128, 128))
    expanded.paste(img, (bx, by))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    expanded.save(str(OUT_DIR / "expanded_preview.png"))
    print(f"Expanded preview saved: {OUT_DIR / 'expanded_preview.png'}")
    print("Set FAL_KEY to continue with AI outpainting.")
    sys.exit(0)

outpainted = outpaint_for_depth_mesh(
    img,
    border_fraction=BORDER_FRACTION,
    out_dir=OUT_DIR,
)

if outpainted is None:
    print("❌ Outpainting failed. Check FAL_KEY and network.")
    sys.exit(1)

outpainted_path = str(OUT_DIR / "outpainted.png")
print(f"Outpainted size: {outpainted.size}")

# ------ Step 2: Depth estimation on outpainted image ------
print("\nRunning depth estimation on outpainted image...")
from designbridge.layout.vision import run_depth_estimation

depth_path, _ = run_depth_estimation(
    outpainted_path,
    model_name=Config.DEPTH_MODEL,
    out_dir=OUT_DIR,
)
print(f"Depth map: {depth_path}")

# ------ Step 3: Generate GLB mesh ------
print("\nGenerating GLB mesh...")
from designbridge.render.depth_cloud import generate_depth_mesh_glb

glb_path = generate_depth_mesh_glb(
    image_path=outpainted_path,
    depth_path=depth_path,
    out_dir=str(OUT_DIR),
)

if not glb_path:
    print("❌ GLB generation failed")
    sys.exit(1)

print(f"\n✅ Done!")
print(f"   Outpainted image: {OUT_DIR / 'outpainted.png'}")
print(f"   Depth map:        {depth_path}")
print(f"   GLB mesh:         {glb_path}")
print()
print("To view in the 3D viewer:")
print(f"   cp '{glb_path}' artifacts/room_mesh/latest.glb")
print(f"   # Then open http://localhost:5173/room-test in the frontend")
