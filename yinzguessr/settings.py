"""
Django settings for the YinzGuessr local demo.

Single player, no accounts, SQLite. Secrets and the Mapillary token are read
from a `.env` file next to manage.py (see .env.example).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-local-demo-only-change-me",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "game",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "yinzguessr.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "yinzguessr.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "America/New_York"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- YinzGuessr ---------------------------------------------------------------

# Google Maps Platform key with the Maps JavaScript API and the Street View
# Static API enabled. The browser uses it to show Street View and the map; the
# server uses it for free Street View metadata lookups.
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()

# Map ID for the Google maps (needed for their markers). DEMO_MAP_ID is
# Google's ID for testing; create your own in the Cloud console for production.
GOOGLE_MAPS_MAP_ID = os.environ.get("GOOGLE_MAPS_MAP_ID", "DEMO_MAP_ID").strip()

# Django's default is "same-origin", which strips the Referer from cross-site
# requests. Google checks the Referer when an API key is restricted to your
# website, so send our origin (never the full URL) to other sites.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# Rounds in one game.
YG_ROUNDS_PER_GAME = 3

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"game": {"handlers": ["console"], "level": "INFO"}},
}
