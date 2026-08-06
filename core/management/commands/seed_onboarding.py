from django.core.management.base import BaseCommand

from core.models import OnboardingStep


DEFAULT_STEPS = [
    {
        "slug": "welcome",
        "title": "Добро пожаловать",
        "subtitle": "Коротко о том, что тебя ждёт",
        "step_type": OnboardingStep.StepType.CONTENT,
        "order": 10,
        "is_required": True,
        "fields_schema": {},
        # ui=profile_quiz → фронт рендерит мульти-экранный квиз.
        # Можно заменить на meta.screens=[...] без деплоя фронта для опций,
        # или добавить новый шаг с другим step_type / meta.ui.
        "meta": {"ui": "profile_quiz"},
    },
    {
        "slug": "birth",
        "title": "Данные рождения",
        "subtitle": "Нужны для построения персональной карты",
        "step_type": OnboardingStep.StepType.BIRTH_DATA,
        "order": 20,
        "is_required": True,
        "fields_schema": {
            "birth_date": {"type": "date", "required": True},
            "birth_time": {"type": "time", "required": False},
            "birth_place": {"type": "string", "required": True},
            "birth_lat": {"type": "number", "required": False},
            "birth_lng": {"type": "number", "required": False},
            "timezone": {"type": "string", "required": False},
        },
        "meta": {},
    },
    {
        "slug": "contacts",
        "title": "Контакты",
        "subtitle": "Email, телефон и Telegram для waitlist",
        "step_type": OnboardingStep.StepType.WAITLIST,
        "order": 30,
        "is_required": True,
        "fields_schema": {
            "telegram": {"type": "string", "required": False},
            "phone": {"type": "string", "required": False},
            "email": {"type": "email", "required": False},
            "name": {"type": "string", "required": False},
        },
        "meta": {},
    },
]


class Command(BaseCommand):
    help = "Создаёт стартовые шаги онбординга (идемпотентно)"

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for data in DEFAULT_STEPS:
            obj, was_created = OnboardingStep.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    "title": data["title"],
                    "subtitle": data["subtitle"],
                    "step_type": data["step_type"],
                    "order": data["order"],
                    "is_required": data["is_required"],
                    "is_active": True,
                    "fields_schema": data["fields_schema"],
                    "meta": data.get("meta") or {},
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
            self.stdout.write(f"  {'+' if was_created else '~'} /onboarding/{obj.slug}/")

        self.stdout.write(self.style.SUCCESS(f"Готово: создано {created}, обновлено {updated}"))
