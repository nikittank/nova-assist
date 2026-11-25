"""Notes page — list + editor split view (mockup-exact).

FIX: editing an existing note and pressing Save UPDATES that exact note.
`self._editing_id` tracks which note is loaded; Save routes to
store.update(editing_id) — never create().
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from .. import icons, theme
from ..core.notes_store import NotesStore
from .widgets_common import FixedRowsHost, RowsScroll, icon_button, style_scoped

from datetime import datetime


def _fmt_ts(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


class NoteCard(QFrame):
    """Clickable note card containing the NoteRow content."""

    clicked = Signal(str)

    def __init__(self, note: dict, parent=None):
        super().__init__(parent)
        self.note = note
        self._selected = False
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.row = NoteRow(note)
        lay.addWidget(self.row)
        self.paint_note(False)
        # pin after layout install (layout creation resets prior constraints)
        self.setFixedHeight(max(64, self.sizeHint().height()))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.note["id"])
        super().mousePressEvent(event)

    def paint_note(self, selected: bool) -> None:
        self._selected = selected
        if selected:
            theme.set_style(self, 
                "QFrame { background: #111111; border: none; }")
        else:
            theme.set_style(self, 
                "QFrame { background: #000000; border: none; }"
                "QFrame:hover { background: #0c0c0c; }")

    def refresh(self, selected: bool) -> None:
        self.paint_note(selected)


class NoteRow(QWidget):
    """Card content: timestamp + [topic] header, title preview."""

    def __init__(self, note: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        head = QHBoxLayout()
        ts = QLabel(_fmt_ts(note["updated_at"]))
        theme.set_style(ts, f"color: #6b7280; font-size: 11px; font-family: {theme.FONT_MONO};")
        topic = QLabel(f"[{note['topic']}]")
        theme.set_style(topic, 
            f"color: {theme.MUTED}; font-size: 11px; font-family: {theme.FONT_MONO};")
        head.addWidget(ts)
        head.addStretch(1)
        head.addWidget(topic)
        title = QLabel(note["title"])
        theme.set_style(title, f"color: {theme.TEXT}; font-size: 13px; font-weight: 500;")
        head2 = QHBoxLayout()
        head2.addWidget(title)
        head2.addStretch(1)
        lay.addLayout(head)
        lay.addLayout(head2)


class NotesPage(QWidget):
    status_message = Signal(str)
    store_changed = Signal()          # queued-safe rebuild from any thread

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._editing_id: str | None = None   # None => new note
        self._cards: dict[str, tuple[NoteCard, NoteRow]] = {}
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(0)

        # header -----------------------------------------------------------
        head = QHBoxLayout()
        title = QLabel("Notes")
        theme.set_style(title, f"color: {theme.WHITE}; font-size: 20px; font-weight: 700;")
        head.addWidget(title)
        head.addStretch(1)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notes…")
        self.search.setMinimumWidth(140)
        self.search.setFixedHeight(34)
        self.search.setMaximumWidth(320)
        self.search.addAction(icons.icon("search", "#6b7280", 14),
                              QLineEdit.LeadingPosition)
        self.search.textChanged.connect(self._rebuild_list)
        self.search.returnPressed.connect(self._focus_first_result)
        head.addWidget(self.search, 1)

        search_btn = QPushButton("Search")
        search_btn.setProperty("variant", "ghost")
        search_btn.setCursor(Qt.PointingHandCursor)
        search_btn.clicked.connect(lambda: self._rebuild_list())
        head.addWidget(search_btn)

        new_btn = QPushButton("  New note")
        new_btn.setProperty("variant", "primary")
        new_btn.setIcon(icons.icon("plus", theme.BLACK, 14, 2))
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self.new_note)
        head.addWidget(new_btn)
        root.addLayout(head)

        root.addSpacing(14)

        # split -------------------------------------------------------------
        self.body_splitter = QSplitter(Qt.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)
        theme.set_style(self.body_splitter, 
            "QSplitter::handle { background: transparent; width: 6px; }")
        self.body_splitter.setContentsMargins(0, 16, 0, 0)
        root.addWidget(self.body_splitter, 1)

        # left: list
        list_panel = QWidget()
        style_scoped(list_panel, "PanelBox",
                     f"background: {theme.PANEL}; border: none;")
        lp = QVBoxLayout(list_panel)
        lp.setContentsMargins(12, 12, 12, 12)
        lp.setSpacing(10)
        self.rows_host = FixedRowsHost(spacing=10)
        self.list_scroll = RowsScroll(self.rows_host)
        lp.addWidget(self.list_scroll)
        list_panel.setMinimumWidth(230)
        list_panel.setMaximumWidth(460)
        self.body_splitter.addWidget(list_panel)

        # right: editor
        editor = QWidget()
        style_scoped(editor, "EditorPanel",
                     f"background: {theme.PANEL}; border: none;")
        ep = QVBoxLayout(editor)
        ep.setContentsMargins(20, 20, 20, 16)
        ep.setSpacing(0)

        title_row = QHBoxLayout()
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Note Title")
        theme.set_style(self.title_input, 
            f"QLineEdit {{ background: transparent; border: none; font-size: 18px;"
            f" font-weight: 700; color: {theme.WHITE}; padding: 2px 0 10px 0; }}")
        self.title_input.returnPressed.connect(self._title_enter)
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        self.title_input.setFont(f)
        title_row.addWidget(self.title_input, 1)

        topic_lbl = QLabel("topic")
        theme.set_style(topic_lbl, 
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "margin-right: 6px;")
        self.topic_input = QLineEdit()
        self.topic_input.setPlaceholderText("bucket")
        self.topic_input.setFixedSize(110, 28)
        theme.set_style(self.topic_input, 
            f"QLineEdit {{ background: #0d0d10; border: 1px solid #22232b;"
            f" border-radius: 6px; font-size: 11px; font-family: {theme.FONT_MONO};"
            f" color: {theme.TEXT_BRIGHT}; padding: 4px 8px; }}")
        title_row.addWidget(topic_lbl)
        title_row.addWidget(self.topic_input)
        ep.addLayout(title_row)

        sep = QFrame()
        sep.setFixedHeight(1)
        theme.set_style(sep, "background: #1a1a24;")
        ep.addWidget(sep)

        self.content = QTextEditCustom()
        self.content.setPlaceholderText("Start typing your note here…")
        self.content.save_requested.connect(self.save_note)
        self.content.cancel_requested.connect(self._cancel_edit)
        ep.addSpacing(12)
        ep.addWidget(self.content, 1)

        ep.addSpacing(12)
        foot_sep = QFrame()
        foot_sep.setFixedHeight(1)
        theme.set_style(foot_sep, "background: #1a1a24;")
        ep.addWidget(foot_sep)
        ep.addSpacing(10)

        foot = QHBoxLayout()
        hint = QLabel('Notes are stored locally. You can also say: "take a note that …"')
        theme.set_style(hint, f"color: {theme.GHOST}; font-style: italic; font-size: 11px;")
        foot.addWidget(hint)
        foot.addStretch(1)
        self.delete_btn = QPushButton("  Delete")
        self.delete_btn.setProperty("variant", "danger")
        self.delete_btn.setIcon(icons.icon("trash", theme.GHOST, 14))
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.clicked.connect(self.delete_current)
        self.save_btn = QPushButton("  Save")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.setIcon(icons.icon("save", theme.BLACK, 14, 2))
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.clicked.connect(self.save_note)
        self.mode_lbl = QLabel("NEW NOTE")
        theme.set_style(self.mode_lbl, 
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; margin-right: 8px;")
        foot.addWidget(self.mode_lbl)
        foot.addWidget(self.delete_btn)
        foot.addWidget(self.save_btn)
        ep.addLayout(foot)
        editor.setMinimumWidth(360)
        self.body_splitter.addWidget(editor)
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        try:
            self.body_splitter.setSizes([320, 640])
        except Exception:
            pass

        self.notes: NotesStore = ctx.notes
        self.notes.add_listener(self._on_store_event)
        self.store_changed.connect(self._rebuild_list)
        self._rebuild_list()
        self.new_note(silent=True)

        # one font everywhere: same typeface as the sidebar/technical UI
        theme.apply_unified_font(self)

    # ------------------------------------------------------------ helpers
    def _title_enter(self) -> None:
        self.content.setFocus()
        self.content.moveCursor(QTextCursor.Start)

    def _focus_first_result(self) -> None:
        if self._cards:
            first = next(iter(self._cards.values()))[0]
            self._select(first.note["id"])

    def _on_store_event(self, event: str, _note=None) -> None:
        # may fire from worker threads (LLM tools) — signal hops to main thread
        self.store_changed.emit()

    def _rebuild_list(self) -> None:
        query = self.search.text() if hasattr(self, "search") else ""
        notes = self.notes.search(query)
        self.rows_host.clear_rows()
        self._cards.clear()
        for note in notes:
            card = NoteCard(note)
            card.clicked.connect(self._select)
            self.rows_host.add_row(card)
            self._cards[note["id"]] = (card, card.row)
        self.list_scroll.refresh()
        self._sync_selection()

    def _sync_selection(self) -> None:
        for nid, (card, _row) in self._cards.items():
            card.refresh(nid == self._editing_id)

    def _select(self, note_id: str) -> None:
        note = self.notes.get(note_id)
        if not note:
            return
        self._loading = True
        self._editing_id = note_id
        self.title_input.setText(note["title"])
        self.content.setPlainText(note["content"])
        self.topic_input.setText(note["topic"])
        self.mode_lbl.setText(f"EDITING #{note_id[-4:]}")
        self.delete_btn.setEnabled(True)
        self._sync_selection()
        self._loading = False

    # ----------------------------------------------------------- actions
    def new_note(self, checked: bool = False, silent: bool = False) -> None:
        self._loading = True
        self._editing_id = None
        self.title_input.clear()
        self.content.clear()
        self.topic_input.setText("note")
        self.mode_lbl.setText("NEW NOTE")
        self.delete_btn.setEnabled(False)
        self._sync_selection()
        self._loading = False
        if not silent:
            self.title_input.setFocus()

    def save_note(self) -> None:
        title = self.title_input.text().strip() or "Untitled note"
        content = self.content.toPlainText()
        topic = self.topic_input.text().strip() or "note"
        if self._editing_id:
            updated = self.notes.update(self._editing_id, title=title,
                                        content=content, topic=topic)
            if updated:
                self.status_message.emit(
                    f"Updated existing note [{updated['topic']}]: {updated['title']}")
                self._select(self._editing_id)
        else:
            note = self.notes.create(title, content, topic)
            self.status_message.emit(f"Saved note [{note['topic']}]: {note['title']}")
            self._select(note["id"])

    def delete_current(self) -> None:
        if self._editing_id:
            self.notes.delete(self._editing_id)
            self.status_message.emit("Note deleted")
            self.new_note(silent=True)

    def _cancel_edit(self) -> None:
        if self._editing_id:
            self._select(self._editing_id)
        else:
            self.new_note(silent=True)

    def on_shown(self) -> None:
        self._rebuild_list()


class QTextEditCustom(QTextEdit):
    """Note content editor: Enter=newline, Ctrl+S=save, Esc=cancel."""

    save_requested = Signal()
    cancel_requested = Signal()

    def keyPressEvent(self, event) -> None:
        from ..shortcuts import event_matches
        if event_matches(event, "Ctrl+S"):
            self.save_requested.emit()
            return
        if event.key() == Qt.Key_Escape:
            self.cancel_requested.emit()
            return
        super().keyPressEvent(event)
