from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import serializers

from .models import (
    GlobalPlanetaryCycle,
    JournalEntry,
    NatalChart,
    OnboardingSession,
    OnboardingStep,
    OnboardingStepAnswer,
    Profile,
    UserInput,
    WaitlistLead,
)


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = (
            "display_name",
            "phone",
            "telegram",
            "birth_date",
            "birth_time",
            "birth_place",
            "birth_lat",
            "birth_lng",
            "timezone",
            "registration_status",
            "onboarding_completed",
        )


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "email", "first_name", "last_name", "profile")


class JournalEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalEntry
        fields = ("id", "date", "mood", "energy", "body", "tags", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class WaitlistLeadSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = WaitlistLead
        fields = (
            "id",
            "email",
            "phone",
            "telegram",
            "name",
            "source",
            "message",
            "created_at",
        )
        read_only_fields = ("id", "created_at")


class OnboardingStepSerializer(serializers.ModelSerializer):
    url_path = serializers.CharField(read_only=True)

    class Meta:
        model = OnboardingStep
        fields = (
            "id",
            "slug",
            "title",
            "subtitle",
            "step_type",
            "order",
            "is_required",
            "fields_schema",
            "meta",
            "url_path",
        )


class OnboardingStepAnswerSerializer(serializers.ModelSerializer):
    step_slug = serializers.SlugField(source="step.slug", read_only=True)
    step_url = serializers.CharField(source="step.url_path", read_only=True)

    class Meta:
        model = OnboardingStepAnswer
        fields = (
            "id",
            "step",
            "step_slug",
            "step_url",
            "payload",
            "completed",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "step", "created_at", "updated_at")


class OnboardingSessionSerializer(serializers.ModelSerializer):
    answers = OnboardingStepAnswerSerializer(many=True, read_only=True)
    next_step = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = OnboardingSession
        fields = (
            "token",
            "status",
            "current_step_slug",
            "birth_date",
            "birth_time",
            "birth_place",
            "birth_lat",
            "birth_lng",
            "timezone",
            "answers",
            "next_step",
            "progress",
            "created_at",
            "updated_at",
            "completed_at",
        )
        read_only_fields = fields

    def get_next_step(self, obj: OnboardingSession):
        # Незавершённые ответы (completed=false) — ещё текущий шаг, не пропускаем.
        done_ids = set(obj.answers.filter(completed=True).values_list("step_id", flat=True))
        nxt = (
            OnboardingStep.objects.filter(is_active=True)
            .exclude(id__in=done_ids)
            .order_by("order", "id")
            .first()
        )
        return OnboardingStepSerializer(nxt).data if nxt else None

    def get_progress(self, obj: OnboardingSession):
        total = OnboardingStep.objects.filter(is_active=True).count()
        done = obj.answers.filter(completed=True).count()
        return {"done": done, "total": total}


class OnboardingStepSubmitSerializer(serializers.Serializer):
    payload = serializers.JSONField(default=dict)
    completed = serializers.BooleanField(default=True)

    def save_answer(self, session: OnboardingSession, step: OnboardingStep) -> OnboardingStepAnswer:
        payload = self.validated_data.get("payload") or {}
        completed = self.validated_data.get("completed", True)

        if step.step_type == OnboardingStep.StepType.BIRTH_DATA:
            if not payload.get("birth_date"):
                raise serializers.ValidationError(
                    {"payload": {"birth_date": ["Обязательное поле для карты."]}}
                )
            has_place = bool(str(payload.get("birth_place") or "").strip())
            has_coords = payload.get("birth_lat") not in (None, "") and payload.get(
                "birth_lng"
            ) not in (None, "")
            if not has_place and not has_coords:
                raise serializers.ValidationError(
                    {
                        "payload": {
                            "birth_place": [
                                "Нужен город рождения — по нему берём таймзону для точной Луны и Солнца."
                            ]
                        }
                    }
                )
        elif step.step_type == OnboardingStep.StepType.WAITLIST:
            email = (payload.get("email") or "").strip()
            phone = (payload.get("phone") or "").strip()
            telegram = (payload.get("telegram") or "").strip()
            if not (email or phone or telegram):
                raise serializers.ValidationError(
                    {
                        "payload": {
                            "telegram": [
                                "Оставь Telegram или телефон — так мы сможем открыть тебе разбор."
                            ]
                        }
                    }
                )

        answer, _ = OnboardingStepAnswer.objects.update_or_create(
            session=session,
            step=step,
            defaults={"payload": payload, "completed": completed},
        )

        # Тяжёлые сайд-эффекты только при завершении шага.
        if completed:
            if step.step_type == OnboardingStep.StepType.BIRTH_DATA:
                self._apply_birth_data(session, payload)
            elif step.step_type == OnboardingStep.StepType.WAITLIST:
                self._apply_waitlist(session, payload)

        update_fields = ["current_step_slug", "updated_at", *dict.fromkeys(self._session_extra_fields)]
        session.current_step_slug = step.slug
        session.save(update_fields=update_fields)

        if completed:
            self._maybe_complete_session(session)
            self._upsert_user_input(session, step, payload)

        return answer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session_extra_fields: list[str] = []

    def _apply_birth_data(self, session: OnboardingSession, payload: dict) -> None:
        mapping = {
            "birth_date": "birth_date",
            "birth_time": "birth_time",
            "birth_place": "birth_place",
            "birth_lat": "birth_lat",
            "birth_lng": "birth_lng",
            "timezone": "timezone",
        }
        for src, dest in mapping.items():
            if src in payload and payload[src] not in (None, ""):
                setattr(session, dest, payload[src])
                self._session_extra_fields.append(dest)

        if session.birth_date:
            chart, _ = NatalChart.objects.update_or_create(
                session=session,
                defaults={
                    "user": session.user,
                    "birth_date": session.birth_date,
                    "birth_time": session.birth_time,
                    "birth_place": session.birth_place,
                    "birth_lat": session.birth_lat,
                    "birth_lng": session.birth_lng,
                    "timezone": session.timezone or "",
                    "status": NatalChart.Status.PENDING,
                    "error_message": "",
                },
            )
            if session.user_id and chart.user_id != session.user_id:
                chart.user = session.user
                chart.save(update_fields=["user"])

            from core.services.geo import GeoLookupError
            from core.services.natal import NatalCalcError
            from core.services.onboarding_astro import calculate_and_store_chart

            try:
                chart = calculate_and_store_chart(chart)
            except (GeoLookupError, NatalCalcError) as exc:
                raise serializers.ValidationError({"payload": {"astro": [str(exc)]}}) from exc

            # Синхронизируем гео, которое добрал сервис (таймзона/координаты)
            session.birth_place = chart.birth_place
            session.birth_lat = chart.birth_lat
            session.birth_lng = chart.birth_lng
            session.timezone = chart.timezone
            for field in ("birth_place", "birth_lat", "birth_lng", "timezone"):
                if field not in self._session_extra_fields:
                    self._session_extra_fields.append(field)

    def _apply_waitlist(self, session: OnboardingSession, payload: dict) -> None:
        email = (payload.get("email") or "").strip().lower() or None
        phone = (payload.get("phone") or "").strip()
        telegram = (payload.get("telegram") or "").strip()

        defaults = {
            "phone": phone,
            "telegram": telegram,
            "name": (payload.get("name") or "").strip(),
            "source": (payload.get("source") or "onboarding").strip() or "onboarding",
            "message": (payload.get("message") or "").strip(),
        }

        lead = None
        if email:
            lead = WaitlistLead.objects.filter(email=email).first()
        if lead is None and telegram:
            lead = WaitlistLead.objects.filter(telegram__iexact=telegram).first()
        if lead is None and phone:
            lead = WaitlistLead.objects.filter(phone=phone).first()

        if lead:
            if email and not lead.email:
                lead.email = email
            for key, value in defaults.items():
                if value:
                    setattr(lead, key, value)
            lead.save()
        else:
            lead = WaitlistLead.objects.create(email=email, **defaults)

        session.waitlist_lead = lead
        self._session_extra_fields.append("waitlist_lead")

    def _maybe_complete_session(self, session: OnboardingSession) -> None:
        required = OnboardingStep.objects.filter(is_active=True, is_required=True)
        answered = set(
            session.answers.filter(completed=True).values_list("step_id", flat=True)
        )
        if all(s.id in answered for s in required):
            session.status = OnboardingSession.Status.COMPLETED
            session.completed_at = timezone.now()
            session.save(update_fields=["status", "completed_at", "updated_at"])

    def _upsert_user_input(
        self, session: OnboardingSession, step: OnboardingStep, payload: dict
    ) -> None:
        UserInput.objects.update_or_create(
            session=session,
            key=f"onboarding.{step.slug}",
            defaults={
                "user": session.user,
                "source": UserInput.Source.ONBOARDING,
                "value": payload,
            },
        )


class UserInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserInput
        fields = ("id", "key", "source", "value", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class NatalChartSerializer(serializers.ModelSerializer):
    class Meta:
        model = NatalChart
        fields = (
            "id",
            "birth_date",
            "birth_time",
            "birth_place",
            "timezone",
            "status",
            "chart_data",
            "calculated_at",
            "created_at",
        )
        read_only_fields = fields


class GlobalPlanetaryCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalPlanetaryCycle
        fields = (
            "key",
            "title",
            "description",
            "starts_at",
            "ends_at",
            "is_active",
            "cycle_data",
        )
