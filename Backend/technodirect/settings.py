"""Django settings for the TechnoDirect live dashboard backend.

All configuration comes from environment / `.env` (django-environ). Values containing
`REPLACE_ME` are treated as unset (see technodirect/envutil.py).
"""
from datetime import timedelta
from pathlib import Path

import sys
import environ
from celery.schedules import crontab

from .envutil import env_bool, env_int, env_list, env_str, parse_times

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
# Hosted mode (deploy/windows): TD_ENV_FILE=.env.production is read first and wins over .env, so the same .env keeps
# the shared settings (data paths, email, ...) and the production file only holds what differs (DEBUG, hosts, key).
_td_env_file = __import__("os").environ.get("TD_ENV_FILE")
if _td_env_file and Path(_td_env_file).exists():
    environ.Env.read_env(_td_env_file, overwrite=True)
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(str(BASE_DIR / ".env"))

DEBUG = env_bool("DEBUG", False)
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
SECRET_KEY = env_str("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-insecure-key-only-for-local-development-do-not-use-in-prod"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is False")

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
# Render sets its public hostname (xxx.onrender.com) - accept it without editing ALLOWED_HOSTS by hand
RENDER_EXTERNAL_HOSTNAME = env_str("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
TIME_ZONE = env_str("TIME_ZONE", "Asia/Kolkata")
USE_TZ = True
USE_I18N = False
LANGUAGE_CODE = "en-in"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_celery_beat",
    "warehouse",
    "accounts",
    "ingestion",
    "analytics",
    "masters",
    "assistant",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # after an edit through the API, back the edited data up to Supabase (no-op until SUPABASE_EDITS_* is set)
    "ingestion.edit_store.EditBackupMiddleware",
]

ROOT_URLCONF = "technodirect.urls"
WSGI_APPLICATION = "technodirect.wsgi.application"

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
            ]
        },
    }
]

# --- Databases ---------------------------------------------------------------
_db_url = env_str("DATABASE_URL")
if _db_url:
    DATABASES = {"default": env.db_url_config(_db_url)}
    DATABASES["default"]["CONN_MAX_AGE"] = 60
else:  # local development fallback
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            # WAL lets the dashboard keep reading while the scheduled refresh writes
            "OPTIONS": {"timeout": 30, "transaction_mode": "IMMEDIATE",
                        "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"},
        }
    }

# The TD tables on Supabase (orders, sales, customers, distributors, products, inventory, loyalty; in rupees). Read-only login
# td_dashboard_ro (deploy/supabase_readonly.sql), through the Supabase Session pooler. Raw SQL only, never migrated
# (technodirect/db_router.py); configured only when host, user and password are all filled in.
_sb_host, _sb_user, _sb_pass = (env_str("SUPABASE_DB_HOST"), env_str("SUPABASE_DB_USER"),
                                env_str("SUPABASE_DB_PASSWORD"))
if _sb_host and _sb_user and _sb_pass:
    DATABASES["supabase"] = {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": _sb_host,
        "PORT": env_int("SUPABASE_DB_PORT", 5432),
        "NAME": env_str("SUPABASE_DB_NAME", "postgres") or "postgres",
        "USER": _sb_user,
        "PASSWORD": _sb_pass,
        "CONN_MAX_AGE": 0,
        # encrypted, and belt and braces: the session itself is read-only and statements time out
        "OPTIONS": {"sslmode": env_str("SUPABASE_DB_SSLMODE", "require") or "require", "connect_timeout": 15,
                    "options": "-c default_transaction_read_only=on -c statement_timeout=120000"},
        "TEST": {"MIRROR": "default"},
    }
# What admins edit in the dashboard (users, targets, ASMs, handovers, mappings, ...) is backed up to Supabase, one schema
# per dashboard module, with a separate login that can write only there (deploy/supabase_edits.sql, ingestion/edit_store.py),
# and restored automatically on a new server.
_sbw_user, _sbw_pass = env_str("SUPABASE_EDITS_USER"), env_str("SUPABASE_EDITS_PASSWORD")
if _sb_host and _sbw_user and _sbw_pass:
    DATABASES["supabase_edits"] = {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": _sb_host,
        "PORT": env_int("SUPABASE_DB_PORT", 5432),
        "NAME": env_str("SUPABASE_DB_NAME", "postgres") or "postgres",
        "USER": _sbw_user,
        "PASSWORD": _sbw_pass,
        "CONN_MAX_AGE": 0,
        "OPTIONS": {"sslmode": env_str("SUPABASE_DB_SSLMODE", "require") or "require", "connect_timeout": 15,
                    "options": "-c statement_timeout=120000"},
        "TEST": {"MIRROR": "default"},
    }

# Which stock the dashboard shows: 'td' = app stock (TD database), 'ck' = Channel Konnect.
INVENTORY_PRIMARY_SOURCE = env_str("INVENTORY_PRIMARY_SOURCE", "td") or "td"

DATABASE_ROUTERS = ["technodirect.db_router.ReadOnlySourceRouter"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
]

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Hosting the built frontend from Django (single-server setup, deploy/windows) ---------------------------------
# FRONTEND_DIST = Frontend/dist built with VITE_API_BASE_URL=/api. WhiteNoise serves its files; unknown paths fall
# back to index.html (technodirect/urls.py) so links like /settlements work on reload.
FRONTEND_DIST = env_str("FRONTEND_DIST")
if FRONTEND_DIST and not Path(FRONTEND_DIST).is_absolute():
    FRONTEND_DIST = str((BASE_DIR / FRONTEND_DIST).resolve())  # e.g. ../Frontend/dist on Render
if FRONTEND_DIST and Path(FRONTEND_DIST).is_dir():
    MIDDLEWARE.insert(MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
                      "whitenoise.middleware.WhiteNoiseMiddleware")
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = True
    WHITENOISE_MAX_AGE = 3600
else:
    FRONTEND_DIST = ""

# --- Cache -------------------------------------------------------------------
REDIS_URL = env_str("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "TIMEOUT": 600,
            "KEY_PREFIX": "td",
        }
    }
elif env_str("CACHE_DIR") and not TESTING:  # tests keep a private in-memory cache (never the live pages)
    # Hosted on one Windows machine without Redis: a file cache shared by the web server and the scheduled refresh
    # (an in-memory cache would not see the refresh bump the data version).
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": env_str("CACHE_DIR"),
            "TIMEOUT": 600,
            "OPTIONS": {"MAX_ENTRIES": 20000},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "td-local",
            "TIMEOUT": 600,
        }
    }
# Analytics responses are cached until the next scheduled refresh (+ this buffer);
# refresh_all also bumps the cache version so stale entries are never served.
ANALYTICS_CACHE_BUFFER_SECONDS = env_int("ANALYTICS_CACHE_BUFFER_SECONDS", 15 * 60)

# --- DRF / JWT ---------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "analytics.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
    "COERCE_DECIMAL_TO_STRING": False,
    # Only views that set throttle_scope are rate-limited (login + OTP endpoints).
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"login": "10000/min", "otp": "10000/min", "assistant": "10000/min"} if TESTING else {
        "login": env_str("LOGIN_RATE_LIMIT", "20/min"), "otp": env_str("OTP_RATE_LIMIT", "30/min"),
        "assistant": env_str("ASSISTANT_RATE_LIMIT", "15/min")},
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- CORS --------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", ["http://localhost:5173"])
# Local development: Vite moves to 5174, 5175... when 5173 is busy, so allow any localhost port.
CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://(localhost|127\.0\.0\.1):\d+$"] if DEBUG else []
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", [])
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")
CORS_EXPOSE_HEADERS = ["Content-Disposition"]

# --- Celery ------------------------------------------------------------------
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or None
CELERY_TASK_ALWAYS_EAGER = not bool(REDIS_URL)  # no broker locally -> run inline
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 20
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# Data refreshes only at fixed IST times (default 10:30 and 15:30). One chained job:
# Supabase (TD data) -> PayU -> CRM sheet -> Channel Konnect -> BlueOrigin / settlement / stock sheets
# -> derivations -> cache invalidation.
SYNC_TIMES = parse_times(env_str("SYNC_TIMES", "10:30,15:30"))
# The web server runs that refresh itself at SYNC_TIMES (ingestion/scheduler.py) - locally, on Windows or on Render,
# catching up on start if a slot was missed. Set AUTO_REFRESH=false only for a second server on the same database.
AUTO_REFRESH = env_bool("AUTO_REFRESH", True)
CELERY_BEAT_SCHEDULE = {
    f"refresh-all-{h:02d}{m:02d}-ist": {"task": "ingestion.tasks.refresh_all", "schedule": crontab(hour=h, minute=m)}
    for h, m in SYNC_TIMES
}
# TD Target Forecaster: on the 27th (after the 10:30 refresh) suggest next month's targets per ASM / distributor
CELERY_BEAT_SCHEDULE["forecast-next-month-targets"] = {
    "task": "masters.tasks.forecast_next_month_targets", "schedule": crontab(day_of_month=27, hour=11, minute=0)}
# A scheduled refresh counts as "missed" (freshness=stale) this long after its slot.
REFRESH_GRACE_MINUTES = env_int("REFRESH_GRACE_MINUTES", 30)

# --- Business defaults --------------------------------------------------------
LAUNCH_DATE = "2024-12-01"
ORDER_DISPATCH_SLA_HOURS = env_int("ORDER_DISPATCH_SLA_HOURS", 48)
# Shipped -> delivered target (days) for the Order flow & delays section.
ORDER_TRANSIT_SLA_DAYS = env_int("ORDER_TRANSIT_SLA_DAYS", 3)
# "Open" orders (ageing, SLA breaches) = still placed / confirmed / shipped AND placed within this many days. The TD
# export's ts_order_status is not updated for many old orders (770 "packed" orders over a year old); those are
# reported separately as stale statuses instead of inflating the open-order counts.
ORDER_OPEN_WINDOW_DAYS = env_int("ORDER_OPEN_WINDOW_DAYS", 30)
# What "Sales" counts (user decision 2026-11-26: the dashboard must match the finance "Order Tracking" sheet):
#   tracker - every paid order at its order value (incl. loyalty points), cancelled and company-internal ones included,
#             exactly as the sheet lists them;
#   net     - the earlier basis: line totals of paid, not-cancelled orders of real distributors.
SALES_BASIS = env_str("SALES_BASIS", "tracker").lower()
LOW_STOCK_THRESHOLD = env_int("LOW_STOCK_THRESHOLD", 5)
RECONCILIATION_TOLERANCE_PCT = 1.0

# --- Integrations (placeholder => "" => not configured) -----------------------
# BlueOrigin offline sheets (FY??_qtr?.csv + Dist-state.xlsx), e.g. the synced Dropbox "Power BI" folder
BLUEORIGIN_DIR = env_str("BLUEORIGIN_DIR")
# ... or the same sheets live from Dropbox through its API (masters/dropbox_bo.py). When all three credentials are
# set, the API is used and BLUEORIGIN_DIR is ignored. Get the refresh token with `manage.py dropbox_auth`.
DROPBOX_APP_KEY = env_str("DROPBOX_APP_KEY")
DROPBOX_APP_SECRET = env_str("DROPBOX_APP_SECRET")
DROPBOX_REFRESH_TOKEN = env_str("DROPBOX_REFRESH_TOKEN")
DROPBOX_BO_PATH = env_str("DROPBOX_BO_PATH", "/Power BI")  # the folder as seen in Dropbox (not the PC path)
DROPBOX_BO_MIRROR = env_str("DROPBOX_BO_MIRROR")  # local copy; default Backend/data/blueorigin_dropbox
# finance team's distributor settlement tracker ("Technodirect Order Tracking" / Tracker) and the "TechnoD
# Distributors" stock-sync sheet ("Inventory Updated" = stock sync date): read LIVE from Google Sheets only, at every
# refresh (ingestion/gsheets.py; needs GOOGLE_SERVICE_ACCOUNT_JSON and the sheet shared with that account).
SETTLEMENT_SHEET_URL = env_str("SETTLEMENT_SHEET_URL")
DISTRIBUTOR_SYNC_SHEET_URL = env_str("DISTRIBUTOR_SYNC_SHEET_URL")
# which tab of each spreadsheet (by name; a #gid in the link overrides it)
SETTLEMENT_SHEET_TAB = env_str("SETTLEMENT_SHEET_TAB", "Tracker")
DISTRIBUTOR_SYNC_SHEET_TAB = env_str("DISTRIBUTOR_SYNC_SHEET_TAB", "TechnoD Distributors")
PAYU_MERCHANT_KEY = env_str("PAYU_MERCHANT_KEY")
PAYU_MERCHANT_SALT = env_str("PAYU_MERCHANT_SALT")
PAYU_BASE_URL = env_str("PAYU_BASE_URL", "https://info.payu.in")
PAYU_CLIENT_ID = env_str("PAYU_CLIENT_ID")
PAYU_CLIENT_SECRET = env_str("PAYU_CLIENT_SECRET")

GOOGLE_SERVICE_ACCOUNT_JSON = env_str("GOOGLE_SERVICE_ACCOUNT_JSON")
# CRM issues tracker ("B2B Order Tracker CRM"): the browser link incl. #gid (or the sheet id + tab name)
CRM_SHEET_URL = env_str("CRM_SHEET_URL")
CRM_SHEET_ID = env_str("CRM_SHEET_ID")
CRM_SHEET_TAB = env_str("CRM_SHEET_TAB")
# monthly ASM / executive targets ("TD_ASM_Executive_Incentive_Tracker", masters/target_sheet.py): only the months
# written in the sheet are changed
TARGETS_SHEET_URL = env_str("TARGETS_SHEET_URL")
TARGETS_SHEET_TAB = env_str("TARGETS_SHEET_TAB", "Monthly Tracker")

CK_BASE_URL = env_str("CK_BASE_URL")
CK_API_KEY = env_str("CK_API_KEY")

MASTER_ADMIN_EMAIL = env_str("MASTER_ADMIN_EMAIL")
MASTER_ADMIN_PASSWORD = env_str("MASTER_ADMIN_PASSWORD")

# --- Techno AI assistant (Ollama) ---------------------------------------------
ASSISTANT_ENABLED = env_bool("ASSISTANT_ENABLED", True)
OLLAMA_BASE_URL = env_str("OLLAMA_BASE_URL", "https://ollama.com")
OLLAMA_API_KEY = env_str("OLLAMA_API_KEY")
OLLAMA_MODEL = env_str("OLLAMA_MODEL")
OLLAMA_TIMEOUT = env_int("OLLAMA_TIMEOUT", 90)
OLLAMA_NUM_CTX = env_int("OLLAMA_NUM_CTX", 16384)

# --- Login OTP (6-digit code emailed after the password step) -----------------
LOGIN_OTP_ENABLED = env_bool("LOGIN_OTP_ENABLED", True)
LOGIN_OTP_TTL_MINUTES = env_int("LOGIN_OTP_TTL_MINUTES", 5)
LOGIN_OTP_MAX_ATTEMPTS = env_int("LOGIN_OTP_MAX_ATTEMPTS", 5)
LOGIN_OTP_MAX_SENDS = env_int("LOGIN_OTP_MAX_SENDS", 5)
LOGIN_OTP_RESEND_SECONDS = env_int("LOGIN_OTP_RESEND_SECONDS", 30)

# --- Daily MIS email (analytics/daily_mis.py): sent after the morning refresh, only when recipients are set ---
MIS_RECIPIENTS = env_str("MIS_RECIPIENTS")  # comma-separated; empty = the daily MIS is not sent
PUBLIC_DASHBOARD_URL = env_str("PUBLIC_DASHBOARD_URL")  # link shown in the email (optional)

# --- Email (Gmail SMTP: smtp.gmail.com:587 + TLS, EMAIL_HOST_PASSWORD = Google App Password) ---
EMAIL_HOST = env_str("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_HOST_USER = env_str("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env_str("EMAIL_HOST_PASSWORD").replace(" ", "")  # app passwords are shown with spaces
EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 20)
DEFAULT_FROM_EMAIL = env_str("DEFAULT_FROM_EMAIL") or (
    f"TechnoDirect Dashboard <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "TechnoDirect Dashboard <noreply@localhost>")
if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
elif DEBUG:
    # Local development without SMTP credentials: the email (with the code) is printed in the runserver console.
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"  # fails loudly until EMAIL_* are set

# --- Security (prod) ------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}
