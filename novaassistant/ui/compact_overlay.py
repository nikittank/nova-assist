"""Compact floating overlay — a dedicated small UI when Nova is shrunk.

Requirement #14: when the main Nova window is shrunk or minimized, the
overlay becomes a DEDICATED compact floating design — NOT a scaled-down
copy of the full overlay. It stays usable while the user works in other
apps.

Layout (vertical, ~72px wide × ~220px tall):
  ┌───────────────┐
  │     [N]       │   Nova identity (small)
  │  ● Listening  │   status dot + state label
  │  ▁▂▃▅▃▂▁     │   small waveform (live)
  │  Thinking…    │   current task (one line)
  │ ───────────── │
  │  [≡] [●] [□]  │   expand / mic / stop
  └───────────────┘

The compact overlay is independent of the full overlay's AIPanel — it has
its own lightweight widgets and paints itself. It is shown when the user
clicks the minimize button on the full overlay OR when the main window is
minimized and the overlay is enabled.
"""
from __future__ import annotations

import sys
from datetime import datetime

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from .. import icons, theme
from .widgets_common import Waveform

IS_WINDOWS = sys.platform == "win32"

COMPACT_W = 220
COMPACT_H = 220


class CompactOverlayPanel(QWidget):
    """The dedicated compact overlay UI (requirement #14).

    A separate design from the full AIPanel: smaller, vertical, focused on
    identity + live state + waveform + current task + three buttons
    (expand / mic / stop). Remains usable while the user works in other
    applications.
    """

    expand_clicked = Signal()
    mic_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._state = "IDLE"
        self._action = "Idle — standing by"
        self.setObjectName("CompactOverlay")
        theme.set_style(
            self,
            f"QWidget#CompactOverlay {{ background: rgba(5,5,7,0.96);"
            f" border: 1px solid {theme.BORDER_2}; border-radius: 14px; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(6)

        # ---- Nova identity row
        head = QHBoxLayout()
        head.setSpacing(6)
        avatar = QLabel("N")
        avatar.setFixedSize(22, 22)
        avatar.setAlignment(Qt.AlignCenter)
        theme.set_style(avatar,
            f"QLabel {{ background: #141416; border: 1px solid #26262b;"
            f" border-radius: 11px; color: {theme.WHITE}; font-size: 10px;"
            "font-weight: 700; }}")
        head.addWidget(avatar)
        name = QLabel("NOVA")
        theme.set_style(name,
            f"color: {theme.WHITE}; font-size: 11px; font-weight: 800;"
            f"font-family: {theme.FONT_MONO}; letter-spacing: 2px;"
            "border: none; background: transparent;")
        head.addWidget(name)
        head.addStretch(1)
        root.addLayout(head)

        # ---- status row (dot + state label)
        st = QHBoxLayout()
        st.setSpacing(6)
        self._status_dot = QLabel()
        self._status_dot.setFixedSize(7, 7)
        theme.set_style(self._status_dot,
            f"background: {theme.EMERALD}; border-radius: 3px; border: none;")
        st.addWidget(self._status_dot)
        self.status_lbl = QLabel("ONLINE")
        theme.set_style(self.status_lbl,
            f"color: {theme.EMERALD}; font-size: 10px; font-weight: 700;"
            f"font-family: {theme.FONT_MONO}; letter-spacing: 0.6px;"
            "border: none; background: transparent;")
        st.addWidget(self.status_lbl)
        st.addStretch(1)
        root.addLayout(st)

        # ---- small waveform (live)
        wave_holder = QWidget()
        theme.set_style(wave_holder, "background: transparent; border: none;")
        wl = QVBoxLayout(wave_holder)
        wl.setContentsMargins(0, 2, 0, 2)
        self.waveform = Waveform(bars=22, height=28)
        theme.set_style(self.waveform, "border: none;")
        wl.addWidget(self.waveform)
        root.addWidget(wave_holder)

        # ---- current task (one line)
        self.task_lbl = QLabel("Idle — standing by")
        self.task_lbl.setWordWrap(True)
        theme.set_style(self.task_lbl,
            f"color: {theme.TEXT_BRIGHT}; font-size: 10px;"
            f"font-family: {theme.FONT_MONO}; border: none;"
            "background: transparent;")
        root.addWidget(self.task_lbl, 1)

        # ---- separator
        from PySide6.QtWidgets import QFrame
        sep = QFrame()
        sep.setFixedHeight(1)
        theme.set_style(sep, f"background: {theme.BORDER}; border: none;")
        root.addWidget(sep)

        # ---- three buttons: expand / mic / stop
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self.btn_expand = self._btn("maximize", "Expand Nova")
        self.btn_expand.clicked.connect(self.expand_clicked)
        self.btn_mic = self._btn("mic", "Push-to-talk (Ctrl+Space)")
        self.btn_mic.clicked.connect(self.mic_clicked)
        self.btn_stop = self._btn("stop", "Stop / cancel")
        self.btn_stop.clicked.connect(self.stop_clicked)
        btns.addWidget(self.btn_expand)
        btns.addWidget(self.btn_mic)
        btns.addWidget(self.btn_stop)
        root.addLayout(btns)

        self.setFixedSize(COMPACT_W, COMPACT_H)

    # --------------------------------------------------------- helpers
    def _btn(self, icon_name: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setFixedSize(28, 28)
        b.setIcon(icons.icon(icon_name, theme.MUTED, 13))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        theme.set_style(b,
            "QPushButton { background: rgba(255,255,255,0.04);"
            " border: 1px solid " + theme.BORDER_2 + ";"
            "border-radius: 8px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.10); }")
        return b

    # ------------------------------------------------------------ state
    STATE_META = {
        "IDLE": ("ONLINE", theme.EMERALD, False),
        "LISTENING": ("LISTENING", theme.WHITE, True),
        "TRANSCRIBING": ("TRANSCRIBING", theme.EMERALD, True),
        "THINKING": ("THINKING", "#c4b5fd", True),
        "EXECUTING": ("EXECUTING", "#c4b5fd", True),
        "RESPONDING": ("RESPONDING", theme.WHITE, True),
        "SPEAKING": ("SPEAKING", theme.EMERALD, True),
        "DONE": ("DONE", theme.EMERALD, False),
    }

    def set_state(self, state: str) -> None:
        self._state = state
        label, color, busy = self.STATE_META.get(
            state, (state.title(), theme.MUTED, False))
        self.status_lbl.setText(label)
        theme.set_style(self.status_lbl,
            f"color: {color}; font-size: 10px; font-weight: 700;"
            f"font-family: {theme.FONT_MONO}; letter-spacing: 0.6px;"
            "border: none; background: transparent;")
        theme.set_style(self._status_dot,
            f"background: {color}; border-radius: 3px; border: none;")
        self.waveform.set_active(state == "LISTENING")
        # update the mic icon: stop icon while listening
        self.btn_mic.setIcon(icons.icon(
            "mic-off" if state == "LISTENING" else "mic",
            theme.RED_TEXT if state == "LISTENING" else theme.MUTED, 13))

    def set_action(self, text: str) -> None:
        self._action = text or "Idle — standing by"
        # one-line clamp
        line = self._action.splitlines()[0][:48] if self._action else ""
        self.task_lbl.setText(line or "Idle — standing by")

    def set_level(self, level: float) -> None:
        if self._state == "LISTENING":
            self.waveform.push_level(level)

    def set_online(self, online: bool) -> None:
        if online:
            self.set_state("IDLE")
        else:
            self.status_lbl.setText("OFFLINE")
            theme.set_style(self.status_lbl,
                f"color: {theme.RED}; font-size: 10px; font-weight: 700;"
                f"font-family: {theme.FONT_MONO}; letter-spacing: 0.6px;"
                "border: none; background: transparent;")
            theme.set_style(self._status_dot,
                f"background: {theme.RED}; border-radius: 3px; border: none;")

    def set_steps(self, steps: list) -> None:
        # show the active step's label as the current task
        active = next((s for s in steps if s.get("status") == "active"), None)
        if active:
            self.set_action(active.get("label", "Working…"))
        elif steps and all(s.get("status") == "done" for s in steps):
            self.set_action("Done")
        else:
            self.set_action("Idle — standing by")

    def add_stream(self, _who: str, _text: str, _ts: str = "") -> None:
        """Compact overlay does not render the conversation stream — the
        full overlay does. Here we just keep the current task updated."""
        pass

    def set_transcript(self, text: str) -> None:
        """Show the partial transcript as the current task while transcribing."""
        if text:
            self.set_action(text[:48])
