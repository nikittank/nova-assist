"""Activity page — telemetry stat cards + Live Execution Audit Stream."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .. import icons, theme
from .widgets_common import HfwRow, ScrollArea, TagPill, style_scoped


class StatCard(QWidget):
    def __init__(self, label: str, icon_name: str):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, True)
        style_scoped(self, "ActivityStat",
                     f"background: {theme.PANEL_2}; border: 1px solid {theme.BORDER_2};"
                     "border-radius: 10px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)
        top = QHBoxLayout()
        cap = QLabel(label)
        theme.set_style(cap, f"color: {theme.MUTED}; font-size: 12px; border: none;")
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, theme.GHOST, 14))
        theme.set_style(ic, "border: none;")
        top.addWidget(cap)
        top.addStretch(1)
        top.addWidget(ic)
        bottom = QHBoxLayout()
        self.value = QLabel("—")
        theme.set_style(self.value, f"color: {theme.WHITE}; font-size: 19px; font-weight: 700; border: none;")
        self.badge = TagPill("—")
        theme.set_style(self.badge, 
            f"color: {theme.TEXT}; font-size: 11px; font-family: {theme.FONT_MONO};"
            f"background: #101116; border: 1px solid {theme.BORDER};"
            "border-radius: 4px; padding: 2px 6px;")
        bottom.addWidget(self.value)
        bottom.addStretch(1)
        bottom.addWidget(self.badge)
        lay.addLayout(top)
        lay.addLayout(bottom)

    def set(self, value: str, badge: str) -> None:
        self.value.setText(value)
        self.badge.setText(badge)


class ActivityPage(QWidget):
    store_changed = Signal()          # queued-safe refresh from any thread

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(0)

        head = QHBoxLayout()
        title = QLabel("Activity")
        theme.set_style(title, f"color: {theme.WHITE}; font-size: 20px; font-weight: 700;")
        head.addWidget(title)
        head.addStretch(1)
        refresh = QPushButton("  Refresh")
        refresh.setProperty("variant", "primary")
        refresh.setIcon(icons.icon("refresh", theme.BLACK, 14, 2))
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self.on_shown)
        clear = QPushButton("  Clear log")
        clear.setProperty("variant", "ghost")
        clear.setIcon(icons.icon("trash", theme.GHOST, 14))
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self._clear)
        head.addWidget(refresh)
        head.addWidget(clear)
        root.addLayout(head)

        root.addSpacing(16)
        cards_holder = QWidget()
        # Keep the telemetry cards in one compact horizontal row.  The old
        # wrapping layout allowed the cards' preferred height to absorb the
        # page, which produced the large empty panels seen on Activity.
        self.cards_grid = QGridLayout(cards_holder)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setHorizontalSpacing(12)
        self.cards_grid.setVerticalSpacing(12)
        self.card_total = StatCard("Total Operations", "activity")
        self.card_rate = StatCard("Success Rate", "check")
        self.card_tools = StatCard("Active Tools", "share")
        self.card_store = StatCard("Storage Mode", "database")
        for row, col, card in (
            (0, 0, self.card_total), (0, 1, self.card_rate),
            (0, 2, self.card_tools), (0, 3, self.card_store),
        ):
            card.setMinimumHeight(104)
            card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.cards_grid.addWidget(card, row, col)
        for col in range(4):
            self.cards_grid.setColumnStretch(col, 1)
        root.addWidget(cards_holder)

        root.addSpacing(16)
        panel = QWidget()
        style_scoped(panel, "ActivityLogPanel",
                     f"background: #0a0a0c; border: 1px solid {theme.BORDER};"
                     "border-radius: 12px;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        bar = QWidget()
        style_scoped(bar, "ActivityLogBar",
                     f"background: #0d0d0f; border-bottom: 1px solid {theme.BORDER};")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(16, 9, 16, 9)
        dot = QLabel()
        dot.setFixedSize(6, 6)
        theme.set_style(dot, f"background: {theme.EMERALD_500}; border-radius: 3px; border: none;")
        cap = QLabel("LIVE EXECUTION AUDIT STREAM")
        theme.set_style(cap, 
            f"color: {theme.MUTED}; font-size: 10px; font-weight: 700;"
            "letter-spacing: 1.2px; border: none;")
        self.sync_chip = TagPill("SYNCED")
        theme.set_style(self.sync_chip, 
            f"color: {theme.MUTED}; font-size: 11px; font-family: {theme.FONT_MONO};"
            f"background: #101116; border: 1px solid {theme.BORDER};"
            "border-radius: 4px; padding: 2px 8px;")
        bl.addWidget(dot)
        bl.addSpacing(8)
        bl.addWidget(cap)
        bl.addStretch(1)
        bl.addWidget(self.sync_chip)
        pl.addWidget(bar)

        self.scroll = ScrollArea()
        holder = QWidget()
        self.log_lay = QVBoxLayout(holder)
        self.log_lay.setContentsMargins(16, 14, 16, 14)
        self.log_lay.setSpacing(14)
        self.log_lay.addStretch(1)
        self.scroll.setWidget(holder)
        pl.addWidget(self.scroll, 1)
        root.addWidget(panel, 1)

        root.addSpacing(10)
        foot = QLabel("Every tool action, note and reminder is logged locally here.")
        theme.set_style(foot, f"color: {theme.GHOST}; font-size: 12px;")
        root.addWidget(foot)

        self.ctx.activity.add_listener(self._on_entry)
        self.store_changed.connect(self.on_shown)

        # one font everywhere: same typeface as the sidebar/technical UI
        theme.apply_unified_font(self)

    # ------------------------------------------------------------- view
    def _clear(self) -> None:
        self.ctx.activity.clear()
        self.on_shown()

    def _on_entry(self, _entry) -> None:
        self.store_changed.emit()

    def on_shown(self) -> None:
        stats = self.ctx.activity.stats()
        self.card_total.set(f"{stats['total']:,}",
                            f"+{stats['ok']} ok" if stats["total"] else "0")
        self.card_rate.set(f"{stats['success_rate']:.1f}%",
                           f"{stats['errors']} errors")
        self.card_tools.set(f"{stats['active_tools']} Nodes", "Online")
        self.card_store.set("JSON", "Local")
        for i in reversed(range(self.log_lay.count() - 1)):
            w = self.log_lay.itemAt(i).widget()
            if w:
                w.setParent(None)
                w.hide()
                w.deleteLater()
        for entry in reversed(self.ctx.activity.entries(120)):
            self.log_lay.insertWidget(self.log_lay.count() - 1, LogRow(entry))
        self.sync_chip.setText("SYNCED")


class LogRow(HfwRow):
    def __init__(self, entry: dict):
        super().__init__()
        theme.set_style(self, "LogRow { border-bottom: 1px solid #16171d; }")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 12)
        col.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        ts = QLabel(entry.get("ts", ""))
        theme.set_style(ts, f"color: {theme.GHOST}; font-family: {theme.FONT_MONO}; font-size: 11px; border: none;")
        ok = entry.get("status", "ok") == "ok"
        category = entry.get("category", "system")
        cat = ActivityTag(category, ok=ok)
        mark = QLabel("[ok]" if ok else "[err]")
        theme.set_style(mark, 
            f"color: {'#d4d4d8' if ok else theme.RED_TEXT}; font-family: {theme.FONT_MONO};"
            "font-weight: 600; font-size: 11px; border: none;")
        head.addWidget(ts)
        head.addWidget(cat)
        head.addWidget(mark)
        head.addStretch(1)
        col.addLayout(head)
        msg = QLabel(entry.get("message", ""))
        msg.setWordWrap(True)
        theme.set_style(msg, f"color: {theme.TEXT}; font-size: 13px; border: none;")
        col.addWidget(msg)
        if entry.get("detail"):
            det = QLabel(entry["detail"][:400])
            det.setWordWrap(True)
            det.setTextInteractionFlags(Qt.TextSelectableByMouse)
            theme.set_style(det, 
                f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
                "border: none;")
            col.addWidget(det)


class ActivityTag(QFrame):
    """Lucide-style category pill used consistently in the audit stream."""

    _ICON_BY_CATEGORY = {
        "tool": "zap",
        "note": "note",
        "reminder": "bell",
        "system": "settings",
        "user": "message",
        "ai": "sparkle",
        "file": "file",
    }
    _COLOR_BY_CATEGORY = {
        "tool": "#f59e0b",       # amber
        "note": "#22d3ee",       # cyan
        "reminder": "#34d399",   # emerald
        "system": "#94a3b8",     # slate
        "user": "#60a5fa",       # blue
        "ai": "#a78bfa",         # violet
        "file": "#38bdf8",       # sky
    }

    def __init__(self, category: str, ok: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("ActivityTag")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 7, 2)
        lay.setSpacing(4)
        icon_color = self._COLOR_BY_CATEGORY.get(
            category, theme.RED_TEXT if not ok else theme.GHOST)
        text = QLabel(category)
        theme.set_style(text,
                        f"color: {icon_color if ok else theme.RED_TEXT};"
                        f" font-size: 10px; font-family: {theme.FONT_MONO};"
                        " background: transparent; border: none;")
        lay.addWidget(text)
        theme.set_style(self,
                        f"background: #14161d; border: 1px solid {icon_color if ok else theme.RED_TEXT};"
                        " padding: 0px;"
                        " border-radius: 5px;")
