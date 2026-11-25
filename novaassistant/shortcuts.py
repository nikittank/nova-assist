"""Global hotkeys + in-app shortcut handling.

FIXES:
1. `AttributeError: function 'GetMessageW' not found`
   GetMessageW is exported by USER32.DLL, not kernel32.dll. The old code did
   `kernel32.GetMessageW(...)`. This module binds user32 and also guards for
   failure gracefully.

2. `TypeError: KeyEvent.matches called with wrong argument types`
   `event.matches(QKeySequence(...))` is not a valid PySide6 signature —
   QKeySequence.matches() takes another QKeySequence. Use `matches(event)`
   helper below which compares sequences the correct way round.
"""
from __future__ import annotations

import sys
import threading

IS_WINDOWS = sys.platform == "win32"

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_SPACE = 0x20
VK_O = 0x4F
VK_N = 0x4E
VK_B = 0x42


class GlobalHotkeys:
    """Windows RegisterHotKey-based global listener (threaded, safe fallbacks)."""

    HOTKEYS = {
        # id: (modifiers, virtual_key, action_name)
        1: (MOD_CONTROL, VK_SPACE, "toggle_listening"),        # Ctrl+Space PTT
        2: (MOD_CONTROL | MOD_SHIFT, VK_O, "toggle_overlay"),  # Ctrl+Shift+O
        3: (MOD_CONTROL | MOD_SHIFT, VK_N, "new_note"),        # Ctrl+Shift+N
        4: (MOD_CONTROL | MOD_SHIFT, VK_B, "pin_widgets"),     # Ctrl+Shift+B
    }

    def __init__(self, callback):
        # callback(action_name: str)
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._started = threading.Event()
        self._registered: list[int] = []
        self._failed: list[int] = []

    # -------------------------------------------------------------- api
    def start(self) -> None:
        if not IS_WINDOWS:
            return                      # silently no-op off Windows
        if self._thread and self._thread.is_alive():
            return
        self._started.clear()
        self._thread = threading.Thread(
            target=self._run, name="nova-global-hotkeys", daemon=True)
        self._thread.start()
        self._started.wait(timeout=3)

    def stop(self) -> None:
        if not IS_WINDOWS or self._thread is None:
            return
        try:
            import ctypes
            if self._thread_id:
                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, WM_QUIT, 0, 0)
        except Exception:
            pass
        self._thread.join(timeout=2)
        self._thread = None

    # ------------------------------------------------------ windows impl
    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._thread_id = kernel32.GetCurrentThreadId()

        # RegisterHotKey(hwnd=None -> thread-level hotkey, id, mods, vk)
        for hotkey_id, (mods, vk, _action) in self.HOTKEYS.items():
            if user32.RegisterHotKey(None, hotkey_id, mods, vk):
                self._registered.append(hotkey_id)
            else:
                self._failed.append(hotkey_id)

        self._started.set()

        msg = wintypes.MSG()
        # ------------------------------------------------------------
        # THE FIX: GetMessageW belongs to user32 (previous code called
        # kernel32.GetMessageW -> AttributeError crash).
        # ------------------------------------------------------------
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                info = self.HOTKEYS.get(msg.wParam)
                if info:
                    try:
                        self._callback(info[2])
                    except Exception:
                        pass
            elif msg.message == WM_QUIT:
                break

        for hotkey_id in self._registered:
            user32.UnregisterHotKey(None, hotkey_id)
        self._registered.clear()


# ------------------------------------------------------------- in-app keys
def _flag_int(value) -> int:
    """PySide6 version-proof int conversion for Qt flag/enum objects."""
    try:
        return int(value)
    except TypeError:
        pass
    v = getattr(value, "value", None)
    if v is not None:
        return int(v)
    try:
        return sum(int(getattr(x, "value", x)) for x in value)
    except Exception:
        return 0


def normalize_event(event) -> tuple[int, int]:
    """(modifiers, key) for a QKeyEvent, keypad noise stripped."""
    try:
        from PySide6.QtCore import Qt
        mask = _flag_int(Qt.ShiftModifier) | _flag_int(Qt.ControlModifier) | \
            _flag_int(Qt.AltModifier) | _flag_int(Qt.MetaModifier)
        mods = _flag_int(event.modifiers()) & mask
        return mods, _flag_int(event.key())
    except Exception:
        return 0, 0


def event_matches(event, combo: str) -> bool:
    """Exact match of a QKeyEvent against 'Ctrl+Space'-style combo strings.

    Correct replacement for the old crashing pattern:
        event.matches(QKeySequence("Ctrl+Space"))   # <- TypeError
    QKeySequence.matches() expects ANOTHER QKeySequence, not to be called on
    the event; here we do: seq_combo.matches(seq_from_event) == ExactMatch,
    with a manual modifier-mask fallback that also normalizes the
    Enter/Return split (QKeySequence("Ctrl+Enter") binds the KEYPAD enter,
    while real Ctrl+Enter presses emit Key_Return — both must match).
    """
    try:
        from PySide6.QtGui import QKeySequence

        seq = QKeySequence(combo)
        event_seq = QKeySequence(event.keyCombination())  # PySide6 >= 6.4
        if seq.matches(event_seq) == QKeySequence.SequenceMatch.ExactMatch:
            return True
    except Exception:
        pass
    # manual fallback (always attempted when primary check failed)
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence

        mods, key = normalize_event(event)
        want_mods = 0
        text = combo.lower()
        if "ctrl" in text:
            want_mods |= _flag_int(Qt.ControlModifier)
        if "shift" in text:
            want_mods |= _flag_int(Qt.ShiftModifier)
        if "alt" in text:
            want_mods |= _flag_int(Qt.AltModifier)
        if "meta" in text:
            want_mods |= _flag_int(Qt.MetaModifier)
        items = QKeySequence(combo)
        if not items:
            return False
        want_key = _flag_int(items[0].key())
        if not _same_key(key, want_key):
            return False
        return mods == want_mods
    except Exception:
        return False


def _same_key(a: int, b: int) -> bool:
    if a == b:
        return True
    # Enter aliases: main Return (0x1000004) and keypad Enter (0x1000005)
    return {a, b} == {0x1000004, 0x1000005}
