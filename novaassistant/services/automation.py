"""Safe, controlled desktop automation handlers.

The LLM never gets raw shell/filesystem access.  It can only invoke the
whitelisted functions below, each of which validates its inputs, expands
paths safely, enforces size/time limits and returns a compact JSON result.

Every function returns a dict:  {"ok": bool, "message": str, ...extra}
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from send2trash import send2trash
except Exception:  # pragma: no cover
    send2trash = None

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

READ_CHUNK_LIMIT = 24000        # max chars returned to the LLM for a file
COMMAND_TIMEOUT = 45            # seconds
SEARCH_TIME_LIMIT = 12.0        # seconds
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "site-packages",
    "AppData", "$Recycle.Bin", "System Volume Information", "Library",
    ".cache", ".npm", ".cargo", "dist-packages", ".tox", ".mypy_cache",
}

APP_ALIASES = {
    # lowercase alias -> launch hint per-OS resolution happens at runtime
    "notepad": {"win": "notepad.exe"},
    "calculator": {"win": "calc.exe", "mac": "Calculator", "linux": "gnome-calculator"},
    "calc": {"win": "calc.exe", "mac": "Calculator", "linux": "gnome-calculator"},
    "paint": {"win": "mspaint.exe"},
    "explorer": {"win": "explorer.exe"},
    "file manager": {"linux": "nautilus", "mac": "Finder"},
    "files": {"linux": "nautilus", "mac": "Finder"},
    "terminal": {"win": "wt.exe", "mac": "Terminal", "linux": "x-terminal-emulator"},
    "cmd": {"win": "cmd.exe"},
    "task manager": {"win": "taskmgr.exe"},
    "settings": {"win": "ms-settings:", "mac": "System Settings", "linux": "gnome-control-center"},
    "browser": {"win": "msedge.exe", "mac": "Safari", "linux": "xdg-open"},
    "chrome": {"win": "chrome.exe", "mac": "Google Chrome", "linux": "google-chrome"},
    "edge": {"win": "msedge.exe", "mac": "Microsoft Edge", "linux": "microsoft-edge"},
    "firefox": {"win": "firefox.exe", "mac": "Firefox", "linux": "firefox"},
    "vscode": {"win": "code.exe", "mac": "Visual Studio Code", "linux": "code"},
    "vs code": {"win": "code.exe", "mac": "Visual Studio Code", "linux": "code"},
    "code": {"win": "code.exe", "mac": "Visual Studio Code", "linux": "code"},
    "word": {"win": "winword.exe", "mac": "Microsoft Word"},
    "excel": {"win": "excel.exe", "mac": "Microsoft Excel"},
    "powerpoint": {"win": "powerpnt.exe", "mac": "Microsoft PowerPoint"},
    "spotify": {"win": "spotify.exe", "mac": "Spotify", "linux": "spotify"},
    "vlc": {"win": "vlc.exe", "mac": "VLC", "linux": "vlc"},
    "discord": {"win": "discord.exe", "mac": "Discord", "linux": "discord"},
    "whatsapp": {"win": "whatsapp.exe", "mac": "WhatsApp", "linux": "whatsapp-for-linux"},
    "telegram": {"win": "telegram.exe", "mac": "Telegram", "linux": "telegram-desktop"},
    "steam": {"win": "steam.exe", "mac": "Steam", "linux": "steam"},
    "outlook": {"win": "outlook.exe", "mac": "Microsoft Outlook"},
    "mail": {"mac": "Mail", "linux": "evolution"},
    "notes": {"mac": "Notes", "linux": "gnome-notes"},
    "calendar": {"win": "outlookcal:", "mac": "Calendar", "linux": "gnome-calendar"},
    "clock": {"win": "timeout.exe", "mac": "Clock", "linux": "gnome-clocks"},
    "camera": {"mac": "Photo Booth"},
    "photos": {"mac": "Photos", "linux": "eog"},
    "music": {"mac": "Music", "linux": "rhythmbox"},
    "visual studio": {"win": "devenv.exe", "mac": "Visual Studio"},
    "pycharm": {"win": "pycharm64.exe", "mac": "PyCharm", "linux": "pycharm"},
    "intellij": {"win": "idea64.exe", "mac": "IntelliJ IDEA", "linux": "idea"},
    "git": {"linux": "git"},
    "steam client": {"win": "steam.exe"},
    "weather": {"linux": "gnome-weather"},
    "screenshot": {"linux": "gnome-screenshot"},
}


def _expand(path_str: str) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path_str))))


def _ok(message: str, **extra) -> dict:
    out = {"ok": True, "message": message}
    out.update(extra)
    return out


def _fail(message: str, **extra) -> dict:
    out = {"ok": False, "message": message}
    out.update(extra)
    return out


def _exists_msg(p: Path) -> dict:
    return _fail(f"Path does not exist: {p}")


# --------------------------------------------------------------------- apps
def open_application(app_name: str) -> dict:
    """Open a desktop application by friendly name."""
    if not app_name or not app_name.strip():
        return _fail("No application name given.")
    name = app_name.strip()
    key = name.lower()
    alias = APP_ALIASES.get(key, {}).get(
        "win" if IS_WINDOWS else "mac" if IS_MACOS else "linux"
    )
    target = alias or name

    try:
        if IS_WINDOWS:
            # 'start' resolves both executables on PATH and registered apps
            subprocess.Popen(["cmd", "/c", "start", "", target], shell=False,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        elif IS_MACOS:
            subprocess.Popen(["open", "-a", target],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            exe = shutil.which(target)
            if exe is None and " " not in target:
                # try common application launcher entries
                exe = shutil.which(f"{target}.desktop")
            if exe is None:
                return _fail(f"Application '{name}' was not found on this system.")
            subprocess.Popen([exe], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        return _ok(f"Opened {name}.")
    except Exception as exc:
        return _fail(f"Could not open {name}: {exc}")


def close_application(app_name: str) -> dict:
    """Ask/force an application to close by name."""
    name = app_name.strip()
    if not name:
        return _fail("No application name given.")
    try:
        if IS_WINDOWS:
            exe = name if name.lower().endswith(".exe") else f"{name}.exe"
            proc = subprocess.run(["taskkill", "/IM", exe, "/F"],
                                  capture_output=True, text=True, timeout=20)
            if proc.returncode == 0:
                return _ok(f"Closed {name}.")
            proc2 = subprocess.run(["taskkill", "/IM", name, "/F"],
                                   capture_output=True, text=True, timeout=20)
            return _ok(f"Closed {name}.") if proc2.returncode == 0 else _fail(
                f"Could not find a running application called {name}.")
        else:
            signal = ["-TERM"]
            proc = subprocess.run(["pkill", *signal, "-x", name],
                                  capture_output=True, text=True, timeout=20)
            if proc.returncode != 0:
                proc = subprocess.run(["pkill", *signal, "-f", name],
                                      capture_output=True, text=True, timeout=20)
            return _ok(f"Closed {name}.") if proc.returncode == 0 else _fail(
                f"Could not find a running application called {name}.")
    except Exception as exc:
        return _fail(f"Could not close {name}: {exc}")


def open_path(path: str) -> dict:
    """Open a file or folder with the OS default handler."""
    p = _expand(path)
    if not p.exists():
        return _exists_msg(p)
    try:
        if IS_WINDOWS:
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif IS_MACOS:
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        kind = "folder" if p.is_dir() else "file"
        return _ok(f"Opened {kind} {p.name}.")
    except Exception as exc:
        return _fail(f"Could not open {p}: {exc}")


# --------------------------------------------------------------------- files
def list_directory(path: str = "") -> dict:
    p = _expand(path) if path else Path.home()
    if not p.exists():
        return _exists_msg(p)
    if not p.is_dir():
        return _fail(f"Not a folder: {p}")
    try:
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
        items = []
        for e in entries[:120]:
            kind = "dir" if e.is_dir() else "file"
            size = ""
            if e.is_file():
                try:
                    size = f" ({e.stat().st_size} bytes)"
                except OSError:
                    pass
            items.append(f"{e.name} [{kind}]{size}")
        return _ok(f"Listed {len(items)} entries in {p}.", entries=items)
    except Exception as exc:
        return _fail(f"Could not list {p}: {exc}")


def search_files(query: str, directory: str = "", max_results: int = 20) -> dict:
    """Recursive filename search (case-insensitive substring match)."""
    if not query:
        return _fail("No search query given.")
    root = _expand(directory) if directory else Path.home()
    if not root.exists():
        return _exists_msg(root)
    max_results = max(1, min(int(max_results or 20), 50))
    needle = query.lower()
    found: list[str] = []
    start = time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        # prune heavy/irrelevant folders in-place
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        if time.time() - start > SEARCH_TIME_LIMIT:
            break
        for fn in filenames:
            if needle in fn.lower():
                found.append(str(Path(dirpath) / fn))
                if len(found) >= max_results:
                    break
        if len(found) >= max_results:
            break
    if not found:
        return _ok(f"No files matching '{query}' were found under {root}.", results=[])
    return _ok(f"Found {len(found)} match(es) for '{query}'.", results=found)


def read_file(path: str, max_chars: int = READ_CHUNK_LIMIT) -> dict:
    p = _expand(path)
    if not p.exists():
        return _exists_msg(p)
    if p.is_dir():
        return list_directory(path)
    max_chars = max(500, min(int(max_chars or READ_CHUNK_LIMIT), READ_CHUNK_LIMIT))
    try:
        suffix = p.suffix.lower()
        if suffix == ".pdf":
            return _read_pdf(p, max_chars)
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        total = len(text)
        excerpt = text[:max_chars]
        note = "" if total <= max_chars else f" ...[truncated, {total} chars total]"
        return _ok(f"Read {p.name} ({total} chars).", path=str(p), content=excerpt + note)
    except Exception as exc:
        return _fail(f"Could not read {p}: {exc}")


def _read_pdf(p: Path, max_chars: int) -> dict:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        parts = []
        count = 0
        for page in reader.pages:
            parts.append(page.extract_text() or "")
            count += 1
            if sum(len(x) for x in parts) > max_chars:
                break
        text = "\n".join(parts)[:max_chars]
        return _ok(f"Read PDF {p.name} ({len(reader.pages)} pages).",
                   path=str(p), content=text)
    except ImportError:
        return _fail("PDF reading needs the 'pypdf' package (pip install pypdf).")
    except Exception as exc:
        return _fail(f"Could not read PDF {p}: {exc}")


def create_text_file(path: str, content: str) -> dict:
    p = _expand(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        p.write_text(content, encoding="utf-8")
        verb = "overwrote" if existed else "created"
        return _ok(f"{verb.capitalize()} file {p} ({len(content)} chars).", path=str(p))
    except Exception as exc:
        return _fail(f"Could not write {p}: {exc}")


def append_to_file(path: str, content: str) -> dict:
    p = _expand(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return _ok(f"Appended {len(content)} chars to {p}.", path=str(p))
    except Exception as exc:
        return _fail(f"Could not append to {p}: {exc}")


def delete_path(path: str) -> dict:
    """Delete a file/folder, preferring recoverable strategies:
    1. OS trash/recycle bin (send2trash)
    2. Nova's own quarantine folder (~/.nova-assistant/trash)
    Never hard-deletes silently."""
    p = _expand(path)
    if not p.exists():
        return _exists_msg(p)
    if send2trash is not None:
        try:
            send2trash(str(p))
            return _ok(f"Moved {p} to the trash/recycle bin.")
        except Exception:
            pass  # fall through to quarantine
    try:
        trash_dir = Path.home() / ".nova-assistant" / "trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = str(int(time.time() * 1000))
        dest = trash_dir / f"{p.name}.{stamp}"
        shutil.move(str(p), str(dest))
        return _ok(f"Moved {p} to Nova's trash folder ({dest}).")
    except Exception as exc:
        return _fail(f"Could not delete {p}: {exc}")


def copy_file(source: str, destination: str) -> dict:
    src, dst = _expand(source), _expand(destination)
    if not src.exists():
        return _exists_msg(src)
    try:
        if dst.is_dir():
            dst = dst / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        overwritten = dst.exists()
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        verb = "Overwrote" if overwritten else "Copied"
        return _ok(f"{verb} {src} -> {dst}.", source=str(src), destination=str(dst))
    except Exception as exc:
        return _fail(f"Could not copy {src} -> {dst}: {exc}")


def move_file(source: str, destination: str) -> dict:
    src, dst = _expand(source), _expand(destination)
    if not src.exists():
        return _exists_msg(src)
    try:
        if dst.is_dir():
            dst = dst / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return _ok(f"Moved {src} -> {dst}.", source=str(src), destination=str(dst))
    except Exception as exc:
        return _fail(f"Could not move {src} -> {dst}: {exc}")


def rename_file(source: str, new_name: str) -> dict:
    src = _expand(source)
    if not src.exists():
        return _exists_msg(src)
    if not new_name or "/" in new_name or "\\" in new_name:
        return _fail(f"Invalid new name: {new_name!r}")
    try:
        dst = src.with_name(new_name)
        if dst.exists():
            return _fail(f"{dst} already exists; choose a different name.")
        src.rename(dst)
        return _ok(f"Renamed {src.name} -> {dst.name}.", source=str(src), destination=str(dst))
    except Exception as exc:
        return _fail(f"Could not rename {src}: {exc}")


def create_folder(path: str) -> dict:
    p = _expand(path)
    try:
        p.mkdir(parents=True, exist_ok=True)
        return _ok(f"Created folder {p}.", path=str(p))
    except Exception as exc:
        return _fail(f"Could not create folder {p}: {exc}")


# ------------------------------------------------------------------ system
def run_command(command: str) -> dict:
    """Run an approved shell command with a timeout and capped output.

    Always requires explicit user confirmation (every safety level).
    """
    cmd = (command or "").strip()
    if not cmd:
        return _fail("Empty command.")
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT, cwd=str(Path.home()),
        )
        out = (proc.stdout or "")[-8000:]
        err = (proc.stderr or "")[-4000:]
        summary = f"Command finished with exit code {proc.returncode}."
        return _ok(summary, command=cmd, exit_code=proc.returncode,
                   stdout=out, stderr=err)
    except subprocess.TimeoutExpired:
        return _fail(f"Command timed out after {COMMAND_TIMEOUT}s: {cmd}")
    except Exception as exc:
        return _fail(f"Command failed: {exc}")


def get_system_info() -> dict:
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "machine": platform.machine(),
        "python": platform.python_version(),
        "home": str(Path.home()),
        "cwd": os.getcwd(),
    }
    msg = (f"{info['os']} ({info['machine']}), Python {info['python']}, "
           f"home folder {info['home']}")
    return _ok(msg, **info)


def desktop_paths() -> dict:
    """Common folder locations the LLM can reference in conversation."""
    home = Path.home()
    paths = {}
    for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        p = home / name
        if p.exists():
            paths[name.lower()] = str(p)
    return _ok("Standard folder locations.", paths=paths)
