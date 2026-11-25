"""Desktop notifications with graceful cross-platform fallbacks.

Order of preference:
  1. plyer (pure-python wrapper over the native notification centre)
  2. notify-send (Linux)
  3. osascript (macOS)
  4. Windows toast via PowerShell
The UI always shows an in-app banner as well, so a failed system
notification is never silent inside the app.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Optional

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


def _plyer_notify(title: str, body: str) -> bool:
    try:
        from plyer import notification
        notification.notify(
            title=title[:64],
            message=body[:240],
            app_name="Nova Assistant",
            timeout=6,
        )
        return True
    except Exception:
        return False


def _notify_send(title: str, body: str) -> bool:
    if not IS_LINUX:
        return False
    try:
        proc = subprocess.run(
            ["notify-send", "-a", "Nova Assistant", title[:64], body[:240]],
            timeout=8, capture_output=True,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _osascript_notify(title: str, body: str) -> bool:
    if not IS_MACOS:
        return False
    try:
        script = (
            f'display notification "{body[:180].replace(chr(34), chr(39))}" '
            f'with title "{title[:60].replace(chr(34), chr(39))}"'
        )
        subprocess.run(["osascript", "-e", script], timeout=8, capture_output=True)
        return True
    except Exception:
        return False


def _powershell_toast(title: str, body: str) -> bool:
    if not IS_WINDOWS:
        return False
    try:
        ps = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] | Out-Null; "
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            f"$t.GetElementsByTagName('text').Item(0).AppendChild($t.CreateTextNode('{title[:60]}')) | Out-Null; "
            f"$t.GetElementsByTagName('text').Item(1).AppendChild($t.CreateTextNode('{body[:180]}')) | Out-Null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($t); "
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
            "'Nova Assistant').Show($toast)"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            timeout=12, capture_output=True,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        return True
    except Exception:
        return False


def notify(title: str, body: str) -> Optional[str]:
    """Fire a desktop notification. Returns the backend used, or None."""
    for name, fn in (
        ("plyer", _plyer_notify),
        ("notify-send", _notify_send),
        ("osascript", _osascript_notify),
        ("powershell", _powershell_toast),
    ):
        try:
            if fn(title, body):
                return name
        except Exception:
            continue
    return None
