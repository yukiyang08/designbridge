#!/usr/bin/env python3
"""爬取 100室內設計「設計圖庫」的空間照片（非案例封面）。

使用 hyperf API：每筆為一張空間圖（客廳、廚房、臥室…），約 1.9 萬張。
去重依據：image_id + CDN 檔名（image_key），會跳過 manifest / 本地已有檔案。

Usage (from project root):
    python -m style_kb.scrapper.export_manifest
    python -m style_kb.scrapper.scraper_100_images --target 500
    python -m style_kb.scrapper.scraper_100_images --max-pages 20
    python -m style_kb.scrapper.scraper_100_images --refresh-manifest --target 200
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.stdout.reconfigure(encoding="utf-8")

from style_kb.scrapper.dedup import (
    MANIFEST_PATH,
    fetch_manifest_from_supabase,
    image_asset_key,
    is_duplicate,
    load_manifest,
    save_manifest,
)
from style_kb.scrapper.scraper_100 import (
    BASE_URL,
    REQUEST_INTERVAL,
    REQUEST_TIMEOUT,
    _create_session,
)

HYPERF_API = "https://api.100.com.tw/hyperf/works"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "raw" / "100interior_images"
MIN_FILE_SIZE = 150 * 1024
PER_PAGE = 30


def _space_marker(cover_img: dict) -> str | None:
    markers = cover_img.get("markers") or []
    for marker in markers:
        text = (marker or {}).get("text")
        if text and str(text).strip():
            return str(text).strip()
    return None


def _build_image_info(work: dict, cover_img: dict) -> dict:
    work_id = int(work["id"])
    return {
        "source": "100interior",
        "work_id": work_id,
        "image_id": cover_img.get("id"),
        "url": cover_img.get("url", ""),
        "case_url": f"{BASE_URL}/cases/{work_id}/",
        "work_url": f"{BASE_URL}/works/{work_id}",
        "work_name": work.get("name", ""),
        "style": work.get("style_cn", ""),
        "size": work.get("size_cn", ""),
        "kind": work.get("kind_cn", ""),
        "region": work.get("region_cn", ""),
        "space_id": cover_img.get("space"),
        "space_marker": _space_marker(cover_img),
    }


def _download_image(session: requests.Session, image_info: dict, output_dir: Path) -> bool:
    url = image_info.get("url") or ""
    if not url:
        return False

    clean_url = url.split("!")[0]
    filename = image_asset_key(url)
    if not filename:
        image_id = image_info.get("image_id")
        filename = f"img_{image_info.get('work_id')}_{image_id}.jpg"

    output_path = output_dir / filename
    if output_path.exists():
        return True

    try:
        r = session.get(clean_url, timeout=REQUEST_TIMEOUT, verify=False)
        r.raise_for_status()
        if len(r.content) < MIN_FILE_SIZE:
            print(f"      skip {filename} (too small)")
            return False

        output_path.write_bytes(r.content)
        meta_path = output_dir / f"{output_path.stem}_meta.json"
        meta_path.write_text(json.dumps(image_info, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as exc:
        print(f"      ❌ 下載失敗 {filename}: {exc}")
        return False


def _fetch_page(session: requests.Session, page: int, per_page: int) -> dict:
    params = {"page": page, "per_page": per_page, "type": "images"}
    r = session.get(HYPERF_API, params=params, timeout=REQUEST_TIMEOUT, verify=False)
    r.raise_for_status()
    return r.json()


# 100.com.tw style_cn → 本地 style_id 對照
STYLE_CN_MAP: dict[str, str] = {
    "現代風": "modern", "北歐風": "nordic", "日式風": "japanese",
    "工業風": "industrial", "美式風": "american", "古典風": "classic",
    "新古典": "classic", "輕奢風": "luxury", "奢華風": "luxury",
    "鄉村風": "country", "混搭風": "other", "其他": "other",
}


def scrape_images(
    *,
    target: int | None,
    max_pages: int | None,
    manifest_path: Path,
    refresh_manifest: bool,
    style_filter: str | None = None, 
    kind_filter: str | None = None,   
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if refresh_manifest:
        print("🔄 從 Supabase 更新 manifest...")
        save_manifest(fetch_manifest_from_supabase(), manifest_path)

    manifest = load_manifest(manifest_path)
    print(
        f"📋 manifest: {len(manifest['image_keys'])} keys, "
        f"{len(manifest['image_ids'])} image_ids"
    )
    if style_filter:
        print(f"🎯 只下載風格：{style_filter}")
    if kind_filter:
        print(f"🎯 只下載屋況：{kind_filter}")

    session = _create_session()
    downloaded = 0
    skipped = 0
    style_skipped = 0
    page = 1
    total_pages = max_pages or 10_000

    while page <= total_pages:
        if target is not None and downloaded >= target:
            break

        data = _fetch_page(session, page, PER_PAGE)
        items = data.get("data") or []
        if not items:
            break

        pagination = (data.get("meta") or {}).get("pagination") or {}
        total_pages = min(total_pages, int(pagination.get("total_pages") or total_pages))
        print(f"📄 第 {page}/{total_pages} 頁（{len(items)} 筆）"
              f"  已下載 {downloaded}  跳過重複 {skipped}  跳過風格 {style_skipped}")

        for work in items:
            if target is not None and downloaded >= target:
                break

            # 風格過濾
            if style_filter:
                work_style = work.get("style_cn", "")
                if style_filter not in work_style:
                    style_skipped += 1
                    continue

            # 屋況過濾（例如只要老屋翻新）
            if kind_filter:
                work_kind = work.get("kind_cn", "")
                if kind_filter not in work_kind:
                    style_skipped += 1
                    continue

            cover = work.get("cover_img") or {}
            url = cover.get("url")
            if not url:
                continue

            image_id = cover.get("id")
            key = image_asset_key(url)
            if is_duplicate(image_key=key, image_id=image_id, manifest=manifest):
                skipped += 1
                continue

            image_info = _build_image_info(work, cover)
            if _download_image(session, image_info, OUTPUT_DIR):
                downloaded += 1
                if key:
                    manifest["image_keys"].add(key)
                if image_id is not None:
                    manifest["image_ids"].add(int(image_id))

        page += 1
        time.sleep(REQUEST_INTERVAL)

    print(f"\n✅ 完成：新下載 {downloaded} 張，跳過重複 {skipped} 張，非目標風格 {style_skipped} 張")
    print(f"📁 輸出：{OUTPUT_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description="爬取 100室內設計圖庫空間照片")
    parser.add_argument("--target",   type=int,  default=None, help="最多新下載幾張（預設：不限）")
    parser.add_argument("--max-pages",type=int,  default=None, help="最多爬幾頁 API")
    parser.add_argument("--manifest", type=str,  default=str(MANIFEST_PATH))
    parser.add_argument("--style-filter", type=str, default=None,
                        help="只下載指定風格（中文），例如：工業風、美式風、鄉村風")
    parser.add_argument("--kind-filter", type=str, default=None,
                        help="只下載指定屋況（中文），例如：老屋翻新")
    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
        help="爬取前從 Supabase 更新 manifest",
    )
    args = parser.parse_args()

    scrape_images(
        target=args.target,
        max_pages=args.max_pages,
        manifest_path=Path(args.manifest),
        refresh_manifest=args.refresh_manifest,
        style_filter=args.style_filter,
        kind_filter=args.kind_filter,
    )


if __name__ == "__main__":
    main()
