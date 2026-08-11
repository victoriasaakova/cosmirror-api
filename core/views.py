from typing import Optional

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    GlobalPlanetaryCycle,
    JournalEntry,
    NatalChart,
    OnboardingSession,
    OnboardingStep,
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
    UserInputSerializer,
    UserSerializer,
    WaitlistLeadSerializer,
)
from .services.geo import GeoLookupError, lookup_place, suggest_places
from .services.insight import build_insight
from .services.natal import calculate_sky_now
from .services.onboarding_astro import build_chart_and_insight
from .services.personalize import is_personalized, personalize_insight


def _quiz_from_session(session: OnboardingSession) -> dict:
    """Собрать ответы квиза со всех content-шагов (не waitlist)."""
    quiz: dict = {}
    answers = (
        session.answers.select_related("step")
        .exclude(step__step_type=OnboardingStep.StepType.WAITLIST)
        .order_by("step__order", "-updated_at")
    )
    seen_slugs: set[str] = set()
    for answer in answers:
        slug = answer.step.slug
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        if not isinstance(answer.payload, dict):
            continue
        for key, value in answer.payload.items():
            if value in (None, "", [], {}):
                continue
            quiz[key] = value
    return quiz


def _ensure_personalized_insight(
    *,
    session: OnboardingSession,
    natal: dict,
    insight: dict,
    chart: Optional[NatalChart] = None,
) -> dict:
    if is_personalized(insight):
        return insight

    personalized = personalize_insight(
        insight=insight,
        natal=natal,
        quiz=_quiz_from_session(session),
    )

    if chart is not None and chart.chart_data is not None:
        data = dict(chart.chart_data)
        data["insight"] = personalized
        chart.chart_data = data
        chart.save(update_fields=["chart_data", "updated_at"])

    return personalized



class HealthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "cosmirror-api"})


class MeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data)


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
            insight = _ensure_personalized_insight(
                session=session,
                natal=natal,
                insight=insight,
                chart=chart,
            )
            return Response(
                {
                    "status": chart.status,
                    "has_birth_time": bool(data.get("has_birth_time")),
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
        insight = _ensure_personalized_insight(
            session=session,
            natal=natal,
            insight=bundle["insight"],
            chart=chart if chart and chart.status == NatalChart.Status.READY else None,
        )

        return Response(
            {
                "status": "ready",
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
        )


class SkyNowView(APIView):
    """Текущие положения планет (для отладки / циклов)."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        sky = calculate_sky_now()
        insight = build_insight({"planets": {}, "has_birth_time": False}, sky)
        return Response({"sky_now": sky, "cycles": insight.get("cycles")})

