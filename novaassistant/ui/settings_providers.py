"""Settings — provider key management rows (Groq / Deepgram, multi-key)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QSizePolicy, QWidget,
)

from .. import theme
from ..providers import deepgram, groq
from .widgets_common import TagPill


class KeyRow(QWidget):
    """One managed API key: enabled / name / masked key / Test / Use-for / Remove."""

    changed = Signal()
    removed = Signal(str)
    use_requested = Signal(str, str)       # (key_id, purpose)
    status_message = Signal(str, bool)     # (message, ok)

    def __init__(self, entry: dict, provider: str, purposes: list[str],
                 active_map: dict[str, str]):
        super().__init__()
        self.entry = entry
        self.provider = provider
        self.purposes = purposes
        self._revealed = False
        theme.set_style(self, 
            f"background: #0d0d10; border: 1px solid #22232b; border-radius: 8px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(8)

        self.enabled = QCheckBox()
        self.enabled.setFixedSize(20, 20)
        theme.set_style(self.enabled, f"""
            QCheckBox {{ background: transparent; border: none; padding: 0; }}
            QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
                border: 1px solid #3f3f46; background: #0d0d10; }}
            QCheckBox::indicator:hover {{ border-color: #71717a; }}
            QCheckBox::indicator:checked {{ background: {theme.FOCUS_RING};
                border-color: {theme.FOCUS_RING}; }}
        """)
        self.enabled.setChecked(entry.get("enabled", True))
        self.enabled.setToolTip("Enable / disable this key")
        self.enabled.toggled.connect(self._persist)
        lay.addWidget(self.enabled)

        self.name_input = QLineEdit(entry.get("name", ""))
        self.name_input.setPlaceholderText("Custom name")
        self.name_input.setMinimumWidth(70)
        self.name_input.setMaximumWidth(130)
        theme.set_style(self.name_input, _input_qss())
        self.name_input.editingFinished.connect(self._persist)
        lay.addWidget(self.name_input)

        self.key_input = QLineEdit(_mask(entry.get("key", "")))
        self.key_input.setReadOnly(True)
        self.key_input.setMinimumWidth(90)
        self.key_input.setMaximumWidth(220)
        theme.set_style(self.key_input, _input_qss() + "color: #a1a1aa;")
        lay.addWidget(self.key_input)

        eye = QPushButton()
        eye.setFixedSize(26, 26)
        eye.setIcon(_eye_icon(False))
        eye.setToolTip("Toggle visibility")
        eye.setCursor(Qt.PointingHandCursor)
        theme.set_style(eye, _icon_qss())
        eye.clicked.connect(self._toggle_reveal)
        lay.addWidget(eye)

        test_btn = QPushButton("Test")
        test_btn.setProperty("variant", "chip")
        test_btn.setFixedHeight(26)
        test_btn.setCursor(Qt.PointingHandCursor)
        test_btn.clicked.connect(self._test)
        lay.addWidget(test_btn)

        self._status = TagPill("—")
        self._status.setFixedHeight(26)
        self._status.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        theme.set_style(self._status, 
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            f"background: #101116; border: 1px solid {theme.BORDER};"
            "border-radius: 4px; padding: 2px 8px;")
        lay.addWidget(self._status)

        lay.addStretch(1)

        for purpose, label in purposes:
            use_btn = QPushButton(label)
            use_btn.setProperty("variant", "chip")
            use_btn.setCursor(Qt.PointingHandCursor)
            is_active = active_map.get(purpose) == entry["id"]
            if is_active:
                use_btn.setText("✓ " + label)
                theme.set_style(use_btn, 
                    f"QPushButton {{ background: rgba(16,185,129,0.12); color: {theme.EMERALD};"
                    f" border: 1px solid rgba(16,185,129,0.4); border-radius: 6px;"
                    "padding: 5px 10px; font-size: 11px; }")
            use_btn.clicked.connect(
                lambda _=False, k=entry["id"], p=purpose: self.use_requested.emit(k, p))
            lay.addWidget(use_btn)

        rm = QPushButton()
        rm.setFixedSize(26, 26)
        from .. import icons
        rm.setIcon(icons.icon("trash", theme.GHOST, 13))
        rm.setToolTip("Remove key")
        rm.setCursor(Qt.PointingHandCursor)
        theme.set_style(rm, _icon_qss())
        rm.clicked.connect(lambda: self.removed.emit(entry["id"]))
        lay.addWidget(rm)

    # ------------------------------------------------------------ slots
    def _persist(self) -> None:
        self.changed.emit()

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        cfg_key = self.entry.get("key", "")
        self.key_input.setText(cfg_key if self._revealed else _mask(cfg_key))
        for btn in self.findChildren(QPushButton):
            if btn.toolTip() == "Toggle visibility":
                btn.setIcon(_eye_icon(self._revealed))

    def _test(self) -> None:
        key = self.entry.get("key", "")
        self._status.setText("testing…")
        theme.set_style(self._status, 
            f"color: #F59E0B; font-size: 10px; font-family: {theme.FONT_MONO};"
            f"background: rgba(245,158,11,0.10); border: 1px solid rgba(245,158,11,0.35);"
            "border-radius: 4px; padding: 2px 8px;")

        def work():
            if self.provider == "groq":
                ok, msg = groq.test_key(key)
            else:
                ok, msg = deepgram.test_key(key)

            def apply():
                color = theme.EMERALD if ok else theme.RED_TEXT
                bg = "rgba(16,185,129,0.10)" if ok else "rgba(239,68,68,0.10)"
                bd = "rgba(16,185,129,0.4)" if ok else "rgba(239,68,68,0.35)"
                self._status.setText(msg[:42])
                theme.set_style(self._status, 
                    f"color: {color}; font-size: 10px; font-family: {theme.FONT_MONO};"
                    f"background: {bg}; border: 1px solid {bd};"
                    "border-radius: 4px; padding: 2px 8px;")
                self.status_message.emit(
                    ("Key valid — " if ok else "Key test failed — ") + msg, ok)

            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, apply)

        import threading
        threading.Thread(target=work, daemon=True).start()


def _eye_icon(revealed: bool):
    from .. import icons
    return icons.icon("eye" if not revealed else "eye-off", theme.GHOST, 13)


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return key[:2] + "•" * 8
    return key[:6] + "•" * 28 + key[-4:]


def _input_qss() -> str:
    return (f"QLineEdit {{ background: #0c0c0e; border: 1px solid #22232b;"
            f" border-radius: 6px; font-size: 11px; font-family: {theme.FONT_MONO};"
            f" color: {theme.TEXT_BRIGHT}; padding: 5px 8px; }}")


def _icon_qss() -> str:
    return ("QPushButton { background: transparent; border: none; border-radius: 6px; }"
            "QPushButton:hover { background: #1f1f23; }")


class AddKeyRow(QWidget):
    """Inline add-key form (name + key + Add)."""

    add_requested = Signal(str, str)

    def __init__(self, placeholder: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Name (e.g. Personal, Work)")
        self.name_input.setMinimumWidth(70)
        self.name_input.setMaximumWidth(180)
        theme.set_style(self.name_input, _input_qss())
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText(placeholder)
        theme.set_style(self.key_input, _input_qss())
        add = QPushButton("  Add key")
        add.setProperty("variant", "primary")
        add.setFixedHeight(30)
        from .. import icons
        add.setIcon(icons.icon("plus", theme.BLACK, 13, 2))
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self._emit_add)
        self.key_input.returnPressed.connect(self._emit_add)
        lay.addWidget(self.name_input)
        lay.addWidget(self.key_input, 1)
        lay.addWidget(add)

    def _emit_add(self) -> None:
        key = self.key_input.text().strip()
        if not key:
            return
        self.add_requested.emit(self.name_input.text().strip(), key)
        self.name_input.clear()
        self.key_input.clear()
