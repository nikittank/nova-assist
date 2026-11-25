"""Chat message bubbles used by the conversation page."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

MAX_BUBBLE_WIDTH = 560

ROLE_NAMES = {
    "user": "You",
    "assistant": "Nova",
    "tool": "Tool",
    "error": "Error",
    "system": "System",
}
FRAME_IDS = {
    "user": "bubbleUser",
    "assistant": "bubbleAssistant",
    "tool": "bubbleTool",
    "error": "bubbleError",
    "system": "bubbleTool",
}


class MessageBubble(QFrame):
    def __init__(self, role: str, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.role = role
        self.setObjectName(FRAME_IDS.get(role, "bubbleAssistant"))
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        self.setMaximumWidth(MAX_BUBBLE_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(3)

        header = QLabel(ROLE_NAMES.get(role, role)
                        + "  \u00b7  " + datetime.now().strftime("%H:%M"))
        header.setObjectName("bubbleRole")
        layout.addWidget(header)

        self.text_label = QLabel(text)
        self.text_label.setObjectName("bubbleText" if role in ("user", "assistant")
                                     else ("errorText" if role == "error" else "toolText"))
        self.text_label.setWordWrap(True)
        self.text_label.setTextFormat(Qt.PlainText)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.text_label)

    def set_text(self, text: str) -> None:
        self.text_label.setText(text)


class ChatStream:
    """Keeps bubble references while the assistant reply is streaming."""

    def __init__(self, layout: QVBoxLayout) -> None:
        self.layout = layout
        self._stretch = layout.itemAt(layout.count() - 1)

    def add(self, role: str, text: str = "") -> MessageBubble:
        bubble = MessageBubble(role, text)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        wrapper = QFrame()
        wrapper.setLayout(row)
        wrapper.setStyleSheet("background: transparent;")
        self.layout.insertWidget(self.layout.count() - 1, wrapper)
        return bubble

    def scroll_to_bottom(self, scrollarea) -> None:
        bar = scrollarea.verticalScrollBar()
        bar.setValue(bar.maximum())
