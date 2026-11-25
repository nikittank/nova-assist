"""Independent Nova widgets — registry of all widget types.

Each widget is a small, self-contained card that can be added, removed,
moved, resized, collapsed, configured and pinned (page / desktop / overlay)
individually. See manager.py for lifecycle + persistence.
"""
from __future__ import annotations

from .activity_w import ActivityWidget
from .ai_status import AIStatusWidget
from .base import WidgetBase
from .clock import ClockWidget
from .date_w import DateWidget
from .focus import FocusWidget
from .quick_notes import QuickNotesWidget
from .reminders_w import RemindersWidget
from .today import WhatsTodayWidget

REGISTRY: dict[str, dict] = {
    "clock": {"label": "Clock / Time", "icon": "clock", "cls": ClockWidget},
    "date": {"label": "Date", "icon": "calendar", "cls": DateWidget},
    "whats_today": {"label": "What's Today", "icon": "sun", "cls": WhatsTodayWidget},
    "focus": {"label": "Focus", "icon": "focus", "cls": FocusWidget},
    "quick_notes": {"label": "Quick Notes", "icon": "note", "cls": QuickNotesWidget},
    "reminders": {"label": "Reminders", "icon": "bell", "cls": RemindersWidget},
    "ai_status": {"label": "AI Status", "icon": "cpu", "cls": AIStatusWidget},
    "activity": {"label": "Activity", "icon": "activity", "cls": ActivityWidget},
}

__all__ = [
    "REGISTRY", "WidgetBase", "ClockWidget", "DateWidget", "WhatsTodayWidget",
    "FocusWidget", "QuickNotesWidget", "RemindersWidget", "AIStatusWidget",
    "ActivityWidget",
]
