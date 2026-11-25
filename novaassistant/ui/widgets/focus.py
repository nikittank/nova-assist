"""Focus widget — the single task currently being worked on.

Requirement #8: the always-visible Clear button is GONE. Focus primarily
shows the current focus. Editing happens through the widget's Edit button /
settings dialog, where the user can change the focus, update the content
and save. Clear lives inside that dialog rather than as a permanent button.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from ... import icons, theme
from .base import WidgetBase

CONFIG_KEY = "widgets.focus_text"


class FocusEditDialog(QDialog):
    """Modal-style edit dialog for the Focus widget.

    Lets the user change the focus text, update the content (multi-line),
    save, or clear (Clear lives here, not as a permanent widget button).
    """

    def __init__(self, current_text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Focus")
        self.setModal(True)
        self.setMinimumWidth(380)
        theme.set_style(self,
            f"background: {theme.PANEL_2}; border: 1px solid {theme.BORDER_2};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        cap = QLabel("What are you working on?")
        theme.set_style(cap,
            f"color: {theme.WHITE}; font-size: 13px; font-weight: 600;"
            "border: none; background: transparent;")
        lay.addWidget(cap)

        desc = QLabel("Set your current focus. It will stay visible on the "
                      "widget until you change or clear it.")
        desc.setWordWrap(True)
        theme.set_style(desc,
            f"color: {theme.MUTED}; font-size: 11px;"
            "border: none; background: transparent;")
        lay.addWidget(desc)

        self.input = QTextEdit()
        self.input.setPlainText(current_text)
        self.input.setMinimumHeight(80)
        self.input.setReadOnly(False)
        self.input.setEnabled(True)
        theme.set_style(self.input,
            f"QTextEdit {{ background: {theme.BLACK}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 8px 10px; font-size: 12px;"
            f" color: {theme.TEXT_BRIGHT}; selection-color: {theme.WHITE};"
            f" selection-background-color: {theme.FOCUS_RING}; }}")
        lay.addWidget(self.input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.clear_btn = QPushButton(" Clear")
        self.clear_btn.setProperty("variant", "danger")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setIcon(icons.icon("trash", theme.GHOST, 13))
        theme.set_style(self.clear_btn,
            f"QPushButton {{ background: rgba(239,68,68,0.12);"
            f" color: {theme.RED_TEXT}; border: 1px solid rgba(239,68,68,0.3);"
            "border-radius: 8px; padding: 7px 14px; font-size: 12px; }}"
            "QPushButton:hover { background: rgba(239,68,68,0.18); }")
        self.clear_btn.clicked.connect(self._clear)
        self.save_btn = QPushButton("  Save")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.setEnabled(True)
        self.save_btn.setDefault(True)
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setIcon(icons.icon("check", theme.BLACK, 13, 2))
        theme.set_style(self.save_btn,
            f"QPushButton {{ background: {theme.WHITE}; color: {theme.BLACK};"
            " border: none; border-radius: 8px; padding: 8px 16px;"
            " font-size: 12px; font-weight: 600; }"
            f"QPushButton:hover {{ background: #e5e5e5; }}")
        self.save_btn.clicked.connect(self._save)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setProperty("variant", "ghost")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addWidget(self.save_btn)
        lay.addLayout(btn_row)

        self._cleared = False
        self._result_text = current_text
        QTimer.singleShot(0, self.input.setFocus)

    def _save(self) -> None:
        self._cleared = False
        self._result_text = self.input.toPlainText().strip()
        self.accept()

    def _clear(self) -> None:
        self._cleared = True
        self._result_text = ""
        self.accept()

    @property
    def result_text(self) -> str:
        return self._result_text

    @property
    def cleared(self) -> bool:
        return self._cleared


class FocusWidget(WidgetBase):
    title = "FOCUS"
    icon_name = "focus"
    default_size = (260, 140)
    min_size = (170, 100)

    # ------------------------------------------------------------- content
    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.text_lbl = QLabel(self._focus_text() or "No focus set")
        self.text_lbl.setWordWrap(True)
        theme.set_style(self.text_lbl,
            f"color: {theme.WHITE if self._focus_text() else theme.GHOST};"
            " font-size: 15px; font-weight: 600; border: none;"
            "background: transparent;")
        lay.addWidget(self.text_lbl, 1)

        # The always-visible Clear button is GONE (requirement #8).
        # Editing (change / save / clear) happens through the Edit button
        # provided by WidgetBase chrome, which opens FocusEditDialog.
        return holder

    def _focus_text(self) -> str:
        return str(self.ctx.config.get(CONFIG_KEY, "") or "")

    # ------------------------------------------------------------ actions
    def edit_content(self) -> bool:
        """Edit button: open the FocusEditDialog so the user can change
        the focus, save updates, or clear it (all in one place)."""
        dlg = FocusEditDialog(self._focus_text(), parent=self)
        if dlg.exec() == QDialog.Accepted:
            text = dlg.result_text
            self.ctx.config.set(CONFIG_KEY, text, save=True)
            self.ctx.config.save()
            self._render(text)
            self.refresh()
            return True
        return True   # consumed the click either way

    def _render(self, text: str) -> None:
        self.text_lbl.setText(text or "No focus set")
        theme.set_style(self.text_lbl,
            f"color: {theme.WHITE if text else theme.GHOST};"
            " font-size: 15px; font-weight: 600; border: none;"
            "background: transparent;")

    def refresh(self) -> None:
        self._render(self._focus_text())

    def build_settings_form(self, parent) -> QWidget:
        form = QWidget(parent)
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel("Placeholder hint"))
        self.ph = QLineEdit(self.settings.get("placeholder",
                                              "What are you working on?"))
        row.addWidget(self.ph, 1)
        lay.addLayout(row)
        # also offer an inline Clear inside the settings form, so users who
        # open the gear can clear without the modal dialog if they prefer
        clear_inline = QPushButton("Clear focus")
        clear_inline.setProperty("variant", "danger")
        clear_inline.setCursor(Qt.PointingHandCursor)
        clear_inline.clicked.connect(lambda: (
            self.ctx.config.set(CONFIG_KEY, ""),
            self._render(""),
        ))
        lay.addWidget(clear_inline)
        lay.addStretch(1)

        def apply() -> None:
            self.settings["placeholder"] = self.ph.text().strip() or \
                "What are you working on?"

        form.apply = apply  # type: ignore[attr-defined]
        return form
