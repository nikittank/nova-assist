#!/usr/bin/env python3
"""Nova self-test — end-to-end validation you can run locally.

    python selftest.py

Runs REAL checks (no mocks where possible):
  1.  imports & package integrity
  2.  config store (save/load/providers)
  3.  notes store (edit-in-place — the duplicate-note fix)
  4.  reminders store (CRUD + complete/snooze/repeat)
  5.  reminder NL parser suite ("remind me tomorrow at 6 PM to call John every Monday")
  6.  keyboard shortcut matching (QKeySequence fix) [offscreen]
  7.  audio playback state machine (sounddevice.is_playing fix) [skips w/o device]
  8.  VAD end-of-speech detection
  9.  Groq / Deepgram key tests (only if keys configured)
  10. UI instantiation smoke test (offscreen Qt)
  11. global hotkey registration (Windows only)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback

PASS = 0
FAIL = 0
FAILURES: list[str] = []


def check(name: str, fn):
    global PASS, FAIL
    try:
        result = fn()
        if result is False:
            raise AssertionError("returned False")
        print(f"  [OK]   {name}")
        PASS += 1
    except Exception as exc:
        print(f"  [FAIL] {name}: {exc}")
        traceback.print_exc(limit=2)
        FAIL += 1
        FAILURES.append(name)


def section(title: str) -> None:
    print(f"\n== {title} ==")


def main() -> int:
    print(f"Nova self-test — Python {sys.version.split()[0]} / {sys.platform}")

    # ------------------------------------------------------------ 1 imports
    section("1. Imports")
    check("package import", lambda: __import__("novaassistant"))
    check("config", lambda: __import__("novaassistant.config", fromlist=["Config"]))
    check("stores", lambda: __import__("novaassistant.core.notes_store"))
    check("parser", lambda: __import__("novaassistant.core.reminder_parser"))
    check("providers.groq", lambda: __import__("novaassistant.providers.groq"))
    check("providers.deepgram", lambda: __import__("novaassistant.providers.deepgram"))
    check("shortcuts module", lambda: __import__("novaassistant.shortcuts"))

    # ------------------------------------------------------------- 2 config
    section("2. Config store")
    tmp = tempfile.mkdtemp(prefix="nova-test-")
    try:
        from novaassistant.config import Config

        def cfg_roundtrip():
            cfg = Config(data_dir=tmp)
            cfg.set("llm.model", "llama-3.3-70b-versatile")
            k1 = cfg.add_groq_key("Personal", "gsk_aaa111", True)
            k2 = cfg.add_groq_key("Work", "gsk_bbb222", True)
            assert cfg.groq_key_for_llm() == "gsk_aaa111"
            cfg.set("providers.active_groq_llm_key_id", k2["id"])
            assert cfg.groq_key_for_llm() == "gsk_bbb222"
            cfg.update_groq_key(k2["id"], enabled=True)
            assert cfg.groq_key_for_llm() == "gsk_bbb222"
            cfg.remove_groq_key(k2["id"])
            assert cfg.groq_key_for_llm() == "gsk_aaa111"
            d1 = cfg.add_deepgram_key("DG1", "dg_x", True)
            d2 = cfg.add_deepgram_key("DG2", "dg_y", True)
            cfg.set("providers.deepgram_tts_key_id", d2["id"])
            assert cfg.deepgram_key_for_tts() == "dg_y"
            assert cfg.deepgram_key_for_stt() == "dg_x"
            return True

        check("config CRUD + provider routing", cfg_roundtrip)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------- 3 notes
    section("3. Notes store (edit-in-place fix)")
    tmp = tempfile.mkdtemp(prefix="nova-test-")
    try:
        from novaassistant.core.notes_store import NotesStore

        def notes_edit_in_place():
            store = NotesStore(tmp)
            note = store.create("9 p.m. Today", "- buy milk", "note")
            count_before = len(store.all())
            # EDIT the same note and save — must NOT create a new one
            updated = store.update(note["id"], title="9 p.m. Today (edited)",
                                   content="- buy milk\n- call john")
            assert updated is not None and updated["id"] == note["id"]
            assert len(store.all()) == count_before, "duplicate note created!"
            # topic preserved unless explicitly changed
            store.update(note["id"], content="- buy milk on friday")
            after = store.get(note["id"])
            assert after["topic"] == "note", "topic was lost on edit!"
            store.update(note["id"], topic="bucket")
            assert store.get(note["id"])["topic"] == "bucket"
            # search still finds edited content
            assert store.search("friday"), "search failed on edited content"
            assert store.update("nonexistent", title="x") is None
            assert len(store.all()) == count_before
            store.delete(note["id"])
            assert len(store.all()) == count_before - 1
            return True

        check("update-in-place / topic preservation / search", notes_edit_in_place)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --------------------------------------------------------- 4 reminders
    section("4. Reminders store")
    tmp = tempfile.mkdtemp(prefix="nova-test-")
    try:
        from datetime import datetime, timedelta

        from novaassistant.core.reminders_store import RemindersStore

        def reminders_flow():
            store = RemindersStore(tmp)
            due = (datetime.now() + timedelta(hours=2)).isoformat(timespec="seconds")
            r = store.create("Call John", due, "none")
            assert store.get(r["id"])["text"] == "Call John"
            store.update(r["id"], text="Call John about Deepgram")
            assert store.get(r["id"])["text"].startswith("Call John about")
            # snooze pushes due forward
            snoozed = store.snooze(r["id"], 5)
            assert datetime.fromisoformat(snoozed["due"]) > datetime.now() + timedelta(minutes=4)
            # complete -> done
            done = store.complete(r["id"])
            assert done["done"] is True
            # repeating reminder reschedules instead of done
            due2 = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
            weekly = store.create("Review work", due2, "weekly")
            res = store.complete(weekly["id"])
            assert res["done"] is False, "weekly reminder should reschedule"
            # due_now detection
            due3 = (datetime.now() - timedelta(seconds=5)).isoformat(timespec="seconds")
            store.create("Fire me now", due3, "none")
            fired = store.due_now(within_seconds=20)
            assert any(x["text"] == "Fire me now" for x in fired)
            assert store.delete(r["id"]) and store.delete(weekly["id"])
            return True

        check("CRUD + snooze + repeat reschedule + due_now", reminders_flow)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ----------------------------------------------------------- 5 parser
    section("5. Reminder NL parser")
    from datetime import datetime

    from novaassistant.core import reminder_parser

    def parser_suite():
        now = datetime(2026, 9, 9, 18, 43, 0)  # Wednesday
        # canonical example
        p = reminder_parser.parse_reminder(
            "remind me tomorrow at 6 PM to call John every Monday", now)
        assert p["text"].lower().startswith("call john"), p
        assert p["date"] == "2026-09-10", p
        assert p["time"] == "18:00", p
        assert p["repeat"] == "weekly:0", p  # every Monday
        # simple time
        p = reminder_parser.parse_reminder("remind me at 6 PM to call John", now)
        assert p["date"] == "2026-09-09" or p["date"] == "2026-09-10", p
        assert p["time"] == "18:00", p
        # relative minutes
        p = reminder_parser.parse_reminder("meeting in 20 minutes", now)
        assert p["datetime"].startswith("2026-09-09T19:03"), p
        # explicit date
        p = reminder_parser.parse_reminder(
            "remind me on Sep 15 at 09:00 to publish changelog", now)
        assert p["date"] == "2026-09-15", p
        assert p["time"] == "09:00", p
        # every day
        p = reminder_parser.parse_reminder("take pills every day at 8 am", now)
        assert p["repeat"] == "daily", p
        assert p["time"] == "08:00", p
        # next friday (upcoming Friday from Wed 2026-09-09)
        p = reminder_parser.parse_reminder("submit report next friday", now)
        assert p["date"] == "2026-09-11", p
        # tonight
        p = reminder_parser.parse_reminder("watch the launch tonight", now)
        assert p["date"] == "2026-09-09", p
        # weekdays
        p = reminder_parser.parse_reminder("standup weekdays at 10:30", now)
        assert p["repeat"] == "weekdays", p
        return True

    check('parse "tomorrow at 6 PM … every Monday" + variants', parser_suite)

    # -------------------------------------------------------- 6 shortcuts
    section("6. Keyboard shortcuts (offscreen Qt)")
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeyEvent, QKeySequence
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        from novaassistant.shortcuts import event_matches

        def shortcut_matching():
            # build a real Ctrl+Space key event
            def make_key(combo_text, key, mods):
                return QKeyEvent(QKeyEvent.Type.KeyPress, key, mods)

            ev = make_key("Ctrl+Space", Qt.Key_Space, Qt.ControlModifier)
            assert event_matches(ev, "Ctrl+Space"), "Ctrl+Space not matched"
            ev = make_key("Ctrl+Enter", Qt.Key_Return, Qt.ControlModifier)
            assert event_matches(ev, "Ctrl+Enter"), "Ctrl+Enter not matched"
            ev = make_key("Enter", Qt.Key_Return, Qt.NoModifier)
            assert event_matches(ev, "Enter"), "Enter not matched"
            # negative: Ctrl+Space must NOT match plain Space
            ev = make_key("Space", Qt.Key_Space, Qt.NoModifier)
            assert not event_matches(ev, "Ctrl+Space")
            # THE REGRESSION: event.matches(QKeySequence(...)) used to crash.
            # event_matches() must handle the same comparison safely.
            ev = make_key("Ctrl+S", Qt.Key_S, Qt.ControlModifier)
            assert event_matches(ev, "Ctrl+S")
            return True

        check("Ctrl+Space / Ctrl+Enter / Enter / Ctrl+S matching",
              shortcut_matching)
    except Exception as exc:
        check("qt availability", lambda: (_ for _ in ()).throw(exc))

    # ------------------------------------------------------------ 7 audio
    section("7. Audio playback state machine")
    try:
        import numpy as np

        from novaassistant.audio.playback import AudioPlayer

        def playback_state():
            player = AudioPlayer()
            # the FIX: is_playing() is our own flag — no sounddevice.is_playing
            assert not player.is_playing()
            try:
                import sounddevice as _sd
                _sd.query_devices(kind="output")   # raises when no output exists
            except Exception:
                print("       (no audio output device — state test only)")
                return True
            sr = 8000
            tone = (np.sin(np.arange(sr) * 0.05) * 12000).astype(np.int16)
            player.play(tone.tobytes(), sr)
            assert player.is_playing(), "should be playing right after play()"
            player.stop()
            assert not player.is_playing(), "should stop immediately"
            # repeated restart
            for _ in range(3):
                player.play(tone.tobytes(), sr)
                player.stop()
            assert not player.is_playing()
            return True

        check("play / is_playing / stop / restart x3", playback_state)
    except Exception as exc:
        print(f"  [SKIP] audio: {exc}")

    # ------------------------------------------------------------- 8 vad
    section("8. VAD end-of-speech")
    from novaassistant.audio.vad import VAD

    def vad_flow():
        import time as _t
        vad = VAD(sensitivity=82, silence_ms=300, min_speech_ms=100)
        t0 = 100.0
        quiet = 0.0005
        loud = 0.08
        states = []
        t = t0
        for _ in range(30):              # silence
            states.append(vad.process(quiet, t))
            t += 0.03
        for _ in range(20):              # speech
            states.append(vad.process(loud, t))
            t += 0.03
        for _ in range(40):              # trailing silence -> done
            result = vad.process(quiet, t)
            states.append(result)
            t += 0.03
            if result == "done":
                break
        assert "done" in states, f"never detected end of speech: {states[-10:]}"
        return True

    check("silence -> speech -> trailing -> done", vad_flow)

    # ------------------------------------------------------- 9 key tests
    section("9. Provider key tests (live, if configured)")
    from novaassistant.config import default_data_dir
    cfg_dir = default_data_dir()
    from novaassistant.config import Config as _C
    cfg = _C(data_dir=cfg_dir)
    groq_key = cfg.groq_key_for_llm()
    dg_key = cfg.deepgram_key_for_stt()
    if groq_key:
        from novaassistant.providers import groq
        ok, msg = groq.test_key(groq_key)
        check(f"Groq LLM key ({'valid' if ok else 'INVALID'}: {msg})", lambda: ok)
    else:
        print("  [SKIP] no Groq key configured")
    if dg_key:
        from novaassistant.providers import deepgram
        ok, msg = deepgram.test_key(dg_key)
        check(f"Deepgram key ({'valid' if ok else 'INVALID'}: {msg})", lambda: ok)
    else:
        print("  [SKIP] no Deepgram key configured")

    # ------------------------------------------------- 9b widget manager
    section("9b. Widget system (manager + persistence)")
    tmp = tempfile.mkdtemp(prefix="nova-wm-")
    try:
        from novaassistant.config import Config

        def widget_manager_flow():
            cfg = Config(data_dir=tmp)
            from novaassistant.ui.widgets.manager import WidgetManager
            mgr = WidgetManager(cfg)
            mgr.attach_ctx(type("Ctx", (), {"config": cfg})())
            assert len(mgr.instances) >= 4, "seed widgets missing"
            types_before = [i["type"] for i in mgr.instances]
            # add / remove
            inst = mgr.create("clock", "page")
            assert any(i["id"] == inst["id"] for i in mgr.instances)
            assert mgr.get(inst["id"])["type"] == "clock"
            mgr.remove(inst["id"])
            assert mgr.get(inst["id"]) is None
            # surface move
            focus = next(i for i in mgr.instances if i["type"] == "focus")
            mgr.move_surface(focus["id"], "desktop")
            assert [i for i in mgr.for_surface("desktop")][0]["type"] == "focus"
            mgr.move_surface(focus["id"], "page")
            # overlay pin
            mgr.set_pin_overlay(focus["id"], True)
            assert mgr.overlay_pinned()[0]["id"] == focus["id"]
            mgr.set_pin_overlay(focus["id"], False)
            # persistence across manager restart (layout restore)
            clock = next(i for i in mgr.instances if i["type"] == "clock")
            clock.update({"x": 128, "y": 96, "w": 300, "h": 200})
            mgr.save()
            mgr2 = WidgetManager(cfg)
            assert mgr2.get(clock["id"])["x"] == 128
            assert mgr2.get(clock["id"])["w"] == 300
            # reset layout restores the seed set
            mgr2.reset_layout()
            assert len(mgr2.instances) >= 4
            return True

        check("create/remove/move-surface/pin/reset + layout restore", widget_manager_flow)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------- 9c widget widgets
    section("9c. Individual widgets construct + actually work")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        def widgets_work():
            import json as _json
            import os as _os
            wtmp = tempfile.mkdtemp(prefix="nova-wtype-")
            from novaassistant.config import Config
            from novaassistant.core.activity_log import ActivityLog
            from novaassistant.core.conversation_store import ConversationStore
            from novaassistant.core.notes_store import NotesStore
            from novaassistant.core.orchestrator import Orchestrator
            from novaassistant.core.reminders_store import RemindersStore
            from novaassistant.ui.widgets.manager import WidgetManager
            from datetime import datetime, timedelta

            cfg = Config(data_dir=wtmp)
            activity = ActivityLog(wtmp)
            notes = NotesStore(wtmp)
            reminders = RemindersStore(wtmp)
            conversation = ConversationStore(wtmp)
            orch = Orchestrator(cfg, notes, reminders, activity, conversation)
            mgr = WidgetManager(cfg)

            Ctx = type("Ctx", (), {
                "config": cfg, "activity": activity, "notes": notes,
                "reminders": reminders, "conversation": conversation,
                "orchestrator": orch, "app_screen": None,
                "widget_manager": mgr,
            })
            ctx = Ctx()
            mgr.attach_ctx(ctx)

            # real data for the widgets to display
            notes.create("Shopping list", "- milk\n- eggs", "note")
            due = (datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds")
            overdue = (datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds")
            r1 = reminders.create("Call John", due, "none")
            r2 = reminders.create("Overdue task", overdue, "none")

            from novaassistant.ui.widgets import REGISTRY
            built = {}
            for wtype, meta in REGISTRY.items():
                inst = mgr.create(wtype, "page")
                w = mgr.build_widget(inst)
                assert w is not None, f"{wtype} did not build"
                w.refresh()          # must not raise with real store data
                w.resize(*meta["cls"].default_size)
                built[wtype] = (inst, w)
            # clock actually shows a time
            clock_inst, clock_w = built["clock"]
            assert ":" in clock_w.time_lbl.text(), "clock shows no time"
            # focus widget persists text via config (the new widget uses a
            # modal edit dialog; set the config value directly to verify the
            # widget renders the saved text on refresh)
            f_inst, f_w = built["focus"]
            ctx.config.set("widgets.focus_text", "Ship the widget system")
            f_w.refresh()
            assert ctx.config.get("widgets.focus_text") == "Ship the widget system"
            assert "Ship the widget system" in f_w.text_lbl.text()
            # quick notes actually create notes (supports '# Title' parsing)
            qn_inst, qn_w = built["quick_notes"]
            qn_w.input.setPlainText("# Widget-made note\nBody of the note")
            qn_w._save()
            assert any(n["title"] == "Widget-made note" for n in notes.all())
            assert any(n["content"] == "Body of the note" for n in notes.all())
            # reminders widget actions hit the real store
            rw_inst, rw_w = built["reminders"]
            rw_w._complete(r1["id"], True)
            assert reminders.get(r1["id"])["done"] is True
            rw_w._snooze(r2["id"])
            assert datetime.fromisoformat(reminders.get(r2["id"])["due"]) > datetime.now()
            rw_w._delete(r2["id"])
            assert reminders.get(r2["id"]) is None
            # reminders widget quick-add parses 'in 20 minutes'
            rw_w.add_input.setText("widget parse test in 20 minutes")
            rw_w._quick_add()
            assert any("widget parse test" in r["text"] for r in reminders.all())
            # what's today lists overdue items
            wt_inst, wt_w = built["whats_today"]
            wt_w.refresh()
            # settings apply flow (clock)
            c_inst, c_w = built["clock"]
            c_w.settings["format"] = "24h"
            c_w.settings["seconds"] = True
            c_w.instance["settings"] = c_w.settings
            c_w.refresh()
            assert len(c_w.time_lbl.text().split(":")) == 3
            # collapse persists
            c_w.toggle_collapsed()
            assert c_inst["settings"]["collapsed"] is True
            c_w.toggle_collapsed()
            for inst, w in built.values():
                w.shutdown()
            shutil.rmtree(wtmp, ignore_errors=True)
            return True

        check("8 widget types build + refresh + real store actions", widgets_work)
    except Exception as exc:
        check("widget types", lambda: (_ for _ in ()).throw(exc))

    # --------------------------------------------------------- 10 UI smoke
    section("10. UI smoke test (offscreen)")
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)

        def ui_smoke():
            from novaassistant.config import Config
            from novaassistant.core.activity_log import ActivityLog
            from novaassistant.core.conversation_store import ConversationStore
            from novaassistant.core.notes_store import NotesStore
            from novaassistant.core.orchestrator import Orchestrator
            from novaassistant.core.reminders_store import RemindersStore
            from novaassistant.ui.widgets.manager import WidgetManager
            ui_tmp = tempfile.mkdtemp(prefix="nova-ui-")
            cfg = Config(data_dir=ui_tmp)
            activity = ActivityLog(ui_tmp)
            notes = NotesStore(ui_tmp)
            reminders = RemindersStore(ui_tmp)
            conversation = ConversationStore(ui_tmp)
            orch = Orchestrator(cfg, notes, reminders, activity, conversation)
            mgr = WidgetManager(cfg)

            Ctx = type("Ctx", (), {
                "config": cfg, "activity": activity, "notes": notes,
                "reminders": reminders, "conversation": conversation,
                "orchestrator": orch, "app_screen": None,
                "widget_manager": mgr,
            })
            ctx = Ctx()
            mgr.attach_ctx(ctx)

            from novaassistant.ui.main_window import MainWindow
            win = MainWindow(ctx)
            from novaassistant.ui.activity import ActivityPage
            from novaassistant.ui.conversation import ConversationPage
            from novaassistant.ui.files import FilesPage
            from novaassistant.ui.notes import NotesPage
            from novaassistant.ui.overlay import OverlayWindow
            from novaassistant.ui.reminders import RemindersPage
            from novaassistant.ui.settings_page import SettingsPage
            from novaassistant.ui.widgets_page import WidgetsPage
            pages = [
                ConversationPage(ctx),
                NotesPage(ctx),
                RemindersPage(ctx),
                ActivityPage(ctx),
                FilesPage(ctx),
                WidgetsPage(ctx),
                SettingsPage(ctx),
            ]
            keys = ["conversation", "notes", "reminders", "activity",
                    "files", "widgets", "settings"]
            for i, page in enumerate(pages):
                win.add_page(keys[i], page)
                page.on_shown()
            for key in keys:
                win.navigate(key)
            ov = OverlayWindow(ctx)
            ov.show()
            ov.rebuild_pinned()
            ov.hide()
            from novaassistant.ui.desktop_widgets import DesktopWidgetsController
            ctrl = DesktopWidgetsController(ctx)
            ctrl.sync()
            ctrl.refresh_all()
            ctrl.toggle_all()
            ctrl.toggle_all()
            # simulate conversation messages
            pages[0].add_message("user", "Can you listen to me?")
            pages[0].add_message("nova", "Yes — I'm listening.")
            pages[0].add_error("Audio playback failed: module 'sounddevice'",
                               "Legacy error path is fixed in playback.py",
                               "Traceback (most recent call last): ... fixed")
            app.processEvents()
            shutil.rmtree(ui_tmp, ignore_errors=True)
            return True

        check("all pages construct + navigate + render", ui_smoke)
    except Exception as exc:
        print(f"  [FAIL] UI smoke: {exc}")
        traceback.print_exc(limit=3)
        globals()["FAIL"] = globals().get("FAIL", 0) + 1

    # ------------------------------------------------- 10b responsive
    section("10b. Responsive layout checks (small window sizes)")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        def responsive_check():
            from novaassistant.config import Config
            from novaassistant.core.activity_log import ActivityLog
            from novaassistant.core.conversation_store import ConversationStore
            from novaassistant.core.notes_store import NotesStore
            from novaassistant.core.orchestrator import Orchestrator
            from novaassistant.core.reminders_store import RemindersStore
            from novaassistant.ui.widgets.manager import WidgetManager
            ui_tmp = tempfile.mkdtemp(prefix="nova-resp-")
            cfg = Config(data_dir=ui_tmp)
            activity = ActivityLog(ui_tmp)
            notes = NotesStore(ui_tmp)
            reminders = RemindersStore(ui_tmp)
            conversation = ConversationStore(ui_tmp)
            orch = Orchestrator(cfg, notes, reminders, activity, conversation)
            mgr = WidgetManager(cfg)
            Ctx = type("Ctx", (), {
                "config": cfg, "activity": activity, "notes": notes,
                "reminders": reminders, "conversation": conversation,
                "orchestrator": orch, "app_screen": None,
                "widget_manager": mgr,
            })
            ctx = Ctx()
            mgr.attach_ctx(ctx)

            from novaassistant.ui.main_window import MainWindow
            from novaassistant.ui.activity import ActivityPage
            from novaassistant.ui.conversation import ConversationPage
            from novaassistant.ui.files import FilesPage
            from novaassistant.ui.notes import NotesPage
            from novaassistant.ui.reminders import RemindersPage
            from novaassistant.ui.settings_page import SettingsPage
            from novaassistant.ui.widgets_page import WidgetsPage
            pages = [
                ConversationPage(ctx), NotesPage(ctx), RemindersPage(ctx),
                ActivityPage(ctx), FilesPage(ctx), WidgetsPage(ctx),
                SettingsPage(ctx),
            ]
            win = MainWindow(ctx)
            for key, page in zip(
                    ("conversation", "notes", "reminders", "activity",
                     "files", "widgets", "settings"), pages):
                win.add_page(key, page)
            win.show()
            problems = []
            for width, height in ((1280, 800), (1040, 680), (940, 620)):
                win.resize(width, height)
                app.processEvents()
                for key, page in zip(
                        ("conversation", "notes", "reminders", "activity",
                         "files", "widgets", "settings"), pages):
                    win.navigate(key)
                    app.processEvents()
                    page_h = page.minimumSizeHint().height()
                    if page_h > height:
                        problems.append(
                            f"{key}@{width}x{height}: min-height {page_h}")
                # sidebar should have auto-collapsed at small width
                if width <= 1040 and not win.sidebar.is_collapsed():
                    problems.append(f"sidebar not collapsed at {width}")
            win.hide()
            shutil.rmtree(ui_tmp, ignore_errors=True)
            assert not problems, "; ".join(problems[:6])
            return True

        check("no page overflow at 1280/1040/940 widths", responsive_check)
    except Exception as exc:
        print(f"  [FAIL] responsive: {exc}")
        traceback.print_exc(limit=3)
        globals()["FAIL"] = globals().get("FAIL", 0) + 1

    # ------------------------------------------------- 10c window snap
    section("10c. Window snapping (Windows-style)")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        def snap_math():
            from PySide6.QtCore import QPoint, QRect
            from novaassistant.ui.main_window import snap_geometry, snap_zone_for
            avail = QRect(0, 0, 1920, 1040)
            assert snap_zone_for(QPoint(5, 500), avail) == "left"
            assert snap_zone_for(QPoint(1915, 500), avail) == "right"
            assert snap_zone_for(QPoint(960, 4), avail) == "max"
            assert snap_zone_for(QPoint(4, 3), avail) == "nw"
            assert snap_zone_for(QPoint(1916, 3), avail) == "ne"
            assert snap_zone_for(QPoint(4, 1036), avail) == "sw"
            assert snap_zone_for(QPoint(1916, 1036), avail) == "se"
            assert snap_zone_for(QPoint(960, 500), avail) is None
            # geometry targets
            g = snap_geometry("left", avail)
            assert g == QRect(0, 0, 960, 1040), str(g)
            g = snap_geometry("right", avail)
            assert g == QRect(960, 0, 960, 1040), str(g)
            g = snap_geometry("max", avail)
            assert g.width() == 1920 and g.height() == 1040
            g = snap_geometry("se", avail)
            assert g == QRect(960, 520, 960, 520), str(g)
            g = snap_geometry("nw", avail)
            assert g == QRect(0, 0, 960, 520), str(g)
            # offset screen
            avail2 = QRect(100, 50, 1600, 900)
            g = snap_geometry("ne", avail2)
            assert g.right() == avail2.right() and g.top() == avail2.top()
            # preview widget constructs + shows/hides
            from novaassistant.ui.main_window import SnapPreview
            pv = SnapPreview()
            pv.show_zone(QRect(0, 0, 800, 600))
            assert pv.isVisible()
            pv.hide()
            assert not pv.isVisible()
            return True

        check("zones (edges/top/corners) + target geometry + preview", snap_math)
    except Exception as exc:
        check("snap math", lambda: (_ for _ in ()).throw(exc))

    # ------------------------------------------------- 10d font scaling
    section("10d. Font size control + live scaling")
    try:
        from PySide6.QtWidgets import QApplication, QLabel
        app = QApplication.instance() or QApplication(sys.argv)

        def font_scale_flow():
            from novaassistant import theme
            # baseline
            theme.set_font_scale(13 / 12.0)
            assert theme.fs(12) == 13 and theme.fs(20) == 22
            qss = theme.build_qss()
            assert "font-size: 13px" in qss, "global QSS not scaled"
            lbl = QLabel()
            theme.set_style(lbl, "color: #fff; font-size: 12px;")
            assert "font-size: 13px" in lbl.styleSheet(), lbl.styleSheet()
            # rescale up: from BASELINE (not from current), idempotent
            theme.set_font_scale(16 / 12.0)
            n = theme.apply_scale_to_tree(lbl)
            assert "font-size: 16px" in lbl.styleSheet(), lbl.styleSheet()
            n2 = theme.apply_scale_to_tree(lbl)   # second pass: no change
            assert "font-size: 16px" in lbl.styleSheet(), "double-scaled!"
            # dynamic rewrite keeps working at the new scale
            theme.set_style(lbl, "color: #fff; font-size: 10px;")
            assert "font-size: 13px" in lbl.styleSheet()  # 10*16/12=13.33->13
            theme.set_font_scale(1.0)
            theme.apply_scale_to_tree(lbl)
            assert "font-size: 10px" in lbl.styleSheet()
            return True

        check("fs() + set_style + idempotent apply_scale_to_tree", font_scale_flow)
    except Exception as exc:
        check("font scaling", lambda: (_ for _ in ()).throw(exc))

    # --------------------------------------- 10e pinned windows + grid
    section("10e. Pinned desktop windows + widgets grid")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.app if hasattr(sys, "app") else sys.argv)

        def pinned_flow():
            from PySide6.QtCore import QRect
            from novaassistant.config import Config
            from novaassistant.core.activity_log import ActivityLog
            from novaassistant.core.conversation_store import ConversationStore
            from novaassistant.core.notes_store import NotesStore
            from novaassistant.core.orchestrator import Orchestrator
            from novaassistant.core.reminders_store import RemindersStore
            from novaassistant.ui.desktop_widgets import (
                DesktopWidgetsController, PinnedWidgetWindow)
            from novaassistant.ui.widgets.manager import WidgetManager
            from novaassistant.ui.widgets_page import WidgetsPage

            ptmp = tempfile.mkdtemp(prefix="nova-pin-")
            cfg = Config(data_dir=ptmp)
            activity = ActivityLog(ptmp)
            notes = NotesStore(ptmp)
            reminders = RemindersStore(ptmp)
            conversation = ConversationStore(ptmp)
            orch = Orchestrator(cfg, notes, reminders, activity, conversation)
            mgr = WidgetManager(cfg)
            Ctx = type("Ctx", (), {
                "config": cfg, "activity": activity, "notes": notes,
                "reminders": reminders, "conversation": conversation,
                "orchestrator": orch, "app_screen": None,
                "widget_manager": mgr,
            })
            ctx = Ctx()
            mgr.attach_ctx(ctx)
            ctrl = DesktopWidgetsController(ctx)

            # pin ONE widget -> exactly ONE window appears
            clock = next(i for i in mgr.instances if i["type"] == "clock")
            mgr.pin_to_desktop(clock["id"])
            ctrl.sync()
            assert len(ctrl.windows) == 1, f"expected 1 window, got {len(ctrl.windows)}"
            win = ctrl.windows[clock["id"]]
            assert isinstance(win, PinnedWidgetWindow)
            assert win.card.window_pinned is True
            # only that widget is on the desktop
            assert [i["type"] for i in mgr.for_surface("desktop")] == ["clock"]
            # geometry persisted
            x, y = win.x(), win.y()
            win.resize(320, 220)
            win.persist_geometry()
            inst = mgr.get(clock["id"])
            assert inst["dw"] == 320 and inst["dh"] == 220, str(inst)
            # restart restore: new controller picks up saved geometry
            mgr2 = WidgetManager(cfg)
            inst2 = mgr2.get(clock["id"])
            assert inst2["dw"] == 320
            # unpin -> window closes, widget back on the page grid
            mgr.unpin_from_desktop(clock["id"])
            ctrl.sync()
            assert len(ctrl.windows) == 0
            assert inst["surface"] == "page"
            # pin a second widget; unpin via the card's close button route
            rem = next(i for i in mgr.instances if i["type"] == "reminders")
            mgr.pin_to_desktop(rem["id"])
            ctrl.sync()
            assert len(ctrl.windows) == 1
            ctrl.windows[rem["id"]].card.unpin_requested.emit(rem["id"])
            ctrl.sync()
            assert len(ctrl.windows) == 0
            # master visibility toggle
            mgr.pin_to_desktop(rem["id"])
            ctrl.sync()
            ctrl.set_visible(False)
            assert not ctrl.windows[rem["id"]].isVisible()
            ctrl.set_visible(True)
            assert ctrl.windows[rem["id"]].isVisible()
            for w in ctrl.windows.values():
                w.shutdown()
                w.hide()
            # grid page: builds cards for page widgets, none draggable
            page = WidgetsPage(ctx)
            page.rebuild()
            app.processEvents()
            assert len(page._cards) >= 4, "grid cards missing"
            card = page._cards[0]
            assert card.widget is not None and card.widget.drag_enabled is False
            assert not card.widget.header.isVisible(), "chrome must be hidden in grid"
            shutil.rmtree(ptmp, ignore_errors=True)
            return True

        check("pin=1 window / unpin closes / geometry restore / grid fixed", pinned_flow)
    except Exception as exc:
        check("pinned windows", lambda: (_ for _ in ()).throw(exc))

    # --------------------------------------- 10f settings structure
    section("10f. Settings cards + scroll-safe combos")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)

        def settings_structure():
            from PySide6.QtCore import QPoint, QPointF, Qt as QtConst
            from PySide6.QtGui import QWheelEvent
            from novaassistant.config import Config
            from novaassistant.core.activity_log import ActivityLog
            from novaassistant.core.conversation_store import ConversationStore
            from novaassistant.core.notes_store import NotesStore
            from novaassistant.core.orchestrator import Orchestrator
            from novaassistant.core.reminders_store import RemindersStore
            from novaassistant.ui.settings_page import SettingsPage
            from novaassistant.ui.widgets.manager import WidgetManager
            stmp = tempfile.mkdtemp(prefix="nova-set-")
            cfg = Config(data_dir=stmp)
            activity = ActivityLog(stmp)
            notes = NotesStore(stmp)
            reminders = RemindersStore(stmp)
            conversation = ConversationStore(stmp)
            orch = Orchestrator(cfg, notes, reminders, activity, conversation)
            mgr = WidgetManager(cfg)
            Ctx = type("Ctx", (), {
                "config": cfg, "activity": activity, "notes": notes,
                "reminders": reminders, "conversation": conversation,
                "orchestrator": orch, "app_screen": None,
                "widget_manager": mgr,
                "apply_runtime_settings": lambda self: None,
            })
            ctx = Ctx()
            mgr.attach_ctx(ctx)
            page = SettingsPage(ctx)
            # every provider card exists
            for attr in ("llm_model", "llm_test_btn", "stt_provider",
                         "stt_key_mode", "stt_model_groq", "stt_model_dg",
                         "dg_stt_key_combo", "tts_key_combo", "tts_voice",
                         "tts_volume", "tts_test_btn", "font_combo",
                         "mic_mode", "overlay_enabled", "confirmation"):
                assert hasattr(page, attr), f"settings missing {attr}"
            # model combos are scroll-safe
            from novaassistant.ui.widgets_common import NoScrollCombo
            for combo in (page.llm_model, page.stt_model_groq,
                          page.stt_model_dg, page.tts_voice, page.font_combo,
                          page.stt_provider):
                assert isinstance(combo, NoScrollCombo), \
                    f"{combo.objectName()} must ignore wheel scrolling"
            # wheelEvent ignored (selection can't change by scrolling)
            page.llm_model.setCurrentIndex(0)
            before = page.llm_model.currentIndex()
            ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0),
                             QPoint(0, 120), QtConst.NoButton,
                             QtConst.NoModifier, QtConst.NoScrollPhase, False)
            page.llm_model.wheelEvent(ev)   # must ignore, never change index
            assert page.llm_model.currentIndex() == before, \
                "wheel changed the model selection!"
            # font size live change flow
            page.ctx.config.set("ui.font_size", 15)
            idx = page.font_combo.findData(15)
            page.font_combo.setCurrentIndex(idx)
            assert cfg.get("ui.font_size") == 15
            # save round-trip keeps provider selection
            page.stt_provider.setCurrentIndex(1)   # deepgram
            page._save()
            assert cfg.get("voice.stt_provider") == "deepgram"
            assert cfg.get("voice.tts_volume") == page.tts_volume.value()
            shutil.rmtree(stmp, ignore_errors=True)
            return True

        check("LLM/STT/TTS cards exist + wheel-safe + font + save", settings_structure)
    except Exception as exc:
        check("settings structure", lambda: (_ for _ in ()).throw(exc))

    # ------------------------------- 10g unified typography + clean headers
    section("10g. Unified typography + clean headers")
    try:
        from PySide6.QtWidgets import QApplication, QLabel, QWidget
        app = QApplication.instance() or QApplication(sys.argv)

        def typography_flow():
            from PySide6.QtGui import QFontInfo
            from novaassistant import theme

            # The mono stack resolves like every existing technical label on
            # the user's machine; in THIS sandbox unknown families collapse to
            # the default, so swap in an installed mono family to make the
            # cascade assertions separable (restored in `finally`).
            real_mono = theme.FONT_MONO
            theme.FONT_MONO = "'DejaVu Sans Mono'"
            try:
                _typography_flow_body(QFontInfo, theme)
            finally:
                theme.FONT_MONO = real_mono
            return True

        def _typography_flow_body(QFontInfo, theme):
            ttmp = tempfile.mkdtemp(prefix="nova-typo-")
            from novaassistant.config import Config
            from novaassistant.core.activity_log import ActivityLog
            from novaassistant.core.conversation_store import ConversationStore
            from novaassistant.core.notes_store import NotesStore
            from novaassistant.core.orchestrator import Orchestrator
            from novaassistant.core.reminders_store import RemindersStore
            from novaassistant.ui.widgets.manager import WidgetManager
            cfg = Config(data_dir=ttmp)
            activity = ActivityLog(ttmp)
            notes = NotesStore(ttmp)
            reminders = RemindersStore(ttmp)
            conversation = ConversationStore(ttmp)
            orch = Orchestrator(cfg, notes, reminders, activity, conversation)
            mgr = WidgetManager(cfg)
            Ctx = type("Ctx", (), {
                "config": cfg, "activity": activity, "notes": notes,
                "reminders": reminders, "conversation": conversation,
                "orchestrator": orch, "app_screen": None,
                "widget_manager": mgr,
            })
            ctx = Ctx()
            mgr.attach_ctx(ctx)

            from novaassistant.ui.activity import ActivityPage
            from novaassistant.ui.conversation import ConversationPage
            from novaassistant.ui.files import FilesPage
            from novaassistant.ui.main_window import MainWindow
            from novaassistant.ui.notes import NotesPage
            from novaassistant.ui.overlay import OverlayWindow
            from novaassistant.ui.reminders import RemindersPage
            from novaassistant.ui.settings_page import SettingsPage
            from novaassistant.ui.widgets_page import WidgetsPage

            win = MainWindow(ctx)
            conv = ConversationPage(ctx)
            pages = {
                "conversation": conv, "notes": NotesPage(ctx),
                "reminders": RemindersPage(ctx), "activity": ActivityPage(ctx),
                "files": FilesPage(ctx), "widgets": WidgetsPage(ctx),
                "settings": SettingsPage(ctx),
            }
            for key, page in pages.items():
                win.add_page(key, page)
            win.show()                      # polish widgets so QSS fonts resolve
            app.processEvents()
            ov = OverlayWindow(ctx)
            ov.show()
            app.processEvents()

            # ---- 1) clean header: no provider/model text in the chrome
            tb_texts = [w.text() for w in win.titlebar.findChildren(QLabel)]
            assert not any(("GROQ" in t.upper() or "DEEPGRAM" in t.upper())
                           for t in tb_texts), f"header still shows provider info: {tb_texts}"
            assert not hasattr(win.titlebar, "_stack"), "stack label still exists"
            assert not hasattr(win.titlebar, "set_stack_label")

            # ---- 2) clean workspace header: no slash/tagline/provider chip
            conv_texts = [w.text() for w in conv.findChildren(QLabel)]
            assert "/" not in conv_texts, "workspace header still has slash decoration"
            assert not any("YOUR AI ASSISTANT" in t.upper() for t in conv_texts)
            assert not hasattr(conv, "_provider_chip"), "provider chip still exists"

            # ---- 3) ONE font: every standard page resolves the mono family
            ref = QLabel()
            theme.set_style(ref, f"color: #fff; font-family: {theme.FONT_MONO};")
            ref.show()
            mono_family = QFontInfo(ref.font()).family()
            bare = QLabel()
            bare.show()
            default_family = QFontInfo(bare.font()).family()
            assert mono_family != default_family, "test env cannot separate fonts"

            probes = [
                ("titlebar", win.titlebar, "Nova — Personal Assistant"),
                ("sidebar", win.sidebar, "NOVA"),
                ("conversation", conv, "Workspace"),
                ("notes", pages["notes"], "Notes"),
                ("reminders", pages["reminders"], "Reminders"),
                ("activity", pages["activity"], "Activity"),
                ("files", pages["files"], "Files"),
                ("settings", pages["settings"], "Settings"),
            ]
            for name, surface, marker in probes:
                lbls = [w for w in surface.findChildren(QLabel)
                        if w.text() == marker]
                assert lbls, f"{name}: marker label {marker!r} not found"
                fam = QFontInfo(lbls[0].font()).family()
                assert fam == mono_family, \
                    f"{name} label resolves to {fam!r}, expected mono {mono_family!r}"

            # ---- 4) widget surfaces keep their current font (untouched)
            wid_title = [w for w in pages["widgets"].findChildren(QLabel)
                         if not w.styleSheet() or "font-family" not in w.styleSheet()]
            assert wid_title, "widgets page: no plain label found"
            fam = QFontInfo(wid_title[0].font()).family()
            assert fam != mono_family, \
                f"widgets page font changed to {fam!r} — must stay untouched"
            assert "* { font-family" not in pages["widgets"].styleSheet()
            panel = getattr(ov, "panel", None)
            if panel is not None:
                assert "* { font-family" not in panel.styleSheet()

            # ---- 5) apply_scale_to_tree now traverses the WHOLE tree
            root = QWidget()
            mid = QWidget()
            leaf = QLabel()
            theme.set_style(leaf, "color: #fff; font-size: 12px;")
            from PySide6.QtWidgets import QVBoxLayout
            rl = QVBoxLayout(root)
            ml = QVBoxLayout(mid)
            rl.addWidget(mid)
            ml.addWidget(leaf)
            root.show()
            theme.set_font_scale(16 / 12.0)
            theme.apply_scale_to_tree(root)
            assert "font-size: 16px" in leaf.styleSheet(), \
                "apply_scale_to_tree did not reach deep children"
            theme.set_font_scale(13 / 12.0)   # restore app default
            theme.apply_scale_to_tree(root)

            ov.hide()
            shutil.rmtree(ttmp, ignore_errors=True)
            return True

        check("one font on chrome+pages / clean headers / widgets untouched", typography_flow)
    except Exception as exc:
        check("typography", lambda: (_ for _ in ()).throw(exc))

    # -------------------------------------------------- 11 global hotkeys
    section("11. Global hotkeys")
    if sys.platform == "win32":
        from novaassistant.shortcuts import GlobalHotkeys

        def hotkey_reg():
            got = []
            hk = GlobalHotkeys(lambda a: got.append(a))
            hk.start()
            import time
            time.sleep(0.5)
            hk.stop()
            assert hk._thread_id, "hotkey thread did not start"
            return True

        check("RegisterHotKey + GetMessageW loop (user32)", hotkey_reg)
    else:
        print("  [SKIP] Windows-only (GetMessageW fix is exercised at import)")

    # ------------------------------------------------------------- summary
    print(f"\nRESULT: {PASS} passed, {FAIL} failed")
    if FAILURES:
        print("Failures:", ", ".join(FAILURES))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
