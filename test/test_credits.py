"""charge_credit：點數不足回 402、端點失敗退點、管理員不扣也不退。不連 Supabase。"""
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.common as common


class _FakeSb:
    def __init__(self, credits):
        self.credits, self.calls = credits, []

    def rpc(self, name, params):
        self.calls.append(params["amount"])
        if self.credits == "admin":
            data = -1
        elif self.credits >= params["amount"]:
            self.credits -= params["amount"]
            data = self.credits
        else:
            data = None
        return type("Q", (), {"execute": lambda _s: type("R", (), {"data": data})()})()


def _client(monkeypatch, sb):
    monkeypatch.setattr(common, "_get_supabase", lambda: sb)
    app = FastAPI()
    app.dependency_overrides[common.get_user_id] = lambda: "u1"

    @app.post("/ok")
    def ok(_: str = Depends(common.charge_credit)):
        return {}

    @app.post("/fail")
    def fail(_: str = Depends(common.charge_credit)):
        raise HTTPException(status_code=502, detail="x")

    return TestClient(app)


def test_charge_and_refund(monkeypatch):
    sb = _FakeSb(2)
    c = _client(monkeypatch, sb)
    assert c.post("/ok").status_code == 200 and sb.credits == 1
    assert c.post("/fail").status_code == 502 and sb.credits == 1   # 失敗退回
    assert c.post("/ok").status_code == 200 and sb.credits == 0
    assert c.post("/ok").status_code == 402 and sb.credits == 0


def test_admin_not_charged(monkeypatch):
    sb = _FakeSb("admin")
    c = _client(monkeypatch, sb)
    assert c.post("/fail").status_code == 502
    assert sb.calls == [1]   # 沒有退點呼叫


def test_pending_user_blocked(monkeypatch):
    import pytest
    from types import SimpleNamespace
    monkeypatch.setattr(common, "activate_if_allowed", lambda _u: "pending")
    for meta, ok in (({}, False), ({"role": "user"}, True), ({"role": "admin"}, True)):
        monkeypatch.setattr(common, "_get_user", lambda *_a, m=meta: SimpleNamespace(id="u1", app_metadata=m))
        if ok:
            assert common.get_user_id(None) == "u1"
        else:
            with pytest.raises(HTTPException) as e:
                common.get_user_id(None)
            assert e.value.status_code == 403
            assert common.get_login_id(None) == "u1"

def test_allowlisted_email_activates(monkeypatch):
    """許可名單裡的 email 第一次請求就開通，並移出名單；不在名單的照樣 403。"""
    import pytest
    from types import SimpleNamespace

    class Sb:
        def __init__(self):
            self.allowed, self.updated = {"a@x.com": "user"}, {}
            self.auth = SimpleNamespace(admin=SimpleNamespace(update_user_by_id=lambda uid, d: self.updated.update({uid: d})))

        def table(self, _name):
            sb = self

            class Q:
                def select(self, *_):
                    self.op = "select"; return self
                def delete(self):
                    self.op = "delete"; return self
                def eq(self, _col, val):
                    self.val = val; return self
                def execute(self):
                    if self.op == "delete":
                        sb.allowed.pop(self.val, None)
                        return SimpleNamespace(data=[])
                    role = sb.allowed.get(self.val)
                    return SimpleNamespace(data=[{"role": role}] if role else [])
            return Q()

    sb = Sb()
    monkeypatch.setattr(common, "_get_supabase", lambda: sb)
    user = lambda email: SimpleNamespace(id=email, email=email, app_metadata={})
    monkeypatch.setattr(common, "_get_user", lambda *_a: user("A@x.com"))
    assert common.get_user_id(None) == "A@x.com"
    assert sb.updated["A@x.com"]["app_metadata"]["role"] == "user" and not sb.allowed
    monkeypatch.setattr(common, "_get_user", lambda *_a: user("b@x.com"))
    with pytest.raises(HTTPException):
        common.get_user_id(None)
