"""Gemini 3.x flash 必須明確關閉思考，否則思考 token 會吃掉輸出額度、提示詞被截斷。離線。"""
from google.genai import types

from designbridge.core.config import Config
from designbridge.render import llm


def _cfg(monkeypatch, model, budget=0):
    monkeypatch.setattr(Config, "GEMINI_MODEL", model)
    monkeypatch.setattr(Config, "GEMINI_THINKING_BUDGET", budget)
    return llm._thinking_config(types)


def test_3x_flash_uses_minimal_thinking_level(monkeypatch):
    cfg = _cfg(monkeypatch, "gemini-3.6-flash")
    assert str(cfg.thinking_level.value).lower() == "minimal"
    assert cfg.thinking_budget is None   # 3.x 不能送 thinking_budget=0


def test_2x_flash_turns_thinking_off_with_zero_budget(monkeypatch):
    cfg = _cfg(monkeypatch, "gemini-2.5-flash")
    assert cfg.thinking_budget == 0


def test_positive_budget_is_passed_through(monkeypatch):
    assert _cfg(monkeypatch, "gemini-3.6-flash", budget=512).thinking_budget == 512


def test_max_tokens_leaves_room_for_thinking(monkeypatch):
    # -1 動態思考實測一次想 7k token：沒留餘裕時平面圖種子點的 JSON 被截在一半
    _cfg(monkeypatch, "gemini-3.6-flash", budget=-1)
    assert llm._thinking_headroom() >= 8192
    _cfg(monkeypatch, "gemini-3.6-flash", budget=2048)
    assert llm._thinking_headroom() == 2048
    _cfg(monkeypatch, "gemini-3.6-flash", budget=0)   # minimal：幾乎不想，不用留
    assert llm._thinking_headroom() == 0


def test_per_call_budget_overrides_global(monkeypatch):
    # 平面圖單獨開思考，全域維持 minimal
    _cfg(monkeypatch, "gemini-3.6-flash", budget=0)
    assert llm._thinking_config(types, -1).thinking_budget == -1
    assert llm._thinking_headroom(-1) >= 8192
    assert llm._thinking_headroom() == 0


def test_json_mode_sets_mime_type_on_gemini(monkeypatch):
    monkeypatch.setattr(llm, "_get_client", lambda _key: None)
    _, cfg = llm._gemini_client_and_config(None, None, None, 1000, json_mode=True)
    assert cfg.response_mime_type == "application/json"
    _, cfg = llm._gemini_client_and_config(None, None, None, 1000)
    assert cfg.response_mime_type is None
