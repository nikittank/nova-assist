"""Configurable desktop widgets (pitch-black, draggable, always available).

Widgets are small frameless tool windows rendered in the Nova design
language. They read local data (SQLite + config) directly, refresh on a
timer, remember their position and support optional pin-on-top + opacity.

Available: What's Today · Focus · Stack · Quick Notes · Reminders ·
System Pulse.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QVBoxLayout, QWidget)

from . import theme

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None


def _mono(text: str, size: int, color: str, weight: int = 600,
          spacing: float = 2.0) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"font-family: {theme.MONO}; font-size: {size}px; font-weight: {weight}; "
        f"letter-spacing: {spacing}px; color: {color}; background: transparent;")
    return lbl


class WidgetWindow(QWidget):
    """Base class: frameless black card, draggable, position persisted."""

    W = 250
    H = 180
    TITLE = "WIDGET"
    WID = "widget"
    INTERVAL_MS = 1000

    def __init__(self, controller, bus, parent=None) -> None:
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Tool)
        self.controller = controller
        self.bus = bus
        self.widget_id = self.WID
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(self.W, self.H)
        self._drag_offset = None

        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(14, 10, 14, 12)
        self.root.setSpacing(6)

        head = QHBoxLayout()
        self.title_lbl = _mono(self.TITLE, 9, theme.DIM)
        head.addWidget(self.title_lbl)
        head.addStretch(1)
        close_btn = QPushButton("\u00d7")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            f"background: transparent; color: {theme.FAINT}; border: none; font-size: 13px;")
        close_btn.clicked.connect(self.hide)
        head.addWidget(close_btn)
        self.root.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setSpacing(4)
        self.root.addLayout(self.body, 1)

        self._apply_pin()
        self._restore_geometry()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(self.INTERVAL_MS)
        # defer the first refresh until the subclass finished building
        QTimer.singleShot(0, self.refresh)

    # ------------------------------------------------------------- helpers
    def _apply_pin(self) -> None:
        state = self.controller.config.get("widget_state", {}) or {}
        pinned = bool((state.get(self.widget_id) or {}).get("pinned", True))
        flags = self.windowFlags()
        if pinned:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        opacity = float((state.get(self.widget_id) or {}).get("opacity", 0.96))
        self.setWindowOpacity(max(0.35, min(1.0, opacity)))

    def show_widget(self) -> None:
        self._apply_pin()
        self._restore_geometry()
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(11, 11, 14, 242))
        p.drawRoundedRect(r, 12, 12)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        self._save_geometry()

    def _restore_geometry(self) -> None:
        state = self.controller.config.get("widget_state", {}) or {}
        geo = state.get(self.widget_id, {})
        if geo.get("x") is not None:
            self.move(int(geo["x"]), int(geo["y"]))
            return
        try:  # cascade new widgets down the right edge, next to the overlay
            from PySide6.QtGui import QGuiApplication
            avail = QGuiApplication.primaryScreen().availableGeometry()
            order = list(WIDGET_CLASSES.keys()).index(self.widget_id) \
                if self.widget_id in WIDGET_CLASSES else 0
            self.move(avail.right() - self.W - 390, avail.top() + 60 + order * 210)
        except Exception:
            self.move(200, 120)

    def _save_geometry(self) -> None:
        state = self.controller.config.get("widget_state", {}) or {}
        geo = state.get(self.widget_id, {}) or {}
        geo.update({"x": self.x(), "y": self.y()})
        state[self.widget_id] = geo
        self.controller.config.set("widget_state", state)
        self.controller.config.save()

    def set_pinned(self, pinned: bool) -> None:
        state = self.controller.config.get("widget_state", {}) or {}
        geo = state.get(self.widget_id, {}) or {}
        geo["pinned"] = bool(pinned)
        state[self.widget_id] = geo
        self.controller.config.set("widget_state", state)
        self._apply_pin()
        self.show_widget()

    def set_opacity(self, value: float) -> None:
        state = self.controller.config.get("widget_state", {}) or {}
        geo = state.get(self.widget_id, {}) or {}
        geo["opacity"] = float(value)
        state[self.widget_id] = geo
        self.controller.config.set("widget_state", state)
        self.setWindowOpacity(max(0.35, min(1.0, value)))

    def refresh(self) -> None:  # pragma: no cover - overridden
        pass


# ---------------------------------------------------------------- widgets
class WhatsTodayWidget(WidgetWindow):
    W, H = 250, 190
    TITLE, WID, INTERVAL_MS = "WHAT'S TODAY", "whats_today", 1000

    def __init__(self, controller, bus, parent=None) -> None:
        self._day = _mono("", 40, theme.TEXT, 700, 0)
        self._date = _mono("", 10, theme.DIM, 600, 2.2)
        self._clock = _mono("", 15, theme.CYAN, 700, 3.0)
        self._greet = QLabel("")
        self._greet.setWordWrap(True)
        self._greet.setStyleSheet(
            f"font-size: 12px; color: {theme.DIM}; background: transparent;")
        super().__init__(controller, bus, parent)
        row = QHBoxLayout()
        row.addWidget(self._day)
        col = QVBoxLayout()
        col.addWidget(self._date)
        col.addWidget(self._clock)
        row.addLayout(col)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addWidget(self._greet)
        self.body.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        now = datetime.now()
        self._day.setText(now.strftime("%d"))
        self._date.setText(now.strftime("%B %Y").upper() + "  ·  "
                           + now.strftime("%A").upper())
        self._clock.setText(now.strftime("%H:%M:%S"))
        hour = now.hour
        greet = "Good morning." if hour < 12 else \
            "Good afternoon." if hour < 18 else "Good evening."
        try:
            today = now.strftime("%Y-%m-%d")
            due = [r for r in self.controller.db.list_reminders(active_only=True)
                   if str(r.get("next_trigger", "")).startswith(today)]
            greet += f"  {len(due)} reminder(s) today."
        except Exception:
            pass
        self._greet.setText(greet)


class FocusWidget(WidgetWindow):
    W, H = 260, 160
    TITLE, WID, INTERVAL_MS = "FOCUS", "focus", 1000

    def __init__(self, controller, bus, parent=None) -> None:
        self._session_start: float | None = None
        self._focus_lbl = QLabel("")
        self._focus_lbl.setWordWrap(True)
        self._focus_lbl.setStyleSheet(
            f"font-family: {theme.SANS}; font-size: 15px; color: {theme.TEXT};"
            f"background: transparent;")
        self._timer_lbl = _mono("no session", 10, theme.DIM)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Set current focus...")
        self._edit.setObjectName("searchInput")
        self._edit.returnPressed.connect(self._set)
        btn_row = QHBoxLayout()
        set_btn = QPushButton("Set")
        set_btn.setObjectName("primaryButton")
        set_btn.clicked.connect(self._set)
        self.session_btn = QPushButton("Start session")
        self.session_btn.setObjectName("ghostButton")
        self.session_btn.clicked.connect(self._toggle_session)
        btn_row.addWidget(set_btn)
        btn_row.addWidget(self.session_btn)
        btn_row.addStretch(1)
        super().__init__(controller, bus, parent)
        self.body.addWidget(self._focus_lbl, 1)
        self.body.addWidget(self._timer_lbl)
        self.body.addWidget(self._edit)
        self.body.addLayout(btn_row)
        self.refresh()

    def _set(self) -> None:
        text = self._edit.text().strip()
        if text:
            self.controller.db.kv_set("focus", text)
            self.controller.db.log_activity("focus", f"Focus set: {text[:60]}")
            self._edit.clear()
            self.refresh()

    def _toggle_session(self) -> None:
        if self._session_start is None:
            self._session_start = time.time()
            self.session_btn.setText("Stop session")
        else:
            self._session_start = None
            self.session_btn.setText("Start session")
        self.refresh()

    def refresh(self) -> None:
        focus = self.controller.db.kv_get("focus", "")
        self._focus_lbl.setText(focus or "No focus set. What matters right now?")
        if self._session_start is None:
            self._timer_lbl.setText("no session")
        else:
            mins = int((time.time() - self._session_start) // 60)
            self._timer_lbl.setText(f"SESSION · {mins:02d}:{int(time.time() - self._session_start) % 60:02d}")


class StackWidget(WidgetWindow):
    """Today's stack: due reminders + the newest notes."""
    W, H = 280, 230
    TITLE, WID, INTERVAL_MS = "STACK", "stack", 20000

    def __init__(self, controller, bus, parent=None) -> None:
        super().__init__(controller, bus, parent)
        self._lbl = QLabel("")
        self._lbl.setWordWrap(True)
        self._lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._lbl.setStyleSheet(
            f"font-size: 11px; color: {theme.TEXT}; background: transparent;")
        self.body.addWidget(self._lbl, 1)
        self.refresh()
        self.bus.reminders_changed.connect(self.refresh)
        self.bus.notes_changed.connect(self.refresh)

    def refresh(self) -> None:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            due = [r for r in self.controller.db.list_reminders(active_only=True)
                   if str(r.get("next_trigger", "")).startswith(today)]
            notes = self.controller.db.list_notes(limit=3)
            lines = [f"REMINDERS TODAY · {len(due)}"]
            for r in due[:3]:
                hhmm = str(r["next_trigger"])[11:16]
                lines.append(f"  {hhmm}  {r['message'][:26]}")
            lines.append("")
            lines.append(f"RECENT NOTES · {len(notes)}")
            for n in notes:
                preview = n["content"][:30].replace("\n", " ")
                lines.append(f"  [{n['topic']}] {preview}")
            self._lbl.setText("\n".join(lines))
        except Exception as exc:
            self._lbl.setText(f"stack unavailable: {exc}")


class QuickNotesWidget(WidgetWindow):
    W, H = 280, 210
    TITLE, WID, INTERVAL_MS = "QUICK NOTES", "quick_notes", 15000

    def __init__(self, controller, bus, parent=None) -> None:
        self._list_lbl = QLabel("")
        self._list_lbl.setWordWrap(True)
        self._list_lbl.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._list_lbl.setStyleSheet(
            f"font-size: 11px; color: {theme.DIM}; background: transparent;")
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Capture a note, Enter saves...")
        self._edit.setObjectName("searchInput")
        self._edit.returnPressed.connect(self._save_note)
        super().__init__(controller, bus, parent)
        self.body.addWidget(self._edit)
        self.body.addWidget(self._list_lbl, 1)
        self.refresh()
        self.bus.notes_changed.connect(self.refresh)

    def _save_note(self) -> None:
        text = self._edit.text().strip()
        if not text:
            return
        row = self.controller.db.add_note(text, "quick")
        self.controller.db.log_activity("note",
                                        f"Quick note #{row['id']}: {text[:60]}")
        self._edit.clear()
        self.bus.notes_changed.emit()
        self.refresh()

    def refresh(self) -> None:
        try:
            notes = self.controller.db.list_notes(limit=40)
            quick = [n for n in notes if n["topic"] == "quick"][:3]
            rows = [f"\u2022 {n['content'][:36].replace(chr(10), ' ')}" for n in quick]
            self._list_lbl.setText("\n".join(rows) if rows
                                   else "No quick notes yet - type one above.")
        except Exception as exc:
            self._list_lbl.setText(f"- {exc}")


class RemindersWidget(WidgetWindow):
    W, H = 300, 250
    TITLE, WID, INTERVAL_MS = "REMINDERS", "reminders", 20000

    def __init__(self, controller, bus, parent=None) -> None:
        self._rows: list[tuple[dict, QLabel, QPushButton]] = []
        super().__init__(controller, bus, parent)
        self._empty_lbl = _mono("nothing pending", 10, theme.FAINT)
        self._empty_lbl.hide()
        self.body.addWidget(self._empty_lbl)
        self.refresh()
        self.bus.reminders_changed.connect(self.refresh)
        self.bus.reminder_fired.connect(lambda _r: self.refresh())

    def _clear_rows(self) -> None:
        for _rem, lbl, btn in self._rows:
            self.body.removeWidget(lbl)
            self.body.removeWidget(btn)
            lbl.deleteLater()
            btn.deleteLater()
        self._rows = []

    def refresh(self) -> None:
        self._clear_rows()
        try:
            rows = self.controller.db.list_reminders(active_only=True)[:5]
        except Exception:
            rows = []
        self._empty_lbl.setVisible(not rows)
        for rem in rows:
            row = QHBoxLayout()
            t = str(rem["next_trigger"])[11:16]
            day = str(rem["next_trigger"])[:10]
            when = _mono(f"{day[5:]} {t}", 10, theme.CYAN)
            when.setToolTip(rem["message"])
            lbl = QLabel(str(rem["message"])[:34])
            lbl.setStyleSheet(
                f"font-size: 11px; color: {theme.TEXT}; background: transparent;")
            done = QPushButton("\u2713")
            done.setFixedSize(22, 22)
            done.setCursor(Qt.PointingHandCursor)
            done.setStyleSheet(
                f"background: transparent; color: {theme.FAINT}; "
                f"border: 1px solid {theme.BORDER}; border-radius: 11px;")
            done.clicked.connect(lambda _=False, rid=rem["id"]:
                                 self._complete(rid))
            row.addWidget(when)
            row.addWidget(lbl, 1)
            row.addWidget(done)
            self.body.addLayout(row)
            self._rows.append((rem, lbl, done))
        self.body.addStretch(1)

    def _complete(self, rid: int) -> None:
        try:
            self.controller.db.set_reminder_active(rid, False)
            self.controller.db.log_activity("reminder", f"Widget completed #{rid}")
            self.bus.reminders_changed.emit()
            self.refresh()
        except Exception:
            pass


class SystemPulseWidget(WidgetWindow):
    W, H = 250, 170
    TITLE, WID, INTERVAL_MS = "SYSTEM PULSE", "system_pulse", 2000

    def __init__(self, controller, bus, parent=None) -> None:
        self._lbl = _mono("", 10, theme.TEXT, 500, 1.0)
        super().__init__(controller, bus, parent)
        self.body.addWidget(self._lbl, 1)
        self.refresh()

    def refresh(self) -> None:
        lines = []
        if psutil is not None:
            try:
                cpu = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory().percent
                lines.append(f"CPU  {cpu:4.0f}%")
                lines.append(f"RAM  {mem:4.0f}%")
                bat = psutil.sensors_battery()
                if bat is not None:
                    state = "CHG" if bat.power_plugged else "BAT"
                    lines.append(f"PWR  {bat.percent:3.0f}% {state}")
            except Exception:
                lines.append("telemetry n/a")
        else:
            lines.append("psutil not installed")
        listening = self.controller.recorder.listening
        lines.append(f"MIC  {'LIVE' if listening else 'OFF'}")
        lines.append(f"STT  {self.controller.stt_engine_name.upper()}")
        self._lbl.setText("\n".join(lines))


WIDGET_CLASSES = {
    "whats_today": WhatsTodayWidget,
    "focus": FocusWidget,
    "stack": StackWidget,
    "quick_notes": QuickNotesWidget,
    "reminders": RemindersWidget,
    "system_pulse": SystemPulseWidget,
}


class WidgetManager:
    """Creates / shows / hides the enabled desktop widgets."""

    def __init__(self, controller, bus) -> None:
        self.controller = controller
        self.bus = bus
        self.widgets: dict[str, WidgetWindow] = {}

    def _enabled_ids(self) -> list[str]:
        we = self.controller.config.get("widgets_enabled", {}) or {}
        return [wid for wid, on in we.items() if on and wid in WIDGET_CLASSES]

    def sync(self) -> None:
        """Create missing widgets, hide disabled/removed ones."""
        enabled = self._enabled_ids()
        for wid in list(self.widgets):
            if wid not in enabled:
                self.widgets[wid].hide()
                del self.widgets[wid]
        for wid in enabled:
            if wid not in self.widgets:
                cls = WIDGET_CLASSES[wid]
                widget = cls(self.controller, self.bus)
                widget.show_widget()
                self.widgets[wid] = widget

    def hide_all(self) -> None:
        for w in self.widgets.values():
            w.hide()

    def show_all(self) -> None:
        self.sync()

    def refresh_all(self) -> None:
        for w in self.widgets.values():
            try:
                w.refresh()
            except Exception:
                pass
