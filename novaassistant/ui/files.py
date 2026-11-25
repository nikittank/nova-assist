"""Files page — full file-manager experience.

Requirement #7: a clean professional file manager that supports:
  - Drive selection (Windows drives or home subdirs on other platforms)
  - Folder navigation (open folders by double-click)
  - Back / Forward / Up navigation with history
  - Breadcrumb path that you can click to jump to any ancestor
  - Search box that filters entries live
  - File actions (open)
  - Clean professional file-manager style consistent with Nova

Not locked to C:\\ anymore — start at the user's home folder.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .. import icons, theme
from ..core import tools as desk
from .flowlayout import FlowLayout
from .widgets_common import NoScrollCombo, ScrollArea, TagPill, style_scoped


IS_WINDOWS = sys.platform == "win32"


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _list_drives() -> list[tuple[str, str]]:
    """Return (label, path) pairs for every drive / quick location."""
    out: list[tuple[str, str]] = []
    if IS_WINDOWS:
        import string
        for letter in string.ascii_uppercase:
            drv = f"{letter}:\\"
            if os.path.isdir(drv):
                out.append((f"{letter}:", drv))
    if not out:
        home = os.path.expanduser("~")
        out.append(("Home", home))
        for name in ("Desktop", "Documents", "Downloads", "Music",
                     "Pictures", "Videos"):
            p = os.path.join(home, name)
            if os.path.isdir(p):
                out.append((name, p))
    return out


class Breadcrumb(QWidget):
    """Path breadcrumb with clickable segments."""
    clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._segments: list[tuple[str, str]] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._lay = lay
        theme.set_style(self,
            f"color: {theme.MUTED}; font-family: {theme.FONT_MONO};"
            "font-size: 11px; background: transparent;")

    def set_path(self, path: str) -> None:
        self._path = path
        # clear
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        # build segments
        home = os.path.expanduser("~")
        display = path
        if path.lower().startswith(home.lower()):
            display = "~" + path[len(home):]
        parts = [p for p in display.replace("\\", "/").split("/") if p]
        # rebuild absolute-ish path per segment for click
        running = home if path.lower().startswith(home.lower()) else \
            (("/" if path.startswith("/") else ""))
        self._segments = []
        for i, part in enumerate(parts):
            if i == 0 and part == "~":
                running = home
                full = home
            elif i == 0 and (IS_WINDOWS and part.endswith(":")):
                running = part + "\\"
                full = running
            elif i == 0:
                running = "/" + part
                full = running
            else:
                full = os.path.join(running, part)
                running = full
            self._segments.append((part, full))
        # render
        for i, (label, full) in enumerate(self._segments):
            btn = QPushButton(label)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFlat(True)
            is_last = (i == len(self._segments) - 1)
            theme.set_style(btn,
                f"color: {theme.WHITE if is_last else theme.MUTED};"
                "font-family: " + theme.FONT_MONO + "; font-size: 11px;"
                "background: transparent; border: none; padding: 2px 4px;"
                "text-align: left;")
            btn.clicked.connect(lambda _=False, p=full: self.clicked.emit(p))
            self._lay.addWidget(btn)
            if not is_last:
                sep = QLabel("/")
                theme.set_style(sep,
                    f"color: {theme.GHOST}; font-family: {theme.FONT_MONO};"
                    "font-size: 11px; padding: 0 2px;"
                    "background: transparent; border: none;")
                self._lay.addWidget(sep)
        self._lay.addStretch(1)


class FileRow(QFrame):
    clicked = Signal()
    def __init__(self, path: str, is_dir: bool, query: str = ""):
        super().__init__()
        self.path = path
        self.is_dir = is_dir
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("FileTreeRow")
        name = os.path.basename(path) or path
        try:
            st = os.stat(path)
            size = "<DIR>" if is_dir else _fmt_size(st.st_size)
            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            size, mtime = "—", "—"
        theme.set_style(self,
            f"QFrame#FileTreeRow {{ background: #0a0a0c; border: 1px solid {theme.BORDER};"
            "border-radius: 8px; }"
            "QFrame#FileTreeRow:hover { background: #111115; border-color: #3f3f46; }")
        self._name = name
        self._size = size
        self._mtime = mtime
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(10)
        icon_label = QLabel()
        icon_label.setFixedSize(18, 18)
        icon_label.setScaledContents(True)
        icon_label.setPixmap(icons.pixmap(
            "folder" if is_dir else "file",
            "#f5c451" if is_dir else theme.MUTED, 16))
        lay.addWidget(icon_label)
        self.name_label = QLabel(name)
        self.name_label.setToolTip(path)
        theme.set_style(self.name_label,
                        f"color: {theme.WHITE if is_dir else theme.TEXT};"
                        " font-size: 13px; border: none; background: transparent;")
        lay.addWidget(self.name_label, 1)
        self.type_label = QLabel("Folder" if is_dir else "File")
        self.size_label = QLabel(size)
        self.date_label = QLabel(mtime)
        for label in (self.type_label, self.size_label, self.date_label):
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            theme.set_style(label,
                            f"color: {theme.MUTED}; font-size: 11px;"
                            f" font-family: {theme.FONT_MONO}; border: none;"
                            " background: transparent;")
        self.type_label.setFixedWidth(82)
        self.size_label.setFixedWidth(86)
        self.date_label.setFixedWidth(142)
        lay.addWidget(self.type_label)
        lay.addWidget(self.size_label)
        lay.addWidget(self.date_label)
        self.setMinimumHeight(42)
        self._query = query.lower()
        
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _render(self) -> None:
        return

        # Legacy text-rendering path retained below for compatibility.
        avail = max(80, self.width() - 90)
        metrics = self.fontMetrics()
        shown = self._name
        if metrics.horizontalAdvance(shown) > avail:
            while shown and metrics.horizontalAdvance(shown + "…") > avail:
                shown = shown[:-1]
            shown += "…"
        self.setText(f"{shown}    {self._meta}")

    def resizeEvent(self, event) -> None:
        self._render()
        super().resizeEvent(event)


class FilesPage(QWidget):
    request_llm = Signal(str)
    status_message = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._path = desk.home_path("Desktop") if os.path.isdir(
            desk.home_path("Desktop")) else os.path.expanduser("~")
        self._back_stack: list[str] = []
        self._forward_stack: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ------------------------------------------------------- header
        header = QWidget()
        style_scoped(header, "FilesHeader",
                     f"background: {theme.BLACK};"
                     f" border-bottom: 1px solid {theme.BORDER};")
        hl = QVBoxLayout(header)
        hl.setContentsMargins(24, 18, 24, 14)
        hl.setSpacing(10)
        title_row = QHBoxLayout()
        title = QLabel("Files")
        theme.set_style(title,
                        f"color: {theme.WHITE}; font-size: 20px; font-weight: 700;"
                        "background: transparent; border: none;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        hl.addLayout(title_row)

        # toolbar: back / forward / up / drive selector / search
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.btn_back = self._nav_btn("chevron-left", "Back")
        self.btn_back.clicked.connect(self._go_back)
        self.btn_forward = self._nav_btn("chevron-right", "Forward")
        self.btn_forward.clicked.connect(self._go_forward)
        self.btn_up = self._nav_btn("chevron-up", "Up")
        self.btn_up.clicked.connect(self._go_up)
        toolbar.addWidget(self.btn_back)
        toolbar.addWidget(self.btn_forward)
        toolbar.addWidget(self.btn_up)
        toolbar.addSpacing(6)
        drive_lbl = QLabel("Drive")
        theme.set_style(drive_lbl,
            f"color: {theme.MUTED}; font-size: 11px;"
            f"font-family: {theme.FONT_MONO}; letter-spacing: 0.6px;"
            "background: transparent; border: none;")
        toolbar.addWidget(drive_lbl)
        self.drive_combo = NoScrollCombo()
        theme.set_style(self.drive_combo,
            "QComboBox { background: #0c0c0e; border: 1px solid #22232b;"
            " border-radius: 8px; padding: 6px 10px; font-size: 12px;"
            f" color: {theme.TEXT_BRIGHT}; }}"
            f"QComboBox QAbstractItemView {{ background: #0c0c0e;"
            f" border: 1px solid {theme.BORDER_2}; }}")
        self.drive_combo.setCursor(Qt.PointingHandCursor)
        self.drive_combo.setMinimumWidth(120)
        self.drive_combo.currentIndexChanged.connect(self._on_drive_changed)
        toolbar.addWidget(self.drive_combo)
        toolbar.addSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search this folder…")
        self.search.setClearButtonEnabled(True)
        theme.set_style(self.search,
            f"QLineEdit {{ background: #0c0c0e; border: 1px solid #22232b;"
            f" border-radius: 8px; padding: 6px 10px; font-size: 12px;"
            f" color: {theme.TEXT_BRIGHT}; }}")
        self.search.textChanged.connect(lambda _t: self._refresh())
        toolbar.addWidget(self.search, 1)
        hl.addLayout(toolbar)

        # breadcrumb
        self.breadcrumb = Breadcrumb()
        self.breadcrumb.clicked.connect(self._goto)
        hl.addWidget(self.breadcrumb)

        # ask nova row
        ask_row = QHBoxLayout()
        ask_row.setSpacing(8)
        self.ask = QLineEdit()
        self.ask.setPlaceholderText(
            'Ask Nova about this folder — e.g. "what\'s in here?"')
        self.ask.returnPressed.connect(self._ask)
        ask_row.addWidget(self.ask, 1)
        ask_btn = QPushButton("  Ask Nova")
        ask_btn.setProperty("variant", "primary")
        ask_btn.setIcon(icons.icon("sparkle", theme.BLACK, 14))
        ask_btn.setCursor(Qt.PointingHandCursor)
        ask_btn.clicked.connect(self._ask)
        ask_row.addWidget(ask_btn)
        hl.addLayout(ask_row)
        root.addWidget(header)

        # ---------------------------------------------------- file panel
        panel = QWidget()
        style_scoped(panel, "FilesPanel",
                     f"background: {theme.BLACK}; border: 1px solid {theme.BORDER};"
                     "border-radius: 12px;")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(12, 12, 12, 12)
        pl.setSpacing(8)
        # column headers
        col_row = QHBoxLayout()
        col_row.setSpacing(10)
        col_row.setContentsMargins(14, 0, 14, 0)
        col_name = QLabel("Name")
        col_type = QLabel("Type")
        col_size = QLabel("Size")
        col_modified = QLabel("Modified")
        theme.set_style(col_name,
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; border: none; background: transparent;")
        for col in (col_type, col_size, col_modified):
            theme.set_style(col,
            f"color: {theme.GHOST}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1px; border: none; background: transparent;")
        col_row.addWidget(col_name, 1)
        col_type.setFixedWidth(82)
        col_size.setFixedWidth(86)
        col_modified.setFixedWidth(142)
        col_row.addWidget(col_type)
        col_row.addWidget(col_size)
        col_row.addWidget(col_modified)
        pl.addLayout(col_row)
        sep = QFrame()
        sep.setFixedHeight(1)
        theme.set_style(sep, f"background: {theme.BORDER}; border: none;")
        pl.addWidget(sep)
        self.scroll = ScrollArea()
        holder = QWidget()
        self.list_lay = QVBoxLayout(holder)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(6)
        self.list_lay.addStretch(1)
        self.scroll.setWidget(holder)
        pl.addWidget(self.scroll)
        root.addWidget(panel, 1)

        # footer hint
        footer = QLabel("Double-click a folder to open it   •   Use Back / Forward / Up to navigate   •   Search filters live")
        footer.setContentsMargins(24, 0, 24, 10)
        theme.set_style(footer,
                        f"color: {theme.GHOST}; font-size: 11px;"
                        "background: transparent; border: none;")
        root.addWidget(footer)

        # populate drives and initial view
        self._populate_drives()
        self._refresh()

        # one font everywhere: same typeface as the sidebar/technical UI
        theme.apply_unified_font(self)

    # ---------------------------------------------------------- nav btn
    def _nav_btn(self, icon_name: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setFixedSize(30, 30)
        b.setIcon(icons.icon(icon_name, theme.MUTED, 14))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        theme.set_style(b,
            "QPushButton { background: #0c0c0e; border: 1px solid #22232b;"
            "border-radius: 8px; }"
            "QPushButton:hover { background: #141418; border-color: #4b4b52; }"
            "QPushButton:disabled { color: #3f3f46; background: #08080a; }")
        return b

    # ----------------------------------------------------- drive selector
    def _populate_drives(self) -> None:
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        for label, path in _list_drives():
            self.drive_combo.addItem(label, path)
        # select the drive matching the current path
        cur = self._path
        idx = 0
        for i in range(self.drive_combo.count()):
            dpath = self.drive_combo.itemData(i)
            if cur.lower().startswith(dpath.lower()):
                idx = i
                break
        self.drive_combo.setCurrentIndex(idx)
        self.drive_combo.blockSignals(False)

    def _on_drive_changed(self, _idx: int) -> None:
        path = self.drive_combo.currentData()
        if path and os.path.isdir(path):
            self._goto(path)

    # --------------------------------------------------------- navigation
    def _goto(self, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        if os.path.abspath(path) != os.path.abspath(self._path):
            self._back_stack.append(self._path)
            self._forward_stack.clear()
        self._path = os.path.abspath(path)
        self._refresh()
        self._update_nav_state()

    def _go_back(self) -> None:
        if not self._back_stack:
            return
        self._forward_stack.append(self._path)
        self._path = self._back_stack.pop()
        self._refresh()
        self._update_nav_state()

    def _go_forward(self) -> None:
        if not self._forward_stack:
            return
        self._back_stack.append(self._path)
        self._path = self._forward_stack.pop()
        self._refresh()
        self._update_nav_state()

    def _go_up(self) -> None:
        parent = os.path.dirname(self._path)
        if parent and parent != self._path and os.path.isdir(parent):
            self._goto(parent)

    def _update_nav_state(self) -> None:
        self.btn_back.setEnabled(bool(self._back_stack))
        self.btn_forward.setEnabled(bool(self._forward_stack))
        parent = os.path.dirname(self._path)
        self.btn_up.setEnabled(bool(parent) and parent != self._path)

    # ------------------------------------------------------------- render
    def _refresh(self) -> None:
        self.breadcrumb.set_path(self._path)
        # clear list
        for i in reversed(range(self.list_lay.count() - 1)):
            w = self.list_lay.itemAt(i).widget()
            if w:
                w.setParent(None)
                w.hide()
                w.deleteLater()
        query = self.search.text().strip().lower()
        try:
            entries = sorted(
                os.listdir(self._path),
                key=lambda n: (not os.path.isdir(os.path.join(self._path, n)),
                                n.lower()))
        except OSError as exc:
            err = QLabel(f"Cannot read folder: {exc}")
            theme.set_style(err, f"color: {theme.RED_TEXT}; font-size: 12px;")
            self.list_lay.insertWidget(0, err)
            return
        # parent ".." row (always first)
        parent = os.path.dirname(self._path)
        if parent and parent != self._path:
            up = FileRow(parent, True)
            up.name_label.setText(".. (parent folder)")
            up.clicked.connect(lambda: self._go_up())
            self.list_lay.insertWidget(self.list_lay.count() - 1, up)
        # filter entries by search
        shown = 0
        for name in entries[:400]:
            if query and query not in name.lower():
                continue
            full = os.path.join(self._path, name)
            row = FileRow(full, os.path.isdir(full))
            row.clicked.connect(self._open_row(row))
            self.list_lay.insertWidget(self.list_lay.count() - 1, row)
            shown += 1
        if query and shown == 0:
            empty = QLabel(f"No files or folders matching '{query}'")
            theme.set_style(empty,
                f"color: {theme.GHOST}; font-size: 12px; padding: 16px;")
            self.list_lay.insertWidget(0, empty)
        self._update_nav_state()

    def _open_row(self, row: FileRow):
        def handler() -> None:
            if row.is_dir:
                self._goto(row.path)
            else:
                result = desk.open_path(row.path)
                self.status_message.emit(
                    result.get("detail") or result.get("error") or "")
        return handler

    def _ask(self) -> None:
        text = self.ask.text().strip()
        if not text:
            return
        self.ask.clear()
        self.request_llm.emit(f"{text} (current folder: {self._path})")

    def on_shown(self) -> None:
        self._refresh()
