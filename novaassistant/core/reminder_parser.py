"""Natural-language reminder extraction.

Parses phrases like:
  "Remind me tomorrow at 6 PM to call John every Monday"
  "remind me at 6 pm to call john"
  "meeting in 20 minutes"
  "every Monday review my work"
  "remind me on Sep 15 at 09:00 to publish changelog"

Pure python (no deps) so it is fully unit-testable.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2,
    "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4,
    "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

REPEATS = {
    "every day": "daily", "everyday": "daily", "daily": "daily",
    "each day": "daily",
    "every weekday": "weekdays", "weekdays": "weekdays",
    "every week": "weekly", "weekly": "weekly",
    "every month": "monthly", "monthly": "monthly",
    "every year": "yearly", "yearly": "yearly", "annually": "yearly",
}


def parse_reminder(text: str, now: datetime | None = None) -> dict[str, Any]:
    """Extract {text, date, time, repeat, datetime, matched_span} from speech."""
    now = now or datetime.now()
    raw = " ".join((text or "").split()).strip()
    if not raw:
        return _empty(raw)

    working = raw
    # strip leading commands -------------------------------------------------
    working = re.sub(
        r"^(nova\s*,?\s*)?(please\s+)?(can you\s+|could you\s+)?"
        r"(set|create|add|make)?\s*(a\s+)?(new\s+)?reminder\s*(for|to|that)?\s*",
        "", working, flags=re.I)
    working = re.sub(r"^remind\s+(me\s+)?(to\s+|that\s+|about\s+|for\s+)?", "", working,
                     flags=re.I)
    working = re.sub(r"^(take|make)\s+a\s+(note\s+)?reminder\s*", "", working, flags=re.I)

    consumed: list[tuple[int, int]] = []  # spans removed from working

    def cut(pattern: str, flags: re.Pattern | int = re.I) -> str | None:
        nonlocal working
        m = re.search(pattern, working, flags)
        if m:
            consumed.append(m.span())
            working = (working[:m.start()] + " " + working[m.end():]).strip()
            return m.group(0)
        return None

    # relative "in N minutes/hours" ------------------------------------------
    rel = re.search(
        r"\bin\s+(\d+|a few|a|an|half an)\s*(minutes?|mins?|min|hours?|hrs?|hr|h)\b",
        working, flags=re.I)
    if rel:
        qty = rel.group(1).lower()
        unit = rel.group(2).lower()
        if qty in ("a", "an"):
            n = 1
        elif qty == "a few":
            n = 5
        elif "half" in qty:
            n = 0.5
        else:
            n = int(qty)
        delta = timedelta(minutes=n) if unit.startswith("m") or unit == "min" \
            else timedelta(hours=n)
        if unit in ("min", "mins", "minutes"):
            delta = timedelta(minutes=n)
        cut(re.escape(rel.group(0)))
        dt = now + delta
        return _result(raw, working, consumed, dt.date(), dt.time(), None)

    # repeat ------------------------------------------------------------------
    repeat = None
    rep_word = None
    # "every monday" / "every mon"
    rep = re.search(r"\bevery\s+(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)"
                    r"[a-z]*\b", working, flags=re.I)
    if rep:
        wd = WEEKDAYS.get(rep.group(1).lower())
        repeat = f"weekly:{wd}" if wd is not None else "weekly"
        rep_word = rep.group(0)
    if repeat is None:
        rep = re.search(r"\b(every\s+day|everyday|each\s+day|daily|every\s+weekday|"
                        r"weekdays|every\s+week|weekly|every\s+month|monthly|"
                        r"every\s+year|yearly|annually)\b", working, flags=re.I)
        if rep:
            phrase = re.sub(r"\s+", " ", rep.group(0).lower()).strip()
            repeat = REPEATS.get(phrase, REPEATS.get(phrase + " ", None))
            if repeat is None:
                for k, v in REPEATS.items():
                    if phrase in k or k in phrase:
                        repeat = v
                        break
            rep_word = rep.group(0)
    if repeat is None:
        rep = re.search(r"\bon\s+(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)"
                        r"[a-z]*s?\b", working, flags=re.I)
        if rep:
            wd = WEEKDAYS.get(rep.group(1).lower())
            if wd is not None:
                repeat = f"weekly:{wd}"
                rep_word = rep.group(0)
    if rep_word:
        cut(re.escape(rep_word))

    # date ---------------------------------------------------------------------
    date_val = None
    # explicit ISO
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", working)
    if m:
        try:
            date_val = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
            cut(re.escape(m.group(0)))
        except ValueError:
            pass
    if date_val is None:
        # month-name dates: "Sep 15", "september 15", "15 Sep", "15th September 2026"
        m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
                      r"[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?\b",
                      working, flags=re.I)
        if m:
            month = MONTHS[m.group(1).lower()]
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else _pick_year(now, month, day)
            try:
                date_val = datetime(year, month, day).date()
                cut(re.escape(m.group(0)))
            except ValueError:
                pass
    if date_val is None:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
                      r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
                      r"[a-z]*\.?(?:,?\s*(\d{4}))?\b", working, flags=re.I)
        if m:
            month = MONTHS[m.group(2).lower()]
            day = int(m.group(1))
            year = int(m.group(3)) if m.group(3) else _pick_year(now, month, day)
            try:
                date_val = datetime(year, month, day).date()
                cut(re.escape(m.group(0)))
            except ValueError:
                pass
    if date_val is None:
        # numeric m/d or d/m (assume m/d)
        m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", working)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = int(m.group(3)) if m.group(3) else now.year
            if year < 100:
                year += 2000
            try:
                date_val = datetime(year, month, day).date()
                cut(re.escape(m.group(0)))
            except ValueError:
                pass
    if date_val is None:
        m = re.search(r"\b(today|tonight|tomorrow|tmr|day after tomorrow)\b", working, flags=re.I)
        if m:
            word = m.group(1).lower()
            date_val = now.date()
            if word == "tomorrow" or word == "tmr":
                date_val = now.date() + timedelta(days=1)
            elif word == "day after tomorrow":
                date_val = now.date() + timedelta(days=2)
            cut(re.escape(m.group(0)))
    if date_val is None:
        # next <weekday> | <weekday> | next week
        m = re.search(r"\bnext\s+(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\b",
                      working, flags=re.I)
        if m:
            wd = WEEKDAYS[m.group(1).lower()]
            date_val = _next_weekday(now, wd, force_next=True)
            cut(re.escape(m.group(0)))
    if date_val is None:
        m = re.search(r"\b(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*day?\b",
                      working, flags=re.I)
        if m and m.group(0).lower() not in ("day",):
            wd = WEEKDAYS.get(m.group(1).lower())
            if wd is not None:
                date_val = _next_weekday(now, wd)
                cut(re.escape(m.group(0)))

    # time ---------------------------------------------------------------------
    time_val = None
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?(?:\.)?\b", working, flags=re.I)
    if m:
        time_val = _ampm(int(m.group(1)), int(m.group(2) or 0), m.group(3).lower())
        cut(re.escape(m.group(0)))
    if time_val is None:
        m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?(?:\.)?\b", working, flags=re.I)
        if m:
            time_val = _ampm(int(m.group(1)), int(m.group(2) or 0), m.group(3).lower())
            cut(re.escape(m.group(0)))
    if time_val is None:
        m = re.search(r"\bat\s+(\d{1,2}):(\d{2})\b", working, flags=re.I)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                time_val = datetime.now().replace(hour=hh, minute=mm, second=0, microsecond=0).time()
                cut(re.escape(m.group(0)))
    if time_val is None:
        m = re.search(r"\b(\d{1,2})\s*o'?clock\b", working, flags=re.I)
        if m:
            hh = int(m.group(1))
            time_val = _ampm(hh if hh <= 12 else hh - 12, 0,
                             "p" if hh >= 13 or hh <= 6 else "a")
            # heuristic: 7 o'clock in the morning => am
            cut(re.escape(m.group(0)))
    if time_val is None:
        m = re.search(r"\b(noon|midday)\b", working, flags=re.I)
        if m:
            time_val = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0).time()
            cut(re.escape(m.group(0)))
    if time_val is None:
        m = re.search(r"\bmidnight\b", working, flags=re.I)
        if m:
            time_val = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).time()
            cut(re.escape(m.group(0)))
    if time_val is None:
        m = re.search(r"\bin\s+the\s+(morning|afternoon|evening|night)\b", working, flags=re.I)
        if m:
            word = m.group(1).lower()
            hh = {"morning": 9, "afternoon": 15, "evening": 18, "night": 21}[word]
            time_val = datetime.now().replace(hour=hh, minute=0, second=0, microsecond=0).time()
            cut(re.escape(m.group(0)))

    # if time implies date and date unknown: 6pm already passed today -> tomorrow
    if time_val is not None and date_val is None:
        candidate = datetime.combine(now.date(), time_val)
        if candidate < now:
            date_val = (now + timedelta(days=1)).date()
        else:
            date_val = now.date()
    if time_val is None and date_val is not None:
        time_val = now.replace(second=0, microsecond=0).time()

    return _result(raw, working, consumed, date_val, time_val, repeat)


# ------------------------------------------------------------------ helpers
def _empty(raw: str) -> dict[str, Any]:
    return {"text": raw, "date": None, "time": None, "repeat": None,
            "datetime": None, "matched": False, "repeat_label": "None"}


def _result(raw, working, consumed, date_val, time_val, repeat) -> dict[str, Any]:
    content = working.strip(" ,.-;:")
    content = re.sub(r"\s{2,}", " ", content)
    content = re.sub(r"\bto\s+call\b", "call", content, flags=re.I)
    # drop dangling connectors
    content = re.sub(r"^(to|that|about|for)\s+", "", content, flags=re.I).strip()
    if not content:
        content = raw
    dt = None
    if date_val and time_val:
        dt = datetime.combine(date_val, time_val)
    return {
        "text": content,
        "date": date_val.isoformat() if date_val else None,
        "time": time_val.strftime("%H:%M") if time_val else None,
        "repeat": repeat,
        "repeat_label": repeat_label(repeat),
        "datetime": dt.isoformat(timespec="seconds") if dt else None,
        "matched": bool(date_val or time_val or repeat),
        "raw": raw,
    }


def repeat_label(repeat: str | None) -> str:
    if not repeat or repeat == "none":
        return "None"
    if repeat.startswith("weekly:"):
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                "Saturday", "Sunday"]
        try:
            return "Every " + days[int(repeat.split(":")[1])]
        except Exception:
            return "Weekly"
    return repeat.capitalize()


def _ampm(hh: int, mm: int, ap: str):
    hh = hh % 12 if hh % 12 != 0 else 12
    if ap == "p" and hh != 12:
        hour = hh + 12
    elif ap == "a" and hh == 12:
        hour = 0
    else:
        hour = hh
    return datetime.now().replace(hour=hour, minute=mm % 60, second=0, microsecond=0).time()


def _next_weekday(now: datetime, weekday: int, force_next: bool = False):
    days_ahead = (weekday - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7 if force_next else 0
    return (now + timedelta(days=days_ahead)).date()


def _pick_year(now: datetime, month: int, day: int) -> int:
    if month < now.month or (month == now.month and day < now.day):
        return now.year + 1
    return now.year
