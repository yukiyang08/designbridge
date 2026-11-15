"""風格搜尋帶房型時只在該房型的圖裡找（RPC 沒有 space 參數，篩選在 style_supabase 做）。"""

import numpy as np

import designbridge.style.style_supabase as ss


def _rows(styles):
    return [{"style_id": s, "image_url": f"u{i}", "source_meta": {}, "style_kb": {}} for i, s in enumerate(styles)]


def _fake(monkeypatch, rows, embs):
    monkeypatch.setattr(ss, "_get_supabase", lambda: None)
    monkeypatch.setattr(ss, "_space_rows", lambda client, space: (rows, embs))
    monkeypatch.setattr(ss, "_encode_query_text", lambda t: np.array([1.0, 0.0], dtype=np.float32))


def test_ranks_within_space_by_similarity(monkeypatch):
    embs = np.array([[1.0, 0.0] if i == 7 else [0.0, 1.0] for i in range(12)], dtype=np.float32)
    _fake(monkeypatch, _rows(["modern"] * 12), embs)
    out = ss._query_style_in_space("q", None, 3, "浴室", fill_other_styles=True)
    assert out[0].image_url == "u7"
    assert len(out) == 3


def test_falls_back_when_space_too_small_or_too_large(monkeypatch):
    _fake(monkeypatch, _rows(["modern"] * 5), np.ones((5, 2), np.float32))
    assert ss._query_style_in_space("q", None, 3, "浴室", True) is None, "太少要退回全庫"
    _fake(monkeypatch, None, None)
    assert ss._query_style_in_space("q", None, 3, "客廳", True) is None, "太大（客廳）走 RPC"


def test_chosen_style_first_then_other_styles_of_same_room(monkeypatch):
    # 浴室只有 2 張北歐：北歐排前面，其餘用浴室的其他風格補，不退回北歐客廳
    styles = ["nordic", "modern", "modern", "nordic"] + ["modern"] * 8
    _fake(monkeypatch, _rows(styles), np.ones((12, 2), np.float32))
    out = ss._query_style_in_space("q", "nordic", 6, "浴室", fill_other_styles=True)
    assert [r.style_id for r in out[:2]] == ["nordic", "nordic"]
    assert len(out) == 6


def test_per_style_mode_never_borrows(monkeypatch):
    # 「各風格一張」：這個風格在浴室沒有圖就回空，不拿別的風格或別的房型充數
    _fake(monkeypatch, _rows(["modern"] * 12), np.ones((12, 2), np.float32))
    assert ss._query_style_in_space("q", "american", 3, "浴室", fill_other_styles=False) == []
