"""
Local development settings — SQLite by default, debug mode.

Set DJANGO_DB=postgres (env var or .env) to develop against a local
PostgreSQL instead — e.g. the compose service: `docker compose up db`.
Connection details come from the same POSTGRES_* vars production uses.
"""
import os

from .base import *  # noqa: F401, F403
from .base import postgres_database

DEBUG = True
ALLOWED_HOSTS = ["*"]

if os.environ.get("DJANGO_DB", "").lower() == "postgres":
    DATABASES = {"default": postgres_database()}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "instance" / "db.sqlite3",
        }
    }
