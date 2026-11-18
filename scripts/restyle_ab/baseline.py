"""換風格實驗：對一張照片跑一次完整的換風格流程（目前的 FLUX 做法），存下描述與條件圖給其他方案重用。

用法（專案根目錄）：
  PYTHONUTF8=1 python scripts/restyle_ab/baseline.py <style_id> <風格中文名> <照片路徑> > base_xx.log

照片要在 artifacts/ 底下（check_request_paths 只收 artifacts 路徑）。
log 最後一行 `@@RESULT {...}` 是結果：出圖路徑、generation_params、條件圖路徑；
gemini_edit.py、hybrid.py 都從這裡讀描述與 seed。
"""
import json
import os
import sys

sys.path.insert(0, '.')
import routers.generate as G
from routers.common import DesignRequest

G._save_history = lambda *a, **k: None   # 不寫進使用者的歷史紀錄

style, zh, photo = sys.argv[1], sys.argv[2], os.path.abspath(sys.argv[3])
req = DesignRequest(text_prompt=f"{zh}風格的室內設計", style_profile_id=style,
                    initial_image_path=photo, restyle=True, output_aspect="auto")
resp = G.generate_design(req, user_id="")
rr = resp.get("render_result") or {}
print("@@RESULT", json.dumps({
    "photo": photo, "path": resp.get("generated_image_path"),
    "gp": rr.get("generation_params"), "cn": rr.get("controlnet_inputs"),
}, ensure_ascii=False, default=str))
