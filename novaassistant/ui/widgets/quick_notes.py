"""Quick Notes widget — fast note capture into the real Notes store.

Requirement #9: this widget uses the SAME notes database/system as the
Notes page (self.ctx.notes) — there is NO separate Quick Notes storage.

If the user types:
    # Project Meeting
    Discuss API integration with the team tomorrow.

Then 'Project Meeting' becomes the note title and everything after it
becomes the note content. The widget also displays the most recent notes
saved through the Notes page (live mirror of ctx.notes.all()).

If no leading '# Title' is present, the first non-empty line becomes the
title and the rest becomes the content (the previous behavior, kept as a
fallback so casual capture still works).
"""
from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ... import icons, theme
from ..widgets_common import FixedRowsHost, RowsScroll, ScrollArea, style_scoped
from .base import WidgetBase

_TITLE_RE = re.compile(r"^\s*#\s*(.+?)\s*$", re.MULTILINE)


def _parse_quick_note(text: str) -> tuple[str, str]:
    """Return (title, content) from a free-text quick-note input.

    Recognizes a leading '# Title' marker. If absent, the first non-empty
    line becomes the title and the remaining lines become the content.
    """
    text = (text or "").strip()
    if not text:
        return "", ""
    m = _TITLE_RE.search(text)
    if m:
        title = m.group(1).strip()
        # everything after the title marker line is the content
        end = m.end()
        # advance to the next newline
        nl = text.find("\n", end)
        content = text[nl + 1:].strip() if nl >= 0 else ""
        return title[:120], content
    # fallback: first non-empty line is the title, rest is content
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "", ""
    if len(lines) == 1:
        return lines[0][:120], ""
    return lines[0][:120], "\n".join(lines[1:])


class QuickNotesWidget(WidgetBase):
    title = "QUICK NOTES"
    icon_name = "note"
    default_size = (300, 300)
    min_size = (240, 270)

    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)

        self.input = QTextEdit()
        self.input.setPlaceholderText(
            "# Title\nNote content goes here…")
        self.input.setFixedHeight(64)
        theme.set_style(self.input,
            f"QTextEdit {{ background: {theme.BLACK}; border: 1px solid {theme.BORDER};"
            f" border-radius: 8px; padding: 6px 9px; font-size: 12px;"
            f" color: {theme.TEXT_BRIGHT}; }}")
        lay.addWidget(self.input)

        # hint row — teach the user the '# Title' format
        hint = QLabel("Tip: start with '# Title' to set the note title")
        theme.set_style(hint,
            f"color: {theme.GHOST}; font-size: 10px;"
            f"font-family: {theme.FONT_MONO}; border: none;"
            "background: transparent;")
        hint.setWordWrap(False)
        lay.addWidget(hint)

        row = QHBoxLayout()
        row.addStretch(1)
        self.save_btn = self._row_button("Save Note", primary=True)
        theme.set_style(self.save_btn,
            f"QPushButton {{ background: {theme.WHITE}; color: {theme.BLACK};"
            " border: none; border-radius: 6px; padding: 6px 12px;"
            " font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { background: #e5e5e5; }")
        self.save_btn.setIcon(icons.icon("plus", theme.BLACK, 12, 2))
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.save_btn)
        lay.addLayout(row)

        self.list_hint = self._caption("RECENT")
        lay.addWidget(self.list_hint)

        self.rows_host = FixedRowsHost(spacing=6)
        self.rows_scroll = RowsScroll(self.rows_host)
        lay.addWidget(self.rows_scroll, 1)
        return holder

    def _save(self) -> None:
        text = self.input.toPlainText().strip()
        if not text:
            return
        title, content = _parse_quick_note(text)
        if not title:
            # nothing usable — bail without creating an empty note
            return
        topic = str(self.settings.get("topic", "note") or "note")
        try:
            # uses the SAME notes store as the Notes page (ctx.notes).
            # No separate Quick Notes storage system exists.
            self.ctx.notes.create(title, content, topic)
        except Exception:
            pass
        self.input.clear()
        self.refresh()

    def refresh(self) -> None:
        self.rows_host.clear_rows()
        try:
            notes = self.ctx.notes.all()
        except Exception:
            notes = []
        max_n = int(self.settings.get("max_recent", 3))
        for note in notes[:max_n]:
            row = QLabel(f"›  {note['title'][:32]}")
            row.setToolTip(note.get("content", "")[:160] or note["title"])
            theme.set_style(row,
                f"color: {theme.TEXT}; font-size: 11px; border: none;"
                "background: transparent;")
            self.rows_host.add_row(row)
        if not notes:
            empty = self._empty("No notes yet — type '# Title' above and press Save.")
            self.rows_host.add_row(empty)
        self.rows_scroll.refresh()

    def edit_content(self) -> bool:
        self.input.setFocus()
        return True

    def build_settings_form(self, parent) -> QWidget:
        form = QWidget(parent)
        from PySide6.QtWidgets import QSpinBox
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Recent notes shown"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 8)
        self.spin.setValue(int(self.settings.get("max_recent", 3)))
        row1.addWidget(self.spin, 1)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Topic tag"))
        self.topic = QPushButton(self.settings.get("topic", "note"))
        self.topic.setProperty("variant", "chip")
        self.topic.setCursor(self.cursor())
        self.topic.clicked.connect(self._pick_topic)
        row2.addWidget(self.topic, 1)
        lay.addLayout(row2)
        lay.addStretch(1)

        def apply() -> None:
            self.settings["max_recent"] = self.spin.value()

        form.apply = apply  # type: ignore[attr-defined]
        return form

    def _pick_topic(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Topic tag", "Tag used for quick notes:",
            text=self.settings.get("topic", "note"))
        if ok and text.strip():
            self.settings["topic"] = text.strip().lower()
            self.topic.setText(self.settings["topic"])
