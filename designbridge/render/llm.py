"""Gemini LLM client for DesignBridge.

``call_llm`` / ``call_llm_stream`` call the Google Generative AI SDK directly.
Tries ``GEMINI_API_KEY`` first; if that key fails, it walks through the
comma-separated extra keys in ``GEMINI_API_KEYS`` in order until one works.
Raises ``RuntimeError`` if no key is set or every key fails.
"""

from __future__ import annotations

import json
import os
import re
import time
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
    """Vertex mode is on if explicitly flagged, or a service-account JSON is present —
    unless GOOGLE_GENAI_FORCE_API_KEY overrides that back to plain API-key mode (Vertex's
    publisher model catalog lags the direct API by months for brand-new model names)."""
    if Config.GOOGLE_GENAI_FORCE_API_KEY:
        return False
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


def _image_to_blob(image: str | bytes | Path | dict) -> dict:
    """Resolve any supported image input to {mime_type, data}. Provider-agnostic —
    both the Gemini (inline blob) and Qwen (base64 data URL) paths build on this."""
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
        blob = _image_to_blob(img)
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
        # 3.x flash 用 thinking_level=minimal 才等於不思考；不設的話思考 token 會吃掉
        # max_output_tokens，輸出被截斷（composer 只剩「(#DDC8B4), yellow (#F」）
        if "flash" in Config.GEMINI_MODEL:
            return types.ThinkingConfig(thinking_level="minimal")
        return None
    return types.ThinkingConfig(thinking_budget=budget)


def _thinking_headroom() -> int:
    """思考 token 也算在 max_output_tokens 裡：模型會思考時，呼叫端的 max_tokens 要另外加的餘裕。"""
    budget = Config.GEMINI_THINKING_BUDGET
    if budget > 0:
        return budget
    if budget < 0:
        # -1 動態思考：實測一張平面圖想了 3.8k～7.4k token，留少了 JSON 會被截斷
        return 16384
    # 0：3.x 非 flash 關不掉思考，模型自己決定
    if not Config.GEMINI_MODEL.startswith(("gemini-1.", "gemini-2.")) and "flash" not in Config.GEMINI_MODEL:
        return 4096
    return 0


_clients: dict[str | None, object] = {}  # api_key (None = Vertex) -> cached genai.Client


def _get_client(api_key: str | None):
    """Cached genai.Client per api_key — constructing one re-authenticates (Vertex: a
    fresh ADC token fetch), measured at ~1-1.5s extra per call versus reusing one."""
    if api_key in _clients:
        return _clients[api_key]

    from google import genai
    from google.genai import types

    # Vertex 配額滿了回 429；平面圖逐區辨識一次平行 3 個請求，不退避重試就會整批失敗
    http_options = types.HttpOptions(retry_options=types.HttpRetryOptions(
        attempts=5, initial_delay=2.0, max_delay=30.0, http_status_codes=[429, 500, 503, 504],
    ))
    if api_key is None:  # Vertex AI mode
        sa = _find_service_account()
        project = Config.GOOGLE_CLOUD_PROJECT or os.getenv("GOOGLE_CLOUD_PROJECT", "")
        if sa:
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
            if not project:  # project id lives inside the service-account json
                project = json.loads(sa.read_text(encoding="utf-8")).get("project_id", "")
        if not project:
            raise RuntimeError("Vertex 模式但找不到 project id（放 service-account.json 或設 GOOGLE_CLOUD_PROJECT）")
        client = genai.Client(vertexai=True, project=project, location=Config.GOOGLE_CLOUD_LOCATION,
                              http_options=http_options)
    else:
        client = genai.Client(api_key=api_key, http_options=http_options)
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
    if max_tokens is not None:
        max_tokens += _thinking_headroom()
    cfg = types.GenerateContentConfig(
        temperature=temperature if temperature is not None else Config.GEMINI_TEMPERATURE,
        **({"max_output_tokens": max_tokens} if max_tokens is not None else {}),
        **({"system_instruction": system} if system else {}),
    )
    thinking = _thinking_config(types)
    if thinking is not None:
        cfg.thinking_config = thinking
    return client, cfg


def get_gemini_client():
    """離線腳本用：認證方式跟主流程一致（有 service-account.json 走 Vertex，否則 API key）。"""
    keys = _resolve_gemini_api_keys()
    if not keys:
        raise _no_key_error()
    return _get_client(keys[0])


def _no_key_error() -> RuntimeError:
    return RuntimeError(
        "未設定 Gemini 認證。擇一：\n"
        "  (a) .env 設 GEMINI_API_KEY（可選 GEMINI_API_KEYS 作為備援）\n"
        "  (b) 把 GCP service-account.json 放到專案根目錄（project id 從檔案自動讀取）"
    )


# ── Usage tracking (ablation experiment) ──────────────────────────────────────
# call_llm()'s return type is a plain str and every caller in the codebase already
# depends on that — so token usage can't ride back through the return value without
# breaking them. This module-level dict is the side channel instead: cleared+refilled
# on every call, read by the ablation harness right after each call_llm() invocation.
last_usage: dict[str, int | str | None] = {}


# ── Qwen (DashScope) backend — OpenAI-compatible, used for the Gemini-vs-Qwen
# ablation study. DashScope's compatible-mode endpoint accepts the standard OpenAI
# chat/completions shape, and this project's internal chat history is already
# OpenAI-shaped (see _history_to_gemini's docstring) — so unlike the Gemini path,
# no format translation is needed for history, only for images (data: URLs instead
# of inline Part objects).
_qwen_client: object | None = None


def _image_to_data_url(image: str | bytes | Path | dict) -> str:
    """Resolve any supported image input to a base64 data: URL for OpenAI-style
    {"type": "image_url", "image_url": {"url": ...}} content blocks."""
    import base64

    blob = _image_to_blob(image)
    b64 = base64.b64encode(blob["data"]).decode("ascii")
    return f"data:{blob['mime_type']};base64,{b64}"


def _build_openai_messages(
    prompt: str,
    images: list[str | bytes | Path | dict] | None,
    system: str | None,
    history: list[dict] | None,
) -> list[dict]:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    if history:
        messages.extend(history)

    content: list[dict] = [
        {"type": "image_url", "image_url": {"url": _image_to_data_url(img)}} for img in (images or [])
    ]
    content.append({"type": "text", "text": prompt})
    messages.append({"role": "user", "content": content})
    return messages


def _get_qwen_client():
    global _qwen_client
    if _qwen_client is None:
        if not Config.DASHSCOPE_API_KEY:
            raise RuntimeError("未設定 DASHSCOPE_API_KEY（.env 加一行 DASHSCOPE_API_KEY=sk-xxx）")
        from openai import OpenAI

        _qwen_client = OpenAI(api_key=Config.DASHSCOPE_API_KEY, base_url=Config.DASHSCOPE_BASE_URL)
    return _qwen_client


def _record_openai_usage(provider: str, model: str, response) -> None:
    """Shared by Qwen and Llama — both are OpenAI-compatible and expose the same
    response.usage shape."""
    usage = getattr(response, "usage", None)
    last_usage.clear()
    last_usage.update({
        "provider": provider,
        "model": model,
        "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
        "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
        "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
    })


def _call_qwen(
    prompt: str,
    *,
    images: list[str | bytes | Path | dict] | None,
    system: str | None,
    history: list[dict] | None,
    temperature: float | None,
    max_tokens: int | None,
    json_mode: bool = False,
    # DashScope's json_object mode makes Qwen pad the response with a dozen unrequested
    # fields (reasoning/context/recommendation/…) instead of the schema the prompt asked
    # for, which blows through a tight max_tokens budget and truncates mid-string — seen
    # on adjuster's short intent/bbox calls (300-500 tokens). Qwen's own JSON compliance
    # without this flag is normally fine, but on floor-plan images it was observed to
    # emit real one-character syntax slips (missing quote, mismatched bracket, see
    # ablation 4.3b) that json_mode's grammar-constrained decoding would prevent. So:
    # only turn it on when there's enough max_tokens headroom (>=1500) to absorb the
    # padding without truncating — this is what floor_plan/room_detect now have.
) -> str:
    client = _get_qwen_client()
    messages = _build_openai_messages(prompt, images, system, history)
    strict_json = json_mode and max_tokens is not None and max_tokens >= 1500
    response = client.chat.completions.create(
        model=Config.QWEN_MODEL,
        messages=messages,
        temperature=temperature if temperature is not None else Config.GEMINI_TEMPERATURE,
        # ponytail: flat penalty, not a loop detector — cuts the repetition-degeneration
        # runs seen on floor-plan parsing (same object repeated with tiny coordinate
        # drift until the token limit) without being aggressive enough to visibly hurt
        # legitimately repeated JSON keys. Raise if repeats still get through.
        frequency_penalty=0.3,
        **({"response_format": {"type": "json_object"}} if strict_json else {}),
        **({"max_tokens": max_tokens} if max_tokens is not None else {}),
    )
    _record_openai_usage("qwen", Config.QWEN_MODEL, response)
    return response.choices[0].message.content or ""


def _call_qwen_stream(
    prompt: str,
    *,
    images: list[str | bytes | Path | dict] | None,
    system: str | None,
    history: list[dict] | None,
    temperature: float | None,
    max_tokens: int | None,
    json_mode: bool = False,  # noqa: ARG001 — see _call_qwen's docstring-comment; not used here either.
) -> Iterator[str]:
    client = _get_qwen_client()
    messages = _build_openai_messages(prompt, images, system, history)
    stream = client.chat.completions.create(
        model=Config.QWEN_MODEL,
        messages=messages,
        temperature=temperature if temperature is not None else Config.GEMINI_TEMPERATURE,
        frequency_penalty=0.3,
        stream=True,
        stream_options={"include_usage": True},
        **({"max_tokens": max_tokens} if max_tokens is not None else {}),
    )
    for chunk in stream:
        if chunk.usage:
            _record_openai_usage("qwen", Config.QWEN_MODEL, chunk)
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


# ── Llama (Vertex AI MaaS) backend — same OpenAI-compatible shape as Qwen, but
# auth is a short-lived OAuth token off the project's service account (reuses
# _find_service_account from the Gemini-Vertex path) instead of a static API key,
# so the client is rebuilt per call rather than cached — a stale cached client would
# silently keep using an expired token past ~1h.
_llama_creds: object | None = None


def _get_llama_bearer_token() -> str:
    global _llama_creds
    import google.auth
    import google.auth.transport.requests

    if _llama_creds is None:
        sa = _find_service_account()
        if sa:
            os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(sa))
        _llama_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _llama_creds.valid:
        _llama_creds.refresh(google.auth.transport.requests.Request())
    return _llama_creds.token


def _get_llama_client():
    if not Config.GOOGLE_CLOUD_PROJECT:
        raise RuntimeError("未設定 GOOGLE_CLOUD_PROJECT（Llama-on-Vertex 需要）")
    from openai import OpenAI

    token = _get_llama_bearer_token()
    base_url = (
        f"https://{Config.LLAMA_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{Config.GOOGLE_CLOUD_PROJECT}/locations/{Config.LLAMA_LOCATION}/endpoints/openapi"
    )
    return OpenAI(api_key=token, base_url=base_url)


# Llama-on-Vertex 500s internally if max_tokens is omitted (seen consistently on
# Scout, not on Maverick) — always pass something rather than relying on caller-supplied
# max_tokens, which most call_llm() call sites in this codebase never set.
_LLAMA_DEFAULT_MAX_TOKENS = 2048

# Scout (via this Vertex MaaS endpoint) leaks its own chat-template header token into
# the content, consistently right before array/object closers in structured output
# (e.g. `"bbox": [0.5,0.5,1.0,0.9</end_header_id|end_header_id]`) — breaks any JSON
# parsing downstream. Strip it before returning, so every caller sees clean text.
_LLAMA_LEAKED_TOKEN_RE = re.compile(r"</?end_header_id\|?end_header_id>?")


def _clean_llama_content(text: str) -> str:
    return _LLAMA_LEAKED_TOKEN_RE.sub("", text)


def _call_llama(
    prompt: str,
    *,
    images: list[str | bytes | Path | dict] | None,
    system: str | None,
    history: list[dict] | None,
    temperature: float | None,
    max_tokens: int | None,
    json_mode: bool = False,
) -> str:
    client = _get_llama_client()
    messages = _build_openai_messages(prompt, images, system, history)
    response = client.chat.completions.create(
        model=Config.LLAMA_MODEL,
        messages=messages,
        temperature=temperature if temperature is not None else Config.GEMINI_TEMPERATURE,
        max_tokens=max_tokens if max_tokens is not None else _LLAMA_DEFAULT_MAX_TOKENS,
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
    )
    _record_openai_usage("llama", Config.LLAMA_MODEL, response)
    return _clean_llama_content(response.choices[0].message.content or "")


def _call_llama_stream(
    prompt: str,
    *,
    images: list[str | bytes | Path | dict] | None,
    system: str | None,
    history: list[dict] | None,
    temperature: float | None,
    max_tokens: int | None,
    json_mode: bool = False,
) -> Iterator[str]:
    client = _get_llama_client()
    messages = _build_openai_messages(prompt, images, system, history)
    stream = client.chat.completions.create(
        model=Config.LLAMA_MODEL,
        messages=messages,
        temperature=temperature if temperature is not None else Config.GEMINI_TEMPERATURE,
        stream=True,
        stream_options={"include_usage": True},
        max_tokens=max_tokens if max_tokens is not None else _LLAMA_DEFAULT_MAX_TOKENS,
        **({"response_format": {"type": "json_object"}} if json_mode else {}),
    )
    for chunk in stream:
        if chunk.usage:
            _record_openai_usage("llama", Config.LLAMA_MODEL, chunk)
        if chunk.choices and chunk.choices[0].delta.content:
            # ponytail: per-chunk cleanup misses a leaked token split across two chunks;
            # fine for now since nothing in this codebase streams Llama yet — bump to a
            # small carry-over buffer if that changes.
            yield _clean_llama_content(chunk.choices[0].delta.content)


# ── Public API ───────────────────────────────────────────────────────────────

def _record_gemini_usage(usage, duration_s: float) -> None:
    """記到帳號用量；思考 token 跟輸出同價，併進 completion。"""
    from designbridge.core import usage as usage_log

    if usage is None:
        return
    out = (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
    usage_log.record_llm(Config.GEMINI_MODEL, getattr(usage, "prompt_token_count", 0), out, duration_s)


def call_llm(
    prompt: str,
    *,
    images: list[str | bytes | Path | dict] | None = None,
    system: str | None = None,
    history: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    json_mode: bool = False,
) -> str:
    """``json_mode=True`` asks the backend to constrain decoding to valid JSON
    (OpenAI-style ``response_format``). Only actually does anything for Llama, which
    otherwise leaks chat-template tokens into structured output and breaks the closing
    bracket. Gemini doesn't show that problem (left alone rather than wiring up its
    differently-shaped response_mime_type config for no benefit), and Qwen gets *worse*
    under it — it pads the response with unrequested fields and overruns tight
    max_tokens budgets — so both silently ignore the flag. Safe for every caller to pass
    when parsing JSON out of the response; it only changes behavior on Llama."""
    if Config.LLM_PROVIDER == "qwen":
        return _call_qwen(
            prompt, images=images, system=system, history=history,
            temperature=temperature, max_tokens=max_tokens, json_mode=json_mode,
        )
    if Config.LLM_PROVIDER == "llama":
        return _call_llama(
            prompt, images=images, system=system, history=history,
            temperature=temperature, max_tokens=max_tokens, json_mode=json_mode,
        )

    keys = _resolve_gemini_api_keys()
    if not keys:
        raise _no_key_error()

    parts = _build_gemini_parts(prompt, images)
    converted = _history_to_gemini(history) if history else None

    errors: list[str] = []
    for i, api_key in enumerate(keys):
        try:
            started = time.perf_counter()
            client, cfg = _gemini_client_and_config(api_key, system, temperature, max_tokens)
            if converted is not None:
                chat = client.chats.create(model=Config.GEMINI_MODEL, config=cfg, history=converted)
                response = chat.send_message(parts)
            else:
                response = client.models.generate_content(
                    model=Config.GEMINI_MODEL, contents=parts, config=cfg
                )
            usage = getattr(response, "usage_metadata", None)
            last_usage.clear()
            last_usage.update({
                "provider": "gemini",
                "model": Config.GEMINI_MODEL,
                "prompt_tokens": getattr(usage, "prompt_token_count", None) if usage else None,
                "completion_tokens": getattr(usage, "candidates_token_count", None) if usage else None,
                "total_tokens": getattr(usage, "total_token_count", None) if usage else None,
            })
            _record_gemini_usage(usage, time.perf_counter() - started)
            if not response.text:
                cand = (response.candidates or [None])[0]
                print(f"⚠️  Gemini 回了空內容（finish_reason={getattr(cand, 'finish_reason', None)}）")
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
    json_mode: bool = False,
) -> Iterator[str]:
    """Streaming variant — yields text chunks.

    Tries ``GEMINI_API_KEY``, then each key in ``GEMINI_API_KEYS`` in order.
    A key is only skipped in favor of the next if it fails before yielding
    any content; once a chunk has been streamed out, further errors just
    propagate (retrying would duplicate output already sent to the caller).
    """
    if Config.LLM_PROVIDER == "qwen":
        yield from _call_qwen_stream(
            prompt, images=images, system=system, history=history,
            temperature=temperature, max_tokens=max_tokens, json_mode=json_mode,
        )
        return
    if Config.LLM_PROVIDER == "llama":
        yield from _call_llama_stream(
            prompt, images=images, system=system, history=history,
            temperature=temperature, max_tokens=max_tokens, json_mode=json_mode,
        )
        return

    keys = _resolve_gemini_api_keys()
    if not keys:
        raise _no_key_error()

    parts = _build_gemini_parts(prompt, images)
    converted = _history_to_gemini(history) if history else None

    errors: list[str] = []
    for i, api_key in enumerate(keys):
        yielded_any = False
        try:
            started = time.perf_counter()
            client, cfg = _gemini_client_and_config(api_key, system, temperature, max_tokens)
            if converted is not None:
                chat = client.chats.create(model=Config.GEMINI_MODEL, config=cfg, history=converted)
                stream = chat.send_message_stream(parts)
            else:
                stream = client.models.generate_content_stream(
                    model=Config.GEMINI_MODEL, contents=parts, config=cfg
                )
            usage = None
            for chunk in stream:
                usage = getattr(chunk, "usage_metadata", None) or usage
                if chunk.text:
                    yielded_any = True
                    yield chunk.text
            _record_gemini_usage(usage, time.perf_counter() - started)
            return
        except Exception as e:  # noqa: BLE001
            if yielded_any:
                raise RuntimeError(f"Gemini 串流中途失敗（key {i + 1}/{len(keys)}）：{e}") from e
            errors.append(f"[key {i + 1}/{len(keys)}] {e}")

    raise RuntimeError("所有 Gemini API key 皆失敗：\n" + "\n".join(errors))
