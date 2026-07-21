"""Calendar sync models.

Direction 1 (read/overlay) needs one thing persisted: the operator's private
iCal subscription URL(s). Like the SMTP password, that URL is a secret BitGigs
must replay verbatim to a third party, so it is **encrypted at rest** via
``core.crypto`` and only ever read back through the ``url`` property — never off
``url_encrypted`` directly. A leaked database dump is worthless without the
``SECRET_KEY`` that derives the Fernet key.
"""
from django.core.validators import RegexValidator
from django.db import models


class CalendarSubscriptionQuerySet(models.QuerySet):
    def enabled(self):
        return self.filter(enabled=True)


class CalendarSubscription(models.Model):
    """One external calendar the operator pastes an iCal URL for.

    Several are allowed (personal + partner + …); each contributes read-only
    "busy" blocks to the planning overlay, coloured by :attr:`color`. Nothing
    from the external calendar is stored — only the URL, and a short-lived cache
    of the fetched feed (see ``services``).
    """

    label = models.CharField(
        max_length=100,
        help_text="A name for this calendar, e.g. 'Personal' or 'Partner'.",
    )
    # Never read this directly — use the `url` property, which decrypts it.
    url_encrypted = models.CharField(max_length=2048, blank=True)
    enabled = models.BooleanField(
        default=True,
        help_text="While off, this calendar contributes no busy blocks.",
    )
    color = models.CharField(
        max_length=7,
        default="#6c757d",
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour as #RRGGBB.")],
        help_text="The colour of this calendar's busy blocks on the planning grid.",
    )

    # Fetch state — surfaced by the settings Test button.
    last_fetch_at = models.DateTimeField(null=True, blank=True)
    last_fetch_ok = models.BooleanField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CalendarSubscriptionQuerySet.as_manager()

    class Meta:
        ordering = ["label"]

    def __str__(self):
        state = "" if self.enabled else " (disabled)"
        return f"{self.label}{state}"

    # ── URL: encrypted at rest, mirroring EmailSettings.password ──────────────
    @property
    def url(self):
        """The subscription URL, or ``None`` if a stored one can't be decrypted.

        ``None`` means "unreadable" (a rotated SECRET_KEY) — distinct from ""
        ("not set") — so the UI can ask for a re-entry rather than treat it as
        empty. See ``core.crypto.decrypt_secret``.
        """
        from core.crypto import decrypt_secret

        return decrypt_secret(self.url_encrypted)

    @url.setter
    def url(self, value):
        from core.crypto import encrypt_secret

        self.url_encrypted = encrypt_secret(value)

    @property
    def url_unreadable(self):
        """True when a URL is stored but SECRET_KEY can no longer decrypt it."""
        return bool(self.url_encrypted) and self.url is None

    @property
    def is_usable(self):
        """Enabled and holding a readable, non-empty URL."""
        return bool(self.enabled and self.url)
