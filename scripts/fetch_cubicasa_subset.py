"""從 CubiCasa5K（Zenodo, 5.5 GB zip）只抓一小批樣本當房間辨識的評估集。

用 HTTP Range 讀遠端 zip：只下載目錄和選中的檔案，不用抓整包。
授權 CC BY-NC-SA 4.0，只限非商業用途；資料放 test/data/cubicasa/（git 已忽略）。

    python scripts/fetch_cubicasa_subset.py --n 50
    python scripts/fetch_cubicasa_subset.py --list      # 只看 zip 結構
"""

from __future__ import annotations

import argparse
import io
import random
import urllib.request
import zipfile
from pathlib import Path

URL = "https://zenodo.org/records/2613548/files/cubicasa5k.zip?download=1"
OUT = Path("test/data/cubicasa")
_CHUNK = 1 << 20


class RangeFile(io.RawIOBase):
    """唯讀、可 seek 的遠端檔案；每次多讀 _CHUNK 當快取，zipfile 的小讀取才不會一次一個請求。"""

    def __init__(self, url: str):
        self.url = url
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req) as r:
            self.size = int(r.headers["Content-Length"])
        self.pos = 0
        self._buf_start, self._buf = 0, b""

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self.pos, io.SEEK_END: self.size}[whence]
        self.pos = max(0, base + offset)
        return self.pos

    def _fetch(self, start: int, end: int) -> bytes:
        import http.client
        import time

        req = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end - 1}"})
        for attempt in range(4):   # Zenodo 偶爾中途斷線（IncompleteRead），重試就好
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    if r.status != 206:
                        raise IOError(f"伺服器沒有照 Range 回應（HTTP {r.status}）")
                    return r.read()
            except (http.client.IncompleteRead, ConnectionError, TimeoutError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        end = min(self.pos + n, self.size)
        if self.pos >= end:
            return b""
        b0, b1 = self._buf_start, self._buf_start + len(self._buf)
        if not (b0 <= self.pos and end <= b1):
            self._buf_start = self.pos
            self._buf = self._fetch(self.pos, min(self.size, max(end, self.pos + _CHUNK)))
        off = self.pos - self._buf_start
        out = self._buf[off: off + (end - self.pos)]
        self.pos += len(out)
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    zf = zipfile.ZipFile(RangeFile(URL))
    names = zf.namelist()
    if args.list:
        print(len(names), "entries")
        for n in names[:40]:
            print(" ", n)
        return

    # 每個樣本是一個資料夾：F1_scaled.png（圖）+ model.svg（標註）。
    # 只抽官方 test split；有 F2 的是多層樓，標註混在同一份 svg，跳過
    have = set(names)
    test = zf.read("cubicasa5k/test.txt").decode().split()
    dirs = [f"cubicasa5k{t.rstrip('/')}" for t in test]
    dirs = [d for d in dirs if f"{d}/F1_scaled.png" in have and f"{d}/F2_scaled.png" not in have]
    picked = random.Random(args.seed).sample(dirs, min(args.n, len(dirs)))
    OUT.mkdir(parents=True, exist_ok=True)
    for i, d in enumerate(sorted(picked), 1):
        sample_id = d.strip("/").replace("cubicasa5k/", "").replace("/", "_")
        dest = OUT / sample_id
        if (dest / "model.svg").is_file():
            continue
        dest.mkdir(exist_ok=True)
        for fname in ("F1_scaled.png", "model.svg"):
            (dest / fname).write_bytes(zf.read(f"{d}/{fname}"))
        print(f"[{i}/{len(picked)}] {sample_id}")
    print(f"done → {OUT}")


if __name__ == "__main__":
    main()
