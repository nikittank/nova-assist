"""Notes store — JSON persistence with explicit edit-in-place semantics.

The duplicate-note bug is prevented by design: `update()` mutates the note
matching `note_id` and NEVER appends. UI code must pass the selected note id
to update(); `create()` is only called for brand-new notes.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from ..config import new_id


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class NotesStore:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "notes.json")
        self._lock = threading.RLock()
        self._notes: list[dict] = []
        self._listeners = []
        self.load()

    # ------------------------------------------------------- persistence
    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    self._notes = json.load(fh)
        except Exception:
            self._notes = []

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._notes, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    # -------------------------------------------------------- observers
    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def _emit(self, event: str, note: dict | None = None) -> None:
        for fn in list(self._listeners):
            try:
                fn(event, note)
            except Exception:
                pass

    # ------------------------------------------------------------- CRUD
    def all(self) -> list[dict]:
        with self._lock:
            return sorted(self._notes, key=lambda n: n["updated_at"], reverse=True)

    def get(self, note_id: str) -> dict | None:
        with self._lock:
            for n in self._notes:
                if n["id"] == note_id:
                    return dict(n)
        return None

    def create(self, title: str, content: str = "", topic: str = "note") -> dict:
        with self._lock:
            note = {
                "id": new_id(),
                "title": (title or "Untitled note").strip(),
                "content": content or "",
                "topic": (topic or "note").strip().lower() or "note",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
            }
            self._notes.append(note)
            self.save()
        self._emit("created", dict(note))
        return dict(note)

    def update(self, note_id: str, title: str | None = None,
               content: str | None = None, topic: str | None = None) -> dict | None:
        """Update an EXISTING note in place (topic preserved unless changed)."""
        with self._lock:
            for note in self._notes:
                if note["id"] == note_id:
                    if title is not None and title.strip():
                        note["title"] = title.strip()
                    if content is not None:
                        note["content"] = content
                    if topic is not None and topic.strip():
                        note["topic"] = topic.strip().lower()
                    note["updated_at"] = _now_iso()
                    self.save()
                    out = dict(note)
                    break
            else:
                return None
        self._emit("updated", out)
        return out

    def delete(self, note_id: str) -> bool:
        with self._lock:
            before = len(self._notes)
            self._notes = [n for n in self._notes if n["id"] != note_id]
            removed = len(self._notes) < before
            if removed:
                self.save()
        if removed:
            self._emit("deleted", {"id": note_id})
        return removed

    def search(self, query: str) -> list[dict]:
        q = (query or "").lower().strip()
        if not q:
            return self.all()
        with self._lock:
            hits = [
                dict(n) for n in self._notes
                if q in n["title"].lower()
                or q in n["content"].lower()
                or q in n["topic"].lower()
            ]
        return sorted(hits, key=lambda n: n["updated_at"], reverse=True)

    def find_by_title(self, title_query: str) -> dict | None:
        """Fuzzy-ish lookup used by the LLM tool layer."""
        q = (title_query or "").lower().strip()
        if not q:
            return None
        notes = self.all()
        for n in notes:
            if n["title"].lower() == q:
                return n
        for n in notes:
            if q in n["title"].lower():
                return n
        return None
