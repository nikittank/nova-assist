"""Activity page: everything Nova did on the system, newest first."""

from __future__ import annotations

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

KIND_ICONS = {
    "tool": "\u2699",
    "note": "\U0001f4dd",
    "reminder": "\u23f0",
    "error": "\u26a0",
    "denied": "\u26d4",
}


class ActivityPage(QWidget):
    def __init__(self, controller, bus, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.bus = bus

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Activity")
        title.setObjectName("pageHeader")
        header.addWidget(title)
        header.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        clear_btn = QPushButton("Clear log")
        clear_btn.setObjectName("dangerButton")
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)
        root.addLayout(header)

        self.list = QListWidget()
        self.list.setObjectName("listPanel")
        root.addWidget(self.list, 1)

        hint = QLabel("Every tool action, note and reminder is logged locally here.")
        hint.setObjectName("hintLabel")
        root.addWidget(hint)

        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for row in self.controller.db.recent_activity(limit=300):
            icon = KIND_ICONS.get(row["kind"], "\u2022")
            status = row.get("status") or "ok"
            item = QListWidgetItem(f"{row['ts']}  {icon} {row['kind']}  [{status}]\n"
                                   f"{row.get('detail') or ''}")
            self.list.addItem(item)

    def _clear(self) -> None:
        self.controller.db.clear_activity()
        self.refresh()
