from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from core.models import AuthToken


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
        return (token.user, token)

    def authenticate_header(self, request):
        return "Bearer"
