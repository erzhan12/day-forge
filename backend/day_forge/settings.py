import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BASE_DIR.parent

load_dotenv(PROJECT_ROOT / ".env")

DEBUG = os.environ.get("DEBUG", "1") == "1"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-dev-only-key-do-not-use-in-production"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY environment variable is required in production.")

if DEBUG:
    ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
else:
    ALLOWED_HOSTS = [h for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "inertia",
    "schedules",
    "templates_mgr",
    "ai",
    "analytics",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "inertia.middleware.InertiaMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "day_forge.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "day_forge.context_processors.vite_dev_mode",
            ],
        },
    },
]

WSGI_APPLICATION = "day_forge.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": PROJECT_ROOT / "db" / "day_forge.db",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [PROJECT_ROOT / "frontend" / "dist"]
STATIC_ROOT = PROJECT_ROOT / "staticfiles"

# Inertia
INERTIA_LAYOUT = "base.html"
INERTIA_SSR_ENABLED = False

# CSRF for Inertia (X-XSRF-TOKEN header)
CSRF_COOKIE_NAME = "XSRF-TOKEN"
CSRF_HEADER_NAME = "HTTP_X_XSRF_TOKEN"
if DEBUG:
    CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://localhost:8006"]
else:
    CSRF_TRUSTED_ORIGINS = [
        h for h in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if h
    ]

# Cookie security
CSRF_COOKIE_HTTPONLY = False  # frontend JS reads XSRF-TOKEN cookie
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31_536_000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# Auth
LOGIN_URL = "/accounts/login/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": PROJECT_ROOT / ".cache",
    }
}

# LLM (OpenAI-compatible; swap base URL for OpenRouter, etc.)
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
LLM_REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "15"))
LLM_MAX_COMMAND_CHARS = int(os.environ.get("LLM_MAX_COMMAND_CHARS", "500"))
LLM_RATE_LIMIT_PER_HOUR = int(os.environ.get("LLM_RATE_LIMIT_PER_HOUR", "100"))
# Heavier model used for draft generation (PRD §15.3). Defaults to gpt-4o
# (~5-10x cost of LLM_MODEL) since drafts shape a whole day from history
# and benefit from the larger context window.
LLM_DRAFT_MODEL = os.environ.get("LLM_DRAFT_MODEL", "gpt-4o")
# Independent fixed-window counter for the draft endpoint. Drafts are
# billed against a separate budget so a misbehaving auto-trigger loop
# can't drain the command budget too. Default 10/hr is well above realistic
# usage (one auto + one or two manual regenerates per day).
LLM_DRAFT_RATE_LIMIT_PER_HOUR = int(
    os.environ.get("LLM_DRAFT_RATE_LIMIT_PER_HOUR", "10")
)
# Number of past schedules included in the draft context (PRD §6.2).
LLM_HISTORY_DAYS = int(os.environ.get("LLM_HISTORY_DAYS", "7"))

# Analytics / streak. Validated at import time so a misconfigured value
# fails the worker boot loudly instead of silently producing ``streak=0``
# forever. ``ANALYTICS_STREAK_THRESHOLD`` is the per-day completion ratio
# required for a day to count toward the streak; ``ANALYTICS_STREAK_WINDOW_DAYS``
# caps the backward calendar walk so an old account doesn't trigger an
# O(account-age) scan.
ANALYTICS_STREAK_THRESHOLD = float(os.environ.get("ANALYTICS_STREAK_THRESHOLD", "0.8"))
if not (0.0 <= ANALYTICS_STREAK_THRESHOLD <= 1.0):
    raise ValueError(
        "ANALYTICS_STREAK_THRESHOLD must be a float in [0.0, 1.0]; "
        f"got {ANALYTICS_STREAK_THRESHOLD!r}"
    )
ANALYTICS_STREAK_WINDOW_DAYS = int(os.environ.get("ANALYTICS_STREAK_WINDOW_DAYS", "30"))
if ANALYTICS_STREAK_WINDOW_DAYS <= 0:
    raise ValueError(
        "ANALYTICS_STREAK_WINDOW_DAYS must be a positive integer; "
        f"got {ANALYTICS_STREAK_WINDOW_DAYS!r}"
    )
