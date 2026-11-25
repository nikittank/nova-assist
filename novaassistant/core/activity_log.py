"""Activity log — the "Live Execution Audit Stream" backend.

Tracks every action in the pipeline:
  user request -> AI reasoning -> tool execution -> success / failure / cancel

Each entry carries a category, message, status (ok | err | cancel), optional
detail (collapsed in the UI but always available), and a stable timestamp so
the Activity page can render a deterministic timeline.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

MAX_ENTRIES = 500


class ActivityLog:
    default_instance: "ActivityLog | None" = None   # for global error hooks

    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "activity.json")
        self._lock = threading.RLock()
        self._entries: list[dict] = []
        self._listeners = []
        self._counters = {"ok": 0, "err": 0, "cancel": 0}
        self._dedupe_key: dict[str, str] = {}   # last message per category
        self.load()

    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    self._entries = json.load(fh)
                for e in self._entries:
                    st = e.get("status", "ok")
                    self._counters[st] = self._counters.get(st, 0) + 1
        except Exception:
            self._entries = []

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self._entries[:MAX_ENTRIES], fh, indent=2, ensure_ascii=False)
                os.replace(tmp, self.path)
            except Exception:
                pass

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn) -> None:
        try:
            self._listeners.remove(fn)
        except ValueError:
            pass

    def log(self, category: str, message: str, status: str = "ok",
            detail: str = "", source: str = "", target: str = "",
            dedupe: bool = False) -> dict:
        """Append one activity entry.

        ``category``   tool | note | reminder | system | voice | error | user | ai
        ``status``     ok | err | cancel
        ``source``     who started it (user / ai / system / scheduler)
        ``target``     what it touched (note id, reminder id, file path, app)
        ``dedupe``     if True, an identical (category, message) entry within
                       the last 1.5 s replaces the previous one instead of
                       appending a duplicate — used for rapid state updates.
        """
        # ---- dedupe -----------------------------------------------------
        if dedupe:
            key = f"{category}|{message}"
            with self._lock:
                prev_ts = self._dedupe_key.get(key)
                now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if prev_ts and prev_ts == now_iso:
                    # same second + same message: replace the last entry
                    if self._entries and \
                            self._entries[0].get("category") == category and \
                            self._entries[0].get("message") == message:
                        self._entries[0].update({
                            "status": status, "detail": detail,
                            "source": source, "target": target,
                        })
                        self.save()
                        self._notify(self._entries[0])
                        return self._entries[0]
                self._dedupe_key[key] = now_iso

        entry = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "category": category,
            "message": message,
            "status": status,
            "detail": detail,
            "source": source,
            "target": target,
        }
        with self._lock:
            self._entries.insert(0, entry)
            self._entries = self._entries[:MAX_ENTRIES]
            self._counters[status] = self._counters.get(status, 0) + 1
            self.save()
        self._notify(entry)
        return entry

    def _notify(self, entry: dict) -> None:
        for fn in list(self._listeners):
            try:
                fn(entry)
            except Exception:
                pass

    def entries(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return list(self._entries[:limit])

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._counters = {"ok": 0, "err": 0, "cancel": 0}
            self._dedupe_key = {}
            self.save()
        for fn in list(self._listeners):
            try:
                fn({"cleared": True})
            except Exception:
                pass

    def stats(self) -> dict:
        with self._lock:
            total = len(self._entries)
            ok = sum(1 for e in self._entries if e.get("status") == "ok")
            errs = sum(1 for e in self._entries if e.get("status") == "err")
            cancels = sum(1 for e in self._entries
                           if e.get("status") == "cancel")
            cats = {}
            for e in self._entries:
                cats[e.get("category", "system")] = \
                    cats.get(e.get("category", "system"), 0) + 1
        rate = (ok / total * 100.0) if total else 100.0
        return {
            "total": total,
            "ok": ok,
            "errors": errs,
            "cancellations": cancels,
            "success_rate": rate,
            "active_tools": max(1, len(cats)),
            "categories": cats,
        }
