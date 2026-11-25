"""Reminder scheduler + natural-language time parsing.

Reminders are stored in SQLite with a naive local ISO timestamp
(``YYYY-MM-DD HH:MM:SS``) plus a recurrence rule:

    none | daily | weekly | weekdays | monthly

A daemon thread wakes every ~10 seconds, fires anything due (system
notification + spoken announcement + activity log) and reschedules
recurring rules.

``parse_reminder_phrase`` extracts {message, date, time, recurrence} from a
spoken sentence such as::

    "Remind me tomorrow at 6 PM to call John every Monday."

It is used by the Reminders page microphone button (instant offline
extraction) and as a fallback when the LLM is unavailable.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

RECURRENCES = ("none", "daily", "weekly", "weekdays", "monthly")
TICK_SECONDS = 10

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}


# --------------------------------------------------------------------------
# natural-language reminder parsing
# --------------------------------------------------------------------------

_TIME_RE = re.compile(
    r"\bat\s+(?P<h>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?\b",
    re.IGNORECASE)
_IN_RE = re.compile(r"\bin\s+(?P<n>\d+)\s*(?P<unit>min(?:ute)?s?|hours?|hrs?|h)\b",
                    re.IGNORECASE)
_TOMORROW_RE = re.compile(r"\btomorrow\b|\btmrw?\b", re.IGNORECASE)
_TONIGHT_RE = re.compile(r"\btonight\b", re.IGNORECASE)
_TODAY_RE = re.compile(r"\btoday\b", re.IGNORECASE)
_EVERY_RE = re.compile(
    r"\bevery\s+(?:(?P<wd>monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thu|"
    r"friday|fri|saturday|sat|sunday|sun)\b|(?P<kind>day|weekday|workday|week|month)\b)",
    re.IGNORECASE)
_ON_WD_RE = re.compile(
    r"\bon\s+(?P<wd>monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thu|"
    r"friday|fri|saturday|sat|sunday|sun)\b", re.IGNORECASE)
_LEAD_RE = re.compile(
    r"^(?:hey\s+nova[, ]*|nova[, ]*)?(?:please\s+)?"
    r"(?:remind(?:er)?\s+(?:me\s+)?(?:to\s+|that\s+|about\s+|for\s+)?"
    r"|take\s+a\s+reminder\s*(?:to\s+|that\s+|about\s+|for\s+)?"
    r"|set\s+(?:up\s+)?a\s+reminder\s*(?:to\s+|that\s+|about\s+|for\s+)?"
    r"|add\s+a\s+reminder\s*(?:to\s+|that\s+|about\s+|for\s+)?"
    r"|new\s+reminder\s*[:]?)", re.IGNORECASE)
_EVERY_TAIL_RE = re.compile(
    r"[, ]*\bevery\s+(?:monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thu|"
    r"friday|fri|saturday|sat|sunday|sun|day|weekday|workday|week|month)\b[. ]*$",
    re.IGNORECASE)


def _apply_time(base: datetime, h: int, minute: int, ampm: str) -> datetime:
    if ampm:
        ampm = ampm.replace(".", "").lower()
        if ampm.startswith("p") and h < 12:
            h += 12
        elif ampm.startswith("a") and h == 12:
            h = 0
    h = min(h, 23)
    return base.replace(hour=h, minute=minute, second=0, microsecond=0)


def _next_weekday(base: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - base.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return base + timedelta(days=days_ahead)


def parse_reminder_phrase(text: str, now: Optional[datetime] = None) -> dict:
    """Extract reminder fields from natural language.

    Returns {"message", "when" (ISO str), "recurrence", "date", "time",
    "recurring"} - "when" is "" when no explicit time was understood.
    """
    now = now or datetime.now()
    raw = (text or "").strip()
    if not raw:
        return {"message": "", "when": "", "recurrence": "none",
                "date": "", "time": "", "recurring": False}

    body = raw
    m = _LEAD_RE.match(body)
    if m:
        body = body[m.end():]

    recurrence = "none"
    wd_match = _EVERY_RE.search(body) or _ON_WD_RE.search(body)
    target_day: Optional[int] = None
    recurring_by_phrase = False

    if wd_match:
        if wd_match.group("wd"):
            wd = wd_match.group("wd").lower()
            target_day = WEEKDAYS.get(wd)
            # "every monday" -> weekly recurrence; "on monday" -> just a day
            recurring_by_phrase = bool(_EVERY_RE.search(body))
            recurrence = "weekly" if recurring_by_phrase else "none"
        else:
            kind = wd_match.group("kind").lower()
            recurrence = {"day": "daily", "week": "weekly",
                          "month": "monthly",
                          "weekday": "weekdays", "workday": "weekdays"}[kind]
            recurring_by_phrase = True
        # strip a trailing "every ..." clause from the message body
        body = _EVERY_TAIL_RE.sub("", body)
        body = _EVERY_RE.sub("", body)
        body = _ON_WD_RE.sub("", body)

    # relative "in 20 minutes"
    m = _IN_RE.search(body)
    when = now
    day_resolved = False
    time_resolved = False
    if m:
        n = int(m.group("n"))
        unit = m.group("unit").lower()
        delta = timedelta(minutes=n) if unit.startswith("min") else \
            timedelta(hours=n) if unit.startswith(("h", "hour")) else timedelta(minutes=n)
        when = now + delta
        day_resolved = time_resolved = True
        body = _IN_RE.sub("", body)

    # explicit clock time
    m = _TIME_RE.search(body)
    explicit_time = None
    if m:
        h = int(m.group("h"))
        minute = int(m.group("min") or 0)
        ampm = m.group("ampm") or ""
        explicit_time = (h, minute, ampm)
        body = _TIME_RE.sub("", body)

    # day resolution
    day_desc = ""
    tonight = bool(_TONIGHT_RE.search(body))
    if _TOMORROW_RE.search(body):
        when = now + timedelta(days=1)
        day_desc = "tomorrow"
        day_resolved = True
        body = _TOMORROW_RE.sub("", body)
    elif tonight:
        when = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if when <= now:
            when = now + timedelta(days=1)
            day_desc = "tomorrow night"
        else:
            day_desc = "tonight"
        day_resolved = True
        body = _TONIGHT_RE.sub("", body)
    elif target_day is not None:
        when = _next_weekday(now, target_day)
        day_resolved = True
    elif _TODAY_RE.search(body):
        day_resolved = True
        body = _TODAY_RE.sub("", body)
    elif recurrence == "daily" and not day_resolved:
        when = now + timedelta(days=1) if now.hour >= 23 else now
        day_resolved = True

    if explicit_time:
        h, minute, ampm = explicit_time
        when = _apply_time(when, h, minute, ampm)
        time_resolved = True
        if ampm:
            ampm_clean = ampm.replace(".", "").upper()
            ampm_clean = "AM" if ampm_clean.startswith("A") else "PM"
            hour12 = h % 12 or 12
            time_desc = f"{hour12}:{minute:02d} {ampm_clean}"
        else:
            time_desc = f"{h}:{minute:02d}"
    elif tonight:
        when = when.replace(hour=20, minute=0, second=0, microsecond=0)
        time_resolved = True
    elif recurrence == "daily":
        when = when.replace(hour=9, minute=0, second=0, microsecond=0) \
            if when.hour == 0 and when.minute == 0 else when
        time_resolved = True
    elif not time_resolved:
        when = when.replace(hour=9, minute=0, second=0, microsecond=0)
        if when <= now and not day_resolved:
            when = when + timedelta(days=1)
        time_resolved = True

    # "at 6" with no am/pm: if 06:00 is already past but 18:00 is not,
    # the speaker almost certainly meant the afternoon/evening slot
    if explicit_time and not explicit_time[2] and when <= now:
        h = explicit_time[0]
        if h < 12:
            alt = _apply_time(when.replace(hour=0), h, explicit_time[1], "pm")
            if alt > now and alt.date() == when.date():
                when = alt

    # if a weekday was given with "every", the first occurrence must be future
    if recurrence == "weekly" and target_day is not None and when.weekday() != target_day:
        when = _next_weekday(when, target_day)
    if when <= now and recurrence != "none":
        # push recurring reminders into the future
        nxt = when
        for _ in range(32):
            nxt = next_occurrence(nxt, recurrence)
            if nxt is None:
                break
            when = nxt
            if when > now:
                break
    elif when <= now:
        when = when + timedelta(days=1)

    message = re.sub(r"\s{2,}", " ", body).strip(" ,.")
    message = re.sub(r"^(?:to|that|about|for)\s+", "", message,
                     flags=re.IGNORECASE).strip(" ,.")
    if not message:
        message = raw.strip(" ,.")

    # describe the resolved day from the FINAL scheduled moment
    if recurrence == "weekly" and target_day is not None:
        day_desc = ["monday", "tuesday", "wednesday", "thursday", "friday",
                    "saturday", "sunday"][when.weekday()]
    elif not day_desc and when.date() == now.date():
        day_desc = "today"
    elif not day_desc and when.date() == (now + timedelta(days=1)).date():
        day_desc = "tomorrow"
    elif not day_desc:
        day_desc = when.strftime("%Y-%m-%d")

    return {
        "message": message,
        "when": when.replace(microsecond=0).isoformat(sep=" "),
        "recurrence": recurrence,
        "date": day_desc,
        "time": when.strftime("%H:%M"),
        "recurring": recurrence != "none",
    }


# --------------------------------------------------------------------------
# scheduling service
# --------------------------------------------------------------------------

def parse_when(value: str) -> Optional[datetime]:
    """Parse the ISO datetimes produced by the LLM (naive local preferred)."""
    if not value:
        return None
    raw = str(value).strip().replace("T", " ")
    if raw.endswith("Z"):
        raw = raw[:-1]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M", "%Y/%m/%d", "%m/%d/%Y %H:%M", "%m/%d/%Y",
                "%d-%m-%Y %H:%M", "%H:%M"):
        try:
            dt = datetime.strptime(raw, fmt)
            if fmt == "%H:%M":  # time-only -> today (or tomorrow if past)
                now = datetime.now()
                dt = now.replace(hour=dt.hour, minute=dt.minute, second=0, microsecond=0)
                if dt <= now:
                    dt += timedelta(days=1)
            return dt
        except ValueError:
            continue
    try:  # last resort: full ISO with offset
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def next_occurrence(dt: datetime, recurrence: str) -> Optional[datetime]:
    if recurrence == "daily":
        return dt + timedelta(days=1)
    if recurrence == "weekly":
        return dt + timedelta(days=7)
    if recurrence == "weekdays":
        nxt = dt + timedelta(days=1)
        while nxt.weekday() >= 5:  # 5=Sat, 6=Sun
            nxt += timedelta(days=1)
        return nxt
    if recurrence == "monthly":
        month = dt.month + 1 if dt.month < 12 else 1
        year = dt.year + (1 if dt.month == 12 else 0)
        day = min(dt.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                           else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        return dt.replace(year=year, month=month, day=day)
    return None


class ReminderService:
    def __init__(self, db, on_fire: Callable[[dict], None],
                 on_error: Optional[Callable[[str], None]] = None) -> None:
        self._db = db
        self._on_fire = on_fire
        self._on_error = on_error
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    # ------------------------------------------------------------------ api
    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop_evt.clear()
            self._thread = threading.Thread(target=self._loop, name="nova-reminders",
                                            daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()

    def add(self, message: str, when: str, recurrence: str = "none",
            note_id: Optional[int] = None) -> dict:
        """Validate + create a reminder. Returns {ok, message, id?}."""
        dt = parse_when(when)
        if dt is None:
            return {"ok": False,
                    "message": f"Could not understand the time '{when}'. "
                               f"Use ISO like 2026-09-09T18:00:00."}
        rec = (recurrence or "none").strip().lower()
        if rec not in RECURRENCES:
            rec = "none"
        if dt <= datetime.now():
            nxt = next_occurrence(dt, rec)
            if rec == "none" or nxt is None or nxt <= datetime.now():
                return {"ok": False,
                        "message": f"That time ({dt.strftime('%Y-%m-%d %H:%M')}) is in the past."}
            dt = nxt
        row = self._db.add_reminder(message, dt.replace(microsecond=0).isoformat(sep=" "),
                                    rec, note_id)
        return {"ok": True,
                "message": f"Reminder set for {dt.strftime('%a %d %b %Y at %H:%M')}"
                           + (f", repeating {rec}" if rec != "none" else "") + ".",
                "id": row["id"], "next": dt.replace(microsecond=0).isoformat(sep=" ")}

    def update(self, reminder_id: int, message: Optional[str] = None,
               when: Optional[str] = None, recurrence: Optional[str] = None) -> dict:
        """Edit an existing reminder in place."""
        rem = self._db.get_reminder(reminder_id)
        if rem is None:
            return {"ok": False, "message": f"No reminder with id {reminder_id}."}
        rec = (recurrence if recurrence is not None else rem["recurrence"]) or "none"
        rec = rec.strip().lower()
        if rec not in RECURRENCES:
            rec = "none"
        if when is not None:
            dt = parse_when(when)
            if dt is None:
                return {"ok": False, "message": f"Could not understand the time '{when}'."}
            if dt <= datetime.now():
                nxt = next_occurrence(dt, rec)
                if rec == "none" or nxt is None or nxt <= datetime.now():
                    return {"ok": False,
                            "message": f"That time ({dt.strftime('%Y-%m-%d %H:%M')}) is in the past."}
                dt = nxt
            trigger = dt.replace(microsecond=0).isoformat(sep=" ")
        else:
            trigger = rem["next_trigger"]
        self._db.update_reminder(reminder_id,
                                 message=message.strip() if message is not None else None,
                                 next_trigger=trigger, recurrence=rec)
        # editing an overdue/finished reminder re-activates it
        if not rem["active"]:
            self._db.set_reminder_active(reminder_id, True)
        return {"ok": True, "message": f"Reminder #{reminder_id} updated."}

    def complete(self, reminder_id: int) -> dict:
        rem = self._db.get_reminder(reminder_id)
        if rem is None:
            return {"ok": False, "message": f"No reminder with id {reminder_id}."}
        self._db.set_reminder_active(reminder_id, False)
        self._db.log_activity("reminder", f"Completed: {rem['message'][:80]}")
        return {"ok": True, "message": f"Reminder '{rem['message'][:50]}' completed."}

    def snooze(self, reminder_id: int, minutes: int = 10) -> dict:
        rem = self._db.get_reminder(reminder_id)
        if rem is None:
            return {"ok": False, "message": f"No reminder with id {reminder_id}."}
        base = parse_when(rem["next_trigger"]) or datetime.now()
        if base <= datetime.now():
            base = datetime.now()
        new_t = (base + timedelta(minutes=max(1, int(minutes))))
        self._db.update_reminder(reminder_id, next_trigger=new_t.replace(
            microsecond=0).isoformat(sep=" "))
        self._db.set_reminder_active(reminder_id, True)
        return {"ok": True,
                "message": f"Snoozed until {new_t.strftime('%H:%M')}."}

    # ------------------------------------------------------------- internals
    def _loop(self) -> None:
        while not self._stop_evt.wait(TICK_SECONDS):
            try:
                self._tick()
            except Exception as exc:  # never let the scheduler die
                if self._on_error:
                    try:
                        self._on_error(f"Reminder scheduler error: {exc}")
                    except Exception:
                        pass

    def _tick(self) -> None:
        now_key = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        for rem in self._db.due_reminders(now_key):
            self._db.set_reminder_trigger(rem["id"], None, active=False)
            rec = (rem.get("recurrence") or "none").lower()
            nxt = next_occurrence(parse_when(rem["next_trigger"]) or datetime.now(), rec)
            if rec != "none" and nxt is not None:
                # fast-forward past misses (e.g. laptop asleep)
                while nxt <= datetime.now():
                    later = next_occurrence(nxt, rec)
                    if later is None:
                        break
                    nxt = later
                self._db.set_reminder_trigger(rem["id"],
                                              nxt.replace(microsecond=0).isoformat(sep=" "),
                                              active=True)
            payload = dict(rem)
            payload["fired_at"] = now_key
            try:
                self._on_fire(payload)
            except Exception:
                pass
