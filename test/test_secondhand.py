"""二手家具比對：大類、細分類篩選與門檻（不讀真實資料檔，不需要 CLIP 模型）。"""

import numpy as np
import pytest

from designbridge.pricing import secondhand


def _vec(i: int, dim: int = 8) -> np.ndarray:
    v = np.zeros(dim, dtype="float32")
    v[i] = 1.0
    return v


@pytest.fixture
def fake_kb(monkeypatch):
    items = [
        {"name": "皮革餐椅", "category": "chair", "subcategory": "dining-chair", "product_code": "1", "price": 1600,
         "url": "u1", "image_url": "i1", "brand": "北二高家具"},
        {"name": "黑色辦公椅", "category": "chair", "subcategory": "desk-chair", "product_code": "2", "price": 299,
         "url": "u2", "image_url": "i2", "brand": "北二高家具"},
        {"name": "柚木沙發", "category": "sofa", "subcategory": "sofa", "product_code": "3", "price": 14500,
         "url": "u3", "image_url": "i3", "brand": "北二高家具"},
        {"name": "收納櫃", "category": "storage", "subcategory": "sideboard", "product_code": "4", "price": 1800,
         "url": "u4", "image_url": "i4", "brand": "北二高家具"},
    ]
    matrix = np.stack([_vec(0), _vec(0) * 0.9 + _vec(1) * 0.436, _vec(2), _vec(3)])
    monkeypatch.setattr(secondhand, "_load", lambda: (items, matrix))
    return items


def test_filters_by_category(fake_kb):
    hits = secondhand.match_secondhand(_vec(2).tolist(), "sofa", "三人座沙發")
    assert [h["name"] for h in hits] == ["柚木沙發"]


def test_subcategory_excludes_other_chairs(fake_kb):
    # 查詢跟餐椅最像，但偵測到的是辦公椅，只能推薦辦公椅
    hits = secondhand.match_secondhand(_vec(0).tolist(), "chair", "辦公椅")
    assert [h["name"] for h in hits] == ["黑色辦公椅"]


def test_below_threshold_returns_nothing(fake_kb):
    assert secondhand.match_secondhand(_vec(5).tolist(), "chair", "餐椅") == []


def test_storage_needs_known_subtype(fake_kb):
    # 「壁掛架」對不到細分類，不要硬推收納櫃
    assert secondhand.match_secondhand(_vec(3).tolist(), "storage", "壁掛架") == []
    assert secondhand.match_secondhand(_vec(3).tolist(), "storage", "收納櫃")


def test_built_in_cabinets_skipped(fake_kb):
    assert secondhand.match_secondhand(_vec(3).tolist(), "storage", "廚房系統收納櫃") == []


def test_to_candidate_marks_source(fake_kb):
    hit = secondhand.match_secondhand(_vec(2).tolist(), "sofa", "沙發")[0]
    c = secondhand.to_candidate(hit)
    assert c["source"] == "secondhand" and c["store"] == "北二高家具"
    assert c["id"] == "beg-3" and c["price"] == 14500 and c["purchase_url"] == "u3"


def test_generic_chair_skips_office_chairs(fake_kb):
    # 「單人椅」對不到細分類：不推薦辦公椅，只剩餐椅
    hits = secondhand.match_secondhand((_vec(0) * 0.9 + _vec(1) * 0.436).tolist(), "chair", "單人椅")
    assert [h["name"] for h in hits] == ["皮革餐椅"]
