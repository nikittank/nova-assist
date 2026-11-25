"""Reminders page — list + add/edit panel with voice capture (mockup-exact).

Adds the required microphone button next to the reminder text field:
speak "Remind me tomorrow at 6 PM to call John every Monday" and the fields
(text / date / time / repeat) are auto-filled with a visible preview.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QTextEdit, QTimeEdit,
    QVBoxLayout, QWidget,
)

from .. import icons, theme
from ..core import reminder_parser
from ..core.reminders_store import REPEAT_NONE
from .widgets_common import (
    FixedRowsHost, HfwRow, NovaCheckBox, RowsScroll, TagPill, style_scoped,
)

REPEATS = [
    ("none", "none"), ("daily", "daily"), ("weekdays", "weekdays"),
    ("weekly", "weekly"), ("monthly", "monthly"),
]


def _repeat_to_combo(rep: str | None) -> str:
    if not rep:
        return "none"
    if rep.startswith("weekly:"):
        return "weekly"
    return rep if rep in dict(REPEATS) else "none"


def _human_due(due: str) -> str:
    try:
        dt = datetime.fromisoformat(due)
        today = datetime.now().date()
        d = dt.date()
        if d == today:
            day = "Today"
        elif d == today.fromordinal(today.toordinal() + 1):
            day = "Tomorrow"
        else:
            day = dt.strftime("%b %d") if dt.year == datetime.now().year \
                else dt.strftime("%Y-%m-%d")
        return f"{day} @ {dt.strftime('%H:%M')}"
    except Exception:
        return due


class ReminderRow(HfwRow):
    action = Signal(str, str)   # (action, id)

    min_natural_height = 76   # title line + chip line + margins (QSS padding)

    def __init__(self, item: dict):
        super().__init__()
        self.item = item
        self.setCursor(Qt.PointingHandCursor)
        # HfwRow keeps minimum height in sync so the due-chip line never clips
        style_scoped(self, "ReminderRow",
                     "background: #0a0a0c; border: 1px solid #26262b; border-radius: 8px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 12, 12)
        lay.setSpacing(14)

        self.checkbox = NovaCheckBox()
        self.checkbox.setChecked(item.get("done", False))
        theme.set_style(self.checkbox, 
            "QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px;"
            " border: 1px solid #4b4b52; background: #000000; }"
            "QCheckBox::indicator:checked { background: #ffffff; border-color: #ffffff;"
            f" image: url({theme.ASSETS_DIR}/check_dark.svg); }}")
        lay.addWidget(self.checkbox, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setSpacing(6)
        title = QLabel(item["text"])
        title.setWordWrap(True)
        theme.set_style(title, 
            f"color: {'#6b7280' if item.get('done') else theme.WHITE}; font-size: 12px;"
            "font-weight: 600; border: none;")
        if item.get("done"):
            f = title.font()
            f.setStrikeOut(True)
            title.setFont(f)
        if item.get("notes"):
            notes = QLabel(item["notes"])
            notes.setWordWrap(True)
            theme.set_style(notes, f"color: {theme.MUTED}; font-size: 11px; border: none;")
            mid.addWidget(notes)
        chips = QHBoxLayout()
        chips.setSpacing(10)
        due_chip = QLabel("  " + _human_due(item["due"]))
        theme.set_style(due_chip, 
            f"color: {'#6b7280' if item.get('done') else '#d4d4d8'}; font-size: 11px;"
            f" font-family: {theme.FONT_MONO}; background: #141416;"
            f" border: 1px solid {theme.BORDER_2}; border-radius: 4px; padding: 3px 8px;")
        rep = QLabel(f"Repeat: <b style='font-weight:500;color:#e5e7eb'>"
                     f"{reminder_parser.repeat_label(item.get('repeat'))}</b>")
        theme.set_style(rep, f"color: {theme.GHOST}; font-size: 11px; border: none;")
        chips.addWidget(due_chip)
        chips.addWidget(rep)
        chips.addStretch(1)
        mid.addWidget(title)
        mid.addLayout(chips)
        lay.addLayout(mid, 1)

        status = item.get("done") and "Done" or (
            "Active" if _is_soon(item["due"]) else "Scheduled")
        color = theme.EMERALD if item.get("done") else (
            theme.WHITE if _is_soon(item["due"]) else theme.MUTED)
        badge = QLabel(status.upper())
        theme.set_style(badge, 
            f"color: {color}; font-size: 10px; font-weight: 700; letter-spacing: 1px;"
            f" background: #141416; border: 1px solid {theme.BORDER_2};"
            "border-radius: 4px; padding: 3px 8px;")
        lay.addWidget(badge, 0, Qt.AlignTop)

        actions = QHBoxLayout()
        actions.setSpacing(2)
        for key, icon_name, tip in (
                ("edit", "edit", "Edit"), ("snooze", "snooze", "Snooze 5 min"),
                ("delete", "trash", "Delete")):
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setIcon(icons.icon(icon_name, theme.GHOST, 13))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            theme.set_style(btn, 
                "QPushButton { background: transparent; border: none; border-radius: 6px; }"
                "QPushButton:hover { background: #1f1f23; }")
            btn.clicked.connect(
                lambda _=False, a=key, rid=item["id"]: self.action.emit(a, rid))
            actions.addWidget(btn)
        holder = QWidget()
        holder.setLayout(actions)
        theme.set_style(holder, "border: none;")
        lay.addWidget(holder, 0, Qt.AlignTop)

        self.checkbox.toggled.connect(
            lambda on: self.action.emit("uncheck" if not on else "complete",
                                        item["id"]))
        self.prime_height()


def _is_soon(due: str) -> bool:
    try:
        dt = datetime.fromisoformat(due)
        return (dt - datetime.now()).total_seconds() < 86400
    except Exception:
        return False


class RemindersPage(QWidget):
    request_llm = Signal(str)
    status_message = Signal(str)
    store_changed = Signal()          # queued-safe rebuild from any thread

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._editing_id: str | None = None
        self._rows: dict[str, ReminderRow] = {}
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)

        # header ------------------------------------------------------------
        head = QHBoxLayout()
        title = QLabel("Reminders")
        theme.set_style(title, f"color: {theme.WHITE}; font-size: 20px; font-weight: 700;")
        self.pending_chip = TagPill("0 pending")
        theme.set_style(self.pending_chip, 
            f"color: #d4d4d8; font-size: 12px; font-family: {theme.FONT_MONO};"
            f"background: #141416; border: 1px solid {theme.BORDER_2};"
            "border-radius: 10px; padding: 3px 10px;")
        head.addWidget(title)
        head.addSpacing(8)
        head.addWidget(self.pending_chip)
        head.addStretch(1)
        refresh = QPushButton("  Refresh")
        refresh.setProperty("variant", "primary")
        refresh.setIcon(icons.icon("refresh", theme.BLACK, 14, 2))
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self._refresh)
        head.addWidget(refresh)
        root.addLayout(head)

        # list ----------------------------------------------------------------
        list_panel = QWidget()
        style_scoped(list_panel, "RemListPanel",
                     f"background: {theme.BLACK}; border: 1px solid {theme.BORDER};"
                     "border-radius: 12px;")
        lp = QVBoxLayout(list_panel)
        lp.setContentsMargins(12, 12, 12, 8)
        lp.setSpacing(10)

        # Summary cards use the otherwise empty area above the reminder list.
        summary_panel = QFrame()
        summary_panel.setObjectName("ReminderSummaryPanel")
        summary_panel.setStyleSheet(
            f"QFrame#ReminderSummaryPanel {{ background: {theme.BLACK};"
            f" border: 1px solid {theme.BORDER}; border-radius: 10px; }}")
        summary = QHBoxLayout(summary_panel)
        summary.setContentsMargins(8, 8, 8, 8)
        summary.setSpacing(8)
        self.summary_values = {}
        for key, label in (("pending", "PENDING"), ("overdue", "OVERDUE"),
                           ("upcoming", "NEXT 7 DAYS")):
            card = QFrame()
            card.setObjectName("ReminderSummaryCard")
            card.setStyleSheet(
                f"QFrame#ReminderSummaryCard {{ background: {theme.PANEL_2};"
                f" border: 1px solid {theme.BORDER_2}; border-radius: 8px; }}")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 8, 10, 8)
            cl.setSpacing(2)
            value = QLabel("0")
            theme.set_style(value, f"color: {theme.WHITE}; font-size: 18px; font-weight: 700; border: none;")
            caption = QLabel(label)
            theme.set_style(caption, f"color: {theme.MUTED}; font-size: 9px; font-family: {theme.FONT_MONO}; border: none;")
            cl.addWidget(value)
            cl.addWidget(caption)
            summary.addWidget(card, 1)
            self.summary_values[key] = value
        self.summary_panel = summary_panel

        self.rows_host = FixedRowsHost(spacing=10)
        self.scroll = RowsScroll(self.rows_host)
        lp.addWidget(self.scroll, 1)
        content = QHBoxLayout()
        content.setSpacing(14)

        # add / edit panel -----------------------------------------------------
        panel = QWidget()
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        style_scoped(panel, "RemAddPanel",
                     f"background: {theme.BLACK}; border: 1px solid {theme.BORDER};"
                     "border-radius: 12px;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(18, 16, 18, 16)
        pl.setSpacing(14)

        prow = QHBoxLayout()
        self.panel_title = QLabel("ADD A REMINDER")
        theme.set_style(self.panel_title, 
            f"color: {theme.MUTED}; font-size: 11px; font-weight: 700;"
            "letter-spacing: 1.2px;")
        self.cancel_edit_btn = QPushButton("Cancel edit")
        self.cancel_edit_btn.setProperty("variant", "chip")
        self.cancel_edit_btn.hide()
        self.cancel_edit_btn.clicked.connect(self._cancel_edit)
        prow.addWidget(self.panel_title)
        prow.addStretch(1)
        prow.addWidget(self.cancel_edit_btn)
        pl.addLayout(prow)

        # text field row WITH the required mic button right next to it
        text_row = QHBoxLayout()
        text_row.setSpacing(10)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("What should I remind you about?")
        self.text_input.setFixedHeight(38)
        self.text_input.returnPressed.connect(self._apply_or_add)
        self.mic_btn = QPushButton()
        self.mic_btn.setFixedSize(38, 38)
        self.mic_btn.setIcon(icons.icon("mic", theme.MUTED, 17))
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.setToolTip("Speak a reminder — e.g. \"Remind me tomorrow at 6 PM to call John every Monday\"")
        theme.set_style(self.mic_btn, 
            f"QPushButton {{ background: #0d0d0f; border: 1px solid {theme.BORDER_2};"
            "border-radius: 8px; }"
            "QPushButton:hover { background: #1f1f23; }")
        self.mic_btn.clicked.connect(self._toggle_voice)
        text_row.addWidget(self.mic_btn)
        text_row.addWidget(self.text_input, 1)
        pl.addLayout(text_row)

        self.notes_input = QTextEdit()
        self.notes_input.setPlaceholderText("Notes (optional)")
        self.notes_input.setFixedHeight(54)
        pl.addWidget(self.notes_input)

        # extracted preview (shown after voice parse or manual parse)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        theme.set_style(self.preview, 
            f"color: {theme.EMERALD}; font-size: 11px; font-family: {theme.FONT_MONO};")
        self.preview.hide()
        pl.addWidget(self.preview)

        grid_holder = QWidget()
        grid_holder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        fields_grid = QGridLayout(grid_holder)
        fields_grid.setContentsMargins(0, 0, 0, 0)
        fields_grid.setHorizontalSpacing(16)
        fields_grid.setVerticalSpacing(12)

        def field_label(text: str) -> QLabel:
            lbl = QLabel(text)
            theme.set_style(lbl, f"color: {theme.MUTED}; font-size: 12px; border: none;")
            return lbl

        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setFixedHeight(32)
        self.date_edit.setMinimumWidth(128)
        from PySide6.QtCore import QDate, QTime
        self.date_edit.setDate(QDate.currentDate())
        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("hh:mm AP")
        self.time_edit.setFixedHeight(32)
        self.time_edit.setMinimumWidth(92)
        self.time_edit.setTime(QTime.currentTime().addSecs(3600))
        self.repeat_combo = QComboBox()
        for _val, label in REPEATS:
            self.repeat_combo.addItem(label, _val)
        self.repeat_combo.setFixedHeight(32)
        self.repeat_combo.setMinimumWidth(102)
        for w in (self.date_edit, self.time_edit, self.repeat_combo):
            theme.set_style(w, 
                f"background: #0d0d10; border: 1px solid #22232b; border-radius: 8px;"
                f" font-size: 12px; font-family: {theme.FONT_MONO};"
                f" color: {theme.TEXT_BRIGHT}; padding: 4px 8px;"
                "QComboBox::drop-down { border: none; width: 22px; }"
                f"QComboBox QAbstractItemView {{ background: #0c0c0e;"
                f" border: 1px solid {theme.BORDER_2}; selection-background-color: #1f1f23; }}")
        theme.set_style(self.date_edit, w.styleSheet())

        fields_grid.addWidget(field_label("Date"), 0, 0)
        fields_grid.addWidget(field_label("Time"), 0, 1)
        fields_grid.addWidget(field_label("Repeat"), 0, 2)
        fields_grid.addWidget(self.date_edit, 1, 0)
        fields_grid.addWidget(self.time_edit, 1, 1)
        fields_grid.addWidget(self.repeat_combo, 1, 2)

        self.add_btn = QPushButton("  Add reminder")
        self.add_btn.setProperty("variant", "primary")
        self.add_btn.setIcon(icons.icon("plus", theme.BLACK, 14, 2.5))
        self.add_btn.setFixedHeight(32)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._apply_or_add)
        fields_grid.addWidget(self.add_btn, 1, 3)
        fields_grid.setColumnStretch(0, 1)
        fields_grid.setColumnStretch(1, 1)
        fields_grid.setColumnStretch(2, 1)
        fields_grid.setColumnStretch(3, 0)
        pl.addWidget(grid_holder)

        hint = QLabel('Or simply say: "remind me tomorrow at 6 PM to call John every Monday" '
                      'or "remind me in 20 minutes to stretch" — then press the mic.')
        hint.setWordWrap(True)
        theme.set_style(hint, f"color: {theme.MUTED}; font-size: 11px; border: none;")
        pl.addWidget(hint)

        # Keep the lower panel lightweight and useful instead of using a large
        # illustration that competes with the reminder form.
        art_panel = QFrame()
        art_panel.setObjectName("ReminderArtPanel")
        art_panel.setStyleSheet(
            f"QFrame#ReminderArtPanel {{ background: {theme.PANEL_2};"
            f" border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
        art_layout = QVBoxLayout(art_panel)
        art_layout.setContentsMargins(10, 10, 10, 10)
        art_title = QLabel("REMINDER FOCUS")
        theme.set_style(art_title, f"color: {theme.MUTED}; font-size: 10px; font-family: {theme.FONT_MONO}; border: none;")
        art_layout.addWidget(art_title)
        quote = QLabel('“Do it now. Your future self will thank you.”')
        quote.setWordWrap(True)
        quote.setAlignment(Qt.AlignCenter)
        theme.set_style(
            quote,
            f"color: {theme.WHITE}; font-size: 16px; font-weight: 700;"
            f" font-family: {theme.FONT_MONO}; padding: 18px 12px; border: none;",
        )
        art_layout.addWidget(quote, 1)

        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        left_column.addWidget(summary_panel)
        left_column.addWidget(panel)
        left_column.addWidget(art_panel)
        left_column.addStretch(1)
        content.addLayout(left_column, 2)
        content.addWidget(list_panel, 3)
        root.addLayout(content, 1)

        # wire store
        self.store = ctx.reminders
        self.store.add_listener(self._on_store_event)
        self.store_changed.connect(self._refresh)
        self._refresh()

        # one font everywhere: same typeface as the sidebar/technical UI
        theme.apply_unified_font(self)

    # ------------------------------------------------------------ voice
    def _toggle_voice(self) -> None:
        orch = self.ctx.orchestrator
        if orch.is_listening:
            orch.stop_listening()          # finalize -> utterance_ready
        else:
            if orch.start_listening():
                self.mic_btn.setIcon(icons.icon("mic-off", theme.RED_TEXT, 17))
                self.preview.setText("Listening… speak your reminder now.")
                self.preview.show()
                self.status_message.emit("Listening for reminder…")

    def on_utterance_transcribed(self, text: str) -> None:
        """Called by app context after STT when this page requested voice."""
        if not self.isVisible():
            return
        parsed = reminder_parser.parse_reminder(text)
        self._fill_from_parse(parsed, source_text=text)

    def _fill_from_parse(self, parsed: dict, source_text: str = "") -> None:
        self.mic_btn.setIcon(icons.icon("mic", theme.MUTED, 17))
        if not parsed.get("matched") and not source_text:
            self.preview.setText("Couldn't extract a time — type it manually.")
            self.preview.show()
            return
        now = datetime.now()
        if parsed.get("datetime"):
            dt = datetime.fromisoformat(parsed["datetime"])
        else:
            dt = now
        self.text_input.setText(parsed.get("text") or source_text)
        self._loading = True
        from PySide6.QtCore import QDate, QTime
        self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
        self.time_edit.setTime(QTime(dt.hour, dt.minute))
        rep_val = _repeat_to_combo(parsed.get("repeat"))
        rep_idx = self.repeat_combo.findData(rep_val)
        self.repeat_combo.setCurrentIndex(max(0, rep_idx))
        self._loading = False
        bits = []
        bits.append(f"text: \"{parsed.get('text', '')}\"")
        bits.append(f"date: {dt.strftime('%Y-%m-%d')}")
        bits.append(f"time: {dt.strftime('%H:%M')}")
        bits.append(f"repeat: {parsed.get('repeat_label', 'None')}")
        self.preview.setText("✓ Extracted  —  " + "   •   ".join(bits))
        self.preview.show()
        self.status_message.emit("Reminder fields filled from speech — review and press Add")

    # ------------------------------------------------------------ CRUD
    def _apply_or_add(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            self.status_message.emit("Type a reminder text first")
            return
        d = self.date_edit.date()
        t = self.time_edit.time()
        due = datetime(d.year(), d.month(), d.day(), t.hour(), t.minute()
                       ).isoformat(timespec="seconds")
        repeat = self.repeat_combo.currentData() or REPEAT_NONE
        if self._editing_id:
            self.store.update(self._editing_id, text=text, due=due, repeat=repeat,
                              notes=self.notes_input.toPlainText())
            self.status_message.emit(f"Updated reminder: {text}")
            self._cancel_edit()
        else:
            self.store.create(text, due, repeat, self.notes_input.toPlainText())
            self.status_message.emit(f"Reminder added: {text}")
            self.text_input.clear()
            self.notes_input.clear()
            self.preview.hide()

    def _action(self, action: str, rid: str) -> None:
        item = self.store.get(rid)
        if not item:
            return
        if action == "complete":
            self.store.complete(rid)
            self.status_message.emit(f"Completed: {item['text']}")
        elif action == "uncheck":
            self.store.reopen(rid)
        elif action == "snooze":
            self.store.snooze(rid, minutes=5)
            self.status_message.emit(f"Snoozed 5 min: {item['text']}")
        elif action == "delete":
            self.store.delete(rid)
            self.status_message.emit(f"Deleted: {item['text']}")
        elif action == "edit":
            self._editing_id = rid
            self._loading = True
            dt = datetime.fromisoformat(item["due"])
            from PySide6.QtCore import QDate, QTime
            self.date_edit.setDate(QDate(dt.year, dt.month, dt.day))
            self.time_edit.setTime(QTime(dt.hour, dt.minute))
            idx = self.repeat_combo.findData(_repeat_to_combo(item.get("repeat")))
            self.repeat_combo.setCurrentIndex(max(0, idx))
            self.text_input.setText(item["text"])
            self.notes_input.setPlainText(item.get("notes", ""))
            self._loading = False
            self.panel_title.setText(f"EDIT REMINDER  #{rid[-4:]}")
            self.add_btn.setText("  Save changes")
            self.cancel_edit_btn.show()
            self.text_input.setFocus()

    def _cancel_edit(self) -> None:
        self._editing_id = None
        self.panel_title.setText("ADD A REMINDER")
        self.add_btn.setText("  Add reminder")
        self.cancel_edit_btn.hide()
        self.text_input.clear()
        self.notes_input.clear()
        self.preview.hide()

    def _refresh(self) -> None:
        items = self.store.all()
        self.rows_host.clear_rows()
        self._rows.clear()
        for item in items:
            row = ReminderRow(item)
            row.action.connect(self._action)
            self.rows_host.add_row(row)
            self._rows[item["id"]] = row
        pending = len([i for i in items if not i.get("done")])
        now = datetime.now()
        week_end = now + timedelta(days=7)
        overdue = 0
        upcoming = 0
        for item in items:
            if item.get("done"):
                continue
            try:
                due = datetime.fromisoformat(item["due"])
            except (KeyError, TypeError, ValueError):
                continue
            if due < now:
                overdue += 1
            elif due <= week_end:
                upcoming += 1
        self.summary_values["pending"].setText(str(pending))
        self.summary_values["overdue"].setText(str(overdue))
        self.summary_values["upcoming"].setText(str(upcoming))
        self.pending_chip.setText(f"{pending} pending")
        self.scroll.refresh()

    def _on_store_event(self, event: str, _item=None) -> None:
        # may fire from worker threads (LLM tools) — signal hops to main thread
        self.store_changed.emit()

    def on_shown(self) -> None:
        self._refresh()
