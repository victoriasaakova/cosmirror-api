"""Thin Groq chat wrapper (OpenAI-compatible)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class GroqError(Exception):
    """Groq call failed or returned unusable content."""


def is_configured() -> bool:
    return bool(getattr(settings, "GROQ_API_KEY", "") or "")


def _model_create_kwargs(model_name: str, *, temperature: float, max_tokens: int) -> dict[str, Any]:
    """Model-specific Groq API params per https://console.groq.com/docs/reasoning"""
    kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    if model_name.startswith("qwen/"):
        # JSON mode: parsed reasoning + no extra thinking tokens (see Groq reasoning docs)
        kwargs["reasoning_format"] = "parsed"
        kwargs["reasoning_effort"] = "none"
    elif "gpt-oss" in model_name or model_name.startswith("openai/"):
        kwargs["reasoning_effort"] = "low"
    return kwargs


def chat_json(
    *,
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.6,
    max_tokens: int = 2500,
) -> dict[str, Any]:
    """
    Call Groq chat completions and parse a JSON object from the reply.
    Raises GroqError on missing key, API failure, or invalid JSON.
    """
    api_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()
    if not api_key:
        raise GroqError("GROQ_API_KEY is not configured")

    model_name = (model or getattr(settings, "GROQ_MODEL", "") or "qwen/qwen3.6-27b").strip()

    try:
        from groq import Groq
    except ImportError as exc:
        raise GroqError("groq package is not installed") from exc

    try:
        client = Groq(api_key=api_key, timeout=90.0)
        create_kwargs: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **_model_create_kwargs(model_name, temperature=temperature, max_tokens=max_tokens),
        }
        try:
            completion = client.chat.completions.create(**create_kwargs)
        except TypeError:
            # Older SDK: drop optional reasoning fields
            for key in ("reasoning_format", "reasoning_effort"):
                create_kwargs.pop(key, None)
            completion = client.chat.completions.create(**create_kwargs)
    except Exception as exc:
        logger.warning("Groq API request failed: %s", type(exc).__name__)
        raise GroqError(f"Groq request failed: {type(exc).__name__}") from exc

    content = ""
    try:
        content = (completion.choices[0].message.content or "").strip()
    except (IndexError, AttributeError) as exc:
        raise GroqError("Groq returned empty choices") from exc

    if not content:
        raise GroqError("Groq returned empty content")

    return _parse_json_object(content)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = _JSON_FENCE.search(text)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Last resort: slice outermost {...}
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise GroqError("Groq reply is not valid JSON") from exc
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc2:
            raise GroqError("Groq reply is not valid JSON") from exc2

    if not isinstance(data, dict):
        raise GroqError("Groq JSON root must be an object")
    return data
