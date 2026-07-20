"""
Production settings — PostgreSQL, no debug.
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401, F403

DEBUG = False

# Fail fast on missing secrets instead of silently running with the insecure
# fallback key from base.py or a blank database password.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY.startswith("django-insecure-"):
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set to a real secret in production.")

_postgres_password = os.environ.get("POSTGRES_PASSWORD", "")
if not _postgres_password:
    raise ImproperlyConfigured("POSTGRES_PASSWORD must be set in production.")

# Security hardening.
# HTTPS enforcement is gated behind DJANGO_ENABLE_HTTPS (default: on) so the
# production settings can also be exercised over plain HTTP for local testing
# by setting DJANGO_ENABLE_HTTPS=0.
ENABLE_HTTPS = os.environ.get("DJANGO_ENABLE_HTTPS", "1").lower() in ("1", "true", "yes", "on")

# Always-safe hardening (no HTTPS dependency)
SECURE_CONTENT_TYPE_NOSNIFF = True

if ENABLE_HTTPS:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DATABASES = {"default": postgres_database()}

# Static files are served by WhiteNoise (see MIDDLEWARE in base.py) so the
# container is self-contained behind gunicorn. Compressed variants are built at
# collectstatic time; no manifest storage (yet), so filenames are stable and a
# stale-reference in a template degrades to a plain 404 instead of a 500.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
