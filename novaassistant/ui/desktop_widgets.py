"""Pinned desktop widgets — INDIVIDUAL floating windows.

Every widget pinned to the desktop becomes its own small frameless window —
there is NO shared board, panel or background behind them. Pin Clock and
only the Clock floats on the desktop; pin Reminders and only Reminders
appears next to it.

DesktopWidgetsController keeps the set of PinnedWidgetWindow objects in
sync with WidgetManager state (create / close / refresh), persists each
window's position + size across restarts and offers master show/hide.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from .widgets import WidgetBase

IS_WINDOWS = sys.platform == "win32"


class PinnedWidgetWindow(QWidget):
    """One widget = one floating always-on-top desktop window."""

    def __init__(self, ctx, inst: dict, controller: "DesktopWidgetsController"):
        super().__init__(None)
        self.ctx = ctx
        self.inst = inst
        self.controller = controller
        self.widget_id = inst["id"]
        self.setWindowTitle("Nova — " + str(inst.get("type", "widget")))
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.card: WidgetBase = ctx.widget_manager.build_widget(inst, parent=self)
        self.card.window_pinned = True
        self.card.apply_transparency()
        self.card.setToolTip("")
        lay.addWidget(self.card)

        # card signals ------------------------------------------------------
        self.card.removed.connect(
            lambda wid: self.ctx.widget_manager.remove(wid))
        self.card.unpin_requested.connect(self._unpin)
        self.card.settings_changed.connect(
            lambda: (self.card.apply_transparency(),
                     self.ctx.widget_manager.persist_state(self.card)))
        self.card.request_overlay_pin.connect(
            lambda wgt, pinned:
            self.ctx.widget_manager.set_pin_overlay(wgt.instance["id"], pinned))

        self._dragging = False
        self._drag_offset = QPoint()

        self._restore_geometry()

    # ------------------------------------------------------------- pin ops
    def _unpin(self, widget_id: str) -> None:
        self.ctx.widget_manager.unpin_from_desktop(widget_id)

    def refresh_data(self) -> None:
        try:
            self.card.refresh()
        except Exception:
            pass

    def rescale(self) -> None:
        try:
            from .. import theme
            theme.apply_scale_to_tree(self)
        except Exception:
            pass

    # ------------------------------------------------------------ geometry
    def _restore_geometry(self) -> None:
        inst = self.inst
        registry = self.ctx.widget_manager._registry()
        meta = registry.get(inst["type"])
        default_w, default_h = (meta["cls"].default_size
                                if meta else (240, 160))
        w = int(inst.get("dw") or default_w)
        h = int(inst.get("dh") or default_h)
        self.resize(max(160, w), max(90, h))

        x, y = inst.get("dx"), inst.get("dy")
        scr = self.screen() or self.ctx.app_screen
        avail = scr.availableGeometry() if scr else None
        if x is None or y is None or avail is None:
            if avail is not None:
                x, y = self.ctx.widget_manager.next_desktop_position(
                    self.width(), self.height(), avail)
            else:
                x, y = 100, 100
            self.ctx.widget_manager.set_desktop_geometry(
                self.widget_id, x, y, self.width(), self.height())
        else:
            x, y = int(x), int(y)
            if avail is not None:
                # Keep the complete floating window visible after a
                # resolution or monitor-layout change.
                x = max(avail.left(), min(x, avail.right() - self.width() + 1))
                y = max(avail.top(), min(y, avail.bottom() - self.height() + 1))
        self.move(x, y)

    def persist_geometry(self) -> None:
        frame = self.frameGeometry()
        self.ctx.widget_manager.set_desktop_geometry(
            self.widget_id, frame.x(), frame.y(), self.width(), self.height())

    def shutdown(self) -> None:
        try:
            self.card.shutdown()
        except Exception:
            pass

    # ---------------------------------------------------------- drag (bg)
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._over_background(
                event.position().toPoint()):
            self._dragging = True
            self._drag_offset = QCursor.pos() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.move(QCursor.pos() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging:
            self._dragging = False
            self.card._clamp_window_into_screen()
            self.persist_geometry()
        super().mouseReleaseEvent(event)

    def _over_background(self, pos) -> bool:
        child = self.childAt(pos)
        return child is None or child is self.card


class DesktopWidgetsController(QObject):
    """Syncs PinnedWidgetWindow objects with WidgetManager state."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.windows: dict[str, PinnedWidgetWindow] = {}
        self._visible = bool(ctx.config.get("widgets.pinned", False))
        ctx.widget_manager.changed.connect(self.sync)
        ctx.widget_manager.data_changed.connect(self.refresh_all)

    # -------------------------------------------------------------- sync
    def sync(self) -> None:
        try:
            mgr = self.ctx.widget_manager
            desired = {i["id"]: i for i in mgr.for_surface("desktop")}
            # close windows whose widget was unpinned / removed
            for wid in list(self.windows):
                if wid not in desired:
                    try:
                        self.windows[wid].shutdown()
                    except Exception:
                        pass
                    self.windows[wid].hide()
                    self.windows[wid].deleteLater()
                    del self.windows[wid]
            # open windows for newly pinned widgets
            for wid, inst in desired.items():
                if wid not in self.windows:
                    try:
                        win = PinnedWidgetWindow(self.ctx, inst, self)
                    except Exception:
                        continue
                    self.windows[wid] = win
            # pinning the first widget flips the master visibility on
            if desired and not self._visible:
                self._visible = True
                self.ctx.config.set("widgets.pinned", True)
            if self._visible:
                for win in self.windows.values():
                    win.show()
                    win.raise_()
        except Exception:
            pass

    def refresh_all(self) -> None:
        for win in self.windows.values():
            win.refresh_data()

    def rescale_all(self) -> None:
        for win in self.windows.values():
            win.rescale()

    # ------------------------------------------------------ master toggle
    def is_visible(self) -> bool:
        return self._visible and bool(self.windows)

    def toggle_all(self) -> None:
        self.set_visible(not self.is_visible())

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self.ctx.config.set("widgets.pinned", self._visible)
        if self._visible:
            self.sync()
        else:
            for win in self.windows.values():
                win.hide()
