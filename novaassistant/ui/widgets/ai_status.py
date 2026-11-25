"""AI Status widget — live Nova / LLM / STT / TTS provider status.

The pinned desktop widget design is unchanged (it already looks good per
the user's note). This module only improves the management-page PREVIEW
so the card aligns cleanly with the other widget cards on the Widgets
page (requirement #10).
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import theme
from .base import WidgetBase

ROWS = [
    ("nova", "NOVA CORE"),
    ("llm", "LLM"),
    ("stt", "STT"),
    ("tts", "TTS"),
]


class AIStatusWidget(WidgetBase):
    title = "AI STATUS"
    icon_name = "cpu"
    default_size = (260, 210)
    min_size = (190, 150)

    def build_content(self, parent) -> QWidget:
        holder = QWidget()
        self.lay = QVBoxLayout(holder)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(6)
        self._rows: dict[str, tuple[QWidget, QLabel, QLabel, QLabel]] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(5000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

        state_hook = getattr(self.ctx, "orchestrator", None)
        if state_hook is not None:
            state_hook.state_changed.connect(self._on_state)
        self.refresh()
        return holder

    def _on_state(self, _state: str) -> None:
        self.refresh()

    # -------------------------------------------------------------- render
    def _make_row(self, key: str, label: str) -> None:
        w = QWidget()
        # fixed-height row so the management-page preview stays compact and
        # aligned with the other widget cards (requirement #10)
        w.setFixedHeight(34)
        theme.set_style(w,
            f"background: {theme.PANEL_3}; border: 1px solid {theme.BORDER};"
            "border-radius: 8px;")
        rl = QHBoxLayout(w)
        rl.setContentsMargins(10, 4, 10, 4)
        rl.setSpacing(8)
        cap = QLabel(label)
        cap.setMinimumWidth(70)
        theme.set_style(cap,
            f"color: {theme.GHOST}; font-size: 9px; font-family: {theme.FONT_MONO};"
            "letter-spacing: 1.2px; border: none; background: transparent;")
        # state dot
        dot = QLabel()
        dot.setFixedSize(7, 7)
        theme.set_style(dot,
            f"background: {theme.GHOST}; border-radius: 3px; border: none;")
        val = QLabel("—")
        theme.set_style(val,
            f"color: {theme.TEXT_BRIGHT}; font-size: 11px;"
            f"font-family: {theme.FONT_MONO}; border: none; background: transparent;")
        rl.addWidget(dot)
        rl.addWidget(cap)
        rl.addStretch(1)
        rl.addWidget(val, 1)
        self.lay.addWidget(w)
        self._rows[key] = (w, dot, cap, val)

    def refresh(self) -> None:
        # remove stale rows then re-add only the enabled ones, in order
        for key in list(self._rows):
            tup = self._rows.pop(key)
            w = tup[0]
            self.lay.removeWidget(w)
            w.deleteLater()
        try:
            stack = self.ctx.config.active_stack()
        except Exception:
            stack = {}
        state = "ONLINE"
        try:
            orch = self.ctx.orchestrator
            state = (orch.state or "IDLE").upper()
        except Exception:
            pass
        listening = state == "LISTENING"
        values = {
            "nova": (state.replace("IDLE", "ONLINE"),
                     theme.EMERALD if not listening else theme.WHITE),
            "llm": (f"Groq {stack.get('llm_model', '—')}",
                    theme.EMERALD if stack.get("llm_key") else "#F59E0B"),
            "stt": (f"{stack.get('stt_provider', '—')} {stack.get('stt_model', '')}",
                    theme.EMERALD if stack.get("stt_key") and stack.get("stt_enabled")
                    else ("#F59E0B" if not stack.get("stt_enabled") and stack.get("stt_key")
                          else theme.RED_TEXT)),
            "tts": (f"Aura {stack.get('tts_voice', '—')}",
                    theme.EMERALD if stack.get("tts_key") and stack.get("tts_enabled")
                    else ("#F59E0B" if not stack.get("tts_enabled") and stack.get("tts_key")
                          else theme.RED_TEXT)),
        }
        for key, label in ROWS:
            if key == "nova" and not self.settings.get("show_nova", True):
                continue
            if key == "llm" and not self.settings.get("show_llm", True):
                continue
            if key == "stt" and not self.settings.get("show_stt", True):
                continue
            if key == "tts" and not self.settings.get("show_tts", True):
                continue
            self._make_row(key, label)
            _w, dot, _cap, val = self._rows[key]
            text, color = values[key]
            val.setText(text)
            theme.set_style(val,
                f"color: {color}; font-size: 11px; font-family: {theme.FONT_MONO};"
                "border: none; background: transparent;")
            # also color the dot to match
            theme.set_style(dot,
                f"background: {color}; border-radius: 3px; border: none;")

    def shutdown(self) -> None:
        self._timer.stop()

    # ------------------------------------------------------------ settings
    def build_settings_form(self, parent) -> QWidget:
        from ..widgets_common import NovaCheckBox
        form = QWidget(parent)
        lay = QVBoxLayout(form)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.checks = {}
        for key, label in (("show_nova", "NOVA core state"),
                           ("show_llm", "LLM (Groq)"),
                           ("show_stt", "STT (Whisper / Nova-3)"),
                           ("show_tts", "TTS (Deepgram Aura)")):
            chk = NovaCheckBox(label)
            chk.setChecked(bool(self.settings.get(key, True)))
            self.checks[key] = chk
            lay.addWidget(chk)
        lay.addStretch(1)

        def apply() -> None:
            for key, chk in self.checks.items():
                self.settings[key] = chk.isChecked()

        form.apply = apply  # type: ignore[attr-defined]
        return form

