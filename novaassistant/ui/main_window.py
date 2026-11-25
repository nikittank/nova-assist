"""Main window — frameless pitch-black chrome with custom titlebar + sidebar.

Includes Windows-style edge snapping: drag to the left/right edge snaps to
half of the screen, top maximizes, corners snap to quarters. A translucent
preview overlay shows the target region while dragging; dragging a snapped
window restores its previous size, exactly like native Windows behavior.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QFont, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton,
    QStackedWidget, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import icons, theme
from .widgets_common import StatusPill, TrafficLights, faint_hline, style_scoped

RESIZE_MARGIN = 5
SNAP_TRIGGER = 14          # px from a screen edge that triggers a snap zone
SNAP_UNSNAP_DELTA = 14     # px of drag movement needed to leave a snap

SNAP_ZONES = ("left", "right", "max", "nw", "ne", "sw", "se")


def snap_zone_for(global_pos: QPoint, avail: QRect) -> str | None:
    """Which snap zone does the cursor touch? Pure function (unit-tested)."""
    left = global_pos.x() - avail.left() <= SNAP_TRIGGER
    right = avail.right() - global_pos.x() <= SNAP_TRIGGER
    top = global_pos.y() - avail.top() <= SNAP_TRIGGER
    bottom = avail.bottom() - global_pos.y() <= SNAP_TRIGGER
    if top and left:
        return "nw"
    if top and right:
        return "ne"
    if bottom and left:
        return "sw"
    if bottom and right:
        return "se"
    if left:
        return "left"
    if right:
        return "right"
    if top:
        return "max"
    return None


def snap_geometry(zone: str, avail: QRect) -> QRect:
    """Target geometry for a snap zone. Pure function (unit-tested)."""
    x, y, w, h = avail.x(), avail.y(), avail.width(), avail.height()
    hw, hh = (w + 1) // 2, (h + 1) // 2
    return {
        "left": QRect(x, y, hw, h),
        "right": QRect(x + w - hw, y, hw, h),
        "max": QRect(x, y, w, h),
        "nw": QRect(x, y, hw, hh),
        "ne": QRect(x + w - hw, y, hw, hh),
        "sw": QRect(x, y + h - hh, hw, hh),
        "se": QRect(x + w - hw, y + h - hh, hw, hh),
    }.get(zone, avail)


class SnapPreview(QWidget):
    """Frameless, non-activating overlay that visualizes the snap target."""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def show_zone(self, geo: QRect) -> None:
        self.setGeometry(geo)
        self.show()
        self.raise_()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        p.setBrush(Qt.NoBrush)
        from PySide6.QtGui import QPen
        pen = QPen(QColor(255, 255, 255, 90), 1.4)
        p.setPen(pen)
        p.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 10, 10)


class TitleBar(QWidget):
    """h-9 window chrome replicating the mockup header (traffic dots + clock)."""

    sidebar_toggled = Signal()

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._win = window
        self.setFixedHeight(36)
        style_scoped(self, "TitleBar",
                     f"background: {theme.BLACK}; border-bottom: 1px solid rgba(255,255,255,0.05);")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 10, 0)
        lay.setSpacing(8)

        self._dots = TrafficLights()

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap("zap", "#a1a1aa", 14))
        theme.set_style(icon_lbl, "background: transparent;")

        title = QLabel("Nova — Personal Assistant")
        theme.set_style(title, 
            f"color: {theme.TEXT}; font-size: 11px; font-weight: 500;"
            "letter-spacing: 0.4px; background: transparent;")

        lay.addWidget(self._dots)
        lay.addSpacing(4)

        self._btn_sidebar = self._caption_button("sidebar")
        self._btn_sidebar.setToolTip("Toggle sidebar")
        self._btn_sidebar.clicked.connect(self.sidebar_toggled)
        lay.addWidget(self._btn_sidebar)
        lay.addSpacing(4)

        lay.addWidget(icon_lbl)
        lay.addWidget(title)
        lay.addStretch(1)

        # clean minimal header: status dot + clock only — no provider/model
        # text in the window chrome (that information lives in Settings and
        # on the Conversation tiles).
        self._dot = QLabel()
        self._dot.setFixedSize(6, 6)
        theme.set_style(self._dot, 
            f"background: {theme.EMERALD_500}; border-radius: 3px;")

        self._clock = QLabel()
        theme.set_style(self._clock, 
            f"color: {theme.MUTED}; font-size: 11px; font-family: {theme.FONT_MONO};"
            "background: transparent;")

        lay.addWidget(self._dot)
        lay.addSpacing(8)
        lay.addWidget(self._clock)
        lay.addSpacing(8)

        sep = QFrame()
        sep.setFixedSize(1, 16)
        theme.set_style(sep, "background: rgba(255,255,255,0.08);")
        lay.addWidget(sep)
        lay.addSpacing(4)

        self._btn_min = self._caption_button("minimize")
        self._btn_max = self._caption_button("maximize")
        self._btn_close = self._caption_button("close")
        theme.set_style(self._btn_close, 
            "QPushButton:hover { background: rgba(232,17,35,0.85); }")
        self._btn_min.clicked.connect(window.showMinimized)
        self._btn_max.clicked.connect(window.toggle_maximize)
        self._btn_close.clicked.connect(window.request_close)
        lay.addWidget(self._btn_min)
        lay.addWidget(self._btn_max)
        lay.addWidget(self._btn_close)

        t = QTimer(self)
        t.setInterval(10000)
        t.timeout.connect(self._tick)
        t.start()
        self._tick()

        # one font everywhere: same typeface as the sidebar/technical UI
        theme.apply_unified_font(self)

    def _caption_button(self, name: str) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("variant", "titlebtn")
        btn.setIcon(icons.icon(name, "#a1a1aa", 12, 1.75))
        btn.setFixedSize(34, 26)
        btn.setCursor(Qt.PointingHandCursor)
        theme.set_style(btn, 
            "QPushButton { background: transparent; border: none; border-radius: 4px; }"
            "QPushButton:hover { background: #1f1f23; }")
        return btn

    def _tick(self) -> None:
        now = datetime.now()
        self._clock.setText(
            f"{now.strftime('%a, %b')} {now.day}, {now.strftime('%Y')}   "
            f"{now.strftime('%I:%M %p')}")

    # drag handling
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._win.window_handle_start(QCursor.pos())

    def mouseDoubleClickEvent(self, event) -> None:
        self._win.toggle_maximize()

    def mouseMoveEvent(self, event) -> None:
        self._win.window_handle_move(QCursor.pos())

    def mouseReleaseEvent(self, event) -> None:
        self._win.window_handle_end()


class SideNavItem(QPushButton):
    def __init__(self, icon_name: str, label: str, parent=None):
        super().__init__(label, parent)
        self._icon_name = icon_name
        self._label_text = label
        self._active = False
        self._icon_only = False
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.setIcon(icons.icon(icon_name, theme.MUTED, 16, 1.75))
        self.setIconSize(QSize(16, 16))
        theme.set_style(self, self._qss(False))
        self._trailing_dot = False
        font = QFont()
        font.setPointSize(9)
        font.setWeight(QFont.DemiBold)
        self.setFont(font)

    def set_icon_only(self, icon_only: bool) -> None:
        self._icon_only = icon_only
        if icon_only:
            self.setText("")
            self.setToolTip(self._label_text)
            self.setMinimumWidth(36)
            self.setMaximumWidth(36)
        else:
            self.setText(self._label_text)
            self.setToolTip("")
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
        theme.set_style(self, self._qss(self._active))

    def _qss(self, active: bool) -> str:
        align = "center; padding: 6px 0;" if self._icon_only else "left; padding: 6px 12px;"
        if active:
            return (f"QPushButton {{ background: {theme.WHITE}; color: {theme.BLACK};"
                    f" border: 1px solid {theme.WHITE}; border-radius: 8px;"
                    f" text-align: {align} font-family: {theme.FONT_MONO};"
                    " font-size: 13px; }}")
        return (f"QPushButton {{ background: {theme.BLACK}; color: {theme.WHITE};"
                f" border: 1px solid transparent; border-radius: 8px;"
                f" text-align: {align} font-family: {theme.FONT_MONO};"
                " font-size: 13px; }"
                "QPushButton:hover { background: #18181b; color: #ffffff; }")

    def set_active(self, active: bool) -> None:
        self._active = active
        self.setChecked(active)
        self.setIcon(icons.icon(self._icon_name,
                                theme.BLACK if active else theme.WHITE, 16, 1.75))
        theme.set_style(self, self._qss(active))


class Sidebar(QWidget):
    page_requested = Signal(str)

    ITEMS = [
        ("conversation", "message", "Conversation"),
        ("notes", "note", "Notes"),
        ("reminders", "bell", "Reminders"),
        ("activity", "activity", "Activity"),
        ("files", "folder", "Files"),
        ("widgets", "grid", "Widgets"),
    ]

    WIDTH = 256
    WIDTH_COLLAPSED = 60

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self._collapsed = False
        self.setFixedWidth(self.WIDTH)
        style_scoped(self, "Sidebar",
                     f"background: {theme.BLACK}; border-right: 1px solid rgba(255,255,255,0.05);")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 24, 16, 20)
        self.root.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.brand = QLabel("NOVA")
        self.brand.setAlignment(Qt.AlignCenter)
        theme.set_style(self.brand, 
            f"color: {theme.WHITE}; font-size: 14px; font-weight: 700;"
            "letter-spacing: 4px; background: transparent;")
        self.pill = StatusPill("Idle")
        head.addWidget(self.brand)
        head.addStretch(1)
        head.addWidget(self.pill)

        self.subtitle = QLabel("Personal Desktop Assistant")
        theme.set_style(self.subtitle, f"color: {theme.GHOST}; font-size: 10px; margin-top: 0;")

        self.name_input = QLineEdit()
        self.name_input.setText(self.config.get("ui.user_name", "") if self.config else "")
        self.name_input.setPlaceholderText("Enter your name")
        self.name_input.setFixedHeight(36)
        self.name_input.editingFinished.connect(self._save_name)
        theme.set_style(self.name_input,
                        f"QLineEdit {{ background: transparent; color: {theme.TEXT};"
                        f" border: 1px solid rgba(255,255,255,0.12); border-radius: 7px;"
                        " padding: 7px 10px; font-size: 12px; "
                        f"font-family: {theme.FONT_MONO}; }}"
                        f"QLineEdit:focus {{ border: 1px solid {theme.WHITE}; }}")

        self.root.addLayout(head)
        self.root.addSpacing(10)
        self.root.addWidget(self.subtitle)
        self.root.addSpacing(10)
        self.root.addWidget(self.name_input)
        self.root.addSpacing(28)
        self._collapsed_header_spacer = QWidget()
        self._collapsed_header_spacer.setFixedHeight(0)
        self.root.addWidget(self._collapsed_header_spacer)

        self._nav_buttons: dict[str, SideNavItem] = {}
        for key, icon_name, label in self.ITEMS:
            btn = SideNavItem(icon_name, label)
            btn.clicked.connect(lambda _=False, k=key: self.page_requested.emit(k))
            self.root.addWidget(btn)
            self.root.addSpacing(4)
            self._nav_buttons[key] = btn

        self.root.addStretch(1)
        self.root.addWidget(faint_hline())
        self.root.addSpacing(10)

        settings_btn = SideNavItem("settings", "Settings")
        settings_btn.clicked.connect(lambda: self.page_requested.emit("settings"))
        self.root.addWidget(settings_btn)
        self._nav_buttons["settings"] = settings_btn

        self.root.addSpacing(8)
        self.nova_box = QPushButton("NOVA")
        self.nova_box.setCursor(Qt.PointingHandCursor)
        self.nova_box.clicked.connect(lambda: self.page_requested.emit("overlay"))
        theme.set_style(self.nova_box,
                        f"color: {theme.BLACK}; background: {theme.WHITE};"
                        " border: none; border-radius: 8px; padding: 8px 12px;"
                        f" font-family: {theme.FONT_MONO}; font-size: 13px;"
                        " font-weight: 700; letter-spacing: 3px;")
        self.root.addWidget(self.nova_box)

        self.root.addSpacing(10)
        self.tag = QLabel("A QUIETER SMARTER YOU")
        self.tag.setMinimumWidth(0)
        self.tag.setMaximumWidth(self.WIDTH - 32)
        self.tag.setFixedHeight(18)
        self.tag.setAlignment(Qt.AlignCenter)
        self.tag.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        theme.set_style(self.tag, 
            f"color: {theme.GHOST}; font-size: 9px; letter-spacing: 1.4px;"
            " background: transparent;")
        self.root.addWidget(self.tag)

        # one font everywhere: same typeface as the technical UI
        theme.apply_unified_font(self)

    def _save_name(self) -> None:
        if self.config:
            self.config.set("ui.user_name", self.name_input.text().strip())

    def set_collapsed(self, collapsed: bool) -> None:
        """Icon-rail mode for small windows; labels hidden, buttons kept."""
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.setFixedWidth(self.WIDTH_COLLAPSED if collapsed else self.WIDTH)
        self.brand.setVisible(True)
        self.brand.setText("N" if collapsed else "NOVA")
        if collapsed:
            self.brand.setFixedWidth(36)
        else:
            self.brand.setMinimumWidth(0)
            self.brand.setMaximumWidth(16777215)
        self.subtitle.setVisible(not collapsed)
        self.name_input.setVisible(not collapsed)
        self._collapsed_header_spacer.setFixedHeight(49 if collapsed else 0)
        self.pill.setVisible(not collapsed)
        self.tag.setVisible(not collapsed)
        self.nova_box.setVisible(True)
        self.nova_box.setText("N" if collapsed else "NOVA")
        self.nova_box.setFixedWidth(36 if collapsed else self.WIDTH - 32)
        margins = self.root.contentsMargins()
        self.root.setContentsMargins(10 if collapsed else margins.left(),
                                     margins.top(), 10 if collapsed else margins.right(),
                                     margins.bottom())
        for btn in self._nav_buttons.values():
            btn.set_icon_only(collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_active(self, key: str) -> None:
        for k, btn in self._nav_buttons.items():
            btn.set_active(k == key)

    def set_status(self, text: str, busy: bool) -> None:
        self.pill.set_text(text)
        self.pill.set_busy(busy)


class MainWindow(QMainWindow):
    """Frameless main shell."""

    overlay_requested = Signal(bool)
    pin_widgets_requested = Signal(bool)
    new_note_requested = Signal()
    close_requested = Signal()
    minimized_changed = Signal(bool)   # requirement #14: notify on minimize

    def __init__(self, app_ctx):
        super().__init__()
        self.ctx = app_ctx
        self.setWindowTitle("Nova — Personal Assistant")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(QSize(940, 620))
        self.resize(1280, 820)
        self.setMouseTracking(True)
        self._sidebar_manual = False
        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(700)
        self._geo_timer.timeout.connect(self._persist_geometry)

        root = QWidget(objectName="RootWindow")
        root.setMouseTracking(True)
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.titlebar = TitleBar(self)
        self.titlebar.sidebar_toggled.connect(self._manual_toggle_sidebar)
        outer.addWidget(self.titlebar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        self.sidebar = Sidebar(self.ctx.config)
        self.sidebar.page_requested.connect(self.navigate)
        body.addWidget(self.sidebar)

        body.addWidget(_VLine())

        self.stack = QStackedWidget()
        style_scoped(self.stack, "PageStack", "background: #000000;")
        body.addWidget(self.stack, 1)

        # frameless state
        self._drag_offset: QPoint | None = None
        self._dragging = False
        self._resize_edge: str = ""
        self._resize_start_geom: QRect | None = None
        self._resize_start_pos: QPoint | None = None

        # snap state
        self._snap_preview = SnapPreview()
        self._snap_zone: str | None = None       # zone under cursor (dragging)
        self._snap_applied: str | None = None    # zone the window rests in
        self._restore_geo: QRect | None = None   # pre-snap / pre-max geometry
        self._drag_start_pos: QPoint | None = None

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(60000)
        self._restore_geometry()

    # ------------------------------------------------------------ nav
    def add_page(self, key: str, widget) -> None:
        self.stack.addWidget(widget)
        widget._page_key = key  # type: ignore[attr-defined]

    def navigate(self, key: str) -> None:
        if key == "overlay":
            self.overlay_requested.emit(True)
            return
        if key == "widgets-pin":
            self.pin_widgets_requested.emit(True)
            return
        for i in range(self.stack.count()):
            w = self.stack.widget(i)
            if getattr(w, "_page_key", "") == key:
                self.stack.setCurrentIndex(i)
                self.sidebar.set_active(key)
                self.ctx.config.set("ui.last_page", key)
                if hasattr(w, "on_shown"):
                    w.on_shown()
                return

    def current_key(self) -> str:
        return getattr(self.stack.currentWidget(), "_page_key", "conversation")

    def set_status(self, text: str, busy: bool) -> None:
        self.sidebar.set_status(text, busy)

    # -------------------------------------------------------- frameless
    def window_handle_start(self, global_pos: QPoint) -> None:
        self._dragging = True
        self._drag_start_pos = global_pos
        self._drag_offset = global_pos - self.frameGeometry().topLeft()
        if not self.isMaximized() and self._snap_applied is None:
            self._restore_geo = self.geometry()

    def window_handle_move(self, global_pos: QPoint) -> None:
        if not self._dragging or self._drag_offset is None:
            return
        if self.isMaximized() or self._snap_applied is not None:
            # native-Windows feel: drag a few px to restore the old size
            delta = global_pos - self._drag_start_pos
            if abs(delta.y()) < SNAP_UNSNAP_DELTA and abs(delta.x()) < SNAP_UNSNAP_DELTA:
                return
            self._leave_snap(global_pos)
        self.move(global_pos - self._drag_offset)
        self._update_snap_preview(global_pos)

    def window_handle_end(self) -> None:
        if self._dragging:
            self._apply_pending_snap()
        self._dragging = False
        self._drag_offset = None
        self._drag_start_pos = None
        self._snap_preview.hide()
        self._snap_zone = None

    # ------------------------------------------------------------- snap
    def _screen_avail(self, global_pos: QPoint) -> QRect:
        scr = QApplication.screenAt(global_pos) or self.screen()
        geo = scr.availableGeometry() if scr else None
        return geo if geo is not None else self.frameGeometry()

    def _update_snap_preview(self, global_pos: QPoint) -> None:
        if self.isMaximized():
            return
        zone = snap_zone_for(global_pos, self._screen_avail(global_pos))
        if zone != self._snap_zone:
            self._snap_zone = zone
            if zone is None:
                self._snap_preview.hide()
            else:
                self._snap_preview.show_zone(
                    snap_geometry(zone, self._screen_avail(global_pos)))

    def _apply_pending_snap(self) -> None:
        zone = self._snap_zone
        if zone is None or self.isMaximized():
            return
        if self._snap_applied is None and self._restore_geo is None:
            self._restore_geo = self.geometry()
        avail = self._screen_avail(QCursor.pos())
        target = snap_geometry(zone, avail)
        if zone == "max":
            self.showMaximized()
        else:
            self.setGeometry(target)
        self._snap_applied = zone

    def _leave_snap(self, global_pos: QPoint) -> None:
        """Restore the pre-snap / pre-maximized size under the cursor."""
        restore = self._restore_geo
        if self.isMaximized():
            self.showNormal()
        self._snap_applied = None
        if restore is not None and restore.width() >= self.minimumWidth():
            self.setGeometry(restore)
        else:
            self.resize(1280, 820)
        # keep the cursor pinned to the same relative spot on the titlebar
        rel_x = max(0.15, min(0.85, 0.5))
        self._drag_offset = QPoint(
            int(restore.width() * rel_x) if restore else self.width() // 2,
            18)

    def toggle_maximize(self) -> None:
        self._snap_preview.hide()
        self._snap_zone = None
        if self.isMaximized():
            self.showNormal()
            self._snap_applied = None
            if self._restore_geo is not None:
                self.setGeometry(self._restore_geo)
        else:
            if self._snap_applied is None:
                self._restore_geo = self.geometry()
            self._snap_applied = None
            self.showMaximized()

    def changeEvent(self, event) -> None:
        """Notify when the window is minimized / restored so the overlay can
        switch to its compact floating UI (requirement #14)."""
        super().changeEvent(event)
        try:
            if event.type() == event.Type.WindowStateChange:
                minimized = self.isMinimized()
                self.minimized_changed.emit(minimized)
        except Exception:
            pass

    # ------------------------------------------------------ sidebar / geo
    def _manual_toggle_sidebar(self) -> None:
        self._sidebar_manual = True
        self.sidebar.set_collapsed(not self.sidebar.is_collapsed())

    def resizeEvent(self, event) -> None:
        # keep everything usable on small windows: icon rail at <= 1040px
        if not self._sidebar_manual:
            self.sidebar.set_collapsed(self.width() <= 1040)
        self._geo_timer.start()
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:
        self._geo_timer.start()
        super().moveEvent(event)

    def _persist_geometry(self) -> None:
        try:
            cfg = getattr(self.ctx, "config", None)
            if cfg is None:
                return
            cfg.set("ui.geometry", {
                "x": self.x(), "y": self.y(),
                "w": self.width(), "h": self.height(),
                "maximized": self.isMaximized(),
            }, save=False)
            cfg.save()
        except Exception:
            pass

    def _restore_geometry(self) -> None:
        try:
            geo = self.ctx.config.get("ui.geometry") or {}
            if geo.get("maximized"):
                return   # will open normal-size; user can maximize again
            w = int(geo.get("w", 0)) or 1280
            h = int(geo.get("h", 0)) or 820
            from PySide6.QtGui import QScreen
            self.resize(max(self.minimumWidth(), w), max(self.minimumHeight(), h))
            scr = self.screen()
            avail = scr.availableGeometry() if scr else None
            x, y = int(geo.get("x", 0)), int(geo.get("y", 0))
            if avail:
                # A saved position can become invalid after a monitor is
                # unplugged or Windows changes DPI.  The old partial-point
                # check allowed the left side of the window to remain off
                # screen, which hid the sidebar text and navigation.
                max_x = max(avail.left(), avail.right() - self.width() + 1)
                max_y = max(avail.top(), avail.bottom() - self.height() + 1)
                x = max(avail.left(), min(x, max_x))
                y = max(avail.top(), min(y, max_y))
            self.move(x, y)
        except Exception:
            pass

    def request_close(self) -> None:
        self.close_requested.emit()

    # resize edges
    def _edge_at(self, pos) -> str:
        m = RESIZE_MARGIN
        r = self.rect()
        edge = ""
        if pos.y() <= m:
            edge += "n"
        elif pos.y() >= r.height() - m:
            edge += "s"
        if pos.x() <= m:
            edge += "w"
        elif pos.x() >= r.width() - m:
            edge += "e"
        return edge

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            if edge:
                self._resize_edge = edge
                self._resize_start_geom = self.geometry()
                self._resize_start_pos = QCursor.pos()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resize_edge and self._resize_start_geom and self._resize_start_pos:
            delta = QCursor.pos() - self._resize_start_pos
            g = QRect(self._resize_start_geom)
            if "e" in self._resize_edge:
                g.setWidth(max(self.minimumWidth(), g.width() + delta.x()))
            if "s" in self._resize_edge:
                g.setHeight(max(self.minimumHeight(), g.height() + delta.y()))
            if "w" in self._resize_edge:
                nw = max(self.minimumWidth(), g.width() - delta.x())
                g.setLeft(g.right() - nw + 1)
            if "n" in self._resize_edge:
                nh = max(self.minimumHeight(), g.height() - delta.y())
                g.setTop(g.bottom() - nh + 1)
            self.setGeometry(g)
            return
        if not self.isMaximized():
            edge = self._edge_at(event.position().toPoint())
            cursors = {
                "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
                "e": Qt.SizeHorCursor, "w": Qt.SizeHorCursor,
                "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
                "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
            }
            self.setCursor(cursors.get(edge, Qt.ArrowCursor))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._resize_edge = ""
        self._resize_start_geom = None
        self._resize_start_pos = None
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        p.setPen(theme.BORDER)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))


class _VLine(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedWidth(1)
        theme.set_style(self, "background: rgba(255,255,255,0.05);")
