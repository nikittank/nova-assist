"""Date widget — shows ONLY today's date (configurable format)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import theme
from .base import WidgetBase

FORMATS = [
    ("Long — Wednesday, September 10, 2026", "%A, %B %d, %Y"),
    ("Medium — Wed, Sep 10, 2026", "%a, %b %d, %Y"),
    ("Short — 2026-09-10", "%Y-%m-%d"),
    ("Numeric — 10/09/2026", "%d/%m/%Y"),
]


class DateWidget(WidgetBase):
    title = "DATE"
    icon_name = "calendar"
    default_size = (280, 110)
    min_size = (170, 88)
    DEFAULT_FORMAT = "%a, %b %d, %Y"

    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addStretch(1)
        self.weekday_lbl = QLabel("")
        self.weekday_lbl.setAlignment(Qt.AlignCenter)
        theme.set_style(self.weekday_lbl, 
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1.6px; border: none; background: transparent;")
        self.date_lbl = QLabel("")
        self.date_lbl.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.weekday_lbl)
        lay.addWidget(self.date_lbl)
        lay.addStretch(1)
        self._timer = QTimer(self)
        self._timer.setInterval(60000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()
        return holder

    def _tick(self) -> None:
        now = datetime.now()
        fmt_code = self.settings.get("format", self.DEFAULT_FORMAT)
        text = now.strftime(fmt_code)
        self.date_lbl.setText(text)
        size = 13 if self.compact else int(self.settings.get("font_size", 17))
        theme.set_style(self.date_lbl, 
            f"color: {theme.WHITE}; font-size: {size}px; font-weight: 600;"
            f"font-family: {theme.FONT_MONO}; border: none;"
            "background: transparent;")
        show_wd = bool(self.settings.get("weekday", True))
        wd = now.strftime("%A").upper()
        if fmt_code.startswith("%A") or fmt_code.startswith("%a"):
            wd = ""      # format already includes the weekday
        self.weekday_lbl.setText(wd if show_wd else "")
        self.weekday_lbl.setVisible(bool(wd and show_wd))

    def refresh(self) -> None:
        self._tick()

    def shutdown(self) -> None:
        self._timer.stop()

    def build_settings_form(self, parent) -> QWidget:
        form = QWidget(parent)
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        row = QHBoxLayout()
        row.addWidget(QLabel("Date format"))
        self.fmt = QComboBox()
        for label, code in FORMATS:
            self.fmt.addItem(label, code)
        idx = self.fmt.findData(self.settings.get("format", self.DEFAULT_FORMAT))
        self.fmt.setCurrentIndex(max(0, idx))
        row.addWidget(self.fmt, 1)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Text size"))
        self.sizec = QComboBox()
        for label, val in (("Small", 14), ("Medium", 17), ("Large", 22)):
            self.sizec.addItem(label, val)
        idx = self.sizec.findData(int(self.settings.get("font_size", 17)))
        self.sizec.setCurrentIndex(max(0, idx))
        row2.addWidget(self.sizec, 1)
        lay.addLayout(row2)

        from ..widgets_common import NovaCheckBox
        self.wd_chk = NovaCheckBox("Show weekday line")
        self.wd_chk.setChecked(bool(self.settings.get("weekday", True)))
        lay.addWidget(self.wd_chk)
        lay.addStretch(1)

        def apply() -> None:
            self.settings["format"] = self.fmt.currentData()
            self.settings["font_size"] = self.sizec.currentData()
            self.settings["weekday"] = self.wd_chk.isChecked()

        form.apply = apply  # type: ignore[attr-defined]
        return form
