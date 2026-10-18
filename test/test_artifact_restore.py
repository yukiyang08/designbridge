"""ensure_artifact：本機缺渲染圖時從 Supabase Storage 補回；路徑守門不能被繞過。
用假的 supabase，不連網。"""
import pytest

import routers.common as common


class _Query:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def select(self, *_):
        return self

    def eq(self, col, val):
        self.log.append(("eq", col, val))
        return self

    def like(self, col, pattern):
        self.log.append(("like", col, pattern))
        return self

    def limit(self, _):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Bucket:
    def __init__(self, store, log):
        self.store, self.log = store, log

    def download(self, key):
        self.log.append(("download", key))
        return self.store[key]


class FakeSupabase:
    def __init__(self, rows=None, store=None):
        self.rows, self.store, self.log = rows or [], store or {}, []

    def table(self, name):
        self.log.append(("table", name))
        return _Query(self.rows, self.log)

    @property
    def storage(self):
        return type("S", (), {"from_": lambda _s, _b: _Bucket(self.store, self.log)})()


@pytest.fixture
def env(tmp_path, monkeypatch):
    art = (tmp_path / "artifacts").resolve()
    (art / "render").mkdir(parents=True)
    monkeypatch.setattr(common, "ARTIFACTS_DIR", art)
    return art


def _use(monkeypatch, fake):
    monkeypatch.setattr(common, "_get_supabase", lambda: fake)
    return fake


def test_existing_file_needs_no_supabase(env, monkeypatch):
    fake = _use(monkeypatch, FakeSupabase())
    f = env / "render" / "a_1.png"
    f.write_bytes(b"x")
    assert common.ensure_artifact(str(f), "u1") is True
    assert fake.log == []


def test_restores_missing_render_from_storage(env, monkeypatch):
    fake = _use(monkeypatch, FakeSupabase(rows=[{"image_path": "u1/a_1.png"}], store={"u1/a_1.png": b"PNG"}))
    f = env / "render" / "a_1.png"
    assert common.ensure_artifact(str(f), "u1") is True
    assert f.read_bytes() == b"PNG"
    assert ("eq", "user_id", "u1") in fake.log          # 只找這位使用者自己的
    assert ("like", "record->>generated_image_path", "%a_1.png") in fake.log


def test_no_user_or_no_row_returns_false(env, monkeypatch):
    _use(monkeypatch, FakeSupabase(rows=[]))
    f = env / "render" / "a_1.png"
    assert common.ensure_artifact(str(f), None) is False
    assert common.ensure_artifact(str(f), "u1") is False
    assert not f.exists()


@pytest.mark.parametrize("rel", ["../outside.png", "uploads/a.png", "render/%.png", "render/a b.png"])
def test_path_guard_blocks_without_touching_supabase(env, monkeypatch, tmp_path, rel):
    fake = _use(monkeypatch, FakeSupabase(rows=[{"image_path": "u1/k.png"}], store={"u1/k.png": b"x"}))
    assert common.ensure_artifact(str(env / rel), "u1") is False
    assert common.ensure_artifact(str(tmp_path / "abs.png"), "u1") is False
    assert fake.log == []

def test_save_panorama_uploads_png_and_records_key(tmp_path, monkeypatch):
    import routers.history as history
    pano = tmp_path / "panorama.png"
    pano.write_bytes(b"PNG")
    calls = []

    class Bucket:
        def upload(self, key, data, opts):
            calls.append(("upload", key, data))

    class Q:
        def update(self, v):
            calls.append(("update", v))
            return self

        def eq(self, *a):
            calls.append(("eq", *a))
            return self

        def execute(self):
            return None

    class SB:
        storage = type("S", (), {"from_": lambda s, b: Bucket()})()

        def table(self, n):
            calls.append(("table", n))
            return Q()

    monkeypatch.setattr(history, "_get_supabase", lambda: SB())
    assert history.save_panorama("u1", "t1", str(pano)) == "u1/t1_pano.png"   # key 固定 _pano.png
    assert ("upload", "u1/t1_pano.png", b"PNG") in calls
    assert ("update", {"pano_path": "u1/t1_pano.png"}) in calls
    assert ("eq", "task_id", "t1") in calls and ("eq", "user_id", "u1") in calls
    assert history.save_panorama("u1", "t1", str(tmp_path / "missing.png")) is None   # 沒檔案不擋環景本身
