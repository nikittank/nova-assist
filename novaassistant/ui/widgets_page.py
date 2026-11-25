"""Widgets page — management grid for the independent widget system.

The page is a clean, FIXED responsive grid of widget cards (FlowLayout —
cards wrap by width and align with no gaps). Cards are NOT freely
draggable here: drag/move applies only once a widget is pinned to the
desktop, where it becomes its own floating window. Each card offers:
edit/settings, pin-to-desktop toggle, pin-in-overlay toggle and remove,
plus a LIVE preview of the real widget.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .. import icons, theme
from .flowlayout import FlowLayout
from .widgets import WidgetBase
from .widgets_common import ScrollArea, style_scoped

CARD_W = 316
CARD_H = 340


class WidgetGridCard(QFrame):
    """One management card: header + live widget preview + action row."""

    def __init__(self, ctx, inst: dict, page: "WidgetsPage"):
        super().__init__()
        self.ctx = ctx
        self.inst = inst
        self.page = page
        self.setFixedSize(CARD_W, CARD_H)
        self.setObjectName("WidgetGridCard")
        theme.set_style(self,
                        f"QWidget#WidgetGridCard {{ background: {theme.GRID_BG};"
                        f" border: 1px solid {theme.WIDGET_BORDER};"
                        " border-radius: 12px; }")
        self._building = True

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        # ------------------------------------------------------------ header
        header = QWidget()
        header.setFixedHeight(34)
        theme.set_style(header, "background: transparent;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 0, 6, 0)
        hl.setSpacing(6)
        registry = ctx.widget_manager._registry()
        meta = registry.get(inst["type"], {})
        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap(meta.get("icon", "grid"),
                                        theme.MUTED, 13))
        theme.set_style(icon_lbl, "background: transparent; border: none;")
        title = QLabel(str(meta.get("label", inst["type"])))
        theme.set_style(title, 
            f"color: {theme.TEXT_BRIGHT}; font-size: 12px; font-weight: 600;"
            "background: transparent; border: none;")
        hl.addWidget(icon_lbl)
        hl.addWidget(title)
        hl.addStretch(1)
        self.badge = QLabel()
        theme.set_style(self.badge, 
            f"color: {theme.FAINT}; font-size: 9px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; background: transparent; border: none;")
        hl.addWidget(self.badge)
        root.addWidget(header)

        # ---------------------------------------------------- live preview
        holder = QWidget()
        theme.set_style(holder, "background: transparent;")
        body_lay = QVBoxLayout(holder)
        body_lay.setContentsMargins(8, 0, 8, 4)
        body_lay.setSpacing(0)
        preview_host = QWidget()
        theme.set_style(preview_host, "background: transparent;")
        pv_lay = QVBoxLayout(preview_host)
        pv_lay.setContentsMargins(0, 0, 0, 0)
        pv_lay.setSpacing(0)
        try:
            self.widget: WidgetBase | None = \
                ctx.widget_manager.build_widget(inst, parent=preview_host)
            if self.widget is not None:
                self.widget.drag_enabled = False
                self.widget.set_chrome_visible(False)
                self.widget.setFixedSize(CARD_W - 18, CARD_H - 96)
                pv_lay.addWidget(self.widget)
        except Exception:
            self.widget = None
            err = QLabel("Widget failed to load")
            theme.set_style(err, 
                f"color: {theme.RED_TEXT}; font-size: 11px; border: none;"
                "background: transparent;")
            pv_lay.addWidget(err)
        body_lay.addWidget(preview_host)
        root.addWidget(holder, 1)

        # ------------------------------------------------------------ actions
        actions = QWidget()
        actions.setFixedHeight(40)
        theme.set_style(actions, "background: transparent;")
        al = QHBoxLayout(actions)
        al.setContentsMargins(8, 0, 8, 6)
        al.setSpacing(6)

        def _act_btn(icon_name: str, tip: str, active: bool = False):
            b = QPushButton()
            b.setFixedSize(28, 28)
            b.setIconSize(QSize(13, 13))
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            color = theme.BLACK if active else theme.MUTED
            bg = ("rgba(16,185,129,0.16)" if active else "transparent")
            bd = ("rgba(16,185,129,0.45)" if active
                  else "1px solid #26262b")
            if not active:
                bd = f"1px solid {theme.BORDER_2}"
            b.setIcon(icons.icon(icon_name, theme.EMERALD if active
                                 else theme.MUTED, 13))
            theme.set_style(
                b,
                f"QPushButton {{ background: {bg}; border: {bd};"
                "border-radius: 7px; }"
                "QPushButton:hover { background: #1c1c22; }"
                f"QPushButton:checked {{ background: rgba(16,185,129,0.16);"
                f" border: 1px solid rgba(16,185,129,0.45); }}")
            return b

        self.btn_settings = _act_btn("settings", "Edit / configure widget")
        self.btn_settings.clicked.connect(self._open_settings)
        self.btn_desktop = _act_btn("pin", "Pin to desktop (floating widget)")
        self.btn_desktop.setCheckable(True)
        self.btn_desktop.toggled.connect(self._toggle_desktop)
        self.btn_overlay = _act_btn("overlay", "Pin inside the AI overlay")
        self.btn_overlay.setCheckable(True)
        self.btn_overlay.toggled.connect(self._toggle_overlay)
        self.btn_remove = _act_btn("trash", "Remove widget")
        self.btn_remove.clicked.connect(self._remove)
        al.addWidget(self.btn_settings)
        al.addStretch(1)
        al.addWidget(self.btn_desktop)
        al.addWidget(self.btn_overlay)
        al.addWidget(self.btn_remove)
        root.addWidget(actions)

        self._building = False
        self.sync_badge()

    # ------------------------------------------------------------ actions
    def sync_badge(self) -> None:
        on_desktop = self.inst.get("surface") == "desktop"
        in_overlay = bool(self.inst.get("pin_overlay"))
        if on_desktop and in_overlay:
            text = "DESKTOP + OVERLAY"
        elif on_desktop:
            text = "ON DESKTOP"
        elif in_overlay:
            text = "IN OVERLAY"
        else:
            text = "MANAGED"
        self.badge.setText(text)
        if self._building:
            return
        self.btn_desktop.blockSignals(True)
        self.btn_desktop.setChecked(on_desktop)
        self.btn_desktop.blockSignals(False)
        self.btn_overlay.blockSignals(True)
        self.btn_overlay.setChecked(in_overlay)
        self.btn_overlay.blockSignals(False)

    def refresh(self) -> None:
        if self.widget is not None:
            try:
                self.widget.refresh()
            except Exception:
                pass

    def shutdown(self) -> None:
        if self.widget is not None:
            try:
                self.widget.shutdown()
            except Exception:
                pass

    def _open_settings(self) -> None:
        if self.widget is not None:
            self.widget._on_edit_clicked()

    def _toggle_desktop(self, on: bool) -> None:
        mgr = self.ctx.widget_manager
        if on:
            mgr.pin_to_desktop(self.inst["id"])
        else:
            mgr.unpin_from_desktop(self.inst["id"])
        self.page.status_message.emit(
            ("Pinned to desktop — " if on else "Unpinned from desktop — ")
            + str(self.inst["type"]))

    def _toggle_overlay(self, on: bool) -> None:
        self.ctx.widget_manager.set_pin_overlay(self.inst["id"], on)

    def _remove(self) -> None:
        self.ctx.widget_manager.remove(self.inst["id"])


class WidgetsPage(QWidget):
    request_llm = Signal(str)          # kept for wiring compatibility
    status_message = Signal(str)
    pin_requested = Signal()           # kept for wiring compatibility

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.manager = ctx.widget_manager
        self._cards: list[WidgetGridCard] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------------------------------------------------------- header
        header = QWidget()
        header.setObjectName("WidgetsHeader")
        theme.set_style(header,
                        "QWidget#WidgetsHeader { border-bottom: 1px solid "
                        f"{theme.BORDER}; }}")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(32, 22, 32, 20)
        hl.setSpacing(8)
        tcol = QVBoxLayout()
        trow = QHBoxLayout()
        t = QLabel("Widgets")
        theme.set_style(t,
                        f"color: {theme.WHITE}; font-size: 20px; font-weight: 600;"
                        "background: transparent; border: none;")
        trow.addWidget(t)
        trow.addStretch(1)
        tcol.addLayout(trow)
        sub = QLabel("Independent desktop tiles — pin them one by one, drag and "
                     "resize on the desktop, restore on restart")
        theme.set_style(sub,
                        f"color: {theme.MUTED}; font-size: 12px;"
                        f"font-family: {theme.FONT_MONO};"
                        "background: transparent; border: none;")
        tcol.addWidget(sub)
        hl.addLayout(tcol)
        hl.addStretch(1)

        add_w = QPushButton("  Add Widget")
        add_w.setProperty("variant", "primary")
        add_w.setIcon(icons.icon("plus", theme.BLACK, 13, 2))
        add_w.setCursor(Qt.PointingHandCursor)
        add_w.clicked.connect(self._show_add_menu)
        self.add_btn = add_w

        reset_btn = QPushButton("  Reset layout")
        reset_btn.setProperty("variant", "ghost")
        reset_btn.setIcon(icons.icon("refresh", theme.MUTED, 13))
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_layout)

        hl.addWidget(add_w)
        hl.addWidget(reset_btn)
        root.addWidget(header)

        # ------------------------------------------------------------ grid
        self.scroll = ScrollArea()
        self.grid_holder = QWidget()
        theme.set_style(self.grid_holder, "background: #000000;")
        self.flow = FlowLayout(self.grid_holder, margin=24, spacing=28)
        self.scroll.setWidget(self.grid_holder)
        root.addWidget(self.scroll, 1)

        self.empty_lbl = QLabel(
            "No widgets yet.\nAdd one with the button above — Clock, Date, "
            "Focus, Quick Notes, Reminders, AI Status and more.")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        theme.set_style(
            self.empty_lbl,
            f"color: {theme.GHOST}; font-size: 12px;"
            f"border: 1px dashed {theme.BORDER_2};"
            "border-radius: 12px; padding: 28px; background: transparent;")

        footer = QLabel(
            "Pin a widget to make it a floating desktop tile   •   drag & resize "
            "only on the desktop   •   positions are restored after restart")
        footer.setContentsMargins(32, 0, 32, 12)
        theme.set_style(footer,
                        f"color: {theme.GHOST}; font-size: 11px;"
                        "background: transparent; border: none;")
        root.addWidget(footer)

        self.manager.changed.connect(self.rebuild)
        self.manager.data_changed.connect(self._refresh_cards)
        self.rebuild()

    # ------------------------------------------------------------- actions
    def _show_add_menu(self) -> None:
        menu = QMenu(self)
        for key, label, icon_name in self.manager.catalog():
            act = menu.addAction(icons.icon(icon_name, theme.MUTED, 14), label)
            act.triggered.connect(lambda _=False, k=key: self._add(k))
        menu.addSeparator()
        hint = menu.addAction("Layout is saved automatically")
        hint.setEnabled(False)
        menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

    def _add(self, wtype: str) -> None:
        inst = self.manager.create(wtype, "page")
        self.status_message.emit(f"Added {inst['type']} widget")

    def _reset_layout(self) -> None:
        self.manager.reset_layout()
        self.status_message.emit("Widget layout reset to defaults")

    def rebuild(self) -> None:
        for card in self._cards:
            card.shutdown()
            card.setParent(None)
            card.hide()
            card.deleteLater()
        self._cards = []

        instances = [i for i in self.manager.instances
                     if i.get("surface") == "page"]
        for inst in instances:
            try:
                card = WidgetGridCard(self.ctx, inst, self)
            except Exception:
                continue
            self.flow.addWidget(card)
            self._cards.append(card)

        has_widgets = bool(self._cards)
        if not has_widgets:
            self.flow.addWidget(self.empty_lbl)
        self.grid_holder.setMinimumSize(360, 240)
        self.grid_holder.adjustSize()

    def _refresh_cards(self) -> None:
        for card in self._cards:
            card.refresh()

    def on_shown(self) -> None:
        self.manager.changed.emit()   # re-sync if desktop/overlay moved widgets
        self.manager.data_changed.emit()
