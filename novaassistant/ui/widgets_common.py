"""Shared pitch-black UI components replicated from the HTML mockups."""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .. import icons, theme


# ------------------------------------------------------------------ helpers
def scoped(name: str, body: str, kind: str = "QWidget") -> str:
    """Scope a stylesheet to ONE widget via objectName selector.

    IMPORTANT: a bare `setStyleSheet("background: X")` on a container leaks
    the rule to every descendant (Qt semantics), which silently breaks child
    button styling. Always scope container stylesheets like this.
    """
    return f"{kind}#{name} {{ {body} }}"


def style_scoped(widget: QWidget, name: str, body: str, kind: str = "QWidget") -> None:
    widget.setObjectName(name)
    theme.set_style(widget, scoped(name, body, kind))


def hline() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    theme.set_style(f, f"background: {theme.BORDER}; border: none;")
    return f


def faint_hline() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    theme.set_style(f, "background: rgba(255,255,255,0.05); border: none;")
    return f


def vline(width: int = 1) -> QFrame:
    f = QFrame()
    f.setFixedWidth(width)
    theme.set_style(f, f"background: {theme.BORDER}; border: none;")
    return f


def spacer() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    theme.set_style(w, "background: transparent;")
    return w


def icon_button(name: str, tip: str = "", size: int = 16, color: str = theme.MUTED,
                hover_bg: bool = True, parent=None) -> QPushButton:
    btn = QPushButton(parent)
    btn.setIcon(icons.icon(name, color, size))
    btn.setVariant = "icon"  # type: ignore[attr-defined]
    btn.setProperty("variant", "icon")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setIconSize(QSize(size, size))
    btn.setFixedSize(QSize(size + 14, size + 14))
    if not hover_bg:
        theme.set_style(btn, "QPushButton:hover { background: transparent; }")
    if tip:
        btn.setToolTip(tip)
    return btn


def primary_button(text: str, icon_name: str | None = None,
                   icon_color: str = theme.BLACK) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("variant", "primary")
    btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        btn.setIcon(icons.icon(icon_name, icon_color, 14, 2))
    return btn


def ghost_button(text: str, icon_name: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("variant", "ghost")
    btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        btn.setIcon(icons.icon(icon_name, theme.MUTED, 14))
    return btn


def danger_button(text: str, icon_name: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("variant", "danger")
    btn.setCursor(Qt.PointingHandCursor)
    if icon_name:
        btn.setIcon(icons.icon(icon_name, theme.GHOST, 14))
    return btn


# ------------------------------------------------------------ status pill
class StatusPill(QWidget):
    """Rounded-full emerald status pill (NOVA sidebar badge)."""

    def __init__(self, text: str = "Idle", dot_color: str = theme.EMERALD,
                 parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)
        lay.setSpacing(6)
        self._dot = QLabel()
        self._dot.setFixedSize(6, 6)
        theme.set_style(self._dot, 
            f"background: {dot_color}; border-radius: 3px;")
        self._text = QLabel(text)
        theme.set_style(self._text, 
            f"color: {theme.EMERALD}; font-size: 11px; background: transparent;")
        lay.addWidget(self._dot)
        lay.addWidget(self._text)
        theme.set_style(self, 
            f"background: transparent; border: none; border-radius: 10px;")

    def set_text(self, text: str, color: str | None = None,
                 dot: str | None = None) -> None:
        self._text.setText(text)
        if color:
            theme.set_style(self._text,
                            f"color: {color}; font-size: 11px; background: transparent;")
        if dot:
            theme.set_style(self._dot, f"background: {dot}; border-radius: 3px;")

    def set_busy(self, busy: bool) -> None:
        color = theme.WHITE if busy else theme.EMERALD
        theme.set_style(self._text,
                        f"color: {color}; font-size: 11px; background: transparent;")
        theme.set_style(self._dot, 
            f"background: {color}; border-radius: 3px;")


# ------------------------------------------------------------ traffic lights
class TrafficLights(QWidget):
    """macOS-style window dots from the conversation mockup."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(58, 12)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        specs = [("#ff5f56", "#e0443e"), ("#ffbd2e", "#dea123"), ("#27c93f", "#1aab29")]
        for i, (fill, border) in enumerate(specs):
            p.setBrush(QColor(fill))
            p.setPen(QPen(QColor(border), 1))
            p.drawEllipse(i * 20, 0, 12, 12)


# ----------------------------------------------------------------- waveform
class Waveform(QWidget):
    """32-band spectrum visualizer with live amplitude feed."""

    def __init__(self, bars: int = 32, height: int = 44, parent=None):
        super().__init__(parent)
        self._bars = bars
        self._levels = [0.0] * bars
        self._decay = [0.0] * bars
        self._active = False
        self.setMinimumHeight(height)
        t = QTimer(self)
        t.setInterval(33)
        t.timeout.connect(self._tick)
        t.start()

    def set_active(self, active: bool) -> None:
        self._active = active

    def push_level(self, level: float) -> None:
        self._levels.pop(0)
        self._levels.append(max(0.0, min(1.0, level)))

    def _tick(self) -> None:
        if not self._active:
            self._levels = [max(0.0, v * 0.82) for v in self._levels]
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if not self._active and all(v < 0.02 for v in self._levels):
            # idle: 1px line at 20% opacity cyan
            p.setPen(QPen(QColor(6, 182, 212, 51), 1))
            y = int(h / 2.0)
            p.drawLine(6, y, w - 6, y)
            return
        bar_w, gap = 2.0, 2.0
        total = self._bars * (bar_w + gap) - gap
        x = (w - total) / 2.0
        base = h / 2.0
        for i, level in enumerate(self._levels):
            amp = max(1.5, level * (h - 8) / 2.0)
            grad_top = QColor(139, 92, 246)   # electric violet peak
            grad_bot = QColor(6, 182, 212)    # cyan floor
            p.setPen(Qt.NoPen)
            p.setBrush(grad_bot)
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, base - amp, bar_w, amp * 2), 1, 1)
            p.fillPath(path, grad_bot)
            p.setBrush(grad_top)
            top = QPainterPath()
            top.addRoundedRect(QRectF(x, base - amp, bar_w, min(amp * 2, amp)), 1, 1)
            p.fillPath(top, grad_top)
            x += bar_w + gap


class MiniWave(QWidget):
    """Tiny 5-bar waveform from the input console (decorative, animated)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 20)
        self._t = 0
        t = QTimer(self)
        t.setInterval(90)
        t.timeout.connect(self._tick)
        t.start()

    def _tick(self) -> None:
        self._t += 1
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        heights = [8, 14, 20, 12, 4]
        for i, base in enumerate(heights):
            wave = 0.6 + 0.4 * math.sin(self._t * 0.9 + i * 0.8)
            hgt = max(2, int(base * wave))
            shade = [90, 110, 130, 110, 90][i]
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(shade, shade, shade + 10))
            p.drawRoundedRect(i * 5, 10 - hgt // 2, 2, hgt, 1, 1)


# ------------------------------------------------------------------ spinner
class Spinner(QWidget):
    """Arc spinner used in the pipeline stepper (active step)."""

    def __init__(self, size: int = 12, color: str = theme.WHITE, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._color = color
        self.setFixedSize(size, size)
        t = QTimer(self)
        t.setInterval(40)
        t.timeout.connect(self._tick)
        t.start()

    def _tick(self) -> None:
        self._angle = (self._angle + 12) % 360
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(self._color), 2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        r = self.width() / 2 - 2
        p.drawArc(2, 2, int(r * 2), int(r * 2), self._angle * 16, 100 * 16)


# ------------------------------------------------------------------ stepper
class StepRow(QWidget):
    done = Signal()

    def __init__(self, label: str, status: str = "queued", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(8)
        self._mark = QLabel("○")
        self._mark.setFixedWidth(14)
        self._mark.setAlignment(Qt.AlignCenter)
        self._label = QLabel(label)
        self._state = QLabel("Queued")
        theme.set_style(self._state, f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};")
        self._spin: Spinner | None = None
        lay.addWidget(self._mark)
        lay.addWidget(self._label)
        lay.addStretch(1)
        lay.addWidget(self._state)
        self.set_status(label, status)

    def set_status(self, label: str, status: str) -> None:
        self._label.setText(label)
        if self._spin:
            self._spin.deleteLater()
            self._spin = None
        if status == "done":
            self._mark.setText("✓")
            theme.set_style(self._mark, f"color: {theme.EMERALD_500}; font-weight: 700;")
            theme.set_style(self._label, "color: #d4d4d8;")
            self._state.setText("Done")
            theme.set_style(self._state,
                            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};")
        elif status == "active":
            self._mark.setText("")
            self._spin = Spinner(11, theme.WHITE)
            holder = QHBoxLayout()
            holder.setContentsMargins(0, 0, 0, 0)
            holder.addWidget(self._spin)
            self._mark.setLayout(holder)
            theme.set_style(self._label, f"color: {theme.WHITE}; font-weight: 600;")
            self._state.setText("Active")
            theme.set_style(self._state,
                            f"color: {theme.EMERALD}; font-size: 10px; font-family: {theme.FONT_MONO};")
        else:
            self._mark.setText("•")
            theme.set_style(self._mark, f"color: {theme.GHOST};")
            theme.set_style(self._label, f"color: {theme.GHOST};")
            self._state.setText("Queued")
            theme.set_style(self._state,
                            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};")


class Stepper(QWidget):
    """SYSTEM PIPELINE box with step rows (mockup exact)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        theme.set_style(self, 
            f"background: {theme.BLACK}; border: 1px solid {theme.BORDER}; border-radius: 12px;")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 12)
        outer.setSpacing(4)
        head = QHBoxLayout()
        self._title = QLabel("SYSTEM PIPELINE")
        theme.set_style(self._title, 
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; border: none;")
        self._counter = QLabel("Ready")
        theme.set_style(self._counter, 
            f"color: {theme.EMERALD}; font-size: 10px; font-family: {theme.FONT_MONO}; border: none;")
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._counter)
        outer.addLayout(head)
        outer.addWidget(hline())
        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 6, 0, 0)
        self._body.setSpacing(3)
        outer.addLayout(self._body)
        self._rows: list[StepRow] = []

    def clear(self) -> None:
        for row in self._rows:
            row.deleteLater()
        self._rows.clear()
        self._counter.setText("Ready")

    def set_steps(self, steps: list[dict]) -> None:
        self.clear()
        done = 0
        for spec in steps:
            row = StepRow(spec.get("label", ""), spec.get("status", "queued"))
            self._body.addWidget(row)
            self._rows.append(row)
            if spec.get("status") == "done":
                done += 1
        total = len(steps)
        if total:
            active = any(s.get("status") == "active" for s in steps)
            self._counter.setText(
                f"Step {done}/{total}" + (" • running" if active else ""))
        else:
            self._counter.setText("Ready")


# --------------------------------------------------------------- mono chips
class MonoChip(QLabel):
    def __init__(self, text: str, parent=None, accent: str | None = None):
        super().__init__(text, parent)
        color = accent or "#d4d4d8"
        theme.set_style(
            self,
            f"color: {color}; font-size: 11px; font-family: {theme.FONT_MONO};"
            f"background: #141416; border: 1px solid {theme.BORDER_2};"
            "border-radius: 5px; padding: 2px 8px;")


class TagPill(QLabel):
    def __init__(self, text: str, color: str = theme.MUTED, bg: str = "#141416",
                 border: str | None = None, parent=None):
        super().__init__(text, parent)
        theme.set_style(
            self,
            f"color: {color}; font-size: 10px; font-family: {theme.FONT_MONO};"
            f"background: {bg}; border: 1px solid {border or theme.BORDER_2};"
            "border-radius: 5px; padding: 1px 6px;")


# ------------------------------------------------------------ scroll combo
class NoScrollCombo(QComboBox):
    """QComboBox that IGNORES the mouse wheel.

    Scrolling over a dropdown must never change the selected value — the
    wheel event is propagated to the parent scroll area instead. The value
    changes only when the user opens the popup and explicitly picks an
    option.
    """

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        event.ignore()


# ----------------------------------------------------------------- checkbox
class NovaCheckBox(QCheckBox):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        theme.set_style(self, f"""
            QCheckBox {{ background: transparent; color: {theme.TEXT}; }}
            QCheckBox::indicator {{
                width: 15px; height: 15px; border-radius: 4px;
                border: 1px solid #3f3f46; background: #0d0d10;
            }}
            QCheckBox::indicator:hover {{ border-color: #71717a; }}
            QCheckBox::indicator:checked {{
                background: {theme.FOCUS_RING}; border-color: {theme.FOCUS_RING};
                image: url({theme.ASSETS_DIR}/check.svg);
            }}
        """)


# ------------------------------------------------------------- scroll area
class ScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        theme.set_style(self, f"""
            QScrollArea {{ background: transparent; }}
            QScrollBar:vertical {{ background: {theme.BLACK}; width: 5px; }}
            QScrollBar::handle:vertical {{
                background: {theme.SCROLL_THUMB}; border-radius: 2px; min-height: 24px; }}
            QScrollBar::handle:vertical:hover {{ background: {theme.SCROLL_THUMB_HOVER}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)


# ------------------------------------------------------------- section card
class SectionCard(QWidget):
    """Rounded-xl bordered container used across all pages."""

    def __init__(self, parent=None, padding: int = 20, bg: str = theme.PANEL,
                 border: str = theme.BORDER):
        super().__init__(parent)
        theme.set_style(self, 
            f"background: {bg}; border: 1px solid {border}; border-radius: 12px;")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(12)


# ------------------------------------------------------------------- rows
class HfwRow(QWidget):
    """Row widget whose height exactly tracks its layout's height-for-width.

    Word-wrapped rows (reminders, activity entries) report a minimum smaller
    than their natural size (QSS padding is not part of QLabel sizeHint), so
    parent layouts shrink them and clip the chip line. The row's height is
    pinned to max(min_natural_height, heightForWidth(width)) — recomputed on
    every resize — which keeps the full row visible at any width.
    """

    min_natural_height = 0

    def __init__(self, parent=None):
        super().__init__(parent)

    def prime_height(self) -> None:
        """Pin the initial height. MUST be called at the END of subclass
        __init__ (after the row's layout is built) — installing a layout on
        a widget resets previously-set fixed sizes."""
        if self.min_natural_height:
            self.setFixedHeight(self.min_natural_height)

    def sync_height(self) -> None:
        h = self.min_natural_height
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            h = max(h, lay.heightForWidth(self.width()))
        if h > 0 and h != self.height():
            self.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        self.sync_height()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:
        self.sync_height()
        super().showEvent(event)


def bind_hover_glow(widget: QWidget) -> None:
    """Subtle hover brightening for card-like widgets via enter/leave events."""
    widget.setAttribute(Qt.WA_Hover, True)


# ------------------------------------------------------ deterministic rows
class FixedRowsHost(QWidget):
    """Vertical stack of fixed-height rows laid out MANUALLY.

    Dynamic QVBoxLayouts + stretch items + deleteLater churn proved
    unreliable (stale QWidgetItem caches, holder sizes not settling), which
    showed up as overlapping rows. This host positions rows itself:
    fully deterministic, no layout caches, works at any width.
    Rows should be HfwRow subclasses (fixed height, synced on resize).
    """

    def __init__(self, spacing: int = 10, parent=None):
        super().__init__(parent)
        self._rows: list[QWidget] = []
        self._spacing = spacing
        theme.set_style(self, "background: transparent;")

    # ------------------------------------------------------------- api
    def add_row(self, w: QWidget) -> None:
        w.setParent(self)
        w.show()
        self._rows.append(w)

    def clear_rows(self) -> None:
        for r in self._rows:
            r.setParent(None)
            r.hide()
            r.deleteLater()
        self._rows = []

    def rows(self) -> list[QWidget]:
        return list(self._rows)

    def relayout_now(self) -> None:
        self._relayout()

    # ---------------------------------------------------------- internals
    def resizeEvent(self, event) -> None:
        self._relayout()
        super().resizeEvent(event)

    def _relayout(self) -> None:
        w = max(160, self.width())
        y = 0
        for r in self._rows:
            if hasattr(r, "sync_height"):
                r.sync_height()
                h = max(1, r.height())
            else:
                # plain widgets (empty-state labels): size their hint
                h = max(24, r.sizeHint().height())
                r.setFixedHeight(h)
            r.setGeometry(0, y, w, h)
            y += h + self._spacing
        self.setFixedHeight(max(40, y - self._spacing if self._rows else 40))


class RowsScroll(ScrollArea):
    """Scroll area bound to a FixedRowsHost: keeps the host as wide as the
    viewport and lets its height drive the scrollbar."""

    def __init__(self, host: FixedRowsHost, parent=None):
        super().__init__(parent)
        self._host = host
        self.setWidgetResizable(False)
        self.setWidget(host)
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.viewport() and event.type() == event.Type.Resize:
            self._host.setFixedWidth(max(160, self.viewport().width() - 2))
            self._host.relayout_now()
        return super().eventFilter(obj, event)

    def refresh(self) -> None:
        self._host.setFixedWidth(max(160, self.viewport().width() - 2))
        self._host.relayout_now()
