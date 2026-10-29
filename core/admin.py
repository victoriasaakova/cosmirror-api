import json

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.db.models import Q, TextField
from django.db.models.functions import Cast
from django.utils.html import format_html

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
