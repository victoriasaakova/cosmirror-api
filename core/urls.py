from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("me/", views.MeView.as_view(), name="me"),
    path(
        "auth/yandex/start/",
        views.YandexAuthStartView.as_view(),
        name="auth-yandex-start",
    ),
    path(
        "auth/yandex/callback/",
        views.YandexAuthCallbackView.as_view(),
        name="auth-yandex-callback",
    ),
    path("me/report/", views.MeReportView.as_view(), name="me-report"),
    path("me/report.pdf/", views.MeReportPdfView.as_view(), name="me-report-pdf"),
    path("me/report/email/", views.MeReportEmailView.as_view(), name="me-report-email"),
    path(
        "me/report/demo-complete/",
        views.MeReportDemoCompleteView.as_view(),
        name="me-report-demo-complete",
    ),
    path("waitlist/", views.WaitlistCreateView.as_view(), name="waitlist"),
    path("journal/", views.JournalEntryListCreateView.as_view(), name="journal"),
    # Онбординг
    path("onboarding/steps/", views.OnboardingStepListView.as_view(), name="onboarding-steps"),
    path(
        "onboarding/sessions/",
        views.OnboardingSessionCreateView.as_view(),
        name="onboarding-session-create",
    ),
    path(
        "onboarding/sessions/<uuid:token>/",
        views.OnboardingSessionDetailView.as_view(),
        name="onboarding-session-detail",
    ),
    path(
        "onboarding/sessions/<uuid:token>/steps/<slug:slug>/",
        views.OnboardingStepSubmitView.as_view(),
        name="onboarding-step-submit",
    ),
    path(
        "onboarding/sessions/<uuid:token>/insight/",
        views.OnboardingInsightView.as_view(),
        name="onboarding-insight",
    ),
    # Гео для онбординга
    path("geo/lookup/", views.GeoLookupView.as_view(), name="geo-lookup"),
    path("geo/suggest/", views.GeoSuggestView.as_view(), name="geo-suggest"),
    # Вводы в продукте
    path("inputs/", views.UserInputListCreateView.as_view(), name="user-inputs"),
    # Астро
    path("astro/charts/", views.NatalChartListView.as_view(), name="natal-charts"),
    path("astro/cycles/", views.GlobalCycleListView.as_view(), name="global-cycles"),
    path("astro/sky-now/", views.SkyNowView.as_view(), name="sky-now"),
    # Оплата Prodamus
    path("orders/", views.OrderCreateView.as_view(), name="order-create"),
    path("orders/<uuid:public_id>/", views.OrderDetailView.as_view(), name="order-detail"),
    path(
        "orders/<uuid:public_id>/report.pdf/",
        views.OrderReportPdfView.as_view(),
        name="order-report-pdf",
    ),
    path(
        "orders/<uuid:public_id>/email/",
        views.OrderEmailView.as_view(),
        name="order-email",
    ),
    path(
        "orders/<uuid:public_id>/demo-complete/",
        views.OrderDemoCompleteView.as_view(),
        name="order-demo-complete",
    ),
    path(
        "payments/prodamus/webhook/",
        views.ProdamusWebhookView.as_view(),
        name="prodamus-webhook",
    ),
    # Без слэша: иначе APPEND_SLASH делает 301 POST→GET и webhook теряется.
    path(
        "payments/prodamus/webhook",
        views.ProdamusWebhookView.as_view(),
        name="prodamus-webhook-noslash",
    ),
]
