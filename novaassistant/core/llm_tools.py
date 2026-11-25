"""LLM tool schema + executor bridge (notes / reminders / desktop / system)."""
from __future__ import annotations

from datetime import datetime

from . import tools as desk

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Launch a desktop application by name (spotify, chrome, notepad, vscode, calculator...).",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Application name"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_folder",
            "description": "Open a folder in the file explorer (downloads, documents, desktop, or any path).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Folder name or path"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Open a website URL in the default browser.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_path",
            "description": "Open any file or folder with the OS default handler.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files in a folder.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "Create a new note. Topic is a short category like 'note', 'bucket', 'work', 'idea'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_note",
            "description": "Edit an EXISTING note (matched by id or title fragment). Updates in place, never duplicates. Keeps its topic unless a new one is given.",
            "parameters": {
                "type": "object",
                "properties": {
                    "note": {"type": "string", "description": "Note id or existing title fragment"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_note",
            "description": "Delete a note by id or title fragment.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_notes",
            "description": "Search notes by query; returns matching notes.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder. Use ISO datetime for due (e.g. 2026-09-10T18:00:00). Repeat: none|daily|weekdays|weekly|monthly or weekly:N (N=0 Monday..6 Sunday).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "due": {"type": "string"},
                    "repeat": {"type": "string"},
                    "notes": {"type": "string", "description": "Optional notes for the reminder."},
                },
                "required": ["text", "due"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List pending reminders.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_reminder",
            "description": "Mark a reminder complete by id or text fragment.",
            "parameters": {
                "type": "object",
                "properties": {"reminder": {"type": "string"}},
                "required": ["reminder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_reminder",
            "description": "Delete a reminder by id or text fragment.",
            "parameters": {
                "type": "object",
                "properties": {"reminder": {"type": "string"}},
                "required": ["reminder"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_datetime",
            "description": "Get the current local date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class ToolExecutor:
    """Runs tool calls against the stores + desktop; thread-safe."""

    def __init__(self, notes_store, reminders_store, activity_log):
        self.notes = notes_store
        self.reminders = reminders_store
        self.activity = activity_log
        self.steps: list[tuple[str, str]] = []   # (label, status) for overlay
        self._cancelled = False

    def reset(self, cancelled: bool = False) -> None:
        self.steps = []
        self._cancelled = cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    # ------------------------------------------------------------ run
    def run(self, name: str, arguments: dict) -> dict:
        try:
            handler = getattr(self, "_tool_" + name, None)
            if handler is None:
                return {"ok": False, "error": f"Unknown tool {name}"}
            result = handler(**(arguments or {}))
            self._log_result(name, result)
            return result
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            self._log_result(name, result)
            return result

    def _log_result(self, name: str, result: dict) -> None:
        ok = bool(result.get("ok", True))
        self.activity.log(
            "tool",
            f"{name}: {result.get('detail') or result.get('error') or 'done'}",
            status="ok" if ok else "err",
        )

    # ---------------------------------------------------------- tools
    @staticmethod
    def _tool_open_app(name: str) -> dict:
        return desk.open_app(name)

    @staticmethod
    def _tool_open_folder(path: str) -> dict:
        return desk.open_folder(path)

    @staticmethod
    def _tool_open_url(url: str) -> dict:
        return desk.open_url(url)

    @staticmethod
    def _tool_open_path(path: str) -> dict:
        return desk.open_path(path)

    @staticmethod
    def _tool_list_dir(path: str = "~") -> dict:
        return desk.list_dir(path)

    def _tool_create_note(self, title: str, content: str = "", topic: str = "note") -> dict:
        note = self.notes.create(title, content, topic)
        self.activity.log("note", f"Saved note [{note['topic']}]: {note['title']}")
        return {"ok": True, "detail": f"Note created with topic '{note['topic']}'",
                "id": note["id"]}

    def _tool_update_note(self, note: str, title: str | None = None,
                          content: str | None = None, topic: str | None = None) -> dict:
        existing = None
        if note:
            existing = self.notes.get(note) or self.notes.find_by_title(note)
        if not existing:
            return {"ok": False, "error": f"No existing note matches '{note}'"}
        updated = self.notes.update(
            existing["id"], title=title, content=content, topic=topic)
        if not updated:
            return {"ok": False, "error": "Update failed"}
        self.activity.log("note", f"Updated note #{updated['id'][-4:]} "
                                  f"[{updated['topic']}]: {updated['title']}")
        return {"ok": True, "detail": f"Updated existing note '{updated['title']}' "
                                      f"(topic kept: {updated['topic']})"}

    def _tool_delete_note(self, note: str) -> dict:
        existing = self.notes.get(note) or self.notes.find_by_title(note)
        if not existing:
            return {"ok": False, "error": f"No note matches '{note}'"}
        self.notes.delete(existing["id"])
        return {"ok": True, "detail": f"Deleted note '{existing['title']}'"}

    def _tool_search_notes(self, query: str) -> dict:
        hits = self.notes.search(query)
        lines = [f"- [{n['topic']}] {n['title']}: {n['content'][:80]}" for n in hits[:8]]
        return {"ok": True,
                "detail": f"{len(hits)} note(s) found",
                "results": "\n".join(lines) if lines else "No notes matched."}

    def _tool_create_reminder(self, text: str, due: str, repeat: str = "none",
                              notes: str = "") -> dict:
        try:
            datetime.fromisoformat(due)
        except Exception:
            return {"ok": False, "error": f"Invalid datetime: {due}"}
        item = self.reminders.create(text, due, repeat or "none", notes or "")
        display_due = datetime.fromisoformat(item["due"]).strftime("%Y-%m-%d %I:%M %p")
        self.activity.log("reminder", f"Reminder set: {item['text']} @ {display_due}")
        return {"ok": True, "detail": f"Reminder set for {display_due}: {item['text']}",
                "id": item["id"]}

    def _tool_list_reminders(self) -> dict:
        items = self.reminders.pending()
        lines = [f"- #{r['id'][-4:]} {r['text']} @ "
                 f"{datetime.fromisoformat(r['due']).strftime('%Y-%m-%d %I:%M %p')} "
                 f"(repeat: {r['repeat']})"
                 for r in items[:15]]
        return {"ok": True, "detail": f"{len(items)} pending reminder(s)",
                "results": "\n".join(lines) if lines else "No pending reminders."}

    def _find_reminder(self, ref: str) -> dict | None:
        for r in self.reminders.all():
            if r["id"] == ref:
                return r
        q = (ref or "").lower().strip()
        for r in self.reminders.all():
            if q and q in r["text"].lower():
                return r
        return None

    def _tool_complete_reminder(self, reminder: str) -> dict:
        item = self._find_reminder(reminder)
        if not item:
            return {"ok": False, "error": f"No reminder matches '{reminder}'"}
        self.reminders.complete(item["id"])
        return {"ok": True, "detail": f"Completed: {item['text']}"}

    def _tool_delete_reminder(self, reminder: str) -> dict:
        item = self._find_reminder(reminder)
        if not item:
            return {"ok": False, "error": f"No reminder matches '{reminder}'"}
        self.reminders.delete(item["id"])
        return {"ok": True, "detail": f"Deleted reminder: {item['text']}"}

    @staticmethod
    def _tool_get_current_datetime() -> dict:
        now = datetime.now()
        return {"ok": True,
                "detail": now.strftime("%A, %B %d, %Y — %I:%M %p"),
                "iso": now.isoformat(timespec="seconds"),
                "results": now.strftime("%A, %B %d, %Y — %I:%M %p")}
