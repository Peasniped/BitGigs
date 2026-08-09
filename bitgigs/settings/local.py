"""
Local development settings — SQLite by default, debug mode.

Set DJANGO_DB=postgres (env var or .env) to develop against a local
PostgreSQL instead — e.g. the compose service: `docker compose up db`.
Connection details come from the same POSTGRES_* vars production uses.
"""
import os
import sys

from .base import *  # noqa: F401, F403
from .base import postgres_database

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Django's default PBKDF2 hasher runs 1.2M iterations — ~0.8s per password. The
# suite creates a user in most setUp()s, which put ~5 of every 6 seconds of the
# run into hashing throwaway passwords. Only under `manage.py test`, so a dev
# database is still written with the real hasher.
if "test" in sys.argv:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

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
