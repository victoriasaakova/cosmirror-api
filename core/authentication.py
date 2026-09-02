from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from core.models import AuthToken
from core.services.device_id import normalize_device_id
from core.services.llm_identity import bind_user_id


class BearerTokenAuthentication(BaseAuthentication):
    """Authorization: Bearer <key> — сессия после входа через Яндекс ID."""

    keyword = "bearer"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION") or ""
        if not header:
            return None
        parts = header.split(None, 1)
        if len(parts) != 2 or parts[0].lower() != self.keyword:
            return None
        key = parts[1].strip()
        if not key:
            return None
        token = AuthToken.objects.select_related("user").filter(key=key).first()
        if token is None or not token.user.is_active:
            raise AuthenticationFailed("Сессия истекла. Войди через Яндекс ID.")
        if token.expires_at <= timezone.now():
            token.delete()
            raise AuthenticationFailed("Сессия истекла. Войди через Яндекс ID.")
        device = normalize_device_id(request.META.get("HTTP_X_DEVICE_ID") or "")
        if token.device_id:
            if device != token.device_id:
                raise AuthenticationFailed(
                    "Сессия привязана к другому устройству. Войди через Яндекс ID."
                )
        elif device:
            token.device_id = device
            token.save(update_fields=["device_id"])
        bind_user_id(token.user_id)
        return (token.user, token)

    def authenticate_header(self, request):
        return "Bearer"
