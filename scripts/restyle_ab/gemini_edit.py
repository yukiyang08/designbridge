"""換風格實驗：用 Gemini 圖片編輯（Vertex AI）換風格，不用遮罩、深度或 ControlNet，只給照片＋指令。

用法：
  PYTHONUTF8=1 python scripts/restyle_ab/gemini_edit.py <照片> <base_xx.log> <輸出資料夾> [模型 ...]

風格描述與房間內容（分割結果寫的那句）取自 baseline.py 的 log，跟 FLUX 用同一份，比較才公平。
模型預設 gemini-3.1-flash-image；第一輪（2026-11-18）在 9 題裡結果最好。
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, '.')
from google.genai import types

from designbridge.render.llm import get_gemini_client

photo, log, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
models = sys.argv[4:] or ['gemini-3.1-flash-image']
out.mkdir(parents=True, exist_ok=True)
gp = json.loads(log.read_text(encoding='utf-8').split('@@RESULT', 1)[1])['gp']
inventory = (gp.get('restyle_inventory') or '').replace('The same room with the same layout and camera angle: ', '') \
    .replace(' Restyle everything in place.', '').strip()

PROMPT = (
    "Restyle the interior of this exact room. Target style: " + gp['prompt_preview'] + "\n\n"
    "Keep the room itself identical: the same camera angle and lens, the same walls, ceiling, floor area, "
    "and every window and door in exactly the same place and size. Keep every piece of furniture and every "
    "appliance as the same kind of object, in the same position and at the same size"
    + (f" (in this photo: {inventory})" if inventory else "") + ". A bed stays a bed, a wardrobe stays a wardrobe, "
    "a refrigerator stays a refrigerator, a stove stays a stove. Only change materials, colors, finishes, textiles "
    "and small decor. Do not add any new windows, doors, curtains or wall openings. Photorealistic interior photograph."
)

client = get_gemini_client()
img = types.Part.from_bytes(data=photo.read_bytes(), mime_type='image/jpeg')
for m in models:
    t = time.time()
    try:
        resp = client.models.generate_content(
            model=m, contents=[img, PROMPT],
            config=types.GenerateContentConfig(response_modalities=['IMAGE', 'TEXT']),
        )
        part = next((p for p in resp.candidates[0].content.parts if getattr(p, 'inline_data', None)), None)
        if part:
            (out / f'{m}.png').write_bytes(part.inline_data.data)
        print(m, 'ok' if part else 'NO IMAGE', f'{time.time() - t:.1f}s', flush=True)
    except Exception as e:
        print(m, 'FAIL', type(e).__name__, str(e)[:300], flush=True)
