"""What's Today widget — today's due tasks/events at a glance."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ... import theme
from ..widgets_common import (
    FixedRowsHost, HfwRow, NovaCheckBox, RowsScroll, style_scoped,
)
from .base import WidgetBase


class _TodayTaskRow(HfwRow):
    min_natural_height = 52


class WhatsTodayWidget(WidgetBase):
    title = "WHAT'S TODAY"
    icon_name = "sun"
    default_size = (280, 240)
    min_size = (200, 170)

    # ------------------------------------------------------------- content
    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        style_scoped(holder, "TodayWidgetContent", "background: transparent;")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.date_cap = self._caption("TODAY")
        lay.addWidget(self.date_cap)

        self.rows_host = FixedRowsHost(spacing=6)
        self.scroll = RowsScroll(self.rows_host)
        lay.addWidget(self.scroll, 1)
        return holder

    def refresh(self) -> None:
        self.date_cap.setText(
            datetime.now().strftime("TODAY, %a %b %d").upper())
        self.rows_host.clear_rows()
        try:
            reminders = self.ctx.reminders.all()
            notes = self.ctx.notes.all()
        except Exception:
            reminders, notes = [], []

        today = datetime.now().date()
        due_items = []
        for r in reminders:
            if r.get("done"):
                continue
            try:
                due = datetime.fromisoformat(r["due"])
            except Exception:
                continue
            if due.date() <= today:
                due_items.append((due, r))
        due_items.sort(key=lambda t: t[0])

        max_n = int(self.settings.get("max_items", 4))
        for due, r in due_items[:max_n]:
            overdue = due < datetime.now()
            self.rows_host.add_row(self._task_row(r, due, overdue))
        if not due_items:
            self.rows_host.add_row(
                self._empty("Nothing due today — clear run."))

        if self.settings.get("show_notes", True):
            today_notes = [n for n in notes
                           if str(n.get("created_at", "")).startswith(today.isoformat())]
            cap = self._caption(f"NOTES TODAY, {len(today_notes)}")
            self.rows_host.add_row(cap)
            for n in today_notes[:2]:
                lbl = QLabel(f"›  {n['title'][:26]}")
                theme.set_style(lbl, 
                    f"color: {theme.TEXT}; font-size: 11px; border: none;"
                    "background: transparent;")
                self.rows_host.add_row(lbl)
        self.scroll.refresh()

    def _task_row(self, item: dict, due: datetime, overdue: bool) -> QWidget:
        row = _TodayTaskRow()
        row.setObjectName("TodayRow")
        theme.set_style(
            row,
            f"QWidget#TodayRow {{ background: {theme.PANEL_3};"
            f" border: 1px solid {'#3b1216' if overdue else theme.BORDER};"
            " border-radius: 8px; }")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(8, 6, 8, 6)
        rl.setSpacing(8)
        chk = NovaCheckBox()
        chk.setToolTip("Complete")
        chk.toggled.connect(lambda on, rid=item["id"]: self._complete(rid, on))
        rl.addWidget(chk, 0, Qt.AlignTop)
        mid = QVBoxLayout()
        mid.setSpacing(1)
        text = QLabel(item.get("text", ""))
        text.setWordWrap(True)
        theme.set_style(text, 
            f"color: {theme.TEXT_BRIGHT}; font-size: 11px; font-weight: 600;"
            "border: none; background: transparent;")
        time_lbl = QLabel(("OVERDUE " if overdue else "")
                          + due.strftime("%H:%M"))
        theme.set_style(time_lbl, 
            f"color: {'#f87171' if overdue else theme.MUTED}; font-size: 10px;"
            f"font-family: {theme.FONT_MONO}; border: none; background: transparent;")
        mid.addWidget(text)
        mid.addWidget(time_lbl)
        rl.addLayout(mid, 1)
        return row

    def _complete(self, rid: str, on: bool) -> None:
        try:
            self.ctx.reminders.complete(rid) if on else self.ctx.reminders.reopen(rid)
        except Exception:
            pass

    def build_settings_form(self, parent) -> QWidget:
        from ..widgets_common import NovaCheckBox
        from PySide6.QtWidgets import QSpinBox
        form = QWidget(parent)
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Tasks shown"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 10)
        self.spin.setValue(int(self.settings.get("max_items", 4)))
        row1.addWidget(self.spin, 1)
        lay.addLayout(row1)
        self.notes_chk = NovaCheckBox("Show notes created today")
        self.notes_chk.setChecked(bool(self.settings.get("show_notes", True)))
        lay.addWidget(self.notes_chk)
        lay.addStretch(1)

        def apply() -> None:
            self.settings["max_items"] = self.spin.value()
            self.settings["show_notes"] = self.notes_chk.isChecked()

        form.apply = apply  # type: ignore[attr-defined]
        return form
