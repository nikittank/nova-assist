"""Clock widget — shows ONLY the current time (configurable format)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ... import theme
from ..widgets_common import style_scoped
from .base import WidgetBase


class ClockWidget(WidgetBase):
    title = "CLOCK"
    icon_name = "clock"
    default_size = (240, 140)
    min_size = (150, 96)

    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        style_scoped(holder, "ClockContent", "background: transparent;")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.time_lbl = QLabel("--:--")
        self.time_lbl.setAlignment(Qt.AlignCenter)
        lay.addStretch(1)
        lay.addWidget(self.time_lbl)
        lay.addStretch(1)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()
        return holder

    def _tick(self) -> None:
        now = datetime.now()
        fmt = self.settings.get("format", "12h")
        seconds = bool(self.settings.get("seconds", False))
        if fmt == "24h":
            text = now.strftime("%H:%M" + (":%S" if seconds else ""))
        else:
            base = "%I:%M" + (":%S" if seconds else "") + " %p"
            text = now.strftime(base)
            if text.startswith("0"):
                text = text[1:]
        self.time_lbl.setText(text)
        size = 20 if self.compact else int(self.settings.get("font_size", 34))
        theme.set_style(self.time_lbl, 
            f"color: {theme.WHITE}; font-size: {size}px; font-weight: 300;"
            f"font-family: {theme.FONT_MONO}; border: none;"
            "background: transparent;")

    def refresh(self) -> None:
        self._tick()

    def shutdown(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------- settings
    def build_settings_form(self, parent) -> QWidget:
        form = QWidget(parent)
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Clock format"))
        self.fmt = QComboBox()
        self.fmt.addItem("12-hour (AM/PM)", "12h")
        self.fmt.addItem("24-hour", "24h")
        self.fmt.setCurrentIndex(0 if self.settings.get("format", "12h") == "12h" else 1)
        row1.addWidget(self.fmt, 1)
        lay.addLayout(row1)

        self.secs = QCheckBox("Show seconds")
        self.secs.setChecked(bool(self.settings.get("seconds", False)))
        lay.addWidget(self.secs)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Text size"))
        self.sizec = QComboBox()
        for label, val in (("Small", 24), ("Medium", 34), ("Large", 46)):
            self.sizec.addItem(label, val)
        idx = self.sizec.findData(int(self.settings.get("font_size", 34)))
        self.sizec.setCurrentIndex(max(0, idx))
        row2.addWidget(self.sizec, 1)
        lay.addLayout(row2)
        lay.addStretch(1)

        def apply() -> None:
            self.settings["format"] = self.fmt.currentData()
            self.settings["seconds"] = self.secs.isChecked()
            self.settings["font_size"] = self.sizec.currentData()

        form.apply = apply  # type: ignore[attr-defined]
        return form
