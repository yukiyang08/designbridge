"""報價比對前的大類修正：Gemini 給的 category 跟商品庫不同時，依名稱改到對的大類。"""

from __future__ import annotations

import designbridge.pricing.furniture_kb as kb
import designbridge.pricing.quotation as quotation


def _searched_category(monkeypatch, name, category):
    seen = {}

    def fake_search(name_zh, category="", top_k=3):
        seen["category"] = category
        return [{"id": "1", "name": "x", "price": 100, "url": "", "image_url": ""}]

    monkeypatch.setattr(kb, "search_kb", fake_search)
    quotation._process_furniture_item({"name_zh": name, "category": category}, img=None)
    return seen["category"]


def test_category_follows_name(monkeypatch):
    assert _searched_category(monkeypatch, "床頭櫃", "table") == "storage"
    assert _searched_category(monkeypatch, "電視櫃", "table") == "storage"
    assert _searched_category(monkeypatch, "單人沙發", "sofa") == "chair"
    assert _searched_category(monkeypatch, "長凳", "sofa") == "chair"
    assert _searched_category(monkeypatch, "盆栽", "other") == "decor"
    assert _searched_category(monkeypatch, "鏡子", "other") == "decor"


def test_unrelated_names_keep_category(monkeypatch):
    assert _searched_category(monkeypatch, "三人沙發", "sofa") == "sofa"
    assert _searched_category(monkeypatch, "窗簾", "curtain") == "curtain"


def test_other_skips_text_search(monkeypatch):
    # 電視不能靠文字搜尋配到電視櫃，要走 LLM 估價
    monkeypatch.setattr(kb, "search_kb", lambda *a, **k: [{"name": "電視櫃", "price": 9999}])
    monkeypatch.setattr(quotation, "_estimate_price_llm", lambda name: 12345)
    item, matched = quotation._process_furniture_item({"name_zh": "電視", "category": "other"}, img=None)
    assert not matched and item["candidates"][0]["price"] == 12345


def test_tiny_box_still_cropped():
    # 崁燈在 1024 寬的圖上常只有十幾 px，要撐大後照樣比對，不能直接放棄
    from PIL import Image
    crop = quotation.crop_image_by_bbox(Image.new("RGB", (1024, 576)), [0.448, 0.078, 0.465, 0.093])
    assert crop is not None and min(crop.size) >= 60
    assert quotation.crop_image_by_bbox(Image.new("RGB", (1024, 576)), [0.5, 0.5, 0.5, 0.6]) is None
