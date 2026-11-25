#!/usr/bin/env python3
"""Nova — Personal Desktop Assistant.

Run:  python main.py
Entry point that assembles config, stores, audio, providers, UI pages,
the independent widget system (page / desktop / overlay surfaces),
overlay, global hotkeys and the tray icon.
"""
from __future__ import annotations

import os
import sys
import traceback

from PySide6.QtCore import QObject, Qt, QTimer, Signal, qInstallMessageHandler
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from novaassistant import APP_NAME, ORG_NAME, __version__
from novaassistant.config import Config
from novaassistant.core.activity_log import ActivityLog
from novaassistant.core.conversation_store import ConversationStore
from novaassistant.core.notes_store import NotesStore
from novaassistant.core.orchestrator import Orchestrator
from novaassistant.core.reminders_store import RemindersStore
from novaassistant.core.scheduler import ReminderScheduler
from novaassistant import icons as icon_engine
from novaassistant import theme
from novaassistant.shortcuts import GlobalHotkeys
from novaassistant.ui.activity import ActivityPage
from novaassistant.ui.conversation import ConversationPage
from novaassistant.ui.desktop_widgets import DesktopWidgetsController
from novaassistant.ui.files import FilesPage
from novaassistant.ui.main_window import MainWindow
from novaassistant.ui.notes import NotesPage
from novaassistant.ui.overlay import OverlayWindow
from novaassistant.ui.reminders import RemindersPage
from novaassistant.ui.settings_page import SettingsPage
from novaassistant.ui.widgets.manager import WidgetManager
from novaassistant.ui.widgets_page import WidgetsPage


def _qt_message_handler(mode, context, message) -> None:
    """Route Qt internals away from the console; only keep fatal errors."""
    try:
        if mode >= 2:  # QtCriticalMsg / QtFatalMsg
            ActivityLog.default_instance.log(
                "system", f"Qt error: {message[:200]}", status="err")
    except Exception:
        pass


class AppContext(QObject):
    """Shared application context (config + stores + orchestrator)."""

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = Config()
        ActivityLog.default_instance = self.activity = ActivityLog(
            self.config.data_dir)
        self.notes = NotesStore(self.config.data_dir)
        self.reminders = RemindersStore(self.config.data_dir)
        self.conversation = ConversationStore(self.config.data_dir)
        self.orchestrator = Orchestrator(
            self.config, self.notes, self.reminders,
            self.activity, self.conversation, parent=self)
        self.scheduler = ReminderScheduler(self.reminders, self.activity, parent=self)
        self.scheduler.reminder_due.connect(self._on_reminder_due)
        self.widget_manager = WidgetManager(self.config, parent=self)
        self.widget_manager.attach_ctx(self)
        self.app_screen = None
        self.tray: QSystemTrayIcon | None = None

    # ------------------------------------------------------------------
    def _on_reminder_due(self, item: dict) -> None:
        if self.tray is not None:
            try:
                self.tray.showMessage(
                    "Nova Reminder", item["text"],
                    QSystemTrayIcon.Information, 6000)
            except Exception:
                pass
        if self.config.get("voice.speak_reminders", True):
            self.orchestrator.speak(f"Reminder: {item['text']}")

    def apply_runtime_settings(self) -> None:
        self.orchestrator.apply_audio_settings()
        if getattr(self, "settings_page", None):
            try:
                self.settings_page.load_from_config()
            except Exception:
                pass
        if getattr(self, "conversation_page", None):
            try:
                self.conversation_page.refresh_provider()
            except Exception:
                pass

    def set_start_with_windows(self, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        try:
            import winreg
            run = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                winreg.KEY_SET_VALUE)
            if enabled:
                exe = sys.executable
                script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
                winreg.SetValueEx(run, "NovaAssistant", 0, winreg.REG_SZ,
                                  f'"{exe}" "{script}"')
            else:
                try:
                    winreg.DeleteValue(run, "NovaAssistant")
                except FileNotFoundError:
                    pass
            winreg.CloseKey(run)
        except Exception:
            pass


def _global_excepthook(exc_type, exc, tb) -> None:
    """Last-resort guard: log every uncaught exception without crashing."""
    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        log = getattr(ActivityLog, "default_instance", None)
        if log is not None:
            log.log("error", f"Unhandled: {exc}", status="err", detail=detail[:1500])
    except Exception:
        pass
    traceback.print_exception(exc_type, exc, tb)


class NovaApplication:
    def __init__(self, app: QApplication):
        self.app = app
        self.ctx = AppContext(app)
        self.ctx.app_screen = app.primaryScreen()

        self.window = MainWindow(self.ctx)
        self.conversation_page = ConversationPage(self.ctx)
        self.notes_page = NotesPage(self.ctx)
        self.reminders_page = RemindersPage(self.ctx)
        self.activity_page = ActivityPage(self.ctx)
        self.files_page = FilesPage(self.ctx)
        self.widgets_page = WidgetsPage(self.ctx)
        self.settings_page = SettingsPage(self.ctx)

        self.window.add_page("conversation", self.conversation_page)
        self.window.add_page("notes", self.notes_page)
        self.window.add_page("reminders", self.reminders_page)
        self.window.add_page("activity", self.activity_page)
        self.window.add_page("files", self.files_page)
        self.window.add_page("widgets", self.widgets_page)
        self.window.add_page("settings", self.settings_page)

        self.overlay = OverlayWindow(self.ctx)
        self.desktop_widgets = DesktopWidgetsController(self.ctx)

        self._wire()
        self._restore_session()
        self._apply_font_scale(full_trees=True)

        # tray
        tray_menu = QMenu()
        act_show = QAction("Show Nova", tray_menu)
        act_show.triggered.connect(self._show_main)
        act_listen = QAction("Start / Stop Listening", tray_menu)
        act_listen.triggered.connect(self._on_tray_listen)
        act_overlay = QAction("Toggle AI Overlay", tray_menu)
        act_overlay.triggered.connect(self.overlay.toggle)
        act_widgets = QAction("Toggle Desktop Widgets", tray_menu)
        act_widgets.triggered.connect(self.desktop_widgets.toggle_all)
        act_quit = QAction("Quit Nova", tray_menu)
        act_quit.triggered.connect(self._quit)
        for a in (act_show, act_listen, act_overlay, act_widgets):
            tray_menu.addAction(a)
        tray_menu.addSeparator()
        tray_menu.addAction(act_quit)
        self.tray = QSystemTrayIcon(icon_engine.app_icon())
        self.tray.setContextMenu(tray_menu)
        self.tray.setToolTip(f"Nova v{__version__}")
        self.tray.activated.connect(
            lambda reason: self._show_main()
            if reason == QSystemTrayIcon.Trigger else None)
        self.tray.show()
        self.ctx.tray = self.tray

        # global hotkeys
        self.hotkeys = GlobalHotkeys(self._on_hotkey)
        self.hotkeys.start()

        self.ctx.set_start_with_windows(
            bool(self.ctx.config.get("general.start_with_windows")))

    # ------------------------------------------------------------ wiring
    def _wire(self) -> None:
        ctx, orch, mgr = self.ctx, self.ctx.orchestrator, self.ctx.widget_manager

        # conversation / page submit paths (text input)
        self.conversation_page.request_llm.connect(orch.submit_text)
        self.widgets_page.request_llm.connect(orch.submit_text)
        self.files_page.request_llm.connect(orch.submit_text)

        # orchestrator -> conversation view + overlay
        # NOTE: orchestrator.submit_text() and _on_utterance() already add the
        # user message to the conversation store BEFORE running the pipeline,
        # so we ONLY render here — never re-add (requirement #1: never lose or
        # skip the transcript, always show user msg before the AI response).
        orch.transcript_ready.connect(
            lambda t: (self.conversation_page.add_message("user", t),
                       self.overlay.panel.add_stream("YOU", t)))
        orch.response_ready.connect(
            lambda r: self.conversation_page.add_message("nova", r))
        orch.response_ready.connect(
            lambda r: self.overlay.panel.add_stream("NOVA", r))
        orch.error_occurred.connect(self._on_error)
        orch.state_changed.connect(self.conversation_page.set_state)
        orch.state_changed.connect(self.overlay.panel.set_state)
        orch.state_changed.connect(self.overlay.compact.set_state)
        orch.state_changed.connect(self._on_state)
        orch.latency_measured.connect(self.conversation_page.set_latency)
        orch.level_changed.connect(self.overlay.panel.set_level)
        orch.level_changed.connect(self.overlay.compact.set_level)
        orch.steps_changed.connect(self.overlay.panel.set_steps)
        orch.steps_changed.connect(self.overlay.compact.set_steps)
        orch.partial_transcript.connect(self.overlay.panel.set_transcript)
        orch.partial_transcript.connect(self.overlay.compact.set_transcript)
        orch.partial_transcript.connect(self.conversation_page.set_transcript_hint)
        orch.listening_changed.connect(self._on_listening)

        # page status + settings
        self.notes_page.status_message.connect(
            lambda m: self.ctx.activity.log("note", m))
        self.reminders_page.status_message.connect(
            lambda m: self.ctx.activity.log("reminder", m))
        self.files_page.status_message.connect(
            lambda m: self.ctx.activity.log("tool", m))
        self.widgets_page.status_message.connect(
            lambda m: self.ctx.activity.log("system", m))
        self.settings_page.status_message.connect(self._toast_status)
        self.settings_page.settings_saved.connect(
            lambda: (self.ctx.activity.log("system", "Settings updated"),
                     self.overlay.set_online(
                         bool(self.ctx.config.active_stack()["llm_key"])),
                     self.conversation_page.refresh_provider()))
        self.settings_page.font_size_changed.connect(self._on_font_size_changed)
        self.settings_page.overlay_toggled.connect(self._set_overlay_enabled)
        self.overlay.panel.input_submitted.connect(orch.submit_text)
        self.overlay.panel.mic_clicked.connect(self._on_overlay_mic)
        self.overlay.panel.stop_clicked.connect(orch.cancel_all)
        self.overlay.panel.minimize_clicked.connect(self._on_overlay_min)
        self.overlay.panel.settings_clicked.connect(
            lambda: (self._show_main(), self.window.navigate("settings")))

        # widget system -----------------------------------------------------
        # any store change -> refresh every live widget (queued to UI thread)
        class _RefreshBridge(QObject):
            trigger = Signal()

        self._notes_refresh = _RefreshBridge()
        self._notes_refresh.trigger.connect(mgr.data_changed)
        self.ctx.notes.add_listener(
            lambda *_: self._notes_refresh.trigger.emit())
        self._rem_refresh = _RefreshBridge()
        self._rem_refresh.trigger.connect(mgr.data_changed)
        self.ctx.reminders.add_listener(
            lambda *_: self._rem_refresh.trigger.emit())

        # refresh conversation status tiles when providers change
        self._conv_refresh = _RefreshBridge()
        self._conv_refresh.trigger.connect(
            self.conversation_page.refresh_provider)

        mgr.desktop_toggle.connect(self.desktop_widgets.toggle_all)
        mgr.open_page.connect(lambda key: (self._show_main(),
                                           self.window.navigate(key)))
        mgr.edit_reminder.connect(self._edit_reminder_from_widget)
        self.widgets_page.pin_requested.connect(self.desktop_widgets.toggle_all)

        # voice reminder fill: when the reminders page started the mic, route
        # transcripts to the reminder parser
        self._voice_reminder_active = False
        orig_toggle = self.reminders_page._toggle_voice

        def reminder_voice_hook():
            self._voice_reminder_active = not orch.is_listening
            orig_toggle()

        self.reminders_page._toggle_voice = reminder_voice_hook
        orch.transcript_ready.connect(self._route_transcript)

        # window events
        self.window.close_requested.connect(self._on_close_request)
        self.window.overlay_requested.connect(self.overlay.toggle)
        self.window.pin_widgets_requested.connect(self.desktop_widgets.toggle_all)
        self.window.new_note_requested.connect(
            lambda: (self._show_main(), self.window.navigate("notes"),
                     self.notes_page.new_note()))
        # requirement #14: when the main window is minimized, switch the
        # overlay to its dedicated compact floating UI. When restored,
        # switch back to the full overlay.
        self.window.minimized_changed.connect(self._on_window_minimized)

        # restore last page
        last = self.ctx.config.get("ui.last_page", "conversation")

        def goto_last():
            self.window.navigate(last if last in
                                 ("conversation", "notes", "reminders",
                                  "activity", "files", "widgets", "settings")
                                 else "conversation")
        QTimer.singleShot(60, goto_last)

    # ------------------------------------------------------------ events
    def _on_overlay_mic(self) -> None:
        """Overlay mic click: honor the current mic mode (PTT vs toggle)."""
        orch = self.ctx.orchestrator
        if orch.mic_mode == "push_to_talk":
            if orch.is_listening:
                orch.push_to_talk_release()
            else:
                orch.push_to_talk_press()
        else:
            orch.toggle_listening()

    def _on_tray_listen(self) -> None:
        """Tray 'Start / Stop Listening' — honor PTT vs continuous mode."""
        orch = self.ctx.orchestrator
        if orch.mic_mode == "push_to_talk":
            if orch.is_listening:
                orch.push_to_talk_release()
            else:
                orch.push_to_talk_press()
        else:
            orch.toggle_listening()

    def _on_window_minimized(self, minimized: bool) -> None:
        """When the main window is minimized, switch the overlay to its
        compact floating UI; when restored, expand it back (req #14)."""
        if not self.ctx.config.get("overlay.enabled", True):
            return
        if minimized:
            # show overlay (if hidden) and collapse to compact floating UI
            if not self.overlay.isVisible():
                self.overlay.show()
            self.overlay.collapse_to_pill()
        else:
            if self.overlay._pill_mode:
                self.overlay.expand_from_pill()

    def _edit_reminder_from_widget(self, rid: str) -> None:
        """Widgets request editing: open Reminders page, prefill or focus."""
        self._show_main()
        self.window.navigate("reminders")
        if rid:
            self.reminders_page._action("edit", rid)
        else:
            self.reminders_page.text_input.setFocus()
            self.reminders_page.status_message.emit(
                "Add a time like 'in 20 minutes' or 'tomorrow 6 PM'")

    def _on_overlay_min(self) -> None:
        if getattr(self.overlay, "_pill_mode", False):
            self.overlay.expand_from_pill()
        else:
            self.overlay.collapse_to_pill()

    def _route_transcript(self, text: str) -> None:
        if self._voice_reminder_active:
            self._voice_reminder_active = False
            self.reminders_page.on_utterance_transcribed(text)

    def desktop_widgets_visible(self) -> bool:
        return self.desktop_widgets.is_visible()

    # ------------------------------------------------------------ theming
    def _apply_font_scale(self, full_trees: bool = False) -> None:
        """Apply the configured font size to the global QSS and, when
        needed, to every already-constructed widget tree."""
        px = int(self.ctx.config.get("ui.font_size", 13))
        theme.set_font_scale(px / 12.0)
        self.app.setStyleSheet(theme.build_qss())
        if full_trees:
            for tree in (self.window, self.overlay):
                try:
                    theme.apply_scale_to_tree(tree)
                except Exception:
                    pass
            self.desktop_widgets.rescale_all()

    def _on_font_size_changed(self, px: int) -> None:
        self._apply_font_scale(full_trees=True)
        self.ctx.activity.log("system", f"Font size applied: {px}px", status="ok")

    def _on_state(self, state: str) -> None:
        self.window.set_status(
            state.title() if state != "IDLE" else "Idle", state != "IDLE")

    def _on_listening(self, active: bool) -> None:
        self.overlay.panel.waveform.set_active(active)

    def _on_error(self, title: str, detail: str) -> None:
        """Errors surface as a friendly inline card; full details live in
        Activity (Diagnostics) — never raw traceback spam in the chat."""
        detail = (detail or "").strip()
        self.ctx.activity.log("error", f"{title}: {detail[:200]}", status="err",
                              detail=detail[:1500])
        self.conversation_page.add_error(title, detail)

    def _on_hotkey(self, action: str) -> None:
        if action == "toggle_listening":
            orch = self.ctx.orchestrator
            # Honor mic_mode: in push_to_talk mode the global Ctrl+Space
            # acts as a one-shot PTT press+release (requirement #3, #4).
            # In continuous mode it toggles VAD-based listening.
            if orch.mic_mode == "push_to_talk":
                if orch.is_listening:
                    orch.push_to_talk_release()
                else:
                    orch.push_to_talk_press()
            else:
                orch.toggle_listening()
        elif action == "toggle_overlay":
            self.overlay.toggle()
        elif action == "new_note":
            self.window.new_note_requested.emit()
        elif action == "pin_widgets":
            self.desktop_widgets.toggle_all()

    def _set_overlay_enabled(self, enabled: bool) -> None:
        self.ctx.config.set("overlay.enabled", bool(enabled))
        if enabled:
            self.overlay.show()
            self.overlay.raise_()
        else:
            self.overlay.hide()

    def _toast_status(self, message: str, ok: bool) -> None:
        self.ctx.activity.log("system", message,
                              status="ok" if ok else "err")

    def _show_main(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_close_request(self) -> None:
        if self.ctx.config.get("general.close_to_tray", True):
            self.window.hide()
        else:
            self._quit()

    def _quit(self) -> None:
        try:
            self.ctx.orchestrator.shutdown()
            self.hotkeys.stop()
            self.tray.hide()
        except Exception:
            pass
        self.app.quit()

    def _restore_session(self) -> None:
        # seed welcome message
        if not self.ctx.conversation.messages():
            self.ctx.conversation.add(
                "nova",
                "Hi, I'm Nova — your personal desktop assistant. Open Settings "
                "to add your Groq and Deepgram API keys to enable full voice "
                "and reasoning capabilities. Try asking to open apps, create "
                "notes, or dictate commands.")
        for msg in self.ctx.conversation.messages():
            if msg["role"] == "error":
                continue
            self.conversation_page.add_message(msg["role"], msg["text"], msg["ts"])
        self.conversation_page.refresh_provider()
        if self.ctx.config.get("overlay.enabled", True):
            QTimer.singleShot(200, self.overlay.show)
        self.overlay.set_online(
            bool(self.ctx.config.active_stack()["llm_key"]))
        if self.ctx.config.get("widgets.pinned", False):
            QTimer.singleShot(300, self.desktop_widgets.sync)
        if self.ctx.config.get("general.start_minimized", False):
            self.window.hide()   # tray handles visibility
        else:
            self.window.show()
        if self.ctx.config.get("voice.auto_listen_on_launch", False):
            QTimer.singleShot(800, self.ctx.orchestrator.start_listening)


def main() -> int:
    # Give Windows a stable application identity so a source-launched build
    # uses Nova's icon instead of the generic Python taskbar icon.
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "nova-assistant.NovaAssistant")
        except Exception:
            pass
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(ORG_NAME)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # font scale must be known before any UI is built
    try:
        _font_px = int(Config().get("ui.font_size", 13))
    except Exception:
        _font_px = 13
    theme.set_font_scale(_font_px / 12.0)
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.build_qss())
    theme.apply_dark_palette(app)
    app.setWindowIcon(icon_engine.app_icon())
    app.setQuitOnLastWindowClosed(False)
    qInstallMessageHandler(_qt_message_handler)
    sys.excepthook = _global_excepthook

    nova = NovaApplication(app)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
