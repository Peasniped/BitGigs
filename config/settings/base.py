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

# Load BASE_DIR/.env into the environment (KEY=VALUE lines; # comments and
# blanks skipped). Real environment variables always win over .env values —
# that is what lets Docker and systemd override the file without editing it.
#
# The two sets record *which* names came from where, so a setting can report its
# own origin. That matters because the losing case is silent and baffling: a
# `$env:FOO='x'` typed once into a PowerShell session persists for the life of
# that console, so every later run in the same window quietly ignores .env.
_ENV_FILE_KEYS = set()  # supplied by .env
_ENV_FILE_SHADOWED = set()  # present in .env, but a real env var already won

# Names a *previous* run of this loader put into the environment. Django's
# autoreloader re-execs the process, so the child inherits everything the parent
# read out of .env as ordinary environment variables — without this marker the
# child re-reads .env, finds the keys already set, and reports its own parent as
# something that overrode the file.
_MARKER = "BITGIGS_ENV_FILE_KEYS"
_INHERITED = {k for k in os.environ.get(_MARKER, "").split(",") if k}

_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        _key = _key.strip()
        _value = _value.strip().strip("'\"")
        if _value:  # an empty value would mask defaults (e.g. dev SECRET_KEY)
            if _key not in os.environ:
                os.environ[_key] = _value
                _ENV_FILE_KEYS.add(_key)
            elif _key in _INHERITED:
                _ENV_FILE_KEYS.add(_key)  # our own earlier run put it there
            else:
                _ENV_FILE_SHADOWED.add(_key)

# Names only — never values, so nothing secret is written into the environment
# that wasn't already there.
os.environ[_MARKER] = ",".join(sorted(_ENV_FILE_KEYS))


def _config_source(*names):
    """Where a setting's value came from, in the words a log line can print.

    Takes names in precedence order, so a renamed variable can name its own
    fallback. "shadowing .env" is the whole point of the function: it is the one
    outcome someone can stare at for a while without working out.
    """
    for name in names:
        if name in _ENV_FILE_KEYS:
            return "from .env"
        if name in os.environ:
            return (
                "from the environment, shadowing .env"
                if name in _ENV_FILE_SHADOWED
                else "from the environment"
            )
    return "the built-in default"

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-CHANGE-ME-in-production-bitgigs",
)


def postgres_database():
    """DATABASES["default"] entry built from the POSTGRES_* environment.

    Single source for the connection config so production.py and an opted-in
    dev setup (DJANGO_DB=postgres in local.py) can never drift apart.
    Password validation stays with the caller: production refuses to boot
    without one, dev may talk to a throwaway container.
    """
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "bitgigs"),
        "USER": os.environ.get("POSTGRES_USER", "bitgigs"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }

ALLOWED_HOSTS = (
    os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if os.environ.get("DJANGO_ALLOWED_HOSTS")
    else []
)

# Only set this behind a reverse proxy you control: it makes rate limiting read
# the client IP from X-Forwarded-For (set by the proxy) instead of REMOTE_ADDR
# (which would be the proxy itself). Off by default because the header is
# client-supplied and therefore spoofable when no proxy strips it.
TRUST_PROXY_IP = os.environ.get("DJANGO_TRUST_PROXY_IP", "").lower() in ("1", "true", "yes", "on")

# BitGigs' own apps, named once. INSTALLED_APPS takes these verbatim and the
# LOGGING block below derives a logger from each import name, so a new app is
# covered by the log configuration without a second edit.
LOCAL_APPS = [
    "core.apps.CoreConfig",
    "workplaces.apps.WorkplacesConfig",
    "shifts.apps.ShiftsConfig",
    "payroll.apps.PayrollConfig",
    "calendar_view.apps.CalendarViewConfig",
    "calendar_sync.apps.CalendarSyncConfig",
    "data_io.apps.DataIoConfig",
    "analytics.apps.AnalyticsConfig",
    "help.apps.HelpConfig",
    "api.apps.ApiConfig",
    "scheduler.apps.SchedulerConfig",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",  # required by allauth
    # Third-party
    "crispy_forms",
    "crispy_bootstrap5",
    # allauth is always installed (one migration state for every deployment); the
    # OIDC provider below is only registered when the OIDC_* env vars are set,
    # so a stock install has no SSO and needs no identity provider.
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.openid_connect",
    # Local apps
    *LOCAL_APPS,
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves collected static files straight from gunicorn, which is what makes
    # the Docker image self-contained (no nginx sidecar). Inert under runserver
    # in dev (DEBUG static handling wins). Storage backend: see production.py.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Site-wide login gate: every view requires auth unless marked with
    # @login_not_required (the contrib auth views already are).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "core.middleware.OnboardingRequiredMiddleware",
    # Makes the Settings → Features switches mean it: a feature that is off
    # doesn't just lose its nav entry, its URLs stop answering.
    "core.middleware.FeatureEnabledMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "core.context_processors.onboarding_status",
                "core.context_processors.sso_status",
                "core.context_processors.display_settings",
                "help.context_processors.help_status",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "core.validators.EmailSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "core.validators.CharacterClassesPasswordValidator"},
    {"NAME": "core.validators.NoSequencesPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Copenhagen"
USE_I18N = True
USE_TZ = True

# Danish number formatting ("en-DK"): English UI text, Danish decimals.
# The en override in config/formats sets comma decimals + period thousands,
# so bare {{ number }} output localizes automatically.
FORMAT_MODULE_PATH = "config.formats"
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
LOGOUT_REDIRECT_URL = "/accounts/login/"

# Setup key: proves whoever claims a fresh install can read the server console,
# so a stranger can't win the race to the account step. Deleted once an owner
# exists. See core/setup_key.py and `manage.py setup_key`.
SETUP_KEY_PATH = BASE_DIR / "instance" / "setup_key.txt"

# Marker file whose mtime records the last run of the orphaned-workplace-icon
# prune. The prune is opportunistic (at most once every ICON_PRUNE_INTERVAL, on a
# normal request) — no cron needed. See workplaces.services.maybe_prune_orphan_icons.
ICON_PRUNE_MARKER_PATH = BASE_DIR / "instance" / "last_icon_prune"

# Whether the once-a-day *automatic* icon prune runs. The prune treats the active
# database as the sole authority on which icons are in use — true in production
# (one DB, one media dir), but false in dev, where a spare db.sqlite3.bak shares
# the same media/ directory and references icons this DB has never seen. So the
# auto-sweep is on here and turned OFF in local.py; `manage.py prune_workplace_icons`
# stays available everywhere as a deliberate, explicit action.
ICON_PRUNE_AUTO = True

# ─── Logging ─────────────────────────────────────────────────────────────────
# Django configures a handler for its own `django` logger only, so without this
# block a module's logger.info() went nowhere at all and a logger.exception()
# reached stderr through Python's last-resort handler — unformatted, untimestamped
# and impossible to tell apart from a traceback. This is the single place that
# decides where BitGigs' log lines go.
#
# The console is the primary sink on purpose: both supported deployments already
# capture a process's stdout/stderr (`docker compose logs`, journald for the
# systemd units), so writing there needs no volume, no rotation and no file
# permissions. A file is opt-in for setups that want one — see LOG_FILE.

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Level for BitGigs' own loggers and Django's. A typo must not stop the app from
# booting, so an unrecognised value falls back to the default rather than raising
# out of dictConfig (same rule as OIDC_PROVIDER_COLOR).
#
# DJANGO_LOG_LEVEL is the old name for this, still honoured so that upgrading
# doesn't silently drop an existing deployment back to INFO — the quiet kind of
# regression nobody notices until they need the logs.
_LOG_LEVEL_RAW = os.environ.get("LOG_LEVEL") or os.environ.get("DJANGO_LOG_LEVEL") or ""
LOG_LEVEL = _LOG_LEVEL_RAW.upper() or "INFO"
# Reported on the startup line beside the level itself, so "I set it and nothing
# happened" answers itself instead of costing an afternoon.
LOG_LEVEL_SOURCE = _config_source("LOG_LEVEL", "DJANGO_LOG_LEVEL")
if LOG_LEVEL not in _LOG_LEVELS:
    LOG_LEVEL = "INFO"
    if _LOG_LEVEL_RAW:
        LOG_LEVEL_SOURCE = f"{_LOG_LEVEL_RAW!r} is not a level, so the default"

# Optional second sink: an absolute or BASE_DIR-relative path, rotated at ~2 MB
# with five generations kept. Unset (the default) means console only.
# DJANGO_LOG_FILE is the old name, honoured for the same reason as
# DJANGO_LOG_LEVEL: an upgrade must not quietly stop writing someone's log file.
LOG_FILE = os.environ.get("LOG_FILE") or os.environ.get("DJANGO_LOG_FILE") or ""

LOGGING = {
    "version": 1,
    # Loggers already created by an imported module (every logging.getLogger at
    # module scope) must keep working — disabling them is the classic way to
    # silence exactly the app code this config exists to capture.
    "disable_existing_loggers": False,
    # Same layout for both sinks (see core/logformat.py); they differ only in
    # whether the severity is coloured. The console decides that for itself from
    # the stream — a terminal gets colour, a pipe into `docker compose logs` or
    # journald gets none — while the file is never coloured, since escape codes
    # in a log file are just noise every later grep has to strip.
    "formatters": {
        "bitgigs": {"()": "core.logformat.BitGigsFormatter", "color": False},
        "bitgigs_console": {"()": "core.logformat.BitGigsFormatter"},
    },
    "handlers": {
        # Deliberately unfiltered: Django's own `console` handler carries a
        # require_debug_true filter, which is why nothing ever appeared in
        # production. Redefining the name replaces that one.
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "bitgigs_console",
        },
    },
    # Third-party libraries inherit this: warnings and worse, nothing routine.
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        # propagate=False so Django's framework messages don't also reach root's
        # handler and print twice. Dropping mail_admins with it is intended —
        # BitGigs sets no ADMINS, and its mail backend needs a configured
        # connection, so a 500 must never try to mail its own traceback out.
        #
        # This follows LOG_LEVEL like the app loggers do. It used to be
        # pinned at INFO, which made the variable look broken: django.server and
        # django.utils.autoreload are *the* lines a dev sees at startup, so
        # setting the level to WARNING appeared to change nothing at all.
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        # …with one exception. Django logs every SQL query on this logger at
        # DEBUG, which is a different kind of firehose from "more detail about
        # what the app is doing" — it would bury exactly the lines someone set
        # LOG_LEVEL=DEBUG to read. It stays at INFO regardless of the
        # variable; there is deliberately no env var to turn it on (add one if a
        # real need turns up, rather than making DEBUG mean two things).
        "django.db.backends": {"level": "INFO", "propagate": True},
        # One logger per app, so `logging.getLogger(__name__)` in e.g.
        # calendar_sync/invites.py lands under the app's own level.
        **{
            entry.split(".")[0]: {"level": LOG_LEVEL, "propagate": True}
            for entry in LOCAL_APPS
        },
    },
}

if LOG_FILE:
    _log_path = Path(LOG_FILE)
    if not _log_path.is_absolute():
        _log_path = BASE_DIR / _log_path
    try:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # An unwritable log directory is an operator mistake, not a reason to
        # refuse to boot: keep the console sink and carry on.
        LOG_FILE = ""
    else:
        LOGGING["handlers"]["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(_log_path),
            "maxBytes": 2 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            # Don't create the file until something is actually logged.
            "delay": True,
            "formatter": "bitgigs",
        }
        LOGGING["root"]["handlers"].append("file")
        LOGGING["loggers"]["django"]["handlers"].append("file")

# ─── Task scheduler ──────────────────────────────────────────────────────────
# The standalone `manage.py run_scheduler` loop checks the DB schedule table
# (scheduler.ScheduledJob) this often for due jobs. It is a separate process,
# not an in-process thread — see the command's docstring. Jobs are defined in
# scheduler/registry.py; the loop is optional (opportunistic housekeeping still
# works without it), so nothing here forces it to run.
SCHEDULER_TICK_SECONDS = 10

# Run enqueued one-off tasks inline (synchronously) instead of on the loop —
# the "always eager" switch, for tests that assert a queued send's effect. Off
# everywhere real; a test flips it on with @override_settings.
SCHEDULER_TASK_EAGER = False

# How long a one-off task may sit in RUNNING before the watchdog calls it dead
# and marks it failed. A task is flipped to RUNNING *before* it runs, so a crash
# mid-task would otherwise leave the row stuck there for ever — nothing re-claims
# it and the queue's Clear/Retry controls only reach finished rows. Generous on
# purpose: the point is to catch a dead process, not to time out slow SMTP.
SCHEDULER_TASK_TIMEOUT_SECONDS = 600

# ─── Outbound mail (optional, configured in-app) ─────────────────────────────
# BitGigs keeps its SMTP configuration in the database (the EmailSettings
# singleton) so the operator can set it up and *test* it from Settings → Email
# rather than through a redeploy. This backend reads that row; see core/mail.py.
#
# Like SSO, mail is entirely optional: with nothing configured the app sends no
# mail and the features that need it (password reset) stay hidden.
EMAIL_BACKEND = "core.mail_backend.DbConfiguredEmailBackend"

# Deployments that keep secrets out of the database can set this; it wins over
# the stored password and the settings page then shows the field as read-only.
EMAIL_PASSWORD_OVERRIDE = os.environ.get("EMAIL_HOST_PASSWORD", "")

# How long a password-reset link stays valid.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 2  # 2 hours

# ─── Optional SSO (any OpenID Connect provider) ──────────────────────────────
# BitGigs must stay feature-complete standalone: with no OIDC_* env vars it
# behaves exactly as before (native password login, no SSO button, no IdP needed).
# Set all three to light up the SSO button alongside the password form.
#
# The three credential vars are all that is *required*. What the button is called
# and what it looks like is cosmetic and optional — see the OIDC_PROVIDER_* vars
# below and core/sso.py, which turn them into the button every SSO page renders.
#
# Because the app is single-tenant (Workplace/TaxProfile/UserSettings have no user
# FK), SSO must never create a second User — it may only attach to the existing
# owner. core.adapters enforces that; see the adapters for the rules.
SITE_ID = 1

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ACCOUNT_ADAPTER = "core.adapters.NoSignupAccountAdapter"
SOCIALACCOUNT_ADAPTER = "core.adapters.OwnerOnlySocialAccountAdapter"
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_STORE_TOKENS = False

OIDC_SERVER_URL = os.environ.get("OIDC_SERVER_URL", "")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
SSO_ENABLED = bool(OIDC_SERVER_URL and OIDC_CLIENT_ID and OIDC_CLIENT_SECRET)

# Provider-neutral: this is the allauth provider_id, and it lands in the callback
# URL the IdP must have registered — /accounts/oidc/sso/login/callback/. Renaming
# it means re-registering that URI at the provider, so leave it alone.
SSO_PROVIDER_ID = "sso"

# Button branding — all optional. OIDC_PROVIDER_BRAND is a one-word preset for a
# provider whose icon BitGigs bundles ("authentik"); the other three override any
# individual piece of it. With none of them set the button is neutral: "SSO", the
# app's own accent colour and a shield glyph. Resolved by core/sso.py.
OIDC_PROVIDER_BRAND = os.environ.get("OIDC_PROVIDER_BRAND", "")
OIDC_PROVIDER_NAME = os.environ.get("OIDC_PROVIDER_NAME", "")
OIDC_PROVIDER_COLOR = os.environ.get("OIDC_PROVIDER_COLOR", "")
# A static path, e.g. graphics/my_idp.svg — drop the file in assets/static/graphics/.
OIDC_PROVIDER_ICON = os.environ.get("OIDC_PROVIDER_ICON", "")

SOCIALACCOUNT_PROVIDERS = {}
if SSO_ENABLED:
    SOCIALACCOUNT_PROVIDERS["openid_connect"] = {
        "APPS": [
            {
                "provider_id": SSO_PROVIDER_ID,
                # Only surfaced in allauth's own admin; the UI uses core.sso.
                "name": OIDC_PROVIDER_NAME or "SSO",
                "client_id": OIDC_CLIENT_ID,
                "secret": OIDC_CLIENT_SECRET,
                "settings": {"server_url": OIDC_SERVER_URL},
            },
        ],
    }
