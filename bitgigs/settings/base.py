"""
Base settings shared across all environments.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Feature apps live under apps/ (a plain directory on the path, not a package),
# so they keep their bare import names (core, workplaces, …). Settings load
# before the app registry, so this single insert covers manage.py/wsgi/asgi.
sys.path.insert(0, str(BASE_DIR / "apps"))

# Editable reference-data files (e.g. ATP rates) live here.
DATA_DIR = BASE_DIR / "data"

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-CHANGE-ME-in-production-bitgigs",
)

ALLOWED_HOSTS = (
    os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if os.environ.get("DJANGO_ALLOWED_HOSTS")
    else []
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "crispy_forms",
    "crispy_bootstrap5",
    # Local apps
    "core.apps.CoreConfig",
    "workplaces.apps.WorkplacesConfig",
    "shifts.apps.ShiftsConfig",
    "payroll.apps.PayrollConfig",
    "calendar_view.apps.CalendarViewConfig",
    "data_io.apps.DataIoConfig",
    "analytics.apps.AnalyticsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.SetupRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "bitgigs.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "assets" / "templates"],
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

WSGI_APPLICATION = "bitgigs.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Copenhagen"
USE_I18N = True
USE_TZ = True

# Danish number formatting ("en-DK"): English UI text, Danish decimals.
# The en override in bitgigs/formats sets comma decimals + period thousands,
# so bare {{ number }} output localizes automatically.
FORMAT_MODULE_PATH = "bitgigs.formats"
# Intentionally OFF: Django's thousands grouping is magnitude-based and cannot
# distinguish money from a year or a database id, so enabling it globally would
# render e.g. 2026 -> "2.026" and pk 1500 -> "1.500" and break JS parseInt.
# Grouped money ("1.234,56") comes from the dk filter, which forces grouping.
USE_THOUSAND_SEPARATOR = False

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "assets" / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "instance" / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Crispy Forms
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"
CRISPY_TEMPLATE_PACK = "bootstrap5"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
