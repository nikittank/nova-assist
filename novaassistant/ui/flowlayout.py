"""FlowLayout — a wrapping horizontal layout for responsive pages.

Children flow left-to-right and wrap to the next line when the parent
narrows, instead of overlapping or clipping. Used for stat tile rows,
chip rows and form rows that must stay usable at small window sizes.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin: int = 0, spacing: int = 10):
        super().__init__(parent)
        self.setContentsMargins(margin, margin, margin, margin)
        self._spacing = spacing
        self._items: list[QLayoutItem] = []

    # ------------------------------------------------------------- qt api
    def addItem(self, item) -> None:  # noqa: N802 (Qt naming)
        self._items.append(item)

    def insertWidget(self, index: int, widget: QWidget) -> None:
        widget.setParent(self.parentWidget())
        self._items.insert(max(0, min(index, len(self._items))),
                           QWidgetItemCompat(widget))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def clear(self) -> None:
        while self._items:
            item = self._items.pop()
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def setSpacing(self, value: int) -> None:
        self._spacing = value

    def spacing(self) -> int:
        return self._spacing

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    # ------------------------------------------------------------ layout
    def _do_layout(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        effective = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y = effective.x(), effective.y()
        line_height = 0
        for item in self._items:
            # query the widget's hint FRESH — QWidgetItem caches the hint
            # computed at first layout, which goes stale after setText()
            # and makes wrapped rows/tiles clip.
            wdg = item.widget()
            if wdg is not None:
                hint = wdg.sizeHint()
                # Fixed-size widget cards can report a stale sizeHint after
                # their preview is rebuilt; use the actual dimensions so
                # row and column gaps remain identical.
                if wdg.width() > 0:
                    hint.setWidth(max(hint.width(), wdg.width()))
                if wdg.height() > 0:
                    hint.setHeight(max(hint.height(), wdg.height()))
            else:
                hint = item.sizeHint()
            w, h = hint.width(), hint.height()
            nxt = x + w + self._spacing
            if nxt - self._spacing > effective.right() + 1 and line_height > 0:
                x = effective.x()
                y += line_height + self._spacing
                line_height = 0
                nxt = x + w + self._spacing
            if not test:
                item.setGeometry(QRect(QPoint(x, y), QSize(w, h)))
            x = nxt
            line_height = max(line_height, h)
        return y + line_height - rect.y() + m.bottom()


# QWidgets are also QLayoutItems in PySide6, but wrap explicitly for safety
# across versions (insertWidget above needs a QLayoutItem).
from PySide6.QtWidgets import QWidgetItem as QWidgetItemCompat  # noqa: E402
