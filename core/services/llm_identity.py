"""Кто сейчас вызывает LLM: IP, user_id, токен онбординг-сессии."""

from __future__ import annotations

import contextvars
from typing import Optional

_ip: contextvars.ContextVar[str] = contextvars.ContextVar("llm_ip", default="")
_user_id: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "llm_user_id", default=None
)
_session_token: contextvars.ContextVar[str] = contextvars.ContextVar(
    "llm_session_token", default=""
)


def client_ip(request) -> str:
    forwarded = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    if forwarded:
        return forwarded[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def bind_request(request) -> None:
    _ip.set(client_ip(request))
    user = getattr(request, "user", None)
    if getattr(user, "is_authenticated", False):
        _user_id.set(int(user.pk))
    else:
        _user_id.set(None)


def bind_user_id(user_id: object) -> None:
    if user_id is None or user_id == "":
        return
    try:
        _user_id.set(int(user_id))
    except (TypeError, ValueError):
        return


def bind_session_token(token: object) -> None:
    value = str(token or "").strip()
    _session_token.set(value)


def current() -> tuple[str, Optional[int], str]:
    return _ip.get() or "", _user_id.get(), _session_token.get() or ""
