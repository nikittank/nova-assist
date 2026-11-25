"""TTS / audio playback.

FIX for: `Audio playback failed: module 'sounddevice' has no attribute
'is_playing'` — sounddevice has NEVER exposed `is_playing`. Playback state is
tracked by this class itself (generation counter + own flag + stream.active),
so stop/restart is reliable and no nonexistent attribute is ever touched.
"""
from __future__ import annotations

import io
import threading
import wave

import numpy as np
from PySide6.QtCore import QObject, Signal


class AudioPlayer(QObject):
    playback_started = Signal(int)          # generation
    playback_finished = Signal(int)         # generation (natural finish)
    playback_stopped = Signal(int)          # generation (stopped by user)
    playback_error = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._sd = None
        self._stream = None
        self._lock = threading.RLock()
        self._buffer = np.zeros(0, dtype=np.int16)
        self._cursor = 0
        self._generation = 0
        self._playing = False
        self._failed = False
        self._volume = 90          # 0-100, applied to decoded PCM

    def set_volume(self, percent: int) -> None:
        """Playback volume 0-100 (applied to subsequent play() calls)."""
        self._volume = max(0, min(100, int(percent)))

    # ------------------------------------------------------------ state
    def is_playing(self) -> bool:
        """Own state flag — NEVER sounddevice.is_playing (does not exist)."""
        with self._lock:
            if self._stream is not None and not self._playing:
                # defensive: stream died underneath us
                try:
                    if not self._stream.active:
                        return False
                except Exception:
                    return False
            return self._playing

    def generation(self) -> int:
        with self._lock:
            return self._generation

    # ------------------------------------------------------------- sd
    def _ensure_sd(self):
        if self._sd is None:
            import sounddevice as sd  # lazy import, guarded
            self._sd = sd
        return self._sd

    # ----------------------------------------------------------- input
    def _decode(self, audio: bytes | np.ndarray, samplerate: int | None):
        """Accept wav bytes or raw int16 pcm -> (np.int16 array, rate)."""
        if isinstance(audio, np.ndarray):
            data = audio.astype(np.int16)
            return data, int(samplerate or 24000)
        buf = io.BytesIO(audio)
        try:
            with wave.open(buf, "rb") as w:
                rate = w.getframerate()
                channels = w.getnchannels()
                raw = w.readframes(w.getnframes())
            data = np.frombuffer(raw, dtype=np.int16)
            if channels > 1:
                data = data.reshape(-1, channels)
            return data, rate
        except wave.Error:
            # raw pcm fallback
            data = np.frombuffer(audio, dtype=np.int16)
            return data, int(samplerate or 24000)

    # ---------------------------------------------------------- stream
    def _callback(self, outdata, frames, time_info, status) -> None:
        with self._lock:
            remaining = len(self._buffer) - self._cursor
            if remaining <= 0:
                outdata[:] = 0
                # end of buffer: schedule finish outside the callback
                self._finished = True
                return
            take = min(frames, remaining)
            chunk = self._buffer[self._cursor:self._cursor + take]
            self._cursor += take
            if chunk.ndim == 1:
                chunk = chunk.reshape(-1, 1)
            outdata[:take] = chunk
            if take < frames:
                outdata[take:] = 0
            if self._cursor >= len(self._buffer):
                self._finished = True

    def play(self, audio: bytes | np.ndarray, samplerate: int | None = None) -> int:
        """Play wav bytes / pcm. Returns generation id. Interrupts current playback."""
        data, rate = self._decode(audio, samplerate)
        if data.size == 0:
            return self._generation
        vol = max(0, min(100, int(self._volume)))
        if vol < 100:
            gain = vol / 100.0
            data = np.clip(data.astype(np.float32) * gain,
                           -32768, 32767).astype(np.int16)
        with self._lock:
            self._generation += 1
            gen = self._generation
            self._stop_stream_locked()
            self._buffer = data
            self._cursor = 0
            self._finished = False
            self._failed = False
            try:
                sd = self._ensure_sd()
                channels = 2 if data.ndim > 1 else 1
                self._stream = sd.OutputStream(
                    samplerate=rate, channels=channels, dtype="int16",
                    blocksize=0, callback=self._callback)
                self._stream.start()
                self._playing = True
            except Exception as exc:
                self._playing = False
                self._stream = None
                self.playback_error.emit(f"Audio playback failed: {exc}")
                return gen
        self.playback_started.emit(gen)
        self._watch(gen)
        return gen

    def _watch(self, gen: int) -> None:
        """Poll playback completion on a helper thread (keeps UI free)."""
        import time

        def watcher():
            while True:
                time.sleep(0.04)
                with self._lock:
                    if gen != self._generation:
                        return                     # superseded by newer play()
                    finished = getattr(self, "_finished", False)
                    if self._stream is None:
                        return
                    if finished or not self._stream.active:
                        done_ok = finished
                        self._stop_stream_locked()
                        self._playing = False
                        break
            if done_ok:
                self.playback_finished.emit(gen)

        t = threading.Thread(target=watcher, name="nova-playback-watch", daemon=True)
        t.start()

    def stop(self) -> None:
        """Interrupt playback immediately (idempotent)."""
        with self._lock:
            if not self._playing and self._stream is None:
                return
            gen = self._generation
            self._stop_stream_locked()
            self._playing = False
            self._buffer = np.zeros(0, dtype=np.int16)
            self._cursor = 0
        self.playback_stopped.emit(gen)

    def _stop_stream_locked(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
