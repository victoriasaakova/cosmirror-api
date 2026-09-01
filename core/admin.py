from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import (
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

    @admin.display(description="Комментарий")
    def short_comment(self, obj: ReportSectionFeedback) -> str:
        text = (obj.comment or "").strip()
        if not text:
            return "—"
        return text if len(text) <= 80 else f"{text[:77]}…"


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
