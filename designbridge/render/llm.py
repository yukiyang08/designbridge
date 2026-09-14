"""Gemini LLM client for DesignBridge.

``call_llm`` / ``call_llm_stream`` call the Google Generative AI SDK directly.
Tries ``GEMINI_API_KEY`` first; if that key fails, it walks through the
comma-separated extra keys in ``GEMINI_API_KEYS`` in order until one works.
Raises ``RuntimeError`` if no key is set or every key fails.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

from designbridge.core.config import Config

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Shared helpers ───────────────────────────────────────────────────────────

def _find_service_account() -> Path | None:
    """Locate a GCP service-account JSON: GOOGLE_APPLICATION_CREDENTIALS if set,
    else ``service-account.json`` (or ``.gcp/*.json``) in the repo root."""
    explicit = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    for cand in (_REPO_ROOT / "service-account.json", *sorted(_REPO_ROOT.glob(".gcp/*.json"))):
        if cand.is_file():
            return cand
    return None


def _vertex_enabled() -> bool:
    """Vertex mode is on if explicitly flagged, or a service-account JSON is present."""
    return bool(Config.GOOGLE_GENAI_USE_VERTEXAI or _find_service_account())

def _resolve_gemini_api_keys() -> list[str | None]:
    """Ordered, deduplicated list of Gemini API keys to try.

    In Vertex AI mode (``GOOGLE_GENAI_USE_VERTEXAI``) there is no API key —
    returns ``[None]`` so callers make a single attempt with the Vertex client
    (auth via service-account JSON / ADC).

    Otherwise ``GEMINI_API_KEY`` is tried first, then each entry of
    ``GEMINI_API_KEYS`` (comma-separated) in order.
    """
    if _vertex_enabled():
        return [None]

    keys: list[str] = []
    primary = (Config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY") or "").strip()
    if primary:
        keys.append(primary)

    extra_raw = Config.GEMINI_API_KEYS or os.getenv("GEMINI_API_KEYS", "")
    for k in extra_raw.split(","):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)

    return keys


def _image_to_gemini_blob(image: str | bytes | Path | dict) -> dict:
    """Convert image to a Gemini inline blob dict {mime_type, data}."""
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif"}

    # Already a blob: the caller knows the real mime type (e.g. it came from a
    # response's Content-Type). Trust it — there is no filename left to guess from,
    # and raw bytes would otherwise be labelled image/jpeg whatever they are.
    if isinstance(image, dict) and "data" in image:
        return {"mime_type": image.get("mime_type") or "image/jpeg", "data": image["data"]}

    if isinstance(image, str) and image.startswith(("http://", "https://")):
        import httpx
        resp = httpx.get(image, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        suffix = Path(image.split("?")[0]).suffix.lower()
        mime = mime_map.get(suffix, "image/jpeg")
        return {"mime_type": mime, "data": resp.content}

    if isinstance(image, bytes):
        return {"mime_type": "image/jpeg", "data": image}

    path = Path(image)
    mime = mime_map.get(path.suffix.lower(), "image/jpeg")
    return {"mime_type": mime, "data": path.read_bytes()}


def _history_to_gemini(history: list[dict]) -> list[dict]:
    """Convert OpenAI-style history to Gemini chat history format."""
    result = []
    for msg in history:
        role = msg.get("role", "user")
        if role == "assistant":
            role = "model"
        elif role == "system":
            continue  # system handled via system_instruction
        content = msg.get("content", "")
        parts = [content] if isinstance(content, str) else [p.get("text", "") for p in content if p.get("type") == "text"]
        result.append({"role": role, "parts": parts})
    return result


def _build_gemini_parts(
    prompt: str,
    images: list[str | bytes | Path | dict] | None,
) -> list:
    """Build a list of google.genai Part objects from images + text."""
    from google.genai import types
    parts: list = []
    for img in (images or []):
        blob = _image_to_gemini_blob(img)
        parts.append(types.Part.from_bytes(data=blob["data"], mime_type=blob["mime_type"]))
    parts.append(prompt)
    return parts


def _thinking_config(types):
    """ThinkingConfig for the configured model, or None to leave it to the model.

    ``thinking_budget=0`` means "don't think at all". Only the Gemini 2.x models
    accept that: sending 0 to a 3.x model is rejected outright with
    ``400 INVALID_ARGUMENT``, which reads as a broken API key rather than an
    unsupported parameter. Since 3.x cannot disable thinking, the honest
    translation of "0" there is to send no thinking_config and let the model pick
    its own budget. A positive budget is a real request and is always passed on.
    """
    budget = Config.GEMINI_THINKING_BUDGET
    if budget == 0 and not Config.GEMINI_MODEL.startswith(("gemini-1.", "gemini-2.")):
        return None
    return types.ThinkingConfig(thinking_budget=budget)


_clients: dict[str | None, object] = {}  # api_key (None = Vertex) -> cached genai.Client


def _get_client(api_key: str | None):
    """Cached genai.Client per api_key — constructing one re-authenticates (Vertex: a
    fresh ADC token fetch), measured at ~1-1.5s extra per call versus reusing one."""
    if api_key in _clients:
        return _clients[api_key]

    from google import genai

    if api_key is None:  # Vertex AI mode
        sa = _find_service_account()
        project = Config.GOOGLE_CLOUD_PROJECT or os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if sa:
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
            if not project:  # project id lives inside the service-account json
                project = json.loads(sa.read_text(encoding="utf-8")).get("project_id", "")
        if not project:
            raise RuntimeError("Vertex 模式但找不到 project id（放 service-account.json 或設 GOOGLE_CLOUD_PROJECT）")
        client = genai.Client(vertexai=True, project=project, location=Config.GOOGLE_CLOUD_LOCATION)
    else:
        client = genai.Client(api_key=api_key)
    _clients[api_key] = client
    return client


def _gemini_client_and_config(
    api_key: str | None,
    system: str | None,
    temperature: float | None,
    max_tokens: int | None,
):
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai 未安裝。請先執行: pip install google-genai") from exc

    client = _get_client(api_key)
    cfg = types.GenerateContentConfig(
        temperature=temperature if temperature is not None else Config.GEMINI_TEMPERATURE,
        **({"max_output_tokens": max_tokens} if max_tokens is not None else {}),
        **({"system_instruction": system} if system else {}),
    )
    thinking = _thinking_config(types)
    if thinking is not None:
        cfg.thinking_config = thinking
    return client, cfg


def _no_key_error() -> RuntimeError:
    return RuntimeError(
        "未設定 Gemini 認證。擇一：\n"
        "  (a) .env 設 GEMINI_API_KEY（可選 GEMINI_API_KEYS 作為備援）\n"
        "  (b) 把 GCP service-account.json 放到專案根目錄（project id 從檔案自動讀取）"
    )


# ── Public API ───────────────────────────────────────────────────────────────

def call_llm(
    prompt: str,
    *,
    images: list[str | bytes | Path | dict] | None = None,
    system: str | None = None,
    history: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
   
    keys = _resolve_gemini_api_keys()
    if not keys:
        raise _no_key_error()

    parts = _build_gemini_parts(prompt, images)
    converted = _history_to_gemini(history) if history else None

    errors: list[str] = []
    for i, api_key in enumerate(keys):
        try:
            client, cfg = _gemini_client_and_config(api_key, system, temperature, max_tokens)
            if converted is not None:
                chat = client.chats.create(model=Config.GEMINI_MODEL, config=cfg, history=converted)
                response = chat.send_message(parts)
            else:
                response = client.models.generate_content(
                    model=Config.GEMINI_MODEL, contents=parts, config=cfg
                )
            return response.text or ""
        except Exception as e:  # noqa: BLE001
            errors.append(f"[key {i + 1}/{len(keys)}] {e}")

    raise RuntimeError("所有 Gemini API key 皆失敗：\n" + "\n".join(errors))


def call_llm_stream(
    prompt: str,
    *,
    images: list[str | bytes | Path | dict] | None = None,
    system: str | None = None,
    history: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Streaming variant — yields text chunks.

    Tries ``GEMINI_API_KEY``, then each key in ``GEMINI_API_KEYS`` in order.
    A key is only skipped in favor of the next if it fails before yielding
    any content; once a chunk has been streamed out, further errors just
    propagate (retrying would duplicate output already sent to the caller).
    """
    keys = _resolve_gemini_api_keys()
    if not keys:
        raise _no_key_error()

    parts = _build_gemini_parts(prompt, images)
    converted = _history_to_gemini(history) if history else None

    errors: list[str] = []
    for i, api_key in enumerate(keys):
        yielded_any = False
        try:
            client, cfg = _gemini_client_and_config(api_key, system, temperature, max_tokens)
            if converted is not None:
                chat = client.chats.create(model=Config.GEMINI_MODEL, config=cfg, history=converted)
                stream = chat.send_message_stream(parts)
            else:
                stream = client.models.generate_content_stream(
                    model=Config.GEMINI_MODEL, contents=parts, config=cfg
                )
            for chunk in stream:
                if chunk.text:
                    yielded_any = True
                    yield chunk.text
            return
        except Exception as e:  # noqa: BLE001
            if yielded_any:
                raise RuntimeError(f"Gemini 串流中途失敗（key {i + 1}/{len(keys)}）：{e}") from e
            errors.append(f"[key {i + 1}/{len(keys)}] {e}")

    raise RuntimeError("所有 Gemini API key 皆失敗：\n" + "\n".join(errors))
