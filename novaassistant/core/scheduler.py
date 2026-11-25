"""Reminder scheduler — timer that fires due reminders (notify + speak)."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class ReminderScheduler(QObject):
    reminder_due = Signal(dict)

    def __init__(self, reminders_store, activity_log, parent: QObject | None = None):
        super().__init__(parent)
        self.store = reminders_store
        self.activity = activity_log
        self._fired: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setInterval(15000)  # 15s tick
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        try:
            for item in self.store.due_now(within_seconds=20):
                if item["id"] in self._fired:
                    continue
                self._fired.add(item["id"])
                if len(self._fired) > 200:
                    self._fired.clear()
                self.store.set_fired(item["id"])
                self.activity.log("reminder", f"Reminder fired: {item['text']}")
                self.reminder_due.emit(item)
        except Exception:
            pass
