"""Nova Assistant — configuration persistence.

Pure-python JSON config store. No Qt imports here so it stays testable
headlessly. Stored in ~/.nova-assistant/config.json (matches the Settings
page copy "stored locally in ~/.nova-assistant").
"""
from __future__ import annotations

import copy
import json
import os
import threading
import uuid

APP_DIR_NAME = ".nova-assistant"

DEFAULTS = {
    "version": 6,
    "general": {
        "start_with_windows": False,
        "start_minimized": False,
        "close_to_tray": True,
        "background_mode": True,
    },
    "voice": {
        # groq | deepgram  -> requirement: switchable STT provider
        "stt_provider": "groq",
        "stt_model_groq": "whisper-large-v3-turbo",
        "stt_model_deepgram": "nova-3",
        "deepgram_language": "multi",
        # mic_mode: "off" (mic disabled) | "continuous" (hands-free VAD)
        # | "push_to_talk" (hold-to-talk, no continuous VAD)
        "mic_mode": "continuous",
        "mic_enabled": True,               # master mic enable/disable
        "stt_enabled": True,               # master STT enable/disable
        "tts_enabled": True,               # master TTS enable/disable
        "speak_replies": True,             # speak AI replies (only if tts_enabled)
        "speak_reminders": True,
        "auto_listen_on_launch": False,
        "vad_sensitivity": 82,             # 0-100
        "silence_ms": 800,
        "tts_voice": "aura-2-thalia-en",
        "tts_volume": 90,                  # 0-100 playback volume
    },
    "llm": {
        "model": "llama-3.3-70b-versatile",
        "temperature": 1.0,
        "max_tokens": 2036,
        "reasoning_effort": "medium",      # low | medium | high
        "memory_messages": 12,
        "confirmation": "strict",          # strict | moderate | permissive
    },
    "providers": {
        "groq_keys": [],                   # [{id,name,key,enabled}]
        "active_groq_llm_key_id": "",
        # STT may reuse the active LLM key or use a dedicated key
        "groq_stt_key_mode": "llm",        # llm | custom
        "groq_stt_key_id": "",
        "deepgram_keys": [],
        "deepgram_stt_key_id": "",
        "deepgram_tts_key_id": "",
    },
    "overlay": {"enabled": True, "width": 400, "side": "right"},
    "widgets": {
        "pinned": False,
        "enabled": ["whats_today", "focus", "quick_notes", "reminders",
                     "telemetry"],          # legacy (pre-2.7)
        "instances": [],                    # managed by ui.widgets.manager
        "desktop_geometry": {},
        "focus_text": "",
    },
    "ui": {"geometry": {}, "last_page": "conversation",
           "font_size": 14},   # comfortable default text size
}


def default_data_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_DIR_NAME)
    return os.path.join(os.path.expanduser("~"), APP_DIR_NAME)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class Config:
    """Thread-safe JSON config with defaults merge."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or default_data_dir()
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, "config.json")
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    # ------------------------------------------------------------- io
    def load(self) -> None:
        with self._lock:
            try:
                if os.path.exists(self.path):
                    with open(self.path, "r", encoding="utf-8") as fh:
                        stored = json.load(fh)
                    self._data = _deep_merge(copy.deepcopy(DEFAULTS), stored)
            except Exception:
                # corrupted config -> fall back to defaults, keep a backup
                try:
                    os.replace(self.path, self.path + ".corrupt.bak")
                except Exception:
                    pass
                self._data = copy.deepcopy(DEFAULTS)
                self.save()

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)

    # ------------------------------------------------------------- access
    def get(self, dotted: str, default=None):
        with self._lock:
            node = self._data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return default
                node = node[part]
            return node

    def set(self, dotted: str, value, save: bool = True) -> None:
        with self._lock:
            parts = dotted.split(".")
            node = self._data
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
            if save:
                self.save()

    def reset_section(self, section: str) -> None:
        with self._lock:
            if section in DEFAULTS:
                self._data[section] = copy.deepcopy(DEFAULTS[section])
                self.save()

    def reset_all(self) -> None:
        with self._lock:
            self._data = copy.deepcopy(DEFAULTS)
            self.save()

    # --------------------------------------------------------- providers
    # Groq keys ---------------------------------------------------------
    def groq_keys(self) -> list[dict]:
        return list(self.get("providers.groq_keys", []))

    def add_groq_key(self, name: str, key: str, enabled: bool = True) -> dict:
        with self._lock:
            entry = {
                "id": new_id(),
                "name": name or f"Groq key {len(self.groq_keys()) + 1}",
                "key": (key or "").strip(),
                "enabled": bool(enabled),
            }
            keys = self.groq_keys()
            keys.append(entry)
            self.set("providers.groq_keys", keys)
            if not self.get("providers.active_groq_llm_key_id"):
                self.set("providers.active_groq_llm_key_id", entry["id"])
            return entry

    def update_groq_key(self, key_id: str, **fields) -> None:
        keys = self.groq_keys()
        for entry in keys:
            if entry["id"] == key_id:
                entry.update({k: v for k, v in fields.items() if k in entry})
        self.set("providers.groq_keys", keys)

    def remove_groq_key(self, key_id: str) -> None:
        keys = [k for k in self.groq_keys() if k["id"] != key_id]
        self.set("providers.groq_keys", keys)
        if self.get("providers.active_groq_llm_key_id") == key_id:
            self.set("providers.active_groq_llm_key_id", keys[0]["id"] if keys else "")
        if self.get("providers.groq_stt_key_id") == key_id:
            self.set("providers.groq_stt_key_id", "")

    def groq_key_for_llm(self) -> str:
        kid = self.get("providers.active_groq_llm_key_id", "")
        for entry in self.groq_keys():
            if entry["id"] == kid and entry["enabled"]:
                return entry["key"]
        for entry in self.groq_keys():
            if entry["enabled"]:
                return entry["key"]
        return ""

    def groq_key_for_stt(self) -> str:
        mode = self.get("providers.groq_stt_key_mode", "llm")
        if mode == "custom":
            kid = self.get("providers.groq_stt_key_id", "")
            for entry in self.groq_keys():
                if entry["id"] == kid:
                    return entry["key"]
            return ""
        return self.groq_key_for_llm()

    # Deepgram keys -----------------------------------------------------
    def deepgram_keys(self) -> list[dict]:
        return list(self.get("providers.deepgram_keys", []))

    def add_deepgram_key(self, name: str, key: str, enabled: bool = True) -> dict:
        with self._lock:
            entry = {
                "id": new_id(),
                "name": name or f"Deepgram key {len(self.deepgram_keys()) + 1}",
                "key": (key or "").strip(),
                "enabled": bool(enabled),
            }
            keys = self.deepgram_keys()
            keys.append(entry)
            self.set("providers.deepgram_keys", keys)
            if not self.get("providers.deepgram_stt_key_id"):
                self.set("providers.deepgram_stt_key_id", entry["id"])
            if not self.get("providers.deepgram_tts_key_id"):
                self.set("providers.deepgram_tts_key_id", entry["id"])
            return entry

    def update_deepgram_key(self, key_id: str, **fields) -> None:
        keys = self.deepgram_keys()
        for entry in keys:
            if entry["id"] == key_id:
                entry.update({k: v for k, v in fields.items() if k in entry})
        self.set("providers.deepgram_keys", keys)

    def remove_deepgram_key(self, key_id: str) -> None:
        keys = [k for k in self.deepgram_keys() if k["id"] != key_id]
        self.set("providers.deepgram_keys", keys)
        for field in ("providers.deepgram_stt_key_id", "providers.deepgram_tts_key_id"):
            if self.get(field) == key_id:
                self.set(field, keys[0]["id"] if keys else "")

    def deepgram_key_for_stt(self) -> str:
        kid = self.get("providers.deepgram_stt_key_id", "")
        for entry in self.deepgram_keys():
            if entry["id"] == kid and entry["enabled"]:
                return entry["key"]
        for entry in self.deepgram_keys():
            if entry["enabled"]:
                return entry["key"]
        return ""

    def deepgram_key_for_tts(self) -> str:
        kid = self.get("providers.deepgram_tts_key_id", "")
        for entry in self.deepgram_keys():
            if entry["id"] == kid and entry["enabled"]:
                return entry["key"]
        for entry in self.deepgram_keys():
            if entry["enabled"]:
                return entry["key"]
        return ""

    # ------------------------------------------------------------ status
    def active_stack(self) -> dict:
        """Summary of which provider/model serves each AI feature."""
        stt_provider = self.get("voice.stt_provider", "groq")
        return {
            "llm_provider": "Groq",
            "llm_model": self.get("llm.model", "llama-3.3-70b-versatile"),
            "llm_key": self.groq_key_for_llm(),
            "llm_enabled": True,   # LLM is ALWAYS enabled — core reasoning engine
            "stt_provider": ("Groq" if stt_provider == "groq" else "Deepgram"),
            "stt_model": (
                self.get("voice.stt_model_groq", "whisper-large-v3-turbo")
                if stt_provider == "groq"
                else self.get("voice.stt_model_deepgram", "nova-3")
            ),
            "stt_key": (
                self.groq_key_for_stt()
                if stt_provider == "groq"
                else self.deepgram_key_for_stt()
            ),
            "stt_enabled": bool(self.get("voice.stt_enabled", True)),
            "tts_provider": "Deepgram",
            "tts_voice": self.get("voice.tts_voice", "aura-2-thalia-en"),
            "tts_key": self.deepgram_key_for_tts(),
            "tts_enabled": bool(self.get("voice.tts_enabled", True)),
            "mic_enabled": bool(self.get("voice.mic_enabled", True)),
            "mic_mode": self.get("voice.mic_mode", "continuous"),
        }

    def services_status(self) -> dict:
        """Compact status for the workspace header three-dot popover.

        Returns one entry per service with a state in
        {'connected','disabled','error','not_configured'} plus a short label.
        Long provider/model text never reaches the header — it lives here
        only for the popover / Diagnostics view.
        """
        stack = self.active_stack()
        # ---- LLM (Groq) -------------------------------------------------
        if not stack["llm_key"]:
            llm = ("error", "Not configured")
        else:
            llm = ("connected", "Ready")
        # ---- STT ---------------------------------------------------------
        if not stack["stt_enabled"]:
            stt = ("disabled", "Disabled")
        elif not stack["stt_key"]:
            stt = ("error", "Not configured")
        else:
            stt = ("connected", f"{stack['stt_provider']} ready")
        # ---- TTS (Deepgram) ---------------------------------------------
        if not stack["tts_enabled"]:
            tts = ("disabled", "Disabled")
        elif not stack["tts_key"]:
            tts = ("error", "Not configured")
        else:
            tts = ("connected", "Aura ready")
        return {
            "llm": {"state": llm[0], "label": llm[1],
                    "provider": stack["llm_provider"],
                    "model": stack["llm_model"]},
            "stt": {"state": stt[0], "label": stt[1],
                    "provider": stack["stt_provider"],
                    "model": stack["stt_model"]},
            "tts": {"state": tts[0], "label": tts[1],
                    "provider": stack["tts_provider"],
                    "model": stack["tts_voice"]},
        }


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
