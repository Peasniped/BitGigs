"""API keys for the BitGigs HTTP API.

A key is generated once, shown to the owner once, and only its SHA-256 hash is
stored — there is deliberately no way to read a key back out of the database
(unlike ``EmailSettings.password``, which must be replayed to the SMTP server,
a key only ever needs to be *compared*). The first characters are kept as a
``prefix`` so the owner can tell keys apart in the settings list.
"""
import hashlib
import secrets

from django.db import models
from django.utils import timezone


KEY_PREFIX = "bg_"
PREFIX_DISPLAY_CHARS = 12  # "bg_" + first 9 of the secret — enough to identify

# The wildcard scope: access to every endpoint, including ones added later.
SCOPE_ALL = "*"


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class ApiKey(models.Model):
    name = models.CharField(
        max_length=100,
        help_text="A nickname so you can tell your keys apart.",
    )
    prefix = models.CharField(
        max_length=PREFIX_DISPLAY_CHARS,
        help_text="The key's first characters, for identification only.",
    )
    key_hash = models.CharField(max_length=64, unique=True, editable=False)

    # List of endpoint ids from api.registry, or ["*"] for everything.
    scopes = models.JSONField(default=list)

    expires_at = models.DateField(
        null=True, blank=True,
        help_text="The key stops working after this date. Blank = never expires.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @classmethod
    def issue(cls, name: str, scopes: list[str], expires_at=None) -> tuple["ApiKey", str]:
        """Create a key and return ``(instance, full_key)``. The full key exists
        only in the return value — the caller shows it once and lets it go."""
        raw = KEY_PREFIX + secrets.token_urlsafe(32)
        instance = cls.objects.create(
            name=name,
            prefix=raw[:PREFIX_DISPLAY_CHARS],
            key_hash=hash_key(raw),
            scopes=scopes,
            expires_at=expires_at,
        )
        return instance, raw

    @classmethod
    def find(cls, raw_key: str) -> "ApiKey | None":
        """The key matching ``raw_key`` regardless of state, or None — state
        checks live in ``api.auth`` so 'revoked' and 'expired' can be reported
        as themselves rather than a generic 'invalid'."""
        if not raw_key or not raw_key.startswith(KEY_PREFIX):
            return None
        try:
            return cls.objects.get(key_hash=hash_key(raw_key))
        except cls.DoesNotExist:
            return None

    def stamp_used(self):
        # .update() keeps this write-only — no save() side effects, no races.
        type(self).objects.filter(pk=self.pk).update(last_used_at=timezone.now())

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at < timezone.localdate()

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_active(self) -> bool:
        return not self.is_revoked and not self.is_expired

    @property
    def has_all_scopes(self) -> bool:
        return SCOPE_ALL in self.scopes

    def allows(self, endpoint_id: str) -> bool:
        return self.has_all_scopes or endpoint_id in self.scopes
