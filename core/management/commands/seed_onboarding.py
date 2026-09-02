from __future__ import annotations

from django.core.management.base import BaseCommand

from core.models import OnboardingSession, OnboardingStep, OnboardingStepAnswer


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
            {
                "value": "stable",
                "label": "В целом всё стабильно",
                "tip": "Не всему нужен ремонт. Посмотрим, куда направить внимание дальше.",
            },
            {
                "value": "one-sphere",
                "label": "Меняется одна важная сфера",
                "tip": "Здесь лучше идти вглубь, а не охватывать всё. Начнём с главного.",
            },
            {
                "value": "many-spheres",
                "label": "Меняется сразу несколько сфер",
                "tip": "События могут быть частями одного процесса. Поищем общую нить.",
            },
            {
                "value": "unclear",
                "label": "Чувствую перемены, но пока не понимаю их",
                "tip": "Необязательно сразу всё понимать. Начнём с того, что уже ощущается.",
            },
        ],
    },
    {
        "id": "focus",
        "kind": "single",
        "field": "focus",
        "title": [
            {"t": "С чем тебе сейчас важнее всего "},
            {"t": "разобраться?", "accent": True},
        ],
        "options": [
            {
                "value": "love",
                "label": "Отношения и любовь",
                "tip": "Не всё решают чувства. Иногда больше говорит сам способ быть рядом.",
            },
            {
                "value": "money",
                "label": "Работа и деньги",
                "tip": "Не каждый тупик требует нового плана. Посмотрим, что держит на месте.",
            },
            {
                "value": "energy",
                "label": "Энергия и восстановление",
                "tip": "Не вся усталость проходит после отдыха. Посмотрим, куда уходят силы.",
            },
            {
                "value": "confidence",
                "label": "Уверенность и самооценка",
                "tip": "Сомнения не всегда про слабость. Иногда дело в чужой мерке.",
            },
            {
                "value": "path",
                "label": "Самореализация и свой путь",
                "tip": "Не всякая цель действительно твоя. Отделим своё от чужих ожиданий.",
            },
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
            {
                "value": "life-stage",
                "label": "Что происходит сейчас",
                "tip": "Сначала отделим факты от реакции на них. Так станет видна причина.",
            },
            {
                "value": "patterns",
                "label": "Какие сценарии повторяются",
                "tip": "Повторение начинается раньше, чем кажется. Посмотрим, где всё запускается.",
            },
            {
                "value": "potential",
                "label": "В чём мой потенциал",
                "tip": "Сильная сторона не всегда похожа на талант. Часто она кажется чем-то обычным.",
            },
            {
                "value": "uncertainty",
                "label": "Куда двигаться дальше",
                "tip": "Следующий шаг не обязан решать всё сразу. Достаточно, чтобы он вернул движение.",
            },
            {
                "value": "future",
                "label": "Чего ждать в ближайшее время",
                "tip": "Точный прогноз начинается не с обещаний. Сначала нужна точка отсчёта.",
            },
        ],
    },
    {
        "id": "chart_knowledge",
        "kind": "single",
        "field": "chart_knowledge",
        "title": [
            {"t": "Что ты знаешь о "},
            {"t": "своей карте?", "accent": True},
        ],
        "options": [
            {
                "value": "sun-only",
                "label": "Знаю только свой знак",
                "tip": "Начинать со словаря не придётся. Объясним карту через знакомые ситуации.",
            },
            {
                "value": "big-three",
                "label": "Знаю Солнце, Луну и асцендент",
                "tip": "База уже есть. Покажем связи между отдельными положениями.",
            },
            {
                "value": "transits",
                "label": "Читаю карту и слежу за транзитами",
                "tip": "Можно идти глубже. Покажем логику аспектов и текущих влияний.",
            },
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
            {
                "value": "understand-self",
                "label": "Хочу понять своё состояние",
                "tip": "Назвать чувство бывает мало. Ясность приходит, когда видна его причина.",
            },
            {
                "value": "person",
                "label": "Думаю о конкретном человеке",
                "tip": "В чужих поступках легко потерять себя. Вернём свою точку зрения в центр.",
            },
            {
                "value": "decision",
                "label": "Стою перед важным выбором",
                "tip": "Ещё одно мнение редко решает выбор. Нужен собственный критерий.",
            },
            {
                "value": "check-feelings",
                "label": "Хочу свериться с собой",
                "tip": "Иногда ответ уже есть. Проверим, почему ему пока трудно доверять.",
            },
            {
                "value": "curious",
                "label": "Мне просто интересно",
                "tip": "Не каждому поиску нужна проблема. Иногда интерес сам открывает важное.",
            },
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

# URL /onboarding/<slug>/ — не обязан совпадать с id поля в payload.
QUIZ_URL_SLUGS = {
    "name": "name",
    "gender": "gender",
    "age": "age",
    "life_stage": "life_stage",
    "focus": "focus",
    "intent": "goal",
    "chart_knowledge": "astrolevel",
    "astrology_trigger": "questions",
}


def _build_default_steps():
    steps = []
    order = 10
    for screen in PROFILE_QUIZ_SCREENS:
        slug = QUIZ_URL_SLUGS.get(screen["id"], screen["id"])
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
            "slug": "understood",
            "title": "Что мы уже поняли",
            "subtitle": "",
            "step_type": OnboardingStep.StepType.CONTENT,
            "order": order,
            "is_required": True,
            "is_active": True,
            "fields_schema": {},
            "meta": {"ui": "synthesis"},
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
            "subtitle": "Email и Telegram для waitlist",
            "step_type": OnboardingStep.StepType.WAITLIST,
            "order": order,
            "is_required": True,
            "is_active": True,
            "fields_schema": {
                "telegram": {"type": "string", "required": True},
                "email": {"type": "email", "required": True},
                "name": {"type": "string", "required": False},
            },
            "meta": {},
        }
    )
    return steps


# Старый монолитный шаг и прежние URL квиза — выключаем после переименования.
LEGACY_INACTIVE_SLUGS = ("welcome",)
SLUG_RENAMES = {
    "intent": "goal",
    "chart_knowledge": "astrolevel",
    "astrology_trigger": "questions",
}


def _rename_slug(old: str, new: str) -> str | None:
    old_step = OnboardingStep.objects.filter(slug=old).first()
    new_step = OnboardingStep.objects.filter(slug=new).first()
    OnboardingSession.objects.filter(current_step_slug=old).update(current_step_slug=new)
    if old_step and not new_step:
        old_step.slug = new
        old_step.save(update_fields=["slug", "updated_at"])
        return f"  ~ renamed /onboarding/{old}/ → /onboarding/{new}/"
    if old_step and new_step and old_step.pk != new_step.pk:
        OnboardingStepAnswer.objects.filter(step=old_step).update(step=new_step)
        old_step.is_active = False
        old_step.save(update_fields=["is_active", "updated_at"])
        return f"  - merged /onboarding/{old}/ into /onboarding/{new}/"
    return None


def _backfill_understood_for_later_steps() -> int:
    """Sessions that already passed birth should not resume on the new screen."""
    understood = OnboardingStep.objects.filter(slug="understood").first()
    if understood is None:
        return 0
    later_session_ids = set(
        OnboardingStepAnswer.objects.filter(
            step__slug__in=("birth", "contacts"),
            completed=True,
        ).values_list("session_id", flat=True)
    )
    existing = set(
        OnboardingStepAnswer.objects.filter(step=understood).values_list(
            "session_id", flat=True
        )
    )
    missing = later_session_ids - existing
    if not missing:
        return 0
    OnboardingStepAnswer.objects.bulk_create(
        [
            OnboardingStepAnswer(
                session_id=session_id,
                step=understood,
                payload={"acknowledged": True},
                completed=True,
            )
            for session_id in missing
        ],
        ignore_conflicts=True,
    )
    return len(missing)


class Command(BaseCommand):
    help = "Создаёт/обновляет шаги онбординга (каждый экран — отдельный URL)"

    def handle(self, *args, **options):
        created = 0
        updated = 0
        for old, new in SLUG_RENAMES.items():
            note = _rename_slug(old, new)
            if note:
                self.stdout.write(note)
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

        backfilled = _backfill_understood_for_later_steps()
        if backfilled:
            self.stdout.write(f"  ~ backfilled understood for {backfilled} session(s)")

        self.stdout.write(self.style.SUCCESS(f"Готово: создано {created}, обновлено {updated}"))
