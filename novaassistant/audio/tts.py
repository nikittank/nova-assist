"""Text-to-speech via Deepgram Aura (v1) voices.

The player is built for streaming conversations:

  * ``feed(text)``  - called with incremental LLM output; text is buffered and
    split into sentence-sized chunks.
  * ``finish()``    - flushes the remainder when the LLM turn is complete.
  * ``stop()``      - interrupts immediately (clears queues, stops playback).

Two threads keep latency low: a synthesizer thread POSTs each chunk to
Deepgram /v1/speak (Aura voice, 24 kHz linear16 WAV) while a playback thread
streams the produced audio back-to-back through a dedicated sounddevice
``OutputStream``.

Playback state is tracked explicitly (generation counters + a stop event);
the module never relies on ``sounddevice.is_playing`` (that attribute does
not exist) or any other implicit module-level state.  Audio is written in
25 ms blocks so Stop responds within ~50 ms and repeated play/stop cycles
never leave a thread behind.

Only Aura v1 voice names are used (aura-*-en) - NOT aura-2 / flux.
"""

from __future__ import annotations

import io
import queue
import re
import threading
from typing import Callable, Optional

import httpx

try:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf
except Exception:  # pragma: no cover
    sd = None
    sf = None
    np = None

DEEPGRAM_SPEAK_URL = "https://api.deepgram.com/v1/speak"
PLAYBACK_SR = 24000
BLOCK_SECONDS = 0.025          # write granularity -> stop latency

_MARKDOWN_STRIP = re.compile(r"[`*_#>]+")
_SENT_BOUNDARY = re.compile(r"(?<=[.!?…])\s+|\n+")


class TTSPlayer:
    def __init__(self, api_key: str = "", voice: str = "aura-asteria-en",
                 enabled: bool = True,
                 on_start: Optional[Callable[[], None]] = None,
                 on_end: Optional[Callable[[], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None) -> None:
        self._api_key = api_key
        self._voice = voice
        self._enabled = enabled
        self._on_start = on_start
        self._on_end = on_end
        self._on_error = on_error

        self._synth_q: "queue.Queue[Optional[str]]" = queue.Queue()
        self._play_q: "queue.Queue[Optional[tuple]]" = queue.Queue(maxsize=16)
        self._stop_evt = threading.Event()
        self._buffer = ""
        self._generation = 0           # bumped by stop(); stale audio is dropped
        self._speaking = False
        self._announce_done = False
        self._lock = threading.RLock()

        self._http = httpx.Client(timeout=60.0)
        self._synth_thread: Optional[threading.Thread] = None
        self._play_thread: Optional[threading.Thread] = None
        self._stream: Optional["sd.OutputStream"] = None
        self._stream_sr = 0

    # ------------------------------------------------------------------ api
    @property
    def speaking(self) -> bool:
        with self._lock:
            return self._speaking

    @property
    def available(self) -> bool:
        return sd is not None and sf is not None

    def configure(self, api_key: str, voice: str, enabled: bool) -> None:
        with self._lock:
            self._api_key = api_key
            self._voice = voice
            self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def feed(self, text: str) -> None:
        """Accept incremental LLM output."""
        if not text or not self._enabled or not self._api_key:
            return
        with self._lock:
            self._ensure_threads()
            # a fresh turn may follow an earlier stop() - reopen the valves
            self._stop_evt.clear()
            self._buffer += text
            # emit complete sentences while keeping a small tail in the buffer
            while True:
                m = _SENT_BOUNDARY.search(self._buffer, 1)
                if m is None or len(self._buffer) < 40:
                    break
                sentence = self._buffer[: m.end()].strip()
                self._buffer = self._buffer[m.end():]
                if sentence:
                    self._synth_q.put(sentence)
            # safety valve: very long run-on text without punctuation
            if len(self._buffer) > 320:
                sentence, self._buffer = self._buffer, ""
                self._synth_q.put(sentence.strip())

    def finish(self) -> None:
        """Flush the remaining buffer as the final chunk."""
        with self._lock:
            if not self._enabled or not self._api_key:
                return
            self._ensure_threads()
            self._stop_evt.clear()
            rest = self._buffer.strip()
            self._buffer = ""
            if rest:
                self._synth_q.put(rest)
            self._announce_done = True
            self._synth_q.put(None)  # end-of-turn marker for the synth thread

    def stop(self) -> None:
        """Interrupt immediately and reset for the next turn."""
        with self._lock:
            self._generation += 1
            self._buffer = ""
            self._announce_done = False
            was_speaking = self._speaking
            self._speaking = False
        self._stop_evt.set()
        self._drain(self._synth_q)
        self._drain(self._play_q)
        if was_speaking:
            self._safe_on_end()

    def shutdown(self) -> None:
        self.stop()
        try:
            self._close_stream()
        except Exception:
            pass
        try:
            self._http.close()
        except Exception:
            pass

    # ------------------------------------------------------------ internals
    @staticmethod
    def _drain(q: "queue.Queue") -> None:
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass

    def _ensure_threads(self) -> None:
        if self._synth_thread is None or not self._synth_thread.is_alive():
            self._synth_thread = threading.Thread(target=self._synth_loop,
                                                  name="nova-tts-synth", daemon=True)
            self._synth_thread.start()
        if self._play_thread is None or not self._play_thread.is_alive():
            self._play_thread = threading.Thread(target=self._play_loop,
                                                 name="nova-tts-play", daemon=True)
            self._play_thread.start()

    def _safe_on_start(self) -> None:
        if self._on_start:
            try:
                self._on_start()
            except Exception:
                pass

    def _safe_on_end(self) -> None:
        if self._on_end:
            try:
                self._on_end()
            except Exception:
                pass

    def _safe_error(self, msg: str) -> None:
        if self._on_error:
            try:
                self._on_error(msg)
            except Exception:
                pass

    # synthesizer thread ---------------------------------------------------
    def _synth_loop(self) -> None:
        while True:
            item = self._synth_q.get()
            if item is None:
                with self._lock:
                    done = self._announce_done
                    gen = self._generation
                if done and not self._stop_evt.is_set():
                    try:
                        self._play_q.put((gen, None), timeout=2.0)
                    except queue.Full:
                        pass
                continue
            if self._stop_evt.is_set():
                continue
            gen = self._generation      # tag audio with the turn generation
            audio = self._synthesize(item)
            if audio and not self._stop_evt.is_set():
                try:
                    self._play_q.put((gen, audio), timeout=5.0)
                except queue.Full:
                    pass

    def _synthesize(self, text: str) -> Optional[bytes]:
        clean = _MARKDOWN_STRIP.sub("", text)
        clean = re.sub(r"\s+", " ", clean).strip()
        if not clean:
            return None
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "audio/wav",
        }
        params = {
            "model": self._voice,          # Aura v1 voice, e.g. aura-asteria-en
            "encoding": "linear16",
            "sample_rate": str(PLAYBACK_SR),
            "container": "wav",
        }
        try:
            resp = self._http.post(
                DEEPGRAM_SPEAK_URL, params=params, headers=headers,
                json={"text": clean},
            )
            resp.raise_for_status()
            return resp.content
        except Exception as exc:
            self._safe_error(f"TTS failed: {exc}")
            return None

    # playback thread --------------------------------------------------------
    def _ensure_stream(self, samplerate: int) -> bool:
        """Open (or re-open) the output stream for the given sample rate."""
        if sd is None:
            return False
        if self._stream is not None and self._stream_sr == samplerate \
                and self._stream.active:
            return True
        self._close_stream()
        try:
            self._stream = sd.OutputStream(
                samplerate=samplerate, channels=1, dtype="float32")
            self._stream.start()
            self._stream_sr = samplerate
            return True
        except Exception as exc:
            self._stream = None
            self._stream_sr = 0
            self._safe_error(f"Could not open audio output: {exc}")
            return False

    def _close_stream(self) -> None:
        stream, self._stream, self._stream_sr = self._stream, None, 0
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def _play_loop(self) -> None:
        while True:
            item = self._play_q.get()
            if item is None:
                continue
            gen, audio = item
            if audio is None:                       # end-of-turn marker
                with self._lock:
                    stale = gen != self._generation or self._stop_evt.is_set()
                    speaking = self._speaking
                    self._speaking = False
                if not stale and speaking:
                    self._safe_on_end()
                continue
            if gen != self._generation:             # stale chunk from before stop()
                continue
            try:
                data, sr = sf.read(io.BytesIO(audio), dtype="float32")
            except Exception as exc:
                self._safe_error(f"Audio decode failed: {exc}")
                continue
            if data.ndim > 1:
                data = data.mean(axis=1)
            if sr is None or sr <= 0:
                sr = PLAYBACK_SR
            if not self._ensure_stream(int(sr)):
                continue

            with self._lock:
                already = self._speaking
                self._speaking = True
            if not already:
                self._safe_on_start()

            block = max(1, int(sr * BLOCK_SECONDS))
            interrupted = False
            turn_dead = False
            try:
                for i in range(0, len(data), block):
                    if self._stop_evt.is_set() or gen != self._generation:
                        interrupted = True       # stop() owns the on_end callback
                        break
                    self._stream.write(data[i:i + block])
            except Exception as exc:
                # device can disappear mid-write; reset the stream for next turn
                self._safe_error(f"Audio playback failed: {exc}")
                self._close_stream()
                interrupted = True
                turn_dead = True                 # turn died on its own
            finally:
                if turn_dead:
                    with self._lock:
                        dead = self._speaking
                        self._speaking = False
                    if dead:
                        self._safe_on_end()
