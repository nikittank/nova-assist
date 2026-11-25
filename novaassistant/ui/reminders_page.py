"""Reminders page: full CRUD + speak-to-fill microphone capture.

  * A microphone button sits next to the text field. Speaking something like
    "Remind me tomorrow at 6 PM to call John every Monday." extracts and
    pre-fills the reminder text, date, time and repeat rule. The extracted
    values are shown as chips BEFORE anything is saved.
  * Selecting a reminder loads it into the form; "Save changes" edits that
    reminder in place. Add / Complete / Snooze / Delete are one click away.
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QTimeEdit, QVBoxLayout,
                               QWidget)

from ..services.reminders import parse_reminder_phrase

RECURRENCES = ["none", "daily", "weekly", "weekdays", "monthly"]


class RemindersPage(QWidget):
    def __init__(self, controller, bus, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.bus = bus
        self._editing_id: int | None = None
        self._current_id: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 14)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Reminders")
        title.setObjectName("pageHeader")
        header.addWidget(title)
        header.addStretch(1)
        self.count_chip = QLabel("")
        self.count_chip.setObjectName("chipLabel")
        header.addWidget(self.count_chip)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("ghostButton")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)
        root.addLayout(header)

        self.list = QListWidget()
        self.list.setObjectName("listPanel")
        self.list.itemClicked.connect(self._on_select)
        root.addWidget(self.list, 1)

        # ---------------------------------------------------------- add form
        form_label = QLabel("ADD A REMINDER")
        form_label.setObjectName("sectionHeader")
        root.addWidget(form_label)

        msg_row = QHBoxLayout()
        self.msg_edit = QLineEdit()
        self.msg_edit.setPlaceholderText(
            'What should I remind you about?  e.g. "Call John tomorrow at 6 PM"')
        self.msg_edit.returnPressed.connect(self._add)
        msg_row.addWidget(self.msg_edit, 1)
        self.mic_button = QPushButton("Speak")
        self.mic_button.setObjectName("cyanButton")
        self.mic_button.setToolTip("Click, then say: remind me tomorrow at 6 PM "
                                   "to call John every Monday")
        self.mic_button.setFixedWidth(110)
        self.mic_button.clicked.connect(self._toggle_voice_capture)
        msg_row.addWidget(self.mic_button)
        root.addLayout(msg_row)

        # extracted-values preview (visible after a voice capture)
        self.extract_row = QHBoxLayout()
        self.extract_title = QLabel("EXTRACTED")
        self.extract_title.setObjectName("monoHeader")
        self.extract_chip = QLabel("")
        self.extract_chip.setObjectName("chipOk")
        self.extract_chip.setWordWrap(True)
        self.extract_row.addWidget(self.extract_title)
        self.extract_row.addWidget(self.extract_chip, 1)
        self.extract_row.addStretch(1)
        root.addLayout(self.extract_row)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.time_edit = QTimeEdit(QTime.currentTime().addSecs(3600))
        self.time_edit.setDisplayFormat("HH:mm")
        self.recurrence = QComboBox()
        self.recurrence.addItems(RECURRENCES)
        self.add_btn = QPushButton("Add reminder")
        self.add_btn.setObjectName("primaryButton")
        self.add_btn.clicked.connect(self._add)
        self.update_btn = QPushButton("Save changes")
        self.update_btn.setObjectName("cyanButton")
        self.update_btn.clicked.connect(self._update_selected)
        self.new_btn = QPushButton("New")
        self.new_btn.setObjectName("ghostButton")
        self.new_btn.clicked.connect(self._reset_form)

        form.addWidget(QLabel("Date"), 1, 0)
        form.addWidget(self.date_edit, 1, 1)
        form.addWidget(QLabel("Time"), 1, 2)
        form.addWidget(self.time_edit, 1, 3)
        form.addWidget(QLabel("Repeat"), 2, 0)
        form.addWidget(self.recurrence, 2, 1)
        row2 = QHBoxLayout()
        row2.addWidget(self.add_btn)
        row2.addWidget(self.update_btn)
        row2.addWidget(self.new_btn)
        form.addLayout(row2, 2, 2, 1, 2)
        root.addLayout(form)

        # ------------------------------------------------------ item actions
        actions = QHBoxLayout()
        self.complete_btn = QPushButton("Complete selected")
        self.complete_btn.clicked.connect(self._complete_selected)
        self.snooze10_btn = QPushButton("Snooze 10 min")
        self.snooze10_btn.setObjectName("ghostButton")
        self.snooze10_btn.clicked.connect(lambda: self._snooze_selected(10))
        self.snooze60_btn = QPushButton("Snooze 1 h")
        self.snooze60_btn.setObjectName("ghostButton")
        self.snooze60_btn.clicked.connect(lambda: self._snooze_selected(60))
        self.delete_btn = QPushButton("Delete selected")
        self.delete_btn.setObjectName("dangerButton")
        self.delete_btn.clicked.connect(self._delete_selected)
        actions.addWidget(self.complete_btn)
        actions.addWidget(self.snooze10_btn)
        actions.addWidget(self.snooze60_btn)
        actions.addWidget(self.delete_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        hint = QLabel("Or simply say: \"remind me at 6 PM to call John\" · "
                      "\"remind me every Monday to review my work\" · select a "
                      "reminder to edit it in place")
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.bus.oneshot_state.connect(self._on_oneshot_state)
        self.bus.oneshot_transcript.connect(self._on_voice_text)
        self.bus.reminder_fired.connect(lambda _r: self.refresh())

        self.refresh()

    # ------------------------------------------------------------- helpers
    def _human_when(self, rem: dict) -> str:
        try:
            when = datetime.strptime(rem["next_trigger"], "%Y-%m-%d %H:%M:%S")
            human = when.strftime("%a %d %b %H:%M")
            overdue = " (due)" if when <= datetime.now() and rem["active"] else ""
        except (ValueError, KeyError):
            human, overdue = str(rem.get("next_trigger", "")), ""
        rec = f" · repeats {rem['recurrence']}" if rem["recurrence"] != "none" else ""
        state = "" if rem["active"] else " · INACTIVE"
        note = f" · note #{rem['note_id']}" if rem.get("note_id") else ""
        return f"{human}{overdue}{rec}{state}{note}"

    # ------------------------------------------------------------- actions
    def refresh(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        rows = self.controller.db.list_reminders()
        active = sum(1 for r in rows if r["active"])
        self.count_chip.setText(f"{active} active · {len(rows)} total")
        for rem in rows:
            item = QListWidgetItem(f"[#{rem['id']}] {self._human_when(rem)}\n"
                                   f"{rem['message']}")
            item.setData(Qt.UserRole, rem["id"])
            if not rem["active"]:
                item.setForeground(Qt.gray)
            self.list.addItem(item)
            if rem["id"] == self._current_id:
                self.list.setCurrentItem(item)   # preserve selection
        self.list.blockSignals(False)

    def _selected_id(self) -> int | None:
        """Current list selection, falling back to the stored selection."""
        item = self.list.currentItem()
        if item is not None:
            rid = item.data(Qt.UserRole)
            if rid is not None:
                self._current_id = rid
                return rid
        return self._current_id

    def _on_select(self, item: QListWidgetItem) -> None:
        rid = item.data(Qt.UserRole)
        rem = self.controller.db.get_reminder(rid)
        if not rem:
            return
        self._current_id = rid
        self._editing_id = rid
        self.msg_edit.setText(rem["message"])
        try:
            when = datetime.strptime(rem["next_trigger"], "%Y-%m-%d %H:%M:%S")
            self.date_edit.setDate(QDate(when.year, when.month, when.day))
            self.time_edit.setTime(QTime(when.hour, when.minute))
        except ValueError:
            pass
        self.recurrence.setCurrentText(rem["recurrence"]
                                       if rem["recurrence"] in RECURRENCES else "none")
        self.add_btn.setText(f"Add as new")
        self.update_btn.setText(f"Save changes to #{rid}")
        self._show_extract(f"editing #{rid}", self._human_when(rem), rem["recurrence"])

    def _reset_form(self) -> None:
        self._editing_id = None
        self._current_id = None
        self.msg_edit.clear()
        self.date_edit.setDate(QDate.currentDate())
        self.time_edit.setTime(QTime.currentTime().addSecs(3600))
        self.recurrence.setCurrentText("none")
        self.add_btn.setText("Add reminder")
        self.update_btn.setText("Save changes")
        self.extract_chip.setVisible(False)
        self.extract_title.setVisible(False)

    def _read_form(self) -> tuple[str, str, str]:
        message = self.msg_edit.text().strip()
        when = (f"{self.date_edit.date().toString('yyyy-MM-dd')} "
                f"{self.time_edit.time().toString('HH:mm')}")
        return message, when, self.recurrence.currentText()

    def _add(self) -> None:
        message, when, recurrence = self._read_form()
        if not message:
            return
        result = self.controller.reminders.add(message, when, recurrence)
        if not result.get("ok"):
            QMessageBox.warning(self, "Reminder", result.get("message", "Invalid time."))
            return
        self.controller.db.log_activity(
            "reminder", f"UI reminder #{result.get('id')}: {message}")
        self.msg_edit.clear()
        self._reset_form()
        self.refresh()
        self.bus.activity_logged.emit({})
        self.bus.reminders_changed.emit()

    def _update_selected(self) -> None:
        rid = self._selected_id() if self._editing_id is None else self._editing_id
        if rid is None:
            QMessageBox.information(self, "Reminder",
                                    "Select a reminder in the list first.")
            return
        message, when, recurrence = self._read_form()
        result = self.controller.reminders.update(rid, message, when,
                                                  recurrence)
        if not result.get("ok"):
            QMessageBox.warning(self, "Reminder", result.get("message", "Update failed."))
            return
        self.controller.db.log_activity("reminder",
                                        f"UI edited reminder #{rid}")
        self.refresh()
        self.bus.activity_logged.emit({})
        self.bus.reminders_changed.emit()

    def _complete_selected(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        result = self.controller.reminders.complete(rid)
        if not result.get("ok"):
            QMessageBox.warning(self, "Reminder", result.get("message", "Failed."))
        self.refresh()
        self.bus.activity_logged.emit({})
        self.bus.reminders_changed.emit()

    def _snooze_selected(self, minutes: int) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        result = self.controller.reminders.snooze(rid, minutes)
        if not result.get("ok"):
            QMessageBox.warning(self, "Reminder", result.get("message", "Failed."))
        self.refresh()
        self.bus.activity_logged.emit({})
        self.bus.reminders_changed.emit()

    def _delete_selected(self) -> None:
        rid = self._selected_id()
        if rid is None:
            return
        self.controller.db.delete_reminder(rid)
        self.controller.db.log_activity("reminder", f"UI deleted reminder #{rid}")
        if self._editing_id == rid or self._current_id == rid:
            self._reset_form()
        self.refresh()
        self.bus.activity_logged.emit({})
        self.bus.reminders_changed.emit()

    # ------------------------------------------------------- voice capture
    def _show_extract(self, what: str, when_h: str, recurrence: str) -> None:
        rec = recurrence if recurrence != "none" else "no repeat"
        self.extract_chip.setText(f"{what}  ·  {when_h}  ·  repeat: {rec}")
        self.extract_chip.setObjectName("chipOk")
        self.extract_chip.style().unpolish(self.extract_chip)
        self.extract_chip.style().polish(self.extract_chip)
        self.extract_chip.setVisible(True)
        self.extract_title.setVisible(True)

    def _show_extract_error(self, text: str) -> None:
        self.extract_chip.setText(text)
        self.extract_chip.setObjectName("chipBad")
        self.extract_chip.style().unpolish(self.extract_chip)
        self.extract_chip.style().polish(self.extract_chip)
        self.extract_chip.setVisible(True)
        self.extract_title.setVisible(True)

    def _toggle_voice_capture(self) -> None:
        if self.mic_button.isChecked():
            self.mic_button.setChecked(False)
            self.controller.cancel_listen_once()
            self.mic_button.setText("Speak")
            return
        ok = self.controller.listen_once(self._on_voice_final)
        if not ok:
            self._show_extract_error("Voice capture unavailable right now.")
            return
        self.mic_button.setChecked(True)
        self.mic_button.setText("Listening...")

    def _on_oneshot_state(self, state: str) -> None:
        if state == "listening":
            self.mic_button.setChecked(True)
            self.mic_button.setText("Listening...")
        elif state == "transcribing":
            self.mic_button.setText("Transcribing...")
        elif state == "":
            self.mic_button.setChecked(False)
            self.mic_button.setText("Speak")

    def _on_voice_text(self, text: str) -> None:
        """Raw transcript arrived from the one-shot capture."""
        if not text:
            self._show_extract_error("Nothing heard - try again.")
            return

    def _on_voice_final(self, text: str) -> None:
        """Transcript -> extraction -> pre-fill (nothing saved yet)."""
        if not text:
            self._show_extract_error("Nothing heard - try again.")
            return
        parsed = parse_reminder_phrase(text)
        if not parsed.get("message"):
            self._show_extract_error(f"Could not parse: \"{text}\"")
            return
        # auto-fill the form; user reviews and presses Add reminder
        try:
            when = datetime.strptime(parsed["when"], "%Y-%m-%d %H:%M:%S")
            self.date_edit.setDate(QDate(when.year, when.month, when.day))
            self.time_edit.setTime(QTime(when.hour, when.minute))
        except (ValueError, KeyError):
            pass
        self.msg_edit.setText(parsed["message"])
        self.recurrence.setCurrentText(parsed["recurrence"]
                                       if parsed["recurrence"] in RECURRENCES
                                       else "none")
        self._editing_id = None
        self.add_btn.setText("Add reminder")
        self._show_extract(f"\"{text[:60]}\"", parsed["date"] + " " + parsed["time"],
                           parsed["recurrence"])
