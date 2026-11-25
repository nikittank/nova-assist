"""AI Overlay — frameless always-on-top AI Operating Layer window.

Stays above Chrome / VS Code / any app while enabled (Qt WindowStaysOnTopHint
+ Windows HWND_TOPMOST enforcement). Draggable, non-blocking, lightweight.

The panel inside shows the full operational layer: Nova identity with
online/offline status, listening/thinking/executing/speaking states, live
waveform, transcript, response stream, current action, task progress and
mic/stop controls. Also hosts widgets pinned in overlay (compact mirrors)
in a collapsible strip.

When minimized, the overlay switches to a DEDICATED compact floating UI
(CompactOverlayPanel) — NOT a scaled-down copy of the full overlay
(requirement #14). The compact overlay keeps the same signals wired so
state / waveform / actions stay live while you work in other apps.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .. import theme
from .ai_panel import AIPanel
from .compact_overlay import COMPACT_H, COMPACT_W, CompactOverlayPanel
from .widgets import WidgetBase

IS_WINDOWS = sys.platform == "win32"

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

NORMAL_H = 760


class OverlayWindow(QWidget):
    """The right-side operational overlay."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("Nova Overlay")
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(int(ctx.config.get("overlay.width", 400)), NORMAL_H)

        theme.set_style(
            self,
            "background: rgba(5,5,7,0.96); border: 1px solid"
            f" {theme.BORDER}; border-radius: 12px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)

        # full panel
        self.panel = AIPanel(compact=True)
        lay.addWidget(self.panel, 1)
        self.panel.close_clicked.connect(self.hide)

        # dedicated compact panel (replaces the old trivial pill) —
        # shown when the user minimizes / shrinks the overlay (req #14)
        self.compact = CompactOverlayPanel(ctx, parent=self)
        self.compact.setVisible(False)
        self.compact.expand_clicked.connect(self.expand_from_pill)
        self.compact.mic_clicked.connect(self.panel.mic_clicked)
        self.compact.stop_clicked.connect(self.panel.stop_clicked)
        lay.addWidget(self.compact)

        # ------------------------------------------------ pinned widget strip
        self.pin_header = QWidget()
        ph = QHBoxLayout(self.pin_header)
        ph.setContentsMargins(14, 6, 8, 6)
        ph.setSpacing(6)
        cap = QLabel("PINNED WIDGETS")
        theme.set_style(
            cap,
            f"color: {theme.GHOST}; font-size: 9px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1.4px; background: transparent; border: none;")
        self._pin_toggle = QLabel("▼")
        theme.set_style(self._pin_toggle,
                        f"color: {theme.GHOST}; font-size: 9px;"
                        "background: transparent; border: none;")
        ph.addWidget(cap)
        ph.addStretch(1)
        ph.addWidget(self._pin_toggle)
        self.pin_header.setCursor(Qt.PointingHandCursor)
        self.pin_header.mousePressEvent = lambda _e: self.toggle_pins()
        self.pin_header.hide()
        lay.addWidget(self.pin_header)

        self.pin_scroll = QScrollArea()
        self.pin_scroll.setWidgetResizable(True)
        self.pin_scroll.setFrameShape(QScrollArea.NoFrame)
        self.pin_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        theme.set_style(self.pin_scroll, f"""
            QScrollArea {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 4px; }}
            QScrollBar::handle:vertical {{
                background: {theme.SCROLL_THUMB}; border-radius: 2px; min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)
        self.pin_holder = QWidget()
        self.pin_lay = QVBoxLayout(self.pin_holder)
        self.pin_lay.setContentsMargins(8, 2, 8, 8)
        self.pin_lay.setSpacing(6)
        self.pin_lay.addStretch(1)
        self.pin_scroll.setWidget(self.pin_holder)
        self.pin_scroll.setMaximumHeight(int(NORMAL_H * 0.42))
        self.pin_scroll.hide()
        lay.addWidget(self.pin_scroll)

        self._pinned_widgets: list[WidgetBase] = []
        self._pills_collapsed = False

        self._dragging = False
        self._drag_offset = QPoint()

        # keep on top (Windows: real HWND_TOPMOST so it floats above everything)
        self._topmost = QTimer(self)
        self._topmost.setInterval(4000)
        self._topmost.timeout.connect(self._enforce_topmost)

        # overlay pinned mirrors rebuild with the widget system
        ctx.widget_manager.changed.connect(self.rebuild_pinned)
        ctx.widget_manager.data_changed.connect(self.refresh_pinned)

    # --------------------------------------------------------- pinned area
    def rebuild_pinned(self) -> None:
        for w in self._pinned_widgets:
            try:
                w.shutdown()
            except Exception:
                pass
            w.setParent(None)
            w.hide()
            w.deleteLater()
        self._pinned_widgets = []
        any_pinned = bool(self.ctx.widget_manager.overlay_pinned())
        self.pin_header.setVisible(any_pinned and not self._pill_mode)
        if not any_pinned:
            self.pin_scroll.hide()
            return
        if not self._pills_collapsed:
            self.pin_scroll.show()
        for inst in self.ctx.widget_manager.overlay_pinned():
            try:
                w = self.ctx.widget_manager.build_widget(inst, compact=True,
                                                         parent=self.pin_holder)
            except Exception:
                continue
            w.request_overlay_pin.connect(
                lambda wgt, pinned:
                self.ctx.widget_manager.set_pin_overlay(wgt.instance["id"], pinned))
            from PySide6.QtWidgets import QSizePolicy
            w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.pin_lay.insertWidget(self.pin_lay.count() - 1, w)
            w.show()
            self._pinned_widgets.append(w)
        if self.isVisible():
            self.pin_scroll.show()
            self.pin_header.show()

    def refresh_pinned(self) -> None:
        for w in self._pinned_widgets:
            try:
                w.refresh()
            except Exception:
                pass

    def toggle_pins(self) -> None:
        self._pills_collapsed = not self._pills_collapsed
        self.pin_scroll.setVisible(
            bool(self._pinned_widgets) and not self._pills_collapsed)
        self._pin_toggle.setText("▶" if self._pills_collapsed else "▼")

    # ---------------------------------------------------------- collapse
    def collapse_to_pill(self) -> None:
        """Switch the overlay to the dedicated CompactOverlayPanel.

        Requirement #14: this is NOT a scaled-down copy of the full overlay —
        it is a separate, dedicated compact floating design with Nova
        identity, mic/status indicator, listening state, small waveform,
        current task, expand button and stop button. Remains usable while
        the user works in other applications.
        """
        self._pill_mode = True
        self.panel.setVisible(False)
        self.pin_header.setVisible(False)
        self.pin_scroll.setVisible(False)
        self.compact.setVisible(True)
        # mirror current state into the compact panel
        try:
            self.compact.set_online(
                bool(self.ctx.config.active_stack()["llm_key"]))
        except Exception:
            pass
        # sync the compact panel's state with the orchestrator's current state
        try:
            self.compact.set_state(self.ctx.orchestrator.state or "IDLE")
        except Exception:
            pass
        self.setFixedSize(COMPACT_W, COMPACT_H)
        self._position_right()

    def expand_from_pill(self) -> None:
        self._pill_mode = False
        self.compact.setVisible(False)
        self.panel.setVisible(True)
        any_pinned = bool(self.ctx.widget_manager.overlay_pinned())
        self.pin_header.setVisible(any_pinned)
        self.pin_scroll.setVisible(any_pinned and not self._pills_collapsed)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        w = int(self.ctx.config.get("overlay.width", 400))
        self.resize(w, NORMAL_H)
        self._position_right()

    _pill_mode = False

    # ------------------------------------------------------------ show
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._pill_mode:
            self.setFixedSize(COMPACT_W, COMPACT_H)
        else:
            self._position_right()
            self.rebuild_pinned()
        self._enforce_topmost()
        self._topmost.start()

    def hideEvent(self, event) -> None:
        self._topmost.stop()
        super().hideEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self._pill_mode:
            self.expand_from_pill()
        else:
            self.collapse_to_pill()
        super().mouseDoubleClickEvent(event)

    def _position_right(self) -> None:
        screen = self.screen() or self.ctx.app_screen
        if screen is None:
            return
        geo = screen.availableGeometry()
        self.move(geo.right() - self.width() - 12,
                  geo.top() + max(12, (geo.height() - self.height()) // 2))

    def _enforce_topmost(self) -> None:
        if not (IS_WINDOWS and self.isVisible()):
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            ctypes.windll.user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        except Exception:
            pass

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            if not self._pill_mode:
                self.activateWindow()

    def set_online(self, online: bool) -> None:
        try:
            self.panel.set_online(online)
        except Exception:
            pass
        try:
            self.compact.set_online(online)
        except Exception:
            pass

    # ------------------------------------------------------------ drag
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_offset = QCursor.pos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.move(QCursor.pos() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False

    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QPainter, QColor
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(5, 5, 7, 244))
        p.setPen(QColor(theme.BORDER))
        radius = 14 if self._pill_mode else 12
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), radius, radius)
