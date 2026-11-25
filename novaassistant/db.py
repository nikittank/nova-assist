"""Nova Assistant - local SQLite storage.

All personal data (notes, reminders, conversation history, activity log)
lives in a single SQLite file inside the app's data directory.  The class
is thread-safe (a single lock guards every operation) because it is used
from the GUI thread, the agent thread and the reminder scheduler thread.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    topic TEXT DEFAULT 'general',
    created_at TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    next_trigger TEXT NOT NULL,
    recurrence TEXT DEFAULT 'none',
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    last_fired TEXT
);
CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT,
    status TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

# Lightweight, idempotent upgrades for databases created by older builds.
MIGRATIONS = [
    "ALTER TABLE reminders ADD COLUMN note_id INTEGER",
    "ALTER TABLE reminders ADD COLUMN completed_at TEXT",
    "CREATE INDEX IF NOT EXISTS idx_reminders_note ON reminders (note_id)",
    "CREATE INDEX IF NOT EXISTS idx_reminders_active ON reminders (active, next_trigger)",
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


class Database:
    def __init__(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            for stmt in MIGRATIONS:
                try:
                    self._conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # column/index already exists
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ util
    @staticmethod
    def _rowdict(row: Optional[sqlite3.Row]) -> Optional[dict]:
        return dict(row) if row is not None else None

    def _execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            try:
                rows = cur.fetchall()
            finally:
                cur.close()  # RETURNING statements must be reset before commit
            self._conn.commit()
            return rows

    # ----------------------------------------------------------------- notes
    def add_note(self, content: str, topic: str = "general") -> dict:
        rows = self._execute(
            "INSERT INTO notes (content, topic, created_at) VALUES (?, ?, ?) RETURNING id",
            (content.strip(), (topic.strip() or "general").lower(), now_iso()),
        )
        return {"id": rows[0]["id"]}

    def get_note(self, note_id: int) -> Optional[dict]:
        rows = self._execute("SELECT * FROM notes WHERE id = ?", (note_id,))
        return self._rowdict(rows[0] if rows else None)

    def update_note(self, note_id: int, content: str, topic: Optional[str] = None) -> bool:
        """Update an EXISTING note in place. Returns False if it does not exist."""
        if self.get_note(note_id) is None:
            return False
        if topic is None:
            self._execute(
                "UPDATE notes SET content = ?, updated_at = ? WHERE id = ?",
                (content.strip(), now_iso(), note_id),
            )
        else:
            self._execute(
                "UPDATE notes SET content = ?, topic = ?, updated_at = ? WHERE id = ?",
                (content.strip(), (topic.strip() or "general").lower(), now_iso(), note_id),
            )
        return True

    def delete_note(self, note_id: int) -> None:
        self._execute("DELETE FROM notes WHERE id = ?", (note_id,))
        # detach any reminders pointing at the deleted note
        self._execute("UPDATE reminders SET note_id = NULL WHERE note_id = ?", (note_id,))

    def list_notes(self, limit: int = 200, topic: str = "") -> list[dict]:
        if topic:
            rows = self._execute(
                "SELECT * FROM notes WHERE topic LIKE ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (f"%{topic.strip().lower()}%", limit),
            )
        else:
            rows = self._execute(
                "SELECT * FROM notes ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in rows]

    def search_notes(self, query: str, limit: int = 20) -> list[dict]:
        like = f"%{query.strip()}%"
        rows = self._execute(
            """SELECT * FROM notes
               WHERE content LIKE ? OR topic LIKE ?
               ORDER BY created_at DESC, id DESC LIMIT ?""",
            (like, like, limit),
        )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- reminders
    def add_reminder(self, message: str, next_trigger: str, recurrence: str = "none",
                     note_id: Optional[int] = None) -> dict:
        rows = self._execute(
            "INSERT INTO reminders (message, next_trigger, recurrence, active, created_at, note_id) "
            "VALUES (?, ?, ?, 1, ?, ?) RETURNING id",
            (message, next_trigger, recurrence or "none", now_iso(), note_id),
        )
        return {"id": rows[0]["id"]}

    def list_reminders(self, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM reminders"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY next_trigger ASC, id ASC"
        return [dict(r) for r in self._execute(sql)]

    def get_reminder(self, reminder_id: int) -> Optional[dict]:
        rows = self._execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        return self._rowdict(rows[0] if rows else None)

    def note_reminder(self, note_id: int) -> Optional[dict]:
        rows = self._execute(
            "SELECT * FROM reminders WHERE note_id = ? ORDER BY id DESC LIMIT 1", (note_id,)
        )
        return self._rowdict(rows[0] if rows else None)

    def update_reminder(self, reminder_id: int, message: Optional[str] = None,
                        next_trigger: Optional[str] = None,
                        recurrence: Optional[str] = None,
                        note_id: Any = "__unset__") -> bool:
        """Edit an existing reminder in place. Returns False if it does not exist."""
        if self.get_reminder(reminder_id) is None:
            return False
        sets, params = [], []
        if message is not None:
            sets.append("message = ?")
            params.append(message)
        if next_trigger is not None:
            sets.append("next_trigger = ?")
            params.append(next_trigger)
        if recurrence is not None:
            sets.append("recurrence = ?")
            params.append(recurrence)
        if note_id != "__unset__":
            sets.append("note_id = ?")
            params.append(note_id)
        if sets:
            params.append(reminder_id)
            self._execute(f"UPDATE reminders SET {', '.join(sets)} WHERE id = ?", tuple(params))
        return True

    def set_reminder_active(self, reminder_id: int, active: bool) -> None:
        stamp = now_iso() if not active else None
        if active:
            self._execute("UPDATE reminders SET active = ?, completed_at = NULL WHERE id = ?",
                          (1, reminder_id))
        else:
            self._execute("UPDATE reminders SET active = ?, completed_at = ? WHERE id = ?",
                          (0, stamp, reminder_id))

    def due_reminders(self, now_key: str) -> list[dict]:
        rows = self._execute(
            "SELECT * FROM reminders WHERE active = 1 AND next_trigger <= ? ORDER BY next_trigger",
            (now_key,),
        )
        return [dict(r) for r in rows]

    def set_reminder_trigger(self, reminder_id: int, next_trigger: Optional[str],
                             active: Optional[bool] = None) -> None:
        if next_trigger is not None:
            self._execute(
                "UPDATE reminders SET next_trigger = ?, last_fired = ? WHERE id = ?",
                (next_trigger, now_iso(), reminder_id),
            )
        if active is not None:
            self._execute(
                "UPDATE reminders SET active = ? WHERE id = ?", (1 if active else 0, reminder_id)
            )

    def delete_reminder(self, reminder_id: int) -> None:
        self._execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

    def delete_reminders_for_note(self, note_id: int) -> None:
        self._execute("DELETE FROM reminders WHERE note_id = ?", (note_id,))

    # -------------------------------------------------------------- activity
    def log_activity(self, kind: str, detail: str = "", status: str = "ok") -> dict:
        ts = now_iso()
        self._execute(
            "INSERT INTO activity (ts, kind, detail, status) VALUES (?, ?, ?, ?)",
            (ts, kind, detail[:2000], status),
        )
        return {"ts": ts, "kind": kind, "detail": detail[:2000], "status": status}

    def recent_activity(self, limit: int = 200) -> list[dict]:
        rows = self._execute(
            "SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def clear_activity(self) -> None:
        self._execute("DELETE FROM activity")

    # -------------------------------------------------------------- messages
    def add_message(self, role: str, content: str) -> None:
        self._execute(
            "INSERT INTO messages (role, content, created_at) VALUES (?, ?, ?)",
            (role, content, now_iso()),
        )

    def recent_messages(self, limit: int = 40) -> list[dict]:
        rows = self._execute(
            "SELECT role, content, created_at FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in reversed(rows)]

    def clear_messages(self) -> None:
        self._execute("DELETE FROM messages")

    # ----------------------------------------------------------- generic json
    def kv_set(self, key: str, value: Any) -> None:
        self._execute(
            "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)", ()
        )
        self._execute(
            "INSERT INTO kv (k, v) VALUES (?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, json.dumps(value)),
        )

    def kv_get(self, key: str, default: Any = None) -> Any:
        self._execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)", ())
        rows = self._execute("SELECT v FROM kv WHERE k = ?", (key,))
        if not rows:
            return default
        try:
            return json.loads(rows[0]["v"])
        except (json.JSONDecodeError, TypeError):
            return default
