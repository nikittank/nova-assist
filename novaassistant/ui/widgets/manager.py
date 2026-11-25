"""WidgetManager — registry, lifecycle and layout persistence for widgets.

Owns the list of widget instances (one JSON record each) stored in
config.widgets.instances so layouts survive restarts:

    {"id": "a1b2", "type": "clock", "surface": "page",
     "x": 24, "y": 24, "w": 240, "h": 150, "collapsed": false,
     "z": 3, "pin_overlay": false, "settings": {"format": "24h"}}

Surfaces: "page" (Widgets page canvas) and "desktop" (pinned desktop
canvas). Any instance with pin_overlay=True is additionally mirrored
(compactly) inside the floating AI overlay.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ...config import new_id

CASCADE_STEP = 28


class WidgetManager(QObject):
    changed = Signal()          # structure changed (add/remove/move surface)
    data_changed = Signal()     # stores changed -> refresh widget contents
    open_page = Signal(str)             # widget asks to open a main page
    edit_reminder = Signal(str)         # widget asks to edit a reminder id
    desktop_toggle = Signal()           # widget asks to toggle desktop pin

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        instances = config.get("widgets.instances")
        if not isinstance(instances, list):
            instances = []
            config.set("widgets.instances", instances)
        self.instances: list[dict] = instances
        if not self.instances:
            self._seed_defaults()

    # ------------------------------------------------------------ registry
    def _registry(self) -> dict:
        # late import avoids a cycle (widgets import manager helpers)
        from . import REGISTRY
        return REGISTRY

    def catalog(self) -> list[tuple[str, str, str]]:
        """(type_key, label, icon) for the Add-Widget menu."""
        return [(k, meta["label"], meta["icon"])
                for k, meta in self._registry().items()]

    # -------------------------------------------------------------- seeds
    def _seed_defaults(self) -> None:
        # non-overlapping starter layout (x, y) for the Widgets page canvas
        plan = [
            ("clock", 24, 24), ("date", 320, 24),
            ("focus", 24, 184), ("ai_status", 320, 168),
            ("quick_notes", 24, 344), ("reminders", 320, 400),
        ]
        for i, (wtype, x, y) in enumerate(plan):
            meta = self._registry()[wtype]
            w, h = meta["cls"].default_size
            self.instances.append({
                "id": new_id(), "type": wtype, "surface": "page",
                "x": x, "y": y, "w": w, "h": h, "collapsed": False,
                "z": i, "pin_overlay": False, "settings": {},
            })
        self.save()

    # ------------------------------------------------------------- queries
    def for_surface(self, surface: str) -> list[dict]:
        items = [i for i in self.instances if i.get("surface") == surface]
        return sorted(items, key=lambda i: i.get("z", 0))

    def overlay_pinned(self) -> list[dict]:
        return [i for i in self.instances if i.get("pin_overlay")]

    def get(self, widget_id: str) -> dict | None:
        for i in self.instances:
            if i["id"] == widget_id:
                return i
        return None

    def build_widget(self, instance: dict, compact: bool = False, parent=None):
        meta = self._registry()[instance["type"]]
        widget = meta["cls"](self._ctx(), instance, compact=compact, parent=parent)
        return widget

    def _ctx(self):
        return self._ctx_ref

    def attach_ctx(self, ctx) -> None:
        self._ctx_ref = ctx

    _ctx_ref = None

    # -------------------------------------------------------------- CRUD
    def create(self, wtype: str, surface: str = "page",
               near_bottom: bool = True) -> dict:
        registry = self._registry()
        if wtype not in registry:
            raise ValueError(f"unknown widget type: {wtype}")
        meta = registry[wtype]
        w, h = meta["cls"].default_size
        z = max([i.get("z", 0) for i in self.instances] or [0]) + 1
        # cascade placement below existing widgets on that surface
        ys = [i.get("y", 0) + i.get("h", 0) for i in self.for_surface(surface)]
        x = 24 + CASCADE_STEP * (len(self.instances) % 6)
        y = (max(ys) + 16) if ys else 24
        inst = {
            "id": new_id(), "type": wtype, "surface": surface,
            "x": x, "y": y, "w": w, "h": h, "collapsed": False,
            "z": z, "pin_overlay": False, "settings": {},
        }
        self.instances.append(inst)
        self.save()
        self.changed.emit()
        return inst

    def remove(self, widget_id: str) -> None:
        self.instances = [i for i in self.instances if i["id"] != widget_id]
        self.save()
        self.changed.emit()

    def persist_geometry(self, widget) -> None:
        inst = self.get(widget.instance["id"])
        if inst is not None:
            inst.update({"x": widget.x(), "y": widget.y(),
                         "w": widget.width(), "h": widget.height()})
            self.save()

    def persist_state(self, widget) -> None:
        inst = self.get(widget.instance["id"])
        if inst is not None:
            inst["settings"] = widget.settings
            inst["collapsed"] = bool(widget.settings.get("collapsed"))
            self.save()

    def set_pin_overlay(self, widget_id: str, pinned: bool) -> None:
        inst = self.get(widget_id)
        if inst is not None:
            inst["pin_overlay"] = bool(pinned)
            self.save()
            self.changed.emit()

    def move_surface(self, widget_id: str, surface: str) -> None:
        inst = self.get(widget_id)
        if inst is not None:
            inst["surface"] = surface
            self.save()
            self.changed.emit()

    # --------------------------------------------------- desktop pinning
    def pin_to_desktop(self, widget_id: str) -> None:
        """Pin ONE widget: it becomes its own floating desktop window."""
        inst = self.get(widget_id)
        if inst is None:
            return
        inst["surface"] = "desktop"
        self.save()
        self.changed.emit()

    def unpin_from_desktop(self, widget_id: str) -> None:
        inst = self.get(widget_id)
        if inst is None:
            return
        inst["surface"] = "page"
        self.save()
        self.changed.emit()

    def set_desktop_geometry(self, widget_id: str, x: int, y: int,
                             w: int, h: int) -> None:
        inst = self.get(widget_id)
        if inst is not None:
            inst.update({"dx": x, "dy": y, "dw": w, "dh": h})
            self.save()

    def next_desktop_position(self, w: int, h: int,
                              screen_avail) -> tuple[int, int]:
        """Cascade new pinned windows from the top-right of the screen."""
        n = len([i for i in self.instances if i.get("surface") == "desktop"])
        margin = 26
        step = 34
        x = screen_avail.right() - w - margin - (n % 5) * step
        y = screen_avail.top() + 60 + (n % 7) * step
        return max(screen_avail.left(), x), max(screen_avail.top(), y)

    def raise_widget(self, widget_id: str) -> None:
        inst = self.get(widget_id)
        if inst is not None:
            z = max([i.get("z", 0) for i in self.instances] or [0]) + 1
            inst["z"] = z
            self.save()   # no changed.emit(): purely visual, views already OK

    def reset_layout(self) -> None:
        self.instances = []
        self.save()
        self._seed_defaults()
        self.changed.emit()

    def save(self) -> None:
        try:
            self.config.set("widgets.pinned",
                            any(i.get("surface") == "desktop"
                                for i in self.instances), save=False)
        except Exception:
            pass
        self.config.set("widgets.instances", self.instances)
