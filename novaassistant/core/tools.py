"""Desktop automation tools: open apps/folders/files/URLs, list directories."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser

IS_WINDOWS = sys.platform == "win32"

# Common app aliases for "open spotify" style commands
APP_ALIASES = {
    "spotify": ["spotify"],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "calc": ["calc.exe"],
    "paint": ["mspaint.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "terminal": ["cmd.exe"],
    "powershell": ["powershell.exe"],
    "task manager": ["taskmgr.exe"],
    "settings": ["ms-settings:"],
    "vscode": ["code"],
    "vs code": ["code"],
    "code": ["code"],
    "chrome": ["chrome"],
    "edge": ["msedge"],
    "firefox": ["firefox"],
    "word": ["winword"],
    "excel": ["excel"],
    "powerpoint": ["powerpnt"],
    "outlook": ["outlook"],
}

USER_DIRS = ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"]


def _home_dir(name: str) -> str:
    return os.path.join(os.path.expanduser("~"), name)


def resolve_folder(name: str) -> str | None:
    """Resolve 'downloads' / 'documents' style names to real paths."""
    n = (name or "").strip().lower().rstrip("\\/")
    for d in USER_DIRS:
        if n == d.lower() or n.endswith("\\" + d.lower()) or n == d.lower()[:-1]:
            path = _home_dir(d)
            if os.path.isdir(path):
                return path
    if os.path.isdir(name or ""):
        return os.path.abspath(name)
    return None


def resolve_app(name: str) -> str | None:
    n = (name or "").strip().lower()
    return (APP_ALIASES.get(n) or [None])[0]


def open_folder(path: str) -> dict:
    """Open a folder in the OS file manager."""
    target = resolve_folder(path) or path
    if not os.path.isdir(target):
        return {"ok": False, "error": f"Folder not found: {target}"}
    try:
        if IS_WINDOWS:
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
        return {"ok": True, "detail": f"Opened folder {target}", "path": target}
    except Exception as exc:
        return {"ok": False, "error": f"Could not open folder: {exc}"}


def open_app(name: str) -> dict:
    """Launch an application by friendly name."""
    exe = resolve_app(name)
    if not exe:
        return {"ok": False, "error": f"Unknown application: {name}"}
    try:
        if IS_WINDOWS:
            os.startfile(exe)  # type: ignore[attr-defined]
        else:
            subprocess.Popen([exe])
        return {"ok": True, "detail": f"Opened {name}"}
    except Exception as exc:
        return {"ok": False, "error": f"Could not open {name}: {exc}"}


def open_url(url: str) -> dict:
    if not url:
        return {"ok": False, "error": "No URL provided"}
    if not url.startswith(("http://", "https://", "file://")):
        url = "https://" + url
    try:
        webbrowser.open(url)
        return {"ok": True, "detail": f"Opened {url}"}
    except Exception as exc:
        return {"ok": False, "error": f"Could not open URL: {exc}"}


def open_path(path: str) -> dict:
    """Open any file or folder with the OS default handler."""
    expanded = os.path.expanduser(path or "")
    if os.path.isdir(expanded):
        return open_folder(expanded)
    if os.path.isfile(expanded):
        try:
            if IS_WINDOWS:
                os.startfile(expanded)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", expanded])
            else:
                subprocess.Popen(["xdg-open", expanded])
            return {"ok": True, "detail": f"Opened {os.path.basename(expanded)}"}
        except Exception as exc:
            return {"ok": False, "error": f"Could not open file: {exc}"}
    return {"ok": False, "error": f"Path not found: {path}"}


def list_dir(path: str = "~") -> dict:
    target = os.path.expanduser(path or "~")
    if not os.path.isdir(target):
        return {"ok": False, "error": f"Folder not found: {path}"}
    try:
        entries = sorted(os.listdir(target))[:200]
        return {"ok": True, "detail": f"{len(entries)} items in {target}",
                "entries": entries, "path": target}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def home_path(name: str) -> str:
    return _home_dir(name)
