# BitGigs production image: gunicorn + WhiteNoise, no sidecars needed.
# Runs the hardened production settings; pair with a PostgreSQL server
# (e.g. the db service in compose.yaml). See .env.example for configuration.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=bitgigs.settings.production

# Build metadata for Settings → About. .git is excluded from the build context,
# so the app can't read it at runtime — pass these in at build time instead:
#   docker build \
#     --build-arg BITGIGS_GIT_COMMIT=$(git rev-parse --short HEAD) \
#     --build-arg BITGIGS_BUILD_DATE=$(date -u +%Y-%m-%d) -t … .
ARG BITGIGS_GIT_COMMIT=""
ARG BITGIGS_BUILD_DATE=""
ENV BITGIGS_DEPLOYMENT=docker \
    BITGIGS_GIT_COMMIT=$BITGIGS_GIT_COMMIT \
    BITGIGS_BUILD_DATE=$BITGIGS_BUILD_DATE

WORKDIR /app

# Dependencies first so code edits don't bust the pip cache layer.
# gunicorn is container-only (it doesn't run on Windows), hence not in
# requirements.txt.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt "gunicorn>=23,<24"

COPY . .
RUN chmod +x docker-entrypoint.sh

# Static assets ship in the repo, so they are collected at build time. The
# dummy env vars only satisfy production.py's fail-fast import guards —
# collectstatic touches no database and the values never leave this layer.
RUN DJANGO_SECRET_KEY=build-time-collectstatic-only POSTGRES_PASSWORD=unused \
    python manage.py collectstatic --noinput

# Non-root. instance/ is the one writable spot (media uploads, setup key) and
# the volume mount point — see compose.yaml.
RUN useradd --create-home bitgigs \
    && mkdir -p /app/instance/media \
    && chown -R bitgigs:bitgigs /app/instance
USER bitgigs

EXPOSE 8000
ENTRYPOINT ["/app/docker-entrypoint.sh"]
