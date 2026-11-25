"""Groq API: chat completions (LLM), Whisper transcription, key testing."""
from __future__ import annotations

import requests

BASE = "https://api.groq.com/openai/v1"
TIMEOUT = 60

LLM_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen/qwen3-32b",
]

STT_MODELS = [
    "whisper-large-v3-turbo",
    "whisper-large-v3",
]


class ProviderError(Exception):
    pass


def test_key(key: str) -> tuple[bool, str]:
    """GET /models — cheap validation of a Groq key."""
    if not key:
        return False, "Key is empty"
    try:
        r = requests.get(f"{BASE}/models", headers=_headers(key), timeout=15)
        if r.status_code == 200:
            return True, "Valid — reachable"
        if r.status_code == 401:
            return False, "Invalid key (401)"
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


# ------------------------------------------------------------------ STT
def transcribe(key: str, wav_bytes: bytes, model: str = "whisper-large-v3-turbo",
               language: str | None = None) -> str:
    """Groq Whisper STT via /audio/transcriptions (multipart upload)."""
    if not key:
        raise ProviderError("No Groq API key configured for STT")
    files = {"file": ("recording.wav", wav_bytes, "audio/wav")}
    data = {"model": model, "response_format": "json", "temperature": "0"}
    if language and language not in ("auto", "multi"):
        data["language"] = language.split("-")[0]
    try:
        r = requests.post(f"{BASE}/audio/transcriptions",
                          headers={"Authorization": f"Bearer {key}"},
                          files=files, data=data, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderError(f"Groq STT network error: {exc}") from exc
    if r.status_code != 200:
        raise ProviderError(f"Groq STT HTTP {r.status_code}: {r.text[:200]}")
    try:
        return (r.json().get("text") or "").strip()
    except ValueError as exc:
        raise ProviderError("Groq STT returned invalid JSON") from exc


# ------------------------------------------------------------------ LLM
def chat(key: str, messages: list[dict], model: str = "llama-3.3-70b-versatile",
         temperature: float = 1.0, max_tokens: int = 2036,
         tools: list[dict] | None = None,
         reasoning_effort: str | None = None) -> dict:
    """One chat-completions turn. Returns the assistant message dict."""
    if not key:
        raise ProviderError("No Groq API key configured for the LLM")
    payload: dict = {
        "model": model,
        "messages": messages,
        "temperature": max(0.0, min(2.0, float(temperature))),
        "max_completion_tokens": int(max_tokens),
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if reasoning_effort and reasoning_effort in ("low", "medium", "high"):
        payload["reasoning_effort"] = reasoning_effort
    try:
        r = requests.post(f"{BASE}/chat/completions", headers=_headers(key),
                          json=payload, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderError(f"Groq LLM network error: {exc}") from exc
    if r.status_code == 429:
        raise ProviderError("Groq rate limit reached (429) — try another key or model")
    if r.status_code != 200:
        raise ProviderError(f"Groq LLM HTTP {r.status_code}: {r.text[:200]}")
    try:
        body = r.json()
        return body["choices"][0]["message"]
    except (ValueError, KeyError, IndexError) as exc:
        raise ProviderError("Groq LLM returned an unexpected response") from exc
