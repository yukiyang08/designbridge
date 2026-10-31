"""Modal 部署參數：依 DESIGNBRIDGE_MODAL_MODE（dev | demo）決定 GPU 與閒置等待。

modal_app.py（部署時）與 deploy.py 共用；容器內也會載入 modal_app.py，所以這個檔案只用標準庫。
"""

import os

# H100 比 L40S 快約 2.3 倍（Union 路徑純算圖 8.2s 對 18~21s），但每秒貴一倍
PROFILES = {
    "dev": {"gpu": "L40S", "scaledown": 60},
    "demo": {"gpu": "H100", "scaledown": 600},
}


def resolve() -> dict:
    """回傳 {gpu, scaledown}；模式沒設或是 off 時用 dev。DESIGNBRIDGE_MODAL_GPU 只給 bench 臨時換 GPU 實驗用。"""
    base = PROFILES.get(os.environ.get("DESIGNBRIDGE_MODAL_MODE", "").strip().lower(), PROFILES["dev"])
    gpu = (os.environ.get("DESIGNBRIDGE_MODAL_GPU") or base["gpu"]).strip()
    if gpu.upper() == "H100":
        gpu = "H100!"  # ! 避免被自動升級成更貴的 H200
    return {"gpu": gpu, "scaledown": base["scaledown"]}
