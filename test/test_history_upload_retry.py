"""history._upload：雲端上傳偶發失敗要重試，全部失敗才放棄（不擋紀錄）。離線，用假的 Storage。"""
from types import SimpleNamespace

from routers import history


class _Bucket:
    def __init__(self, fail_times):
        self.fail_times, self.calls = fail_times, 0

    def upload(self, key, data, opts):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("connection reset")


def _sb(bucket):
    return SimpleNamespace(storage=SimpleNamespace(from_=lambda name: bucket))


def _png(tmp_path):
    p = tmp_path / "render.png"
    p.write_bytes(b"png")
    return p


def test_succeeds_first_try(tmp_path, monkeypatch):
    monkeypatch.setattr(history.time, "sleep", lambda s: None)
    b = _Bucket(0)
    assert history._upload(_sb(b), "u1", "t1", _png(tmp_path)) == "u1/t1.png"
    assert b.calls == 1


def test_retries_after_transient_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(history.time, "sleep", lambda s: None)
    b = _Bucket(2)
    assert history._upload(_sb(b), "u1", "t1", _png(tmp_path)) == "u1/t1.png"
    assert b.calls == 3


def test_gives_up_after_all_tries(tmp_path, monkeypatch):
    monkeypatch.setattr(history.time, "sleep", lambda s: None)
    b = _Bucket(99)
    assert history._upload(_sb(b), "u1", "t1", _png(tmp_path)) is None
    assert b.calls == history._UPLOAD_TRIES


def test_missing_local_file_skips_upload(tmp_path):
    b = _Bucket(0)
    assert history._upload(_sb(b), "u1", "t1", tmp_path / "nope.png") is None
    assert b.calls == 0
