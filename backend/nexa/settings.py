import os
from pathlib import Path
from urllib.parse import urlsplit

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("NEXA_DEBUG", "1") == "1"

SECRET_KEY = os.environ.get("NEXA_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("Set NEXA_SECRET_KEY when NEXA_DEBUG=0")
    SECRET_KEY = "dev-only-insecure-key-change-me"

ALLOWED_HOSTS = [h for h in os.environ.get("NEXA_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

# Origins allowed to call the API from a browser. "null" covers the frontend opened from file://.
CORS_ALLOWED_ORIGINS = [
    o for o in os.environ.get("NEXA_CORS_ORIGINS", "null,http://localhost:5500,http://127.0.0.1:5500,http://localhost:8080").split(",") if o
]
# In development any localhost or 127.0.0.1 port may call the API, so changing the dev server port never breaks sign-in.
CORS_ALLOW_LOCAL_DEV = os.environ.get("NEXA_CORS_ALLOW_LOCAL_DEV", "1" if DEBUG else "0") == "1"

# In development Django also serves frontend/Nexa.html, so the page and the API share one origin (no CORS involved).
SERVE_FRONTEND = os.environ.get("NEXA_SERVE_FRONTEND", "1" if DEBUG else "0") == "1"
FRONTEND_DIR = BASE_DIR.parent / "frontend"

# Base URL the magic link in the sign-in email points to.
FRONTEND_URL = os.environ.get("NEXA_FRONTEND_URL", "http://localhost:8000/Nexa.html")

# Origins whose HTTPS pages may submit forms to Django (the admin) when a tunnel terminates TLS, e.g. https://*.trycloudflare.com.
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("NEXA_CSRF_TRUSTED_ORIGINS", "").split(",") if o]
# When set, /admin/ answers 404 to requests relayed by a tunnel or proxy, so it stays reachable only from this machine.
ADMIN_LOCAL_ONLY = os.environ.get("NEXA_ADMIN_LOCAL_ONLY", "0") == "1"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "api.middleware.AdminLocalOnlyMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "api.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "nexa.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nexa.wsgi.application"

# Production sets NEXA_DATABASE_URL (e.g. postgres://user:password@host:5432/nexa); SQLite is the local default.
if os.environ.get("NEXA_DATABASE_URL"):
    DATABASES = {"default": dj_database_url.config(env="NEXA_DATABASE_URL", conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

redis_url = os.environ.get("NEXA_REDIS_URL", "")
if redis_url:
    redis_endpoint = urlsplit(redis_url)
    if redis_endpoint.scheme not in ("redis", "rediss") or not redis_endpoint.hostname:
        raise RuntimeError("NEXA_REDIS_URL must be a valid redis:// or rediss:// URL.")
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": redis_url,
            "TIMEOUT": 300,
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
        }
    }
else:
    # Shared across server processes; run createcachetable after migrate.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "nexa_cache",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Harare"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_ROOT = Path(os.environ.get("NEXA_MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_STORAGE = os.environ.get("NEXA_MEDIA_STORAGE", "local")
if MEDIA_STORAGE not in ("local", "r2"):
    raise RuntimeError("NEXA_MEDIA_STORAGE must be local or r2.")
if MEDIA_STORAGE == "r2":
    r2_bucket = os.environ.get("NEXA_R2_BUCKET", "")
    r2_endpoint = os.environ.get("NEXA_R2_ENDPOINT", "")
    r2_access_key = os.environ.get("NEXA_R2_ACCESS_KEY_ID", "")
    r2_secret_key = os.environ.get("NEXA_R2_SECRET_ACCESS_KEY", "")
    if not all((r2_bucket, r2_endpoint, r2_access_key, r2_secret_key)):
        raise RuntimeError("R2 storage requires NEXA_R2_BUCKET, NEXA_R2_ENDPOINT and access credentials.")
    endpoint = urlsplit(r2_endpoint)
    if (endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password
            or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment):
        raise RuntimeError("NEXA_R2_ENDPOINT must be an HTTPS origin without credentials or a path.")
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": r2_bucket,
                "endpoint_url": r2_endpoint,
                "access_key": r2_access_key,
                "secret_key": r2_secret_key,
                "region_name": "auto",
                "default_acl": None,
                "file_overwrite": False,
            },
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email links may be written to the console only in development.
EMAIL_BACKEND = os.environ.get(
    "NEXA_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("NEXA_EMAIL_HOST", "")
EMAIL_USE_SSL = os.environ.get("NEXA_EMAIL_USE_SSL", "0") == "1"
EMAIL_PORT = int(os.environ.get("NEXA_EMAIL_PORT", "465" if EMAIL_USE_SSL else "587"))
EMAIL_HOST_USER = os.environ.get("NEXA_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("NEXA_EMAIL_PASSWORD", "")
RESEND_API_KEY = os.environ.get("NEXA_RESEND_API_KEY", "")
ANYMAIL_REQUESTS_TIMEOUT = 15
EMAIL_TIMEOUT = 15
EMAIL_USE_TLS = os.environ.get("NEXA_EMAIL_USE_TLS", "0" if DEBUG or EMAIL_USE_SSL else "1") == "1"
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise RuntimeError("NEXA_EMAIL_USE_TLS and NEXA_EMAIL_USE_SSL cannot both be enabled.")
DEFAULT_FROM_EMAIL = os.environ.get("NEXA_FROM_EMAIL", "Nexa <no-reply@nexa.local>")
async_alerts = os.environ.get("NEXA_ASYNC_ALERTS", "0")
if async_alerts not in ("0", "1"):
    raise RuntimeError("NEXA_ASYNC_ALERTS must be 0 or 1.")
NEXA_ASYNC_ALERTS = async_alerts == "1"

MAGIC_LINK_MINUTES = 15
PASSWORD_RESET_MINUTES = int(os.environ.get("NEXA_PASSWORD_RESET_MINUTES", "30"))
if not 5 <= PASSWORD_RESET_MINUTES <= 120:
    raise RuntimeError("NEXA_PASSWORD_RESET_MINUTES must be between 5 and 120.")
API_TOKEN_DAYS = 30

NEXA_AI_API_KEY = os.environ.get("NEXA_AI_API_KEY", "")
NEXA_AI_BASE_URL = os.environ.get("NEXA_AI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
NEXA_AI_MODEL = os.environ.get("NEXA_AI_MODEL", "gemini-3.8-flash")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"api": {"handlers": ["console"], "level": "INFO"}},
}
