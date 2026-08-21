import logging
from typing import Optional
from urllib.parse import quote

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

from .authentication import BearerTokenAuthentication
from .models import (
    GlobalPlanetaryCycle,
    JournalEntry,
    NatalChart,
    OnboardingSession,
    OnboardingStep,
    Order,
    UserInput,
    WaitlistLead,
)
from .serializers import (
    GlobalPlanetaryCycleSerializer,
    JournalEntrySerializer,
    NatalChartSerializer,
    OnboardingSessionSerializer,
    OnboardingStepSerializer,
    OnboardingStepSubmitSerializer,
    OrderSerializer,
    UserInputSerializer,
    UserSerializer,
    WaitlistLeadSerializer,
)
from .services.geo import GeoLookupError, lookup_place, suggest_places
from .services.insight import build_insight
from .services.natal import calculate_sky_now
from .services.onboarding_astro import build_chart_and_insight
from .services.orders import (
    OrderError,
    apply_prodamus_webhook,
    complete_local_demo_order,
    create_or_resume_order,
    refresh_payment_link_if_stale,
    validate_idempotency_key,
)
from .services.personalize import (
    insight_is_ready,
    schedule_session_personalization,
    should_schedule_personalization,
)
from .services.prodamus import extract_sign, is_configured, parse_webhook_payload, verify_webhook
from .services.yandex_oauth import (
    YandexOAuthError,
    build_authorize_url,
    complete_yandex_login,
    exchange_code,
    resolve_redirect_uri,
)


def _kickoff_personalization(
    *,
    session: OnboardingSession,
    insight: dict,
    chart: Optional[NatalChart] = None,
) -> tuple[dict, bool]:
    """Не блокируем HTTP на LLM: стартуем фон и отдаём то, что уже есть."""
    if chart is not None:
        chart.refresh_from_db()
        stored = (chart.chart_data or {}).get("insight") if isinstance(chart.chart_data, dict) else None
        if isinstance(stored, dict):
            insight = stored
        if should_schedule_personalization(insight):
            schedule_session_personalization(
                session_id=session.pk,
                chart_id=chart.pk,
                token=str(session.token),
            )
    return insight, insight_is_ready(insight)


def _insight_payload(*, natal: dict, insight: dict, status_value: str, insight_ready: bool) -> dict:
    return {
        "status": status_value,
        "insight_ready": insight_ready,
        "has_birth_time": bool(natal.get("has_birth_time")),
        "natal": {
            "planets": natal.get("planets"),
            "ascendant": natal.get("ascendant"),
            "midheaven": natal.get("midheaven"),
            "houses": natal.get("houses"),
            "notes": natal.get("notes") or [],
            "location": natal.get("location"),
            "timezone": natal.get("timezone"),
            "engine": natal.get("engine"),
        },
        "insight": insight,
    }



class HealthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "cosmirror-api"})


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


class YandexAuthStartView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request):
        token = (request.query_params.get("session_token") or "").strip()
        if not token:
            return Response({"detail": "session_token обязателен."}, status=status.HTTP_400_BAD_REQUEST)
        session = get_object_or_404(OnboardingSession, token=token)
        requested = (request.query_params.get("redirect_uri") or "").strip()
        try:
            uri = resolve_redirect_uri(requested)
            url = build_authorize_url(session=session, requested_redirect=uri)
        except YandexOAuthError as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        return Response({"url": url, "redirect_uri": uri})


class YandexAuthCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):
        frontend = (getattr(settings, "FRONTEND_URL", "") or "https://cosmirror.ru").rstrip("/")
        error = (request.query_params.get("error") or "").strip()
        if error:
            return redirect(f"{frontend}/onboarding/contacts/?error={quote(error)}")
        try:
            session, profile = exchange_code(
                code=str(request.query_params.get("code") or ""),
                state=str(request.query_params.get("state") or ""),
            )
            _user, auth_token = complete_yandex_login(session=session, profile=profile)
        except YandexOAuthError:
            return redirect(f"{frontend}/onboarding/contacts/?error=oauth")
        return redirect(
            f"{frontend}/onboarding/insight/"
            f"#auth={quote(auth_token.key)}&session_token={quote(str(session.token))}"
        )

    def post(self, request):
        try:
            session, profile = exchange_code(
                code=str(request.data.get("code") or ""),
                state=str(request.data.get("state") or ""),
            )
            user, auth_token = complete_yandex_login(session=session, profile=profile)
        except YandexOAuthError as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        return Response(
            {
                "token": auth_token.key,
                "session_token": str(session.token),
                "user": UserSerializer(user).data,
            }
        )


def _orders_for_user(user):
    return Order.objects.filter(Q(user=user) | Q(session__user=user))


def _latest_order_for(user) -> Optional[Order]:
    qs = _orders_for_user(user)
    paid = qs.filter(status=Order.Status.PAID).order_by("-paid_at", "-created_at").first()
    return paid or qs.order_by("-created_at").first()


def _owned_order_or_404(user, public_id) -> Order:
    order = _orders_for_user(user).filter(public_id=public_id).first()
    if order is None:
        from django.http import Http404

        raise Http404()
    return order


class WaitlistCreateView(generics.CreateAPIView):
    queryset = WaitlistLead.objects.all()
    serializer_class = WaitlistLeadSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        email = (request.data.get("email") or "").strip().lower()
        if not email:
            return Response({"email": ["Обязательное поле."]}, status=status.HTTP_400_BAD_REQUEST)

        existing = WaitlistLead.objects.filter(email=email).first()
        if existing:
            changed = False
            for field in ("phone", "telegram", "name", "message", "source"):
                value = request.data.get(field)
                if value and not getattr(existing, field):
                    setattr(existing, field, value)
                    changed = True
                elif value and field in ("phone", "telegram", "name", "message"):
                    setattr(existing, field, value)
                    changed = True
            if changed:
                existing.save()
            return Response(
                WaitlistLeadSerializer(existing).data,
                status=status.HTTP_200_OK,
            )

        data = {**request.data, "email": email}
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class JournalEntryListCreateView(generics.ListCreateAPIView):
    serializer_class = JournalEntrySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return JournalEntry.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class OnboardingStepListView(generics.ListAPIView):
    """Список активных шагов онбординга (каждый со своим url_path)."""

    serializer_class = OnboardingStepSerializer
    permission_classes = [permissions.AllowAny]
    queryset = OnboardingStep.objects.filter(is_active=True)


class OnboardingSessionCreateView(APIView):
    """Создать новую сессию онбординга (до регистрации)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        session = OnboardingSession.objects.create()
        if request.user.is_authenticated:
            session.user = request.user
            session.save(update_fields=["user"])
        first = OnboardingStep.objects.filter(is_active=True).order_by("order", "id").first()
        if first:
            session.current_step_slug = first.slug
            session.save(update_fields=["current_step_slug"])
        return Response(
            OnboardingSessionSerializer(session).data,
            status=status.HTTP_201_CREATED,
        )


class OnboardingSessionDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        session = get_object_or_404(OnboardingSession, token=token)
        return Response(OnboardingSessionSerializer(session).data)


class OnboardingStepSubmitView(APIView):
    """Сохранить ответ на шаг /onboarding/<slug>/ для сессии."""

    permission_classes = [permissions.AllowAny]

    def put(self, request, token, slug):
        session = get_object_or_404(OnboardingSession, token=token)
        step = get_object_or_404(OnboardingStep, slug=slug, is_active=True)
        serializer = OnboardingStepSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save_answer(session, step)
        session.refresh_from_db()
        return Response(OnboardingSessionSerializer(session).data)

    post = put


class UserInputListCreateView(generics.ListCreateAPIView):
    """Вводы внутри продукта (вопросы безопасности — позже)."""

    serializer_class = UserInputSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserInput.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, source=UserInput.Source.PRODUCT)


class NatalChartListView(generics.ListAPIView):
    """Индивидуальные карты пользователя (расчёт — позже)."""

    serializer_class = NatalChartSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return NatalChart.objects.filter(user=self.request.user)


class GlobalCycleListView(generics.ListAPIView):
    """Общие планетарные циклы для всех."""

    serializer_class = GlobalPlanetaryCycleSerializer
    permission_classes = [permissions.AllowAny]
    queryset = GlobalPlanetaryCycle.objects.filter(is_active=True)


class GeoLookupView(APIView):
    """Город → lat/lng/timezone для онбординга."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        q = (request.query_params.get("q") or request.query_params.get("place") or "").strip()
        if not q:
            return Response({"detail": "Параметр q обязателен."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            geo = lookup_place(q)
        except GeoLookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "place": geo.place,
                "latitude": geo.latitude,
                "longitude": geo.longitude,
                "timezone": geo.timezone,
                "country": geo.country,
            }
        )


class GeoSuggestView(APIView):
    """Автокомплит городов (Nominatim / OpenStreetMap)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"results": []})
        try:
            items = suggest_places(q, limit=5)
        except GeoLookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {
                "results": [
                    {
                        "place": item.place,
                        "latitude": item.latitude,
                        "longitude": item.longitude,
                        "timezone": item.timezone,
                        "country": item.country,
                    }
                    for item in items
                ]
            }
        )


class OnboardingInsightView(APIView):
    """
    Инсайт онбординга: натал + текущие циклы + что может влиять.
    Если карта уже посчитана — отдаём из NatalChart.chart_data.
    Тексты персонализируются через Groq (если есть ключ) и кэшируются в chart_data.
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        return self._build_insight_response(token)

    def _build_insight_response(self, token):
        session = get_object_or_404(OnboardingSession, token=token)
        chart = NatalChart.objects.filter(session=session).first()

        if chart and chart.status == NatalChart.Status.READY and chart.chart_data:
            data = chart.chart_data
            natal = {
                "planets": data.get("planets"),
                "ascendant": data.get("ascendant"),
                "midheaven": data.get("midheaven"),
                "houses": data.get("houses"),
                "notes": data.get("notes") or [],
                "location": data.get("location"),
                "timezone": data.get("timezone"),
                "engine": data.get("engine"),
                "has_birth_time": bool(data.get("has_birth_time")),
            }
            insight = data.get("insight")
            if not insight:
                insight = build_insight(data, calculate_sky_now())
            insight, ready = _kickoff_personalization(
                session=session,
                insight=insight,
                chart=chart,
            )
            return Response(
                _insight_payload(
                    natal=natal,
                    insight=insight,
                    status_value=chart.status,
                    insight_ready=ready,
                )
            )

        if not session.birth_date:
            return Response(
                {"detail": "Сначала сохраните шаг birth с датой и городом."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            bundle = build_chart_and_insight(
                birth_date=session.birth_date,
                birth_time=session.birth_time,
                birth_place=session.birth_place,
                birth_lat=session.birth_lat,
                birth_lng=session.birth_lng,
                timezone_name=session.timezone or "",
            )
        except GeoLookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        natal = bundle["natal"]
        insight, ready = _kickoff_personalization(
            session=session,
            insight=bundle["insight"],
            chart=chart if chart and chart.status == NatalChart.Status.READY else None,
        )
        return Response(
            _insight_payload(
                natal=natal,
                insight=insight,
                status_value="ready",
                insight_ready=ready,
            )
        )


class SkyNowView(APIView):
    """Текущие положения планет (для отладки / циклов)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        sky = calculate_sky_now()
        insight = build_insight({"planets": {}, "has_birth_time": False}, sky)
        return Response({"sky_now": sky, "cycles": insight.get("cycles")})


class OrderCreateView(APIView):
    """
    Создать заказ у нас и платёжную ссылку в Prodamus.
    Обязателен заголовок Idempotency-Key — повтор с тем же ключом
    и тем же телом возвращает тот же заказ, без второго платежа.
    """

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        try:
            idempotency_key = validate_idempotency_key(
                request.headers.get("Idempotency-Key")
                or request.data.get("idempotency_key")
            )
        except OrderError as exc:
            return Response({"detail": exc.detail}, status=exc.status)

        token = (request.data.get("session_token") or request.data.get("token") or "").strip()
        if not token:
            return Response({"detail": "session_token обязателен."}, status=status.HTTP_400_BAD_REQUEST)
        session = get_object_or_404(OnboardingSession, token=token)
        if session.user_id and session.user_id != request.user.id:
            return Response(
                {"detail": "Сессия принадлежит другому аккаунту."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if not session.user_id:
            session.user = request.user
            session.save(update_fields=["user", "updated_at"])

        try:
            order, created = create_or_resume_order(
                session=session,
                idempotency_key=idempotency_key,
                promo_code=str(request.data.get("promo_code") or "").strip(),
            )
        except OrderError as exc:
            return Response({"detail": exc.detail}, status=exc.status)

        return Response(
            OrderSerializer(order).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class OrderDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request, public_id):
        order = _owned_order_or_404(request.user, public_id)
        try:
            order = refresh_payment_link_if_stale(order)
        except OrderError:
            pass
        return Response(OrderSerializer(order).data)


class MeReportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request):
        order = _latest_order_for(request.user)
        if order is None:
            return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        try:
            order = refresh_payment_link_if_stale(order)
        except OrderError:
            pass
        return Response(OrderSerializer(order).data)


class OrderReportPdfView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request, public_id=None):
        order = (
            _owned_order_or_404(request.user, public_id)
            if public_id
            else _latest_order_for(request.user)
        )
        if order is None or order.status != Order.Status.PAID:
            return Response({"detail": "Отчёт будет после оплаты."}, status=status.HTTP_403_FORBIDDEN)
        from core.services.pdf_report import render_report_pdf
        from core.services.report import public_paid_report

        pdf = render_report_pdf(public_paid_report(order))
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="cosmirror-report.pdf"'
        return response


class MeReportPdfView(OrderReportPdfView):
    def get(self, request, public_id=None):
        return super().get(request, public_id=None)


class OrderEmailView(APIView):
    """Поменять почту после оплаты и отправить PDF ещё раз."""

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request, public_id=None):
        order = (
            _owned_order_or_404(request.user, public_id)
            if public_id
            else _latest_order_for(request.user)
        )
        if order is None:
            return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        from core.services.fulfillment import FulfillmentError, update_order_email_and_resend

        email = str(request.data.get("email") or request.user.email or "")
        try:
            order = update_order_email_and_resend(order, email)
        except FulfillmentError as exc:
            code = status.HTTP_409_CONFLICT if "оплат" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
            return Response({"detail": str(exc)}, status=code)
        return Response(OrderSerializer(order).data)


class MeReportEmailView(OrderEmailView):
    def post(self, request, public_id=None):
        return super().post(request, public_id=None)


class OrderDemoCompleteView(APIView):
    """Только DEBUG / PRODAMUS_DEMO_MODE: пометить заказ оплаченным без webhook."""

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request, public_id=None):
        if not settings.DEBUG and not getattr(settings, "PRODAMUS_DEMO_MODE", False):
            return Response(status=status.HTTP_404_NOT_FOUND)
        order = (
            _owned_order_or_404(request.user, public_id)
            if public_id
            else _latest_order_for(request.user)
        )
        if order is None:
            return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        try:
            order = complete_local_demo_order(order)
        except OrderError as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        return Response(OrderSerializer(order).data)


class MeReportDemoCompleteView(OrderDemoCompleteView):
    def post(self, request, public_id=None):
        return super().post(request, public_id=None)


class ProdamusWebhookView(APIView):
    """
    urlNotification Prodamus. Подтверждение оплаты — только валидная Sign.
    https://help.prodamus.ru/payform/uvedomleniya/kak-ustroena-otpravka-uvedomlenii-ob-oplate
    """

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def post(self, request):
        if not is_configured():
            return Response({"detail": "Prodamus не настроен."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        signature = extract_sign(request.headers)
        if not signature:
            return Response({"detail": "Нет заголовка Sign."}, status=status.HTTP_400_BAD_REQUEST)

        payload = parse_webhook_payload(request.data)
        if not payload and request.body:
            try:
                payload = parse_webhook_payload(request.body.decode("utf-8"))
            except Exception:
                payload = {}
        if not payload:
            logger.warning("Prodamus webhook empty body content_type=%s", request.content_type)
            return Response({"detail": "Пустое тело уведомления."}, status=status.HTTP_400_BAD_REQUEST)

        secret = settings.PRODAMUS_SECRET_KEY
        allow_demo = bool(settings.PRODAMUS_DEMO_MODE)
        if not verify_webhook(payload, secret, signature, allow_demo=allow_demo):
            logger.warning(
                "Prodamus webhook bad signature keys=%s",
                sorted(str(k) for k in payload.keys())[:24],
            )
            return Response({"detail": "Неверная подпись."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = apply_prodamus_webhook(payload)
        except OrderError as exc:
            logger.warning("Prodamus webhook rejected: %s", exc.detail)
            return Response({"detail": exc.detail}, status=exc.status)

        # Prodamus ждёт HTTP 200 и тело success, иначе шлёт уведомление повторно.
        return HttpResponse("success")

