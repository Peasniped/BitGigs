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

# Default event titles, shared by the global settings (operator-level defaults)
# and each contract's optional override. {workplace}, {date}, {start}, {end}
# are substituted per shift.
TITLE_ONSITE_DEFAULT = "På arbejde hos {workplace}"
TITLE_REMOTE_DEFAULT = "Arbejder hjemme, {workplace}"


class CalendarInviteSettings(models.Model):
    """Singleton global config for outgoing calendar invites (Direction 2).

    Holds the master arm plus the operator-level **defaults** every contract
    inherits unless it overrides them (see :class:`ContractCalendarConfig`).
    Invites ride the **existing** SMTP channel (Settings → Email); off unless the
    operator turns it on, and even then a contract sends nothing until its own
    ``send_invites`` is set.
    """

    enabled = models.BooleanField(
        default=False,
        help_text="Master switch for sending calendar invites. While off, no "
                  "invites are sent regardless of per-contract settings.",
    )
    send_to_personal = models.BooleanField(
        default=True,
        help_text="Also add your own address to every invite, so each shift lands "
                  "in your personal calendar too.",
    )
    owner_address = models.EmailField(
        blank=True,
        help_text="Your own address for that personal-calendar copy. Leave blank "
                  "to use your account email.",
    )

    # ── operator-level defaults every contract inherits unless it overrides ──
    default_title_onsite = models.CharField(
        max_length=200, default=TITLE_ONSITE_DEFAULT,
        help_text="Default event title for on-site shifts. {workplace}, {date}, "
                  "{start}, {end} are substituted.",
    )
    default_title_remote = models.CharField(
        max_length=200, default=TITLE_REMOTE_DEFAULT,
        help_text="Default event title for remote shifts. Same placeholders as "
                  "on-site.",
    )
    default_remote_address = models.CharField(
        max_length=255, blank=True,
        help_text="Default location for remote shifts when a contract sets none.",
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

    def personal_address(self):
        """Address for the personal-calendar copy: the explicit ``owner_address``,
        else the single owner account's email (the account login *is* the email)."""
        if self.owner_address:
            return self.owner_address
        from django.contrib.auth.models import User

        owner = (
            User.objects.filter(is_superuser=True).order_by("pk").first()
            or User.objects.order_by("pk").first()
        )
        if not owner:
            return ""
        return owner.email or owner.username


class ContractCalendarConfig(models.Model):
    """Per-contract invite configuration (Direction 2).

    A contract with ``send_invites`` on emits a calendar invite per on-site /
    remote shift once activated from the planning page. Every field except
    ``address_onsite`` (the item-6 exception) has an operator-level default on
    :class:`CalendarInviteSettings`; an ``override_*`` flag decides whether this
    contract uses its own value or inherits that default — see the ``resolved_*``
    helpers.
    """

    contract = models.OneToOneField(
        "workplaces.WorkplaceContract",
        on_delete=models.CASCADE,
        related_name="calendar_config",
    )
    send_invites = models.BooleanField(
        default=False,
        help_text="Send calendar invites for this contract's shifts.",
    )

    # Recipient (single work address). Its own on/off switch, mirroring the
    # global "send invites to personal calendar" one: inviting the employer's
    # mailbox is a separate decision from wanting the shift in your own calendar,
    # and a contract may legitimately want only the latter.
    send_to_work = models.BooleanField(
        default=True,
        help_text="Invite the work address below. Turn off to send this "
                  "contract's shifts only to your own calendar.",
    )
    recipient = models.EmailField(
        blank=True,
        help_text="Work address to invite for this contract.",
    )

    # Titles — inherit the global defaults unless overridden.
    override_title_onsite = models.BooleanField(default=False)
    title_onsite = models.CharField(max_length=200, blank=True)
    override_title_remote = models.BooleanField(default=False)
    title_remote = models.CharField(max_length=200, blank=True)

    # Remote location — inherits default_remote_address unless overridden.
    override_address_remote = models.BooleanField(default=False)
    address_remote = models.CharField(max_length=255, blank=True)

    # On-site location has no global default — always per contract, falling back
    # to the workplace name.
    address_onsite = models.CharField(
        max_length=255, blank=True,
        help_text="Location for on-site shifts. Defaults to the workplace name.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Only on-site / remote shifts generate invites — inviting colleagues to
    # sick leave or vacation makes no sense.
    INVITEABLE_TYPES = ("on_site", "remote")

    def __str__(self):
        return f"Invite config for {self.contract}"

    @property
    def workplace(self):
        return self.contract.workplace

    # ── inheritance-aware resolution ─────────────────────────────────────────
    def _settings(self, invite_settings=None):
        return invite_settings if invite_settings is not None else CalendarInviteSettings.load()

    def resolved_recipient(self, invite_settings=None):
        # A plain per-contract field (no global default) behind its own on/off
        # switch; the form requires it whenever *both* invites and the work
        # address are on for the contract. Off → no work recipient at all, so the
        # invite goes only wherever else it's addressed (the personal calendar).
        return self.recipient if self.send_to_work else ""

    def resolved_title_onsite(self, invite_settings=None):
        if self.override_title_onsite and self.title_onsite:
            return self.title_onsite
        return self._settings(invite_settings).default_title_onsite or TITLE_ONSITE_DEFAULT

    def resolved_title_remote(self, invite_settings=None):
        if self.override_title_remote and self.title_remote:
            return self.title_remote
        return self._settings(invite_settings).default_title_remote or TITLE_REMOTE_DEFAULT

    def recipient_list(self, invite_settings=None):
        recip = self.resolved_recipient(invite_settings)
        return [recip] if recip else []

    def title_for(self, shift_type, context, invite_settings=None):
        template = (
            self.resolved_title_remote(invite_settings) if shift_type == "remote"
            else self.resolved_title_onsite(invite_settings)
        )
        try:
            return template.format(**context)
        except (KeyError, IndexError, ValueError):
            # A malformed placeholder must never break a send.
            return template

    def location_for(self, shift_type, invite_settings=None):
        settings = self._settings(invite_settings)
        if shift_type == "remote":
            if self.override_address_remote and self.address_remote:
                return self.address_remote
            return settings.default_remote_address
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
    # Fingerprint of the event content the last REQUEST actually carried (see
    # invites.event_fingerprint). Comparing it with the shift's current content is
    # what makes "this invite is out of date" a fact rather than a guess — an edit
    # to a field the recipient never sees (notes) must not raise the flag. Blank on
    # invites sent before this existed: unknown, and deliberately read as *not*
    # stale, so an upgrade doesn't mark every live invite for re-sending.
    content_key = models.CharField(max_length=64, blank=True)

    # When the message was handed to the queue…
    sent_at = models.DateTimeField(null=True, blank=True)
    # …and when SMTP actually accepted one. The gap between the two is the whole
    # point: sends are queued, so "dispatched" is not "delivered", and a rejected
    # send (rate limit, bad address) would otherwise leave the shift wearing an
    # "invite sent" marker for an email nobody ever received. A row that has
    # never been delivered is one nobody holds — safe to drop entirely.
    delivered_at = models.DateTimeField(null=True, blank=True)
    send_failed_at = models.DateTimeField(null=True, blank=True)
    send_error = models.TextField(blank=True)

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

    @property
    def send_failed(self):
        """True while the last send attempt is known to have failed."""
        return self.send_failed_at is not None

    @property
    def ever_delivered(self):
        """True once any send for this series reached the mail server — i.e. the
        recipients hold *something*, so the series can't be treated as unsent."""
        return self.delivered_at is not None
