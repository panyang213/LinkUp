import json
import os
import dj_database_url
from pathlib import Path


SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"

BASE_DIR = Path(__file__).resolve().parent.parent

_env = BASE_DIR / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver").split(",")

CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS",
    "http://192.168.8.36:8000"
).split(",")

INSTALLED_APPS = [
    "daphne", 
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    'django.contrib.messages',
    "django.contrib.staticfiles",
    "channels",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "chat.context.registered",
    ]},
}]

DATABASES = {
    "default": dj_database_url.config(
        default="sqlite:///" + str(BASE_DIR / "db.sqlite3"),
        conn_max_age=600
    )
}

# Anonymous sessions live ONLY in a signed cookie (nothing is written to the database)
# and the cookie disappears when the browser closes.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG   

# In-memory channel layer for local development; Redis when REDIS_URL is set.
if os.environ.get("REDIS_URL"):
    CHANNEL_LAYERS = {"default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [os.environ["REDIS_URL"]]},
    }}
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Manila"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles" 
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MIN_AGE = 18


FIREBASE_CREDENTIALS = os.environ.get("FIREBASE_CREDENTIALS", "")
FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET", "")
FIREBASE_WEB_CONFIG = json.loads(os.environ.get("FIREBASE_WEB_CONFIG") or "null")
SESSION_COOKIE_AGE_REGISTERED = 60 * 60 * 24 * 14

TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DATA_BACKEND = os.environ.get("DATA_BACKEND", "django")

# ---------------- voice / video calls (WebRTC) ----------------
# STUN helps two devices find each other. People behind strict networks (some schools, offices, mobile
# carriers) may also need a TURN relay: set WEBRTC_ICE_SERVERS to a JSON list, e.g.
# [{"urls":"stun:stun.l.google.com:19302"},{"urls":"turn:YOUR-TURN-HOST:3478","username":"...","credential":"..."}]
WEBRTC_ICE_SERVERS = json.loads(os.environ.get("WEBRTC_ICE_SERVERS") or '[{"urls": "stun:stun.l.google.com:19302"}]')