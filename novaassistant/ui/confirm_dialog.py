"""Modal confirmation dialog for sensitive tool actions.

The controller's worker thread blocks on a threading.Event; this dialog is
opened on the GUI thread (via a queued signal) and sets the result.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from . import theme


class ConfirmDialog(QDialog):
    def __init__(self, tool_name: str, args: dict, description: str, parent=None) -> None:
        super().__init__(parent)
        self.approved = False
        self.setWindowTitle("Confirm action - Nova")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        title = QLabel("Nova wants to perform an action")
        title.setObjectName("pageHeader")
        layout.addWidget(title)

        desc = QLabel(description)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        info = QLabel(f"Tool: {tool_name}")
        info.setStyleSheet(f"color: {theme.DIM}; font-size: 12px;")
        layout.addWidget(info)

        args_box = QPlainTextEdit()
        args_box.setReadOnly(True)
        args_box.setMaximumHeight(140)
        try:
            args_box.setPlainText(json.dumps(args, indent=2, ensure_ascii=False)[:2000])
        except Exception:
            args_box.setPlainText(str(args)[:2000])
        layout.addWidget(args_box)

        note = QLabel("Nothing happens until you approve. You can change how often "
                      "Nova asks in Settings.")
        note.setObjectName("hintLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        deny = QPushButton("Deny")
        deny.setObjectName("dangerButton")
        approve = QPushButton("Approve")
        approve.setObjectName("approveButton")
        approve.setDefault(True)
        buttons.addWidget(deny)
        buttons.addWidget(approve)
        layout.addLayout(buttons)

        deny.clicked.connect(self.reject)
        approve.clicked.connect(self._approve)

    def _approve(self) -> None:
        self.approved = True
        self.accept()

    @staticmethod
    def request(parent, tool_name: str, args: dict, description: str) -> bool:
        dlg = ConfirmDialog(tool_name, args, description, parent)
        dlg.exec()
        return dlg.approved
