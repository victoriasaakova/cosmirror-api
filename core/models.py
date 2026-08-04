import uuid

from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Расширение пользователя: контакты, рождение, статус регистрации."""

    class RegistrationStatus(models.TextChoices):
        WAITLIST = "waitlist", "Waitlist"
        PENDING = "pending", "Ожидает регистрации"
        ACTIVE = "active", "Зарегистрирован"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    display_name = models.CharField("Имя", max_length=120, blank=True)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    telegram = models.CharField("Telegram", max_length=64, blank=True)

    birth_date = models.DateField("Дата рождения", null=True, blank=True)
    birth_time = models.TimeField("Время рождения", null=True, blank=True)
    birth_place = models.CharField("Место рождения", max_length=255, blank=True)
    birth_lat = models.DecimalField(
        "Широта", max_digits=9, decimal_places=6, null=True, blank=True
    )
    birth_lng = models.DecimalField(
        "Долгота", max_digits=9, decimal_places=6, null=True, blank=True
    )
    timezone = models.CharField("Часовой пояс", max_length=64, blank=True, default="UTC")

    registration_status = models.CharField(
        "Статус регистрации",
        max_length=16,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.WAITLIST,
    )
    onboarding_completed = models.BooleanField("Онбординг пройден", default=False)
    notes_admin = models.TextField("Заметки админа", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Профиль"
        verbose_name_plural = "Профили"

    def __str__(self) -> str:
        return self.display_name or self.user.get_username()


class OnboardingStep(models.Model):
    """
    Определение шага онбординга.
    slug = сегмент URL на фронте (/onboarding/<slug>/).
    Шагов может быть сколько угодно — порядок через `order`.
    """

    class StepType(models.TextChoices):
        CONTENT = "content", "Контент / экран"
        BIRTH_DATA = "birth_data", "Данные рождения"
        WAITLIST = "waitlist", "Контакты waitlist"
        INPUT = "input", "Ввод пользователя"
        CUSTOM = "custom", "Кастомный"

    slug = models.SlugField("URL slug", max_length=64, unique=True)
    title = models.CharField("Заголовок", max_length=200)
    subtitle = models.CharField("Подзаголовок", max_length=300, blank=True)
    step_type = models.CharField(
        "Тип шага",
        max_length=32,
        choices=StepType.choices,
        default=StepType.CUSTOM,
    )
    order = models.PositiveIntegerField("Порядок", default=0)
    is_required = models.BooleanField("Обязательный", default=True)
    is_active = models.BooleanField("Активен", default=True)
    # JSON-схема/ключи полей, которые ждём от фронта на этом шаге
    fields_schema = models.JSONField("Схема полей", default=dict, blank=True)
    meta = models.JSONField("Мета", default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Шаг онбординга"
        verbose_name_plural = "Шаги онбординга"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.order}. {self.slug}"

    @property
    def url_path(self) -> str:
        return f"/onboarding/{self.slug}/"


class OnboardingSession(models.Model):
    """
    Сессия прохождения онбординга до (и после) регистрации.
    Идентификатор — UUID token в localStorage / cookie.
    Позже привязывается к User.
    """

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "В процессе"
        COMPLETED = "completed", "Завершён"
        CONVERTED = "converted", "Конвертирован в аккаунт"

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_sessions",
    )
    waitlist_lead = models.ForeignKey(
        "WaitlistLead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_sessions",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )
    current_step_slug = models.SlugField("Текущий шаг", max_length=64, blank=True)

    # Денормализация birth для астро-сервиса до создания Profile
    birth_date = models.DateField(null=True, blank=True)
    birth_time = models.TimeField(null=True, blank=True)
    birth_place = models.CharField(max_length=255, blank=True)
    birth_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    birth_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    timezone = models.CharField(max_length=64, blank=True, default="UTC")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Сессия онбординга"
        verbose_name_plural = "Сессии онбординга"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.token} ({self.status})"


class OnboardingStepAnswer(models.Model):
    """Ответ пользователя на конкретный шаг — сохраняем каждый шаг отдельно."""

    session = models.ForeignKey(
        OnboardingSession,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    step = models.ForeignKey(
        OnboardingStep,
        on_delete=models.PROTECT,
        related_name="answers",
    )
    payload = models.JSONField("Данные шага", default=dict)
    completed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ответ шага онбординга"
        verbose_name_plural = "Ответы шагов онбординга"
        unique_together = [("session", "step")]
        ordering = ["step__order", "id"]

    def __str__(self) -> str:
        return f"{self.session.token} → {self.step.slug}"


class WaitlistLead(models.Model):
    """Заявки до полноценной регистрации: email + телефон + telegram."""

    email = models.EmailField("Email", blank=True, null=True, unique=True)
    phone = models.CharField("Телефон", max_length=32, blank=True)
    telegram = models.CharField("Telegram", max_length=64, blank=True)
    name = models.CharField("Имя", max_length=120, blank=True)
    source = models.CharField("Источник", max_length=64, blank=True, default="landing")
    message = models.TextField("Сообщение", blank=True)

    # Связь с будущим аккаунтом (закладка под регистрацию)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="waitlist_leads",
    )
    converted_at = models.DateTimeField("Конвертирован в пользователя", null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    contacted = models.BooleanField("Связались", default=False)
    notes_admin = models.TextField("Заметки админа", blank=True)

    class Meta:
        verbose_name = "Заявка waitlist"
        verbose_name_plural = "Waitlist"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.email


class UserInput(models.Model):
    """
    Всё, что пользователь вводит внутри продукта.
    Позже — вопросы безопасности и другие формы.
    key — стабильный идентификатор вопроса/поля.
    """

    class Source(models.TextChoices):
        ONBOARDING = "onboarding", "Онбординг"
        PRODUCT = "product", "Продукт"
        SECURITY = "security", "Вопрос безопасности"
        OTHER = "other", "Другое"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inputs",
    )
    session = models.ForeignKey(
        OnboardingSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inputs",
    )
    key = models.CharField("Ключ", max_length=128, db_index=True)
    source = models.CharField(
        max_length=32,
        choices=Source.choices,
        default=Source.PRODUCT,
    )
    value = models.JSONField("Значение", default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ввод пользователя"
        verbose_name_plural = "Вводы пользователей"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "key"]),
            models.Index(fields=["session", "key"]),
        ]

    def __str__(self) -> str:
        owner = self.user_id or self.session_id or "?"
        return f"{owner}:{self.key}"


class JournalEntry(models.Model):
    """Дневник состояния — чтобы видеть паттерны пользователя."""

    class Mood(models.TextChoices):
        LOW = "low", "Низкое"
        MIXED = "mixed", "Смешанное"
        OK = "ok", "Нормально"
        HIGH = "high", "Высокое"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="journal_entries",
    )
    date = models.DateField("Дата")
    mood = models.CharField("Настроение", max_length=16, choices=Mood.choices, blank=True)
    energy = models.PositiveSmallIntegerField("Энергия 1–10", null=True, blank=True)
    body = models.TextField("Запись", blank=True)
    tags = models.CharField("Теги", max_length=255, blank=True, help_text="через запятую")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Запись дневника"
        verbose_name_plural = "Дневник"
        ordering = ["-date", "-created_at"]
        unique_together = [("user", "date")]

    def __str__(self) -> str:
        return f"{self.user.get_username()} — {self.date}"


class NatalChart(models.Model):
    """
    Индивидуальная астрологическая карта / расчёты по дате рождения.
    Сервис расчёта — позже; модель хранит вход и результат.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает расчёта"
        READY = "ready", "Готово"
        FAILED = "failed", "Ошибка"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="natal_charts",
    )
    session = models.OneToOneField(
        OnboardingSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="natal_chart",
    )
    birth_date = models.DateField()
    birth_time = models.TimeField(null=True, blank=True)
    birth_place = models.CharField(max_length=255, blank=True)
    birth_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    birth_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    timezone = models.CharField(max_length=64, blank=True, default="UTC")

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    # Результат расчёта (планеты, дома, аспекты…) — заполнит сервис позже
    chart_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Натальная карта"
        verbose_name_plural = "Натальные карты"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Chart {self.birth_date} ({self.status})"


class GlobalPlanetaryCycle(models.Model):
    """
    Общие планетарные циклы и расчёты, актуальные для всех пользователей.
    Не привязаны к дате рождения.
    """

    key = models.SlugField("Ключ", max_length=64, unique=True)
    title = models.CharField("Название", max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    # Данные цикла (транзиты, ретро, аспекты…) — сервис позже
    cycle_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Планетарный цикл"
        verbose_name_plural = "Планетарные циклы"
        ordering = ["-starts_at", "key"]

    def __str__(self) -> str:
        return self.title or self.key
