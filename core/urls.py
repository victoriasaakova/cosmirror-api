from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("me/", views.MeView.as_view(), name="me"),
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
]
