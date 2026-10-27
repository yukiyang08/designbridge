"""請求帶來的路徑／網址守門：路徑穿越、SSRF、SVG 注入、非成員掛進別人的設計。離線。"""
import pytest
from fastapi import HTTPException

import routers.common as common
from designbridge.style import style_supabase as ss
from routers.common import DesignRequest, check_request_paths


@pytest.fixture
def art(tmp_path, monkeypatch):
    d = (tmp_path / "artifacts").resolve()
    (d / "uploads").mkdir(parents=True)
    monkeypatch.setattr(common, "ARTIFACTS_DIR", d)
    return d


def _req(**kw):
    return DesignRequest(text_prompt="x", **kw)


@pytest.mark.parametrize("field", ["initial_image_path", "mask_image_path", "floor_plan_path", "style_reference_image_path"])
def test_path_outside_artifacts_rejected(art, field, tmp_path):
    secret = tmp_path / ".env"
    secret.write_text("KEY=1")
    for bad in (str(secret), str(art / "uploads" / ".." / ".." / ".env")):   # 絕對路徑、含 uploads 的 ../ 穿越
        with pytest.raises(HTTPException) as e:
            check_request_paths(_req(**{field: bad}))
        assert e.value.status_code == 400


def test_nested_paths_in_scene_graph_and_plan_are_checked(art, tmp_path):
    outside = str(tmp_path / "x.png")
    for kw in ({"scene_graph": {"projected_depth_path": outside}},
               {"plan": {"scene_graph": {"seg": [{"projected_seg_path": outside}]}}},
               {"plan": {"generated_image_path": outside}}):
        with pytest.raises(HTTPException):
            check_request_paths(_req(**kw))


def test_artifact_paths_and_style_url_are_allowed(art):
    ok = str(art / "uploads" / "a.png")   # 不要求檔案存在
    check_request_paths(_req(initial_image_path=ok, floor_plan_path=ok,
                             scene_graph={"projected_depth_path": ok},
                             style_reference_image_path="https://example.com/ref.jpg"))


@pytest.mark.parametrize("url", ["http://169.254.169.254/latest/meta-data", "http://127.0.0.1:8000/x",
                                 "http://10.0.0.5/a.jpg", "http://[::1]/a.jpg", "file:///etc/passwd", "ftp://8.8.8.8/a.jpg"])
def test_ssrf_urls_are_blocked(url):
    with pytest.raises(ValueError):
        ss._assert_public_url(url)


def test_public_ip_allowed_and_non_image_not_cached(tmp_path, monkeypatch):
    ss._assert_public_url("https://8.8.8.8/a.jpg")   # 公網位址放行

    class R:   # 假的 httpx 回應：200 但內容是 JSON（模擬抓到內網 API 回應）
        is_redirect, next_request, content = False, None, b'{"secret": 1}'
        def raise_for_status(self): pass
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: R())
    monkeypatch.setattr(ss, "STYLE_REF_DIR", tmp_path)
    assert ss.download_style_image("https://8.8.8.8/a.jpg") is None   # 不是圖片，不落地
    assert list(tmp_path.iterdir()) == []


def test_redirect_to_internal_is_blocked(tmp_path, monkeypatch):
    class Redirect:
        is_redirect = True
        next_request = type("N", (), {"url": "http://169.254.169.254/latest"})()
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: Redirect())
    with pytest.raises(ValueError):
        ss._fetch_image_bytes("https://8.8.8.8/a.jpg")


def test_svg_room_name_is_escaped():
    from designbridge.roomplan.svg_render import escape
    assert escape("</text><g onload=x>&") == "&lt;/text&gt;&lt;g onload=x&gt;&amp;"
