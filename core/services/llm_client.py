"""
Унифицированный LLM-клиент для персонализации разборов.

Приоритет провайдеров (LLM_PROVIDER=auto):
  1. Polza.ai — https://polza.ai/docs (OpenAI-compatible, без VPN из РФ)
  2. Groq — legacy fallback
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class LLMError(Exception):
    """LLM call failed or returned unusable content."""


def is_configured() -> bool:
    return active_provider() is not None


def active_provider() -> Optional[str]:
    """Текущий провайдер: polza | groq | None."""
    forced = (getattr(settings, "LLM_PROVIDER", "") or "auto").strip().lower()
    polza_key = (getattr(settings, "POLZA_API_KEY", "") or "").strip()
    groq_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()

    if forced == "polza":
        return "polza" if polza_key else None
    if forced == "groq":
        return "groq" if groq_key else None

    if polza_key:
        return "polza"
    if groq_key:
        return "groq"
    return None


def chat_json(
    *,
    system: str,
    user: str,
    model: Optional[str] = None,
    temperature: float = 0.6,
    max_tokens: int = 2500,
) -> dict[str, Any]:
    provider = active_provider()
    if not provider:
        raise LLMError("No LLM API key configured (POLZA_API_KEY or GROQ_API_KEY)")

    if provider == "polza":
        return _polza_chat_json(
            system=system,
            user=user,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    from core.services import groq_client

    try:
        return groq_client.chat_json(
            system=system,
            user=user,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except groq_client.GroqError as exc:
        raise LLMError(str(exc)) from exc


def _polza_chat_json(
    *,
    system: str,
    user: str,
    model: Optional[str],
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    api_key = (getattr(settings, "POLZA_API_KEY", "") or "").strip()
    if not api_key:
        raise LLMError("POLZA_API_KEY is not configured")

    model_name = (
        model or getattr(settings, "POLZA_MODEL", "") or "openai/gpt-5.6-terra-pro"
    ).strip()
    base_url = (
        getattr(settings, "POLZA_BASE_URL", "") or "https://polza.ai/api/v1"
    ).strip()

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LLMError("openai package is not installed") from exc

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=120.0)
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
        logger.warning("Polza API request failed: %s", type(exc).__name__)
        raise LLMError(f"Polza request failed: {type(exc).__name__}") from exc

    content = ""
    try:
        content = (completion.choices[0].message.content or "").strip()
    except (IndexError, AttributeError) as exc:
        raise LLMError("Polza returned empty choices") from exc

    if not content:
        raise LLMError("Polza returned empty content")

    return _parse_json_object(content)


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = _JSON_FENCE.search(text)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("LLM reply is not valid JSON") from exc
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc2:
            raise LLMError("LLM reply is not valid JSON") from exc2

    if not isinstance(data, dict):
        raise LLMError("LLM JSON root must be an object")
    return data
