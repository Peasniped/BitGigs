"""ASGI config for BitGigs project."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bitgigs.settings.local")
application = get_asgi_application()
