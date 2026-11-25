"""Conversation page: message stream, text input, mic control, attachments.

Keyboard behaviour (see novaassistant/shortcuts.py):
  * Enter              -> send the message
  * Shift+Enter        -> insert a newline
  * Ctrl+Enter         -> send (also handled app-wide)
  * the input never swallows shortcuts needed elsewhere
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout,
                               QWidget)

from . import theme
from .bubbles import ChatStream


class ChatInput(QTextEdit):
    """Message input: Enter sends, Shift+Enter makes a newline."""

    def __init__(self, on_send) -> None:
        super().__init__()
        self._on_send = on_send
        self.setPlaceholderText("Type a message, or talk to Nova...   "
                                "(Enter = send  ·  Shift+Enter = newline)")
        self.setFixedHeight(64)
        self.setObjectName("chatInput")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)      # newline
            else:
                # plain Enter and Ctrl+Enter both send
                self._on_send()
            return
        super().keyPressEvent(event)


class ChatPage(QWidget):
    def __init__(self, controller, bus, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.bus = bus
        self._stream_bubble = None
        self._stream_text = ""
        self._attachment: dict | None = None
        self._listening = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(10)

        # header ----------------------------------------------------------
        header = QHBoxLayout()
        title = QLabel("Conversation")
        title.setObjectName("pageHeader")
        header.addWidget(title)
        header.addStretch(1)
        self.engine_chip = QLabel()
        self.engine_chip.setObjectName("chipLabel")
        header.addWidget(self.engine_chip)
        self.model_chip = QLabel()
        self.model_chip.setObjectName("chipLabel")
        header.addWidget(self.model_chip)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.setVisible(False)
        self.stop_button.clicked.connect(controller.stop_current)
        header.addWidget(self.stop_button)
        root.addLayout(header)

        # message stream ----------------------------------------------------
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        stream_holder = QWidget()
        stream_holder.setStyleSheet("background: transparent;")
        self.stream_layout = QVBoxLayout(stream_holder)
        self.stream_layout.setContentsMargins(0, 6, 6, 6)
        self.stream_layout.setSpacing(8)
        self.stream_layout.addStretch(1)
        self.scroll.setWidget(stream_holder)
        root.addWidget(self.scroll, 1)
        self.stream = ChatStream(self.stream_layout)

        # attachment chip -----------------------------------------------------
        attach_row = QHBoxLayout()
        self.attach_chip = QLabel()
        self.attach_chip.setObjectName("chipLabel")
        self.attach_chip.setVisible(False)
        attach_row.addWidget(self.attach_chip)
        attach_row.addStretch(1)
        root.addLayout(attach_row)

        # input row ------------------------------------------------------------
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = ChatInput(self._send)
        input_row.addWidget(self.input, 1)

        button_col = QVBoxLayout()
        button_col.setSpacing(6)
        self.attach_button = QPushButton("Attach file")
        self.attach_button.setObjectName("ghostButton")
        self.attach_button.setToolTip("Attach a local file so Nova can explain it")
        self.attach_button.clicked.connect(self._pick_attachment)
        self.mic_button = QPushButton("Listen")
        self.mic_button.setObjectName("micButton")
        self.mic_button.setCheckable(self._ptt_mode() is False)
        self.mic_button.setFixedWidth(150)
        self.mic_button.clicked.connect(self._mic_clicked)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self._send)
        button_col.addWidget(self.mic_button)
        button_col.addWidget(self.attach_button)
        input_row.addLayout(button_col)
        input_row.addWidget(self.send_button)
        root.addLayout(input_row)

        hint = QLabel("Ctrl+Space push-to-talk / toggle mic  ·  Enter or Ctrl+Enter sends  ·  "
                      "Shift+Enter newline  ·  Esc stops Nova")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ONE window-level Ctrl+Enter shortcut (two identical window shortcuts
        # would be ambiguous and neither would fire)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._send)
        self._apply_mode()
        self._refresh_engine_chip()

    # ------------------------------------------------------------ actions
    def _ptt_mode(self) -> bool:
        return self.controller.config.get("listening_mode") == "ptt"

    def _apply_mode(self) -> None:
        ptt = self._ptt_mode()
        self.mic_button.setCheckable(not ptt)
        self.mic_button.setText("Hold to talk" if ptt else "Listen")

    def _refresh_engine_chip(self) -> None:
        tts = "voice on" if self.controller.config.get("tts_enabled") else "voice off"
        self.engine_chip.setText(f"STT {self.controller.stt_engine_name} · {tts}")
        self.model_chip.setText(f"LLM {self.controller.llm_model_name()}")

    def _mic_clicked(self) -> None:
        if self._ptt_mode():
            return  # handled by pressed/released events
        self.controller.toggle_listening()

    def _send(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        attachment, self._attachment = self._attachment, None
        self._update_attach_chip()
        self.add_system_thinking()
        self.controller.send_text(text, attachment)

    def send_from_shortcut(self) -> None:
        """Ctrl+Enter from anywhere in the app."""
        self._send()

    def _pick_attachment(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach a file for Nova to read",
            str(self.controller.config.data_dir()),
            "All files (*.*)")
        if not path:
            return
        result = self.controller.attach_file(path)
        if result.get("ok"):
            self._attachment = {"name": result["name"], "content": result["content"]}
            self._update_attach_chip()
        else:
            self.add_error(result.get("error", "Could not attach file."))

    def _update_attach_chip(self) -> None:
        if self._attachment:
            self.attach_chip.setText(
                f"Attached: {self._attachment['name']} "
                f"(will send with your next message)")
            self.attach_chip.setVisible(True)
        else:
            self.attach_chip.setVisible(False)

    # mic pressed/released for push-to-talk (wired by MainWindow) ----------
    def mic_pressed(self) -> None:
        if self._ptt_mode():
            self.controller.ptt_start()

    def mic_released(self) -> None:
        if self._ptt_mode():
            self.controller.ptt_stop()

    # ------------------------------------------------------------- stream
    def _defer_scroll(self) -> None:
        QTimer.singleShot(0, lambda: self.stream.scroll_to_bottom(self.scroll))

    def add_user_message(self, text: str, attachment: dict | None = None) -> None:
        label = text
        if attachment:
            label = f"[attached: {attachment.get('name', 'file')}]\n{text}"
        self.stream.add("user", label)
        self._stream_bubble = None
        self._stream_text = ""
        self._defer_scroll()

    def add_system_thinking(self) -> None:
        return  # status pill already communicates this

    def append_assistant_delta(self, text: str) -> None:
        self._stream_text += text
        if self._stream_bubble is None:
            self._stream_bubble = self.stream.add("assistant")
        self._stream_bubble.set_text(self._stream_text)
        self._defer_scroll()

    def finish_assistant(self, text: str) -> None:
        if not text:
            return
        if self._stream_bubble is not None:
            self._stream_bubble.set_text(text)
        else:
            self.stream.add("assistant", text)
        self._stream_bubble = None
        self._stream_text = ""
        self._defer_scroll()

    def add_tool_call(self, name: str, args_repr: str) -> None:
        self.stream.add("tool", f"\u2699  {name}({args_repr[:160]})")
        self._defer_scroll()

    def add_tool_result(self, name: str, summary: str, ok: bool) -> None:
        mark = "\u2713" if ok else "\u2717"
        self.stream.add("tool", f"{mark}  {summary[:200]}")
        self._defer_scroll()

    def add_system(self, text: str) -> None:
        self.stream.add("tool", text)
        self._defer_scroll()

    def add_error(self, text: str) -> None:
        self.stream.add("error", text)
        self._defer_scroll()

    def load_history(self, messages: list[dict]) -> None:
        for m in messages:
            role = "assistant" if m["role"] == "assistant" else "user"
            self.stream.add(role, m["content"])
        self._defer_scroll()

    # ------------------------------------------------------------- state
    def set_listening(self, on: bool) -> None:
        self._listening = bool(on)
        ptt = self._ptt_mode()
        if ptt:
            self.mic_button.setText("Hold to talk" if not on else "Mic live")
        else:
            self.mic_button.setChecked(bool(on))
            self.mic_button.setText("Stop listening" if on else "Listen")

    def set_status(self, status: str) -> None:
        self.stop_button.setVisible(status in ("processing", "speaking"))

    def set_mode_changed(self) -> None:
        self._apply_mode()
        self.set_listening(self._listening)

    def refresh_chips(self) -> None:
        self._refresh_engine_chip()
