"""WidgetBase — chrome shared by every independent Nova widget.

Every widget card gets, per requirement:
  - an Edit button (edits the widget's primary content)
  - a Settings button (per-widget configuration dialog)
  - a Minimize/Collapse button
  - a Close/Hide button (unpins from desktop / removes the widget)
  - drag-to-move and resize support (grip at bottom-right corner)
  - a right-click menu: pin to desktop / pin in overlay / bring to front /
    reset size / remove

Modes:
  * canvas/page mode — free drag inside a host surface (legacy + overlay)
  * window_pinned mode — the card IS the content of its own floating
    desktop window: drag/resize move+resize the WINDOW, and the close
    button unpins back to the Widgets page
  * grid mode (drag_enabled=False, chrome hidden) — used by the Widgets
    management page where cards sit in a clean fixed grid
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QVBoxLayout, QWidget,
)

from ... import icons, theme
from ..widgets_common import style_scoped

SNAP = 8
HEADER_H = 30


def _tool_btn(icon_name: str, tip: str) -> QPushButton:
    b = QPushButton()
    b.setFixedSize(22, 22)
    b.setIcon(icons.icon(icon_name, theme.GHOST, 12))
    b.setIconSize(QSize(12, 12))
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    theme.set_style(b, 
        "QPushButton { background: transparent; border: none; border-radius: 5px; }"
        "QPushButton:hover { background: #232329; }")
    return b


class WidgetBase(QFrame):
    removed = Signal(str)          # widget id (delete entirely)
    unpin_requested = Signal(str)  # widget id (pinned close btn: back to page)
    geometry_changed = Signal(object)   # self
    raised = Signal(object)             # self
    settings_changed = Signal()         # per-widget settings persisted
    request_overlay_pin = Signal(object, bool)  # self, pinned

    title = "WIDGET"
    icon_name = "grid"
    default_size = (240, 160)
    min_size = (180, 120)
    has_settings = True

    def __init__(self, ctx, instance: dict, compact: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.instance = instance
        self.compact = compact
        self.settings: dict = dict(instance.get("settings") or {})
        self.window_pinned = False    # True when hosted in a desktop window
        self.drag_enabled = True      # False on the Widgets page grid

        self.setObjectName("NovaWidget")
        theme.set_style(
            self,
            f"QWidget#NovaWidget {{ background: {theme.WIDGET_BG};"
            f" border: 1px solid {theme.WIDGET_BORDER}; border-radius: 12px; }}")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(1, 1, 1, 1)
        self._root.setSpacing(0)

        # ------------------------------------------------------------ header
        self.header = QWidget()
        self.header.setFixedHeight(HEADER_H)
        theme.set_style(self.header, "background: transparent;")
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(8, 0, 4, 0)
        hl.setSpacing(2)
        self._grip_lbl = QLabel()
        self._grip_lbl.setPixmap(icons.pixmap("grip", "#3f3f46", 12))
        theme.set_style(self._grip_lbl, "background: transparent;")
        self.title_lbl = QLabel(self.display_title())
        theme.set_style(self.title_lbl, 
            f"color: {theme.MUTED}; font-size: 10px; font-weight: 700;"
            f" font-family: {theme.FONT_MONO}; letter-spacing: 1.2px;"
            "background: transparent; border: none;")
        hl.addWidget(self._grip_lbl)
        hl.addSpacing(2)
        hl.addWidget(self.title_lbl)
        hl.addStretch(1)

        if not compact:
            self.btn_edit = _tool_btn("edit", "Edit widget content")
            self.btn_edit.clicked.connect(self._on_edit_clicked)
            self.btn_cfg = _tool_btn("settings", "Widget settings")
            self.btn_cfg.clicked.connect(self.open_settings)
            self.btn_min = _tool_btn("minimize", "Collapse")
            self.btn_min.clicked.connect(self.toggle_collapsed)
            self.btn_close = _tool_btn("close", "Remove widget")
            self.btn_close.clicked.connect(self._on_close_clicked)
            for b in (self.btn_edit, self.btn_cfg, self.btn_min, self.btn_close):
                hl.addWidget(b)
        else:
            self.btn_unpin = _tool_btn("pin-off", "Unpin from overlay")
            self.btn_unpin.clicked.connect(
                lambda: self.request_overlay_pin.emit(self, False))
            hl.addWidget(self.btn_unpin)
        self._root.addWidget(self.header)

        # ------------------------------------------------------------- body
        self.body = QWidget()
        theme.set_style(self.body, "background: transparent;")
        self._body_lay = QVBoxLayout(self.body)
        self._body_lay.setContentsMargins(12, 4, 12, 12)
        self._body_lay.setSpacing(8)
        self._root.addWidget(self.body, 1)

        try:
            content = self.build_content(self._body_lay) or QWidget()
        except Exception:
            content = QLabel("Widget failed to load")
            theme.set_style(content, f"color: {theme.RED_TEXT}; font-size: 11px;")
        self.content = content
        self._body_lay.addWidget(content, 1)

        # resize grip (bottom-right) — only for full mode
        if not compact:
            self._grip = ResizeGrip(self)
            self._grip.resize_dragged = self._on_resize_drag
            self._grip.setCursor(Qt.SizeFDiagCursor)

        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._drag_offset: QPoint | None = None
        self._moved = False

        if self.settings.get("collapsed"):
            self._apply_collapsed(instant=True)

    # ------------------------------------------------------------ overridables
    def display_title(self) -> str:
        return self.title

    def build_content(self, parent: QVBoxLayout) -> QWidget | None:
        raise NotImplementedError

    def build_settings_form(self, parent) -> QWidget | None:
        """Return a widget exposing .apply() -> None, or None if no settings."""
        return None

    def edit_content(self) -> bool:
        """'Edit' button action; return True if handled."""
        return False

    def refresh(self) -> None:
        """Pull fresh data from stores (called by canvases on data changes)."""

    def shutdown(self) -> None:
        """Stop timers/threads before the widget is discarded."""

    def apply_transparency(self) -> None:
        """Apply this widget's saved transparency to its current surface."""
        opacity = max(20, min(100, int(self.settings.get("opacity", 100)))) / 100
        target = self.window() if self.window_pinned else self
        target.setWindowOpacity(opacity)

    # ------------------------------------------------------------ chrome ops
    def _on_edit_clicked(self) -> None:
        if not self.edit_content():
            self.open_settings()

    def _on_close_clicked(self) -> None:
        if self.window_pinned:
            # pinned to the desktop: the X unpins back to the Widgets page
            self.unpin_requested.emit(self.instance["id"])
        else:
            self.removed.emit(self.instance["id"])

    def set_chrome_visible(self, visible: bool) -> None:
        """Hide header buttons + grip (Widgets-page grid embeds)."""
        self.header.setVisible(visible)
        if hasattr(self, "_grip"):
            self._grip.setVisible(visible)

    def toggle_collapsed(self) -> None:
        self.settings["collapsed"] = not self.settings.get("collapsed")
        self.instance["settings"] = self.settings
        self._apply_collapsed()
        self.settings_changed.emit()

    def _apply_collapsed(self, instant: bool = False) -> None:
        collapsed = bool(self.settings.get("collapsed"))
        self.body.setVisible(not collapsed)
        if not self.compact:
            self.btn_min.setIcon(icons.icon(
                "chevron-up" if collapsed else "minimize", theme.GHOST, 12))
            self.btn_min.setToolTip("Expand" if collapsed else "Collapse")
        if collapsed:
            self.setMinimumHeight(HEADER_H + 2)
            self.setMaximumHeight(HEADER_H + 2)
        else:
            self.setMaximumHeight(16777215)
            min_h = self.min_size[1] if not self.compact else 0
            self.setMinimumHeight(min_h)

    def open_settings(self) -> None:
        if not self.has_settings:
            return
        form = self.build_settings_form(self)
        if form is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.display_title()} — settings")
        dlg.setModal(True)
        theme.set_style(dlg, 
            f"QDialog {{ background: {theme.PANEL}; }}"
            f"QLabel {{ color: {theme.TEXT}; font-size: 12px; background: transparent; }}")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(12)
        lay.addWidget(form)

        transparency_row = QHBoxLayout()
        transparency_label = QLabel("Transparency")
        transparency_slider = QSlider(Qt.Horizontal)
        transparency_slider.setRange(20, 100)
        transparency_slider.setValue(
            max(20, min(100, int(self.settings.get("opacity", 100)))))
        transparency_value = QLabel(f"{transparency_slider.value()}%")
        transparency_slider.valueChanged.connect(
            lambda value: transparency_value.setText(f"{value}%"))
        transparency_row.addWidget(transparency_label)
        transparency_row.addWidget(transparency_slider, 1)
        transparency_row.addWidget(transparency_value)
        lay.addLayout(transparency_row)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "ghost")
        cancel.clicked.connect(dlg.reject)
        ok = QPushButton("Apply")
        ok.setProperty("variant", "primary")
        ok.clicked.connect(dlg.accept)
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)
        if dlg.exec() == QDialog.Accepted:
            form.apply()
            self.settings["opacity"] = transparency_slider.value()
            self.instance["settings"] = self.settings
            self.apply_transparency()
            self.settings_changed.emit()
            self.refresh()

    # -------------------------------------------------------------- drag
    def _drag_start(self, pos: QPoint) -> None:
        if self.window_pinned:
            win = self.window()
            self._drag_offset = QCursor.pos() - win.frameGeometry().topLeft()
        else:
            self._drag_offset = pos
        self._moved = False

    def _drag_move(self) -> None:
        if self._drag_offset is None or self.compact or not self.drag_enabled:
            return
        self._moved = True
        if self.window_pinned:
            self.window().move(QCursor.pos() - self._drag_offset)
            return
        parent = self.parentWidget()
        if parent is None:
            return
        top_left = QCursor.pos() - self._drag_offset
        self.move(top_left - parent.mapToGlobal(QPoint(0, 0)))

    def _drag_end(self) -> None:
        if self._drag_offset is None:
            return
        self._drag_offset = None
        if self.compact or not self.drag_enabled:
            return
        if self.window_pinned:
            self._clamp_window_into_screen()
            self._persist_window_geometry()
            return
        # snap to grid and clamp inside the canvas
        parent = self.parentWidget()
        if parent is not None:
            p = self.pos()
            p.setX(max(0, (p.x() // SNAP) * SNAP))
            p.setY(max(0, (p.y() // SNAP) * SNAP))
            p.setX(min(p.x(), max(0, parent.width() - 60)))
            p.setY(min(p.y(), max(0, parent.height() - 40)))
            self.move(p)
        self.instance["x"], self.instance["y"] = self.x(), self.y()
        self.geometry_changed.emit(self)

    def _clamp_window_into_screen(self) -> None:
        win = self.window()
        scr = win.screen() or QApplication.primaryScreen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        geo = win.frameGeometry()
        # Keep the complete floating widget inside the usable screen area.
        x = max(avail.left(), min(geo.x(), avail.right() - geo.width() + 1))
        y = max(avail.top(), min(geo.y(), avail.bottom() - geo.height() + 1))
        win.move(x, y)

    def _persist_window_geometry(self) -> None:
        """Store the floating window's frame as the widget's desktop geom."""
        win = self.window()
        frame = win.frameGeometry()
        self.instance["dx"], self.instance["dy"] = frame.x(), frame.y()
        self.instance["dw"], self.instance["dh"] = win.width(), win.height()
        mgr = getattr(self.ctx, "widget_manager", None)
        if mgr is not None:
            mgr.save()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.compact and self.drag_enabled:
            self.raised.emit(self)
            self._drag_start(event.position().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self._drag_move()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_end()
        super().mouseReleaseEvent(event)

    def _on_resize_drag(self, delta: QPoint) -> None:
        w = max(self.min_size[0], self.width() + delta.x())
        h = max(self.min_size[1], self.height() + delta.y())
        if self.window_pinned:
            win = self.window()
            scr = win.screen() or QApplication.primaryScreen()
            if scr is not None:
                avail = scr.availableGeometry()
                w = min(w, avail.width())
                h = min(h, avail.height())
            win.resize(w, h)
        else:
            self.resize(w, h)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.compact and self.drag_enabled:
            self.toggle_collapsed()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        if self.compact:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        surf = self.instance.get("surface", "page")
        if self.window_pinned:
            act_unpin = menu.addAction("Unpin (back to Widgets page)")
            act_unpin.triggered.connect(
                lambda: self.unpin_requested.emit(self.instance["id"]))
        else:
            act_front = menu.addAction("Bring to front")
            act_front.triggered.connect(lambda: self.raised.emit(self))
            menu.addSeparator()
            act_page = menu.addAction("Move to Widgets page")
            act_page.setEnabled(surf != "page")
            act_page.triggered.connect(lambda: self._move_surface("page"))
            act_desk = menu.addAction("Pin to desktop")
            act_desk.setEnabled(surf != "desktop")
            act_desk.triggered.connect(lambda: self._move_surface("desktop"))
        pinned = bool(self.instance.get("pin_overlay"))
        menu.addSeparator()
        act_pin = menu.addAction("Pin in overlay" if not pinned
                                 else "Unpin from overlay")
        act_pin.triggered.connect(
            lambda: self.request_overlay_pin.emit(self, not pinned))
        menu.addSeparator()
        act_reset = menu.addAction("Reset size")
        act_reset.triggered.connect(self._reset_size)
        act_rm = menu.addAction("Remove widget")
        act_rm.triggered.connect(lambda: self.removed.emit(self.instance["id"]))
        menu.exec(event.globalPos())

    def _move_surface(self, surface: str) -> None:
        self.instance["surface"] = surface
        self.instance["settings"] = self.settings
        mgr = getattr(self.ctx, "widget_manager", None)
        if mgr:
            mgr.save()
            mgr.changed.emit()

    def _reset_size(self) -> None:
        self.resize(*self.default_size)
        self.instance["w"], self.instance["h"] = self.default_size
        self.geometry_changed.emit(self)

    # ---------------------------------------------------------- internals
    def resizeEvent(self, event) -> None:
        if not self.compact and hasattr(self, "_grip"):
            self._grip.move(self.width() - 16, self.height() - 16)
            self._grip.raise_()
        if not self.compact and not self.window_pinned:
            w, h = self.width(), self.height()
            if w != self.instance.get("w") or h != self.instance.get("h"):
                self.instance["w"], self.instance["h"] = w, h
        super().resizeEvent(event)

    # helpers for subclasses ---------------------------------------------
    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text.upper())
        theme.set_style(lbl, 
            f"color: {theme.GHOST}; font-size: 9px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1.4px; border: none; background: transparent;")
        return lbl

    def _value(self, size: int = 26, color: str = theme.WHITE, mono: bool = True,
               weight=700) -> QLabel:
        lbl = QLabel("")
        font_extra = f"font-family: {theme.FONT_MONO};" if mono else ""
        theme.set_style(lbl, 
            f"color: {color}; font-size: {size}px; font-weight: {weight};"
            f"{font_extra} border: none; background: transparent;")
        return lbl

    def _empty(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        theme.set_style(lbl, 
            f"color: {theme.GHOST}; font-size: 11px; border: none;"
            "background: transparent;")
        return lbl

    def _row_button(self, text: str, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("variant", "primary" if primary else "ghost")
        b.setCursor(Qt.PointingHandCursor)
        theme.set_style(
            b, "QPushButton { padding: 5px 10px; font-size: 11px; }")
        return b


class ResizeGrip(QWidget):
    """Bottom-right corner resize handle for widget cards."""

    resize_dragged = None  # set to callable(QPoint delta) by the owner

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        theme.set_style(self, "background: transparent;")
        self._press: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = QCursor.pos()

    def mouseMoveEvent(self, event) -> None:
        if self._press is not None and callable(self.resize_dragged):
            self.resize_dragged(QCursor.pos() - self._press)
            self._press = QCursor.pos()

    def mouseReleaseEvent(self, event) -> None:
        self._press = None

    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#3f3f46"))
        for i in range(3):
            p.drawEllipse(11 - i * 4, 11, 2, 2)
            p.drawEllipse(11, 11 - i * 4, 2, 2)
            p.drawEllipse(11 - i * 4, 11 - i * 4, 2, 2)
