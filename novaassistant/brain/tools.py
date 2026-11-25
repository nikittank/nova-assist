"""Tool registry: JSON schemas for the LLM, whitelisted handlers, and the
per-level confirmation policy.

The LLM can ONLY call these functions - it has no generic shell or
filesystem access.  Sensitive actions are gated by the confirmation
policy which depends on the configured level (relaxed/balanced/strict):

  * relaxed  - confirm DELETE + shell commands only
  * balanced - also confirm writes/moves/renames/app closes
  * strict   - confirm everything that touches the system
"""

from __future__ import annotations

import json
from typing import Callable, Optional

from ..services import automation
from ..services.reminders import RECURRENCES

MAX_TOOL_RESULT_CHARS = 6000


class ToolContext:
    """Shared objects the note/reminder handlers need."""

    def __init__(self, db, config) -> None:
        self.db = db
        self.config = config


# ----------------------------------------------------------------- helpers
def _resolve_note(args: dict, ctx: ToolContext) -> Optional[dict]:
    """Find a note by explicit id, else by the best search match."""
    note_id = args.get("note_id")
    if note_id not in (None, ""):
        try:
            return ctx.db.get_note(int(note_id))
        except (TypeError, ValueError):
            return None
    query = (args.get("query") or "").strip()
    if query:
        rows = ctx.db.search_notes(query, 5)
        if rows:
            return rows[0]
    return None


# ------------------------------------------------------------------- notes
def _note_add(args: dict, ctx: ToolContext) -> dict:
    content = (args.get("content") or "").strip()
    if not content:
        return {"ok": False, "message": "The note was empty."}
    topic = (args.get("topic") or "general").strip().lower()
    row = ctx.db.add_note(content, topic)
    ctx.db.log_activity("note", f"Saved note #{row['id']} [{topic}]: {content[:80]}")
    return {"ok": True, "message": f"Note saved with topic '{topic}'.", "id": row["id"]}


def _note_update(args: dict, ctx: ToolContext) -> dict:
    """Edit an EXISTING note in place - never creates a duplicate."""
    note = _resolve_note(args, ctx)
    if note is None:
        return {"ok": False,
                "message": "No matching note found. Use search_notes first to "
                           "locate the note id, then retry with its numeric id."}
    new_content = (args.get("content") or "").strip()
    if not new_content:
        return {"ok": False, "message": "The new note content was empty."}
    # keep the existing topic unless the user explicitly provides a new one
    new_topic = (args.get("topic") or "").strip().lower() or None
    ok = ctx.db.update_note(note["id"], new_content, new_topic)
    if not ok:
        return {"ok": False, "message": f"Note #{note['id']} no longer exists."}
    topic_txt = new_topic or note["topic"]
    ctx.db.log_activity("note", f"Edited note #{note['id']} [{topic_txt}]")
    return {"ok": True,
            "message": f"Note #{note['id']} updated in place (topic '{topic_txt}' kept).",
            "id": note["id"], "topic": topic_txt}


def _note_delete(args: dict, ctx: ToolContext) -> dict:
    note = _resolve_note(args, ctx)
    if note is None:
        return {"ok": False, "message": "No matching note found."}
    ctx.db.delete_reminders_for_note(note["id"])
    ctx.db.delete_note(note["id"])
    ctx.db.log_activity("note", f"Deleted note #{note['id']}: {note['content'][:60]}")
    return {"ok": True, "message": f"Deleted note #{note['id']} and its reminders."}


def _note_search(args: dict, ctx: ToolContext) -> dict:
    query = (args.get("query") or "").strip()
    limit = max(1, min(int(args.get("limit") or 10), 25))
    if not query:
        return {"ok": False, "message": "No search query given."}
    rows = ctx.db.search_notes(query, limit)
    if not rows:
        return {"ok": True, "message": f"No notes matching '{query}'.", "notes": []}
    return {"ok": True, "message": f"Found {len(rows)} note(s).",
            "notes": [{"id": r["id"], "topic": r["topic"], "created_at": r["created_at"],
                       "content": r["content"][:600]} for r in rows]}


def _note_recent(args: dict, ctx: ToolContext) -> dict:
    limit = max(1, min(int(args.get("limit") or 5), 25))
    rows = ctx.db.list_notes(limit)
    return {"ok": True, "message": f"Retrieved {len(rows)} recent note(s).",
            "notes": [{"id": r["id"], "topic": r["topic"], "created_at": r["created_at"],
                       "content": r["content"][:600]} for r in rows]}


# --------------------------------------------------------------- reminders
def _rem_set(args: dict, ctx: ToolContext) -> dict:
    from ..services.reminders import ReminderService  # local import avoids cycle
    svc = ReminderService(ctx.db, on_fire=lambda _r: None)
    note_id = args.get("note_id")
    note = None
    if note_id not in (None, ""):
        note = _resolve_note({"note_id": note_id}, ctx)
    result = svc.add(args.get("message") or "", args.get("when") or "",
                     args.get("recurrence") or "none",
                     note_id=note["id"] if note else None)
    if result.get("ok"):
        ctx.db.log_activity("reminder",
                            f"Set reminder #{result.get('id')}: {args.get('message')}"
                            f" @ {result.get('next')}"
                            + (f" (linked to note #{note['id']})" if note else ""))
    return result


def _rem_list(args: dict, ctx: ToolContext) -> dict:
    rows = ctx.db.list_reminders(active_only=True)
    if not rows:
        return {"ok": True, "message": "There are no active reminders.", "reminders": []}
    return {"ok": True, "message": f"{len(rows)} active reminder(s).",
            "reminders": [{"id": r["id"], "message": r["message"],
                           "next": r["next_trigger"], "recurrence": r["recurrence"]}
                          for r in rows]}


def _rem_update(args: dict, ctx: ToolContext) -> dict:
    from ..services.reminders import ReminderService
    try:
        rid = int(args.get("reminder_id"))
    except (TypeError, ValueError):
        return {"ok": False, "message": "A numeric reminder_id is required."}
    svc = ReminderService(ctx.db, on_fire=lambda _r: None)
    result = svc.update(rid, args.get("message"), args.get("when"),
                        args.get("recurrence"))
    if result.get("ok"):
        ctx.db.log_activity("reminder", f"Edited reminder #{rid}")
    return result


def _rem_delete(args: dict, ctx: ToolContext) -> dict:
    try:
        rid = int(args.get("reminder_id"))
    except (TypeError, ValueError):
        return {"ok": False, "message": "A numeric reminder_id is required."}
    rem = ctx.db.get_reminder(rid)
    if not rem:
        return {"ok": False, "message": f"No reminder with id {rid}."}
    ctx.db.delete_reminder(rid)
    ctx.db.log_activity("reminder", f"Deleted reminder #{rid}: {rem['message']}")
    return {"ok": True, "message": f"Deleted reminder '{rem['message'][:60]}'."}


def _rem_complete(args: dict, ctx: ToolContext) -> dict:
    from ..services.reminders import ReminderService
    try:
        rid = int(args.get("reminder_id"))
    except (TypeError, ValueError):
        return {"ok": False, "message": "A numeric reminder_id is required."}
    result = ReminderService(ctx.db, on_fire=lambda _r: None).complete(rid)
    return result


def _rem_snooze(args: dict, ctx: ToolContext) -> dict:
    from ..services.reminders import ReminderService
    try:
        rid = int(args.get("reminder_id"))
    except (TypeError, ValueError):
        return {"ok": False, "message": "A numeric reminder_id is required."}
    minutes = 10
    try:
        minutes = max(1, int(args.get("minutes") or 10))
    except (TypeError, ValueError):
        pass
    result = ReminderService(ctx.db, on_fire=lambda _r: None).snooze(rid, minutes)
    return result


# note-attached reminders --------------------------------------------------
def _note_reminder_add(args: dict, ctx: ToolContext) -> dict:
    note = _resolve_note(args, ctx)
    if note is None:
        return {"ok": False, "message": "No matching note found."}
    old = ctx.db.note_reminder(note["id"])
    if old is not None:
        ctx.db.delete_reminder(old["id"])
    result = _rem_set({"message": args.get("message") or note["content"][:80],
                       "when": args.get("when"), "recurrence": args.get("recurrence"),
                       "note_id": note["id"]}, ctx)
    if result.get("ok"):
        result["message"] = (f"Reminder attached to note #{note['id']}: "
                             + result.get("message", ""))
    return result


def _note_reminder_remove(args: dict, ctx: ToolContext) -> dict:
    note = _resolve_note(args, ctx)
    if note is None:
        return {"ok": False, "message": "No matching note found."}
    old = ctx.db.note_reminder(note["id"])
    if old is None:
        return {"ok": True, "message": f"Note #{note['id']} has no reminder."}
    ctx.db.delete_reminder(old["id"])
    return {"ok": True, "message": f"Removed the reminder from note #{note['id']}."}


# ------------------------------------------------------------------- focus
def _set_focus(args: dict, ctx: ToolContext) -> dict:
    focus = (args.get("text") or "").strip()
    if not focus:
        return {"ok": False, "message": "Focus text was empty."}
    ctx.db.kv_set("focus", focus)
    ctx.db.log_activity("focus", f"Focus set: {focus[:80]}")
    return {"ok": True, "message": f"Focus set to: {focus}"}


def _t(description: str, props: dict, required: list) -> dict:
    return {"type": "function", "function": {
        "name": None, "description": description,
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


def _schema() -> list[dict]:
    tools = []

    def add(name, description, props, required, confirm, describe):
        s = _t(description, props, required)
        s["function"]["name"] = name
        tools.append(s)
        HANDLERS[name] = _HANDLERS[name]
        CONFIRM[name] = confirm
        DESCRIBE[name] = describe

    add("open_application",
        "Open a desktop application by name (e.g. 'Chrome', 'Spotify', 'VS Code').",
        {"app_name": {"type": "string", "description": "Application name"}},
        ["app_name"],
        {"relaxed": False, "balanced": False, "strict": True},
        lambda a: f"Open application '{a.get('app_name')}'")

    add("close_application",
        "Close/kill a running application by name.",
        {"app_name": {"type": "string", "description": "Application name"}},
        ["app_name"],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Close application '{a.get('app_name')}' (force-close if needed)")

    add("open_path",
        "Open a file or folder with its default application.",
        {"path": {"type": "string", "description": "Absolute or ~-relative path"}},
        ["path"],
        {"relaxed": False, "balanced": False, "strict": True},
        lambda a: f"Open '{a.get('path')}' with the default app")

    add("list_directory",
        "List the entries of a folder (defaults to the home folder).",
        {"path": {"type": "string", "description": "Folder path (optional)"}},
        [],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"List folder '{a.get('path') or '~'}'")

    add("search_files",
        "Search files by name (case-insensitive substring) starting at a folder "
        "(defaults to home). Skips system/cache folders.",
        {"query": {"type": "string", "description": "Filename text to look for"},
         "directory": {"type": "string", "description": "Folder to search in (optional)"},
         "max_results": {"type": "integer", "description": "Max matches (default 20)"}},
        ["query"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Search files for '{a.get('query')}'"
                  + (f" in {a.get('directory')}" if a.get("directory") else ""))

    add("read_file",
        "Read a text/code file (or a PDF) and return its content. Use this before "
        "explaining, summarizing or editing a file.",
        {"path": {"type": "string"}, "max_chars": {"type": "integer"}},
        ["path"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Read file '{a.get('path')}'")

    add("create_text_file",
        "Create a new text file, or OVERWRITE an existing one.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Create/overwrite file '{a.get('path')}' "
                  f"({len(a.get('content') or '')} chars)")

    add("append_to_file",
        "Append text to the end of an existing file (creates it if missing).",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Append to file '{a.get('path')}'")

    add("delete_path",
        "Delete a file or folder. Moves it to the OS trash/recycle bin when possible. "
        "ALWAYS asks the user for confirmation first.",
        {"path": {"type": "string"}}, ["path"],
        {"relaxed": True, "balanced": True, "strict": True},
        lambda a: f"DELETE '{a.get('path')}' (moved to trash when possible)")

    add("copy_file",
        "Copy a file or folder. If the destination is a folder, the item is copied into it.",
        {"source": {"type": "string"}, "destination": {"type": "string"}},
        ["source", "destination"],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Copy '{a.get('source')}' -> '{a.get('destination')}'")

    add("move_file",
        "Move a file or folder (also used to organize files).",
        {"source": {"type": "string"}, "destination": {"type": "string"}},
        ["source", "destination"],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Move '{a.get('source')}' -> '{a.get('destination')}'")

    add("rename_file",
        "Rename a file or folder within its current folder.",
        {"source": {"type": "string"}, "new_name": {"type": "string"}},
        ["source", "new_name"],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Rename '{a.get('source')}' to '{a.get('new_name')}'")

    add("create_folder",
        "Create a folder (parents are created automatically).",
        {"path": {"type": "string"}}, ["path"],
        {"relaxed": False, "balanced": False, "strict": True},
        lambda a: f"Create folder '{a.get('path')}'")

    add("run_command",
        "Run a shell/command-prompt command. ALWAYS asks the user for confirmation "
        "first. Output is captured with a 45s timeout.",
        {"command": {"type": "string"}}, ["command"],
        {"relaxed": True, "balanced": True, "strict": True},
        lambda a: f"Run command: {a.get('command')}")

    add("take_note",
        "Create a NEW personal note. Include a short lowercase topic tag "
        "(e.g. 'project', 'idea', 'todo'). Use update_note instead when the user "
        "wants to change an existing note.",
        {"content": {"type": "string"}, "topic": {"type": "string"}},
        ["content"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Save note [{a.get('topic') or 'general'}]: "
                  f"{(a.get('content') or '')[:60]}")

    add("update_note",
        "Edit an EXISTING note IN PLACE (never creates a new note). Locate the note "
        "with query (or use its numeric note_id from search_notes), then pass the "
        "full new content. The existing topic is kept unless you pass a new topic.",
        {"query": {"type": "string", "description": "Text to locate the note"},
         "note_id": {"type": "integer", "description": "Explicit note id (preferred)"},
         "content": {"type": "string", "description": "The complete new content"},
         "topic": {"type": "string", "description": "Only if the user asks to change it"}},
        ["content"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Update note #{a.get('note_id') or a.get('query')}: "
                  f"{(a.get('content') or '')[:60]}")

    add("delete_note",
        "Delete a personal note (locate by query or note_id). Also removes a "
        "reminder attached to it.",
        {"query": {"type": "string"}, "note_id": {"type": "integer"}},
        [],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Delete note #{a.get('note_id') or a.get('query')}")

    add("search_notes",
        "Search the user's saved notes by keyword or topic.",
        {"query": {"type": "string"}, "limit": {"type": "integer"}},
        ["query"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Search notes for '{a.get('query')}'")

    add("list_recent_notes",
        "List the most recent notes.",
        {"limit": {"type": "integer"}}, [],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: "List recent notes")

    add("set_reminder",
        "Create a reminder. 'when' MUST be an ISO 8601 local datetime computed from "
        "the current time (e.g. 2026-09-09T18:00:00). recurrence: none/daily/weekly/"
        "weekdays/monthly. Optionally pass note_id to attach it to a note.",
        {"message": {"type": "string"},
         "when": {"type": "string", "description": "ISO local datetime"},
         "recurrence": {"type": "string", "enum": list(RECURRENCES)},
         "note_id": {"type": "integer", "description": "Attach to a note (optional)"}},
        ["message", "when"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Set reminder '{a.get('message')}' at {a.get('when')}"
                  f" ({a.get('recurrence') or 'none'})")

    add("update_reminder",
        "Edit an EXISTING reminder in place (time, repeat rule or text). Never "
        "creates a duplicate.",
        {"reminder_id": {"type": "integer"},
         "message": {"type": "string"},
         "when": {"type": "string", "description": "New ISO local datetime"},
         "recurrence": {"type": "string", "enum": list(RECURRENCES)}},
        ["reminder_id"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Update reminder #{a.get('reminder_id')}")

    add("complete_reminder",
        "Mark a reminder as done/completed.",
        {"reminder_id": {"type": "integer"}}, ["reminder_id"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Complete reminder #{a.get('reminder_id')}")

    add("snooze_reminder",
        "Snooze a reminder by a number of minutes.",
        {"reminder_id": {"type": "integer"}, "minutes": {"type": "integer"}},
        ["reminder_id"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Snooze reminder #{a.get('reminder_id')} by {a.get('minutes') or 10} min")

    add("list_reminders",
        "List active reminders.",
        {}, [],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: "List reminders")

    add("delete_reminder",
        "Delete a reminder by its numeric id.",
        {"reminder_id": {"type": "integer"}}, ["reminder_id"],
        {"relaxed": False, "balanced": True, "strict": True},
        lambda a: f"Delete reminder #{a.get('reminder_id')}")

    add("set_note_reminder",
        "Attach (or replace) a reminder on an existing note. 'when' is an ISO 8601 "
        "local datetime; recurrence: none/daily/weekly/weekdays/monthly.",
        {"query": {"type": "string", "description": "Locate the note by text"},
         "note_id": {"type": "integer"},
         "message": {"type": "string", "description": "Reminder text (defaults to the note)"},
         "when": {"type": "string", "description": "ISO local datetime"},
         "recurrence": {"type": "string", "enum": list(RECURRENCES)}},
        ["when"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Attach reminder to note #{a.get('note_id') or a.get('query')} "
                  f"at {a.get('when')}")

    add("remove_note_reminder",
        "Remove the reminder attached to a note (the note itself is kept).",
        {"query": {"type": "string"}, "note_id": {"type": "integer"}},
        [],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Remove reminder from note #{a.get('note_id') or a.get('query')}")

    add("set_focus",
        "Set the user's current focus shown on the Focus desktop widget "
        "(e.g. 'Finish the Q3 report').",
        {"text": {"type": "string"}}, ["text"],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: f"Set focus: {a.get('text')}")

    add("get_system_info",
        "Get basic system information (OS, home folder, current time context).",
        {}, [],
        {"relaxed": False, "balanced": False, "strict": False},
        lambda a: "Read system information")

    return tools


_HANDLERS: dict[str, Callable] = {
    "open_application": lambda a, ctx: automation.open_application(a.get("app_name", "")),
    "close_application": lambda a, ctx: automation.close_application(a.get("app_name", "")),
    "open_path": lambda a, ctx: automation.open_path(a.get("path", "")),
    "list_directory": lambda a, ctx: automation.list_directory(a.get("path") or ""),
    "search_files": lambda a, ctx: automation.search_files(
        a.get("query", ""), a.get("directory") or "", a.get("max_results") or 20),
    "read_file": lambda a, ctx: automation.read_file(
        a.get("path", ""), a.get("max_chars") or 24000),
    "create_text_file": lambda a, ctx: automation.create_text_file(
        a.get("path", ""), a.get("content", "")),
    "append_to_file": lambda a, ctx: automation.append_to_file(
        a.get("path", ""), a.get("content", "")),
    "delete_path": lambda a, ctx: automation.delete_path(a.get("path", "")),
    "copy_file": lambda a, ctx: automation.copy_file(
        a.get("source", ""), a.get("destination", "")),
    "move_file": lambda a, ctx: automation.move_file(
        a.get("source", ""), a.get("destination", "")),
    "rename_file": lambda a, ctx: automation.rename_file(
        a.get("source", ""), a.get("new_name", "")),
    "create_folder": lambda a, ctx: automation.create_folder(a.get("path", "")),
    "run_command": lambda a, ctx: automation.run_command(a.get("command", "")),
    "take_note": _note_add,
    "update_note": _note_update,
    "delete_note": _note_delete,
    "search_notes": _note_search,
    "list_recent_notes": _note_recent,
    "set_reminder": _rem_set,
    "update_reminder": _rem_update,
    "complete_reminder": _rem_complete,
    "snooze_reminder": _rem_snooze,
    "list_reminders": _rem_list,
    "delete_reminder": _rem_delete,
    "set_note_reminder": _note_reminder_add,
    "remove_note_reminder": _note_reminder_remove,
    "set_focus": _set_focus,
    "get_system_info": lambda a, ctx: automation.get_system_info(),
}

HANDLERS: dict[str, Callable[[dict, ToolContext], dict]] = {}
CONFIRM: dict[str, dict[str, bool]] = {}
DESCRIBE: dict[str, Callable[[dict], str]] = {}
TOOLS: list[dict] = _schema()


def tool_names() -> list[str]:
    return [t["function"]["name"] for t in TOOLS]


def needs_confirmation(name: str, level: str) -> bool:
    flags = CONFIRM.get(name)
    if not flags:
        return False
    return bool(flags.get(level, flags.get("balanced", True)))


def describe(name: str, args: dict) -> str:
    fn = DESCRIBE.get(name)
    if not fn:
        return f"{name}({args})"
    try:
        return fn(args or {})
    except Exception:
        return f"{name}({args})"


def execute(name: str, args: dict, ctx: ToolContext) -> dict:
    """Run a tool and return a JSON-safe result dict."""
    handler = HANDLERS.get(name)
    if handler is None:
        return {"ok": False, "message": f"Unknown tool '{name}'."}
    try:
        result = handler(args or {}, ctx)
        if not isinstance(result, dict):
            result = {"ok": True, "message": str(result)}
        result.setdefault("ok", True)
        result.setdefault("message", "Done.")
        return result
    except Exception as exc:
        return {"ok": False, "message": f"Tool '{name}' crashed: {exc}"}


def result_for_llm(result: dict) -> str:
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        text = str(result)
    return text[:MAX_TOOL_RESULT_CHARS]
