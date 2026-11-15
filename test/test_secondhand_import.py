"""二手家具 CSV 匯入：欄位對應、驗證、分類（不碰真實資料檔）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from import_secondhand_csv import convert  # noqa: E402
from secondhand_store import classify  # noqa: E402

ROW = {"名稱": "實木咖啡桌 90x90", "價格": "$2,750", "網址": "https://x.test/p/1", "圖片網址": "https://x.test/1.jpg"}


def test_chinese_headers_and_price_format():
    items, problems = convert([{**ROW, "分類": "桌子", "原價": "4,500", "寬": "90", "評級": "A級"}], "ESG.STYLE")
    assert not problems
    it = items[0]
    assert (it["category"], it["subcategory"], it["price"]) == ("table", "coffee-side-table", 2750)
    assert it["original_price"] == 4500 and it["width_cm"] == 90 and it["grade"] == "A級"
    assert it["brand"] == "ESG.STYLE" and it["condition"] == "二手" and it["id"].startswith("esg-style-")


def test_english_headers():
    row = {"name": "Leather dining chair 餐椅", "price": "1200", "url": "https://x.test/2", "image_url": "https://x.test/2.jpg"}
    items, problems = convert([row], "Shop")
    assert not problems and items[0]["category"] == "chair"


def test_invalid_rows_are_reported():
    rows = [
        {**ROW, "圖片網址": ""},
        {**ROW, "名稱": "神秘物品", "網址": "https://x.test/a"},
        {**ROW, "分類": "電器", "網址": "https://x.test/b"},
        {**ROW, "價格": "面議", "網址": "https://x.test/c"},
        ROW, ROW,   # 第二筆網址重複
    ]
    items, problems = convert(rows, "S")
    assert len(items) == 1 and len(problems) == 5


def test_user_category_wins_over_name():
    # 名稱有「椅」但使用者填桌子：大類用桌子
    assert classify("吧台椅桌組", "table", keep_default=True)[0] == "table"
    # 爬蟲沒填分類：名稱判斷
    assert classify("橘色扶手沙發", "chair") == ("chair", "armchair")
