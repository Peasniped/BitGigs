"""Calendar sync models.

Direction 1 (read/overlay) needs one thing persisted: the operator's private
iCal subscription URL(s). Like the SMTP password, that URL is a secret BitGigs
must replay verbatim to a third party, so it is **encrypted at rest** via
``core.crypto`` and only ever read back through the ``url`` property — never off
``url_encrypted`` directly. A leaked database dump is worthless without the
``SECRET_KEY`` that derives the Fernet key.
"""
import uuid

from django.core.validators import RegexValidator
from django.db import models


def parse_addresses(text):
    """Split a free-text recipients field into a clean list of addresses.

    Accepts commas, semicolons and newlines as separators. Order-preserving and
    de-duplicated; no validation beyond emptiness (the form field validates).
    """
    if not text:
        return []
    raw = text.replace(";", "\n").replace(",", "\n").splitlines()
    seen, out = set(), []
    for part in raw:
        addr = part.strip()
        key = addr.lower()
        if addr and key not in seen:
            seen.add(key)
            out.append(addr)
    return out


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


# ─────────────────────────────────────────────────────────────────────────────
# Direction 2 — outgoing invites
# ─────────────────────────────────────────────────────────────────────────────

class CalendarInviteSettings(models.Model):
    """Singleton global config for outgoing calendar invites (Direction 2).

    Invites ride the **existing** SMTP channel (Settings → Email); this row only
    holds the calendar-specific choices. Off unless the operator turns it on, and
    even then a workplace sends nothing until its own ``send_invites`` is set.
    """

    enabled = models.BooleanField(
        default=False,
        help_text="Master switch for sending calendar invites. While off, no "
                  "invites are sent regardless of per-workplace settings.",
    )
    owner_address = models.EmailField(
        blank=True,
        help_text="Your own address, added to every invite so each shift also "
                  "lands in your personal calendar. May differ from your login email.",
    )
    default_remote_address = models.CharField(
        max_length=255, blank=True,
        help_text="Default location for remote shifts when a workplace sets none.",
    )

    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Calendar Invite Settings"
        verbose_name_plural = "Calendar Invite Settings"

    def __str__(self):
        return "Calendar invites (%s)" % ("on" if self.enabled else "off")

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton, matching UserSettings / EmailSettings
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class WorkplaceCalendarConfig(models.Model):
    """Per-workplace invite configuration (Direction 2).

    A workplace with ``send_invites`` on and at least one recipient (or the global
    owner address) emits a calendar invite per on-site/remote shift once activated
    from the planning page. Title and location are templated by shift type.
    """

    TITLE_ONSITE_DEFAULT = "På arbejde hos {workplace}"
    TITLE_REMOTE_DEFAULT = "Arbejder hjemme, {workplace}"

    workplace = models.OneToOneField(
        "workplaces.Workplace",
        on_delete=models.CASCADE,
        related_name="calendar_config",
    )
    send_invites = models.BooleanField(
        default=False,
        help_text="Send calendar invites for this workplace's shifts.",
    )
    recipients = models.TextField(
        blank=True,
        help_text="Work email(s) to invite, one per line or comma-separated.",
    )
    title_onsite = models.CharField(
        max_length=200, default=TITLE_ONSITE_DEFAULT,
        help_text="Event title for on-site shifts. {workplace}, {date}, "
                  "{start}, {end} are substituted.",
    )
    title_remote = models.CharField(
        max_length=200, default=TITLE_REMOTE_DEFAULT,
        help_text="Event title for remote shifts. Same placeholders as on-site.",
    )
    address_onsite = models.CharField(
        max_length=255, blank=True,
        help_text="Location for on-site shifts. Defaults to the workplace name.",
    )
    address_remote = models.CharField(
        max_length=255, blank=True,
        help_text="Location for remote shifts. Falls back to the global default "
                  "remote address.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Invite config for {self.workplace.name}"

    def recipient_list(self):
        return parse_addresses(self.recipients)

    # Only on-site / remote shifts generate invites — inviting colleagues to
    # sick leave or vacation makes no sense.
    INVITEABLE_TYPES = ("on_site", "remote")

    def title_for(self, shift_type, context):
        template = self.title_remote if shift_type == "remote" else self.title_onsite
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError):
            # A malformed placeholder must never break a send.
            return template

    def location_for(self, shift_type, invite_settings=None):
        if shift_type == "remote":
            if self.address_remote:
                return self.address_remote
            return invite_settings.default_remote_address if invite_settings else ""
        return self.address_onsite or self.workplace.name


class ShiftInvite(models.Model):
    """Tracks an invite series sent for one shift, keyed by its stable
    ``invite_uid`` rather than a row PK so it survives PlannedShift → Shift
    approval. Its existence + ``active`` status drives the planning chip style;
    its ``sequence`` is bumped on every re-send (edit) and CANCEL.
    """

    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    # The stable identity shared with the backing shift's invite_uid. The full
    # namespaced iCalendar UID actually sent (bitgigs-shift-<uuid>@<domain>) is
    # stored separately so a CANCEL reuses the exact UID even if mail config changed.
    invite_uid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    uid = models.CharField(max_length=255, blank=True)

    workplace = models.ForeignKey(
        "workplaces.Workplace",
        on_delete=models.CASCADE,
        related_name="calendar_invites",
    )
    sequence = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    last_recipients = models.TextField(blank=True)

    sent_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["invite_uid"])]

    def __str__(self):
        return f"Invite {self.invite_uid} ({self.status}, seq {self.sequence})"

    @property
    def is_active(self):
        return self.status == self.STATUS_ACTIVE
