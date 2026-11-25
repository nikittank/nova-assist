"""Reminders widget — live reminders with complete / snooze / edit / delete."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from ... import icons, theme
from ..widgets_common import (
    FixedRowsHost, HfwRow, NovaCheckBox, RowsScroll, style_scoped,
)
from .base import WidgetBase


def _human_due(due: str) -> str:
    try:
        dt = datetime.fromisoformat(due)
        today = datetime.now().date()
        d = dt.date()
        if d == today:
            return dt.strftime("Today %H:%M")
        if d == today.fromordinal(today.toordinal() + 1):
            return dt.strftime("Tomorrow %H:%M")
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return due


class _WidgetRemRow(HfwRow):
    min_natural_height = 58


class RemindersWidget(WidgetBase):
    title = "REMINDERS"
    icon_name = "bell"
    default_size = (300, 260)
    min_size = (220, 190)

    # ------------------------------------------------------------- content
    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        style_scoped(holder, "RemWidgetContent", "background: transparent;")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.rows_host = FixedRowsHost(spacing=6)
        self.scroll = RowsScroll(self.rows_host)
        lay.addWidget(self.scroll, 1)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.add_input = QLineEdit()
        self.add_input.setPlaceholderText("Add: 'meeting in 20m'…")
        theme.set_style(self.add_input, 
            f"QLineEdit {{ background: {theme.BLACK}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 6px 9px; font-size: 11px;"
            f" color: {theme.TEXT_BRIGHT}; }}")
        self.add_input.returnPressed.connect(self._quick_add)
        add_btn = QPushButton()
        add_btn.setFixedSize(28, 28)
        add_btn.setIcon(icons.icon("plus", theme.MUTED, 13, 2))
        add_btn.setToolTip("Quick add reminder")
        add_btn.setCursor(Qt.PointingHandCursor)
        theme.set_style(add_btn, 
            "QPushButton { background: #0d0d0f; border: 1px solid "
            + theme.BORDER_2 + "; border-radius: 8px; }"
            "QPushButton:hover { background: #1f1f23; }")
        add_btn.clicked.connect(self._quick_add)
        add_row.addWidget(self.add_input, 1)
        add_row.addWidget(add_btn)
        lay.addLayout(add_row)
        return holder

    # -------------------------------------------------------------- render
    def refresh(self) -> None:
        self.rows_host.clear_rows()
        try:
            items = self.ctx.reminders.all()
        except Exception:
            items = []
        show_done = bool(self.settings.get("show_completed", False))
        max_n = int(self.settings.get("max_items", 4))
        pending = [i for i in items if not i.get("done")]
        pending.sort(key=lambda r: r.get("due", ""))
        rows = pending if not show_done else (pending + [i for i in items if i.get("done")])
        for item in rows[:max_n]:
            self.rows_host.add_row(self._row(item))
        if not rows:
            self.rows_host.add_row(
                self._empty("Nothing pending. Add one below."))
        self.scroll.refresh()

    def _row(self, item: dict) -> QWidget:
        row = _WidgetRemRow()
        row.setObjectName("RemWidgetRow")
        theme.set_style(
            row,
            f"QWidget#RemWidgetRow {{ background: {theme.PANEL_3};"
            f" border: 1px solid {theme.BORDER}; border-radius: 8px; }}")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 6, 6, 6)
        rl.setSpacing(6)

        chk = NovaCheckBox()
        chk.setChecked(bool(item.get("done")))
        chk.setToolTip("Complete")
        chk.toggled.connect(
            lambda on, rid=item["id"]: self._complete(rid, on))
        rl.addWidget(chk, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setSpacing(1)
        text = QLabel(item.get("text", ""))
        text.setWordWrap(True)
        theme.set_style(text, 
            f"color: {'#6b7280' if item.get('done') else theme.TEXT_BRIGHT};"
            " font-size: 11px; font-weight: 600; border: none;"
            "background: transparent;")
        mid.addWidget(text)
        due = QLabel(_human_due(item.get("due", "")))
        theme.set_style(due, 
            f"color: {theme.MUTED}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "border: none; background: transparent;")
        mid.addWidget(due)
        rl.addLayout(mid, 1)

        for icon_name, tip, cb in (
                ("snooze", "Snooze 5 min", lambda rid=item["id"]: self._snooze(rid)),
                ("edit", "Edit in Reminders", lambda rid=item["id"]: self._edit(rid)),
                ("trash", "Delete", lambda rid=item["id"]: self._delete(rid))):
            b = QPushButton()
            b.setFixedSize(22, 22)
            b.setIcon(icons.icon(icon_name, theme.GHOST, 11))
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            theme.set_style(b, 
                "QPushButton { background: transparent; border: none;"
                " border-radius: 5px; } QPushButton:hover { background: #232329; }")
            b.clicked.connect(cb)
            rl.addWidget(b, 0, Qt.AlignTop)
        return row

    # ------------------------------------------------------------- actions
    def _complete(self, rid: str, on: bool) -> None:
        try:
            self.ctx.reminders.complete(rid) if on else self.ctx.reminders.reopen(rid)
        except Exception:
            pass

    def _snooze(self, rid: str) -> None:
        try:
            self.ctx.reminders.snooze(rid, minutes=5)
        except Exception:
            pass

    def _delete(self, rid: str) -> None:
        try:
            self.ctx.reminders.delete(rid)
        except Exception:
            pass

    def _edit(self, rid: str) -> None:
        mgr = getattr(self.ctx, "widget_manager", None)
        if mgr:
            mgr.edit_reminder.emit(rid)

    def _quick_add(self) -> None:
        text = self.add_input.text().strip()
        if not text:
            return
        from ...core import reminder_parser
        self.add_input.clear()
        try:
            parsed = reminder_parser.parse_reminder(text)
        except Exception:
            parsed = {}
        if parsed.get("datetime"):
            self.ctx.reminders.create(parsed["text"], parsed["datetime"],
                                      parsed.get("repeat") or "none")
        else:
            # no time understood -> hand off to the Reminders page
            mgr = getattr(self.ctx, "widget_manager", None)
            if mgr:
                mgr.open_page.emit("reminders")
                mgr.edit_reminder.emit("")

    def edit_content(self) -> bool:
        self.add_input.setFocus()
        return True

    # ------------------------------------------------------------ settings
    def build_settings_form(self, parent) -> QWidget:
        from ..widgets_common import NovaCheckBox
        from PySide6.QtWidgets import QSpinBox
        form = QWidget(parent)
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Reminders shown"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 10)
        self.spin.setValue(int(self.settings.get("max_items", 4)))
        row1.addWidget(self.spin, 1)
        lay.addLayout(row1)

        self.done_chk = NovaCheckBox("Show completed reminders")
        self.done_chk.setChecked(bool(self.settings.get("show_completed", False)))
        lay.addWidget(self.done_chk)
        lay.addStretch(1)

        def apply() -> None:
            self.settings["max_items"] = self.spin.value()
            self.settings["show_completed"] = self.done_chk.isChecked()

        form.apply = apply  # type: ignore[attr-defined]
        return form
