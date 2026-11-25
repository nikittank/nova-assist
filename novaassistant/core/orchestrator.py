"""Nova orchestration: voice -> STT -> LLM -> tools -> verify -> response -> TTS.

Complete pipeline (requirement #1, #2, #3, #4, #6):

  Mic capture (VAD end-of-speech OR push-to-talk release)
    -> final transcript
    -> USER message added to conversation FIRST
    -> LLM reasoning + tool calls
    -> execute + verify
    -> final AI response
    -> Deepgram Aura TTS (only if voice.tts_enabled)

All long work happens in a worker QThread; the UI subscribes to signals.

State model (requirement #3, #4):
  - LLM is ALWAYS enabled — the core reasoning engine. No on/off switch.
  - STT path is only entered when voice.stt_enabled AND voice.mic_enabled.
  - VAD only runs when mic_mode == "continuous" (hands-free).
    mic_mode == "push_to_talk" -> capture on press, emit on release, NO VAD.
    mic_mode == "off" -> mic disabled, no capture, no VAD.
  - TTS only fires when voice.tts_enabled. If disabled the AI response is
    shown as text only, never played as audio.
"""
from __future__ import annotations

import json
import re
import time
import traceback

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..audio.capture import MicCapture
from ..audio.playback import AudioPlayer
from ..providers import deepgram, groq
from .llm_tools import TOOLS_SCHEMA, ToolExecutor

SYSTEM_PROMPT = """You are Nova, a precise personal desktop assistant running \
locally on the user's Windows machine. You control the desktop: apps, folders, \
files, notes and reminders.

Rules:
- Prefer tools over guessing. Use the provided tools for notes, reminders and \
desktop actions.
- For reminders, compute the ISO datetime from the current time \
(get_current_datetime) and the user's words.
- When a user asks to EDIT or CHANGE an existing note or reminder, use the \
update/delete tools — never silently create duplicates.
- Keep final answers short and direct (1-3 sentences), like a calm operator.
- After executing tools, report exactly what happened in plain language. If a \
tool failed, say so plainly without exposing the raw error or stack trace.
- The user may speak casually; infer intent correctly.
- Never include raw file names, internal paths, tool names, JSON payloads, or \
system output in your spoken reply unless the user explicitly asks for them. \
Keep spoken responses natural and human.
"""

STATE_IDLE = "IDLE"
STATE_LISTENING = "LISTENING"
STATE_TRANSCRIBING = "TRANSCRIBING"
STATE_THINKING = "THINKING"
STATE_EXECUTING = "EXECUTING"
STATE_RESPONDING = "RESPONDING"
STATE_SPEAKING = "SPEAKING"
STATE_DONE = "DONE"


# ----------------------------------------------------------------------
# TTS sanitization
# ----------------------------------------------------------------------
_TECHNICAL_PATTERNS = [
    re.compile(r"[A-Za-z]:[\\/][^\s`'\"<>|]+"),          # windows paths
    re.compile(r"/(?:[a-zA-Z0-9_.-]+/)+[a-zA-Z0-9_.-]+"),  # posix paths
    re.compile(r"\b[a-f0-9]{16,}\b", re.I),                # hash-like ids
    re.compile(r"\b\d{4,}\b"),                            # long numbers
    re.compile(r"```.*?```", re.S),                       # code blocks
    re.compile(r"`[^`]+`"),                              # inline code
    re.compile(r"\b(?:gsk_|dg_|sk-)[A-Za-z0-9_\-]{6,}"),  # api key stubs
    re.compile(r"\bhttps?://\S+"),                        # urls
]
_TOOL_NAME_RE = re.compile(r"\b(?:open_app|open_path|create_note|update_note|"
                           r"delete_note|search_notes|create_reminder|"
                           r"update_reminder|delete_reminder|list_reminders|"
                           r"complete_reminder|get_current_datetime)\b")


def _sanitize_for_speech(text: str) -> str:
    """Strip technical noise so TTS never speaks file names, paths or tool
    names (requirement #1: 'Never make TTS unnecessarily speak technical
    information')."""
    if not text:
        return ""
    out = text
    for pat in _TECHNICAL_PATTERNS:
        out = pat.sub(" ", out)
    out = _TOOL_NAME_RE.sub(" ", out)
    # collapse whitespace
    out = re.sub(r"\s+", " ", out).strip()
    return out


class _Worker(QThread):
    """LLM + tools pipeline for one request (text or transcript)."""

    state_changed = Signal(str)
    steps_changed = Signal(list)
    response_ready = Signal(str)
    error_occurred = Signal(str)
    latency_measured = Signal(int)
    activity = Signal(str, str, str, str)  # category, message, status, detail

    def __init__(self, ctx, transcript: str, parent: QObject | None = None):
        super().__init__(parent)
        self._ctx = ctx
        self._transcript = transcript
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        self._ctx.executor.reset(cancelled=True)

    # ------------------------------------------------------------ steps
    def _steps(self, items: list[tuple[str, str]]) -> None:
        self.steps_changed.emit([{"label": a, "status": b} for a, b in items])

    def _log(self, category: str, message: str, status: str = "ok",
             detail: str = "", source: str = "", target: str = "") -> None:
        try:
            self.activity.emit(category, message, status, detail)
        except Exception:
            pass

    # ------------------------------------------------------------- run
    def run(self) -> None:  # noqa: C901 — pipeline
        cfg = self._ctx.config
        stack = cfg.active_stack()
        transcript = self._transcript
        started = time.monotonic()
        try:
            # ------------------------------------------------ 01 UNDERSTAND
            self._steps([("01 UNDERSTANDING REQUEST", "active"),
                         ("02 PLANNING ACTIONS", "queued"),
                         ("03 EXECUTING TOOLS", "queued"),
                         ("04 COMPOSING RESPONSE", "queued")])
            self._log("ai", f"Processing request: {transcript[:80]}",
                      "ok", detail=transcript, source="ai")
            if self._cancelled:
                self._log("ai", "Request cancelled by user", "cancel",
                           source="user")
                return
            if not stack["llm_key"]:
                raise groq.ProviderError(
                    "No Groq API key configured. Open Settings to add one.")

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *self._ctx.conversation.memory(
                    int(cfg.get("llm.memory_messages", 12))),
                {"role": "user", "content": transcript},
            ]

            # ------------------------------------------------- 02 PLAN
            self._steps([("01 UNDERSTANDING REQUEST", "done"),
                         ("02 PLANNING ACTIONS", "active"),
                         ("03 EXECUTING TOOLS", "queued"),
                         ("04 COMPOSING RESPONSE", "queued")])
            self.state_changed.emit(STATE_THINKING)
            if self._cancelled:
                self._log("ai", "Cancelled during planning", "cancel",
                           source="user")
                return

            executor = self._ctx.executor
            executor.reset(cancelled=False)
            message = groq.chat(
                key=stack["llm_key"], messages=messages,
                model=stack["llm_model"],
                temperature=float(cfg.get("llm.temperature", 1.0)),
                max_tokens=int(cfg.get("llm.max_tokens", 2036)),
                tools=TOOLS_SCHEMA,
                reasoning_effort=cfg.get("llm.reasoning_effort", "medium"),
            )

            # -------------------------------------------- 03 EXECUTE
            tool_rounds = 0
            while message.get("tool_calls") and tool_rounds < 4:
                if self._cancelled:
                    self._log("tool", "Tool execution cancelled", "cancel",
                              source="user")
                    return
                self.state_changed.emit(STATE_EXECUTING)
                self._steps([("01 UNDERSTANDING REQUEST", "done"),
                             ("02 PLANNING ACTIONS", "done"),
                             ("03 EXECUTING TOOLS", "active"),
                             ("04 COMPOSING RESPONSE", "queued")])
                messages.append({
                    "role": "assistant",
                    "content": message.get("content") or "",
                    "tool_calls": message["tool_calls"],
                })
                results_payload = []
                total = len(message["tool_calls"])
                for idx, call in enumerate(message["tool_calls"], start=1):
                    if self._cancelled:
                        self._log("tool", "Tool call cancelled", "cancel",
                                  source="user")
                        return
                    fn = call.get("function", {})
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    self._steps([
                        ("01 UNDERSTANDING REQUEST", "done"),
                        ("02 PLANNING ACTIONS", "done"),
                        (f"03 {name.upper()} ({idx}/{total})", "active"),
                        ("04 COMPOSING RESPONSE", "queued")])
                    result = executor.run(name, args)
                    ok = not (isinstance(result, dict) and result.get("error"))
                    self._log("tool", f"{name} — {result.get('detail','ok' if not result.get('error') else result.get('error'))[:100]}",
                              "ok" if ok else "err",
                              detail=json.dumps(result)[:800],
                              source="ai", target=name)
                    results_payload.append({
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": json.dumps(result)[:2000],
                    })
                messages.extend(results_payload)
                if self._cancelled:
                    return
                message = groq.chat(
                    key=stack["llm_key"], messages=messages,
                    model=stack["llm_model"],
                    temperature=float(cfg.get("llm.temperature", 1.0)),
                    max_tokens=int(cfg.get("llm.max_tokens", 2036)),
                    tools=TOOLS_SCHEMA,
                    reasoning_effort=cfg.get("llm.reasoning_effort", "medium"),
                )
                tool_rounds += 1

            # --------------------------------------------- 04 RESPOND
            if self._cancelled:
                return
            self._steps([("01 UNDERSTANDING REQUEST", "done"),
                         ("02 PLANNING ACTIONS", "done"),
                         ("03 EXECUTING TOOLS", "done"),
                         ("04 COMPOSING RESPONSE", "active")])
            self.state_changed.emit(STATE_RESPONDING)
            answer = (message.get("content") or "").strip()
            if not answer:
                answer = "Done."
            self.latency_measured.emit(int((time.monotonic() - started) * 1000))
            self._log("ai", f"Response: {answer[:80]}", "ok",
                      detail=answer, source="ai")
            self.response_ready.emit(answer)
            self._steps([("01 UNDERSTANDING REQUEST", "done"),
                         ("02 PLANNING ACTIONS", "done"),
                         ("03 EXECUTING TOOLS", "done"),
                         ("04 COMPOSING RESPONSE", "done")])
        except Exception as exc:
            if self._cancelled:
                return
            detail = traceback.format_exc(limit=3)
            self._log("error", str(exc), "err", detail=detail, source="ai")
            self.error_occurred.emit(str(exc))


class Orchestrator(QObject):
    """Public facade wired to the UI + audio stack."""

    state_changed = Signal(str)
    transcript_ready = Signal(str)          # final STT transcript
    partial_transcript = Signal(str)        # live capture status text
    steps_changed = Signal(list)
    response_ready = Signal(str)
    error_occurred = Signal(str, str)       # title, detail
    latency_measured = Signal(int)
    listening_changed = Signal(bool)
    level_changed = Signal(float)
    activity_logged = Signal(dict)          # one activity entry

    def __init__(self, config, notes_store, reminders_store, activity_log,
                 conversation_store, parent: QObject | None = None):
        super().__init__(parent)
        self.config = config
        self.notes = notes_store
        self.reminders = reminders_store
        self.activity = activity_log
        self.conversation = conversation_store

        self.capture = MicCapture(
            sensitivity=int(config.get("voice.vad_sensitivity", 82)),
            silence_ms=int(config.get("voice.silence_ms", 800)), parent=self)
        self.player = AudioPlayer(self)
        self.executor = ToolExecutor(notes_store, reminders_store, activity_log)

        self._state = STATE_IDLE
        self._worker: _Worker | None = None
        self._pending_listen = False
        self._shutdown = False
        self._ptt_active = False   # push-to-talk held state

        # wiring
        self.capture.level_changed.connect(self.level_changed)
        self.capture.utterance_ready.connect(self._on_utterance)
        self.capture.state_changed.connect(self._on_capture_state)
        self.capture.capture_error.connect(
            lambda e: self.error_occurred.emit("Microphone", e))
        self.player.playback_finished.connect(self._on_tts_finished)
        self.player.playback_stopped.connect(self._on_tts_finished)
        self.player.playback_error.connect(
            lambda e: self.error_occurred.emit("TTS", e))

        # bridge worker activity signals to the ActivityLog
        self.activity_logged_handler_active = True

    # ------------------------------------------------------------ state
    @property
    def state(self) -> str:
        return self._state

    def _set_state(self, value: str) -> None:
        self._state = value
        self.state_changed.emit(value)

    @property
    def is_listening(self) -> bool:
        return self.capture.is_open and self.capture._want_input

    @property
    def mic_mode(self) -> str:
        return self.config.get("voice.mic_mode", "continuous")

    @property
    def stt_enabled(self) -> bool:
        return bool(self.config.get("voice.stt_enabled", True))

    @property
    def tts_enabled(self) -> bool:
        return bool(self.config.get("voice.tts_enabled", True))

    @property
    def mic_enabled(self) -> bool:
        return bool(self.config.get("voice.mic_enabled", True))

    def _can_use_mic(self) -> bool:
        """Mic is allowed only when STT is enabled, mic is enabled, and
        the mode is not 'off'."""
        return self.mic_enabled and self.stt_enabled and \
            self.mic_mode in ("continuous", "push_to_talk")

    def _on_capture_state(self, state: str) -> None:
        """Translate the raw capture VAD state into a partial transcript
        hint visible in the conversation/overlay."""
        if not self.capture._want_input:
            return
        hints = {
            "idle": "Listening…",
            "speaking": "Listening…",
            "trailing": "Processing speech…",
        }
        hint = hints.get(state, "")
        if hint:
            self.partial_transcript.emit(hint)

    # ------------------------------------------------------ TTS gating
    def _on_tts_finished(self, *_):
        self._set_state(STATE_IDLE)
        if self._pending_listen:
            self._pending_listen = False
            self.start_listening()

    def speak(self, text: str) -> None:
        """Deepgram Aura TTS playback (async).

        Honors voice.tts_enabled — when False, the response is shown as text
        only and never played as audio (requirement #2)."""
        if not text:
            return
        if not self.tts_enabled:
            # text-only mode: skip audio entirely
            self._set_state(STATE_DONE)
            QTimer.singleShot(150, lambda: self._set_state(STATE_IDLE))
            return
        key = self.config.deepgram_key_for_tts()
        voice = self.config.get("voice.tts_voice", "aura-2-thalia-en")
        if not key:
            # surface as a quiet diagnostic — not in the chat
            self.activity.log("error",
                              "TTS unavailable — no Deepgram key",
                              status="err")
            self._set_state(STATE_IDLE)
            return

        # Sanitize the text so TTS doesn't speak file names, paths, tools
        spoken = _sanitize_for_speech(text)
        if not spoken:
            # nothing safe to speak — fall back to a clean idle
            self._set_state(STATE_IDLE)
            return

        def work():
            try:
                wav = deepgram.speak(key, spoken, voice)
                if not self._shutdown:
                    self._set_state(STATE_SPEAKING)
                    self.player.play(wav)
            except Exception as exc:
                if not self._shutdown:
                    self.activity.log("error", f"TTS failed: {exc}",
                                      status="err",
                                      detail=traceback.format_exc(limit=3))

        import threading
        threading.Thread(target=work, name="nova-tts", daemon=True).start()

    def stop_speaking(self) -> None:
        self.player.stop()
        if self._state == STATE_SPEAKING:
            self._set_state(STATE_IDLE)

    # ------------------------------------------------------- listening
    def start_listening(self) -> bool:
        """Open mic for one utterance (VAD-delimited in continuous mode,
        or until stop_listening is called in push-to-talk mode)."""
        if not self._can_use_mic():
            self.activity.log("voice",
                              "Mic not available — STT or mic disabled",
                              status="err")
            return False
        if self.player.is_playing():
            # never start capture over TTS output
            self._pending_listen = True
            return False
        self.stop_speaking()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self.activity.log("voice", "Listening started",
                          status="ok", source="user")
        ok = self.capture.start_listening()
        if ok:
            self._set_state(STATE_LISTENING)
            self.listening_changed.emit(True)
        return ok

    def stop_listening(self) -> None:
        was = self.is_listening
        self.capture.stop_listening(flush=True)
        self.listening_changed.emit(False)
        if was:
            self.activity.log("voice", "Listening stopped",
                              status="ok", source="user")
        if self._state == STATE_LISTENING:
            self._set_state(STATE_IDLE)

    def toggle_listening(self) -> None:
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()

    # ----------------------------------------------- push-to-talk (PTT)
    def push_to_talk_press(self) -> bool:
        """Begin a push-to-talk capture. The mic stays open until
        push_to_talk_release() — VAD's natural end-of-speech detection
        also still works to flush shorter utterances, but the mic never
        re-opens automatically (requirement #3, #4: PTT = no continuous
        VAD listening)."""
        if self.mic_mode != "push_to_talk":
            # fall back to toggle (so the global hotkey still works when
            # the user is in continuous mode)
            return self.start_listening()
        if not self._can_use_mic():
            return False
        if self.player.is_playing():
            self.stop_speaking()
        self._ptt_active = True
        # open the mic and mark want_input — VAD will emit utterance_ready
        # when speech ends naturally; release() does a final flush
        ok = self.capture.start_listening()
        if not ok:
            self._ptt_active = False
            return False
        self._set_state(STATE_LISTENING)
        self.listening_changed.emit(True)
        self.activity.log("voice", "Push-to-talk started",
                          status="ok", source="user")
        return True

    def push_to_talk_release(self) -> None:
        """Release PTT: stop capture and flush whatever was buffered."""
        if not self._ptt_active:
            return
        self._ptt_active = False
        self.capture.stop_listening(flush=True)
        self.listening_changed.emit(False)
        self.activity.log("voice", "Push-to-talk released",
                          status="ok", source="user")

    def _on_utterance(self, wav_bytes: bytes) -> None:
        # In PTT mode, the VAD may emit utterance_ready mid-press when
        # end-of-speech is detected. We honor that (transcribe + respond)
        # but keep the PTT flag so release() doesn't double-stop.
        if self._ptt_active:
            # keep listening for more speech until release
            self.capture._want_input = True
        self.listening_changed.emit(False)
        self._set_state(STATE_TRANSCRIBING)
        self.partial_transcript.emit("Transcribing…")
        stack = self.config.active_stack()
        provider = self.config.get("voice.stt_provider", "groq")

        def work():
            text = ""
            error = ""
            try:
                if provider == "deepgram":
                    text = deepgram.transcribe(
                        stack["stt_key"], wav_bytes,
                        model=self.config.get("voice.stt_model_deepgram", "nova-3"),
                        language=self.config.get("voice.deepgram_language", "multi"))
                else:
                    text = groq.transcribe(
                        stack["stt_key"], wav_bytes,
                        model=self.config.get("voice.stt_model_groq",
                                              "whisper-large-v3-turbo"),
                        language=self.config.get("voice.deepgram_language", "auto"))
            except Exception as exc:
                error = str(exc)
            if self._shutdown:
                return
            if error:
                self.activity.log("error", f"STT failed: {error}",
                                  status="err",
                                  detail=traceback.format_exc(limit=3))
                self.error_occurred.emit("Speech recognition", error)
                self._set_state(STATE_IDLE)
            elif text.strip():
                self.activity.log("voice", f"Transcribed: {text.strip()[:80]}",
                                  status="ok", source="user")
                # ALWAYS add the user message to the conversation FIRST so
                # it appears before the AI response (requirement #1).
                self.conversation.add("user", text.strip())
                self.transcript_ready.emit(text.strip())
                self._run_pipeline(text.strip())
            else:
                self.partial_transcript.emit("")
                self._set_state(STATE_IDLE)

        import threading
        threading.Thread(target=work, name="nova-stt", daemon=True).start()

    # ---------------------------------------------------- text requests
    def submit_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        # user message is added BEFORE running the pipeline (req #1)
        self.conversation.add("user", text)
        self.activity.log("user", f"Sent: {text[:80]}",
                          status="ok", source="user")
        self._run_pipeline(text)

    def _run_pipeline(self, transcript: str) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self.executor.reset()
        # parent=None: the worker may be created from the STT thread; we hold
        # the reference ourselves and never reparent it across threads.
        self._worker = _Worker(self, transcript, parent=None)
        self._worker.state_changed.connect(self._set_state)
        self._worker.steps_changed.connect(self.steps_changed)
        self._worker.latency_measured.connect(self.latency_measured)
        self._worker.response_ready.connect(self._on_response)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.activity.connect(self._on_worker_activity)
        self._worker.finished.connect(self._worker_finished)
        self._worker.start()

    def _on_worker_activity(self, category: str, message: str,
                            status: str, detail: str) -> None:
        try:
            entry = self.activity.log(category, message, status=status,
                                       detail=detail, source="ai")
            self.activity_logged.emit(entry)
        except Exception:
            pass

    def _on_response(self, answer: str) -> None:
        self.conversation.add("nova", answer)
        self.response_ready.emit(answer)
        self.partial_transcript.emit("")
        if self.tts_enabled and self.config.get("voice.speak_replies", True):
            self.speak(answer)
        else:
            self._set_state(STATE_DONE)
            # brief "done" pulse then back to idle
            QTimer.singleShot(200, lambda: self._set_state(STATE_IDLE))

    def _on_error(self, message: str) -> None:
        # Errors never go into the conversation store as content; they are
        # surfaced as a friendly banner via error_occurred and logged to
        # Activity (Diagnostics). Raw tracebacks never reach the chat.
        self.error_occurred.emit("Execution Error", message)
        self._set_state(STATE_IDLE)

    def _worker_finished(self) -> None:
        if self._state in (STATE_THINKING, STATE_EXECUTING, STATE_RESPONDING,
                           STATE_TRANSCRIBING):
            self._set_state(STATE_IDLE)

    def cancel_all(self) -> None:
        """Stop everything: capture, worker, TTS."""
        was_listening = self.is_listening
        was_speaking = self._state == STATE_SPEAKING
        was_running = bool(self._worker and self._worker.isRunning())
        self.capture.stop_listening(flush=False)
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self.player.stop()
        self._set_state(STATE_IDLE)
        self.listening_changed.emit(False)
        if was_listening or was_running or was_speaking:
            self.activity.log("system", "Action cancelled by user",
                              status="cancel", source="user")

    def apply_audio_settings(self) -> None:
        self.capture.set_params(
            sensitivity=int(self.config.get("voice.vad_sensitivity", 82)),
            silence_ms=int(self.config.get("voice.silence_ms", 800)))
        try:
            self.player.set_volume(int(self.config.get("voice.tts_volume", 90)))
        except Exception:
            pass
        # if mic was just disabled mid-listen, stop cleanly
        if not self._can_use_mic() and self.is_listening:
            self.capture.stop_listening(flush=False)
            self.listening_changed.emit(False)
            self._set_state(STATE_IDLE)

    def shutdown(self) -> None:
        self._shutdown = True
        self.cancel_all()
        self.capture.close()
