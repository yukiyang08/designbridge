"""部署 Modal 應用：依 .env 的 DESIGNBRIDGE_MODAL_MODE（dev | demo）帶入 GPU／閒置等待。

python scripts/modal_flux/deploy.py              # 部署主渲染（designbridge-flux）
python scripts/modal_flux/deploy.py --app edit   # 部署局部修改／擴圖（designbridge-edit，Fill dev）
python scripts/modal_flux/deploy.py --show       # 只顯示會用的設定，不部署

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
    args = sys.argv[1:]
    target = "edit_app.py" if ("--app", "edit") in zip(args, args[1:]) or "--app=edit" in args else "modal_app.py"
    print(f"部署 {target}")
    if "--show" not in sys.argv:
        sys.exit(subprocess.call([sys.executable, "-m", "modal", "deploy", str(HERE / target)]))
