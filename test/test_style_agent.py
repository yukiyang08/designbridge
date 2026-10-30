from designbridge.style import style_agent
from designbridge.style.style_supabase import SupabaseStyleResult


def _r(sid):
    return SupabaseStyleResult(style_id=sid, image_url=sid, display_url=sid, style_name=sid, similarity=0.5, style_kb={})


def test_rewrite_then_pick_best(monkeypatch):
    queries = []
    monkeypatch.setattr(
        style_agent, "query_style_images_supabase",
        lambda text_query, style_id, top_k: queries.append(text_query) or [_r("nordic"), _r("japanese")],
    )
    verdicts = iter([{"ok": False, "rewrite": "日式原木"}, {"ok": True, "best": 1, "reason": "原木"}])
    monkeypatch.setattr(style_agent, "_review", lambda *a: next(verdicts))
    results, reason = style_agent.pick_style_results({}, "日式", None)
    assert queries == ["日式", "日式原木"]
    assert results[0].style_id == "japanese" and reason == "原木"


def test_failure_returns_none(monkeypatch):
    def boom(**_):
        raise RuntimeError("rpc down")
    monkeypatch.setattr(style_agent, "query_style_images_supabase", boom)
    assert style_agent.pick_style_results({}, "x", None) is None
