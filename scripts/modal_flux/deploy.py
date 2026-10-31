"""部署 Modal 應用：依 .env 的 DESIGNBRIDGE_MODAL_MODE（dev | demo）帶入 GPU／閒置等待。

python scripts/modal_flux/deploy.py          # 部署
python scripts/modal_flux/deploy.py --show   # 只顯示會用的設定，不部署

部署是全隊共用的（同名覆蓋），只有負責部署的人切換模式。
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(HERE.parents[1] / ".env")

import os  # noqa: E402

from profiles import resolve  # noqa: E402

if __name__ == "__main__":
    cfg = resolve()
    print(f"模式 {os.environ.get('DESIGNBRIDGE_MODAL_MODE') or '(未設，用舊預設)'} → {cfg}")
    if "--show" not in sys.argv:
        sys.exit(subprocess.call([sys.executable, "-m", "modal", "deploy", str(HERE / "modal_app.py")]))
