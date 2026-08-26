"""ASGI config for BitGigs project."""
import os

from django.core.asgi import get_asgi_application

# Fail closed: a server entrypoint that forgets to set the env var must get
# the hardened production settings, never DEBUG. Dev uses manage.py --settings.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
application = get_asgi_application()
