"""Лимит инсайта: не регенерить успешный текст, но дать каждому пользователю шанс на LLM."""

from __future__ import annotations

import logging
import os
import sys
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.services.llm_client import LLMError
from core.services.llm_identity import current

logger = logging.getLogger(__name__)

INSIGHT_PROMPT_ID = "onboarding_insight"


class LLMLimitExceeded(LLMError):
    """Слишком много вызовов модели за окно — вызывающий код уходит в fallback."""


def _running_tests() -> bool:
    return "test" in sys.argv or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _int_setting(name: str, default: int) -> int:
    raw = getattr(settings, name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(0, value)


def consume_llm_call(*, prompt_id: str = "", enforce: bool | None = None) -> None:
    """Списать попытку инсайта. Платный отчёт не трогаем. IP/аккаунт не режем."""
    if enforce is None:
        enforce = not _running_tests()
    if not enforce:
        return
    if (prompt_id or "").strip() != INSIGHT_PROMPT_ID:
        return

    _ip, _user_id, session_token = current()
    per_session = _int_setting("LLM_INSIGHT_ATTEMPTS_PER_SESSION", 3)
    if session_token and per_session:
        _tick(f"insight:session:{session_token}", timedelta(days=2), per_session)


def _tick(key: str, window: timedelta, limit: int) -> None:
    from core.models import LlmRateBucket

    now = timezone.now()
    with transaction.atomic():
        bucket, _created = LlmRateBucket.objects.get_or_create(
            key=key,
            defaults={"window_started_at": now, "count": 0},
        )
        if now - bucket.window_started_at >= window:
            bucket.window_started_at = now
            bucket.count = 0
        if bucket.count >= limit:
            logger.warning("LLM insight limit hit key=%s limit=%s", key, limit)
            raise LLMLimitExceeded("Insight LLM limit exceeded")
        bucket.count += 1
        bucket.save(update_fields=["count", "window_started_at"])
