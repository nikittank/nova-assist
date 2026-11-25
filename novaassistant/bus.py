"""Nova Assistant - application event bus.

Background threads (audio capture, STT, agent, scheduler) communicate with
the Qt main thread exclusively through these signals.  Qt delivers signals
emitted from non-GUI threads to slots in the GUI thread via queued
connections, so all UI code stays thread-safe.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    # status: idle | listening | recording | processing | speaking
    status_changed = Signal(str)

    # chat flow
    user_message = Signal(str)                 # final user text (voice or typed)
    assistant_delta = Signal(str)              # streamed token
    assistant_done = Signal(str)               # full final assistant text
    thinking_changed = Signal(bool)            # reasoning model is generating

    # tool activity
    tool_call = Signal(str, str)               # name, args-json
    tool_result = Signal(str, str)             # name, short result
    confirm_request = Signal(object)           # {"id","name","args","description","holder","event"}

    # voice
    listening_changed = Signal(bool)           # mic toggle state
    partial_heard = Signal(str)                # optional interim info
    mic_level = Signal(float)                  # live input level 0.0..1.0 (VAD thread)
    oneshot_state = Signal(str)                # one-shot capture state text ("", listening, thinking)
    oneshot_transcript = Signal(str)           # one-shot capture final transcript

    # data changes
    notes_changed = Signal()                   # notes table changed (UI refresh)
    reminders_changed = Signal()               # reminders table changed (UI refresh)

    # overlay / widgets
    overlay_toggled = Signal(bool)             # overlay visibility changed
    global_hotkey = Signal(str)                # "ptt_down" | "ptt_up" | "overlay"

    # system events
    reminder_fired = Signal(object)            # reminder row dict
    notification = Signal(str, str)            # title, body
    activity_logged = Signal(object)           # activity row dict
    error = Signal(str)
    info = Signal(str)

    # settings
    settings_applied = Signal()
