# Nova — Personal Desktop Assistant (v2.10 "Pitch Black")

A black, minimal, futuristic desktop assistant for Windows built with PySide6.
The UI is a 1:1 replication of the uploaded `nova_*_pitch_black.html` mockups —
same layout, same colors, same typography, same components.

```
python main.py
```

> Python 3.10+ required. Install deps first: `pip install -r requirements.txt`

---

## What changed in v2.10 (wiring + state management + UI behavior)

- **Conversation flow #1** — the orchestrator now adds the user message to the
  conversation store BEFORE running the pipeline, so the user message always
  appears before the AI response. Live states (Listening / Transcribing /
  Thinking / Executing / Speaking / Done) animate in the conversation header.
  Raw errors never appear in the chat — a friendly banner with an expandable
  Details section is used instead, and the full traceback always goes to the
  Activity log. TTS never speaks technical information (file names, paths,
  tool names, URLs) — a sanitizer strips them before synthesis.
- **STT / TTS / LLM controls #2** — LLM is ALWAYS enabled (it is the core
  reasoning engine) with an "ALWAYS ON" badge instead of a toggle. New
  Enable/Disable STT and Enable/Disable TTS toggles in Settings live-apply
  to the orchestrator the instant you change them.
- **Microphone controls #3** — added an explicit mic Enable/Disable master
  switch and three modes: Off (no listening), Continuous (hands-free VAD) and
  Push-to-Talk (hold Ctrl+Space). The states do not conflict; PTT never
  re-opens the mic automatically.
- **VAD behavior #4** — VAD only runs in Continuous mode. PTT = no continuous
  VAD. Mic OFF = no STT/VAD processing. Changing the mode in Settings takes
  effect immediately on the actual microphone behavior.
- **API status header #5** — a three-dot status cluster in the workspace
  header (LLM / STT / TTS) shows compact Connected / Disabled / Error
  states. Click opens a popover with per-service details and a Diagnostics
  button that jumps to Settings. Long provider/model text never lives in
  the header.
- **Activity wiring #6** — every action is now logged with a timestamp and
  status (ok / err / cancel), source (user / ai / system) and target. A
  dedupe flag collapses rapid identical state updates so the audit stream
  stays clean. The Activity page shows cancellations as a separate counter.
- **Files page #7** — completely redesigned as a professional file manager:
  drive selector, Back / Forward / Up navigation with history, clickable
  breadcrumb path, live search filter, and double-click-to-open folders.
  No longer locked to `C:\` — starts at the user's home folder and supports
  every available drive.
- **Focus widget #8** — the always-visible Clear button is GONE. Editing
  happens through the Edit button, which opens a dialog with change-focus,
  save and clear actions in one place.
- **Quick Notes widget #9** — now parses `# Title` as the note title and the
  text after it as the note content. Uses the SAME notes store as the Notes
  page (no separate Quick Notes storage system). The widget shows the actual
  most-recent notes saved from anywhere in Nova.
- **AI Status widget preview #10** — the management-page preview card now
  uses fixed-height rows with consistent alignment, matching the other widget
  cards. The pinned desktop widget design is unchanged.
- **Settings alignment #11** — every form row uses a consistent 200px label
  width, consistent spacing, consistent input/combo heights and consistent
  card padding. Settings now feels like a professional production app.
- **Clean headings #12** — removed every decorative slash from headings and
  labels (`GROQ // WHISPER` → `GROQ WHISPER`, `Overlay & Desktop` →
  `Overlay Desktop`, etc.). Clean typography replaces slash-based visual
  separation.
- **Lively conversation UI #13** — added an animated `LiveStateStrip` above
  the input console that pulses while the pipeline is active, a `StatePulse`
  dot in the header, and a moving-highlight progress bar. User and AI
  messages remain visually distinct and appear in the correct order.
- **Compact overlay #14** — when the main Nova window is minimized, the
  overlay switches to a DEDICATED compact floating UI (not a scaled-down
  copy of the full overlay): Nova identity, status dot, mini waveform,
  current task, expand / mic / stop buttons. It stays usable while you work
  in other apps. Expanding returns to the full overlay.
- **Final wiring check #15** — the complete pipeline is verified by an
  automated test suite (see `test_pipeline.py`): STT → Conversation → LLM →
  Tools → Activity → TTS, plus PTT, VAD, mic start/stop, STT/TTS enable/
  disable, LLM-always-active, API status, Notes, Reminders, Files, Widgets,
  Overlay, Settings and keyboard shortcuts.

## What changed in v2.9 (unified typography + clean headers)

- **ONE font everywhere.** The entire application shell — titlebar, sidebar,
  Conversation, Notes, Reminders, Activity, Files, Settings, every button,
  label, input, message, card, date/time and status text — now uses the same
  technical typeface as the header/technical UI (JetBrains Mono stack).
  One font → one typography → one visual language.
- **Desktop widgets and the AI overlay are untouched** — they keep their exact
  current fonts and design (enforced by automated tests and byte-identical
  sources).
- **Clean minimal header.** The top bar now shows only the app identity, a
  status dot and the clock — the `GROQ / DEEPGRAM` provider text was removed
  (provider details live in Settings and on the Conversation tiles).
- **Clean Workspace header.** `/ Workspace  YOUR AI ASSISTANT. ON YOUR
  DESKTOP.` and the provider chip are gone — just `Workspace` and the status
  tiles.
- **Font-size setting now rescales every control live** (a traversal bug in
  the rescale pass was found and fixed while unifying typography).

## What was FIXED (your reported bugs)

| # | Bug | Fix |
|---|-----|-----|
| 1 | `AttributeError: function 'GetMessageW' not found` crash in `shortcuts.py` | `GetMessageW` is exported by **user32.dll**, not kernel32. The global-hotkey thread now binds `ctypes.WinDLL("user32")` and calls `user32.GetMessageW(...)` (see `novaassistant/shortcuts.py`). |
| 2 | `Audio playback failed: module 'sounddevice' has no attribute 'is_playing'` | `sounddevice.is_playing` **does not exist**. Playback state is tracked by `AudioPlayer` itself (generation counter + own flag + `stream.active`) — play/stop/restart is fully reliable (see `novaassistant/audio/playback.py`). |
| 3 | `TypeError: KeyEvent.matches called with wrong argument types` | `event.matches(QKeySequence(...))` is not a valid signature. `shortcuts.event_matches()` compares sequences the correct way round **and** normalizes the Qt Enter/Return split (`QKeySequence("Ctrl+Enter")` binds keypad-Enter while keyboards emit Key_Return — both now match). |
| 4 | Editing a note and saving created a duplicate | The Notes editor tracks `_editing_id`; **Save routes to `update(existing_id)`** and `create()` only runs for brand-new notes. Topic/category (e.g. `bucket`) is preserved unless you explicitly change it. Covered by an automated test. |

## Features

### Keyboard shortcuts
- **Ctrl+Space** — global push-to-talk / toggle listening (works in ANY app)
- **Ctrl+Enter or Enter** — send in Conversation, Overlay, Widgets & Desktop-widget inputs
- **Enter** — natural behavior in note title (jumps to content), note content (newline), reminder field (adds)
- **Ctrl+S** — save note, **Esc** — cancel note edit
- **Ctrl+Shift+O** — global AI Overlay toggle · **Ctrl+Shift+N** — new note · **Ctrl+Shift+B** — pin desktop widgets

### Voice pipeline (complete flow)
`Mic capture → VAD end-of-speech detection → STT → full transcript → Groq LLM (tool calls) → execute + verify → final response → Deepgram Aura TTS`
- STT: **Groq Whisper Large V3 Turbo** or **Deepgram Nova-3** — switchable in Settings → Voice
- VAD waits until you finish speaking (adaptive noise floor, configurable silence window & sensitivity) — never cuts you off early
- Listening never starts while TTS is playing (pending-listen queue)

### Conversation
Natural commands via LLM tool-calling: open apps/folders/URLs, create / **edit existing** / delete / search notes, create / list / complete / delete reminders with computed datetimes, get current time. Errors render as a friendly one-line banner — the technical traceback stays **collapsed** behind a Details button (Copy included), and full details are always written to the Activity log, never spammed into the chat. A global exception hook catches anything unhandled and logs it instead of crashing.

### Notes
Full CRUD. Selecting a note loads it into the editor; Save **updates that exact note**. Search box filters live.

### Reminders
- **Microphone button next to the text field** — say *"Remind me tomorrow at 6 PM to call John every Monday"* and it extracts + shows text / date / time / repeat before saving
- Add / Edit / Delete / Complete / Snooze (5 min) / change date, time, repeat, content
- Local NL parser (works without API keys) + repeating reminders auto-reschedule

### Settings — AI Models Providers
Separate configuration per feature, exactly as requested:
- **GROQ LLM** — multiple keys (custom name, enable/disable, Test, Set Active, Remove) + model selector. The LLM is ALWAYS enabled — no on/off switch (it is the core reasoning engine).
- **GROQ WHISPER STT** — Enable/Disable toggle, reuse the LLM key or a separate key + Whisper model selector
- **DEEPGRAM NOVA STT** — separate key + Nova-3/Nova-2 + language
- **DEEPGRAM AURA TTS** — Enable/Disable toggle, separate key + Aura voice selector
- Usage chips show exactly which provider/model/key serves every feature

### Widgets — independent, individually managed tiles
Widgets are **separate, independent cards** — not one big dashboard. Eight types:

| Widget | What it does |
|--------|--------------|
| Clock / Time | shows ONLY the time (12/24 h, seconds, text size) |
| Date | shows ONLY the date (long / medium / ISO / numeric format) |
| What's Today | tasks due today + overdue (complete inline), notes created today |
| Focus | your current focus task — inline Edit button, one-click Clear |
| Quick Notes | fast capture into the real notes store + recent list |
| Reminders | live reminders with complete / snooze / edit / delete + quick add |
| AI Status | live NOVA / LLM / STT / TTS provider status |
| Task / AI Activity | current AI operation + pipeline steps + recent audit rows |

Every widget card has its own **Edit** button, **Settings** dialog, **Minimize/Collapse**,
**Close**, drag-to-move (8 px snap) and corner **resize grip**. Right-click a widget for:
bring to front · move to Widgets page · **pin to desktop** · **pin in overlay** · reset size · remove.

The Widgets page toolbar offers **Add Widget** (menu of all types), **Pin to desktop**
(a frameless always-on-top desktop canvas hosting `desktop` widgets) and **Reset layout**.
Widget layout (position, size, collapse, per-widget settings, surface, overlay pins) is
**saved automatically and restored after restarting Nova**.

### Responsive layout
- Sidebar auto-collapses to an icon rail at small widths (manual toggle in the titlebar)
- Stat tiles, hint chips, form fields and cards **wrap** instead of overlapping (custom flow layout)
- Notes uses a resizable splitter; lists use deterministic fixed-height rows (no clipping)
- Window size/position persists; minimum window 940×620; high-DPI pass-through scaling

### AI Overlay (operational layer)
Frameless, draggable, **always-on-top** right-side panel that stays above Chrome / VS Code / anything (WindowStaysOnTopHint + periodic `SetWindowPos(HWND_TOPMOST)` on Windows). Shows: NOVA // ONLINE status, LISTENING / THINKING / EXECUTING / SPEAKING, live voice waveform, your full STT transcript, Nova's response, UNDERSTAND/PLAN/EXECUTE/SIMPLIFY stage, SYSTEM PIPELINE multi-step progress (✓ Done / ● Active / Queued), mic + stop/cancel + quick input. Toggle: sidebar, tray, or Ctrl+Shift+O.
Widgets **pinned in overlay** appear as compact mirrors in a collapsible strip at the bottom.
Double-click the overlay (or its ❯ button) to collapse it to a tiny pill; double-click again to restore.

### Background & startup
System tray (Show / Listen / Overlay / Widgets / Quit), close-to-tray, start-minimized, and optional "Start with Windows".

## Data & keys
Everything is stored locally in `~/.nova-assistant/` (`config.json`, `notes.json`, `reminders.json`, `conversation.json`, `activity.json`). API keys never leave your machine except to their own provider (api.groq.com / api.deepgram.com).

## Self-test

```
python selftest.py
```

Runs 18 real check groups: imports, config provider routing, notes edit-in-place, reminders CRUD/snooze/repeat, the NL reminder parser suite, shortcut matching (incl. the Enter/Return normalization), audio playback state machine, VAD end-of-speech, live Groq/Deepgram key validation (when configured), **the widget system (manager CRUD / persistence / layout restore)**, **each of the 8 widget types against real store data**, a full offscreen UI boot of every page + overlay + widgets, **responsive checks at 1280 / 1040 / 940 widths**, and the global hotkey registration on Windows.

## Project layout

```
nova-assistant/
├── main.py                      # entry point (python main.py)
├── selftest.py                  # end-to-end self tests
├── requirements.txt
└── novaassistant/
    ├── config.py                # JSON config + multi-key provider store
    ├── theme.py                 # exact pitch-black tokens + QSS + palette
    ├── icons.py                 # inline lucide-style SVG icon engine
    ├── shortcuts.py             # global hotkeys (user32 fix) + key matching
    ├── audio/
    │   ├── capture.py           # mic capture + VAD utterances
    │   ├── playback.py          # TTS playback (is_playing fix)
    │   └── vad.py               # end-of-speech state machine
    ├── providers/
    │   ├── groq.py              # chat completions + Whisper STT + key test
    │   └── deepgram.py          # Nova-3 STT + Aura TTS + key test
    ├── core/
    │   ├── notes_store.py       # CRUD w/ update-in-place
    │   ├── reminders_store.py   # CRUD + snooze + repeat scheduling
    │   ├── reminder_parser.py   # NL datetime extraction
    │   ├── llm_tools.py         # tool schema + executor
    │   ├── orchestrator.py      # voice→STT→LLM→tools→TTS pipeline
    │   ├── scheduler.py         # reminder firing
    │   ├── activity_log.py / conversation_store.py / tools.py
    └── ui/
        ├── main_window.py       # frameless chrome + titlebar + collapsible sidebar
        ├── conversation.py / notes.py / reminders.py / activity.py
        ├── files.py / widgets_page.py / settings_page.py
        ├── flowlayout.py        # wrapping flow layout (responsive rows/tiles)
        ├── widgets/             # independent widget system
        │   ├── base.py          # WidgetBase chrome (edit/settings/collapse/close/drag)
        │   ├── manager.py       # lifecycle + layout persistence
        │   ├── clock.py / date_w.py / today.py / focus.py
        │   ├── quick_notes.py / reminders_w.py / ai_status.py / activity_w.py
        ├── settings_providers.py# multi-key manager rows
        ├── ai_panel.py          # AI Operating Layer surface
        ├── overlay.py           # always-on-top overlay + pinned-widget strip
        └── desktop_widgets.py   # one floating window per pinned widget
```

## Troubleshooting
- **No microphone detected** → check Windows mic privacy settings; the app surfaces device errors as an error card.
- **PortAudio error on import** → `pip install sounddevice` inside the same Python you run with.
- **Keys show "NO KEY"** → Settings → LLM / STT / TTS cards → add keys → press **Test** / **Use for …**.
- **A dropdown changed while scrolling** → it can't anymore; Nova combos ignore the wheel by design.
