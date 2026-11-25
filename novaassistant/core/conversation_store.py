"""Conversation store — chat transcript persistence + memory window."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

MAX_MESSAGES = 300


class ConversationStore:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "conversation.json")
        self._lock = threading.RLock()
        self._messages: list[dict] = []
        self._listeners = []
        self.load()

    def load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    self._messages = json.load(fh)
        except Exception:
            self._messages = []

    def save(self) -> None:
        with self._lock:
            try:
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(self._messages[-MAX_MESSAGES:], fh, indent=2, ensure_ascii=False)
                os.replace(tmp, self.path)
            except Exception:
                pass

    def add_listener(self, fn) -> None:
        self._listeners.append(fn)

    def add(self, role: str, text: str, meta: dict | None = None) -> dict:
        msg = {
            "role": role,  # user | nova | error
            "text": text,
            "ts": datetime.now().strftime("%I:%M %p").lstrip("0"),
            "meta": meta or {},
        }
        with self._lock:
            self._messages.append(msg)
            self._messages = self._messages[-MAX_MESSAGES:]
            self.save()
        for fn in list(self._listeners):
            try:
                fn(msg)
            except Exception:
                pass
        return msg

    def messages(self) -> list[dict]:
        with self._lock:
            return list(self._messages)

    def memory(self, n: int) -> list[dict]:
        """Last n messages as {role, content} for the LLM context."""
        with self._lock:
            window = self._messages[-n:]
        out = []
        for m in window:
            if m["role"] in ("user", "nova"):
                out.append({
                    "role": "user" if m["role"] == "user" else "assistant",
                    "content": m["text"],
                })
        return out

    def clear(self) -> None:
        with self._lock:
            self._messages = []
            self.save()
        for fn in list(self._listeners):
            try:
                fn({"cleared": True})
            except Exception:
                pass
