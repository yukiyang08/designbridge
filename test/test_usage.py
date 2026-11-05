"""用量記錄：middleware → get_user_id → 端點 thread pool → 子執行緒都記到同一個帳號；金額估算。不連 Supabase。"""
import contextvars
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from designbridge.core import usage


def test_usage_attributed_to_user(monkeypatch):
    rows = []
    monkeypatch.setattr(usage._writer, "submit", lambda _fn, row: rows.append(row))
    app = FastAPI()

    @app.middleware("http")
    async def ctx(request: Request, call_next):
        usage.start_request(request.url.path)
        return await call_next(request)

    def fake_user_id():   # 跟 get_user_id 一樣是同步依賴，跑在另一個 context 副本
        usage.set_user("u1")
        return "u1"

    @app.post("/gen")
    def gen(_: str = Depends(fake_user_id)):
        usage.record_llm("gemini", 1_000_000, 1_000_000, 2.0)
        with ThreadPoolExecutor(1) as pool:
            pool.submit(contextvars.copy_context().run, usage.record_fal, "fal-ai/flux-general",
                        {"images": [{"width": 1024, "height": 1024}]}, 5.0, 1.5).result()
        return {}

    TestClient(app).post("/gen")
    assert [(r["user_id"], r["route"], r["kind"]) for r in rows] == [("u1", "/gen", "llm"), ("u1", "/gen", "image")]
    assert rows[0]["cost_usd"] == round(sum(usage.GEMINI_PRICE), 6)
    assert rows[1]["cost_usd"] == 0.075 and rows[1]["queue_s"] == 1.5


def test_fal_cost_rounds_up_megapixels(monkeypatch):
    rows = []
    monkeypatch.setattr(usage._writer, "submit", lambda _fn, row: rows.append(row))
    usage.record_fal("fal-ai/flux-kontext/dev", {"images": [{"width": 1536, "height": 1024}]}, 1.0)
    assert rows[0]["cost_usd"] == 0.05 and rows[0]["user_id"] is None   # 1.5 MP 進位成 2
