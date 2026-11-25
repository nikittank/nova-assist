"""Deepgram API: Nova-3 STT, Aura TTS, key testing."""
from __future__ import annotations

import requests

BASE = "https://api.deepgram.com/v1"
TIMEOUT = 60

STT_MODELS = ["nova-3", "nova-2", "nova-2-medical", "nova-2-meeting"]

TTS_VOICES = [
    "aura-2-thalia-en",
    "aura-2-andromeda-en",
    "aura-2-helena-en",
    "aura-2-apollo-en",
    "aura-2-arcas-en",
    "aura-asteria-en",
    "aura-luna-en",
    "aura-orion-en",
    "aura-arcas-en",
    "aura-perseus-en",
    "aura-angus-en",
    "aura-puck-en",
    "aura-helios-en",
    "aura-zeus-en",
]

VOICE_LABELS = {
    "aura-2-thalia-en": "Aura-2 Thalia (Warm, Natural Female)",
    "aura-2-andromeda-en": "Aura-2 Andromeda (Expressive Female)",
    "aura-2-helena-en": "Aura-2 Helena (Precise, Articulate Female)",
    "aura-2-apollo-en": "Aura-2 Apollo (Confident Male)",
    "aura-2-arcas-en": "Aura-2 Arcas (Calm Professional Male)",
    "aura-asteria-en": "Aura Asteria (Warm, Natural Female)",
    "aura-luna-en": "Aura Luna (Expressive Female)",
    "aura-orion-en": "Aura Orion (Clear, Friendly Male)",
    "aura-arcas-en": "Aura Arcas (Calm, Professional Male)",
    "aura-perseus-en": "Aura Perseus (Informal, Friendly Male)",
    "aura-angus-en": "Aura Angus (Deep, Assured Male)",
    "aura-puck-en": "Aura Puck (Energetic Male)",
    "aura-helios-en": "Aura Helios (Bright Male)",
    "aura-zeus-en": "Aura Zeus (Authoritative Male)",
}


class ProviderError(Exception):
    pass


def _headers(key: str) -> dict:
    return {"Authorization": f"Token {key}"}


def test_key(key: str) -> tuple[bool, str]:
    if not key:
        return False, "Key is empty"
    try:
        r = requests.get(f"{BASE}/projects", headers=_headers(key), timeout=15)
        if r.status_code == 200:
            return True, "Valid — reachable"
        if r.status_code == 401:
            return False, "Invalid key (401)"
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except requests.RequestException as exc:
        return False, f"Network error: {exc}"


# ------------------------------------------------------------------- STT
def transcribe(key: str, wav_bytes: bytes, model: str = "nova-3",
               language: str = "multi") -> str:
    """Deepgram Nova STT via /v1/listen (pre-recorded)."""
    if not key:
        raise ProviderError("No Deepgram API key configured for STT")
    params = {"model": model, "smart_format": "true", "punctuate": "true"}
    if language and language != "auto":
        params["language"] = language   # nova-3 supports "multi"
    try:
        r = requests.post(f"{BASE}/listen", params=params,
                          headers={**_headers(key),
                                   "Content-Type": "audio/wav"},
                          data=wav_bytes, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderError(f"Deepgram STT network error: {exc}") from exc
    if r.status_code != 200:
        raise ProviderError(f"Deepgram STT HTTP {r.status_code}: {r.text[:200]}")
    try:
        results = r.json()["results"]["channels"][0]["alternatives"][0]
        return (results.get("transcript") or "").strip()
    except (ValueError, KeyError, IndexError) as exc:
        raise ProviderError("Deepgram STT returned an unexpected response") from exc


# ------------------------------------------------------------------- TTS
def speak(key: str, text: str, voice: str = "aura-2-thalia-en",
          sample_rate: int = 24000) -> bytes:
    """Deepgram Aura TTS -> wav bytes (linear16 in a wav container)."""
    if not key:
        raise ProviderError("No Deepgram API key configured for TTS")
    text = (text or "").strip()
    if not text:
        raise ProviderError("Nothing to speak")
    if len(text) > 1900:
        text = text[:1900] + "…"
    params = {
        "model": voice,
        "encoding": "linear16",
        "sample_rate": str(sample_rate),
        "container": "wav",
    }
    try:
        r = requests.post(f"{BASE}/speak", params=params,
                          headers={**_headers(key),
                                   "Content-Type": "application/json"},
                          json={"text": text}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise ProviderError(f"Deepgram TTS network error: {exc}") from exc
    if r.status_code != 200:
        raise ProviderError(f"Deepgram TTS HTTP {r.status_code}: {r.text[:200]}")
    ctype = r.headers.get("Content-Type", "")
    if "audio" not in ctype and "octet-stream" not in ctype:
        raise ProviderError(f"Deepgram TTS returned non-audio response: {ctype}")
    return r.content
