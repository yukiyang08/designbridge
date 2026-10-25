"""我的設計（雲端）：列表／刪除只動自己的資料、他人設計讀不到；整層並行存檔時每間房都有圖。
離線，用記憶體版的假 Supabase。"""
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import history


class _Q:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload, self.n = db, name, [], "select", None, None

    def select(self, *_): return self
    def order(self, *_, **__): return self
    def limit(self, n): self.n = n; return self
    def delete(self): self.op = "delete"; return self
    def update(self, p): self.op, self.payload = "update", p; return self
    def upsert(self, p, **kw): self.op, self.payload = "upsert", p; return self
    def eq(self, c, v): self.filters.append(lambda r: r.get(c) == v); return self
    def in_(self, c, vs): self.filters.append(lambda r: r.get(c) in vs); return self

    def execute(self):
        rows = self.db.setdefault(self.name, [])
        hit = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "delete":
            for r in hit:
                rows.remove(r)
            return SimpleNamespace(data=hit)
        if self.op == "update":
            for r in hit:
                r.update(self.payload)
            return SimpleNamespace(data=hit)
        if self.op == "upsert":
            key = "id" if self.name == "projects" else "task_id" if self.name == "designs" else None
            if key and any(r.get(key) == self.payload.get(key) for r in rows):
                return SimpleNamespace(data=[])
            rows.append(dict(self.payload))
            return SimpleNamespace(data=[self.payload])
        return SimpleNamespace(data=[dict(r) for r in hit][: self.n])


class FakeSB:
    def __init__(self, db, fail_first_upload=False):
        self.db, self.removed, self.uploaded, self._seen = db, [], {}, set()
        self._fail_once, self._lock = fail_first_upload, threading.Lock()
        self.storage = SimpleNamespace(from_=lambda _b: self)

    def table(self, name): return _Q(self.db, name)

    def upload(self, key, data, opts):
        with self._lock:
            if self._fail_once and key not in self._seen:
                self._seen.add(key)
                raise RuntimeError("connection reset")   # 每個檔第一次上傳都失敗
            self.uploaded[key] = data

    def remove(self, paths): self.removed += list(paths)
    def create_signed_urls(self, paths, ttl): return [{"path": p, "signedURL": "https://x/" + p} for p in paths]


def _db():
    return {
        "designs": [
            {"task_id": "t1", "user_id": "A", "project_id": "p1", "image_path": "A/t1.png", "pano_path": "A/t1_pano.png",
             "floor_plan_path": None, "source_photo_path": None, "style_ref_path": None,
             "record": {}, "title": "A的設計", "quotation": None, "space_id": "main", "space_name": "客廳"},
            {"task_id": "t2", "user_id": "B", "project_id": "p2", "image_path": "B/t2.png", "pano_path": None,
             "floor_plan_path": None, "source_photo_path": None, "style_ref_path": None,
             "record": {}, "title": "B的設計", "quotation": None, "space_id": "main", "space_name": "客廳"},
        ],
        "projects": [{"id": "p1", "user_id": "A", "cad_svg_path": "A/projects/p1_plan.svg"},
                     {"id": "p2", "user_id": "B", "cad_svg_path": None}],
    }


@pytest.fixture
def sb(monkeypatch):
    s = FakeSB(_db())
    monkeypatch.setattr(history, "_get_supabase", lambda: s)
    return s


def test_list_only_returns_own_designs(sb):
    out = history.get_history(limit=0, user_id="A")
    assert [r["title"] for r in out] == ["A的設計"]


def test_delete_removes_row_and_storage_files(sb):
    assert history.delete_history(task_ids=["t1"], user_id="A") == {"deleted": 1}
    assert [r["task_id"] for r in sb.db["designs"]] == ["t2"]
    assert {"A/t1.png", "A/t1_pano.png", "A/projects/p1_plan.svg"} <= set(sb.removed)   # 圖、環景、平面圖一併移除
    assert [p["id"] for p in sb.db["projects"]] == ["p2"]                                  # 設計底下沒圖了就連設計刪掉


def test_cannot_delete_other_users_design(sb):
    assert history.delete_history(task_ids=["t2"], user_id="A") == {"deleted": 0}
    assert len(sb.db["designs"]) == 2 and sb.removed == []


def test_other_users_project_is_not_found(sb):
    with pytest.raises(HTTPException) as e:
        history.get_project("p2", user_id="A")
    assert e.value.status_code == 404


def test_parallel_room_saves_all_reach_cloud(tmp_path, monkeypatch):
    """整層套用到其他房間：多間房同時存檔，每個檔第一次上傳都失敗，仍要每間房都有圖。"""
    s = FakeSB({}, fail_first_upload=True)
    monkeypatch.setattr(history, "_get_supabase", lambda: s)
    monkeypatch.setattr(history.time, "sleep", lambda _s: None)
    rooms = ["living", "bed1", "bed2", "dining"]

    def save(rid):
        png = tmp_path / f"{rid}.png"
        png.write_bytes(b"png")
        history._save_history("A", {"task_id": f"t_{rid}", "generated_image_path": str(png)},
                              project_id="p1", space_id=rid, space_name=rid)

    ts = [threading.Thread(target=save, args=(r,)) for r in rooms]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(r["space_id"] for r in s.db["designs"]) == sorted(rooms)
    assert all(r["image_path"] for r in s.db["designs"])


def _share(sb):
    for p in sb.db["projects"]:
        p.update(share_token=None, invite_token=None, title="設計")


def test_invite_makes_editor_who_sees_and_edits_but_cannot_delete(sb):
    _share(sb)
    # 非擁有者不能開邀請連結
    with pytest.raises(HTTPException) as e:
        history.put_sharing("p1", history.SharingBody(invite=True), user_id="B")
    assert e.value.status_code == 404
    token = history.put_sharing("p1", history.SharingBody(invite=True), user_id="A")["invite_token"]
    assert history.put_sharing("p1", history.SharingBody(invite=True), user_id="A")["invite_token"] == token   # 已開就沿用

    assert history.accept_invite(token, user_id="B")["project_id"] == "p1"
    assert {r["title"] for r in history.get_history(limit=0, user_id="B")} == {"A的設計", "B的設計"}
    roles = {r["title"]: r["role"] for r in history.get_history(limit=0, user_id="B")}
    assert roles == {"A的設計": "editor", "B的設計": "owner"}

    history.put_project_state("p1", history.ProjectState(settings={"x": 1}), user_id="B")
    assert sb.db["projects"][0]["settings"] == {"x": 1}
    assert history.delete_history(task_ids=["t1"], user_id="B") == {"deleted": 0}   # 共編者不能刪

    history.remove_member("p1", "B", user_id="B")   # 共編者自己退出
    assert [r["title"] for r in history.get_history(limit=0, user_id="B")] == ["B的設計"]


def test_invite_revoked_or_unknown_token_is_404(sb):
    _share(sb)
    token = history.put_sharing("p1", history.SharingBody(invite=True), user_id="A")["invite_token"]
    history.put_sharing("p1", history.SharingBody(invite=False), user_id="A")
    for t in (token, "nope"):
        with pytest.raises(HTTPException) as e:
            history.accept_invite(t, user_id="B")
        assert e.value.status_code == 404


def test_cannot_attach_design_to_someone_elses_project(sb):
    """沒有權限的人帶別人的 project_id 存檔：另開新設計，不能掛進對方（與其共編者）的設計。"""
    history._save_history("B", {"task_id": "intruder"}, project_id="p1", space_id="main", space_name="x")
    row = next(r for r in sb.db["designs"] if r["task_id"] == "intruder")
    assert row["project_id"] != "p1" and row["user_id"] == "B"
