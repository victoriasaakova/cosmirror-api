from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("me/", views.MeView.as_view(), name="me"),
    path("me/birth/", views.MeBirthView.as_view(), name="me-birth"),
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
    path("auth/logout/", views.AuthLogoutView.as_view(), name="auth-logout"),
    path("auth/dev-login/", views.AuthDevLoginView.as_view(), name="auth-dev-login"),
    path("me/dev-reset/", views.MeDevResetView.as_view(), name="me-dev-reset"),
    path("me/report/", views.MeReportView.as_view(), name="me-report"),
    path("me/cabinet/", views.MeCabinetView.as_view(), name="me-cabinet"),
    path(
        "me/cabinet/locked-preview/<slug:section>/",
        views.MeCabinetLockedPreviewView.as_view(),
        name="me-cabinet-locked-preview",
    ),
    path(
        "me/report/feedback/",
        views.MeReportFeedbackView.as_view(),
        name="me-report-feedback",
    ),
    path(
        "me/report/natal/generate/",
        views.MeReportNatalGenerateView.as_view(),
        name="me-report-natal-generate",
    ),
    path(
        "me/report/aspects/generate/",
        views.MeReportAspectsGenerateView.as_view(),
        name="me-report-aspects-generate",
    ),
    path(
        "me/report/cycles/generate/",
        views.MeReportCyclesGenerateView.as_view(),
        name="me-report-cycles-generate",
    ),
    path("me/report.pdf/", views.MeReportPdfView.as_view(), name="me-report-pdf"),
    path("me/report/email/", views.MeReportEmailView.as_view(), name="me-report-email"),
    path(
        "me/report/demo-complete/",
        views.MeReportDemoCompleteView.as_view(),
        name="me-report-demo-complete",
    ),
    path(
        "me/report/confirm-payment/",
        views.MeReportConfirmPaymentView.as_view(),
        name="me-report-confirm-payment",
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
    path("landing/chart/", views.LandingChartView.as_view(), name="landing-chart"),
    path(
        "landing/chart/<uuid:token>/",
        views.LandingChartDetailView.as_view(),
        name="landing-chart-detail",
    ),
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
