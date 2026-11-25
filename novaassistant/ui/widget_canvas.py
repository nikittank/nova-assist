"""WidgetCanvas — absolute-position host surface for independent widgets.

One canvas per surface: the Widgets page hosts surface="page", the pinned
desktop window hosts surface="desktop". The canvas:
  - rebuilds its children from WidgetManager on structural changes
  - refreshes children on store data changes
  - persists geometry / collapse / settings through the manager
  - shows a friendly empty state with an Add-Widget action
  - adapts its minimum size so parents scroll instead of clipping
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import theme
from .widgets import WidgetBase
from .widgets.manager import WidgetManager

MARGIN = 24


class WidgetCanvas(QWidget):
    add_requested = Signal()      # empty-state button pressed

    def __init__(self, ctx, surface: str, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.surface = surface
        self.manager: WidgetManager = ctx.widget_manager
        self._widgets: list[WidgetBase] = []
        self.setStyleSheet(f"background: {theme.BLACK};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.empty_lbl = QLabel(
            "No widgets here yet.\nAdd one from the toolbar above, or "
            "right-click any widget to move it here.")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setStyleSheet(
            f"color: {theme.GHOST}; font-size: 12px; border: 1px dashed {theme.BORDER_2};"
            "border-radius: 12px; padding: 28px; background: transparent;")
        lay.addWidget(self.empty_lbl)

        self.manager.changed.connect(self.rebuild)
        self.manager.data_changed.connect(self.refresh_all)
        self.rebuild()

    # ------------------------------------------------------------ lifecycle
    def rebuild(self) -> None:
        for w in self._widgets:
            try:
                w.shutdown()
            except Exception:
                pass
            w.setParent(None)
            w.hide()
            w.deleteLater()
        self._widgets = []

        for inst in self.manager.for_surface(self.surface):
            try:
                w = self.manager.build_widget(inst, parent=self)
            except Exception:
                continue
            w.setGeometry(int(inst.get("x", 24)), int(inst.get("y", 24)),
                          int(inst.get("w", 240)), int(inst.get("h", 160)))
            w.removed.connect(self.manager.remove)
            w.geometry_changed.connect(self.manager.persist_geometry)
            w.settings_changed.connect(
                lambda wgt=w: self.manager.persist_state(wgt))
            w.raised.connect(self._on_raised)
            w.request_overlay_pin.connect(
                lambda wgt, pinned: self.manager.set_pin_overlay(wgt.instance["id"], pinned))
            if inst.get("settings", {}).get("collapsed"):
                w._apply_collapsed(instant=True)
            w.show()
            self._widgets.append(w)

        self.empty_lbl.setVisible(not self._widgets)
        self._update_min_size()

    def refresh_all(self) -> None:
        for w in self._widgets:
            try:
                w.refresh()
            except Exception:
                pass

    def _on_raised(self, widget: WidgetBase) -> None:
        widget.raise_()
        self.manager.raise_widget(widget.instance["id"])

    def _update_min_size(self) -> None:
        if not self._widgets:
            self.setMinimumSize(320, 240)
            return
        right = max(w.x() + w.width() for w in self._widgets)
        bottom = max(w.y() + w.height() for w in self._widgets)
        self.setMinimumSize(right + MARGIN, bottom + MARGIN)

    # mouse press on the canvas background raises nothing; the desktop
    # window subclass uses it to drag the frameless window itself.
    def background_press(self) -> bool:
        return True
