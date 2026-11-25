"""The agent: conversation loop between the user, gpt-oss-120b and tools.

One call to ``handle_user_text`` runs a full ReAct-style turn:

    user text -> LLM stream -> (tool calls -> confirmation -> execution)*
              -> final answer

The agent runs inside the controller's worker thread.  All UI feedback goes
through the ``emit`` callback; confirmations block on a callback provided by
the controller (which round-trips to a modal dialog on the GUI thread).
"""

from __future__ import annotations

import json
import platform
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import tools as toolset
from .llm import GroqBrain, LLMError

MAX_TOOL_ROUNDS = 6


class Agent:
    def __init__(self, config, db, brain: GroqBrain,
                 emit: Callable[..., None],
                 confirm: Callable[[str, dict, str], bool]) -> None:
        self.config = config
        self.db = db
        self.brain = brain
        self.emit = emit
        self.confirm = confirm          # (tool_name, args, description) -> approved
        self.tool_ctx = toolset.ToolContext(db, config)
        self.history: list[dict] = []
        self.cancel_event = threading.Event()
        self._load_history()

    # ---------------------------------------------------------------- memory
    def _load_history(self) -> None:
        self.history = []
        for m in self.db.recent_messages(limit=40):
            role = m["role"]
            if role in ("user", "assistant") and m["content"]:
                self.history.append({"role": role, "content": m["content"]})

    def reset_memory(self) -> None:
        self.history = []
        self.db.clear_messages()

    def _trimmed_history(self) -> list[dict]:
        """Keep the most recent window without splitting tool-call groups."""
        limit = max(6, int(self.config.get("context_messages", 24)))
        if len(self.history) <= limit:
            return list(self.history)
        cut = len(self.history) - limit
        while cut < len(self.history) and self.history[cut].get("role") != "user":
            cut += 1
        return list(self.history[cut:])

    # ----------------------------------------------------------- system text
    def _system_prompt(self) -> str:
        now = datetime.now().astimezone()
        os_name = platform.system()
        home = str(Path.home())
        paths = [name for name in ("Desktop", "Documents", "Downloads", "Pictures")
                 if (Path.home() / name).exists()]
        level = self.config.get("confirmation_level", "relaxed")
        return (
            "You are Nova, a warm, sharp personal AI assistant running as a native "
            f"desktop app on the user's {os_name} laptop. You act like a personal "
            "computer operator: understand what the user wants, do it with tools, "
            "and briefly report what you did.\n\n"
        f"Current date/time: {now.strftime('%A, %Y-%m-%d %I:%M %p')} "
            f"(timezone {now.strftime('%Z%z')}).\n"
            f"User home folder: {home}.\n"
            f"Standard folders available: {', '.join(paths) if paths else 'unknown'}.\n"
            f"Confirmation policy: {level}.\n\n"
            "Tool rules:\n"
            "- When the user asks you to DO something on the computer, call the "
            "matching tool instead of giving instructions.\n"
            "- For 'remind me ...' compute the ISO 8601 LOCAL datetime from the "
            "current time above and call set_reminder. Recurring phrasing maps to: "
            "every day -> daily, every <weekday> -> weekly, every weekday/workday -> "
            "weekdays, every month -> monthly.\n"
            "- For 'take a note ...' call take_note with a short topic tag.\n"
            "- NOTES - creating vs editing: take_note CREATES a new note; to change, "
            "extend, rewrite or correct an EXISTING note you MUST use update_note: "
            "first search_notes to find it (or use a known note_id), then call "
            "update_note with that id and the complete new content. update_note "
            "edits in place and NEVER creates a duplicate. Keep the note's existing "
            "topic (e.g. 'bucket') unless the user explicitly asks to change it.\n"
            "- Reminders can be attached to notes with set_note_reminder; rescheduled "
            "or reworded with update_reminder; finished with complete_reminder; "
            "delayed with snooze_reminder; removed with delete_reminder or "
            "remove_note_reminder.\n"
            "- Before answering questions about files/code/errors, read the actual "
            "content with read_file (or the attached context) - never guess.\n"
            "- You may chain several tools in one turn when that is clearly needed "
            "(e.g. search then read, or search_notes then update_note).\n"
            "- Some tools may pop a confirmation dialog for the user; if the user "
            "denies, apologize briefly and do not retry.\n"
            "- After actions, confirm in one short sentence what happened; if a tool "
            "failed, say so plainly and suggest a fix.\n\n"
            "Style: your replies are SPOKEN aloud via text-to-speech and also shown "
            "in chat. Keep them natural and concise (usually 1-4 sentences). "
            "Never use markdown, bullet points, emojis, or code formatting unless "
            "the user explicitly asks to see code. Plain flowing sentences only."
        )

    # ------------------------------------------------------------- main turn
    def handle_user_text(self, text: str, attachment: Optional[dict] = None) -> None:
        """Process one user turn (blocking; call from a worker thread)."""
        self.cancel_event = threading.Event()
        self._done_emitted = False

        display_text = text
        if attachment:
            display_text = (f"[Attached file: {attachment['name']}]\n\n{text}")
        self.history.append({"role": "user", "content": display_text})
        self.db.add_message("user", display_text)
        self.emit("user_message", text=text, attachment=attachment)

        messages = [{"role": "system", "content": self._system_prompt()}]
        messages += self._trimmed_history()

        try:
            final_text = self._loop(messages)
        except LLMError as exc:
            self.emit("error", message=str(exc))
            self.emit("assistant_done", text=f"Sorry, I hit an API problem: {exc}")
            return
        except Exception as exc:  # unexpected - keep the app alive
            self.emit("error", message=f"Unexpected error: {exc}")
            self.emit("assistant_done", text="Something went wrong while handling that.")
            return

        if final_text:
            self.history.append({"role": "assistant", "content": final_text})
            self.db.add_message("assistant", final_text)
        if not self._done_emitted:
            self.emit("assistant_done", text=final_text or "Done.")

    def _loop(self, messages: list[dict]) -> str:
        for _round in range(MAX_TOOL_ROUNDS):
            if self.cancel_event.is_set():
                self._done_emitted = True
                self.emit("assistant_done", text="Stopped.")
                return ""

            content_parts: list[str] = []
            pending_calls: list[dict] = []
            self.emit("thinking", active=True)

            for ev in self.brain.stream_chat(messages, toolset.TOOLS, self.cancel_event):
                if ev["type"] == "delta":
                    content_parts.append(ev["text"])
                    self.emit("assistant_delta", text=ev["text"])
                elif ev["type"] == "tool_calls":
                    pending_calls = ev["calls"]
                elif ev["type"] == "cancelled":
                    self._done_emitted = True
                    self.emit("assistant_done", text="Stopped.")
                    return ""
                elif ev["type"] == "done":
                    pass

            self.emit("thinking", active=False)
            content = "".join(content_parts)

            if pending_calls:
                messages.append({"role": "assistant", "content": content or None,
                                 "tool_calls": [
                                     {"id": c["id"], "type": "function",
                                      "function": {"name": c["name"],
                                                   "arguments": c["arguments"]}}
                                     for c in pending_calls]})
                for call in pending_calls:
                    if self.cancel_event.is_set():
                        self._done_emitted = True
                        self.emit("assistant_done", text="Stopped.")
                        return ""
                    self._execute_call(messages, call)
                continue  # let the LLM speak about the tool results

            return content.strip()

        self.emit("error", message="Too many tool rounds; stopping for safety.")
        return ("I stopped after several tool steps to stay safe. "
                "Ask me to continue if needed.")

    # ------------------------------------------------------------ tool exec
    def _execute_call(self, messages: list[dict], call: dict) -> None:
        name, args_raw = call["name"], call.get("arguments", "{}")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}

        self.emit("tool_call", name=name, args=args)
        level = self.config.get("confirmation_level", "relaxed")

        approved = True
        if toolset.needs_confirmation(name, level):
            description = toolset.describe(name, args)
            approved = self.confirm(name, args, description)

        if not approved:
            result = {"ok": False,
                      "message": "The user DENIED this action in the confirmation dialog."}
            self.db.log_activity("tool", f"{name} denied by user", status="denied")
        else:
            result = toolset.execute(name, args, self.tool_ctx)
            self.db.log_activity("tool", f"{name}: {result.get('message', '')[:200]}",
                                 status="ok" if result.get("ok") else "error")

        summary = result.get("message", "")
        self.emit("tool_result", name=name, summary=summary, ok=result.get("ok", False))
        messages.append({"role": "tool", "tool_call_id": call["id"],
                         "content": toolset.result_for_llm(result)})

    # -------------------------------------------------------------- controls
    def cancel(self) -> None:
        self.cancel_event.set()
