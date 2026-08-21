"""
Django settings for Cosmirror API.
"""

from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-change-me-cosmirror",
)

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]
if DEBUG:
    ALLOWED_HOSTS = list(
        dict.fromkeys(
            ALLOWED_HOSTS
            + ["*", ".ngrok-free.app", ".ngrok.io", ".trycloudflare.com", ".loca.lt"]
        )
    )

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "core.apps.CoreConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "idempotency-key",
)

# Trust X-Forwarded-Proto from nginx when serving HTTPS
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.authentication.BearerTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
}

# LLM — персонализация инсайта / оффера (опционально)
# Polza.ai (рекомендуется для RU/прод): https://polza.ai/docs
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "auto").strip().lower()
POLZA_API_KEY = (os.getenv("POLZA_API_KEY") or "").strip()
POLZA_BASE_URL = (os.getenv("POLZA_BASE_URL") or "https://polza.ai/api/v1").strip()
POLZA_MODEL = (os.getenv("POLZA_MODEL") or "openai/gpt-5.6-terra-pro").strip()
GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
GROQ_MODEL = (os.getenv("GROQ_MODEL") or "qwen/qwen3.6-27b").strip()

# Публичные URL (редиректы после оплаты + webhook для Prodamus)
FRONTEND_URL = (os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")
PUBLIC_API_URL = (os.getenv("PUBLIC_API_URL") or "http://127.0.0.1:8000").rstrip("/")

# Яндекс ID OAuth 2.0 — https://yandex.ru/dev/id/doc/ru/
YANDEX_OAUTH_CLIENT_ID = (os.getenv("YANDEX_OAUTH_CLIENT_ID") or "").strip()
YANDEX_OAUTH_CLIENT_SECRET = (os.getenv("YANDEX_OAUTH_CLIENT_SECRET") or "").strip()
YANDEX_OAUTH_REDIRECT_URI = (
    os.getenv("YANDEX_OAUTH_REDIRECT_URI") or f"{FRONTEND_URL}/onboarding/contacts"
).strip()

# Товар по умолчанию. Имя попадает в чек (54-ФЗ, до 128 символов).
COSMIRROR_PRODUCT_SKU = (os.getenv("COSMIRROR_PRODUCT_SKU") or "personal_report").strip()
COSMIRROR_PRODUCT_NAME = (
    os.getenv("COSMIRROR_PRODUCT_NAME") or "Персональный астрологический отчёт"
).strip()
COSMIRROR_PRODUCT_PRICE = (os.getenv("COSMIRROR_PRODUCT_PRICE") or "777").strip()
# «Доступы к материалам» / paid_content — обязательно для чека, даже в демо.
COSMIRROR_PRODUCT_PAID_CONTENT = (
    os.getenv("COSMIRROR_PRODUCT_PAID_CONTENT")
    or (
        "Персональный астрологический отчёт Cosmirror. "
        "После оплаты отправим отчёт на email, указанный при оформлении. "
        "https://cosmirror.ru"
    )
).strip()

# Prodamus Payform: https://help.prodamus.ru/payform/integracii/rest-api/instrukcii-dlya-samostoyatelnaya-integracii-servisov
PRODAMUS_FORM_URL = (os.getenv("PRODAMUS_FORM_URL") or "").strip()
PRODAMUS_SECRET_KEY = (os.getenv("PRODAMUS_SECRET_KEY") or "").strip()
PRODAMUS_SYS = (os.getenv("PRODAMUS_SYS") or "").strip()
PRODAMUS_DEMO_MODE = os.getenv("PRODAMUS_DEMO_MODE", "0") == "1"
PRODAMUS_NOTIFICATION_URL = (os.getenv("PRODAMUS_NOTIFICATION_URL") or "").strip()
# Короткие do=link счета игнорируют ?ref=. Скидку надо передать как discount_value.
# Формат: code:rubles,code2:rubles
PRODAMUS_PROMO_DISCOUNTS = (os.getenv("PRODAMUS_PROMO_DISCOUNTS") or "test100:776").strip()

# Почта Cosmirror: ящик hello@cosmirror.ru на хостинге REG.RU
# https://help.reg.ru/support/hosting/nastroyka-pochty-regru/nastroyka-pochty-i-pochtovykh-kliyentovv/nastroyka-pochtovykh-kliyentovv
RESEND_API_KEY = (os.getenv("RESEND_API_KEY") or "").strip()
EMAIL_FROM = (os.getenv("EMAIL_FROM") or "Cosmirror <hello@cosmirror.ru>").strip()
EMAIL_BCC = (os.getenv("EMAIL_BCC") or "hello@cosmirror.ru").strip()
EMAIL_HOST = (os.getenv("EMAIL_HOST") or "mail.hosting.reg.ru").strip()
EMAIL_PORT = int(os.getenv("EMAIL_PORT") or "465")
EMAIL_HOST_USER = (os.getenv("EMAIL_HOST_USER") or "hello@cosmirror.ru").strip()
EMAIL_HOST_PASSWORD = (os.getenv("EMAIL_HOST_PASSWORD") or "").strip()
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "1") == "1"
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "0") == "1"
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST_PASSWORD or RESEND_API_KEY
    else "django.core.mail.backends.console.EmailBackend",
)
