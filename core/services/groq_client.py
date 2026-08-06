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

    model_name = (model or getattr(settings, "GROQ_MODEL", "") or "llama-3.3-70b-versatile").strip()

    try:
        from groq import Groq
    except ImportError as exc:
        raise GroqError("groq package is not installed") from exc

    try:
        client = Groq(api_key=api_key, timeout=45.0)
        completion = client.chat.completions.create(
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
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
