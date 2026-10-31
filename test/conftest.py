"""測試一律不碰雲端 GPU：開發者的 .env 就算打開 Modal 開關，測試也不該真的呼叫 Modal（會慢且花錢）。"""

import pytest

from designbridge.core.config import Config


@pytest.fixture(autouse=True)
def _no_modal_gpu(monkeypatch):
    monkeypatch.setattr(Config, "USE_MODAL_GPU", False)
    monkeypatch.setattr(Config, "USE_MODAL_EDIT", False)   # 啟動時就由 .env 算好，不會跟著上一行變
