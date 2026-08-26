#!/bin/sh
# Container entrypoint: apply migrations, then serve. compose.yaml's
# depends_on/healthcheck guarantees the database is accepting connections
# before this runs. The first-run setup key is printed to this log —
# read it with: docker compose logs app
set -e

python manage.py migrate --noinput

exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --access-logfile - \
    --error-logfile -
