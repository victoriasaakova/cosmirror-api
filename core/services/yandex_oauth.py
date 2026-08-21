"""OAuth 2.0 Яндекс ID: authorization code + PKCE, затем профиль пользователя."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from core.models import (
    AuthToken,
    NatalChart,
    OnboardingSession,
    OnboardingStep,
    OnboardingStepAnswer,
    Profile,
    WaitlistLead,
    YandexOAuthState,
)

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://oauth.yandex.ru/authorize"
TOKEN_URL = "https://oauth.yandex.ru/token"
USERINFO_URL = "https://login.yandex.ru/info"
SCOPE = "login:info login:email"
STATE_TTL = timedelta(minutes=15)


class YandexOAuthError(Exception):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


@dataclass(frozen=True)
class YandexProfile:
    yandex_id: str
    login: str
    email: str
    first_name: str
    last_name: str
    display_name: str


def is_configured() -> bool:
    return bool(
        (getattr(settings, "YANDEX_OAUTH_CLIENT_ID", "") or "").strip()
        and (getattr(settings, "YANDEX_OAUTH_CLIENT_SECRET", "") or "").strip()
    )


def _configured_redirect_uri() -> str:
    return (getattr(settings, "YANDEX_OAUTH_REDIRECT_URI", "") or "").strip()


def normalize_redirect_uri(uri: str) -> str:
    """Yandex сравнивает Callback URL посимвольно: слэш, www и query уже другой адрес."""
    parts = urllib.parse.urlsplit((uri or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    path = parts.path.rstrip("/")
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def redirect_uri() -> str:
    return normalize_redirect_uri(_configured_redirect_uri())


def _allowed_redirect_hosts() -> set[str]:
    hosts: set[str] = set()
    origins = [
        getattr(settings, "FRONTEND_URL", "") or "",
        getattr(settings, "PUBLIC_API_URL", "") or "",
        *list(getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []),
    ]
    for origin in origins:
        host = urllib.parse.urlsplit(str(origin).strip()).netloc.lower()
        if host:
            hosts.add(host)
            if host.startswith("www."):
                hosts.add(host[4:])
            else:
                hosts.add(f"www.{host}")
    hosts.update(
        {
            "localhost:3000",
            "127.0.0.1:3000",
            "localhost:8000",
            "127.0.0.1:8000",
        }
    )
    return hosts


def _allowed_redirect_paths() -> set[str]:
    return {"/onboarding/contacts", "/api/auth/yandex/callback"}


def is_allowed_redirect_uri(uri: str) -> bool:
    normalized = normalize_redirect_uri(uri)
    if not normalized:
        return False
    parts = urllib.parse.urlsplit(normalized)
    return parts.netloc in _allowed_redirect_hosts() and parts.path in _allowed_redirect_paths()


def resolve_redirect_uri(requested: str | None = None) -> str:
    for raw in (requested or "", _configured_redirect_uri()):
        normalized = normalize_redirect_uri(raw)
        if normalized and is_allowed_redirect_uri(normalized):
            return normalized
    raise YandexOAuthError(
        "Redirect URI Яндекс ID не совпадает с адресом возврата. "
        "В кабинете OAuth укажи тот же URL, без завершающего слэша.",
        503,
    )


def _client_id() -> str:
    return (getattr(settings, "YANDEX_OAUTH_CLIENT_ID", "") or "").strip()


def _client_secret() -> str:
    return (getattr(settings, "YANDEX_OAUTH_CLIENT_SECRET", "") or "").strip()


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _cleanup_states() -> None:
    cutoff = timezone.now() - STATE_TTL
    YandexOAuthState.objects.filter(created_at__lt=cutoff).delete()


def build_authorize_url(*, session: OnboardingSession, requested_redirect: str | None = None) -> str:
    if not is_configured():
        raise YandexOAuthError("Яндекс ID не настроен.", 503)
    uri = resolve_redirect_uri(requested_redirect)
    _cleanup_states()
    verifier, challenge = _pkce_pair()
    nonce = secrets.token_urlsafe(24)
    YandexOAuthState.objects.create(
        nonce=nonce,
        session=session,
        code_verifier=verifier,
        redirect_uri=uri,
    )
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": _client_id(),
            "redirect_uri": uri,
            "scope": SCOPE,
            "state": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def _post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        payload = _parse_json(raw)
        detail = str(payload.get("error_description") or payload.get("error") or "Не удалось получить токен Яндекса.")
        logger.warning("Yandex token error: %s", detail)
        raise YandexOAuthError(detail, 400) from exc
    except urllib.error.URLError as exc:
        raise YandexOAuthError("Яндекс OAuth временно недоступен.", 502) from exc
    payload = _parse_json(raw)
    if not payload.get("access_token"):
        raise YandexOAuthError("Яндекс не вернул access_token.", 400)
    return payload


def _get_json(url: str, *, access_token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"OAuth {access_token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise YandexOAuthError("Не удалось получить профиль Яндекса.", 400) from exc
    except urllib.error.URLError as exc:
        raise YandexOAuthError("Яндекс ID временно недоступен.", 502) from exc
    return _parse_json(raw)


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise YandexOAuthError("Некорректный ответ Яндекса.", 502) from exc
    return data if isinstance(data, dict) else {}


def _profile_from_info(info: dict[str, Any]) -> YandexProfile:
    yandex_id = str(info.get("id") or "").strip()
    if not yandex_id:
        raise YandexOAuthError("Яндекс не вернул идентификатор пользователя.", 400)
    emails = info.get("emails") if isinstance(info.get("emails"), list) else []
    email = str(info.get("default_email") or (emails[0] if emails else "") or "").strip().lower()
    if not email or "@" not in email:
        raise YandexOAuthError("Нужен доступ к почте Яндекса, чтобы открыть разбор.", 400)
    first_name = str(info.get("first_name") or "").strip()
    last_name = str(info.get("last_name") or "").strip()
    display_name = str(
        info.get("display_name") or info.get("real_name") or first_name or info.get("login") or ""
    ).strip()
    return YandexProfile(
        yandex_id=yandex_id,
        login=str(info.get("login") or "").strip(),
        email=email,
        first_name=first_name,
        last_name=last_name,
        display_name=display_name,
    )


def exchange_code(*, code: str, state: str) -> tuple[OnboardingSession, YandexProfile]:
    code = (code or "").strip()
    state = (state or "").strip()
    if not code or not state:
        raise YandexOAuthError("Нет кода авторизации Яндекса.", 400)
    record = YandexOAuthState.objects.select_related("session").filter(nonce=state).first()
    if record is None:
        raise YandexOAuthError("Сессия входа устарела. Попробуй ещё раз.", 400)
    if timezone.now() - record.created_at > STATE_TTL:
        record.delete()
        raise YandexOAuthError("Сессия входа устарела. Попробуй ещё раз.", 400)
    token_payload = _post_form(
        TOKEN_URL,
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "code_verifier": record.code_verifier,
            "redirect_uri": record.redirect_uri or redirect_uri(),
        },
    )
    access_token = str(token_payload.get("access_token") or "")
    info = _get_json(f"{USERINFO_URL}?format=json", access_token=access_token)
    profile = _profile_from_info(info)
    session = record.session
    record.delete()
    return session, profile


def issue_auth_token(user: User) -> AuthToken:
    return AuthToken.objects.create(key=secrets.token_hex(32), user=user)


def _unique_username(yandex_id: str) -> str:
    base = f"yandex_{yandex_id}"[:150]
    if not User.objects.filter(username=base).exists():
        return base
    suffix = secrets.token_hex(3)
    return f"yandex_{yandex_id}_{suffix}"[:150]


@transaction.atomic
def get_or_create_yandex_user(profile: YandexProfile) -> User:
    existing_profile = (
        Profile.objects.select_related("user").filter(yandex_id=profile.yandex_id).first()
    )
    if existing_profile:
        user = existing_profile.user
        _refresh_user_profile(user, profile)
        return user

    user = User.objects.filter(email__iexact=profile.email).first()
    if user is None:
        user = User.objects.create_user(
            username=_unique_username(profile.yandex_id),
            email=profile.email,
            first_name=profile.first_name,
            last_name=profile.last_name,
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
    _refresh_user_profile(user, profile)
    return user


def _refresh_user_profile(user: User, profile: YandexProfile) -> None:
    changed = []
    if profile.email and user.email.lower() != profile.email:
        user.email = profile.email
        changed.append("email")
    if profile.first_name and not user.first_name:
        user.first_name = profile.first_name
        changed.append("first_name")
    if profile.last_name and not user.last_name:
        user.last_name = profile.last_name
        changed.append("last_name")
    if changed:
        user.save(update_fields=[*changed])
    account, _ = Profile.objects.get_or_create(user=user)
    account.yandex_id = profile.yandex_id
    if profile.display_name and not account.display_name:
        account.display_name = profile.display_name
    account.registration_status = Profile.RegistrationStatus.ACTIVE
    account.save()


def attach_session_to_user(
    session: OnboardingSession,
    user: User,
    *,
    email: str,
    name: str = "",
) -> OnboardingSession:
    session.user = user
    if session.status != OnboardingSession.Status.COMPLETED:
        session.status = OnboardingSession.Status.CONVERTED
    session.save(update_fields=["user", "status", "updated_at"])

    NatalChart.objects.filter(session=session).update(user=user)

    account, _ = Profile.objects.get_or_create(user=user)
    profile_fields = []
    if session.birth_date and not account.birth_date:
        account.birth_date = session.birth_date
        profile_fields.append("birth_date")
    if session.birth_time and not account.birth_time:
        account.birth_time = session.birth_time
        profile_fields.append("birth_time")
    if session.birth_place and not account.birth_place:
        account.birth_place = session.birth_place
        profile_fields.append("birth_place")
    if session.birth_lat is not None and account.birth_lat is None:
        account.birth_lat = session.birth_lat
        profile_fields.append("birth_lat")
    if session.birth_lng is not None and account.birth_lng is None:
        account.birth_lng = session.birth_lng
        profile_fields.append("birth_lng")
    if session.timezone and (not account.timezone or account.timezone == "UTC"):
        account.timezone = session.timezone
        profile_fields.append("timezone")
    if name and not account.display_name:
        account.display_name = name
        profile_fields.append("display_name")
    if profile_fields:
        account.save(update_fields=profile_fields)

    _upsert_waitlist_from_yandex(session, user, email=email, name=name)
    return session


def _upsert_waitlist_from_yandex(
    session: OnboardingSession,
    user: User,
    *,
    email: str,
    name: str,
) -> None:
    step = OnboardingStep.objects.filter(
        is_active=True,
        step_type=OnboardingStep.StepType.WAITLIST,
    ).first()
    existing_payload: dict[str, Any] = {}
    if step:
        answer = OnboardingStepAnswer.objects.filter(session=session, step=step).first()
        if answer and isinstance(answer.payload, dict):
            existing_payload = dict(answer.payload)

    payload = {
        **existing_payload,
        "email": email,
        "name": name or existing_payload.get("name") or "",
        "source": existing_payload.get("source") or "yandex_id",
        "pd_consent": True,
        "pd_consent_at": existing_payload.get("pd_consent_at") or timezone.now().isoformat(),
        "auth_provider": "yandex_id",
    }
    if step:
        OnboardingStepAnswer.objects.update_or_create(
            session=session,
            step=step,
            defaults={"payload": payload, "completed": True},
        )

    lead = session.waitlist_lead
    if lead is None:
        lead = WaitlistLead.objects.filter(email__iexact=email).first()
    if lead is None:
        lead = WaitlistLead.objects.create(
            email=email,
            name=name,
            source="yandex_id",
            user=user,
            converted_at=timezone.now(),
        )
    else:
        lead.email = email
        if name and not lead.name:
            lead.name = name
        lead.user = user
        if not lead.converted_at:
            lead.converted_at = timezone.now()
        if not lead.source:
            lead.source = "yandex_id"
        lead.save()
    if session.waitlist_lead_id != lead.id:
        session.waitlist_lead = lead
        session.save(update_fields=["waitlist_lead", "updated_at"])


def complete_yandex_login(
    *,
    session: OnboardingSession,
    profile: YandexProfile,
) -> tuple[User, AuthToken]:
    user = get_or_create_yandex_user(profile)
    attach_session_to_user(session, user, email=profile.email, name=profile.display_name)
    return user, issue_auth_token(user)
