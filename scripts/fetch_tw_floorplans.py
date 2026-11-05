"""從 100室內設計抓台灣平面配置圖，當房間辨識的內部評估集（不訓練、不散布）。

每個案例的 work_info.blueprints 有裝修前／後的平面圖；取「後」（配置圖，有家具），
順便記下坪數和格局（如 3房2廳2衛），可當比例尺與房間數的對照答案。
存到 test/data/floorplans_tw/（git 已忽略），來源寫進同目錄的 sources.json。

    python scripts/fetch_tw_floorplans.py --n 30
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")

API = "https://api.100.com.tw/hyperf/works"
OUT = Path("test/data/floorplans_tw")
INTERVAL = 1.5   # 每個請求間隔，不對網站造成負擔
HEADERS = {"User-Agent": "Mozilla/5.0 (DesignBridge student research; floor-plan evaluation)"}


def get_json(session: requests.Session, url: str, **params) -> dict:
    time.sleep(INTERVAL)
    r = session.get(url, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    src_file = OUT / "sources.json"
    sources = json.loads(src_file.read_text(encoding="utf-8")) if src_file.is_file() else {}
    have = {v.get("work_id") for v in sources.values()}
    session = requests.Session()

    # 跳著翻頁，涵蓋不同年份、不同設計公司，而不是只有最新的案例
    pages = list(range(1, 300, 7))
    random.Random(args.seed).shuffle(pages)
    got, companies = 0, []
    for page in pages:
        if got >= args.n:
            break
        items = get_json(session, API, page=page, per_page=30, type="images")["data"]
        for it in items:
            if got >= args.n:
                break
            wid, company = it.get("id"), (it.get("company") or {}).get("name", "")
            # 同一家公司最多 2 張，避免評估集被某家的畫法主導
            if wid in have or companies.count(company) >= 2:
                continue
            have.add(wid)
            try:
                d = get_json(session, f"{API}/{wid}")["data"]
            except requests.RequestException as e:
                print(f"  跳過 {wid}：{e}")
                continue
            bps = (d.get("work_info") or {}).get("blueprints") or []
            after = next((b.get("after") for b in bps if (b.get("after") or {}).get("url")), None)
            if not after:
                continue
            time.sleep(INTERVAL)
            img = session.get(after["url"], headers=HEADERS, timeout=30)
            if img.status_code != 200 or len(img.content) < 20_000:
                continue
            name = f"tw_100_{wid}.jpg"
            (OUT / name).write_bytes(img.content)
            sources[name] = {
                "來源": f"100室內設計・{company}", "網址": d.get("share_url") or f"https://www.100.com.tw/works/{wid}",
                "work_id": wid, "坪數": d.get("size_cn"), "格局": d.get("pattern_cn"),
                "類型": d.get("kind_cn"), "風格": d.get("style_cn"),
            }
            companies.append(company)
            got += 1
            print(f"[{got}/{args.n}] {name} {d.get('size_cn')} {d.get('pattern_cn')} {company}", flush=True)
            src_file.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"done：新增 {got} 張 → {OUT}")


if __name__ == "__main__":
    main()
