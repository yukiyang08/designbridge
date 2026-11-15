"""上傳平面圖的品質檢查：太小、太淡、太糊直接擋下，不送進 Gemini 亂猜。"""

from __future__ import annotations

import numpy as np
from PIL import Image

# ponytail: 門檻取自 artifacts/uploads 的 71 張真實平面圖（最小短邊 369、對比 64、銳利度 113），
# 刻意定得比它們低很多免得誤擋；有評估集後再調
_MIN_SIDE = 300
_MIN_CONTRAST = 30
_MIN_SHARPNESS = 50
_WORK_SIDE = 1240   # 統一縮到這個尺寸再量，銳利度才不受原圖大小影響


class FloorPlanRejected(ValueError):
    """圖片不適合辨識；訊息直接顯示給使用者。"""


def check_floor_plan_image(image_path: str) -> None:
    from scipy import ndimage as ndi

    with Image.open(image_path) as im:
        rgba = im.convert("RGBA")
    # 透明底的 PNG 要墊白底，不然透明處會被當成黑色
    g = Image.alpha_composite(Image.new("RGBA", rgba.size, "white"), rgba).convert("L")
    side = min(g.size)
    if side < _MIN_SIDE:
        raise FloorPlanRejected(
            f"圖片解析度太低（短邊 {side}px，至少要 {_MIN_SIDE}px），請上傳更清楚的平面圖")
    s = _WORK_SIDE / max(g.size)
    resample = Image.Resampling.BILINEAR if s > 1 else Image.Resampling.BOX
    a = np.asarray(g.resize((round(g.width * s), round(g.height * s)), resample), dtype=float)
    p5, p95 = np.percentile(a, [5, 95])
    if p95 - p5 < _MIN_CONTRAST:
        raise FloorPlanRejected("圖片對比太低、看不清牆線，請上傳更清楚的平面圖")
    if ndi.laplace(a).var() < _MIN_SHARPNESS:
        raise FloorPlanRejected("圖片太模糊，請上傳更清楚的平面圖")


if __name__ == "__main__":
    import sys
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())

    def expect(img: Image.Image, ok: bool) -> None:
        p = tmp / "t.png"
        img.save(p)
        try:
            check_floor_plan_image(str(p))
            assert ok, "應該被擋"
        except FloorPlanRejected:
            assert not ok, "不該被擋"

    plan = Image.new("L", (800, 600), 255)
    from PIL import ImageDraw, ImageFilter
    d = ImageDraw.Draw(plan)
    for x in range(50, 800, 120):
        d.line((x, 50, x, 550), fill=0, width=4)
    d.rectangle((50, 50, 750, 550), outline=0, width=8)
    expect(plan, True)
    expect(plan.resize((250, 190)), False)                       # 太小
    expect(Image.new("L", (800, 600), 200), False)               # 一片灰，沒對比
    expect(plan.filter(ImageFilter.GaussianBlur(12)), False)     # 太糊
    for p in sys.argv[1:]:   # 也可以傳真實圖片路徑看結果
        try:
            check_floor_plan_image(p)
            print("OK", p)
        except FloorPlanRejected as e:
            print("擋下", p, e)
    print("floorplan_quality self-check passed")
