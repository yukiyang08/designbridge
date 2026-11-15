"""沙發外型篩選：零件、轉角、躺椅、單人座、沙發床。"""

from designbridge.pricing.furniture_kb import filter_sofa_shape

POOL = [
    {"name": "SÖDERHAMN 轉角沙發，Fridtuna 深灰藍色", "subcategory": "sofa"},
    {"name": "SÖDERHAMN 三人座沙發，Kelinge 深藍色", "subcategory": "sofa"},
    {"name": "SÖDERHAMN 單人座沙發，Kelinge 深藍色", "subcategory": "sofa"},
    {"name": "SÖDERHAMN 四人座轉角沙發，Kelinge 深藍色", "subcategory": "sofa"},
    {"name": "MANNARP 三人座沙發附躺椅，Saxemara 黑藍色", "subcategory": "sofa"},
    {"name": "VIMLE 收納椅凳，Gunnared 米色", "subcategory": "sofa"},
    {"name": "HYLTARP 雙人座沙發床，Kilanda 淡藍色", "subcategory": "sofa-bed"},
]


def names(pool):
    return [h["name"].split("，")[0] for h in pool]


def test_plain_sofa_gets_only_regular_multi_seat():
    assert names(filter_sofa_shape(POOL, "藍色雙人沙發")) == ["SÖDERHAMN 三人座沙發"]
    assert names(filter_sofa_shape(POOL, "沙發")) == ["SÖDERHAMN 三人座沙發"]


def test_l_shaped_gets_corner_and_chaise():
    assert names(filter_sofa_shape(POOL, "L型沙發")) == ["SÖDERHAMN 四人座轉角沙發", "MANNARP 三人座沙發附躺椅"]


def test_explicit_single_and_sofa_bed():
    assert "SÖDERHAMN 單人座沙發" in names(filter_sofa_shape(POOL, "單人沙發"))
    assert "HYLTARP 雙人座沙發床" in names(filter_sofa_shape(POOL, "沙發床"))


def test_falls_back_when_filter_empties_pool():
    only_parts = [POOL[0], POOL[5]]
    assert filter_sofa_shape(only_parts, "沙發") == only_parts
