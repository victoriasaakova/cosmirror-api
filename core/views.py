import logging
import uuid
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
    AuthToken,
    GlobalPlanetaryCycle,
    JournalEntry,
    NatalChart,
    OnboardingSession,
    OnboardingStep,
    Order,
    ReportSectionFeedback,
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
    ReportSectionFeedbackSerializer,
    ReportSectionFeedbackWriteSerializer,
    UserInputSerializer,
    UserSerializer,
    WaitlistLeadSerializer,
)
from .services.geo import GeoLookupError, lookup_place, suggest_places
from .services.landing_chart import calculate_landing_wheel, wheel_for_session
from .services.insight import build_insight
from .services.natal import NatalCalcError, calculate_sky_now
from .services.natal_common import public_natal_error
from .services.onboarding_astro import build_chart_and_insight
from .services.orders import (
    OrderError,
    apply_prodamus_webhook,
    complete_local_demo_order,
    confirm_checkout_return,
    create_or_resume_order,
    refresh_payment_link_if_stale,
    validate_idempotency_key,
)
from .services.personalize import (
    insight_is_ready,
    quiz_from_session,
    schedule_session_personalization,
    should_schedule_personalization,
    _has_funnel_structure,
)
from .services.onboarding_fallback import build_onboarding_fallback
from .services.prodamus import (
    extract_sign,
    is_configured,
    parse_checkout_return,
    parse_webhook_payload,
    verify_webhook,
)
from .services.account import (
    BirthUpdateError,
    birth_snapshot,
    delete_user_account,
    update_user_birth,
)
from .services.yandex_oauth import (
    YandexOAuthError,
    build_authorize_url,
    complete_yandex_login,
    exchange_code,
    get_or_create_dev_user,
    issue_auth_token,
    maybe_repair_display_name,
    resolve_redirect_uri,
)


def _resolve_insight_funnel(
    *,
    session: OnboardingSession,
    insight: dict,
    natal: dict,
) -> dict:
    source = str((insight or {}).get("source") or "")
    if source not in ("", "templates") and _has_funnel_structure(insight):
        return insight
    return build_onboarding_fallback(
        insight=insight or {},
        natal=natal or {},
        quiz=quiz_from_session(session),
    )


def _kickoff_personalization(
    *,
    session: OnboardingSession,
    insight: dict,
    natal: Optional[dict] = None,
    chart: Optional[NatalChart] = None,
) -> tuple[dict, bool]:
    """Не блокируем HTTP на LLM: стартуем фон и отдаём полный fallback funnel."""
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
    insight = _resolve_insight_funnel(session=session, insight=insight, natal=natal or {})
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


def _has_paid_report(user) -> bool:
    order = _latest_order_for(user)
    return bool(order and order.status == Order.Status.PAID)


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request):
        maybe_repair_display_name(request.user)
        data = UserSerializer(request.user).data
        data["has_paid_report"] = _has_paid_report(request.user)
        birth = birth_snapshot(request.user)
        data["birth"] = birth
        profile = data.get("profile")
        if isinstance(profile, dict):
            for key in (
                "birth_date",
                "birth_time",
                "birth_place",
                "birth_lat",
                "birth_lng",
                "timezone",
            ):
                if not profile.get(key) and birth.get(key):
                    profile[key] = birth[key]
            data["profile"] = profile
        if data["has_paid_report"]:
            from core.services.report_jobs import kickoff_paid_report_for_user

            kickoff_paid_report_for_user(request.user, retry_failed=False)
        return Response(data)

    def delete(self, request):
        delete_user_account(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeBirthView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def patch(self, request):
        raw = request.data if isinstance(request.data, dict) else {}
        try:
            birth = update_user_birth(request.user, raw)
        except BirthUpdateError as exc:
            return Response({exc.field: [exc.message]}, status=status.HTTP_400_BAD_REQUEST)
        maybe_repair_display_name(request.user)
        data = UserSerializer(request.user).data
        data["has_paid_report"] = _has_paid_report(request.user)
        data["birth"] = birth
        return Response(data)


class YandexAuthStartView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def get(self, request):
        token = (request.query_params.get("session_token") or "").strip()
        if token:
            session = get_object_or_404(OnboardingSession, token=token)
        else:
            session = OnboardingSession.objects.create()
        requested = (request.query_params.get("redirect_uri") or "").strip()
        after = (request.query_params.get("after") or "").strip().lower()
        try:
            uri = resolve_redirect_uri(requested)
            url = build_authorize_url(session=session, requested_redirect=uri)
        except YandexOAuthError as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        if after == "account":
            session.current_step_slug = "account"
            session.save(update_fields=["current_step_slug", "updated_at"])
        return Response({"url": url, "redirect_uri": uri})


class AuthLogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        token = getattr(request, "auth", None)
        if isinstance(token, AuthToken):
            token.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeDevResetView(APIView):
    """Только DEBUG: стереть заказы пользователя, чтобы пройти оплату заново."""

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        if not settings.DEBUG:
            return Response(status=status.HTTP_404_NOT_FOUND)
        deleted, _ = _orders_for_user(request.user).delete()
        return Response({"ok": True, "deleted": deleted})


class AuthDevLoginView(APIView):
    """Только DEBUG: вход без Яндекса, чтобы пройти квиз и кабинет на localhost."""

    permission_classes = [permissions.AllowAny]
    authentication_classes: list = []

    def post(self, request):
        if not settings.DEBUG:
            return Response(status=status.HTTP_404_NOT_FOUND)
        raw = request.data if isinstance(request.data, dict) else {}
        persona = str(raw.get("persona") or "empty").strip().lower()
        if persona not in {"empty", "report", "insight", "cabinet"}:
            return Response(
                {"detail": "persona: empty, report, insight или cabinet."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = get_or_create_dev_user()
        _orders_for_user(user).delete()
        session_token = ""
        if persona == "report":
            from core.services.dev_fixtures import seed_dev_paid_report

            order = seed_dev_paid_report(user)
            session_token = str(order.session.token)
        elif persona == "insight":
            from core.services.dev_fixtures import seed_dev_insight_funnel

            session = seed_dev_insight_funnel(user)
            session_token = str(session.token)
        elif persona == "cabinet":
            from core.services.dev_fixtures import seed_dev_free_cabinet

            session = seed_dev_free_cabinet(user)
            session_token = str(session.token)
        auth_token = issue_auth_token(user)
        user_data = UserSerializer(user).data
        user_data["has_paid_report"] = _has_paid_report(user)
        if user_data["has_paid_report"]:
            from core.services.report_jobs import kickoff_paid_report_for_user

            kickoff_paid_report_for_user(user, retry_failed=False)
        return Response(
            {
                "token": auth_token.key,
                "session_token": session_token,
                "user": user_data,
            }
        )


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
        if _has_paid_report(_user):
            from core.services.report_jobs import kickoff_paid_report_for_user

            kickoff_paid_report_for_user(_user, retry_failed=False)
        dest = (
            f"{frontend}/account/"
            if _has_paid_report(_user) or (session.current_step_slug or "") in {
                "account",
                "insight",
                "cosmoportrait",
                "report",
            }
            else f"{frontend}/onboarding/insight/"
        )
        return redirect(
            f"{dest}#auth={quote(auth_token.key)}&session_token={quote(str(session.token))}"
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
        user_data = UserSerializer(user).data
        user_data["has_paid_report"] = _has_paid_report(user)
        if user_data["has_paid_report"]:
            from core.services.report_jobs import kickoff_paid_report_for_user

            kickoff_paid_report_for_user(user, retry_failed=False)
        return Response(
            {
                "token": auth_token.key,
                "session_token": str(session.token),
                "user": user_data,
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


class LandingChartView(APIView):
    """Swiss-колесо для лендинга: без инсайта и без завершения шага birth."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        payload = request.data if isinstance(request.data, dict) else {}
        birth_date = str(payload.get("birth_date") or "").strip()
        if not birth_date:
            return Response(
                {"detail": "Нужна дата рождения."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        birth_place = str(payload.get("birth_place") or "").strip()
        lat = payload.get("birth_lat")
        lng = payload.get("birth_lng")
        has_coords = lat not in (None, "") and lng not in (None, "")
        if not birth_place and not has_coords:
            return Response(
                {"detail": "Нужен город рождения."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = request.user if getattr(request.user, "is_authenticated", False) else None
        unknown_time = bool(payload.get("unknown_time"))
        try:
            data = calculate_landing_wheel(
                token=str(payload.get("token") or "").strip() or None,
                birth_date=birth_date,
                birth_time=payload.get("birth_time"),
                unknown_time=unknown_time,
                birth_place=birth_place,
                birth_lat=float(lat) if has_coords else None,
                birth_lng=float(lng) if has_coords else None,
                timezone_name=str(payload.get("timezone") or ""),
                user=user,
            )
        except GeoLookupError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except NatalCalcError as exc:
            return Response(
                {"detail": public_natal_error(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "Не получилось прочитать данные рождения."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(data)


class LandingChartDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        session = get_object_or_404(OnboardingSession, token=token)
        try:
            return Response(wheel_for_session(session))
        except LookupError:
            return Response(
                {"detail": "Карта ещё не посчитана."},
                status=status.HTTP_404_NOT_FOUND,
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
                natal=natal,
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
            natal=natal,
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
        if order.status == Order.Status.PAID:
            from core.services.report_jobs import kickoff_paid_report_for_order

            kickoff_paid_report_for_order(order, retry_failed=False)
            order.refresh_from_db()
        return Response(OrderSerializer(order).data)


class MeCabinetView(APIView):
    """Free natal cabinet for an authenticated user who has not paid yet."""

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request):
        if _has_paid_report(request.user):
            return Response({"access": "paid", "report": None, "locked_sections": []})
        from core.services.cabinet import build_free_cabinet

        payload = build_free_cabinet(request.user)
        if payload is None:
            return Response({"detail": "Нет карты."}, status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class MeCabinetLockedPreviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get(self, request, section: str):
        if _has_paid_report(request.user):
            return Response(status=status.HTTP_404_NOT_FOUND)
        from core.services.locked_preview import locked_preview_payload

        payload = locked_preview_payload(request.user, section)
        if not payload:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(payload)


class MeReportFeedbackView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        order = _latest_order_for(request.user)
        if order is None:
            return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        if order.status != Order.Status.PAID:
            return Response(
                {"detail": "Фидбэк будет после оплаты."},
                status=status.HTTP_403_FORBIDDEN,
            )
        writer = ReportSectionFeedbackWriteSerializer(data=request.data)
        writer.is_valid(raise_exception=True)
        data = writer.validated_data
        skipped = bool(data.get("comment_skipped"))
        comment = "" if skipped else str(data.get("comment") or "")
        defaults = {
            "user": request.user,
            "rating": data["rating"],
        }
        if skipped:
            defaults["comment"] = ""
            defaults["comment_skipped"] = True
        elif "comment" in request.data:
            defaults["comment"] = comment
            defaults["comment_skipped"] = False
        obj, _created = ReportSectionFeedback.objects.update_or_create(
            order=order,
            section=data["section"],
            defaults=defaults,
        )
        return Response(ReportSectionFeedbackSerializer(obj).data)


class MeReportNatalGenerateView(APIView):
    """Собрать вкладку «Твоя карта» скиллом paid_report_natal (Polza)."""

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        order = _latest_order_for(request.user)
        if order is None:
            return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        if order.status != Order.Status.PAID:
            return Response(
                {"detail": "Разбор карты будет после оплаты."},
                status=status.HTTP_403_FORBIDDEN,
            )
        force = str(request.data.get("force") or "").lower() in {"1", "true", "yes"}
        from core.services.report import generate_natal_section

        report = generate_natal_section(order, force=force)
        natal = ((report.get("document") or {}).get("interpretive") or {}).get("natal") or {}
        return Response(
            {
                "status": natal.get("source") or "fallback",
                "natal": natal,
                "report": report,
            }
        )


class MeReportAspectsGenerateView(APIView):
    """Собрать вкладку «Аспекты» скиллом paid_report_aspects (Polza)."""

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        order = _latest_order_for(request.user)
        if order is None:
            return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        if order.status != Order.Status.PAID:
            return Response(
                {"detail": "Разбор карты будет после оплаты."},
                status=status.HTTP_403_FORBIDDEN,
            )
        force = str(request.data.get("force") or "").lower() in {"1", "true", "yes"}
        from core.services.report import generate_aspects_section

        report = generate_aspects_section(order, force=force)
        aspects = ((report.get("document") or {}).get("interpretive") or {}).get("aspects") or {}
        return Response(
            {
                "status": aspects.get("source") or "fallback",
                "aspects": aspects,
                "report": report,
            }
        )


class MeReportCyclesGenerateView(APIView):
    """Собрать вкладку «Циклы» скиллом paid_report_cycles (Polza)."""

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        order = _latest_order_for(request.user)
        if order is None:
            return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        if order.status != Order.Status.PAID:
            return Response(
                {"detail": "Разбор карты будет после оплаты."},
                status=status.HTTP_403_FORBIDDEN,
            )
        force = str(request.data.get("force") or "").lower() in {"1", "true", "yes"}
        from core.services.report import generate_cycles_section

        report = generate_cycles_section(order, force=force)
        cycles = ((report.get("document") or {}).get("interpretive") or {}).get("cycles") or {}
        return Response(
            {
                "status": cycles.get("source") or "fallback",
                "cycles": cycles,
                "report": report,
            }
        )


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


class MeReportConfirmPaymentView(APIView):
    """
    Возврат с Prodamus urlSuccess. СБП может прислать webhook на 15+ минут позже
    редиректа, страница кабинета не должна крутиться всё это время.
    """

    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        payload = {}
        if isinstance(request.data, dict):
            payload.update(request.data)
        payload.update(request.query_params.dict())
        params = parse_checkout_return(payload)
        if params["order_ref"]:
            try:
                public_id = uuid.UUID(params["order_ref"])
            except (ValueError, TypeError):
                return Response(
                    {"detail": "Некорректный номер заказа."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            order = _orders_for_user(request.user).filter(public_id=public_id).first()
            if order is None:
                return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        else:
            order = _latest_order_for(request.user)
            if order is None:
                return Response({"detail": "Нет заказа."}, status=status.HTTP_404_NOT_FOUND)
        try:
            order = confirm_checkout_return(order, payload)
        except OrderError as exc:
            return Response({"detail": exc.detail}, status=exc.status)
        if order.status == Order.Status.PAID:
            from core.services.report_jobs import kickoff_paid_report_for_order

            kickoff_paid_report_for_order(order, retry_failed=False)
            order.refresh_from_db()
        return Response(OrderSerializer(order).data)


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

