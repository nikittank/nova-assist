"""Voice activity detection state machine (pure python, unit-testable).

Energy-gated VAD with adaptive noise floor:
  idle -> speaking (level above threshold)
  speaking -> trailing (silence started)
  trailing -> speaking (speech resumed)
  trailing -> done (silence longer than `silence_ms`)
"""
from __future__ import annotations

import math
import time
from collections import deque

IDLE = "idle"
SPEAKING = "speaking"
TRAILING = "trailing"


class VAD:
    def __init__(self, sensitivity: int = 82, silence_ms: int = 800,
                 min_speech_ms: int = 250, max_utterance_ms: int = 20000):
        self.sensitivity = max(1, min(100, int(sensitivity)))
        self.silence_ms = max(150, int(silence_ms))
        self.min_speech_ms = max(80, int(min_speech_ms))
        self.max_utterance_ms = int(max_utterance_ms)
        self.reset()
        # noise floor tracking
        self._floor = 0.008

    # sensitivity 100 -> very low threshold (picks up whisper)
    # sensitivity 1   -> high threshold (loud speech only)
    @property
    def threshold(self) -> float:
        t = 0.0025 + (1.0 - self.sensitivity / 100.0) * 0.055
        return max(t, self._floor * 2.2)

    def reset(self) -> None:
        self.state = IDLE
        self._speech_start = 0.0
        self._last_voice = 0.0
        self._recent = deque(maxlen=60)

    def _update_floor(self, rms: float) -> None:
        self._recent.append(rms)
        if len(self._recent) >= 30:
            ordered = sorted(self._recent)
            self._floor = ordered[len(ordered) // 10]  # ~10th percentile

    def process(self, rms: float, t: float | None = None) -> str:
        """Feed one frame RMS (0..1). Returns new state ('done' when utterance ended)."""
        t = t if t is not None else time.monotonic()
        rms = max(0.0, min(1.0, rms))
        self._update_floor(rms)
        thr = self.threshold

        if self.state == IDLE:
            if rms > thr:
                self.state = SPEAKING
                self._speech_start = t
                self._last_voice = t
        elif self.state == SPEAKING:
            if rms > thr:
                self._last_voice = t
            else:
                if (t - self._speech_start) * 1000.0 >= self.min_speech_ms:
                    self.state = TRAILING
                else:
                    # blip — treat as noise, back to idle
                    self.state = IDLE
        elif self.state == TRAILING:
            if rms > thr:
                self.state = SPEAKING
                self._last_voice = t
            elif (t - self._last_voice) * 1000.0 >= self.silence_ms:
                self.state = IDLE
                return "done"

        if self.state in (SPEAKING, TRAILING):
            if (t - self._speech_start) * 1000.0 >= self.max_utterance_ms:
                self.state = IDLE
                return "done"
        return self.state

    @staticmethod
    def rms(frame: bytes) -> float:
        """RMS of int16 little-endian PCM frame."""
        import struct
        n = len(frame) // 2
        if n == 0:
            return 0.0
        data = struct.unpack(f"<{n}h", frame[:n * 2])
        acc = 0
        for sample in data:
            acc += sample * sample
        return math.sqrt(acc / n) / 32768.0
