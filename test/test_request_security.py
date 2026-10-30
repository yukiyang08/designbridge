"""請求帶來的路徑／網址守門：路徑穿越、SSRF、SVG 注入、非成員掛進別人的設計。離線。"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

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


def test_request_payload_limits():
    with pytest.raises(ValidationError):
        DesignRequest(text_prompt="x" * 2001)
    with pytest.raises(ValidationError):
        DesignRequest(scene_graph={"furniture_placements": [{}] * 301})
    with pytest.raises(ValidationError):   # plan 裡面包的 scene_graph 也要檢查
        DesignRequest(plan={"scene_graph": {"furniture_placements": [{}] * 301}})
    with pytest.raises(ValidationError):
        DesignRequest(cad_plan={"svg": "x" * 2_100_000})
    with pytest.raises(ValidationError):   # 除錯覆寫欄位不能拿來燒 fal 額度
        DesignRequest(controlnet_steps_override=10_000)
    DesignRequest(text_prompt="x" * 2000, scene_graph={"furniture_placements": [{}] * 300})


def test_llm_room_size_is_clamped():
    from designbridge.core.nodes.requirement import _normalize_space_info
    req = {"space_info": {"estimated_size": {"width": 1e9, "depth": "inf", "height": -3}}}
    _normalize_space_info(req)
    assert req["space_info"]["estimated_size"] == {"width": 50.0, "height": 2.8, "depth": 50.0}


def _jpeg_with_exif(path, orientation):
    from PIL import Image
    im = Image.new("RGB", (400, 300), "white")
    exif = Image.Exif()
    exif[0x0112] = orientation   # Orientation
    exif[0x010F] = "SomePhone"   # Make：代表會被一起剝除的中繼資料
    im.save(path, "JPEG", exif=exif)


def test_upload_is_rotated_and_exif_stripped(tmp_path):
    from PIL import Image
    from routers.generate import _normalize_upload
    f = tmp_path / "a.jpg"
    _jpeg_with_exif(f, 6)
    assert Image.open(f).size == (400, 300)   # 不處理的話後端看到的是橫躺的
    _normalize_upload(f)
    with Image.open(f) as fixed:
        assert fixed.size == (300, 400)       # 與瀏覽器顯示的方向一致
        assert not fixed.getexif()            # 方向以外的中繼資料（含 GPS）一併移除


def test_upload_without_exif_is_left_untouched(tmp_path):
    from PIL import Image
    from routers.generate import _normalize_upload
    f = tmp_path / "plain.png"
    Image.new("RGB", (40, 30)).save(f)
    before = f.read_bytes()
    _normalize_upload(f)
    assert f.read_bytes() == before


def test_upload_rejects_non_image_and_huge_images(tmp_path, monkeypatch):
    from PIL import Image
    import routers.generate as gen
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"<html>not an image</html>")
    with pytest.raises(HTTPException) as e:
        gen._normalize_upload(fake)
    assert e.value.status_code == 400 and not fake.exists()   # 不是圖片：回 400 並刪檔

    big = tmp_path / "big.png"
    Image.new("RGB", (100, 100)).save(big)
    monkeypatch.setattr(gen, "_MAX_UPLOAD_PIXELS", 5000)
    with pytest.raises(HTTPException):
        gen._normalize_upload(big)
    assert not big.exists()


def test_request_body_over_limit_is_413():
    from fastapi.testclient import TestClient
    from api import app
    r = TestClient(app).post("/api/health", content=b"x" * (31 * 1024 * 1024))
    assert r.status_code == 413
