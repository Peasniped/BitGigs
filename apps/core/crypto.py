"""Symmetric encryption for secrets BitGigs must store *and* read back.

Only for values the app has to replay verbatim to a third party — today just the
SMTP password (see ``EmailSettings``). Anything that only needs verifying, like
the owner's own password, stays a one-way hash and must never come through here.

The key is derived from ``SECRET_KEY``, so the ciphertext is worthless on its own:
a leaked database dump does not leak the mail password unless the settings file
or environment leaked with it. The flip side is that **rotating SECRET_KEY makes
every stored secret undecryptable** — callers get ``None`` and are expected to ask
the operator to re-enter the value rather than crash.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)

# Bumping this invalidates every stored secret, so treat it as a migration.
_KEY_INFO = b"bitgigs.email.v1"


def _fernet():
    digest = hashlib.sha256(_KEY_INFO + settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value):
    """Encrypt a string for storage. Empty input stays empty (= "not set")."""
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token):
    """Decrypt a stored secret, or ``None`` if it cannot be read.

    ``None`` means "unreadable" — a rotated SECRET_KEY, or a value written before
    encryption existed. Callers must treat it as *unknown*, not as empty, so the
    UI can tell "no password configured" apart from "password needs re-entering".
    """
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError):
        # Never log the token itself. The settings page asks the operator to
        # re-enter the value, but that only helps whoever opens it — this is the
        # line that explains a mail server that quietly stopped authenticating.
        logger.warning(
            "A stored secret could not be decrypted — has DJANGO_SECRET_KEY changed? "
            "Re-enter it in Settings → Email."
        )
        return None
