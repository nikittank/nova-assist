"""AssistantController - the composition root.

Wires together:  microphone -> STT -> agent(LLM+tools) -> TTS -> UI bus,
plus the reminder scheduler, desktop notifications and the settings
lifecycle.  A single worker thread processes spoken/typed requests
sequentially so tool runs never overlap.
"""

from __future__ import annotations

import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Callable, Optional

from .bus import EventBus
from .config import Config
from .db import Database
from .audio.recorder import MicRecorder
from .audio.stt import STTError, create_stt
from .audio.tts import TTSPlayer
from .brain.agent import Agent
from .brain.llm import GroqBrain, LLMError
from .services.notifier import notify
from .services.reminders import ReminderService

IDLE, LISTENING, RECORDING, PROCESSING, SPEAKING = (
    "idle", "listening", "recording", "processing", "speaking")

# short cool-down after TTS so the speaker tail is not re-captured
UNSUPPRESS_DELAY_MS = 350


class AssistantController:
    def __init__(self, bus: EventBus, config: Optional[Config] = None) -> None:
        self.bus = bus
        self.config = config or Config()
        self.db = Database(self.config.db_path())

        self.tts = TTSPlayer(
            api_key=self.config.tts_key(),
            voice=self.config.get("tts_voice", "aura-asteria-en"),
            enabled=bool(self.config.get("tts_enabled", True)),
            on_start=self._on_tts_start,
            on_end=self._on_tts_end,
            on_error=lambda m: self.bus.error.emit(m),
        )
        self.recorder = MicRecorder(on_utterance=self._on_utterance,
                                    on_error=lambda m: self.bus.error.emit(m),
                                    on_level=lambda lvl: self.bus.mic_level.emit(lvl))
        self.reminders = ReminderService(self.db, on_fire=self._on_reminder_fired,
                                         on_error=lambda m: self.bus.error.emit(m))

        self._brain: Optional[GroqBrain] = None
        self._agent: Optional[Agent] = None
        self._stt = None
        self._stt_error = ""

        self._tasks: "queue.Queue[tuple]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._busy = False
        self._status = IDLE
        self._tts_speaking = False
        self._tts_lock = threading.Lock()

        # one-shot voice capture (Reminders page microphone button)
        self._oneshot_cb: Optional[Callable[[str], None]] = None
        self._oneshot_active = False
        self._oneshot_piggyback = False
        self._unsuppress_timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------ life
    def start(self) -> None:
        self.reminders.start()
        self._worker = threading.Thread(target=self._work_loop, name="nova-worker",
                                        daemon=True)
        self._worker.start()
        if self.config.get("auto_listen_on_start"):
            self.toggle_listening(True)
        else:
            self._set_status(IDLE)

    def shutdown(self) -> None:
        self._stop_evt.set()
        try:
            self.recorder.stop()
        except Exception:
            pass
        try:
            self.reminders.stop()
        except Exception:
            pass
        try:
            self.tts.shutdown()
        except Exception:
            pass
        try:
            self._tasks.put_nowait(("quit", None))
        except Exception:
            pass

    # ---------------------------------------------------------------- status
    def _set_status(self, status: str) -> None:
        if status != self._status:
            self._status = status
            self.bus.status_changed.emit(status)

    def current_status(self) -> str:
        return self._status

    # ------------------------------------------------------------ microphone
    def toggle_listening(self, force_on: Optional[bool] = None) -> None:
        want_on = (not self.recorder.listening) if force_on is None else force_on
        if want_on:
            if not self.recorder.available:
                self.bus.error.emit(
                    "Microphone support unavailable: " + self.recorder.import_error())
                return
            ok = self.recorder.start(mode=self.config.get("listening_mode", "continuous"))
            self.bus.listening_changed.emit(ok)
            if ok:
                self._set_status(LISTENING if self._status != SPEAKING else SPEAKING)
                self.bus.info.emit("Microphone on - "
                                   + ("say something, I am listening."
                                      if self.recorder.mode == "continuous"
                                      else "hold the mic button (or Ctrl+Space) to talk."))
            else:
                self._set_status(IDLE)
        else:
            self.recorder.stop()
            self.bus.listening_changed.emit(False)
            if self._status in (LISTENING, RECORDING):
                self._set_status(IDLE)

    def ptt_start(self) -> None:
        if self.recorder.listening and self.config.get("listening_mode") == "ptt":
            self.recorder.ptt_start()
            self._set_status(RECORDING)

    def ptt_stop(self) -> None:
        if self.recorder.listening:
            self.recorder.ptt_stop()
            self._set_status(PROCESSING if self._busy else LISTENING)

    def _on_utterance(self, wav_bytes: bytes) -> None:
        """Called from the VAD thread when a complete utterance is ready."""
        if self._stop_evt.is_set():
            return
        # one-shot capture (voice reminder field, ...) short-circuits the queue
        cb = self._oneshot_cb
        if self._oneshot_active and cb is not None:
            self._oneshot_active = False
            self._oneshot_cb = None
            threading.Thread(target=self._finish_oneshot, args=(cb, wav_bytes),
                             daemon=True, name="nova-oneshot").start()
            return
        self._tasks.put(("wav", wav_bytes))

    # --------------------------------------------------- one-shot voice flow
    def listen_once(self, on_text: Callable[[str], None]) -> bool:
        """Capture a single spoken utterance and hand the transcript back.

        Runs on a dedicated capture session when the mic is idle; when a
        listening session is already running the next utterance is routed
        to ``on_text`` instead of the normal request queue.
        """
        if self._oneshot_active:
            return False

        def deliver(text: str) -> None:
            self.bus.oneshot_state.emit("")
            self.bus.oneshot_transcript.emit(text)
            try:
                on_text(text)
            except Exception as exc:
                self.bus.error.emit(f"Voice capture handler failed: {exc}")

        self._oneshot_cb = deliver
        if self.recorder.listening:
            # piggy-back on the live session: next utterance is ours
            self._oneshot_active = True
            self._oneshot_piggyback = True
            self.bus.oneshot_state.emit("listening")
            return True
        self._oneshot_piggyback = False
        self._oneshot_active = True
        ok = self.recorder.start_oneshot(lambda wav: self._on_utterance(wav))
        if not ok:
            self._oneshot_active = False
            self._oneshot_cb = None
            return False
        self.bus.oneshot_state.emit("listening")
        return True

    def cancel_listen_once(self) -> None:
        self._oneshot_active = False
        self._oneshot_cb = None
        if not self._oneshot_piggyback:
            # we own the capture session - close it; a main listening session
            # (piggy-back mode) must stay untouched
            self.recorder.stop()
            self.bus.listening_changed.emit(False)
        self._oneshot_piggyback = False
        self.bus.oneshot_state.emit("")

    def _finish_oneshot(self, cb: Callable[[str], None], wav_bytes: bytes) -> None:
        """Transcribe the captured WAV (worker thread) and deliver the text."""
        self.bus.oneshot_state.emit("transcribing")
        if not wav_bytes:
            cb("")
            return
        try:
            text = self._transcribe(wav_bytes)
        except Exception:
            text = ""
        cb(text or "")

    # ------------------------------------------------------------- user turn
    def send_text(self, text: str, attachment: Optional[dict] = None) -> None:
        text = (text or "").strip()
        if text:
            self._tasks.put(("text", (text, attachment)))

    def attach_file(self, path: str) -> dict:
        """Read a local file so it can be attached to the next message."""
        from .brain import tools as toolset
        result = toolset.execute("read_file", {"path": path, "max_chars": 24000},
                                 toolset.ToolContext(self.db, self.config))
        if not result.get("ok"):
            return {"ok": False, "error": result.get("message", "Could not read file.")}
        return {"ok": True, "name": Path(path).name,
                "content": result.get("content", "")}

    def stop_current(self) -> None:
        """User pressed Stop: cancel the agent turn and silence the voice."""
        if self._agent is not None:
            self._agent.cancel()
        with self._tts_lock:
            was = self._tts_speaking
        self.tts.stop()
        self._tts_speaking = False
        self._busy = False
        self._unsuppress_now()
        self._set_status(LISTENING if self.recorder.listening else IDLE)
        if was:
            self.bus.info.emit("Stopped.")

    # ------------------------------------------------------------- internals
    def _work_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                kind, payload = self._tasks.get(timeout=0.5)
            except queue.Empty:
                continue
            if kind == "quit":
                break
            self._busy = True
            self.recorder.set_suppressed(True)
            self._set_status(PROCESSING)
            try:
                if kind == "wav":
                    text = self._transcribe(payload)
                    if text:
                        self._run_agent(text)
                    else:
                        self.bus.info.emit("I couldn't hear anything intelligible.")
                elif kind == "text":
                    text, attachment = payload
                    self._run_agent(text, attachment)
            except Exception as exc:
                self.bus.error.emit(str(exc))
            finally:
                self._busy = False
                if not self.tts.speaking and not self._tts_speaking:
                    self._unsuppress_soon()
                    self._set_status(LISTENING if self.recorder.listening else IDLE)
                # if TTS is still talking, _on_tts_end restores the status

    def _transcribe(self, wav_bytes: bytes) -> str:
        try:
            if self._stt is None:
                self._stt = create_stt(self.config)
                self._stt_error = ""
        except STTError as exc:
            self._stt = None
            self._stt_error = str(exc)
        if self._stt is None:
            self.bus.error.emit(self._stt_error or "STT engine unavailable.")
            return ""
        try:
            return self._stt.transcribe(wav_bytes)
        except STTError as exc:
            self.bus.error.emit(str(exc))
            return ""

    def _ensure_agent(self) -> Optional[Agent]:
        if self._agent is None:
            try:
                if self._brain is None:
                    self._brain = GroqBrain(self.config)
                self._brain.reconfigure()
            except LLMError as exc:
                self.bus.error.emit(str(exc))
                return None
            self._agent = Agent(
                self.config, self.db, self._brain,
                emit=self._agent_emit,
                confirm=self._confirm_action,
            )
        return self._agent

    def _run_agent(self, text: str, attachment: Optional[dict] = None) -> None:
        agent = self._ensure_agent()
        if agent is None:
            return
        agent.handle_user_text(text, attachment)

    def _agent_emit(self, event: str, **kwargs) -> None:
        """Route agent events to the bus + TTS."""
        if event == "assistant_delta":
            self.bus.assistant_delta.emit(kwargs["text"])
            if self.tts.enabled and self.config.tts_key():
                self.tts.feed(kwargs["text"])
        elif event == "assistant_done":
            text = kwargs.get("text", "")
            if text and self.tts.enabled and self.config.tts_key():
                self.tts.feed(text)
                self.tts.finish()
            self.bus.assistant_done.emit(text)
        elif event == "user_message":
            self.bus.user_message.emit(kwargs["text"])
        elif event == "error":
            self.bus.error.emit(kwargs["message"])
        elif event == "thinking":
            self.bus.thinking_changed.emit(kwargs["active"])
        elif event == "tool_call":
            self.bus.tool_call.emit(kwargs["name"], repr(kwargs["args"])[:300])
        elif event == "tool_result":
            self.bus.tool_result.emit(kwargs["name"], str(kwargs.get("summary", ""))[:300])
            self.bus.activity_logged.emit({})

    # confirmations ----------------------------------------------------
    def _confirm_action(self, name: str, args: dict, description: str) -> bool:
        holder = {"approved": False}
        done = threading.Event()
        self.bus.confirm_request.emit({
            "id": uuid.uuid4().hex, "name": name, "args": args,
            "description": description, "holder": holder, "event": done,
        })
        done.wait(timeout=180)
        return bool(holder["approved"])

    # TTS callbacks ------------------------------------------------------
    def _on_tts_start(self) -> None:
        self._tts_speaking = True
        self.recorder.set_suppressed(True)
        self._set_status(SPEAKING)

    def _on_tts_end(self) -> None:
        self._tts_speaking = False
        if not self._busy:
            self._unsuppress_soon()
        self._set_status(LISTENING if self.recorder.listening
                         and not self._busy else
                         (PROCESSING if self._busy else IDLE))

    def _unsuppress_now(self) -> None:
        self.recorder.set_suppressed(False)

    def _unsuppress_soon(self) -> None:
        """Release mic suppression after a short cool-down (speaker tail)."""
        self._cancel_unsuppress_timer()
        self.recorder.set_suppressed(True)
        self._unsuppress_timer = threading.Timer(
            UNSUPPRESS_DELAY_MS / 1000.0, self._unsuppress_now, daemon=True)
        self._unsuppress_timer.start()

    def _cancel_unsuppress_timer(self) -> None:
        if self._unsuppress_timer is not None:
            try:
                self._unsuppress_timer.cancel()
            except Exception:
                pass
            self._unsuppress_timer = None

    # reminders -----------------------------------------------------------
    def _on_reminder_fired(self, reminder: dict) -> None:
        message = reminder.get("message", "Reminder")
        self.db.log_activity("reminder", f"Fired: {message}")
        notify("Nova - Reminder", message)
        self.bus.reminder_fired.emit(reminder)
        if (self.config.get("speak_reminders", True) and self.tts.enabled
                and not self._busy):
            with self._tts_lock:
                self.tts.feed(f"Reminder: {message}")
                self.tts.finish()

    # settings -------------------------------------------------------------
    def apply_settings(self) -> list[str]:
        """Persist settings and hot-reload every component. Returns errors."""
        self.config.save()
        errors: list[str] = []
        self.tts.configure(self.config.tts_key(),
                           self.config.get("tts_voice", "aura-asteria-en"),
                           bool(self.config.get("tts_enabled", True)))
        # STT engine - recreate; report key problems up-front
        try:
            self._stt = create_stt(self.config)
            self._stt_error = ""
        except STTError as exc:
            self._stt = None
            self._stt_error = str(exc)
            errors.append(str(exc))
        if self.config.has_groq_key():
            try:
                if self._brain is None:
                    self._brain = GroqBrain(self.config)
                else:
                    self._brain.reconfigure()
                self._agent = None  # rebuild agent with fresh config/brain
            except LLMError as exc:
                errors.append(str(exc))
        mode = self.config.get("listening_mode", "continuous")
        self.recorder.set_mode(mode)
        if self.recorder.listening:
            self.recorder.stop()
            ok = self.recorder.start(mode=mode)
            self.bus.listening_changed.emit(ok)
        self.bus.settings_applied.emit()
        return errors

    def reset_memory(self) -> None:
        if self._agent is not None:
            self._agent.reset_memory()
        else:
            self.db.clear_messages()
        self.bus.info.emit("Conversation memory cleared.")

    # misc ------------------------------------------------------------------
    @staticmethod
    def open_data_folder() -> None:
        from .services import automation
        automation.open_path(str(Path.home() / ".nova-assistant"))

    @property
    def stt_engine_name(self) -> str:
        if self._stt is not None:
            return self._stt.name
        engine = self.config.get("stt_engine")
        if engine == "deepgram_nova3":
            return f"Deepgram {self.config.get('stt_deepgram_model', 'nova-3')}"
        return f"Groq {self.config.get('stt_groq_model', 'whisper-large-v3-turbo')}"

    def llm_model_name(self) -> str:
        return str(self.config.get("llm_model", ""))

    def os_name(self) -> str:
        return os.name
