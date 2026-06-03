"""
Production settings — PostgreSQL, no debug.
"""
import os

from .base import *  # noqa: F401, F403

DEBUG = False

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

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "bitgigs"),
        "USER": os.environ.get("POSTGRES_USER", "bitgigs"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}
