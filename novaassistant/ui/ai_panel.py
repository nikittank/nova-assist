"""AI Operating Layer panel — NOVA identity + live states (mockup-exact).

Shared design for the floating AI overlay. Shows: Nova identity with
online/offline status, the current state (LISTENING / THINKING / EXECUTING
/ SPEAKING), a live voice waveform, the user transcript, the AI response
stream, the current action, task progress with pipeline steps, and
microphone + stop/cancel controls with quick text input.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import icons, theme
from .widgets_common import (
    HfwRow, ScrollArea, Spinner, StepRow, Stepper, Waveform)


def _ts() -> str:
    return datetime.now().strftime("%H:%M")


class ModeSelector(QWidget):
    """UNDERSTAND / PLAN / EXECUTE / SIMPLIFY strip."""

    MODES = ["UNDERSTAND", "PLAN", "EXECUTE", "SIMPLIFY"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ModeSelector")
        theme.set_style(
            self,
            f"QWidget#ModeSelector {{ background: {theme.BLACK};"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self._labels: dict[str, QLabel] = {}
        for mode in self.MODES:
            lbl = QLabel(mode)
            lbl.setAlignment(Qt.AlignCenter)
            theme.set_style(
                lbl,
                f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
                "border: none; padding: 3px 0; border-radius: 5px; background: transparent;")
            lay.addWidget(lbl, 1)
            self._labels[mode] = lbl
        self.set_stage("UNDERSTAND")

    def set_stage(self, stage: str) -> None:
        stage = stage.upper() if stage else "IDLE"
        mapping = {
            "LISTENING": "UNDERSTAND", "THINKING": "PLAN",
            "EXECUTING": "EXECUTE", "RESPONDING": "SIMPLIFY",
            "SPEAKING": "SIMPLIFY", "IDLE": "",
        }
        target = mapping.get(stage, "")
        for mode, lbl in self._labels.items():
            active = mode == target
            theme.set_style(
                lbl,
                f"color: {theme.BLACK if active else theme.GHOST};"
                f"background: {theme.WHITE if active else 'transparent'};"
                f"font-size: 10px; font-family: {theme.FONT_MONO};"
                f"font-weight: {600 if active else 400}; border: none;"
                "padding: 3px 0; border-radius: 5px;")


class StreamBubble(HfwRow):
    """Chat bubble whose height tracks its wrapped text at any width."""

    def __init__(self, who: str, text: str, ts: str):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 8, 12, 8)
        col.setSpacing(3)
        is_user = who == "YOU"
        self.setObjectName("UserBubble" if is_user else "NovaBubble")
        if is_user:
            theme.set_style(
                self,
                f"QWidget#UserBubble {{ background: {theme.PANEL};"
                f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}")
        else:
            theme.set_style(
                self,
                f"QWidget#NovaBubble {{ background: #0e0e12;"
                f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}")
        head = QHBoxLayout()
        if is_user:
            head.addStretch(1)
        w = QLabel(who)
        theme.set_style(
            w,
            f"color: {theme.WHITE if not is_user else theme.MUTED}; font-size: 10px;"
            f"font-family: {theme.FONT_MONO}; font-weight: 700; border: none;"
            "background: transparent;")
        t = QLabel(ts or _ts())
        theme.set_style(t,
                        f"color: {theme.GHOST}; font-size: 10px; border: none;"
                        "background: transparent;")
        head.addWidget(w)
        head.addSpacing(4)
        head.addWidget(t)
        if is_user:
            head.addStretch(0)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # full-width label + TEXT alignment => deterministic wrap width
        body.setAlignment(Qt.AlignRight | Qt.AlignVCenter if is_user
                          else Qt.AlignLeft | Qt.AlignVCenter)
        theme.set_style(
            body,
            "QLabel { border: none; background: transparent;"
            f" color: {theme.TEXT_BRIGHT if is_user else theme.TEXT};"
            "font-size: 12px; }")
        self._body = body
        self._head_h = head.sizeHint().height()
        col.addLayout(head)
        col.addWidget(body, 1)
        self.min_natural_height = max(44, self.sizeHint().height())
        self.prime_height()

    def sync_height(self) -> None:
        """Deterministic: height = header + body.heightForWidth(body width)."""
        try:
            inner_w = max(60, self.width() - 24 - 2)   # margins + border
            h = (8 + self._head_h + 3
                 + self._body.heightForWidth(inner_w) + 8 + 2)
            self.setFixedHeight(max(self.min_natural_height, h))
        except Exception:
            super().sync_height()


class AIPanel(QWidget):
    """The complete AI operating layer surface."""

    mic_clicked = Signal()
    stop_clicked = Signal()
    input_submitted = Signal(str)
    settings_clicked = Signal()
    minimize_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.compact = compact
        self.setObjectName("AIPanel")
        theme.set_style(
            self,
            f"QWidget#AIPanel {{ background: #050507;"
            f" border-left: 1px solid {theme.BORDER}; }}")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        # ================================================================ header
        head = QHBoxLayout()
        head.setSpacing(8)
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap("zap", "#a1a1aa", 15))
        theme.set_style(icon_lbl, "background: transparent; border: none;")
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        title = QLabel("NOVA")
        theme.set_style(
            title,
            f"color: {theme.WHITE}; font-size: 14px; font-weight: 800;"
            f"font-family: {theme.FONT_MONO}; letter-spacing: 3px; border: none;"
            "background: transparent;")
        subtitle = QLabel("AI OPERATING LAYER")
        theme.set_style(
            subtitle,
            f"color: {theme.GHOST}; font-size: 9px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1.6px; border: none; background: transparent;")
        tcol.addWidget(title)
        tcol.addWidget(subtitle)
        head.addWidget(icon_lbl)
        head.addSpacing(2)
        head.addLayout(tcol)
        head.addStretch(1)

        # online / offline status pill
        self._online_dot = QLabel()
        self._online_dot.setFixedSize(7, 7)
        theme.set_style(self._online_dot, 
            f"background: {theme.EMERALD}; border-radius: 3px;")
        self._online_lbl = QLabel("ONLINE")
        theme.set_style(
            self._online_lbl,
            f"color: {theme.EMERALD}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "font-weight: 700; letter-spacing: 1px; border: none;"
            "background: transparent;")
        head.addWidget(self._online_dot)
        head.addWidget(self._online_lbl)

        self.btn_min = QPushButton()
        self.btn_min.setFixedSize(24, 24)
        self.btn_min.setIcon(icons.icon("chevron-right", theme.GHOST, 12))
        self.btn_min.setToolTip("Collapse layer")
        self.btn_min.setCursor(Qt.PointingHandCursor)
        theme.set_style(self.btn_min, 
            "QPushButton { background: transparent; border: none; border-radius: 6px; }"
            "QPushButton:hover { background: #1f1f23; }")
        self.btn_min.clicked.connect(self.minimize_clicked)
        head.addWidget(self.btn_min)
        self.btn_close = QPushButton()
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setIcon(icons.icon("close", theme.GHOST, 12))
        self.btn_close.setToolTip("Hide overlay")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        theme.set_style(self.btn_close, 
            "QPushButton { background: transparent; border: none; border-radius: 6px; }"
            "QPushButton:hover { background: #1f1f23; }")
        self.btn_close.clicked.connect(self.close_clicked)
        head.addWidget(self.btn_close)
        root.addLayout(head)

        line = QFrame()
        line.setFixedHeight(1)
        theme.set_style(line, f"background: {theme.BORDER}; border: none;")
        root.addWidget(line)

        # ============================================================ state card
        wave_box = QWidget()
        wave_box.setObjectName("AudioStreamBox")
        theme.set_style(
            wave_box,
            f"QWidget#AudioStreamBox {{ background: {theme.BLACK};"
            f" border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
        wb = QVBoxLayout(wave_box)
        wb.setContentsMargins(14, 10, 14, 12)
        wb.setSpacing(8)
        wrow = QHBoxLayout()
        cap = QLabel("AUDIO STREAM")
        theme.set_style(
            cap,
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; border: none; background: transparent;")
        self.status_lbl = QLabel("NOVA, ONLINE")
        theme.set_style(
            self.status_lbl,
            f"color: {theme.EMERALD}; font-size: 11px; font-family: {theme.FONT_MONO};"
            "font-weight: 700; letter-spacing: 0.6px; border: none;"
            "background: transparent;")
        wrow.addWidget(cap)
        wrow.addStretch(1)
        wrow.addWidget(self.status_lbl)
        wb.addLayout(wrow)
        self.waveform = Waveform(bars=32, height=46)
        theme.set_style(self.waveform, "border: none;")
        wb.addWidget(self.waveform)
        self.modes = ModeSelector()
        wb.addWidget(self.modes)
        root.addWidget(wave_box)

        # ============================================================== stream
        self.scroll = ScrollArea()
        stream_holder = QWidget()
        self.stream = QVBoxLayout(stream_holder)
        self.stream.setContentsMargins(0, 2, 4, 2)
        self.stream.setSpacing(8)
        self.stream.addStretch(1)
        self.scroll.setWidget(stream_holder)
        self.scroll.setMinimumHeight(120)
        root.addWidget(self.scroll, 1)

        # live STT transcript strip
        self.transcript = QLabel("")
        self.transcript.setWordWrap(True)
        theme.set_style(
            self.transcript,
            f"color: {theme.MUTED}; font-size: 11px; font-family: {theme.FONT_MONO};"
            "border: none; background: transparent;")
        self.transcript.hide()
        root.addWidget(self.transcript)

        # ====================================================== action + progress
        self.action_box = QWidget()
        self.action_box.setObjectName("ActionBox")
        theme.set_style(
            self.action_box,
            f"QWidget#ActionBox {{ background: {theme.BLACK};"
            f" border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
        ab = QVBoxLayout(self.action_box)
        ab.setContentsMargins(12, 9, 12, 10)
        ab.setSpacing(6)
        arow = QHBoxLayout()
        arow.setSpacing(8)
        acap = QLabel("CURRENT ACTION")
        theme.set_style(
            acap,
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; border: none; background: transparent;")
        self._action_spin_holder = QHBoxLayout()
        self._action_spin_holder.setContentsMargins(0, 0, 0, 0)
        arow.addWidget(acap)
        arow.addStretch(1)
        arow.addLayout(self._action_spin_holder)
        ab.addLayout(arow)
        self.action_lbl = QLabel("Idle — waiting for your command")
        self.action_lbl.setWordWrap(True)
        theme.set_style(
            self.action_lbl,
            f"color: {theme.TEXT_BRIGHT}; font-size: 11px;"
            f"font-family: {theme.FONT_MONO}; border: none; background: transparent;")
        ab.addWidget(self.action_lbl)

        prow = QHBoxLayout()
        prow.setSpacing(8)
        pcap = QLabel("TASK PROGRESS")
        theme.set_style(
            pcap,
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; border: none; background: transparent;")
        self.progress_lbl = QLabel("Ready")
        theme.set_style(
            self.progress_lbl,
            f"color: {theme.EMERALD}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "border: none; background: transparent;")
        prow.addWidget(pcap)
        prow.addStretch(1)
        prow.addWidget(self.progress_lbl)
        ab.addLayout(prow)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(5)
        ab.addWidget(self.progress)
        root.addWidget(self.action_box)

        # pipeline stepper
        self.stepper = Stepper()
        root.addWidget(self.stepper)

        # ============================================================ controls
        sep = QFrame()
        sep.setFixedHeight(1)
        theme.set_style(sep, f"background: {theme.BORDER}; border: none;")
        root.addWidget(sep)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        self.btn_settings = QPushButton()
        self.btn_settings.setFixedSize(30, 30)
        self.btn_settings.setIcon(icons.icon("settings", theme.GHOST, 14))
        self.btn_settings.setToolTip("Settings")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        theme.set_style(self.btn_settings, 
            "QPushButton { background: rgba(255,255,255,0.04); border: 1px solid "
            + theme.BORDER_2 + "; border-radius: 8px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.08); }")
        self.btn_settings.clicked.connect(self.settings_clicked)

        self.btn_stop = QPushButton()
        self.btn_stop.setFixedSize(48, 48)
        self.btn_stop.setIcon(icons.icon("stop", theme.BLACK, 18, 2))
        self.btn_stop.setToolTip("Stop / cancel")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        theme.set_style(self.btn_stop, 
            f"QPushButton {{ background: {theme.WHITE}; border: none; border-radius: 24px; }}"
            f"QPushButton:hover {{ background: #e5e5e5; }}")
        self.btn_stop.clicked.connect(self.stop_clicked)

        self.btn_mic = QPushButton()
        self.btn_mic.setFixedSize(30, 30)
        self.btn_mic.setIcon(icons.icon("mic", theme.MUTED, 15))
        self.btn_mic.setToolTip("Push to talk (Ctrl+Space)")
        self.btn_mic.setCursor(Qt.PointingHandCursor)
        theme.set_style(self.btn_mic, 
            "QPushButton { background: rgba(255,255,255,0.04); border: 1px solid "
            + theme.BORDER_2 + "; border-radius: 8px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.08); }")
        self.btn_mic.clicked.connect(self.mic_clicked)

        ctrl.addWidget(self.btn_settings)
        ctrl.addStretch(1)
        ctrl.addWidget(self.btn_stop)
        ctrl.addStretch(1)
        ctrl.addWidget(self.btn_mic)
        root.addLayout(ctrl)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type a message to Nova…")
        theme.set_style(self.input, 
            f"QLineEdit {{ background: {theme.BLACK}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 8px 12px; font-size: 12px;"
            f" color: {theme.TEXT_BRIGHT}; }}")
        self.input.returnPressed.connect(self._submit)
        send = QPushButton()
        send.setFixedSize(32, 32)
        send.setIcon(icons.icon("send", theme.BLACK, 15, 2.5))
        send.setToolTip("Send")
        send.setCursor(Qt.PointingHandCursor)
        theme.set_style(send, 
            f"QPushButton {{ background: {theme.WHITE}; border: none; border-radius: 8px; }}"
            f"QPushButton:hover {{ background: #e5e5e5; }}")
        send.clicked.connect(self._submit)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(send)
        root.addLayout(input_row)

        tag = QLabel("NOVA, ONLINE  •  QUIETER SMARTER FASTER")
        tag.setAlignment(Qt.AlignCenter)
        theme.set_style(
            tag,
            f"color: {theme.GHOST}; font-size: 9px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1.4px; border: none; background: transparent;")
        root.addWidget(tag)

    def _submit(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.input_submitted.emit(text)

    # ------------------------------------------------------------ state
    def set_online(self, online: bool) -> None:
        dot_color = theme.EMERALD if online else theme.RED
        text = "ONLINE" if online else "OFFLINE"
        self._online_lbl.setText(text)
        theme.set_style(
            self._online_lbl,
            f"color: {dot_color}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "font-weight: 700; letter-spacing: 1px; border: none;"
            "background: transparent;")
        theme.set_style(self._online_dot, 
            f"background: {dot_color}; border-radius: 3px;")

    def set_state(self, state: str) -> None:
        labels = {
            "IDLE": ("NOVA, ONLINE", theme.EMERALD, False),
            "LISTENING": ("LISTENING", theme.WHITE, True),
            "THINKING": ("THINKING", "#c4b5fd", True),
            "EXECUTING": ("EXECUTING", "#c4b5fd", True),
            "RESPONDING": ("RESPONDING", theme.WHITE, True),
            "SPEAKING": ("SPEAKING", theme.EMERALD, True),
        }
        text, color, active = labels.get(state, (state.title(), theme.EMERALD, False))
        self.status_lbl.setText(text)
        theme.set_style(
            self.status_lbl,
            f"color: {color}; font-size: 11px; font-family: {theme.FONT_MONO};"
            "font-weight: 700; letter-spacing: 0.6px; border: none;"
            "background: transparent;")
        self.waveform.set_active(state == "LISTENING")
        self.modes.set_stage(state)
        self.btn_mic.setIcon(icons.icon(
            "mic-off" if state == "LISTENING" else "mic",
            theme.RED_TEXT if state == "LISTENING" else theme.MUTED, 15))
        if state == "IDLE":
            self.set_action("Idle — waiting for your command", running=False)
            self.progress.setValue(0)
            self.progress_lbl.setText("Ready")

    def set_action(self, text: str, running: bool = False) -> None:
        self.action_lbl.setText(text or "—")
        # spinner lifecycle
        if running and getattr(self, "_action_spin", None) is None:
            self._action_spin = Spinner(11, theme.WHITE)
            self._action_spin_holder.addWidget(self._action_spin)
        elif not running and getattr(self, "_action_spin", None) is not None:
            self._action_spin.deleteLater()
            self._action_spin = None

    _action_spin = None

    def set_level(self, level: float) -> None:
        if self.status_lbl.text() == "LISTENING":
            self.waveform.push_level(level)

    def add_stream(self, who: str, text: str, ts: str = "") -> None:
        bubble = StreamBubble(who, text, ts)
        self.stream.insertWidget(self.stream.count() - 1, bubble)
        # height depends on final wrap width — re-sync as it settles
        for delay in (0, 40, 140):
            QTimer.singleShot(delay, bubble.sync_height)
        bar = self.scroll.verticalScrollBar()
        QTimer.singleShot(10, lambda: bar.setValue(bar.maximum()))

    def set_transcript(self, text: str) -> None:
        self.transcript.setText(f'"{text}"' if text else "")
        self.transcript.setVisible(bool(text))

    def set_steps(self, steps: list) -> None:
        self.stepper.set_steps(steps)
        total = len(steps)
        done = sum(1 for s in steps if s.get("status") == "done")
        active = next((s for s in steps if s.get("status") == "active"), None)
        if total:
            pct = int(round(100.0 * done / total))
            self.progress.setValue(pct)
            self.progress_lbl.setText(
                f"Step {done}/{total}" + (" • running" if active else ""))
        else:
            self.progress.setValue(0)
            self.progress_lbl.setText("Ready")
        if active:
            self.set_action(active.get("label", "Working…"), running=True)
        elif total and done >= total:
            self.set_action("All steps complete", running=False)
