"""Setup key — proof that whoever claims a fresh install is the operator.

A brand-new BitGigs has no owner, so *whoever reaches the account step first*
would otherwise become the admin. The key closes that race: it is written to the
server console and to instance/setup_key.txt on first run, and the account step
refuses to create the owner without it — by password *or* by SSO. Once the owner
exists the key is deleted and never needed again.

Reprint or rotate it with:  python manage.py setup_key [--regenerate]
"""
import logging
import secrets

from django.conf import settings

logger = logging.getLogger(__name__)

# token_urlsafe is URL-safe base64 over os.urandom, so 32 bytes = 256 bits of
# entropy in a 43-character key. Brute force is not a threat model here.
KEY_BYTES = 32

# Set once the key has been accepted; every later stage of the account step (and
# the SSO bootstrap in core.adapters) refuses to act without it.
SESSION_FLAG = "setup_key_verified"


def key_path():
    from pathlib import Path
    return Path(settings.SETUP_KEY_PATH)


def get_or_create_key():
    """The current key, generating (and announcing) one if there isn't one yet."""
    path = key_path()
    if path.is_file():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing

    key = secrets.token_urlsafe(KEY_BYTES)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key, encoding="utf-8")
    announce(key)
    return key


def regenerate_key():
    path = key_path()
    path.unlink(missing_ok=True)
    return get_or_create_key()


def check_key(candidate):
    """Constant-time comparison against the stored key."""
    if not candidate:
        return False
    return secrets.compare_digest(candidate.strip(), get_or_create_key())


def clear_key():
    """Called once the owner exists — the key has done its job."""
    key_path().unlink(missing_ok=True)


def announce(key):
    logger.warning(
        "\n"
        "  ┌────────────────────────────────────────────────────────────┐\n"
        "  │  BitGigs setup key — needed to create the owner account.   │\n"
        "  └────────────────────────────────────────────────────────────┘\n"
        "      %s\n"
        "  Also saved to: %s\n",
        key, key_path(),
    )
