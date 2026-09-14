"""
測試 Gemini 多 key 輪替邏輯（純邏輯，不呼叫真實 API）。

執行方式：
    python test/test_gemini_key_rotation.py

註：目錄重構後輪替實作從 designbridge.llm 的 call_with_gemini_key_rotation
搬進 designbridge.render.llm 的 call_llm 本身，key 解析則由
_resolve_gemini_api_keys 負責，本測試已對齊新的 API。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 蓋掉可能存在的 .env 值，確保測試結果穩定
os.environ["GEMINI_API_KEY"] = "key-a"
os.environ["GEMINI_API_KEYS"] = "key-a,key-b,key-c"
os.environ.pop("GOOGLE_GENAI_USE_VERTEXAI", None)

from designbridge.core.config import Config
import designbridge.render.llm as llm

# Config 在 import 時就從環境讀值，這裡直接對齊上面設定的測試值
Config.GEMINI_API_KEY = "key-a"
Config.GEMINI_API_KEYS = "key-a,key-b,key-c"


def test_keys_merged_and_deduped():
    """GEMINI_API_KEY 排第一，GEMINI_API_KEYS 依序接上並去重。"""
    assert llm._resolve_gemini_api_keys() == ["key-a", "key-b", "key-c"]


def _patch_client(monkey: dict, fake):
    """把 _gemini_client_and_config 換成受控替身，回傳還原用的原函式。"""
    original = llm._gemini_client_and_config

    class _Models:
        def generate_content(self, *, model, contents, config):
            return fake(config._test_api_key)

    class _Client:
        models = _Models()

    def patched(api_key, system, temperature, max_tokens):
        client, cfg = _Client(), type("Cfg", (), {})()
        cfg._test_api_key = api_key
        return client, cfg

    llm._gemini_client_and_config = patched
    monkey["restore"] = original
    return original


def test_rotation_tries_each_key_until_one_works():
    calls = []

    def fake(api_key):
        calls.append(api_key)
        if api_key != "key-c":
            raise RuntimeError("429 quota exceeded")
        return type("R", (), {"text": "ok"})()

    monkey = {}
    _patch_client(monkey, fake)
    try:
        assert llm.call_llm("hi") == "ok"
        assert calls == ["key-a", "key-b", "key-c"]
    finally:
        llm._gemini_client_and_config = monkey["restore"]


def test_raises_after_all_keys_exhausted():
    def always_quota(api_key):
        raise RuntimeError("429 quota exceeded")

    monkey = {}
    _patch_client(monkey, always_quota)
    try:
        llm.call_llm("hi")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        # 錯誤訊息要把每一把 key 的失敗原因都帶出來，方便診斷
        assert "所有 Gemini API key 皆失敗" in str(e)
        assert str(e).count("quota exceeded") == 3
    finally:
        llm._gemini_client_and_config = monkey["restore"]


def test_no_key_raises_helpful_error():
    """完全沒設 key 時要給可操作的訊息，而不是讓 SDK 拋難懂的錯。"""
    orig_key, orig_keys = Config.GEMINI_API_KEY, Config.GEMINI_API_KEYS
    orig_env = os.environ.pop("GEMINI_API_KEY", None), os.environ.pop("GEMINI_API_KEYS", None)
    Config.GEMINI_API_KEY, Config.GEMINI_API_KEYS = "", ""
    try:
        assert llm._resolve_gemini_api_keys() == []
        llm.call_llm("hi")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as e:
        assert "GEMINI_API_KEY" in str(e)
    finally:
        Config.GEMINI_API_KEY, Config.GEMINI_API_KEYS = orig_key, orig_keys
        if orig_env[0] is not None:
            os.environ["GEMINI_API_KEY"] = orig_env[0]
        if orig_env[1] is not None:
            os.environ["GEMINI_API_KEYS"] = orig_env[1]


def test_thinking_budget_zero_skipped_on_gemini_3():
    """thinking_budget=0 只有 2.x 收，送給 3.x 會被回 400，必須改為不送。"""
    from google.genai import types

    orig_model, orig_budget = Config.GEMINI_MODEL, Config.GEMINI_THINKING_BUDGET
    try:
        Config.GEMINI_THINKING_BUDGET = 0
        Config.GEMINI_MODEL = "gemini-3.6-flash"
        assert llm._thinking_config(types) is None
        Config.GEMINI_MODEL = "gemini-2.5-flash"
        assert llm._thinking_config(types).thinking_budget == 0
        # 明確指定的正數預算，任何模型都照送
        Config.GEMINI_THINKING_BUDGET = 512
        Config.GEMINI_MODEL = "gemini-3.6-flash"
        assert llm._thinking_config(types).thinking_budget == 512
    finally:
        Config.GEMINI_MODEL, Config.GEMINI_THINKING_BUDGET = orig_model, orig_budget


if __name__ == "__main__":
    test_keys_merged_and_deduped()
    test_rotation_tries_each_key_until_one_works()
    test_raises_after_all_keys_exhausted()
    test_no_key_raises_helpful_error()
    test_thinking_budget_zero_skipped_on_gemini_3()
    print("OK")
