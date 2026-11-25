"""Microphone capture with integrated end-of-speech VAD.

Emits Qt signals: level(rms), state(str), utterance_ready(wav_bytes).
sounddevice import is lazy+guarded so the app still boots without PortAudio.
"""
from __future__ import annotations

import io
import struct
import threading
import wave

from PySide6.QtCore import QObject, Signal

SAMPLE_RATE = 16000
BLOCK_MS = 30
BLOCK = SAMPLE_RATE * BLOCK_MS // 1000  # 480 frames


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class MicCapture(QObject):
    level_changed = Signal(float)
    state_changed = Signal(str)          # idle | speaking | trailing | done
    utterance_ready = Signal(bytes)      # wav bytes
    capture_error = Signal(str)

    def __init__(self, sensitivity: int = 82, silence_ms: int = 800,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._sd = None
        self._stream = None
        self._lock = threading.Lock()
        self._buffer: list[bytes] = []
        self._recording = False        # actively capturing an utterance
        self._want_input = False       # user wants mic open
        self._vad = None
        self.set_params(sensitivity, silence_ms)
        self._level = 0.0

    # ------------------------------------------------------------ config
    def set_params(self, sensitivity: int, silence_ms: int) -> None:
        from .vad import VAD
        self._vad = VAD(sensitivity=sensitivity, silence_ms=silence_ms)

    @property
    def is_open(self) -> bool:
        return self._stream is not None

    @property
    def is_speaking(self) -> bool:
        return bool(self._vad and self._vad.state in ("speaking", "trailing"))

    @property
    def last_level(self) -> float:
        return self._level

    # -------------------------------------------------------------- io
    def _ensure_sd(self):
        if self._sd is None:
            import sounddevice as sd  # lazy
            self._sd = sd
        return self._sd

    def open(self) -> bool:
        """Open the input stream (starts monitoring; VAD decides utterances)."""
        with self._lock:
            if self._stream is not None:
                return True
            try:
                sd = self._ensure_sd()
                self._stream = sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                    blocksize=BLOCK, callback=self._on_frames)
                self._stream.start()
                return True
            except Exception as exc:   # no device / PortAudio missing
                self._stream = None
                self.capture_error.emit(f"Microphone unavailable: {exc}")
                return False

    def close(self) -> None:
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self._buffer.clear()
            if self._vad:
                self._vad.reset()

    def start_listening(self) -> bool:
        """Open mic and wait for a full utterance (VAD-delimited)."""
        self._want_input = False          # set only after the stream is live
        self._buffer.clear()
        if self._vad:
            self._vad.reset()
        ok = self.open()
        if ok:
            self._want_input = True
            self.state_changed.emit("idle")
        return ok

    def stop_listening(self, flush: bool = True) -> None:
        """Stop; if flush and speech in progress, emit what we captured."""
        self._want_input = False
        if flush and self._recording and self._buffer:
            self._emit_utterance()
        self._recording = False
        self._buffer.clear()
        if self._vad:
            self._vad.reset()
        self.state_changed.emit("idle")

    # -------------------------------------------------------- callbacks
    def _on_frames(self, indata, frames, time_info, status) -> None:
        try:
            if status:
                pass
            frame = bytes(indata[:, 0] if hasattr(indata, "shape") and indata.ndim > 1
                          else indata)
            rms = self._vad.rms(frame) if self._vad else 0.0
            self._level = rms
            self.level_changed.emit(rms)
            if not self._want_input:
                return
            from .vad import IDLE
            result = self._vad.process(rms)
            if result != IDLE or self._recording:
                if not self._recording:
                    self._recording = True
                    self._buffer.clear()
                    self.state_changed.emit("speaking")
                self._buffer.append(frame)
                if self._vad.state == "trailing":
                    self.state_changed.emit("trailing")
            if result == "done" and self._recording:
                self._recording = False
                self._emit_utterance()
        except Exception:
            # never raise inside the PortAudio thread
            pass

    def _emit_utterance(self) -> None:
        pcm = b"".join(self._buffer)
        self._buffer.clear()
        if len(pcm) < SAMPLE_RATE * 2 * 0.25:   # < 250ms of audio: ignore
            self.state_changed.emit("idle")
            return
        wav = pcm_to_wav(pcm, SAMPLE_RATE)
        self.state_changed.emit("idle")
        self.utterance_ready.emit(wav)
