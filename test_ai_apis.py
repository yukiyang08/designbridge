#!/usr/bin/env python3
"""Smoke test: `call_llm` (Gemini) + HF whoami.

  python test_ai_apis.py
  python test_ai_apis.py [--llm-only | --hf-only]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def _any_llm_key() -> bool:
    from designbridge.render.llm import _resolve_gemini_api_keys
    return bool(_resolve_gemini_api_keys())   # Vertex 模式回 [None]，也算有認證


def test_llm() -> bool:
    from designbridge.render.llm import call_llm

    out = call_llm(
        'Reply with one word: OK',
        temperature=0.1,
    ).strip()
    print(f"LLM: {out[:300] or '(empty)'}")
    return bool(out)


def test_hf() -> bool:
    tok = os.getenv("HF_TOKEN")
    if not tok:
        print("no HF_TOKEN")
        return False
    try:
        r = requests.get(
            "https://huggingface.co/api/whoami-v2",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=10,
        )
        if r.status_code != 200:
            print(f"HF: FAIL {r.status_code}")
            return False
        name = r.json().get("name") or r.json().get("fullname") or "?"
        print(f"HF: OK ({name})")
        return True
    except requests.RequestException as e:
        print(f"HF: FAIL ({e})")
        return False


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--llm-only", action="store_true")
    p.add_argument("--hf-only", action="store_true")
    args = p.parse_args()

    if args.llm_only and args.hf_only:
        sys.exit(2)

    if args.hf_only:
        sys.exit(0 if test_hf() else 1)

    if args.llm_only:
        if not _any_llm_key():
            print("LLM: 沒有認證（service-account.json 或 GEMINI_API_KEY）")
            sys.exit(1)
        try:
            ok = test_llm()
        except Exception as e:  # noqa: BLE001
            print(f"LLM: FAIL — {e}")
            ok = False
        sys.exit(0 if ok else 1)

    llm_ok = False
    if not _any_llm_key():
        print("LLM: no key")
    else:
        try:
            llm_ok = test_llm()
        except Exception as e:  # noqa: BLE001
            print(f"LLM: FAIL — {e}")

    hf_ok = test_hf()
    print(f"Summary: LLM={'OK' if llm_ok else 'FAIL'}  HF={'OK' if hf_ok else 'skip/FAIL'}")
    sys.exit(0 if llm_ok else 1)


if __name__ == "__main__":
    main()
