"""Notes page: search, browse, create, edit and delete local notes.

Fixes / features:

  * Editing an existing note and pressing Save updates THAT note in place.
    (The old page reset its selection on every refresh, so a background
    refresh between selecting and saving silently turned the edit into a
    brand-new note - the duplicate-note bug.)
  * The note's topic/category is preserved unless the user edits the topic
    field.
  * A reminder can be attached to / changed on / removed from a note.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDateEdit, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QTextEdit, QTimeEdit,
                               QVBoxLayout, QWidget)

RECURRENCES = ["none", "daily", "weekly", "weekdays", "monthly"]


class NoteReminderDialog(QDialog):
    """Add / change the reminder attached to a note."""

    def __init__(self, message: str = "", when: str = "", recurrence: str = "none",
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Note reminder - Nova")
        self.setModal(True)
        self.setMinimumWidth(380)

        form = QFormLayout(self)
        self.msg_edit = QLineEdit(message)
        form.addRow("Reminder text", self.msg_edit)

        dt = None
        if when:
            try:
                dt = datetime.strptime(str(when), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                dt = None
        self.date_edit = QDateEdit(QDate.currentDate() if dt is None else
                                   QDate(dt.year, dt.month, dt.day))
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        t = (QTime.currentTime().addSecs(3600) if dt is None else QTime(dt.hour, dt.minute))
        self.time_edit = QTimeEdit(t)
        self.time_edit.setDisplayFormat("HH:mm")
        form.addRow("Date", self.date_edit)
        form.addRow("Time", self.time_edit)

        self.recurrence = QComboBox()
        self.recurrence.addItems(RECURRENCES)
        self.recurrence.setCurrentText(recurrence if recurrence in RECURRENCES else "none")
        form.addRow("Repeat", self.recurrence)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("primaryButton")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[str, str, str]:
        when = (f"{self.date_edit.date().toString('yyyy-MM-dd')} "
                f"{self.time_edit.time().toString('HH:mm')}")
        return self.msg_edit.text().strip(), when, self.recurrence.currentText()


class NotesPage(QWidget):
    def __init__(self, controller, bus, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.bus = bus
        self._current_id: int | None = None
        self._loading = False          # guard against programmatic setText loops

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Notes")
        title.setObjectName("pageHeader")
        header.addWidget(title)
        header.addStretch(1)
        self.search = QLineEdit()
        self.search.setObjectName("searchInput")
        self.search.setPlaceholderText("Search notes...")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(self._on_search)
        self.search.returnPressed.connect(self._on_search)
        header.addWidget(self.search)
        new_btn = QPushButton("New note")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_note)
        header.addWidget(new_btn)
        root.addLayout(header)

        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setObjectName("listPanel")
        self.list.setFixedWidth(340)
        self.list.itemClicked.connect(self._on_select)
        body.addWidget(self.list)

        right = QVBoxLayout()
        # topic + reminder row ------------------------------------------------
        meta_row = QHBoxLayout()
        topic_label = QLabel("Topic")
        topic_label.setObjectName("monoHeader")
        self.topic_edit = QLineEdit()
        self.topic_edit.setPlaceholderText("general")
        self.topic_edit.setFixedWidth(180)
        self.topic_edit.setStatusTip("Keep the note's existing category unless you change it")
        meta_row.addWidget(topic_label)
        meta_row.addWidget(self.topic_edit)
        meta_row.addStretch(1)
        self.reminder_chip = QLabel()
        self.reminder_chip.setObjectName("chipLabel")
        meta_row.addWidget(self.reminder_chip)
        self.remind_btn = QPushButton("Add reminder")
        self.remind_btn.clicked.connect(self._add_note_reminder)
        self.remind_remove_btn = QPushButton("Remove")
        self.remind_remove_btn.setObjectName("ghostButton")
        self.remind_remove_btn.clicked.connect(self._remove_note_reminder)
        meta_row.addWidget(self.remind_btn)
        meta_row.addWidget(self.remind_remove_btn)
        right.addLayout(meta_row)

        self.detail = QTextEdit()
        self.detail.setPlaceholderText("Select a note, or click 'New note' to write one...")
        right.addWidget(self.detail, 1)
        actions = QHBoxLayout()
        self.editor_hint = QLabel("")
        self.editor_hint.setObjectName("hintLabel")
        actions.addWidget(self.editor_hint)
        actions.addStretch(1)
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.clicked.connect(self._save)
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete)
        actions.addWidget(self.save_btn)
        actions.addWidget(self.delete_btn)
        right.addLayout(actions)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        hint = QLabel("Notes are stored locally. You can also just say: "
                      "\"take a note that ...\" or \"update my note about ...\"")
        hint.setObjectName("hintLabel")
        root.addWidget(hint)

        self.refresh()

    # ------------------------------------------------------------- helpers
    def _fmt_reminder(self, rem: dict | None) -> str:
        if not rem:
            return ""
        try:
            when = datetime.strptime(rem["next_trigger"], "%Y-%m-%d %H:%M:%S")
            human = when.strftime("%a %d %b %H:%M")
        except (ValueError, KeyError):
            human = str(rem.get("next_trigger", ""))
        rec = rem.get("recurrence", "none")
        extra = f" · repeats {rec}" if rec and rec != "none" else ""
        return f"Reminder: {human}{extra}"

    def _update_reminder_row(self) -> None:
        rem = None
        if self._current_id is not None:
            rem = self.controller.db.note_reminder(self._current_id)
        if rem and rem.get("active"):
            self.reminder_chip.setText(self._fmt_reminder(rem))
            self.reminder_chip.setObjectName("chipOk")
            self.reminder_chip.setStyleSheet("")   # force re-polish
            self.remind_btn.setText("Change reminder")
            self.remind_remove_btn.setVisible(True)
        else:
            self.reminder_chip.setText("no reminder")
            self.reminder_chip.setObjectName("chipLabel")
            self.reminder_chip.setStyleSheet("")
            self.remind_btn.setText("Add reminder")
            self.remind_remove_btn.setVisible(False)
        # re-apply stylesheet so the objectName change takes effect
        self.reminder_chip.style().unpolish(self.reminder_chip)
        self.reminder_chip.style().polish(self.reminder_chip)

    # ------------------------------------------------------------- actions
    def refresh(self) -> None:
        """Reload the list while PRESERVING the current selection/editor."""
        self.list.blockSignals(True)
        self.list.clear()
        rows = self.controller.db.list_notes(limit=300)
        for note in rows:
            preview = note["content"][:70].replace("\n", " ")
            item = QListWidgetItem(f"#{note['id']} · {note['created_at'][:16]} · "
                                   f"[{note['topic']}]\n{preview}")
            item.setData(Qt.UserRole, note["id"])
            self.list.addItem(item)
            if note["id"] == self._current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self._update_reminder_row()

    def _on_search(self) -> None:
        query = self.search.text().strip()
        self.list.blockSignals(True)
        self.list.clear()
        rows = (self.controller.db.search_notes(query, 100) if query
                else self.controller.db.list_notes(limit=300))
        for note in rows:
            preview = note["content"][:70].replace("\n", " ")
            item = QListWidgetItem(f"#{note['id']} · {note['created_at'][:16]} · "
                                   f"[{note['topic']}]\n{preview}")
            item.setData(Qt.UserRole, note["id"])
            self.list.addItem(item)
            if note["id"] == self._current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def _on_select(self, item: QListWidgetItem) -> None:
        note_id = item.data(Qt.UserRole)
        note = self.controller.db.get_note(note_id)
        if note:
            self._loading = True
            self._current_id = note["id"]
            self.detail.setPlainText(note["content"])
            self.topic_edit.setText(note["topic"] or "general")
            self._loading = False
            self.editor_hint.setText(f"Editing note #{note['id']} - Save updates this note")
            self._update_reminder_row()

    def _new_note(self) -> None:
        self._current_id = None
        self.detail.setPlainText("")
        self.topic_edit.setText("")
        self.editor_hint.setText("New note - Save creates it")
        self._update_reminder_row()
        self.detail.setFocus()

    def _save(self) -> None:
        content = self.detail.toPlainText().strip()
        if not content:
            return
        topic = self.topic_edit.text().strip().lower()
        if self._current_id is None:
            row = self.controller.db.add_note(content, topic or "general")
            self._current_id = row["id"]
            self.controller.db.log_activity("note",
                                            f"UI note saved #{row['id']}: {content[:60]}")
        else:
            # EXACT note update - topic kept as-is (even unchanged) so the
            # existing category is never lost
            existing = self.controller.db.get_note(self._current_id)
            if existing is None:
                # note vanished (e.g. deleted from chat) -> create fresh
                row = self.controller.db.add_note(content, topic or "general")
                self._current_id = row["id"]
            else:
                self.controller.db.update_note(
                    self._current_id, content, topic or existing["topic"])
                self.controller.db.log_activity(
                    "note", f"UI note #{self._current_id} edited in place")
        self.editor_hint.setText(f"Saved note #{self._current_id}")
        self.refresh()
        self.bus.activity_logged.emit({})
        self.bus.notes_changed.emit()

    def _delete(self) -> None:
        if self._current_id is None:
            return
        confirm = QMessageBox.question(
            self, "Delete note", "Delete this note permanently?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm == QMessageBox.Yes:
            self.controller.db.delete_reminders_for_note(self._current_id)
            self.controller.db.delete_note(self._current_id)
            self.controller.db.log_activity("note",
                                            f"UI note #{self._current_id} deleted")
            self._current_id = None
            self.detail.setPlainText("")
            self.topic_edit.setText("")
            self.editor_hint.setText("")
            self.refresh()
            self.bus.activity_logged.emit({})
            self.bus.notes_changed.emit()

    # --------------------------------------------------------- note reminders
    def _add_note_reminder(self) -> None:
        if self._current_id is None:
            QMessageBox.information(self, "Note reminder",
                                    "Select (or save) a note first.")
            return
        note = self.controller.db.get_note(self._current_id)
        if note is None:
            return
        old = self.controller.db.note_reminder(note["id"])
        dlg = NoteReminderDialog(
            message=(old["message"] if old else note["content"][:80]),
            when=(old["next_trigger"] if old else ""),
            recurrence=(old["recurrence"] if old else "none"), parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        message, when, recurrence = dlg.values()
        if not message:
            QMessageBox.warning(self, "Note reminder", "The reminder text is empty.")
            return
        if old is not None:
            self.controller.db.delete_reminder(old["id"])
        result = self.controller.reminders.add(message, when, recurrence,
                                               note_id=note["id"])
        if not result.get("ok"):
            QMessageBox.warning(self, "Note reminder",
                                result.get("message", "Invalid time."))
            return
        self.controller.db.log_activity(
            "note", f"Reminder attached to note #{note['id']}: {message[:60]}")
        self.refresh()
        self.bus.reminders_changed.emit()
        self.bus.activity_logged.emit({})

    def _remove_note_reminder(self) -> None:
        if self._current_id is None:
            return
        old = self.controller.db.note_reminder(self._current_id)
        if old is None:
            return
        self.controller.db.delete_reminder(old["id"])
        self.controller.db.log_activity(
            "note", f"Reminder removed from note #{self._current_id}")
        self.refresh()
        self.bus.reminders_changed.emit()
