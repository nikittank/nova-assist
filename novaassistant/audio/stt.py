"""Speech-to-text engines.

Two interchangeable engines, selected in Settings (or config.json):

  * GroqWhisperSTT   - Groq ``whisper-large-v3-turbo`` (fast file transcription)
  * DeepgramNovaSTT  - Deepgram ``nova-3`` streaming-grade model via REST

Both consume a complete 16 kHz mono WAV utterance and return text.

Keys are resolved per feature by the config layer:
  * Groq STT  -> config.stt_groq_key()   (dedicated key, else active LLM key)
  * Deepgram  -> config.stt_deepgram_key()  (dedicated key, else general key)
"""

from __future__ import annotations

import threading

import httpx

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"

DEFAULT_GROQ_STT_MODEL = "whisper-large-v3-turbo"
DEFAULT_DEEPGRAM_STT_MODEL = "nova-3"


class STTError(Exception):
    pass


class BaseSTT:
    name = "base"

    def transcribe(self, wav_bytes: bytes) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - interface
        pass


class GroqWhisperSTT(BaseSTT):
    """Groq API - whisper-large-v3-turbo (or whisper-large-v3)."""

    def __init__(self, api_key: str, language: str = "en",
                 model: str = DEFAULT_GROQ_STT_MODEL) -> None:
        if not api_key:
            raise STTError("Groq API key is not configured (Settings > AI Models & Providers).")
        self.name = f"Groq {model}"
        self.language = language
        self.model = model or DEFAULT_GROQ_STT_MODEL
        self._api_key = api_key
        self._lock = threading.Lock()
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from groq import Groq  # lazy import
            self._client = Groq(api_key=self._api_key)
        return self._client

    def transcribe(self, wav_bytes: bytes) -> str:
        try:
            with self._lock:
                client = self._ensure_client()
                result = client.audio.transcriptions.create(
                    model=self.model,
                    file=("speech.wav", wav_bytes, "audio/wav"),
                    language=self.language,
                    temperature=0.0,
                )
            return (getattr(result, "text", "") or "").strip()
        except Exception as exc:
            raise STTError(f"Groq STT failed: {exc}") from exc


class DeepgramNovaSTT(BaseSTT):
    """Deepgram API - nova-3 (or nova-2), pre-recorded utterance."""

    def __init__(self, api_key: str, language: str = "en",
                 model: str = DEFAULT_DEEPGRAM_STT_MODEL) -> None:
        if not api_key:
            raise STTError("Deepgram API key is not configured (Settings > AI Models & Providers).")
        self.name = f"Deepgram {model}"
        self.language = language
        self.model = model or DEFAULT_DEEPGRAM_STT_MODEL
        self._api_key = api_key
        self._http = httpx.Client(timeout=45.0)

    def transcribe(self, wav_bytes: bytes) -> str:
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/wav",
        }
        params = {
            "model": self.model,
            "smart_format": "true",
            "punctuate": "true",
            "language": self.language,
        }
        try:
            resp = self._http.post(
                DEEPGRAM_LISTEN_URL, params=params, headers=headers, content=wav_bytes
            )
            resp.raise_for_status()
            data = resp.json()
            alt = data["results"]["channels"][0]["alternatives"][0]
            return (alt.get("transcript") or "").strip()
        except Exception as exc:
            raise STTError(f"Deepgram {self.model} STT failed: {exc}") from exc

    def close(self) -> None:
        try:
            self._http.close()
        except Exception:
            pass


def create_stt(config) -> BaseSTT:
    """Factory driven by config['stt_engine'] with per-provider keys."""
    engine = config.get("stt_engine", "groq_whisper")
    language = config.get("stt_language", "en")
    if engine == "deepgram_nova3":
        return DeepgramNovaSTT(config.stt_deepgram_key(), language,
                               config.get("stt_deepgram_model",
                                          DEFAULT_DEEPGRAM_STT_MODEL))
    return GroqWhisperSTT(config.stt_groq_key(), language,
                          config.get("stt_groq_model", DEFAULT_GROQ_STT_MODEL))


def test_groq_key(api_key: str) -> str:
    """Validate a Groq key by listing models. Returns a human message."""
    if not api_key:
        return "No key provided."
    try:
        import httpx as _hx
        resp = _hx.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=20)
        if resp.status_code == 200:
            ids = [m.get("id", "") for m in resp.json().get("data", [])]
            return f"OK - {len(ids)} models available"
        if resp.status_code == 401:
            return "Invalid key (401 unauthorized)"
        return f"HTTP {resp.status_code}"
    except Exception as exc:
        return f"Failed: {exc}"


def test_deepgram_key(api_key: str) -> str:
    """Validate a Deepgram key against the projects endpoint."""
    if not api_key:
        return "No key provided."
    try:
        import httpx as _hx
        resp = _hx.get(
            "https://api.deepgram.com/v1/projects",
            headers={"Authorization": f"Token {api_key}"}, timeout=20)
        if resp.status_code == 200:
            projects = resp.json().get("projects", [])
            return f"OK - {len(projects)} project(s)"
        if resp.status_code == 401 or resp.status_code == 403:
            return "Invalid key (unauthorized)"
        return f"HTTP {resp.status_code}"
    except Exception as exc:
        return f"Failed: {exc}"
