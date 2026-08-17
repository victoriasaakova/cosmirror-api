"""Публичный URL фронта: прод (https) или локальный демо (http://localhost)."""

from __future__ import annotations

import urllib.parse

from django.conf import settings

_LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def public_frontend_base(*, fallback: str = "https://cosmirror.ru") -> str:
    front = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if front.startswith("https://"):
        return front
    host = urllib.parse.urlparse(front).hostname
    if host in _LOCAL_HOSTS:
        return front
    return fallback
