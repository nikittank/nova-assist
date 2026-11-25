"""Conversation page — chat stream + input console (mockup-exact)."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import icons, theme
from .widgets_common import (
    MiniWave, ScrollArea, TagPill, icon_button, primary_button, spacer,
    style_scoped,
)


# ------------------------------------------------------------------- helpers
def _state_meta(state: str) -> tuple[str, str, bool]:
    """(label, color, busy) for a pipeline state."""
    return {
        "IDLE": ("Idle", theme.MUTED, False),
        "LISTENING": ("Listening", theme.EMERALD, True),
        "TRANSCRIBING": ("Transcribing", theme.EMERALD, True),
        "THINKING": ("Thinking", "#c4b5fd", True),
        "EXECUTING": ("Executing", "#c4b5fd", True),
        "RESPONDING": ("Responding", theme.WHITE, True),
        "SPEAKING": ("Speaking", theme.EMERALD, True),
        "DONE": ("Done", theme.EMERALD, False),
    }.get(state, (state.title(), theme.MUTED, False))


class StatePulse(QWidget):
    """Animated pulsing dot that reflects the current pipeline state.

    Subtle (not distracting): a single emerald dot at idle, a brighter
    pulsing dot while busy, and a tiny ring while speaking. Used in the
    conversation header and in message bubbles.
    """

    def __init__(self, parent=None, size: int = 10):
        super().__init__(parent)
        self._size = size
        self._state = "IDLE"
        self._t = 0
        self.setFixedSize(size + 4, size + 4)
        t = QTimer(self)
        t.setInterval(60)
        t.timeout.connect(self._tick)
        t.start()

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def _tick(self) -> None:
        self._t += 1
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        label, color, busy = _state_meta(self._state)
        # base dot
        cx = cy = self.width() // 2
        r = self._size // 2
        if busy:
            # outer pulse
            phase = (self._t % 24) / 24.0
            ring = int(r + 4 * (1.0 - phase))
            ring_alpha = int(120 * (1.0 - phase))
            ring_color = QColor(color)
            ring_color.setAlpha(max(0, ring_alpha))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ring_color, 1.4))
            p.drawEllipse(cx - ring, cy - ring, ring * 2, ring * 2)
        # core
        core = QColor(color)
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)


class StatusDotCluster(QWidget):
    """Compact three-dot service status indicator (LLM / STT / TTS).

    Each dot is colored: emerald=connected, amber=disabled, red=error.
    Click opens a popover with the full per-service state — long
    provider/model text never lives in the header (requirement #5).
    """
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = {"llm": "error", "stt": "error", "tts": "error"}
        self._labels = {"llm": "LLM", "stt": "STT", "tts": "TTS"}
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(64, 22)
        self._t = 0
        t = QTimer(self)
        t.setInterval(80)
        t.timeout.connect(self._tick)
        t.start()

    def set_states(self, llm: str, stt: str, tts: str) -> None:
        self._states = {"llm": llm, "stt": stt, "tts": tts}
        self.update()

    def _tick(self) -> None:
        self._t += 1
        self.update()

    def _color_for(self, state: str) -> QColor:
        if state == "connected":
            return QColor(theme.EMERALD)
        if state == "disabled":
            return QColor("#F59E0B")
        return QColor(theme.RED)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        order = ["llm", "stt", "tts"]
        gap = 6
        dot_r = 5
        any_busy = any(self._states[k] == "connected" for k in order)
        for i, key in enumerate(order):
            color = self._color_for(self._states[key])
            cx = 8 + i * (dot_r * 2 + gap + 4)
            cy = self.height() // 2
            if any_busy and self._states[key] == "connected":
                # subtle pulse on connected dots when the pipeline is alive
                phase = ((self._t + i * 7) % 30) / 30.0
                pulse_r = int(dot_r + 3 * (1.0 - phase))
                pulse_alpha = int(90 * (1.0 - phase))
                pc = QColor(color)
                pc.setAlpha(max(0, pulse_alpha))
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(pc, 1.2))
                p.drawEllipse(cx - pulse_r, cy - pulse_r,
                              pulse_r * 2, pulse_r * 2)
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2)


class ServiceStatusPopover(QFrame):
    """Popover card that opens under the three-dot cluster.

    Shows one compact row per service with state, label and provider/model.
    Long text lives here only — never in the header itself.
    """
    open_settings = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        theme.set_style(self,
            f"background: {theme.PANEL_2}; border: 1px solid {theme.BORDER_2};"
            "border-radius: 12px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("API Status")
        theme.set_style(title,
            f"color: {theme.WHITE}; font-size: 12px; font-weight: 600;"
            "border: none; background: transparent;")
        head.addWidget(title)
        head.addStretch(1)
        diag = QPushButton("Diagnostics")
        diag.setProperty("variant", "chip")
        diag.setCursor(Qt.PointingHandCursor)
        diag.clicked.connect(self.open_settings)
        head.addWidget(diag)
        lay.addLayout(head)
        line = QFrame()
        line.setFixedHeight(1)
        theme.set_style(line, f"background: {theme.BORDER}; border: none;")
        lay.addWidget(line)
        self._rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}
        for key, name in (("llm", "LLM"), ("stt", "STT"), ("tts", "TTS")):
            row = QHBoxLayout()
            row.setSpacing(10)
            dot = QLabel()
            dot.setFixedSize(8, 8)
            theme.set_style(dot,
                f"background: {theme.GHOST}; border-radius: 4px;"
                "border: none;")
            cap = QLabel(name)
            theme.set_style(cap,
                f"color: {theme.MUTED}; font-size: 10px;"
                f"font-family: {theme.FONT_MONO}; letter-spacing: 1px;"
                "border: none; background: transparent;")
            val = QLabel("—")
            theme.set_style(val,
                f"color: {theme.TEXT_BRIGHT}; font-size: 11px;"
                f"font-family: {theme.FONT_MONO}; border: none;"
                "background: transparent;")
            row.addWidget(dot)
            row.addWidget(cap)
            row.addStretch(1)
            row.addWidget(val, 1)
            lay.addLayout(row)
            self._rows[key] = (dot, cap, val)

    def refresh(self) -> None:
        status = self.ctx.config.services_status()
        for key, (dot, cap, val) in self._rows.items():
            info = status[key]
            state = info["state"]
            if state == "connected":
                color = theme.EMERALD
            elif state == "disabled":
                color = "#F59E0B"
            else:
                color = theme.RED
            theme.set_style(dot,
                f"background: {color}; border-radius: 4px; border: none;")
            val.setText(f"{info['label']}")
            theme.set_style(val,
                f"color: {color if state != 'connected' else theme.TEXT_BRIGHT};"
                f"font-size: 11px; font-family: {theme.FONT_MONO};"
                "border: none; background: transparent;")


class StatTile(QWidget):
    def __init__(self, label: str, value: str = "", mono: bool = True,
                 value_color: str = theme.WHITE, dot: bool = False, parent=None):
        super().__init__(parent)
        style_scoped(self, "StatTile",
                     f"background: {theme.PANEL_2}; border: 1px solid {theme.BORDER};"
                     "border-radius: 8px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(2)
        cap = QLabel(label.upper())
        theme.set_style(cap,
            f"color: {theme.MUTED}; font-size: 10px; font-weight: 600;"
            "letter-spacing: 1px; border: none; background: transparent;")
        row = QHBoxLayout()
        row.setSpacing(6)
        self._dot = QLabel()
        self._dot.setFixedSize(6, 6)
        theme.set_style(self._dot, f"background: {theme.EMERALD_500}; border-radius: 3px; border: none;")
        self._dot.hide()
        row.addWidget(self._dot)
        self._value = QLabel(value)
        theme.set_style(self._value,
            f"color: {value_color}; font-size: 12px; font-weight: 500;"
            f"{'font-family: ' + theme.FONT_MONO + ';' if mono else ''} border: none; background: transparent;")
        row.addWidget(self._value)
        row.addStretch(1)
        lay.addWidget(cap)
        lay.addLayout(row)

    def set_value(self, value: str, color: str | None = None, dot_ok: bool | None = None) -> None:
        self._value.setText(value)
        if color:
            theme.set_style(self._value,
                f"color: {color}; font-size: 12px; font-weight: 500;"
                f"font-family: {theme.FONT_MONO}; border: none; background: transparent;")
        if dot_ok is not None:
            self._dot.setVisible(dot_ok)
            theme.set_style(self._dot,
                f"background: {theme.EMERALD_500 if dot_ok else theme.RED};"
                "border-radius: 3px; border: none;")


class BubbleLabel(QLabel):
    """Word-wrapped bubble that keeps its height in sync with width
    (plain QLabel + wordWrap clips text inside nested layouts)."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setWordWrap(True)

    def resizeEvent(self, event) -> None:
        w = self.width()
        if w > 24:
            self.setMinimumHeight(self.heightForWidth(w))
        super().resizeEvent(event)


class ChatBubble(QWidget):
    """One message row (avatar + header + bubble) per mockup geometry."""

    def __init__(self, role: str, text: str, ts: str, parent=None):
        super().__init__(parent)
        self.role = role
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        is_user = role == "user"
        maxw = 1060

        av = QLabel("N")
        av.setFixedSize(32, 32)
        av.setAlignment(Qt.AlignCenter)
        if is_user:
            av.setPixmap(icons.pixmap("user", "#a1a1aa", 16, 2))
        else:
            theme.set_style(av,
                "QLabel { background: #141416; border: 1px solid #26262b;"
                f" border-radius: 16px; color: {theme.WHITE}; font-size: 12px;"
                "font-weight: 700; }")

        if not is_user:
            lay.addWidget(av, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        if is_user:
            head.addStretch(1)
            time_lbl = QLabel(ts)
            theme.set_style(time_lbl, f"color: {theme.GHOST}; font-size: 10px;")
            name = QLabel("You")
            theme.set_style(name, f"color: #d4d4d8; font-size: 12px; font-weight: 500;")
            head.addWidget(time_lbl)
            head.addWidget(name)
        else:
            name = QLabel("Nova")
            theme.set_style(name, f"color: {theme.WHITE}; font-size: 12px; font-weight: 500;")
            time_lbl = QLabel(ts)
            theme.set_style(time_lbl, f"color: {theme.GHOST}; font-size: 10px;")
            head.addWidget(name)
            head.addWidget(time_lbl)

        body = BubbleLabel(text)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Give the conversation column real width so short lines do not force
        # the bubble into a narrow card.  The maximum keeps long messages
        # readable and matches the HTML mockup's max-w-3xl treatment.
        body.setMinimumWidth(360 if is_user else 480)
        body.setMaximumWidth(maxw - 24)
        self.body_label = body
        if is_user:
            theme.set_style(body,
                f"background: {theme.PANEL_ACTIVE}; color: {theme.WHITE};"
                f"border: 1px solid {theme.BORDER_3}; border-radius: 12px;"
                f"border-top-right-radius: 4px; padding: 11px 17px; font-size: 14px;")
        else:
            theme.set_style(body,
                f"background: {theme.PANEL_2}; color: #e5e5e5;"
                f"border: 1px solid {theme.BORDER}; border-radius: 12px;"
                f"border-top-left-radius: 4px; padding: 14px;"
                "font-size: 14px; line-height: 1.6;")
        col.addLayout(head)
        col.addWidget(body if is_user else body, 0,
                      Qt.AlignRight if is_user else Qt.AlignLeft)

        holder = QWidget()
        hlay = QHBoxLayout(holder)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.addLayout(col, 1)
        lay.addWidget(holder, 1)

        if is_user:
            lay.addWidget(av, 0, Qt.AlignTop)

        # subtle fade-in animation (requirement #13)
        self._fade = QPropertyAnimation(self, b"windowOpacity")
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        # windowOpacity only works on top-level windows; use a simple
        # graphics-effect-free visibility fade via setVisible + stylesheet


class ErrorCard(QWidget):
    """Friendly error banner. Technical traceback is COLLAPSED by default —
    the user can open it explicitly (or copy it); full details always go to
    the Activity log instead of being spammed into the chat.

    Requirement #1: do not show raw errors inside the main conversation
    workspace — only a friendly one-line banner with an expandable Details
    section.
    """

    def __init__(self, title: str, detail: str, traceback_text: str = "", parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel("Nova")
        theme.set_style(name, f"color: {theme.WHITE}; font-size: 12px; font-weight: 500;")
        badge = TagPill("Error", color=theme.RED_TEXT,
                        bg="rgba(80,7,10,0.6)", border="rgba(127,29,29,0.5)")
        head.addWidget(name)
        head.addWidget(badge)
        head.addStretch(1)
        col.addLayout(head)

        banner = QWidget()
        style_scoped(banner, "ErrorBanner",
                     f"background: {theme.ERROR_BG}; border: 1px solid {theme.ERROR_BORDER};"
                     "border-radius: 12px;")
        bl = QHBoxLayout(banner)
        bl.setContentsMargins(14, 12, 12, 12)
        bl.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("alert", theme.RED_TEXT, 16, 2))
        theme.set_style(ic, "border: none;")
        txt = QWidget()
        theme.set_style(txt, "border: none;")
        tl = QVBoxLayout(txt)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(3)
        h = QLabel(title)
        h.setWordWrap(True)
        theme.set_style(h, f"color: {theme.RED_SOFT}; font-size: 12px; font-weight: 600; border: none;")
        first_line = (detail or "").strip().splitlines()[0] if detail.strip() else \
            "The operation hit a problem. Full details are in Activity."
        p = QLabel(first_line[:220])
        p.setWordWrap(True)
        theme.set_style(p, f"color: {theme.MUTED}; font-size: 11px; border: none;")
        tl.addWidget(h)
        tl.addWidget(p)
        bl.addWidget(ic)
        bl.addWidget(txt, 1)

        btn_col = QVBoxLayout()
        btn_col.setAlignment(Qt.AlignTop)
        self.details_btn = QPushButton(" Details")
        self.details_btn.setProperty("variant", "ghost")
        self.details_btn.setIcon(icons.icon("chevron-down", theme.MUTED, 12))
        self.details_btn.setCursor(Qt.PointingHandCursor)
        theme.set_style(self.details_btn,
            "QPushButton { padding: 5px 10px; font-size: 11px; }")
        self.details_btn.clicked.connect(self._toggle_details)
        btn_col.addWidget(self.details_btn)
        copy_btn = QPushButton(" Copy")
        copy_btn.setProperty("variant", "ghost")
        copy_btn.setIcon(icons.icon("copy", theme.GHOST, 12))
        copy_btn.setCursor(Qt.PointingHandCursor)
        theme.set_style(copy_btn,
            "QPushButton { padding: 5px 10px; font-size: 11px; }")
        copy_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(traceback_text or detail))
        btn_col.addWidget(copy_btn)
        bl.addLayout(btn_col)
        col.addWidget(banner)

        # technical view — hidden until explicitly opened
        self.details = QWidget()
        style_scoped(self.details, "ErrorCode",
                     f"background: {theme.CODE_BG}; border: 1px solid {theme.CODE_BORDER};"
                     "border-radius: 12px;")
        cl = QVBoxLayout(self.details)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(6)
        code_head = QLabel("Traceback (most recent call last):")
        theme.set_style(code_head,
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO}; border: none;")
        cl.addWidget(code_head)
        body = QLabel((traceback_text or detail)[:1200])
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        theme.set_style(body,
            f"color: #d4d4d8; font-size: 11px; font-family: {theme.FONT_MONO}; border: none;")
        cl.addWidget(body)
        self.details.hide()
        col.addWidget(self.details)
        self._open = False

    def _toggle_details(self) -> None:
        self._open = not self._open
        self.details.setVisible(self._open)
        self.details_btn.setIcon(icons.icon(
            "chevron-up" if self._open else "chevron-down", theme.MUTED, 12))
        self.details_btn.setText(" Hide" if self._open else " Details")


class LiveStateStrip(QWidget):
    """Subtle strip shown above the input console while the pipeline is
    active: 'Listening…' / 'Transcribing…' / 'Thinking…' / 'Executing…' /
    'Speaking…'.  Animates a thin progress bar to feel alive (req #13)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self.setFixedHeight(26)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 0, 24, 0)
        lay.setSpacing(8)
        self.pulse = StatePulse(self, size=8)
        lay.addWidget(self.pulse)
        self.label = QLabel("Idle")
        theme.set_style(self.label,
            f"color: {theme.MUTED}; font-size: 11px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 0.6px; border: none; background: transparent;")
        lay.addWidget(self.label)
        lay.addStretch(1)
        # indeterminate progress hint
        self.bar = QFrame()
        self.bar.setFixedHeight(2)
        self.bar.setMinimumWidth(60)
        theme.set_style(self.bar, f"background: {theme.BORDER}; border: none;")
        lay.addWidget(self.bar, 1)
        self._t = 0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)
        self._state = "IDLE"

    def _tick(self) -> None:
        self._t += 1
        # animate the bar with a moving highlight
        w = self.bar.width()
        if w <= 0:
            return
        pos = (self._t * 3) % (w + 60) - 30
        theme.set_style(self.bar,
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            f" stop:0 {theme.BORDER}, stop:{max(0,min(1,(pos+30)/(w+60))):.3f} {theme.EMERALD},"
            f" stop:{max(0,min(1,(pos+30+20)/(w+60))):.3f} {theme.EMERALD},"
            f" stop:1 {theme.BORDER}); border: none;")

    def set_state(self, state: str) -> None:
        self._state = state
        label, color, busy = _state_meta(state)
        self.label.setText(label + "…")
        theme.set_style(self.label,
            f"color: {color}; font-size: 11px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 0.6px; border: none; background: transparent;")
        self.pulse.set_state(state)
        if busy:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
            theme.set_style(self.bar, f"background: {theme.BORDER}; border: none;")
        self.setVisible(state != "IDLE")


class ConversationPage(QWidget):
    request_llm = Signal(str)          # text submitted by user

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ------------------------------------------------- workspace header
        header = QWidget()
        style_scoped(header, "ConvHeader",
                     f"background: {theme.BLACK}; border-bottom: 1px solid #141414;")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(24, 16, 24, 16)
        hl.setSpacing(12)
        row = QHBoxLayout()
        title = QLabel("Workspace")
        theme.set_style(title, f"color: {theme.WHITE}; font-size: 17px; font-weight: 600;")
        row.addWidget(title)
        row.addStretch(1)

        # three-dot status cluster + popover (requirement #5)
        self.status_cluster = StatusDotCluster()
        self.status_cluster.clicked.connect(self._toggle_status_popover)
        row.addWidget(self.status_cluster)

        # mic / listening pulse
        self.header_pulse = StatePulse(size=8)
        row.addWidget(self.header_pulse)

        hl.addLayout(row)

        grid_holder = QWidget()
        # Use a stable single row for the five compact status cards.  The
        # previous custom flow layout could calculate an oversized minimum
        # height and, on some Windows scaling settings, paint the cards outside
        # the visible header.
        grid_holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        grid_holder.setFixedHeight(58)
        self.tiles_flow = QHBoxLayout(grid_holder)
        self.tiles_flow.setContentsMargins(0, 0, 0, 0)
        self.tiles_flow.setSpacing(10)
        self.tile_status = StatTile("Assistant", "Idle", dot=True)
        self.tile_groq = StatTile("Groq API", "Not configured", dot=False)
        self.tile_stt = StatTile("STT Engine", "Not configured", dot=False)
        self.tile_model = StatTile("Model", "—")
        self.tile_latency = StatTile("Latency", "—", value_color=theme.EMERALD)
        for tile in (self.tile_status, self.tile_groq, self.tile_stt,
                     self.tile_model, self.tile_latency):
            tile.setMinimumWidth(148)
            # Match the reference grid: five equal telemetry columns spread
            # across the header instead of clustering at the left edge.
            self.tiles_flow.addWidget(tile, 1)
        hl.addWidget(grid_holder)
        root.addWidget(header)

        # status popover (created lazily, shown on click)
        self._popover: ServiceStatusPopover | None = None

        # ------------------------------------------------------ chat scroll
        self.scroll = ScrollArea()
        self.scroll.setWidgetResizable(True)
        chat_holder = QWidget()
        self.chat_lay = QVBoxLayout(chat_holder)
        self.chat_lay.setContentsMargins(32, 24, 32, 24)
        self.chat_lay.setSpacing(24)
        self.chat_lay.addStretch(1)
        self.scroll.setWidget(chat_holder)
        root.addWidget(self.scroll, 1)
        self._bubbles = 0
        self._bubble_labels: list[BubbleLabel] = []

        # --------------------------------------- live state strip (req #13)
        self.state_strip = LiveStateStrip()
        root.addWidget(self.state_strip)

        # ------------------------------------------------------ input footer
        footer = QWidget()
        style_scoped(footer, "ConvFooter",
                     f"background: transparent; border: none;")
        fl = QVBoxLayout(footer)
        fl.setContentsMargins(24, 14, 24, 22)
        fl.setSpacing(12)

        box_holder = QHBoxLayout()
        box = QWidget()
        box.setObjectName("InputConsole")
        theme.set_style(box,
            f"QWidget#InputConsole {{ background: {theme.PANEL_2};"
            f" border: 1px solid {theme.BORDER}; border-radius: 16px; }}")
        box.setMaximumWidth(960)
        box.setMinimumWidth(520)
        box.setMinimumHeight(56)
        bl = QHBoxLayout(box)
        bl.setContentsMargins(14, 10, 10, 10)
        bl.setSpacing(6)
        attach = icon_button("attach", "Attach file")
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask Nova anything or press mic to talk…")
        theme.set_style(self.input,
            f"QLineEdit {{ background: transparent; border: none; font-size: 14px;"
            f" color: {theme.WHITE}; padding: 6px; }}")
        self.input.returnPressed.connect(self._send)
        self.input.installEventFilter(self)
        self.mic_btn = icon_button("mic", "Hold mic (or Ctrl+Space) for push-to-talk", 16)
        self.mic_btn.clicked.connect(self._on_mic_clicked)
        self.send_btn = primary_button("", "send")
        self.send_btn.setFixedSize(40, 40)
        self.send_btn.setToolTip("Send message (Ctrl+Enter)")
        self.send_btn.clicked.connect(self._send)
        wave = MiniWave()
        bl.addWidget(attach)
        bl.addWidget(self.input, 1)
        bl.addWidget(wave)
        bl.addWidget(self.mic_btn)
        bl.addWidget(self.send_btn)
        # Center the composer in the workspace instead of pushing it to the
        # far right when the window is wide.
        box_holder.addStretch(1)
        box_holder.addWidget(box, 1)
        box_holder.addStretch(1)
        fl.addLayout(box_holder)

        hints_holder = QWidget()
        # The mockup keeps shortcuts on the left and suggestion chips in one
        # compact row on the right.  A normal horizontal layout avoids the
        # oversized two-column buttons produced by wrapping FlowLayout here.
        self.hints_flow = QHBoxLayout(hints_holder)
        self.hints_flow.setContentsMargins(0, 0, 0, 0)
        self.hints_flow.setSpacing(8)
        hint = QLabel("Hold mic (or Ctrl+Space) for push-to-talk   •   Ctrl+Enter sends")
        theme.set_style(hint, f"color: {theme.GHOST}; font-size: 11px;")
        self.hints_flow.addWidget(hint)
        self.hints_flow.addStretch(1)
        try_lbl = QLabel("Try:")
        theme.set_style(try_lbl, f"color: {theme.GHOST}; font-size: 11px;")
        self.hints_flow.addWidget(try_lbl)
        for phrase in ("Open Spotify", "Take a note that…", "Remind me at 6 PM",
                       "What's on my plate?"):
            chip = QPushButton(f'"{phrase}"')
            chip.setProperty("variant", "chip")
            chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda _=False, t=phrase: self._send_chip(t))
            self.hints_flow.addWidget(chip)
        fl.addWidget(hints_holder)
        root.addWidget(footer)

        self._error_detail: tuple[str, str] = ("", "")

        # one font everywhere: same typeface as the sidebar/technical UI
        theme.apply_unified_font(self)

    # ------------------------------------------------- status popover
    def _toggle_status_popover(self) -> None:
        if self._popover is None:
            self._popover = ServiceStatusPopover(self.ctx, parent=self)
            self._popover.open_settings.connect(self._goto_settings)
        self._popover.refresh()
        # position below the cluster, right-aligned
        gp = self.status_cluster.mapToGlobal(
            self.status_cluster.rect().bottomRight())
        self._popover.move(gp.x() - self._popover.sizeHint().width(),
                           gp.y() + 4)
        self._popover.show()
        self._popover.raise_()

    def _goto_settings(self) -> None:
        if self._popover is not None:
            self._popover.hide()
        from .main_window import MainWindow  # noqa: F401
        win = self.window()
        if hasattr(win, "navigate"):
            win.navigate("settings")

    # ------------------------------------------------------------- mic
    def _on_mic_clicked(self) -> None:
        orch = self.ctx.orchestrator
        mode = orch.mic_mode
        if mode == "push_to_talk":
            # toggle: click = press+release (one-shot)
            # for true hold behavior the global Ctrl+Space hotkey is used
            if orch.is_listening:
                orch.push_to_talk_release()
            else:
                orch.push_to_talk_press()
        else:
            orch.toggle_listening()

    # ------------------------------------------------------------- send
    def eventFilter(self, obj, event) -> bool:
        from ..shortcuts import event_matches
        if obj is self.input and event.type() == event.Type.KeyPress:
            if event_matches(event, "Ctrl+Enter"):
                self._send()
                return True
        return super().eventFilter(obj, event)

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.request_llm.emit(text)

    def _send_chip(self, phrase: str) -> None:
        self.request_llm.emit(phrase.rstrip("…"))

    # -------------------------------------------------------- rendering
    def add_message(self, role: str, text: str, ts: str = "Just now") -> None:
        bubble = ChatBubble(role, text, ts)
        self.chat_lay.insertWidget(self.chat_lay.count() - 1, bubble)
        if bubble.body_label is not None:
            self._bubble_labels.append(bubble.body_label)
            self._apply_bubble_widths()
        self._bubbles += 1
        if self._bubbles > 120:
            first = self.chat_lay.itemAt(0)
            if first and first.widget():
                first.widget().deleteLater()
            self._bubbles -= 1
        QTimer.singleShot(20, self._scroll_bottom)

    def _apply_bubble_widths(self) -> None:
        """Cap bubble width to the live viewport so text never clips."""
        avail = max(260, self.scroll.viewport().width() - 140)
        for lbl in self._bubble_labels:
            lbl.setMaximumWidth(min(678, avail))

    def resizeEvent(self, event) -> None:
        self._apply_bubble_widths()
        super().resizeEvent(event)

    def add_error(self, title: str, detail: str, traceback_text: str = "") -> None:
        self.chat_lay.insertWidget(self.chat_lay.count() - 1,
                                   ErrorCard(title, detail, traceback_text))
        self._bubbles += 1
        QTimer.singleShot(20, self._scroll_bottom)

    def _scroll_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # ----------------------------------------------------------- status
    def set_state(self, state: str) -> None:
        label, color, busy = _state_meta(state)
        self.tile_status.set_value(label,
                                   color=theme.WHITE if not busy else color,
                                   dot_ok=not busy)
        self.state_strip.set_state(state)
        self.header_pulse.set_state(state)
        if state == "LISTENING":
            self.mic_btn.setIcon(icons.icon("mic-off", theme.RED_TEXT, 16))
            self.mic_btn.setToolTip("Stop listening (Ctrl+Space)")
        else:
            self.mic_btn.setIcon(icons.icon("mic", theme.MUTED, 16))
            self.mic_btn.setToolTip("Push-to-talk (Ctrl+Space)")

    def set_transcript_hint(self, text: str) -> None:
        if text:
            self.input.setPlaceholderText(text)
        else:
            self.input.setPlaceholderText("Ask Nova anything or press mic to talk…")

    def refresh_provider(self) -> None:
        stack = self.ctx.config.active_stack()
        self.tile_groq.set_value(
            "Connected" if stack["llm_key"] else "Not configured",
            dot_ok=bool(stack["llm_key"]))
        if stack["stt_provider"] == "Groq":
            ok = bool(stack["stt_key"])
            self.tile_stt.set_value(f"Groq • {stack['stt_model']}" if ok else "Not configured",
                                    dot_ok=ok)
        else:
            ok = bool(stack["stt_key"])
            self.tile_stt.set_value(f"Deepgram • {stack['stt_model']}" if ok else "Not configured",
                                    dot_ok=ok)
        self.tile_model.set_value(stack["llm_model"])
        # refresh the three-dot cluster too
        status = self.ctx.config.services_status()
        self.status_cluster.set_states(
            status["llm"]["state"],
            status["stt"]["state"],
            status["tts"]["state"],
        )
        # long values changed the tiles' hints — force the flow to re-measure
        self.tiles_flow.invalidate()

    def set_latency(self, ms: int) -> None:
        color = theme.EMERALD if ms < 1000 else ("#F59E0B" if ms < 3000 else theme.RED_TEXT)
        self.tile_latency.set_value(f"{ms} ms", color=color)

    def on_shown(self) -> None:
        self.refresh_provider()
        self.input.setFocus()
