"""Task / Activity widget — the current AI operation + recent audit rows."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ... import theme
from .base import WidgetBase


class ActivityWidget(WidgetBase):
    title = "AI ACTIVITY"
    icon_name = "activity"
    default_size = (280, 230)
    min_size = (200, 160)

    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.op_cap = self._caption("CURRENT OPERATION")
        self.op_lbl = QLabel("Idle — standing by")
        self.op_lbl.setWordWrap(True)
        theme.set_style(self.op_lbl, 
            f"color: {theme.EMERALD}; font-size: 12px; font-weight: 600;"
            "border: none; background: transparent;")
        lay.addWidget(self.op_cap)
        lay.addWidget(self.op_lbl)

        self.steps_lbl = QLabel("")
        self.steps_lbl.setWordWrap(True)
        theme.set_style(self.steps_lbl, 
            f"color: {theme.MUTED}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "border: none; background: transparent;")
        lay.addWidget(self.steps_lbl)

        self.hist_cap = self._caption("RECENT")
        lay.addWidget(self.hist_cap)
        self.hist_lay = QVBoxLayout()
        self.hist_lay.setContentsMargins(0, 0, 0, 0)
        self.hist_lay.setSpacing(4)
        lay.addLayout(self.hist_lay, 1)

        self._steps: list[dict] = []
        orch = getattr(self.ctx, "orchestrator", None)
        if orch is not None:
            orch.state_changed.connect(self._on_state)
            orch.steps_changed.connect(self._on_steps)
        listener = getattr(self.ctx, "activity", None)
        if listener is not None:
            self._listener = self._on_activity
            listener.add_listener(self._listener)
        # debounce rapid activity-log bursts
        self._timer = QTimer(self)
        self._timer.setInterval(120)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._refresh_history)
        self.refresh()
        return holder

    # -------------------------------------------------------------- events
    def _on_state(self, state: str) -> None:
        labels = {
            "IDLE": ("Idle — standing by", theme.EMERALD),
            "LISTENING": ("Listening for your voice…", theme.WHITE),
            "THINKING": ("Thinking through the request…", "#c4b5fd"),
            "EXECUTING": ("Executing tools…", "#c4b5fd"),
            "RESPONDING": ("Composing response…", theme.WHITE),
            "SPEAKING": ("Speaking reply…", theme.EMERALD),
        }
        text, color = labels.get(state, (state.title(), theme.TEXT))
        self.op_lbl.setText(text)
        theme.set_style(self.op_lbl, 
            f"color: {color}; font-size: 12px; font-weight: 600;"
            "border: none; background: transparent;")

    def _on_steps(self, steps: list) -> None:
        self._steps = steps or []
        lines = []
        for s in self._steps[:4]:
            mark = {"done": "✓", "active": "●"}.get(s.get("status"), "○")
            lines.append(f"{mark} {s.get('label', '')}")
        self.steps_lbl.setText("\n".join(lines))

    def _on_activity(self, _entry=None) -> None:
        self._timer.start()

    # -------------------------------------------------------------- render
    def _refresh_history(self) -> None:
        while self.hist_lay.count():
            item = self.hist_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        try:
            entries = self.ctx.activity.entries(50)
        except Exception:
            entries = []
        n = int(self.settings.get("history_rows", 3))
        for entry in reversed(entries[:n]):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(6)
            ok = entry.get("status", "ok") == "ok"
            mark = QLabel("[ok]" if ok else "[err]")
            theme.set_style(mark, 
                f"color: {'#d4d4d8' if ok else theme.RED_TEXT}; font-size: 9px;"
                f"font-family: {theme.FONT_MONO}; border: none;"
                "background: transparent;")
            msg = QLabel(str(entry.get("message", ""))[:38])
            theme.set_style(msg, 
                f"color: {theme.TEXT}; font-size: 10px; border: none;"
                "background: transparent;")
            rl.addWidget(mark)
            rl.addWidget(msg, 1)
            self.hist_lay.addWidget(row)
        if not entries:
            self.hist_lay.addWidget(self._empty("No activity yet."))

    def refresh(self) -> None:
        try:
            state = (self.ctx.orchestrator.state or "IDLE").upper()
        except Exception:
            state = "IDLE"
        self._on_state(state)
        self._refresh_history()

    def shutdown(self) -> None:
        self._timer.stop()
        listener = getattr(self.ctx, "activity", None)
        if listener is not None and getattr(self, "_listener", None):
            try:
                listener.remove_listener(self._listener)
            except Exception:
                pass

    # ------------------------------------------------------------ settings
    def build_settings_form(self, parent) -> QWidget:
        from PySide6.QtWidgets import QSpinBox
        form = QWidget(parent)
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        row = QHBoxLayout()
        row.addWidget(QLabel("History rows"))
        self.spin = QSpinBox()
        self.spin.setRange(0, 6)
        self.spin.setValue(int(self.settings.get("history_rows", 3)))
        row.addWidget(self.spin, 1)
        lay.addLayout(row)
        lay.addStretch(1)

        def apply() -> None:
            self.settings["history_rows"] = self.spin.value()

        form.apply = apply  # type: ignore[attr-defined]
        return form
