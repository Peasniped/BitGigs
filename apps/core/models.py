from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils import timezone


class TaxProfile(models.Model):
    """
    Date-versioned personal tax settings.
    The profile with the latest effective_from <= a given date is used.
    """

    monthly_deduction = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Monthly personal tax deduction (personfradrag) in DKK.",
    )
    tax_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Combined municipality + health tax rate (trækprocent).",
    )
    church_tax_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Church tax rate (kirkeskat). Set to 0 if not a member.",
    )
    am_bidrag_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=8.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="AM-bidrag (labour market contribution), typically 8%.",
    )
    effective_from = models.DateField(
        unique=True,
        help_text="This profile applies from this date forward.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"TaxProfile from {self.effective_from} ({self.tax_percent}%)"


class ATPConfiguration(models.Model):
    """
    Date-versioned ATP (Arbejdsmarkedets Tillægspension) settings.
    ATP brackets define employee/employer contributions based on monthly hours.
    """

    effective_from = models.DateField(
        unique=True,
        help_text="This ATP configuration applies from this date forward.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"ATP from {self.effective_from}"


class ATPBracket(models.Model):
    """
    A single ATP contribution bracket.
    hours_min (inclusive), hours_max (inclusive or None for open-ended).
    """

    configuration = models.ForeignKey(
        ATPConfiguration,
        on_delete=models.CASCADE,
        related_name="brackets",
    )
    hours_min = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Minimum monthly hours (inclusive).",
    )
    hours_max = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum monthly hours (inclusive). Leave blank for open-ended.",
    )
    employee_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Employee ATP contribution in DKK.",
    )
    employer_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        help_text="Employer ATP contribution in DKK.",
    )

    class Meta:
        ordering = ["hours_min"]

    def __str__(self):
        upper = f"–{self.hours_max}" if self.hours_max else "+"
        return f"{self.hours_min}{upper} h/mo → emp {self.employee_amount} kr."


class UserSettings(models.Model):
    """Singleton-style global settings for the app."""

    WEEK_START_CHOICES = [
        (0, "Monday"),
        (6, "Sunday"),
    ]

    PROJECTION_METHOD_CHOICES = [
        ("ema", "Exponential moving average (recent months weighted higher)"),
        ("avg", "Simple average"),
    ]

    THEME_CHOICES = [
        ("light", "Light"),
        ("dark", "Dark"),
        ("auto", "Auto (follow system)"),
    ]

    theme = models.CharField(
        max_length=5,
        choices=THEME_CHOICES,
        default="light",
        help_text="Color theme. Auto follows the operating system's setting.",
    )

    accent_color = models.CharField(
        max_length=7,
        default="#0e61de",
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour as #RRGGBB.")],
        help_text="The app's accent colour — buttons, links, tints and "
                  "gradients all follow it.",
    )

    secondary_color = models.CharField(
        max_length=7,
        default="#9fd6fb",
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a colour as #RRGGBB.")],
        help_text="The gradient companion colour — pairs with the accent for "
                  "buttons, tints and gradients.",
    )

    week_start = models.IntegerField(
        choices=WEEK_START_CHOICES,
        default=0,
        help_text="0 = Monday, 6 = Sunday",
    )

    show_shift_type_colors = models.BooleanField(
        default=True,
        help_text="Colour calendar shift chips by type (on-site / remote / sick / …).",
    )

    show_help_button = models.BooleanField(
        default=True,
        help_text="Show the floating help button on every page. F1 and More → Help "
                  "still open help when this is off.",
    )

    mask_money = models.BooleanField(
        default=False,
        help_text="Hide every money amount across the app (dashboard, analytics, "
                  "payslips, …) so you can demo or screenshot without exposing pay. "
                  "Each amount becomes a fixed-length run of dots, so neither the "
                  "value nor the number of digits can be read off. Hours and dates "
                  "stay visible.",
    )

    # Analytics projection
    projection_method = models.CharField(
        max_length=10,
        choices=PROJECTION_METHOD_CHOICES,
        default="ema",
        help_text="How to estimate future hours from your historical shifts.",
    )
    projection_trailing_months = models.PositiveIntegerField(
        default=6,
        help_text="Number of past months used to compute the projection.",
    )
    use_planned_shifts = models.BooleanField(
        default=True,
        help_text="When a future month has planned shifts, use them for its income "
                  "instead of the trailing-average projection.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User Settings"
        verbose_name_plural = "User Settings"

    def __str__(self):
        return f"Settings (week starts {self.get_week_start_display()})"

    def save(self, *args, **kwargs):
        # Enforce singleton: always overwrite pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class EmailSettings(models.Model):
    """Singleton SMTP configuration, edited in Settings → Email.

    Held in the database rather than env vars so the operator can configure and
    *test* mail from inside the app. The password is the one exception to
    "config is plain data": it is stored encrypted (see ``core.crypto``) and only
    ever read back through the ``password`` property.

    ``enabled`` is the master switch — with it off, ``core.mail`` refuses to send
    and every email-dependent feature (today: password reset) hides itself. A
    fresh install has this row absent entirely, which reads as off.
    """

    SECURITY_NONE = "none"
    SECURITY_STARTTLS = "starttls"
    SECURITY_SSL = "ssl"
    SECURITY_CHOICES = [
        (SECURITY_STARTTLS, "STARTTLS (usually port 587)"),
        (SECURITY_SSL, "Implicit TLS / SSL (usually port 465)"),
        (SECURITY_NONE, "None — unencrypted (not recommended)"),
    ]

    enabled = models.BooleanField(
        default=False,
        help_text="Master switch. While this is off BitGigs sends no mail at all "
                  "and features that need it stay hidden.",
    )

    host = models.CharField(max_length=255, blank=True, help_text="e.g. smtp.gmail.com")
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(
        max_length=10, choices=SECURITY_CHOICES, default=SECURITY_STARTTLS,
    )
    username = models.CharField(
        max_length=255, blank=True,
        help_text="Leave blank if the server accepts mail without authenticating.",
    )
    # Never read this directly — use the `password` property, which decrypts and
    # applies the environment override.
    password_encrypted = models.CharField(max_length=512, blank=True)

    from_email = models.EmailField(
        blank=True,
        help_text="The address mail is sent from. Many providers require this to "
                  "match the account you authenticate as.",
    )
    from_name = models.CharField(
        max_length=100, blank=True, default="BitGigs",
        help_text="Display name shown beside the from address.",
    )
    timeout = models.PositiveIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(120)],
        help_text="Seconds to wait for the server before giving up.",
    )

    allow_password_reset = models.BooleanField(
        default=True,
        help_text="Offer 'Forgot your password?' on the login page. Needs a "
                  "working mail setup; turn it off to require console recovery.",
    )

    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Email Settings"
        verbose_name_plural = "Email Settings"

    def __str__(self):
        if not self.enabled:
            return "Email (disabled)"
        return f"Email via {self.host or 'unconfigured'}:{self.port}"

    def save(self, *args, **kwargs):
        # Enforce singleton, matching UserSettings.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    # ── Password: encrypted at rest, overridable from the environment ─────────
    @property
    def password(self):
        """The SMTP password, or ``None`` if a stored one can't be decrypted.

        An ``EMAIL_HOST_PASSWORD`` environment variable wins over the stored
        value, so a deployment that keeps secrets outside the database can, and
        the settings page shows the field as environment-managed.
        """
        from django.conf import settings as django_settings
        override = getattr(django_settings, "EMAIL_PASSWORD_OVERRIDE", "")
        if override:
            return override
        from .crypto import decrypt_secret
        return decrypt_secret(self.password_encrypted)

    @password.setter
    def password(self, value):
        from .crypto import encrypt_secret
        self.password_encrypted = encrypt_secret(value)

    @property
    def password_from_env(self):
        from django.conf import settings as django_settings
        return bool(getattr(django_settings, "EMAIL_PASSWORD_OVERRIDE", ""))

    @property
    def password_unreadable(self):
        """True when a password is stored but SECRET_KEY can no longer decrypt it."""
        return bool(self.password_encrypted) and self.password is None

    @property
    def is_configured(self):
        return bool(self.enabled and self.host and self.from_email)

    def reset_to_fresh(self, *, save=True):
        """Return this singleton to a clean, disabled state — clears the
        credentials, sender and stored test result, and drops the password.
        Shared by the Email tab's Clear button and onboarding Start-over (which
        must undo the mail server the hidden email step wrote as it went)."""
        field = self._meta.get_field
        self.enabled = False
        self.host = ""
        self.port = field("port").default
        self.security = field("security").default
        self.username = ""
        self.password = ""
        self.from_email = ""
        self.from_name = field("from_name").default
        self.timeout = field("timeout").default
        self.last_test_at = None
        self.last_test_ok = None
        if save:
            self.save()


class EmailLogQuerySet(models.QuerySet):
    def failures_unseen(self):
        """Failed sends the operator has not yet dismissed — the dashboard
        banner and the log's Dismiss control both key off this set."""
        return self.filter(ok=False, acknowledged_at__isnull=True)


class EmailLog(models.Model):
    """One row per outgoing send attempt (test or real app mail), recording the
    recipient, subject, outcome and — when it fails — why.

    Every path that puts mail on the wire logs here: real app mail through
    ``DbConfiguredEmailBackend.send_messages`` (this is the only choke point that
    catches Django's own password-reset mail, which never touches
    ``core.mail.send_mail``) and the diagnostic send in ``mail.run_and_record``.
    Only metadata is stored — never the message body. The table is bounded: each
    ``record`` prunes to the most recent ``PRUNE_KEEP`` rows.
    """

    PRUNE_KEEP = 200

    KIND_TEST = "test"
    KIND_SENT = "sent"
    KIND_CHOICES = [
        (KIND_TEST, "Test message"),
        (KIND_SENT, "Sent"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    to = models.CharField(max_length=254, blank=True)
    subject = models.CharField(max_length=255, blank=True)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_SENT)
    ok = models.BooleanField(default=True)
    error = models.TextField(blank=True)
    # Set when the operator dismisses the dashboard failure banner. Only failures
    # are ever unacknowledged; successes are recorded already-seen (see record()).
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    objects = EmailLogQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        state = "ok" if self.ok else "failed"
        return f"{self.get_kind_display()} to {self.to or '—'} ({state})"

    @classmethod
    def record(cls, to, subject, ok, kind=KIND_SENT, error=""):
        """Create a log row and prune the table back to ``PRUNE_KEEP``.

        Successes are stamped acknowledged immediately — the banner is only ever
        about failures, so a success never needs dismissing.
        """
        entry = cls.objects.create(
            to=(to or "")[:254],
            subject=(subject or "")[:255],
            ok=ok,
            kind=kind,
            error=error or "",
            acknowledged_at=timezone.now() if ok else None,
        )
        cls._prune()
        return entry

    @classmethod
    def _prune(cls):
        keep_ids = list(
            cls.objects.order_by("-created_at").values_list("id", flat=True)[: cls.PRUNE_KEEP]
        )
        cls.objects.exclude(id__in=keep_ids).delete()


class OnboardingDraft(models.Model):
    """In-progress onboarding input, held per user until the final Finish writes
    the real rows. Stored in the DB (not just the session) so the data survives
    logging out mid-onboarding or switching browser. Deleted on completion.

    ``data`` is a dict of ``{step_key: raw_post_payload}`` for the tax /
    workplace / contract / terms steps (each payload already passed the step
    form's ``is_valid()``)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="onboarding_draft",
    )
    data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Onboarding draft for {self.user} ({', '.join(self.data) or 'empty'})"
