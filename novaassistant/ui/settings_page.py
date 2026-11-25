"""Settings page — professional provider cards: LLM / STT / TTS first,
then Voice, Appearance, Overlay Desktop, Safety.

Structure (requirement #2, #11, #12):
  * LLM card  — Groq keys (multi), model selector (click-to-change, scroll-
                safe), temperature, max tokens, reasoning, test connection.
                LLM is ALWAYS enabled — no on/off switch (it is the core
                reasoning engine).
  * STT card  — Enable/Disable toggle, active engine selector; Groq Whisper
                block (own key mode, model, test) and Deepgram Nova block
                (key, model, test).
  * TTS card  — Deepgram only: Enable/Disable toggle, key manager, Aura
                voice, volume, speaking settings, test voice.
All dropdowns ignore the mouse wheel: the value changes ONLY when the user
opens the popup and explicitly clicks an option.
Headings and labels use clean typography — no decorative slashes (#12).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSlider, QStackedWidget, QVBoxLayout, QWidget, QSizePolicy,
)

from .. import icons, theme
from ..providers import deepgram as dg
from ..providers import groq
from .settings_providers import AddKeyRow, KeyRow
from .widgets_common import NoScrollCombo, NovaCheckBox, ScrollArea, TagPill


# ------------------------------------------------------------------ helpers
def _section(title: str, chip: str = "", chip_color: str = theme.MUTED) -> tuple[QWidget, QVBoxLayout]:
    card = QWidget()
    card.setObjectName("SettingsSection")
    theme.set_style(
        card,
        "QWidget#SettingsSection { background: #0d0d0f;"
        f" border: 1px solid {theme.BORDER}; border-radius: 12px; }}")
    card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(20, 18, 20, 18)
    lay.setSpacing(24)
    lay.setAlignment(Qt.AlignTop)
    head = QHBoxLayout()
    head.setSpacing(10)
    h = QLabel(title)
    theme.set_style(h,
                    "color: #e4e4e7; font-size: 13px; font-weight: 600;"
                    "border: none; background: transparent;")
    head.addWidget(h)
    head.addStretch(1)
    if chip:
        c = TagPill(chip)
        c.setFixedHeight(26)
        c.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        theme.set_style(
            c,
            f"color: {chip_color}; font-size: 10px; font-family: {theme.FONT_MONO};"
            "font-weight: 700; letter-spacing: 0.8px; background: #101116;"
            f" border: 1px solid {theme.BORDER}; border-radius: 4px; padding: 2px 8px;")
        head.addWidget(c)
    lay.addLayout(head)
    return card, lay


# consistent label width so every form row aligns (requirement #11)
LABEL_W = 200
HINT_W = 170


def _form_row(label: str, widget: QWidget, hint: str = "") -> QHBoxLayout:
    row = QVBoxLayout()
    row.setSpacing(8)
    control_row = QHBoxLayout()
    control_row.setSpacing(8)
    lbl = QLabel(label)
    lbl.setFixedWidth(LABEL_W)
    lbl.setWordWrap(False)
    theme.set_style(lbl,
                    "color: #d4d4d8; font-size: 12px; font-weight: 500;"
                    "border: none; background: transparent;")
    control_row.addWidget(lbl)
    control_row.addWidget(widget, 1)
    row.addLayout(control_row)
    if hint:
        h = QLabel(hint)
        h.setWordWrap(True)
        h.setContentsMargins(LABEL_W + 12, 0, 0, 0)
        theme.set_style(h,
                        f"color: {theme.GHOST}; font-size: 10px;"
                        "border: none; background: transparent;")
        row.addWidget(h)
    return row


def _toggle_row(label: str, checkbox: NovaCheckBox, hint: str = "") -> QHBoxLayout:
    """A consistent two-line toggle row for STT/TTS settings."""
    row = QVBoxLayout()
    row.setSpacing(8)
    lbl = QLabel(label)
    lbl.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    lbl.setWordWrap(False)
    theme.set_style(lbl,
                    "color: #d4d4d8; font-size: 12px; font-weight: 500;"
                    "border: none; background: transparent;")
    row.addWidget(lbl)
    detail_row = QHBoxLayout()
    detail_row.setSpacing(10)
    detail_row.setContentsMargins(0, 0, 0, 0)
    detail_row.addWidget(checkbox)
    if hint:
        h = QLabel(hint)
        h.setWordWrap(False)
        h.setMinimumWidth(280)
        h.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        theme.set_style(h,
                        f"color: {theme.GHOST}; font-size: 10px;"
                        "border: none; background: transparent;")
        detail_row.addWidget(h)
    detail_row.addStretch(1)
    row.addLayout(detail_row)
    return row


def _desc(text: str) -> QLabel:
    d = QLabel(text)
    d.setWordWrap(True)
    theme.set_style(d,
                    f"color: {theme.GHOST}; font-size: 11px;"
                    "border: none; background: transparent;")
    return d


def _sub_head(text: str) -> QLabel:
    lbl = QLabel(text)
    theme.set_style(
        lbl,
        f"color: {theme.MUTED}; font-size: 10px; font-weight: 700;"
        f" font-family: {theme.FONT_MONO}; letter-spacing: 1.4px;"
        "border: none; background: transparent;")
    return lbl


def _mono_input() -> QLineEdit:
    w = QLineEdit()
    theme.set_style(
        w,
        "QLineEdit { background: #0c0c0e; border: 1px solid #22232b;"
        " border-radius: 8px; padding: 6px 10px; font-size: 12px;"
        f" font-family: {theme.FONT_MONO}; color: {theme.TEXT_BRIGHT}; }}")
    return w


def _combo() -> NoScrollCombo:
    combo = NoScrollCombo()
    theme.set_style(
        combo,
        "QComboBox { background: #0c0c0e; border: 1px solid #22232b;"
        " border-radius: 8px; padding: 6px 10px; font-size: 12px;"
        f" color: {theme.TEXT_BRIGHT}; }}"
        f"QComboBox QAbstractItemView {{ background: #0c0c0e;"
        f" border: 1px solid {theme.BORDER_2}; selection-background-color: #1f1f23; }}")
    combo.setCursor(Qt.PointingHandCursor)
    return combo


def _set_pill(pill: QLabel, state: str, msg: str = "") -> None:
    """Status pill states: idle / testing / ok / err."""
    pill.setFixedHeight(26)
    pill.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    styles = {
        "idle": (theme.GHOST, "#101116", theme.BORDER),
        "testing": ("#F59E0B", "rgba(245,158,11,0.10)",
                    "rgba(245,158,11,0.35)"),
        "ok": (theme.EMERALD, "rgba(16,185,129,0.10)",
               "rgba(16,185,129,0.4)"),
        "err": (theme.RED_TEXT, "rgba(239,68,68,0.10)",
                "rgba(239,68,68,0.35)"),
    }
    color, bg, bd = styles.get(state, styles["idle"])
    pill.setText(msg or "—")
    theme.set_style(
        pill,
        f"color: {color}; font-size: 10px; font-family: {theme.FONT_MONO};"
        f"background: {bg}; border: 1px solid {bd};"
        "border-radius: 4px; padding: 3px 10px;")


def _status_dot(ok: bool) -> QLabel:
    dot = QLabel()
    dot.setFixedSize(8, 8)
    theme.set_style(dot,
        f"background: {theme.EMERALD if ok else '#F59E0B'}; border-radius: 4px;")
    dot.setToolTip("Provider ready" if ok else "API key missing")
    return dot


def _short(key: str) -> str:
    return (key[:5] + "…" + key[-4:]) if len(key) > 12 else (key or "empty")


class SettingsPage(QWidget):
    status_message = Signal(str, bool)
    overlay_toggled = Signal(bool)
    settings_saved = Signal()
    font_size_changed = Signal(int)

    FONT_CHOICES = [(14, "Default — 14 px"), (15, "Large — 15 px"),
                    (16, "Huge — 16 px")]

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self._key_rows: list[KeyRow] = []
        self._loading = True

        outer_root = QVBoxLayout(self)
        outer_root.setContentsMargins(0, 0, 0, 0)

        # Keep the Settings header fixed while only the tab content scrolls.
        header_host = QWidget()
        header_root = QVBoxLayout(header_host)
        header_root.setContentsMargins(32, 24, 32, 20)
        outer_root.addWidget(header_host)

        content_host = QWidget()
        content_host.setMinimumWidth(0)
        root = QVBoxLayout(content_host)
        root.setContentsMargins(32, 0, 32, 32)
        root.setSpacing(28)
        outer_root.addWidget(content_host, 1)

        # ------------------------------------------------------- header
        head = QVBoxLayout()
        head.setSpacing(3)
        title = QLabel("Settings")
        theme.set_style(title,
                        f"color: {theme.WHITE}; font-size: 20px; font-weight: 700;"
                        "border: none; background: transparent;")
        sub = QLabel("Configure model engines, voice synthesis, appearance and "
                     "security guardrails")
        sub.setWordWrap(False)
        sub.setMinimumHeight(18)
        sub.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        theme.set_style(sub,
                        f"color: {theme.GHOST}; font-size: 12px;"
                        "border: none; background: transparent;")
        head.addWidget(title)
        head.addWidget(sub)
        head_row = QHBoxLayout()
        head_row.addLayout(head)
        head_row.addStretch(1)
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setProperty("variant", "ghost")
        reset_btn.setCursor(Qt.PointingHandCursor)
        reset_btn.clicked.connect(self._reset)
        save_btn = QPushButton("Save Changes")
        save_btn.setProperty("variant", "primary")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        head_row.addWidget(reset_btn)
        head_row.addWidget(save_btn)
        header_root.addLayout(head_row)

        # Keep the settings page compact and group related controls so long
        # provider forms do not become one oversized scrolling column.
        tabs_host = QWidget()
        tabs_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        tabs_host_layout = QHBoxLayout(tabs_host)
        tabs_host_layout.setContentsMargins(0, 0, 0, 0)
        tabs_host_layout.setSpacing(24)

        sidebar = QVBoxLayout()
        sidebar.setSpacing(6)
        sidebar.setContentsMargins(0, 0, 0, 0)
        stack = QStackedWidget()
        stack.setStyleSheet(
            "QStackedWidget { border: none; background: #000000; }")
        tab_buttons = []
        tab_group = QButtonGroup(tabs_host)
        tab_group.setExclusive(True)
        tab_names = ("LLM", "STT", "TTS", "Other")
        for index, tab_name in enumerate(tab_names):
            button = QPushButton(tab_name)
            button.setCheckable(True)
            button.setFixedSize(140, 48)
            tab_group.addButton(button, index)
            button.setStyleSheet(
                "QPushButton { background: #0d0d0f; color: #8b8b95; "
                "border: 1px solid #1a1a1f; border-radius: 6px; "
                "text-align: left; padding-left: 18px; font-size: 12px; }"
                "QPushButton:hover { color: #ffffff; background: #141418; }"
                "QPushButton:checked { background: #ffffff; color: #000000; "
                "border-left: 3px solid #ffffff; }")
            button.clicked.connect(lambda checked, i=index: stack.setCurrentIndex(i))
            sidebar.addWidget(button)
            tab_buttons.append(button)
        sidebar.addStretch(1)
        tabs_host_layout.addLayout(sidebar)
        scroll = ScrollArea()
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollBar:vertical { width: 0px; background: transparent; }"
            "QScrollBar:horizontal { height: 0px; background: transparent; }"
            "QScrollBar::handle:vertical { min-height: 0px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, "
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical "
            "{ height: 0px; background: transparent; }")
        scroll.setWidget(stack)
        scroll.verticalScrollBar().hide()
        scroll.horizontalScrollBar().hide()
        tabs_host_layout.addWidget(scroll, 1)
        tab_layouts = {}
        for tab_name in tab_names:
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(24)
            page_layout.setAlignment(Qt.AlignTop)
            stack.addWidget(page)
            tab_layouts[tab_name] = page_layout
        tab_buttons[0].setChecked(True)
        def update_scrollbar(index: int) -> None:
            # Every tab may scroll, but only when its content is taller than
            # the available viewport.
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.verticalScrollBar().setEnabled(True)

        stack.currentChanged.connect(update_scrollbar)
        update_scrollbar(0)
        root.addWidget(tabs_host, 1)

        # =================================================== LLM — GROQ
        llm_card, llm = _section("LLM Language Model", "PROVIDER GROQ",
                                 theme.WHITE)
        # LLM is ALWAYS enabled — no on/off switch (it is the core reasoning
        # engine, requirement #2). Show a permanent 'Always enabled' badge
        # so the user understands there is no toggle to find.
        always_on = TagPill("ALWAYS ON")
        always_on.setFixedHeight(26)
        always_on.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        theme.set_style(
            always_on,
            f"color: {theme.EMERALD}; font-size: 9px; font-family: {theme.FONT_MONO};"
            "font-weight: 700; letter-spacing: 0.8px; background: rgba(16,185,129,0.10);"
            f" border: 1px solid rgba(16,185,129,0.4); border-radius: 4px; padding: 2px 8px;")
        llm_row = QHBoxLayout()
        llm_row.setSpacing(8)
        llm_row.addWidget(always_on)
        llm_row.addStretch(1)
        llm.addLayout(llm_row)
        llm.addWidget(_desc(
            "Groq API keys for chat reasoning. Add multiple keys with custom "
            "names, enable/disable, test them, and pick the active one. The "
            "LLM is always enabled — it is the core reasoning engine."))
        self.groq_keys_box = QVBoxLayout()
        self.groq_keys_box.setSpacing(8)
        llm.addLayout(self.groq_keys_box)
        self.groq_add = AddKeyRow("gsk_…")
        self.groq_add.add_requested.connect(self._add_groq_key)
        llm.addWidget(self.groq_add)

        self.llm_model = _combo()
        for m in groq.LLM_MODELS:
            self.llm_model.addItem(m)
        self.llm_model.setMaxVisibleItems(12)
        llm.addLayout(_form_row("Model", self.llm_model,
                                "Click the selector and choose explicitly — "
                                "scrolling never changes the model"))
        self.llm_active_chip = TagPill("Active model — ")
        self.llm_active_chip.setFixedHeight(26)
        self.llm_active_chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        llm.addWidget(self.llm_active_chip)

        self.temperature = _mono_input()
        self.max_tokens = _mono_input()
        self.reasoning = _combo()
        for r in ("low", "medium", "high"):
            self.reasoning.addItem(r)
        self.memory = _mono_input()
        llm.addLayout(_form_row("Temperature (0–2)", self.temperature))
        llm.addLayout(_form_row("Max completion tokens", self.max_tokens))
        llm.addLayout(_form_row("Reasoning effort", self.reasoning))
        llm.addLayout(_form_row("Conversation memory (messages)", self.memory))

        trow = QHBoxLayout()
        self.llm_test_btn = QPushButton("Test connection")
        self.llm_test_btn.setProperty("variant", "ghost")
        self.llm_test_btn.setCursor(Qt.PointingHandCursor)
        self.llm_test_btn.clicked.connect(self._test_llm)
        self.llm_test_status = QLabel()
        _set_pill(self.llm_test_status, "idle")
        trow.addWidget(self.llm_test_btn)
        trow.addSpacing(8)
        trow.addWidget(self.llm_test_status, 1)
        llm.addLayout(trow)
        tab_layouts["LLM"].addWidget(llm_card)

        # =================================================== STT
        stt_card, stt = _section("STT Speech to Text", "GROQ + DEEPGRAM",
                                 theme.WHITE)
        # STT Enable/Disable toggle (requirement #2)
        self.stt_enabled = NovaCheckBox("")
        self.stt_enabled.setToolTip(
            "When disabled, microphone voice input will not activate")
        stt.addLayout(_toggle_row(
            "Enable speech recognition (STT)", self.stt_enabled,
            "When off, mic input never reaches the LLM"))
        stt.addWidget(_desc(
            "Pick the engine Nova uses to transcribe your voice. Both "
            "providers are configured independently below."))
        self.stt_provider = _combo()
        self.stt_provider.addItem("Groq Whisper Large V3 Turbo (active engine)",
                                  "groq")
        self.stt_provider.addItem("Deepgram Nova-3 (active engine)", "deepgram")
        stt.addLayout(_form_row("Active STT engine", self.stt_provider))
        self.stt_provider_status = TagPill("ENGINE —")
        stt.addWidget(self.stt_provider_status)

        # ---- Groq Whisper block
        stt.addWidget(_sub_head("GROQ WHISPER"))
        self.stt_key_mode = _combo()
        self.stt_key_mode.addItem("Reuse the active LLM key", "llm")
        self.stt_key_mode.addItem("Use a separate key", "custom")
        self.stt_key_mode.currentIndexChanged.connect(self._groq_stt_mode_changed)
        stt.addLayout(_form_row("Groq STT key", self.stt_key_mode))
        self.stt_key_combo = _combo()
        stt.addLayout(_form_row("Separate STT key", self.stt_key_combo))
        self.stt_model_groq = _combo()
        for m in groq.STT_MODELS:
            self.stt_model_groq.addItem(m)
        stt.addLayout(_form_row("Whisper model", self.stt_model_groq))
        gtrow = QHBoxLayout()
        gtrow.setSpacing(8)
        self.groq_stt_test_btn = QPushButton("Test Groq STT")
        self.groq_stt_test_btn.setProperty("variant", "ghost")
        self.groq_stt_test_btn.setCursor(Qt.PointingHandCursor)
        self.groq_stt_test_btn.clicked.connect(self._test_groq_stt)
        self.groq_stt_test_status = QLabel()
        _set_pill(self.groq_stt_test_status, "idle")
        gtrow.addWidget(self.groq_stt_test_btn)
        gtrow.addSpacing(8)
        gtrow.addWidget(self.groq_stt_test_status, 1)
        stt.addLayout(gtrow)

        sep1 = QFrame()
        sep1.setFixedHeight(1)
        theme.set_style(sep1, "background: #141418; border: none;")
        stt.addWidget(sep1)

        # ---- Deepgram Nova block
        stt.addWidget(_sub_head("DEEPGRAM NOVA-3"))
        self.dg_stt_key_combo = _combo()
        stt.addLayout(_form_row("Deepgram STT key", self.dg_stt_key_combo,
                                "Keys are managed in the TTS card below"))
        self.stt_model_dg = _combo()
        for m in dg.STT_MODELS:
            self.stt_model_dg.addItem(m)
        stt.addLayout(_form_row("Nova model", self.stt_model_dg))
        self.dg_lang = _combo()
        for code, label in (("multi", "multi (auto language)"), ("en", "en"),
                            ("en-US", "en-US"), ("en-GB", "en-GB"), ("hi", "hi")):
            self.dg_lang.addItem(label, code)
        stt.addLayout(_form_row("Language", self.dg_lang))
        dtrow = QHBoxLayout()
        dtrow.setSpacing(8)
        self.dg_stt_test_btn = QPushButton("Test Deepgram STT")
        self.dg_stt_test_btn.setProperty("variant", "ghost")
        self.dg_stt_test_btn.setCursor(Qt.PointingHandCursor)
        self.dg_stt_test_btn.clicked.connect(self._test_dg_stt)
        self.dg_stt_test_status = QLabel()
        _set_pill(self.dg_stt_test_status, "idle")
        dtrow.addWidget(self.dg_stt_test_btn)
        dtrow.addSpacing(8)
        dtrow.addWidget(self.dg_stt_test_status, 1)
        stt.addLayout(dtrow)
        tab_layouts["STT"].addWidget(stt_card)

        # =================================================== TTS — DEEPGRAM
        tts_card, tts = _section("TTS Text to Speech", "PROVIDER DEEPGRAM",
                                 theme.WHITE)
        # TTS Enable/Disable toggle (requirement #2)
        self.tts_enabled = NovaCheckBox("")
        self.tts_enabled.setToolTip(
            "When disabled, AI responses show as text but no audio plays")
        tts.addLayout(_toggle_row(
            "Enable speech synthesis (TTS)", self.tts_enabled,
            "When off, Nova replies in text only"))
        tts.addWidget(_desc(
            "Nova speaks with Deepgram Aura voices. This section is fully "
            "separate from the LLM and STT providers, with its own key "
            "selection, voice, volume and speaking settings."))
        tts.addWidget(_sub_head("DEEPGRAM API KEYS"))
        self.dg_keys_box = QVBoxLayout()
        self.dg_keys_box.setSpacing(8)
        tts.addLayout(self.dg_keys_box)
        self.dg_add = AddKeyRow("Deepgram API key…")
        self.dg_add.add_requested.connect(self._add_dg_key)
        tts.addWidget(self.dg_add)
        self.tts_key_combo = _combo()
        tts.addLayout(_form_row("Active TTS key", self.tts_key_combo))
        self.tts_voice = _combo()
        for v in dg.TTS_VOICES:
            self.tts_voice.addItem(dg.VOICE_LABELS.get(v, v), v)
        tts.addLayout(_form_row("Aura voice", self.tts_voice))

        vol_row = QHBoxLayout()
        vol_row.setSpacing(12)
        vol_lbl = QLabel("Volume")
        vol_lbl.setMinimumWidth(LABEL_W)
        vol_lbl.setMaximumWidth(LABEL_W + 40)
        theme.set_style(vol_lbl,
                        "color: #d4d4d8; font-size: 12px; font-weight: 500;"
                        "border: none; background: transparent;")
        self.tts_volume = QSlider(Qt.Horizontal)
        self.tts_volume.setRange(0, 100)
        self.tts_volume.setValue(90)
        self.tts_volume.setCursor(Qt.PointingHandCursor)
        self.tts_volume_label = QLabel("90%")
        theme.set_style(self.tts_volume_label,
                        f"color: {theme.TEXT_BRIGHT}; font-size: 11px;"
                        f"font-family: {theme.FONT_MONO}; border: none;"
                        "background: transparent;")
        self.tts_volume.valueChanged.connect(
            lambda v: self.tts_volume_label.setText(f"{v}%"))
        self.tts_volume.sliderReleased.connect(self._apply_volume)
        vol_row.addWidget(vol_lbl)
        vol_row.addWidget(self.tts_volume, 1)
        vol_row.addWidget(self.tts_volume_label)
        tts.addLayout(vol_row)

        self.speak_replies = NovaCheckBox("Speak AI replies aloud (Deepgram Aura)")
        self.speak_reminders = NovaCheckBox("Speak reminders when they fire")
        tts.addWidget(self.speak_replies)
        tts.addWidget(self.speak_reminders)

        vtrow = QHBoxLayout()
        vtrow.setSpacing(8)
        self.tts_test_btn = QPushButton("Test voice")
        self.tts_test_btn.setProperty("variant", "ghost")
        self.tts_test_btn.setCursor(Qt.PointingHandCursor)
        self.tts_test_btn.clicked.connect(self._test_tts)
        self.tts_test_status = QLabel()
        _set_pill(self.tts_test_status, "idle")
        vtrow.addWidget(self.tts_test_btn)
        vtrow.addSpacing(8)
        vtrow.addWidget(self.tts_test_status, 1)
        tts.addLayout(vtrow)
        tab_layouts["TTS"].addWidget(tts_card)

        # =================================================== VOICE
        voice_card, voice = _section("Voice Input")
        # Master mic enable/disable toggle (requirement #3)
        self.mic_enabled = NovaCheckBox("")
        self.mic_enabled.setToolTip(
            "Master switch for microphone access")
        voice.addLayout(_toggle_row(
            "Enable microphone", self.mic_enabled,
            "When off, no mic capture happens at all"))
        self.mic_mode = _combo()
        self.mic_mode.addItem("Off (no listening)", "off")
        self.mic_mode.addItem("Continuous (hands-free VAD)", "continuous")
        self.mic_mode.addItem("Push to talk (Ctrl+Space)", "push_to_talk")
        voice.addLayout(_form_row("Microphone mode", self.mic_mode,
                                  "Off no VAD, Continuous uses VAD, PTT no continuous VAD"))
        self.vad_slider = QSlider(Qt.Horizontal)
        self.vad_slider.setRange(50, 100)
        self.vad_slider.setValue(82)
        self.vad_slider.setCursor(Qt.PointingHandCursor)
        self.vad_label = QLabel("82")
        theme.set_style(self.vad_label,
                        f"color: {theme.TEXT_BRIGHT}; font-size: 11px;"
                        f"font-family: {theme.FONT_MONO}; border: none;"
                        "background: transparent;")
        self.vad_slider.valueChanged.connect(
            lambda v: self.vad_label.setText(str(v)))
        self.vad_slider.sliderReleased.connect(self._apply_vad)
        voice.addLayout(_form_row("VAD sensitivity", self.vad_slider,
                                  "Higher = stops sooner after you speak"))
        self.auto_listen = NovaCheckBox(
            "Start listening automatically when Nova launches")
        voice.addWidget(self.auto_listen)
        tab_layouts["Other"].addWidget(voice_card)

        # =================================================== APPEARANCE
        app_card, app = _section("Appearance")
        self.font_combo = _combo()
        for px, label in self.FONT_CHOICES:
            self.font_combo.addItem(label, px)
        self.font_combo.currentIndexChanged.connect(self._font_changed)
        app.addLayout(_form_row("Font size", self.font_combo,
                                "Applies instantly — the layout stays "
                                "responsive at every size"))
        app.addWidget(_desc(
            "Scales every font in Nova uniformly. Nothing overlaps: pages "
            "scroll and text wraps at any size."))
        tab_layouts["Other"].addWidget(app_card)

        # =================================================== OVERLAY & DESKTOP
        desk_card, desk = _section("Overlay Desktop")
        self.overlay_enabled = NovaCheckBox(
            "Enable the always-on-top AI overlay (visible above every app)")
        self.overlay_enabled.toggled.connect(self.overlay_toggled.emit)
        desk.addWidget(self.overlay_enabled)
        self.start_minimized = NovaCheckBox("Start minimized to tray (background mode)")
        self.close_to_tray = NovaCheckBox("Closing the window keeps Nova in the tray")
        self.start_with_windows = NovaCheckBox("Start with Windows (registry Run key)")
        for w in (self.start_minimized, self.close_to_tray, self.start_with_windows):
            desk.addWidget(w)
        tab_layouts["Other"].addWidget(desk_card)

        # =================================================== SAFETY
        safe_card, safe = _section("Safety")
        self.confirmation = _combo()
        self.confirmation.addItem("strict (Prompt before file writes / shell)", "strict")
        self.confirmation.addItem("moderate (Prompt on high-risk commands)", "moderate")
        self.confirmation.addItem("permissive (Fully autonomous)", "permissive")
        safe.addLayout(_form_row("Confirmation level", self.confirmation))
        cache_row = QHBoxLayout()
        cache_info = QLabel("Clear conversation history buffer without affecting "
                            "notes or reminders.")
        cache_info.setWordWrap(True)
        theme.set_style(cache_info,
                        f"color: {theme.GHOST}; font-size: 12px;"
                        "border: none; background: transparent;")
        cache_btn = QPushButton("Clear Local Conversation Cache")
        cache_btn.setProperty("variant", "ghost")
        cache_btn.setCursor(Qt.PointingHandCursor)
        cache_btn.clicked.connect(self._clear_cache)
        cache_row.addWidget(cache_info, 1)
        cache_row.addWidget(cache_btn)
        safe.addLayout(cache_row)
        tab_layouts["Other"].addWidget(safe_card)

        self._loading = False
        self.load_from_config()
        # live-apply the voice toggles so the mic behavior reflects the new
        # state instantly (requirement #2, #3, #4)
        self.mic_enabled.toggled.connect(self._live_apply_voice)
        self.stt_enabled.toggled.connect(self._live_apply_voice)
        self.tts_enabled.toggled.connect(self._live_apply_voice)
        self.mic_mode.currentIndexChanged.connect(self._live_apply_voice)

        # one font everywhere: same typeface as the sidebar/technical UI
        theme.apply_unified_font(self)

    # ------------------------------------------------------------ helpers
    def _groq_stt_mode_changed(self) -> None:
        mode = self.stt_key_mode.currentData()
        self.stt_key_combo.setEnabled(mode == "custom")

    def _live_apply_voice(self) -> None:
        """When STT/TTS/mic/mode toggles change in Settings, apply them to
        the orchestrator immediately so the mic behavior reflects the new
        state without requiring a Save (requirement #4: 'Make sure changing
        the mode immediately changes the actual microphone behavior')."""
        if self._loading:
            return
        cfg = self.ctx.config
        cfg.set("voice.mic_enabled", self.mic_enabled.isChecked(), save=False)
        cfg.set("voice.stt_enabled", self.stt_enabled.isChecked(), save=False)
        cfg.set("voice.tts_enabled", self.tts_enabled.isChecked(), save=False)
        cfg.set("voice.mic_mode",
                self.mic_mode.currentData() or "continuous", save=False)
        cfg.save()
        try:
            self.ctx.orchestrator.apply_audio_settings()
        except Exception:
            pass
        # refresh the conversation header three-dot cluster
        try:
            self.ctx.widget_manager.data_changed.emit()
        except Exception:
            pass

    def _font_changed(self, _idx: int) -> None:
        if self._loading:
            return
        px = self.font_combo.currentData()
        if px:
            self.ctx.config.set("ui.font_size", int(px))
            self.font_size_changed.emit(int(px))
            self.status_message.emit(f"Font size set to {px}px — applied live", True)

    def _apply_volume(self) -> None:
        self.ctx.config.set("voice.tts_volume", int(self.tts_volume.value()))
        self.ctx.orchestrator.apply_audio_settings()

    def _apply_vad(self) -> None:
        self.ctx.config.set("voice.vad_sensitivity", int(self.vad_slider.value()))
        self.ctx.orchestrator.apply_audio_settings()

    # --------------------------------------------------------- key manage
    def _add_groq_key(self, name: str, key: str) -> None:
        self.ctx.config.add_groq_key(name or "Groq key", key)
        self._rebuild_key_rows()
        self._refresh_usage()
        self.status_message.emit("Groq key added", True)

    def _add_dg_key(self, name: str, key: str) -> None:
        self.ctx.config.add_deepgram_key(name or "Deepgram key", key)
        self._rebuild_key_rows()
        self._refresh_usage()
        self.status_message.emit("Deepgram key added", True)

    def _remove_groq_key(self, kid: str) -> None:
        self.ctx.config.remove_groq_key(kid)
        self._rebuild_key_rows()
        self._refresh_usage()

    def _remove_dg_key(self, kid: str) -> None:
        self.ctx.config.remove_deepgram_key(kid)
        self._rebuild_key_rows()
        self._refresh_usage()

    def _use_key(self, kid: str, purpose: str) -> None:
        cfg = self.ctx.config
        if purpose == "llm":
            cfg.set("providers.active_groq_llm_key_id", kid)
        elif purpose == "groq_stt":
            cfg.set("providers.groq_stt_key_mode", "custom")
            cfg.set("providers.groq_stt_key_id", kid)
        elif purpose == "dg_stt":
            cfg.set("providers.deepgram_stt_key_id", kid)
        elif purpose == "dg_tts":
            cfg.set("providers.deepgram_tts_key_id", kid)
        self._rebuild_key_rows()
        self._refresh_usage()
        self._sync_key_combos()
        self.status_message.emit(f"Active key updated for {purpose}", True)

    def _rebuild_key_rows(self) -> None:
        cfg = self.ctx.config
        for row in self._key_rows:
            row.setParent(None)
            row.hide()
            row.deleteLater()
        self._key_rows.clear()
        self._clear_layout(self.groq_keys_box)
        self._clear_layout(self.dg_keys_box)

        active_map = {
            "llm": cfg.get("providers.active_groq_llm_key_id", ""),
            "groq_stt": (cfg.get("providers.groq_stt_key_id", "")
                         if cfg.get("providers.groq_stt_key_mode") == "custom" else ""),
        }
        for entry in cfg.groq_keys():
            row = KeyRow(entry, "groq",
                         [("llm", "Use for LLM"), ("groq_stt", "Use for STT")],
                         active_map)
            row.removed.connect(self._remove_groq_key)
            row.use_requested.connect(self._use_key)
            row.changed.connect(self._persist_keys)
            self.groq_keys_box.addWidget(row)
            self._key_rows.append(row)

        active_map_dg = {
            "dg_stt": cfg.get("providers.deepgram_stt_key_id", ""),
            "dg_tts": cfg.get("providers.deepgram_tts_key_id", ""),
        }
        for entry in cfg.deepgram_keys():
            row = KeyRow(entry, "deepgram",
                         [("dg_stt", "Use for STT"), ("dg_tts", "Use for TTS")],
                         active_map_dg)
            row.removed.connect(self._remove_dg_key)
            row.use_requested.connect(self._use_key)
            row.changed.connect(self._persist_keys)
            self.dg_keys_box.addWidget(row)
            self._key_rows.append(row)

        self._sync_key_combos()

    def _sync_key_combos(self) -> None:
        cfg = self.ctx.config
        for combo, entries, active_field in (
                (self.stt_key_combo, cfg.groq_keys(), "providers.groq_stt_key_id"),
                (self.dg_stt_key_combo, cfg.deepgram_keys(),
                 "providers.deepgram_stt_key_id"),
                (self.tts_key_combo, cfg.deepgram_keys(),
                 "providers.deepgram_tts_key_id")):
            combo.blockSignals(True)
            combo.clear()
            for e in entries:
                combo.addItem(f"{e['name']} ({_short(e['key'])})", e["id"])
            kid = cfg.get(active_field, "")
            idx = combo.findData(kid)
            combo.setCurrentIndex(max(0, idx))
            combo.blockSignals(False)
        self.stt_key_combo.setEnabled(
            cfg.get("providers.groq_stt_key_mode") == "custom")

    def _clear_layout(self, lay) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.hide()
                w.deleteLater()

    def _persist_keys(self) -> None:
        """Pull row widget state back into config (name/enabled/key)."""
        cfg = self.ctx.config
        groq_rows = [r for r in self._key_rows if r.provider == "groq"]
        dg_rows = [r for r in self._key_rows if r.provider == "deepgram"]
        groq_keys = cfg.groq_keys()
        for row in groq_rows:
            for e in groq_keys:
                if e["id"] == row.entry["id"]:
                    e["name"] = row.name_input.text().strip() or e["name"]
                    e["enabled"] = row.enabled.isChecked()
        cfg.set("providers.groq_keys", groq_keys)
        dg_keys = cfg.deepgram_keys()
        for row in dg_rows:
            for e in dg_keys:
                if e["id"] == row.entry["id"]:
                    e["name"] = row.name_input.text().strip() or e["name"]
                    e["enabled"] = row.enabled.isChecked()
        cfg.set("providers.deepgram_keys", dg_keys)
        self._refresh_usage()

    # ------------------------------------------------------------ status
    def _refresh_usage(self) -> None:
        cfg = self.ctx.config
        stack = cfg.active_stack()

        self.llm_active_chip.setText(f"Active model — {stack['llm_model']}")

        engine = "GROQ" if cfg.get("voice.stt_provider", "groq") == "groq" \
            else "DEEPGRAM"
        stt_state = "ON" if stack.get("stt_enabled", True) else "OFF"
        _set_pill(self.stt_provider_status, "idle",
                  f"ENGINE {engine} · {stack['stt_model']}"
                  f" · {'key ok' if stack['stt_key'] else 'NO KEY'}"
                  f" · STT {stt_state}")

        # live-apply mic/STT/TTS toggles (requirement #2, #3, #4: changing
        # the mode immediately changes the actual microphone behavior)
        if not self._loading:
            try:
                self.ctx.orchestrator.apply_audio_settings()
            except Exception:
                pass

    # --------------------------------------------------------- async tests
    def _run_async(self, work, apply) -> None:
        def runner():
            try:
                result = work()
            except Exception as exc:              # never crash the UI
                result = (False, f"Error: {exc}")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: apply(result))
        threading.Thread(target=runner, daemon=True).start()

    def _test_llm(self) -> None:
        key = self.ctx.config.groq_key_for_llm()
        _set_pill(self.llm_test_status, "testing", "testing…")

        def apply(res):
            ok, msg = res
            _set_pill(self.llm_test_status, "ok" if ok else "err", msg[:60])
            self.status_message.emit(
                ("LLM connection OK — " if ok else "LLM test failed — ") + msg, ok)

        self._run_async(lambda: groq.test_key(key), apply)

    def _test_groq_stt(self) -> None:
        mode = self.ctx.config.get("providers.groq_stt_key_mode", "llm")
        key = (self.ctx.config.groq_key_for_stt() if mode != "custom"
               else self._key_from_combo(self.stt_key_combo, self.ctx.config.groq_keys()))
        _set_pill(self.groq_stt_test_status, "testing", "testing…")

        def apply(res):
            ok, msg = res
            _set_pill(self.groq_stt_test_status, "ok" if ok else "err", msg[:60])
            self.status_message.emit(
                ("Groq STT OK — " if ok else "Groq STT test failed — ") + msg, ok)

        self._run_async(lambda: groq.test_key(key), apply)

    def _test_dg_stt(self) -> None:
        key = self._key_from_combo(self.dg_stt_key_combo,
                                   self.ctx.config.deepgram_keys())
        _set_pill(self.dg_stt_test_status, "testing", "testing…")

        def apply(res):
            ok, msg = res
            _set_pill(self.dg_stt_test_status, "ok" if ok else "err", msg[:60])
            self.status_message.emit(
                ("Deepgram STT OK — " if ok else "Deepgram STT test failed — ") + msg,
                ok)

        self._run_async(lambda: dg.test_key(key), apply)

    def _test_tts(self) -> None:
        cfg = self.ctx.config
        key = cfg.deepgram_key_for_tts()
        voice = cfg.get("voice.tts_voice", "aura-2-thalia-en")
        _set_pill(self.tts_test_status, "testing", "synthesizing…")

        def work():
            wav = dg.speak(key, "This is Nova. Voice test successful.", voice)
            return (True, "Voice ready — playing sample"), wav

        def apply(res):
            (ok, msg), wav = res
            _set_pill(self.tts_test_status, "ok" if ok else "err", msg[:60])
            if ok and wav:
                try:
                    self.ctx.orchestrator.player.play(wav)
                except Exception:
                    pass
            self.status_message.emit("TTS test: " + msg, ok)

        def guarded_work():
            if not key:
                return (False, "No Deepgram API key configured"), None
            try:
                return work()
            except Exception as exc:
                return (False, str(exc)), None

        self._run_async(guarded_work, apply)

    @staticmethod
    def _key_from_combo(combo: QComboBox, entries: list[dict]) -> str:
        kid = combo.currentData()
        for e in entries:
            if e["id"] == kid:
                return e.get("key", "")
        return ""

    # ------------------------------------------------------------- load/save
    def load_from_config(self) -> None:
        cfg = self.ctx.config
        self._loading = True
        self.llm_model.setCurrentText(cfg.get("llm.model"))
        self.temperature.setText(str(cfg.get("llm.temperature", 1.0)))
        self.max_tokens.setText(str(cfg.get("llm.max_tokens", 2036)))
        self.reasoning.setCurrentText(cfg.get("llm.reasoning_effort", "medium"))
        self.memory.setText(str(cfg.get("llm.memory_messages", 12)))

        provider = cfg.get("voice.stt_provider", "groq")
        idx = self.stt_provider.findData(provider)
        self.stt_provider.setCurrentIndex(max(0, idx))
        self.stt_model_groq.setCurrentText(cfg.get("voice.stt_model_groq"))
        self.stt_model_dg.setCurrentText(cfg.get("voice.stt_model_deepgram"))
        li = self.dg_lang.findData(cfg.get("voice.deepgram_language", "multi"))
        self.dg_lang.setCurrentIndex(max(0, li))
        # mic_mode now has 3 options: off / continuous / push_to_talk
        mode = cfg.get("voice.mic_mode", "continuous")
        mi = self.mic_mode.findData(mode)
        self.mic_mode.setCurrentIndex(max(0, mi if mi >= 0 else 1))
        self.mic_enabled.setChecked(cfg.get("voice.mic_enabled", True))
        self.stt_enabled.setChecked(cfg.get("voice.stt_enabled", True))
        self.tts_enabled.setChecked(cfg.get("voice.tts_enabled", True))
        self.vad_slider.setValue(int(cfg.get("voice.vad_sensitivity", 82)))
        self.auto_listen.setChecked(cfg.get("voice.auto_listen_on_launch", False))
        self.tts_voice.setCurrentIndex(
            max(0, self.tts_voice.findData(cfg.get("voice.tts_voice"))))
        self.tts_volume.setValue(int(cfg.get("voice.tts_volume", 90)))
        self.speak_replies.setChecked(cfg.get("voice.speak_replies", True))
        self.speak_reminders.setChecked(cfg.get("voice.speak_reminders", True))

        font_px = int(cfg.get("ui.font_size", 14))
        fi = self.font_combo.findData(font_px)
        self.font_combo.setCurrentIndex(max(0, fi))

        self.overlay_enabled.setChecked(cfg.get("overlay.enabled", True))
        self.start_minimized.setChecked(cfg.get("general.start_minimized", False))
        self.close_to_tray.setChecked(cfg.get("general.close_to_tray", True))
        self.start_with_windows.setChecked(cfg.get("general.start_with_windows", False))
        ci = self.confirmation.findData(cfg.get("llm.confirmation", "strict"))
        self.confirmation.setCurrentIndex(max(0, ci))

        mode = cfg.get("providers.groq_stt_key_mode", "llm")
        mi = self.stt_key_mode.findData(mode)
        self.stt_key_mode.setCurrentIndex(max(0, mi))

        self._rebuild_key_rows()
        self._refresh_usage()
        self._loading = False

    def _save(self) -> None:
        cfg = self.ctx.config
        self._persist_keys()
        cfg.set("llm.model", self.llm_model.currentText())
        try:
            cfg.set("llm.temperature",
                    max(0.0, min(2.0, float(self.temperature.text()))))
        except ValueError:
            pass
        try:
            cfg.set("llm.max_tokens", max(64, int(self.max_tokens.text())))
        except ValueError:
            pass
        cfg.set("llm.reasoning_effort", self.reasoning.currentText())
        try:
            cfg.set("llm.memory_messages",
                    max(2, min(50, int(self.memory.text()))))
        except ValueError:
            pass
        cfg.set("voice.stt_provider", self.stt_provider.currentData() or "groq")
        cfg.set("voice.stt_model_groq", self.stt_model_groq.currentText())
        cfg.set("voice.stt_model_deepgram", self.stt_model_dg.currentText())
        cfg.set("voice.deepgram_language", self.dg_lang.currentData() or "multi")
        cfg.set("voice.mic_mode", self.mic_mode.currentData() or "continuous")
        cfg.set("voice.mic_enabled", self.mic_enabled.isChecked())
        cfg.set("voice.stt_enabled", self.stt_enabled.isChecked())
        cfg.set("voice.tts_enabled", self.tts_enabled.isChecked())
        cfg.set("voice.vad_sensitivity", int(self.vad_slider.value()))
        cfg.set("voice.auto_listen_on_launch", self.auto_listen.isChecked())
        cfg.set("voice.tts_voice", self.tts_voice.currentData()
                or "aura-2-thalia-en")
        cfg.set("voice.tts_volume", int(self.tts_volume.value()))
        cfg.set("voice.speak_replies", self.speak_replies.isChecked())
        cfg.set("voice.speak_reminders", self.speak_reminders.isChecked())
        cfg.set("ui.font_size", int(self.font_combo.currentData() or 14))
        cfg.set("overlay.enabled", self.overlay_enabled.isChecked())
        cfg.set("general.start_minimized", self.start_minimized.isChecked())
        cfg.set("general.close_to_tray", self.close_to_tray.isChecked())
        cfg.set("general.start_with_windows", self.start_with_windows.isChecked())
        cfg.set("llm.confirmation", self.confirmation.currentData() or "strict")
        if self.stt_key_mode.currentData() == "custom":
            cfg.set("providers.groq_stt_key_mode", "custom")
            kid = self.stt_key_combo.currentData()
            if kid:
                cfg.set("providers.groq_stt_key_id", kid)
        else:
            cfg.set("providers.groq_stt_key_mode", "llm")
        kid = self.dg_stt_key_combo.currentData()
        if kid:
            cfg.set("providers.deepgram_stt_key_id", kid)
        kid = self.tts_key_combo.currentData()
        if kid:
            cfg.set("providers.deepgram_tts_key_id", kid)
        cfg.save()
        self.ctx.apply_runtime_settings()
        self._refresh_usage()
        self.settings_saved.emit()
        self.status_message.emit("Settings saved — providers reloaded", True)

    def _reset(self) -> None:
        self.ctx.config.reset_all()
        self.load_from_config()
        self.ctx.apply_runtime_settings()
        self.font_size_changed.emit(int(self.ctx.config.get("ui.font_size", 14)))
        self.status_message.emit("Settings reset to defaults", True)

    def _clear_cache(self) -> None:
        self.ctx.conversation.clear()
        self.status_message.emit("Conversation cache cleared", True)

    def on_shown(self) -> None:
        self.load_from_config()
