"""Reminders store — CRUD + complete/snooze + repeat scheduling."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

from ..config import new_id

REPEAT_NONE = "none"
REPEAT_DAILY = "daily"
REPEAT_WEEKDAYS = "weekdays"
REPEAT_WEEKLY = "weekly"
REPEAT_MONTHLY = "monthly"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RemindersStore:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "reminders.json")
        self._lock = threading.RLock()
        self._items: list[dict] = []
        self._listeners = []
        self.load()

    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    self._items = json.load(fh)
        except Exception:
            self._items = []

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._items, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _emit(self, event: str, item: dict | None = None) -> None:
        for fn in list(self._listeners):
            try:
                fn(event, item)
            except Exception:
                pass

    # ------------------------------------------------------------- CRUD
    def all(self) -> list[dict]:
        with self._lock:
            return sorted(
                self._items,
                key=lambda r: (r.get("done", False), r.get("due", "")),
            )

    def pending(self) -> list[dict]:
        return [r for r in self.all() if not r.get("done")]

    def get(self, rid: str) -> dict | None:
        with self._lock:
            for r in self._items:
                if r["id"] == rid:
                    return dict(r)
        return None

    def create(self, text: str, due: str, repeat: str = REPEAT_NONE,
               notes: str = "") -> dict:
        with self._lock:
            item = {
                "id": new_id(),
                "text": (text or "Reminder").strip(),
                "due": due,                       # ISO datetime
                "repeat": repeat or REPEAT_NONE,
                "notes": (notes or "").strip(),
                "done": False,
                "fired_at": "",
                "created_at": _now_iso(),
            }
            self._items.append(item)
            self.save()
        self._emit("created", dict(item))
        return dict(item)

    def update(self, rid: str, text: str | None = None, due: str | None = None,
               repeat: str | None = None, notes: str | None = None) -> dict | None:
        with self._lock:
            for r in self._items:
                if r["id"] == rid:
                    if text is not None and text.strip():
                        r["text"] = text.strip()
                    if due is not None and due:
                        r["due"] = due
                    if repeat is not None:
                        r["repeat"] = repeat
                    if notes is not None:
                        r["notes"] = notes.strip()
                    self.save()
                    out = dict(r)
                    break
            else:
                return None
        self._emit("updated", out)
        return out

    def delete(self, rid: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [r for r in self._items if r["id"] != rid]
            removed = len(self._items) < before
            if removed:
                self.save()
        if removed:
            self._emit("deleted", {"id": rid})
        return removed

    def complete(self, rid: str) -> dict | None:
        item = self.get(rid)
        if not item:
            return None
        if item.get("repeat", REPEAT_NONE) != REPEAT_NONE:
            # repeating reminders reschedule instead of completing
            nxt = self._next_occurrence(item)
            if nxt:
                return self.update(rid, due=nxt)
        with self._lock:
            for r in self._items:
                if r["id"] == rid:
                    r["done"] = True
                    self.save()
                    out = dict(r)
                    break
        self._emit("updated", out)
        return out

    def reopen(self, rid: str) -> dict | None:
        with self._lock:
            for r in self._items:
                if r["id"] == rid:
                    r["done"] = False
                    self.save()
                    out = dict(r)
                    break
            else:
                return None
        self._emit("updated", out)
        return out

    def snooze(self, rid: str, minutes: int = 5) -> dict | None:
        item = self.get(rid)
        if not item:
            return None
        base = datetime.now()
        try:
            old = datetime.fromisoformat(item["due"])
            if old > base:
                base = old
        except Exception:
            pass
        return self.update(rid, due=(base + timedelta(minutes=minutes)).isoformat(timespec="seconds"))

    def set_fired(self, rid: str) -> None:
        with self._lock:
            for r in self._items:
                if r["id"] == rid:
                    r["fired_at"] = _now_iso()
                    self.save()
                    return

    # -------------------------------------------------------- scheduler
    def _next_occurrence(self, item: dict) -> str | None:
        try:
            due = datetime.fromisoformat(item["due"])
        except Exception:
            return None
        rep = item.get("repeat", REPEAT_NONE)
        base = max(due, datetime.now())
        if rep == REPEAT_DAILY:
            nxt = base + timedelta(days=1)
        elif rep == REPEAT_WEEKDAYS:
            nxt = base + timedelta(days=1)
            while nxt.weekday() >= 5:
                nxt += timedelta(days=1)
        elif rep == REPEAT_WEEKLY:
            nxt = base + timedelta(weeks=1)
        elif rep == REPEAT_MONTHLY:
            month = base.month + 1 if base.month < 12 else 1
            year = base.year + (1 if base.month == 12 else 0)
            day = min(base.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                                 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
            nxt = base.replace(year=year, month=month, day=day)
        else:
            return None
        return nxt.isoformat(timespec="seconds")

    def due_now(self, within_seconds: int = 30) -> list[dict]:
        """Reminders whose time has come (used by the scheduler tick)."""
        now = datetime.now()
        out = []
        for r in self.pending():
            try:
                due = datetime.fromisoformat(r["due"])
            except Exception:
                continue
            if due <= now and (now - due).total_seconds() <= within_seconds + 25:
                out.append(r)
        return out
