"""Microphone capture with an energy-based voice-activity detector.

Design:
  * sounddevice.InputStream pushes 30 ms int16 frames into a queue from the
    PortAudio callback thread.
  * A worker thread runs a small state machine:
        idle -> speech (frame RMS above adaptive threshold)
             -> end after ~810 ms of silence (or 30 s hard cap)
    and emits each complete utterance as a 16 kHz mono WAV byte string.
  * A 510 ms pre-roll buffer keeps the start of an utterance from being
    clipped.
  * A live input level (0..1) is reported through ``on_level`` so the UI and
    the overlay can draw a real-time waveform.
  * While the assistant is speaking (or thinking) the caller can set
    ``suppressed`` so the echo of the speakers is never transcribed
    (half-duplex conversation).

Two listening modes are supported:
  * ``continuous`` - hands-free; utterances are detected automatically.
  * ``ptt``        - push-to-talk; record while ptt_start()/ptt_stop().

``start_oneshot()`` runs a single "listen once" capture (used by the
Reminders microphone button) without touching a main listening session.
"""

from __future__ import annotations

import io
import queue
import threading
import wave
from typing import Callable, Optional

import numpy as np

try:
    import sounddevice as sd
except Exception as _sd_err:  # pragma: no cover - handled at runtime
    sd = None
    _SD_IMPORT_ERROR = _sd_err
else:
    _SD_IMPORT_ERROR = None

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000          # 480
SILENCE_FRAMES_TO_END = 27                              # ~810 ms
MIN_SPEECH_FRAMES = 6                                   # ~180 ms
PREROLL_FRAMES = 17                                     # ~510 ms
MAX_UTTERANCE_FRAMES = SAMPLE_RATE * 30 // FRAME_SAMPLES  # 30 s cap
ONESHOT_MAX_SECONDS = 15                                # single capture cap


def encode_wav(pcm_bytes: bytes, samplerate: int = SAMPLE_RATE, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(samplerate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()


class MicRecorder:
    """Continuous microphone listener with VAD + push-to-talk support."""

    def __init__(self, on_utterance: Callable[[bytes], None],
                 on_error: Optional[Callable[[str], None]] = None,
                 on_level: Optional[Callable[[float], None]] = None) -> None:
        self._on_utterance = on_utterance
        self._on_error = on_error
        self._on_level = on_level
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=400)
        self._stream = None
        self._worker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

        self.listening = False            # session-level toggle (user intent)
        self.suppressed = False           # ignore mic while assistant talks
        self.mode = "continuous"          # continuous | ptt

        self._ptt_recording = False
        self._ptt_buffer: list[bytes] = []
        self._ptt_lock = threading.Lock()

        # one-shot capture state
        self._oneshot = False
        self._oneshot_cb: Optional[Callable[[bytes], None]] = None
        self._oneshot_watchdog: Optional[threading.Timer] = None

    # ------------------------------------------------------------------ api
    @property
    def available(self) -> bool:
        return _SD_IMPORT_ERROR is None

    def import_error(self) -> str:
        return str(_SD_IMPORT_ERROR) if _SD_IMPORT_ERROR else ""

    @property
    def ptt_active(self) -> bool:
        with self._ptt_lock:
            return self._ptt_recording

    def start(self, mode: str = "continuous") -> bool:
        """Open the microphone and start the VAD worker. Returns success."""
        if sd is None:
            self._report("sounddevice/PortAudio is not available: " + self.import_error())
            return False
        if self._stream is not None:
            self.mode = mode
            return True
        try:
            self.mode = mode
            self._stop_evt.clear()
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                blocksize=FRAME_SAMPLES,
                callback=self._callback,
            )
            self._stream.start()
            self._worker = threading.Thread(target=self._run, name="nova-vad", daemon=True)
            self._worker.start()
            self.listening = True
            return True
        except Exception as exc:  # device missing, busy, permission denied...
            self._stream = None
            self._report(f"Could not open microphone: {exc}")
            return False

    def stop(self) -> None:
        self.listening = False
        self._cancel_oneshot_watchdog()
        self._stop_evt.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        # drain the queue so the worker exits quickly
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            self._worker = None

    def set_mode(self, mode: str) -> None:
        self.mode = mode if mode in ("continuous", "ptt") else "continuous"

    def set_suppressed(self, value: bool) -> None:
        self.suppressed = bool(value)

    # one-shot capture ------------------------------------------------------
    def start_oneshot(self, on_result: Callable[[bytes], None],
                      max_seconds: float = ONESHOT_MAX_SECONDS) -> bool:
        """Listen once and deliver a single utterance WAV to ``on_result``.

        Returns False if a main listening session or a capture is running
        (the caller can then route the next utterance instead).
        """
        if self.listening or self._oneshot:
            return False
        self._oneshot = True
        self._oneshot_cb = on_result
        if not self.start(mode="continuous"):
            self._oneshot = False
            self._oneshot_cb = None
            return False
        self._oneshot_watchdog = threading.Timer(
            max_seconds, self._oneshot_timeout, daemon=True)
        self._oneshot_watchdog.start()
        return True

    def _oneshot_timeout(self) -> None:
        """Cap the capture: deliver whatever was captured (possibly silence)."""
        if not self._oneshot:
            return
        self._oneshot = False
        cb = self._oneshot_cb
        self._oneshot_cb = None
        self.stop()
        if cb:
            try:
                cb(b"")          # empty -> "nothing heard"
            except Exception:
                pass

    def _cancel_oneshot_watchdog(self) -> None:
        if self._oneshot_watchdog is not None:
            try:
                self._oneshot_watchdog.cancel()
            except Exception:
                pass
            self._oneshot_watchdog = None

    # push-to-talk -------------------------------------------------------
    def ptt_start(self) -> None:
        if not self.listening:
            return
        with self._ptt_lock:
            self._ptt_recording = True
            self._ptt_buffer = []

    def ptt_stop(self) -> None:
        with self._ptt_lock:
            if not self._ptt_recording:
                return
            self._ptt_recording = False
            pcm = b"".join(self._ptt_buffer)
            self._ptt_buffer = []
        if len(pcm) >= SAMPLE_RATE * 2 * 0.35:  # >= 0.35 s of audio
            self._deliver(encode_wav(pcm))

    # ------------------------------------------------------------ internals
    def _report(self, msg: str) -> None:
        if self._on_error:
            self._on_error(msg)

    def _deliver(self, wav: bytes) -> None:
        """Route a complete utterance (one-shot capture or normal flow)."""
        if self._oneshot:
            self._cancel_oneshot_watchdog()
            self._oneshot = False
            cb = self._oneshot_cb
            self._oneshot_cb = None
            was_listening = self.listening
            self.stop()
            if cb:
                try:
                    cb(wav if was_listening else b"")
                except Exception:
                    pass
            return
        if self._on_utterance:
            try:
                self._on_utterance(wav)
            except Exception:
                pass

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            pass  # overflows are non-fatal; drop frame
        try:
            self._queue.put_nowait(bytes(indata))  # copy out of PortAudio buffer
        except queue.Full:
            pass

    def _run(self) -> None:
        """VAD worker: consumes frames, emits complete utterances."""
        noise_floor = 400.0
        preroll: list[bytes] = []
        in_speech = False
        speech_frames = 0
        silence_run = 0
        total_frames = 0
        buffer: list[bytes] = []
        level_tick = 0

        while not self._stop_evt.is_set():
            try:
                frame = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue

            samples = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(np.square(samples))) + 1e-9)

            # live input level for the waveform (throttled to ~20 Hz)
            level_tick += 1
            if self._on_level is not None and level_tick % 2 == 0 and not self.suppressed:
                level = min(1.0, rms / 2500.0)
                try:
                    self._on_level(level)
                except Exception:
                    pass

            # push-to-talk bypasses VAD entirely
            with self._ptt_lock:
                ptt_active = self._ptt_recording
                if ptt_active:
                    self._ptt_buffer.append(frame)

            if ptt_active or self.suppressed:
                if in_speech:      # abort a live VAD utterance on suppression
                    in_speech, speech_frames, silence_run, total_frames = False, 0, 0, 0
                    buffer, preroll = [], []
                noise_floor = 0.97 * noise_floor + 0.03 * min(rms, 3000.0)
                continue

            threshold = max(noise_floor * 3.2, 300.0)

            if not in_speech:
                preroll.append(frame)
                if len(preroll) > PREROLL_FRAMES:
                    preroll.pop(0)
                noise_floor = 0.97 * noise_floor + 0.03 * min(rms, 3000.0)
                if rms > threshold:
                    in_speech = True
                    speech_frames, silence_run, total_frames = 1, 0, 1
                    buffer = list(preroll)
                    preroll = []
            else:
                buffer.append(frame)
                total_frames += 1
                if rms > threshold:
                    speech_frames += 1
                    silence_run = 0
                else:
                    silence_run += 1

                end_of_utterance = (
                    silence_run >= SILENCE_FRAMES_TO_END
                    or total_frames >= MAX_UTTERANCE_FRAMES
                )
                if end_of_utterance:
                    if speech_frames >= MIN_SPEECH_FRAMES:
                        wav = encode_wav(b"".join(buffer))
                        in_speech, speech_frames, silence_run, total_frames = False, 0, 0, 0
                        buffer = []
                        self._deliver(wav)
                    else:
                        in_speech, speech_frames, silence_run, total_frames = False, 0, 0, 0
                        buffer = []
