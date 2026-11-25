"""Groq LLM client - openai/gpt-oss-120b with streaming + tool calling.

Mirrors the official Groq recipe for gpt-oss models:
    temperature=1, top_p=1, max_completion_tokens=2048, reasoning_effort=medium
(reasoning tokens arrive on ``delta.reasoning`` and are not shown in chat).
"""

from __future__ import annotations

import threading
from typing import Generator, Optional


class LLMError(Exception):
    pass


class GroqBrain:
    def __init__(self, config) -> None:
        self._config = config
        self._client = None
        self._lock = threading.Lock()
        self._ensure_client()

    def _ensure_client(self) -> None:
        api_key = self._config.llm_key()   # active key from the Groq pool
        if not api_key:
            raise LLMError("Groq API key is not configured "
                           "(Settings > AI Models & Providers).")
        try:
            from groq import Groq
        except ImportError as exc:
            raise LLMError("The 'groq' package is not installed: pip install groq") from exc
        if self._client is None or getattr(self, "_key", None) != api_key:
            self._client = Groq(api_key=api_key)
            self._key = api_key

    def reconfigure(self) -> None:
        with self._lock:
            self._ensure_client()

    # ------------------------------------------------------------------ chat
    def stream_chat(self, messages: list[dict], tools: Optional[list[dict]],
                    cancel_event: Optional[threading.Event] = None
                    ) -> Generator[dict, None, None]:
        """Yield events:
            {"type": "delta",  "text": str}
            {"type": "tool_calls", "calls": [{"id","name","arguments"}]}
            {"type": "done",   "content": str, "finish_reason": str}
            {"type": "cancelled"}
        Raises LLMError on API failure.
        """
        with self._lock:
            self._ensure_client()
            cfg = self._config.as_dict()
            kwargs = dict(
                model=cfg.get("llm_model", "openai/gpt-oss-120b"),
                messages=messages,
                temperature=float(cfg.get("temperature", 1.0)),
                max_completion_tokens=int(cfg.get("max_completion_tokens", 2048)),
                top_p=float(cfg.get("top_p", 1.0)),
                reasoning_effort=cfg.get("reasoning_effort", "medium"),
                stream=True,
            )
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            try:
                stream = self._client.chat.completions.create(**kwargs)
            except Exception as exc:
                raise LLMError(f"Groq request failed: {exc}") from exc

        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}
        finish_reason = ""
        cancelled = False

        try:
            for chunk in stream:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta is not None:
                    text = getattr(delta, "content", None)
                    if text:
                        content_parts.append(text)
                        yield {"type": "delta", "text": text}
                    for tc in (getattr(delta, "tool_calls", None) or []):
                        slot = tool_calls.setdefault(
                            tc.index, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            slot["id"] = tc.id
                        fn = getattr(tc, "function", None)
                        if fn is not None:
                            if fn.name:
                                slot["name"] += fn.name
                            if fn.arguments:
                                slot["arguments"] += fn.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
        except Exception as exc:
            raise LLMError(f"Stream interrupted: {exc}") from exc

        if cancelled:
            yield {"type": "cancelled"}
            return

        if tool_calls:
            calls = [{"id": v["id"] or f"call_{i}", "name": v["name"],
                      "arguments": v["arguments"] or "{}"}
                     for i, v in sorted(tool_calls.items())]
            yield {"type": "tool_calls", "calls": calls}

        yield {"type": "done", "content": "".join(content_parts),
               "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop")}

    # ------------------------------------------------------------- utilities
    def quick_complete(self, system: str, user: str) -> str:
        """Small non-streaming helper (used for internal utilities)."""
        with self._lock:
            self._ensure_client()
            try:
                resp = self._client.chat.completions.create(
                    model=self._config.get("llm_model", "openai/gpt-oss-120b"),
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=0.3, max_completion_tokens=512,
                    reasoning_effort="low",
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:
                raise LLMError(f"Groq request failed: {exc}") from exc
