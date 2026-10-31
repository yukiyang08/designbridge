"""條件圖預先計算：同參數只算一次、參數變了重算、失敗不留快取。"""
from designbridge.layout import condition_prefetch as cp

PL = [{"type": "sofa", "x": 1.0, "y": 2.0, "w": 2.0, "h": 0.9, "rotation": 0.0}]


def _fake(calls, tmp_path):
    def fake(placements, file_id, rw, rd, w, h):
        calls.append(file_id)
        d = tmp_path / f"{file_id}.png"
        d.write_bytes(b"x")
        return {"camera": {}, "score": 0.5, "edge_path": None, "depth_path": str(d)}
    return fake


def test_hit_and_miss(monkeypatch, tmp_path):
    cp._jobs.clear()
    calls: list[str] = []
    monkeypatch.setattr(cp, "_compute", _fake(calls, tmp_path))
    a = cp.get_conditions(PL, 4.0, 3.0, 1024, 768)
    assert cp.get_conditions(PL, 4.0, 3.0, 1024, 768) == a and len(calls) == 1
    cp.get_conditions(PL, 4.0, 3.0, 768, 1024)          # 輸出比例不同 → 重算
    cp.get_conditions([{**PL[0], "x": 1.5}], 4.0, 3.0, 1024, 768)  # 家具被挪 → 重算
    assert len(calls) == 3


def test_failure_not_cached(monkeypatch, tmp_path):
    cp._jobs.clear()
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("boom")
        return _fake([], tmp_path)(*a, **k)

    monkeypatch.setattr(cp, "_compute", flaky)
    try:
        cp.get_conditions(PL, 4.0, 3.0, 1024, 768)
    except RuntimeError:
        pass
    assert cp.get_conditions(PL, 4.0, 3.0, 1024, 768)["depth_path"]
