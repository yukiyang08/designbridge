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
