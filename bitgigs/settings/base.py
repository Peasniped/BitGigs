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
# blanks skipped). Real environment variables always win over .env values.
_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _, _value = _line.partition("=")
        _value = _value.strip().strip("'\"")
        if _value:  # an empty value would mask defaults (e.g. dev SECRET_KEY)
            os.environ.setdefault(_key.strip(), _value)

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
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "bitgigs.urls"

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

WSGI_APPLICATION = "bitgigs.wsgi.application"

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
# The en override in bitgigs/formats sets comma decimals + period thousands,
# so bare {{ number }} output localizes automatically.
FORMAT_MODULE_PATH = "bitgigs.formats"
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
