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
    "calendar_sync",
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
    # TLS terminates at the shared Caddy reverse proxy, which forwards plain
    # HTTP with `X-Forwarded-Proto: https`. Without this, SECURE_SSL_REDIRECT
    # (set just above) sees every proxied request as insecure and 301-loops.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# Auth
LOGIN_URL = "/accounts/login/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Cache / rate-limit backend. The three AI rate-limit buckets
# (``ai_cmd_rl`` / ``ai_draft_rl`` / ``ai_chat_rl``, see
# ``ai.views._consume_rate_limit``) and the ``caldav_events:*`` keys both
# live in ``CACHES['default']``. Production-shaped deploys point
# ``REDIS_URL`` at a shared Redis so the counters are atomic (Redis
# ``INCR``) and global across workers. When ``REDIS_URL`` is unset we fall
# back to ``LocMemCache`` — the conventional dev backend the test suite
# assumes (pinned in ``conftest.py``). That fallback only boots cleanly
# when AI is disabled: the ``ai.E001`` system check blocks startup on an
# ineffective backend (LocMem / FileBased / Dummy) whenever ``LLM_API_KEY``
# is set, independent of ``DEBUG``.
# ``.strip()`` so a whitespace-only value (stray trailing space in .env,
# or a templated/CI var that resolves to blank) falls back to LocMem and
# trips ``ai.E001`` loudly when AI is enabled — rather than selecting
# RedisCache with a blank LOCATION that only fails on the first cache hit.
# Mirrors the ``LLM_API_KEY.strip()`` guard in ``ai/checks.py``.
REDIS_URL = os.environ.get("REDIS_URL", "").strip()
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            # Namespace keys so a Redis shared with another app doesn't
            # collide on ``ai_cmd_rl:*`` / ``caldav_events:*``.
            "KEY_PREFIX": "dayforge",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
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
# Set to a writable file path to capture the rendered LLM draft user_message
# on every generate-draft call. Used by the Phase 6 Test 7 e2e script
# (frontend/scripts/playwright/draft-prompt-history-suffix.mjs) to verify
# the prompt content end-to-end without manually patching service.py. Empty
# string disables capture (default). Default-off so production deployments
# never write the prompt to disk.
LLM_DRAFT_CAPTURE_PROMPT_PATH = os.environ.get("LLM_DRAFT_CAPTURE_PROMPT_PATH", "")

# Chat (feature 0007). Independent rate-limit bucket from the one-shot
# command endpoint — same shared-cache requirement enforced by ai.E001.
# A "task" typically takes 3-5 chat turns, so the budget is set such that
# ~12 distinct tasks/hour fit comfortably without leaving accidental
# headroom for runaway loops.
LLM_CHAT_RATE_LIMIT_PER_HOUR = int(
    os.environ.get("LLM_CHAT_RATE_LIMIT_PER_HOUR", "60")
)
# Hard cap on len(messages[]) per request. Protects against runaway
# transcript size if the client never resets the thread.
LLM_CHAT_MAX_TURNS = int(os.environ.get("LLM_CHAT_MAX_TURNS", "20"))
# Hard cap on the sum of len(content) across all messages — caps prompt
# cost regardless of how many short turns the user piles on. Default is
# 4× LLM_MAX_COMMAND_CHARS so the user can comfortably build up a
# multi-turn brief without bumping into the limit on a normal session.
LLM_CHAT_MAX_TOTAL_CHARS = int(
    os.environ.get(
        "LLM_CHAT_MAX_TOTAL_CHARS", str(LLM_MAX_COMMAND_CHARS * 4)
    )
)
# Schema caps on the model's per-turn output. Truncated provider responses
# or runaway questions surface as a parse error (502) rather than a UI
# overflow.
LLM_CHAT_MAX_ASK_CHARS = int(os.environ.get("LLM_CHAT_MAX_ASK_CHARS", "300"))
# Cap on the LLM's ``explanation`` field — applies to BOTH the chat envelope
# (feature 0007) and the legacy one-shot ``validate_response_envelope``. A
# unified cap keeps the two surfaces consistent (the chat plan called this
# out as "apply the same cap to the existing one-shot for consistency"). The
# default 300 is intentionally tighter than the previous hardcoded 500 in
# ``schemas.py``; the system prompt asks for a one-sentence explanation, so
# anything beyond 300 is already a deviation from the requested format.
LLM_MAX_EXPLANATION_CHARS = int(
    os.environ.get("LLM_MAX_EXPLANATION_CHARS", "300")
)

# Validate the chat-related caps at import time so a misconfigured deploy
# fails worker boot loudly instead of silently producing degenerate
# behaviour (e.g. an unreachable rate limit, a turn cap of zero that
# rejects every request, a transcript char cap of zero that 400s every
# message). Mirrors the ``ANALYTICS_STREAK_*`` precedent below.
# Scope: only the settings introduced in feature 0007. Pre-existing LLM
# settings (``LLM_RATE_LIMIT_PER_HOUR``, ``LLM_HISTORY_DAYS``,
# ``LLM_REQUEST_TIMEOUT``, etc.) are intentionally NOT validated here —
# they have shipped without validation since Phase 4 and tightening them
# in this PR would be scope creep that could break tolerated deploy
# configurations.
for _name, _value in (
    ("LLM_CHAT_RATE_LIMIT_PER_HOUR", LLM_CHAT_RATE_LIMIT_PER_HOUR),
    ("LLM_CHAT_MAX_TURNS", LLM_CHAT_MAX_TURNS),
    ("LLM_CHAT_MAX_TOTAL_CHARS", LLM_CHAT_MAX_TOTAL_CHARS),
    ("LLM_CHAT_MAX_ASK_CHARS", LLM_CHAT_MAX_ASK_CHARS),
    ("LLM_MAX_EXPLANATION_CHARS", LLM_MAX_EXPLANATION_CHARS),
):
    if _value <= 0:
        raise ValueError(
            f"{_name} must be a positive integer; got {_value!r}"
        )
del _name, _value

# ---------------------------------------------------------------------------
# CalDAV / Apple Calendar (feature 0011)
# ---------------------------------------------------------------------------
# Fernet symmetric encryption key (URL-safe base64, 32 bytes). No insecure
# default — empty value is tolerated only when DEBUG=True. The
# ``calendar_sync.E001`` system check blocks DEBUG=False startup if unset
# and ``calendar_sync.crypto`` raises ImproperlyConfigured at use time.
CALDAV_ENCRYPTION_KEY = os.environ.get("CALDAV_ENCRYPTION_KEY", "")
# Default base URL used by the connect-flow when the user doesn't provide
# one. Echoed back via GET /api/calendar/account/ so the frontend never
# hardcodes the default.
CALDAV_DEFAULT_BASE_URL = os.environ.get(
    "CALDAV_DEFAULT_BASE_URL", "https://caldav.icloud.com/"
)
# Hard cap on each CalDAV HTTP call. Same risk profile as
# LLM_REQUEST_TIMEOUT — a hung iCloud connection must not pin a worker.
CALDAV_REQUEST_TIMEOUT = float(os.environ.get("CALDAV_REQUEST_TIMEOUT", "10"))
# Per-(user, date) event-list cache window. Versioned keys (see
# calendar_sync/cache.py) keep correctness intact regardless of backend;
# the ``calendar_sync.W001`` check warns when the backend is non-shared.
CALDAV_CACHE_TTL_SECONDS = int(os.environ.get("CALDAV_CACHE_TTL_SECONDS", "300"))
# Match the ANALYTICS_STREAK_* import-time validation pattern: fail
# loudly on a misconfigured deploy rather than silently producing
# zero-TTL caches (every request a cache miss, hammering iCloud).
if CALDAV_CACHE_TTL_SECONDS <= 0:
    raise ValueError(
        "CALDAV_CACHE_TTL_SECONDS must be a positive integer; "
        f"got {CALDAV_CACHE_TTL_SECONDS!r}"
    )
if CALDAV_REQUEST_TIMEOUT <= 0:
    raise ValueError(
        "CALDAV_REQUEST_TIMEOUT must be a positive number; "
        f"got {CALDAV_REQUEST_TIMEOUT!r}"
    )

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
