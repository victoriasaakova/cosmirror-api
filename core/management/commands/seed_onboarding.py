from django.core.management.base import BaseCommand

from core.models import OnboardingStep


# Каждый экран квиза = отдельный OnboardingStep → /onboarding/<slug>/
PROFILE_QUIZ_SCREENS = [
    {
        "id": "name",
        "kind": "text",
        "field": "name",
        "title": [
            {"t": "Давай познакомимся, "},
            {"t": "как тебя зовут?", "accent": True},
        ],
        "placeholder": "Твоё имя",
        "autocomplete": "given-name",
    },
    {
        "id": "gender",
        "kind": "single",
        "field": "gender",
        "title": [{"t": "Укажи свой "}, {"t": "пол", "accent": True}],
        "columns": 2,
        "options": [
            {"value": "female", "label": "Женский"},
            {"value": "male", "label": "Мужской"},
        ],
    },
    {
        "id": "age",
        "kind": "single",
        "field": "age",
        "title": [{"t": "Сколько тебе "}, {"t": "лет?", "accent": True}],
        "columns": 2,
        "options": [
            {"value": "18-24", "label": "18–24"},
            {"value": "25-34", "label": "25–34"},
            {"value": "35-44", "label": "35–44"},
            {"value": "45+", "label": "45+"},
        ],
    },
    {
        "id": "life_stage",
        "kind": "single",
        "field": "life_stage",
        "title": [
            {"t": "Какой период у тебя "},
            {"t": "сейчас?", "accent": True},
        ],
        "options": [
            {"value": "stable", "label": "все довольно стабильно"},
            {"value": "one-sphere", "label": "меняется одна важная сфера"},
            {"value": "many-spheres", "label": "перестройки в нескольких сферах жизни"},
            {"value": "ready-to-change", "label": "чувствую, что пора что-то менять"},
            {"value": "unclear", "label": "пока не понимаю, что происходит"},
        ],
    },
    {
        "id": "focus",
        "kind": "multi",
        "field": "focus",
        "title": [
            {"t": "Какая сфера жизни сейчас волнует "},
            {"t": "больше всего?", "accent": True},
        ],
        "hint": "Можно выбрать несколько",
        "options": [
            {"value": "love", "label": "отношения и любовь"},
            {"value": "money", "label": "деньги и работа"},
            {"value": "energy", "label": "энергия, ресурсы и восстановление"},
            {"value": "confidence", "label": "самооценка и уверенность"},
            {"value": "path", "label": "самореализация и поиск своего пути"},
            {"value": "other", "label": "другое"},
        ],
    },
    {
        "id": "intent",
        "kind": "single",
        "field": "intent",
        "title": [
            {"t": "Какая у тебя главная цель "},
            {"t": "на данный момент?", "accent": True},
        ],
        "options": [
            {"value": "future", "label": "узнать, что меня ждёт в ближайшем будущем"},
            {"value": "potential", "label": "понять себя и свой потенциал"},
            {"value": "uncertainty", "label": "найти выход из неопределённости"},
            {"value": "relationships", "label": "наладить отношения"},
            {"value": "patterns", "label": "понять закономерности своей жизни"},
            {"value": "life-stage", "label": "разобраться в текущем жизненном этапе"},
            {"value": "other", "label": "другое"},
        ],
    },
    {
        "id": "chart_knowledge",
        "kind": "single",
        "field": "chart_knowledge",
        "title": [
            {"t": "Что ты уже знаешь про "},
            {"t": "свою карту?", "accent": True},
        ],
        "options": [
            {"value": "sun-only", "label": "Только знак зодиака"},
            {"value": "big-three", "label": "Знак, луна или асцендент"},
            {"value": "natal-chart", "label": "Читаю свою натальную карту"},
            {"value": "transits", "label": "Разбираюсь в транзитах"},
        ],
    },
    {
        "id": "astrology_trigger",
        "kind": "single",
        "field": "astrology_trigger",
        "title": [
            {"t": "Что обычно приводит тебя "},
            {"t": "к астрологии?", "accent": True},
        ],
        "options": [
            {"value": "understand-self", "label": "Хочу понять, что со мной происходит"},
            {"value": "person", "label": "Не складывается с конкретным человеком"},
            {"value": "decision", "label": "Нужно принять решение"},
            {"value": "check-feelings", "label": "Хочу проверить свои ощущения"},
            {"value": "curious", "label": "Просто интересно"},
        ],
    },
]

QUIZ_TITLES = {
    "name": "Имя",
    "gender": "Пол",
    "age": "Возраст",
    "life_stage": "Период жизни",
    "focus": "Фокус",
    "intent": "Цель",
    "chart_knowledge": "Знание карты",
    "astrology_trigger": "Триггер",
}


def _build_default_steps():
    steps = []
    order = 10
    for screen in PROFILE_QUIZ_SCREENS:
        slug = screen["id"]
        steps.append(
            {
                "slug": slug,
                "title": QUIZ_TITLES.get(slug, slug),
                "subtitle": "",
                "step_type": OnboardingStep.StepType.CONTENT,
                "order": order,
                "is_required": True,
                "is_active": True,
                "fields_schema": {screen["field"]: {"type": "string", "required": True}},
                "meta": {"screens": [screen]},
            }
        )
        order += 10

    steps.append(
        {
            "slug": "birth",
            "title": "Данные рождения",
            "subtitle": "Нужны для построения персональной карты",
            "step_type": OnboardingStep.StepType.BIRTH_DATA,
            "order": order,
            "is_required": True,
            "is_active": True,
            "fields_schema": {
                "birth_date": {"type": "date", "required": True},
                "birth_time": {"type": "time", "required": False},
                "birth_place": {"type": "string", "required": True},
                "birth_lat": {"type": "number", "required": False},
                "birth_lng": {"type": "number", "required": False},
                "timezone": {"type": "string", "required": False},
            },
            "meta": {},
        }
    )
    order += 10

    steps.append(
        {
            "slug": "contacts",
            "title": "Контакты",
            "subtitle": "Email, телефон и Telegram для waitlist",
            "step_type": OnboardingStep.StepType.WAITLIST,
            "order": order,
            "is_required": True,
            "is_active": True,
            "fields_schema": {
                "telegram": {"type": "string", "required": False},
                "phone": {"type": "string", "required": False},
                "email": {"type": "email", "required": False},
                "name": {"type": "string", "required": False},
            },
            "meta": {},
        }
    )
    return steps


# Старый монолитный шаг — выключаем, чтобы не дублировать квиз.
LEGACY_INACTIVE_SLUGS = ("welcome",)


class Command(BaseCommand):
    help = "Создаёт/обновляет шаги онбординга (каждый экран — отдельный URL)"

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for data in _build_default_steps():
            obj, was_created = OnboardingStep.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    "title": data["title"],
                    "subtitle": data["subtitle"],
                    "step_type": data["step_type"],
                    "order": data["order"],
                    "is_required": data["is_required"],
                    "is_active": data["is_active"],
                    "fields_schema": data["fields_schema"],
                    "meta": data.get("meta") or {},
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
            self.stdout.write(f"  {'+' if was_created else '~'} /onboarding/{obj.slug}/")

        for slug in LEGACY_INACTIVE_SLUGS:
            n = OnboardingStep.objects.filter(slug=slug, is_active=True).update(is_active=False)
            if n:
                self.stdout.write(f"  - deactivated /onboarding/{slug}/")

        self.stdout.write(self.style.SUCCESS(f"Готово: создано {created}, обновлено {updated}"))
