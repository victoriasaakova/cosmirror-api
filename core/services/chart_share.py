"""Публичная ссылка на карту: непрозрачный токен и урезанный снимок без PII."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Any

from django.conf import settings
from django.core import signing
from django.utils import timezone

from core.models import ChartShare, Order
from core.services.frontend import public_frontend_base
from core.services.report import public_paid_report

TOKEN_BYTES = 32
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SEAL_SALT = "chart-share-v1"

_POINT_KEYS = (
    "key",
    "name",
    "sign",
    "sign_ru",
    "degree",
    "minute",
    "house",
    "fact",
    "retrograde",
    "glyph",
)
_HOUSE_KEYS = ("house", "sign", "sign_ru", "theme", "occupants")
_ASPECT_KEYS = (
    "a",
    "b",
    "a_name",
    "b_name",
    "aspect",
    "aspect_ru",
    "kind",
    "orb",
    "theme",
    "fact",
)
_WHEEL_PLANET_KEYS = (
    "key",
    "name",
    "glyph",
    "longitude",
    "degree",
    "minute",
    "retrograde",
    "sign",
    "sign_ru",
    "house",
)
_WHEEL_HOUSE_KEYS = ("house", "cusp")
_WHEEL_ASPECT_KEYS = ("a", "b", "kind", "aspect", "orb")
_WHEEL_SIGN_KEYS = ("sign", "sign_ru", "start")
_WHEEL_KEYS = (
    "ascendant_longitude",
    "mc_longitude",
    "dsc_longitude",
    "ic_longitude",
)


class ChartShareError(Exception):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def is_share_token(value: str) -> bool:
    raw = (value or "").strip()
    if not TOKEN_RE.fullmatch(raw):
        return False
    return UUID_RE.fullmatch(raw) is None


def hash_share_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


def internal_share_authorized(request) -> bool:
    expected = (getattr(settings, "SHARE_INTERNAL_KEY", "") or "").encode("utf-8")
    got = (request.META.get("HTTP_X_COSMIRROR_SHARE") or "").encode("utf-8")
    if not expected or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def share_url_for(raw_token: str) -> str:
    return f"{public_frontend_base()}/s/{raw_token}/"


def lookup_share(raw_token: str) -> ChartShare | None:
    if not is_share_token(raw_token):
        return None
    share = (
        ChartShare.objects.select_related("order", "order__session")
        .filter(token_hash=hash_share_token(raw_token), revoked_at__isnull=True)
        .first()
    )
    if share is None:
        return None
    if share.order.status != Order.Status.PAID:
        return None
    return share


def public_share_payload(order: Order) -> dict[str, Any]:
    """Только колесо, таблица планет и расшифровка натала. Без PII и чужих слоёв."""
    report = public_paid_report(order)
    document = report.get("document") if isinstance(report.get("document"), dict) else {}
    factual = document.get("factual") if isinstance(document.get("factual"), dict) else {}
    natal = factual.get("natal") if isinstance(factual.get("natal"), dict) else {}
    interpretive = (
        document.get("interpretive") if isinstance(document.get("interpretive"), dict) else {}
    )
    natal_layer = interpretive.get("natal") if isinstance(interpretive.get("natal"), dict) else {}
    has_birth_time = bool(natal.get("has_birth_time"))
    return {
        "title": "Натальная карта",
        "disclaimer": (
            "Это не прогноз будущего и не замена терапии. "
            "Интерпретация — гипотеза, которую стоит проверить на своём опыте."
        ),
        "sections": [],
        "document": {
            "factual": {
                "natal": {
                    "has_birth_time": has_birth_time,
                    "points": _pick_list(natal.get("points"), _POINT_KEYS),
                    "houses": _pick_list(natal.get("houses"), _HOUSE_KEYS),
                    "aspects": _pick_list(natal.get("aspects"), _ASPECT_KEYS),
                    "wheel": _share_wheel(natal.get("wheel")),
                }
            },
            "interpretive": {
                "natal": {
                    "payload": natal_layer.get("payload")
                    if isinstance(natal_layer.get("payload"), dict)
                    else {},
                }
            },
            "presentation": {
                "web": {
                    "tabs": [
                        {"id": "home", "label": "Карта", "hint": ""},
                        {"id": "natal", "label": "Расшифровка", "hint": ""},
                    ],
                    "default_tab": "home",
                }
            },
        },
    }


def ensure_chart_share(order: Order) -> dict[str, str]:
    if order.status != Order.Status.PAID:
        raise ChartShareError("Ссылка доступна после оплаты.", 403)
    natal = ((public_share_payload(order).get("document") or {}).get("factual") or {}).get("natal")
    wheel = natal.get("wheel") if isinstance(natal, dict) else None
    planets = wheel.get("planets") if isinstance(wheel, dict) else None
    if not planets:
        raise ChartShareError("Карта ещё не собралась.", 409)

    owner_id = order.user_id
    if owner_id is None and order.session_id:
        owner_id = getattr(order.session, "user_id", None)
    if owner_id is None:
        raise ChartShareError("Нельзя поделиться этой картой.", 403)

    share = ChartShare.objects.filter(order=order, revoked_at__isnull=True).first()
    if share is not None:
        raw = _unseal(share.token_sealed)
        if raw:
            return {"url": share_url_for(raw), "token": raw}
        share.revoked_at = timezone.now()
        share.save(update_fields=["revoked_at"])

    raw = _new_token()
    ChartShare.objects.update_or_create(
        order=order,
        defaults={
            "user_id": owner_id,
            "token_hash": hash_share_token(raw),
            "token_sealed": signing.dumps(raw, salt=_SEAL_SALT),
            "revoked_at": None,
        },
    )
    return {"url": share_url_for(raw), "token": raw}


def revoke_chart_share(order: Order) -> None:
    ChartShare.objects.filter(order=order, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )


def _new_token() -> str:
    for _ in range(8):
        raw = secrets.token_urlsafe(TOKEN_BYTES)
        if is_share_token(raw) and not ChartShare.objects.filter(
            token_hash=hash_share_token(raw)
        ).exists():
            return raw
    raise ChartShareError("Не получилось создать ссылку.", 500)


def _unseal(sealed: str) -> str:
    try:
        raw = signing.loads(sealed, salt=_SEAL_SALT)
    except signing.BadSignature:
        return ""
    return raw if isinstance(raw, str) and is_share_token(raw) else ""


def _share_wheel(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    wheel = {key: raw.get(key) for key in _WHEEL_KEYS if key in raw}
    wheel["planets"] = _pick_list(raw.get("planets"), _WHEEL_PLANET_KEYS)
    if raw.get("houses"):
        wheel["houses"] = _pick_list(raw.get("houses"), _WHEEL_HOUSE_KEYS)
    if raw.get("aspects"):
        wheel["aspects"] = _pick_list(raw.get("aspects"), _WHEEL_ASPECT_KEYS)
    if raw.get("signs"):
        wheel["signs"] = _pick_list(raw.get("signs"), _WHEEL_SIGN_KEYS)
    return wheel


def _pick_list(rows: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    picked: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {key: row[key] for key in keys if key in row}
        if item:
            picked.append(item)
    return picked
