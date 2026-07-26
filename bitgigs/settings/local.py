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

# A dev checkout often keeps a db.sqlite3.bak with real data pointed at the same
# media/ directory, so icons that DB references would look orphaned to this one.
# Never auto-delete them in dev; run `manage.py prune_workplace_icons` by hand if
# you actually want a sweep.
ICON_PRUNE_AUTO = False

if os.environ.get("DJANGO_DB", "").lower() == "postgres":
    DATABASES = {"default": postgres_database()}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "instance" / "db.sqlite3",
        }
    }
