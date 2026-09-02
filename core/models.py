import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


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
    yandex_id = models.CharField(
        "Яндекс ID",
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
    )

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


class Order(models.Model):
    """
    Заказ на персональный разбор. Создаётся нашим бэкендом, затем
    в Prodamus уходит платёжная ссылка с order_id = public_id.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Создаётся"
        AWAITING_PAYMENT = "awaiting_payment", "Ожидает оплаты"
        PAID = "paid", "Оплачен"
        CANCELED = "canceled", "Отменён"
        DENIED = "denied", "Отклонён"
        FAILED = "failed", "Ошибка"

    public_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True
    )
    idempotency_key = models.CharField(
        "Ключ идемпотентности",
        max_length=128,
        unique=True,
        db_index=True,
    )
    idempotency_request_hash = models.CharField(
        "Хэш запроса идемпотентности",
        max_length=64,
        help_text="SHA-256 канонического тела (сессия + sku). Повтор с другим телом → 409.",
    )

    session = models.ForeignKey(
        OnboardingSession,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    waitlist_lead = models.ForeignKey(
        "WaitlistLead",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )

    customer_email = models.EmailField("Email", blank=True)
    customer_phone = models.CharField("Телефон", max_length=32, blank=True)
    customer_telegram = models.CharField("Telegram", max_length=64, blank=True)

    product_sku = models.SlugField("SKU", max_length=64)
    product_name = models.CharField("Товар", max_length=255)
    amount = models.DecimalField("Сумма", max_digits=10, decimal_places=2)
    currency = models.CharField("Валюта", max_length=8, default="rub")

    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    payment_url = models.URLField("Ссылка на оплату", max_length=4000, blank=True)
    prodamus_order_id = models.CharField(
        "ID заказа в Prodamus",
        max_length=64,
        blank=True,
        db_index=True,
    )
    paid_at = models.DateTimeField("Оплачен", null=True, blank=True)
    fulfilled_at = models.DateTimeField("Отчёт отправлен", null=True, blank=True)
    fulfillment_error = models.TextField("Ошибка отправки отчёта", blank=True)
    webhook_payload = models.JSONField("Последний webhook", default=dict, blank=True)
    interpretive = models.JSONField(
        "Слои интерпретации (натал / аспекты / циклы)",
        default=dict,
        blank=True,
    )
    last_error = models.TextField("Последняя ошибка", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session", "product_sku", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.public_id} ({self.status})"


class ChartShare(models.Model):
    """
    Публичная ссылка на карту.

    В URL — случайный capability-токен (не UUID заказа и не user id).
    В базе — SHA-256 токена для поиска и зашифрованная копия для повторной
    выдачи владельцу. Сам токен не является ключом к /api/orders/.
    """

    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    token_sealed = models.CharField(max_length=255)
    order = models.OneToOneField(
        Order,
        on_delete=models.CASCADE,
        related_name="chart_share",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chart_shares",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Публичная ссылка на карту"
        verbose_name_plural = "Публичные ссылки на карту"

    def __str__(self) -> str:
        return f"{self.token_hash[:8]}… ({self.order_id})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class AuthToken(models.Model):
    """Сессия входа после Яндекс ID. Ключ уходит на фронт как Bearer-токен."""

    key = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="auth_tokens",
    )
    device_id = models.CharField(
        "Устройство",
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        help_text="Стабильный id браузера. Пусто — старая сессия, привяжется с первого запроса.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField("Истекает")

    class Meta:
        verbose_name = "Токен входа"
        verbose_name_plural = "Токены входа"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user_id} · {self.key[:8]}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at


class YandexOAuthState(models.Model):
    """Одноразовый state + PKCE verifier на время редиректа в Яндекс."""

    nonce = models.CharField(max_length=64, unique=True, db_index=True)
    session = models.ForeignKey(
        OnboardingSession,
        on_delete=models.CASCADE,
        related_name="yandex_oauth_states",
    )
    code_verifier = models.CharField(max_length=128)
    redirect_uri = models.CharField(max_length=500, blank=True)
    device_id = models.CharField("Устройство", max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "OAuth state Яндекса"
        verbose_name_plural = "OAuth state Яндекса"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.nonce


class ReportSectionFeedback(models.Model):
    """Оценка точности раздела платного отчёта: «насколько это про тебя»."""

    class Section(models.TextChoices):
        NATAL = "natal", "Твоя карта"
        ASPECTS = "aspects", "Аспекты"
        CYCLES = "cycles", "Циклы"
        REQUEST = "request", "Запрос"
        PRACTICE = "practice", "Практика"

    class Rating(models.TextChoices):
        ABOUT_ME = "about_me", "🌝 Про меня"
        PARTIAL = "partial", "🌗 Частично"
        NOT_ABOUT_ME = "not_about_me", "🌚 Не про меня"

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="section_feedback",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="report_section_feedback",
    )
    section = models.CharField("Раздел", max_length=16, choices=Section.choices)
    rating = models.CharField("Оценка", max_length=16, choices=Rating.choices)
    comment = models.TextField("Комментарий", blank=True)
    comment_skipped = models.BooleanField("Отправлено без комментария", default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Фидбэк по разделу отчёта"
        verbose_name_plural = "Фидбэк по разделам отчёта"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "section"],
                name="uniq_report_section_feedback",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order_id}:{self.section} ({self.rating})"


class LlmRateBucket(models.Model):
    """Счётчик вызовов LLM в скользящем окне (IP / пользователь / глобальный день)."""

    key = models.CharField(max_length=160, unique=True)
    window_started_at = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Окно лимита LLM"
        verbose_name_plural = "Окна лимитов LLM"

    def __str__(self) -> str:
        return f"{self.key}={self.count}"
