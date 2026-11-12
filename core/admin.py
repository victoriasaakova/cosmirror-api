import json

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.utils.html import format_html, format_html_join

from .models import (
    ChartShare,
    CompatibilityReport,
    GlobalPlanetaryCycle,
    JournalEntry,
    NatalChart,
    OnboardingSession,
    OnboardingStep,
    OnboardingStepAnswer,
    Order,
    Profile,
    ReportSectionFeedback,
    UserInput,
    WaitlistLead,
)
from .services.compatibility.policy import BODY_RU, CATEGORY_TITLE


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    extra = 0
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
        "yandex_id",
        "registration_status",
        "onboarding_completed",
        "notes_admin",
        "created_at",
        "updated_at",
    )
    readonly_fields = ("created_at", "updated_at")


class JournalEntryInline(admin.TabularInline):
    model = JournalEntry
    extra = 0
    fields = ("date", "mood", "energy", "tags", "body")
    show_change_link = True
    max_num = 20


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "user",
        "phone",
        "telegram",
        "birth_date",
        "registration_status",
        "onboarding_completed",
        "created_at",
    )
    list_filter = ("registration_status", "onboarding_completed", "created_at")
    search_fields = (
        "display_name",
        "phone",
        "telegram",
        "yandex_id",
        "user__username",
        "user__email",
        "birth_place",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(OnboardingStep)
class OnboardingStepAdmin(admin.ModelAdmin):
    list_display = ("order", "slug", "title", "step_type", "is_required", "is_active", "url_path")
    list_display_links = ("slug",)
    list_editable = ("order", "is_required", "is_active")
    list_filter = ("step_type", "is_active", "is_required")
    search_fields = ("slug", "title")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("order", "id")


class OnboardingStepAnswerInline(admin.TabularInline):
    model = OnboardingStepAnswer
    extra = 0
    fields = ("step", "completed", "payload", "updated_at")
    readonly_fields = ("updated_at",)
    show_change_link = True


@admin.register(OnboardingSession)
class OnboardingSessionAdmin(admin.ModelAdmin):
    list_display = (
        "token",
        "status",
        "current_step_slug",
        "birth_date",
        "waitlist_lead",
        "user",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("token", "current_step_slug", "birth_place", "waitlist_lead__email")
    readonly_fields = ("token", "created_at", "updated_at", "completed_at")
    inlines = (OnboardingStepAnswerInline,)


@admin.register(OnboardingStepAnswer)
class OnboardingStepAnswerAdmin(admin.ModelAdmin):
    list_display = ("session", "step", "completed", "updated_at")
    list_filter = ("completed", "step")
    search_fields = ("session__token", "step__slug")


@admin.register(JournalEntry)
class JournalEntryAdmin(admin.ModelAdmin):
    list_display = ("date", "user", "mood", "energy", "tags", "created_at")
    list_filter = ("mood", "date", "created_at")
    search_fields = ("user__username", "user__email", "body", "tags")
    date_hierarchy = "date"


@admin.register(WaitlistLead)
class WaitlistLeadAdmin(admin.ModelAdmin):
    list_display = ("email", "phone", "telegram", "name", "source", "contacted", "user", "created_at")
    list_filter = ("contacted", "source", "created_at")
    search_fields = ("email", "phone", "telegram", "name", "message")
    list_editable = ("contacted",)
    readonly_fields = ("created_at", "converted_at")


@admin.register(UserInput)
class UserInputAdmin(admin.ModelAdmin):
    list_display = ("key", "source", "user", "session", "updated_at")
    list_filter = ("source", "created_at")
    search_fields = ("key", "user__username", "user__email", "session__token")
    readonly_fields = ("created_at", "updated_at")


@admin.register(NatalChart)
class NatalChartAdmin(admin.ModelAdmin):
    list_display = ("birth_date", "user", "status", "birth_place", "calculated_at", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "user__email", "birth_place")
    readonly_fields = ("created_at", "updated_at", "calculated_at")


@admin.register(GlobalPlanetaryCycle)
class GlobalPlanetaryCycleAdmin(admin.ModelAdmin):
    list_display = ("key", "title", "starts_at", "ends_at", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("key", "title")
    prepopulated_fields = {"key": ("title",)}


class ReportSectionFeedbackInline(admin.TabularInline):
    model = ReportSectionFeedback
    extra = 0
    fields = ("section", "rating", "comment", "comment_skipped", "updated_at")
    readonly_fields = ("updated_at",)
    show_change_link = True
    verbose_name = "Фидбэк раздела"
    verbose_name_plural = "Фидбэк по разделам — каждый раздел отдельно"


@admin.register(ReportSectionFeedback)
class ReportSectionFeedbackAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "user",
        "section",
        "rating",
        "comment_skipped",
        "short_comment",
        "updated_at",
    )
    list_filter = ("section", "rating", "comment_skipped", "created_at")
    search_fields = (
        "comment",
        "order__public_id",
        "order__customer_email",
        "user__username",
        "user__email",
    )
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("order", "user")
    autocomplete_fields = ("order", "user")
    date_hierarchy = "created_at"
    ordering = ("-updated_at",)

    @admin.display(description="Комментарий")
    def short_comment(self, obj: ReportSectionFeedback) -> str:
        text = (obj.comment or "").strip()
        if not text:
            return "—"
        return text if len(text) <= 80 else f"{text[:77]}…"


def _compatibility_people(report: CompatibilityReport) -> dict[str, dict]:
    raw = report.private_input if isinstance(report.private_input, dict) else {}
    people = raw.get("persons")
    found: dict[str, dict] = {}
    if not isinstance(people, list):
        return found
    for person in people:
        if isinstance(person, dict) and person.get("person_id") in {"A", "B"}:
            found[str(person["person_id"])] = person
    return found


def _ru_date(value: object) -> str:
    if not isinstance(value, str):
        return "—"
    parts = value.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year, month, day = parts
        return f"{day}.{month}.{year}"
    return value or "—"


def _clock(person: dict) -> str:
    status = person.get("birth_time_status")
    raw = person.get("birth_time")
    if status == "unknown" or not raw:
        return "время неизвестно"
    clock = str(raw)[:5]
    if status == "approximate":
        return f"{clock}, примерно"
    return clock


def _person_line(person: dict | None) -> str:
    if not person:
        return "—"
    name = str(person.get("display_name") or "").strip() or "без имени"
    place = str(person.get("place_name") or "").strip() or "город не указан"
    return f"{name} · {_ru_date(person.get('birth_date'))} · {_clock(person)} · {place}"


def _search_needles(term: str) -> list[str]:
    """SQLite хранит JSON с \\u-экранированием, Postgres — обычным текстом."""
    variants = {
        term,
        term.casefold(),
        term.lower(),
        term.upper(),
        term.capitalize(),
        term.title(),
    }
    needles: set[str] = set()
    for variant in variants:
        if not variant:
            continue
        needles.add(variant)
        dumped = json.dumps(variant, ensure_ascii=True)
        if len(dumped) >= 2 and dumped[0] == '"' and dumped[-1] == '"':
            needles.add(dumped[1:-1])
    return list(needles)


_SCORE_TITLES = (
    ("harmony", "Гармония и совместимость"),
    ("karmic_patterns", "Кармическая связь"),
    ("current_tension", "Напряжение сейчас"),
    ("transformation", "Потенциал трансформации"),
)

_EMPTY_READING = "Текст интерпретации не записан."
_EMPTY_CYCLE = "Сейчас нет отдельного значимого цикла по выбранным критериям."


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _paragraphs(*parts: object) -> str:
    rows: list[str] = []
    for part in parts:
        text = _text(part)
        if text and text not in rows:
            rows.append(text)
    return "\n\n".join(rows)


def _reading_blocks(document: object) -> list[tuple[str, str]]:
    if not isinstance(document, dict):
        return []
    blocks: list[tuple[str, str]] = []
    context = document.get("relationship_context")
    if isinstance(context, dict):
        _add_block(blocks, "Вопрос", _text(context.get("user_question")))
    if not _add_current_reading(blocks, document):
        _add_legacy_reading(blocks, document)
    return blocks


def _add_current_reading(blocks: list[tuple[str, str]], document: dict) -> bool:
    before = len(blocks)
    insight = document.get("insight") if isinstance(document.get("insight"), dict) else {}
    _add_block(
        blocks,
        "Короткий вывод",
        _paragraphs(insight.get("title") or insight.get("headline"), insight.get("body"), insight.get("basis")),
    )
    scoring = document.get("scoring") if isinstance(document.get("scoring"), dict) else {}
    for key, title in _SCORE_TITLES:
        row = scoring.get(key)
        if isinstance(row, dict):
            _add_block(blocks, title, _score_text(row))
    deep = document.get("deep_dive") if isinstance(document.get("deep_dive"), dict) else {}
    sections = deep.get("sections") if isinstance(deep.get("sections"), list) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        _add_block(
            blocks,
            _text(section.get("section_title")) or "Тема разбора",
            _paragraphs(section.get("headline"), section.get("body") or section.get("preview")),
        )
    conclusion = deep.get("conclusion") if isinstance(deep.get("conclusion"), dict) else {}
    _add_block(
        blocks,
        "Главное о связи",
        _paragraphs(
            conclusion.get("headline"),
            conclusion.get("body") or conclusion.get("summary"),
        ),
    )
    names = _public_names(document)
    cycles = document.get("active_cycles") if isinstance(document.get("active_cycles"), dict) else {}
    people = cycles.get("persons") if isinstance(cycles.get("persons"), dict) else {}
    for person_id in ("A", "B"):
        row = people.get(person_id)
        if isinstance(row, dict):
            _add_block(blocks, f"Цикл · {names[person_id]}", _cycle_text(row))
    pair = document.get("pair_card") if isinstance(document.get("pair_card"), dict) else {}
    _add_block(blocks, "Карта пары", _pair_text(pair))
    return len(blocks) > before


def _add_legacy_reading(blocks: list[tuple[str, str]], document: dict) -> None:
    bond = document.get("bond") if isinstance(document.get("bond"), dict) else {}
    insights = bond.get("insights") if isinstance(bond.get("insights"), list) else []
    for insight in insights:
        if not isinstance(insight, dict):
            continue
        category = str(insight.get("category") or "")
        _add_block(
            blocks,
            _text(insight.get("title")) or CATEGORY_TITLE.get(category, "Связка"),
            _paragraphs(insight.get("snapshot"), insight.get("summary"), insight.get("deep_read")),
        )
    signs = document.get("signs") if isinstance(document.get("signs"), dict) else {}
    comparisons = signs.get("comparisons") if isinstance(signs.get("comparisons"), list) else []
    for row in comparisons:
        if not isinstance(row, dict):
            continue
        point = str(row.get("point") or "")
        _add_block(
            blocks,
            f"Знаки · {BODY_RU.get(point, point or 'положение')}",
            _paragraphs(row.get("meaning"), row.get("common_ground"), row.get("difference")),
        )


def _add_block(blocks: list[tuple[str, str]], title: str, text: str) -> None:
    if text:
        blocks.append((title, text))


def _score_text(row: dict) -> str:
    percent = ""
    value = row.get("value")
    if isinstance(value, (int, float)) and row.get("status") not in {"pending", "unavailable", "error"}:
        percent = f"{round(value)}%"
    return _paragraphs(percent, row.get("summary"))


def _cycle_text(row: dict) -> str:
    interpretation = row.get("interpretation") if isinstance(row.get("interpretation"), dict) else {}
    if row.get("status") != "ready" or not interpretation:
        return _EMPTY_CYCLE
    body = _text(interpretation.get("body")) or _paragraphs(
        interpretation.get("teaser"),
        interpretation.get("focus"),
        interpretation.get("sensitive_point"),
        interpretation.get("need"),
        interpretation.get("resource"),
        interpretation.get("relationship_lens"),
    )
    return _paragraphs(interpretation.get("headline"), interpretation.get("astrological_basis_ru"), body)


def _pair_text(pair: dict) -> str:
    if pair.get("status") not in {None, "ready"}:
        return ""
    card = pair.get("card") if isinstance(pair.get("card"), dict) else {}
    love = pair.get("love") if isinstance(pair.get("love"), dict) else {}
    title = _text(love.get("name") or card.get("name"))
    upright = _text(love.get("upright"))
    shadow = _text(love.get("reversed"))
    parts = [title]
    if upright:
        parts.append(f"Главная тема отношений\n{upright}")
    if shadow:
        parts.append(f"Теневая сторона\n{shadow}")
    return _paragraphs(*parts)


def _public_names(document: dict) -> dict[str, str]:
    names = {"A": "Ты", "B": "Партнёр"}
    people = document.get("persons")
    if not isinstance(people, list):
        return names
    for person in people:
        if isinstance(person, dict) and person.get("id") in names:
            name = _text(person.get("display_name"))
            if name:
                names[str(person["id"])] = name
    return names


def _reading_html(document: object) -> str:
    blocks = _reading_blocks(document)
    if not blocks:
        return _EMPTY_READING
    return format_html(
        '<div style="max-width:46rem">{}</div>',
        format_html_join(
            "",
            (
                '<section style="margin:0 0 1.35rem">'
                '<h3 style="margin:0 0 .35rem;font-size:13px">{}</h3>'
                '<div style="white-space:pre-wrap;line-height:1.45">{}</div>'
                "</section>"
            ),
            blocks,
        ),
    )


def _person_detail(person: dict | None) -> str:
    if not person:
        return "—"
    timezone_id = str(person.get("timezone_id") or "").strip() or "—"
    latitude = person.get("latitude")
    longitude = person.get("longitude")
    coords = "—"
    if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
        coords = f"{latitude:.4f}, {longitude:.4f}"
    return f"{_person_line(person)}\nчасовой пояс: {timezone_id}\nкоординаты: {coords}"


@admin.register(CompatibilityReport)
class CompatibilityReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "person_a", "person_b")
    list_display_links = ("created_at",)
    list_filter = ("created_at",)
    search_fields = ("input_hash",)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    readonly_fields = (
        "created_at",
        "entered_pair",
        "relationship_type",
        "reference_date",
        "written_reading",
        "id",
        "input_hash",
        "private_input",
        "updated_at",
    )
    fieldsets = (
        (
            "Что ввели",
            {"fields": ("created_at", "entered_pair", "relationship_type", "reference_date")},
        ),
        (
            "Что написали",
            {"fields": ("written_reading",)},
        ),
        (
            "Служебное",
            {
                "classes": ("collapse",),
                "fields": ("id", "input_hash", "private_input", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).defer("private_natals", "public_document")

    def get_search_results(self, request, queryset, search_term):
        term = (search_term or "").strip()
        if not term:
            return queryset, False
        annotated = queryset.annotate(_input_text=Cast("private_input", TextField()))
        matched = Q()
        for needle in _search_needles(term):
            matched |= Q(_input_text__icontains=needle) | Q(input_hash__icontains=needle)
        return annotated.filter(matched), False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            return False
        return super().has_change_permission(request, obj)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        context = {
            "show_save": False,
            "show_save_and_continue": False,
            "show_save_and_add_another": False,
        }
        if extra_context:
            context.update(extra_context)
        return super().change_view(request, object_id, form_url, context)

    @admin.display(description="Ты")
    def person_a(self, obj: CompatibilityReport) -> str:
        return _person_line(_compatibility_people(obj).get("A"))

    @admin.display(description="Партнёр")
    def person_b(self, obj: CompatibilityReport) -> str:
        return _person_line(_compatibility_people(obj).get("B"))

    @admin.display(description="Интерпретация")
    def written_reading(self, obj: CompatibilityReport) -> str:
        return _reading_html(obj.public_document)

    @admin.display(description="Пара")
    def entered_pair(self, obj: CompatibilityReport) -> str:
        people = _compatibility_people(obj)
        text = (
            f"Ты\n{_person_detail(people.get('A'))}\n\n"
            f"Партнёр\n{_person_detail(people.get('B'))}"
        )
        return format_html(
            '<pre style="white-space:pre-wrap;margin:0;font-family:inherit">{}</pre>',
            text,
        )


@admin.register(ChartShare)
class ChartShareAdmin(admin.ModelAdmin):
    list_display = ("token_prefix", "order", "user", "created_at", "revoked_at")
    list_filter = ("created_at",)
    search_fields = ("token_hash", "order__public_id", "user__email")
    readonly_fields = ("token_hash", "token_sealed", "created_at")
    raw_id_fields = ("order", "user")

    @admin.display(description="Токен")
    def token_prefix(self, obj: ChartShare) -> str:
        return f"{obj.token_hash[:8]}…"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "public_id",
        "status",
        "amount",
        "customer_email",
        "product_sku",
        "prodamus_order_id",
        "created_at",
        "paid_at",
        "fulfilled_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "public_id",
        "idempotency_key",
        "customer_email",
        "customer_phone",
        "customer_telegram",
        "prodamus_order_id",
        "session__token",
    )
    readonly_fields = (
        "public_id",
        "idempotency_key",
        "idempotency_request_hash",
        "payment_url",
        "prodamus_order_id",
        "webhook_payload",
        "interpretive",
        "created_at",
        "updated_at",
        "paid_at",
        "fulfilled_at",
        "fulfillment_error",
    )
    inlines = (ReportSectionFeedbackInline,)
    actions = ("send_demo_report",)

    @admin.action(description="Отметить оплаченным и отправить демо-отчёт")
    def send_demo_report(self, request, queryset):
        from core.services.fulfillment import FulfillmentError, mark_paid_and_deliver

        ok = 0
        for order in queryset:
            try:
                mark_paid_and_deliver(order, force=True)
                ok += 1
            except FulfillmentError as exc:
                self.message_user(
                    request,
                    f"{order.public_id}: {exc}",
                    level=messages.ERROR,
                )
        if ok:
            self.message_user(request, f"Демо-отчёт отправлен: {ok}", level=messages.SUCCESS)


class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline, JournalEntryInline)
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active", "date_joined")


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
admin.site.site_header = "Cosmirror Admin"
admin.site.site_title = "Cosmirror"
admin.site.index_title = "Пользователи и продукт"
