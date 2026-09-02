"""Стабильный id браузера: сессия Яндекса живёт только на этом устройстве."""

from __future__ import annotations

import re

_DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def normalize_device_id(raw: object) -> str:
    value = str(raw or "").strip()
    if _DEVICE_RE.fullmatch(value):
        return value
    return ""
