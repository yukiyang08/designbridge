"""換風格實驗：接力——Gemini 換好風格的圖，再用 FLUX＋自家風格 LoRA 低強度 img2img 過一次。

用法：
  PYTHONUTF8=1 python scripts/restyle_ab/hybrid.py <gemini 輸出圖> <base_xx.log> <輸出資料夾> <強度 ...>

輸出尺寸照輸入圖的比例算（長邊 1024、取 16 的倍數）；第一輪腳本固定成 1024×768，直式照片被拉變形。
"""
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, '.')
import fal_client
from PIL import Image

from designbridge.core.config import Config
from designbridge.render.render_backends import _fal_flux_general

src, log, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
strengths = [float(s) for s in sys.argv[4:]] or [0.25]
out.mkdir(parents=True, exist_ok=True)
os.environ['FAL_KEY'] = Config.FAL_KEY
gp = json.loads(log.read_text(encoding='utf-8').split('@@RESULT', 1)[1])['gp']

im = Image.open(src).convert('RGB')
k = 1024 / max(im.size)
W, H = (round(im.width * k / 16) * 16, round(im.height * k / 16) * 16)
buf = io.BytesIO()
im.resize((W, H), Image.LANCZOS).save(buf, format='PNG')
url = fal_client.upload(buf.getvalue(), content_type='image/png')
for s in strengths:
    args = {'prompt': gp['prompt_preview'], 'image_url': url, 'strength': s, 'num_inference_steps': 28,
            'guidance_scale': 3.5, 'image_size': {'width': W, 'height': H}, 'seed': gp['seed'],
            'loras': gp.get('loras') or []}
    (out / f'hybrid_{s:.2f}.png').write_bytes(_fal_flux_general('fal-ai/flux-general/image-to-image', args))
    print('ok', s, flush=True)
