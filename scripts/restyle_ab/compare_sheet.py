"""換風格實驗：把每一題的原照片與各方案結果拼成一張對照表（每題一列）。

用法：
  PYTHONUTF8=1 python scripts/restyle_ab/compare_sheet.py <cases.txt> <run_cases.sh 的輸出資料夾> <輸出 jpg>
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

cases, run_dir, dst = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
COLS = ['原照片', 'FLUX（家電保護）', 'Gemini flash', 'Gemini＋FLUX LoRA 0.25']
W, H = 420, 315
font = ImageFont.truetype('C:/Windows/Fonts/msjh.ttc', 22)
small = ImageFont.truetype('C:/Windows/Fonts/msjh.ttc', 18)

rows = []
for line in cases.read_text(encoding='utf-8').splitlines():
    if not line.strip():
        continue
    cid, photo, sid, zh = line.split()
    log = (run_dir / f'base_{cid}.log').read_text(encoding='utf-8')
    flux = json.loads(log.split('@@RESULT', 1)[1])['path'] if '"backend": "photo_restyle_fal"' in log else None
    rows.append((f'{cid}  {Path(photo).name} → {zh}', [photo, flux, run_dir / cid / 'gemini-3.1-flash-image.png',
                                                         run_dir / cid / 'hybrid_0.25.png']))

sheet = Image.new('RGB', (4 * (W + 8) + 8, 40 + len(rows) * (H + 40)), 'white')
draw = ImageDraw.Draw(sheet)
for j, c in enumerate(COLS):
    draw.text((8 + j * (W + 8), 8), c, fill=(140, 113, 99), font=font)
for i, (title, paths) in enumerate(rows):
    y = 40 + i * (H + 40)
    draw.text((8, y + 4), title, fill=(40, 40, 40), font=small)
    for j, p in enumerate(paths):
        x = 8 + j * (W + 8)
        if p and Path(p).exists():
            im = Image.open(p).convert('RGB')
            im.thumbnail((W, H))
            sheet.paste(im, (x, y + 32))
        else:
            draw.rectangle((x, y + 32, x + W, y + 32 + H), fill=(236, 233, 228))
            draw.text((x + W // 2 - 20, y + 32 + H // 2), '失敗', fill=(150, 150, 150), font=small)
sheet.save(dst, quality=86)
print(dst)
