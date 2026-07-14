"""Custom auth password validators."""
from django.contrib.auth.password_validation import UserAttributeSimilarityValidator
from django.core.exceptions import ValidationError


def _join(parts):
    """"a", "a and b", "a, b and c"."""
    if len(parts) == 1:
        return parts[0]
    return "%s and %s" % (", ".join(parts[:-1]), parts[-1])


class EmailSimilarityValidator(UserAttributeSimilarityValidator):
    """UserAttributeSimilarityValidator reworded for our single email-as-username
    account: the only personal attribute we hold is the email address, so the
    generic "your other personal information" wording is replaced accordingly."""

    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError as error:
            raise ValidationError(
                "Your password can’t be too similar to your email address.",
                code=getattr(error, "code", "password_too_similar"),
            )

    def get_help_text(self):
        return "Your password can’t be too similar to your email address."


class CharacterClassesPasswordValidator:
    """Require one lowercase letter, one uppercase letter, one number and one
    symbol (any non-alphanumeric, non-whitespace char). Mirrored client-side by
    the onboarding checklist (`onboarding_password.js`)."""

    def validate(self, password, user=None):
        missing = []
        if not any(c.islower() for c in password):
            missing.append("one lowercase letter")
        if not any(c.isupper() for c in password):
            missing.append("one uppercase letter")
        if not any(c.isdigit() for c in password):
            missing.append("one number")
        if not any((not c.isalnum()) and (not c.isspace()) for c in password):
            missing.append("one symbol")
        if missing:
            raise ValidationError(
                "Your password must contain at least %(missing)s.",
                code="password_missing_character_classes",
                params={"missing": _join(missing)},
            )

    def get_help_text(self):
        return (
            "Your password must contain at least one lowercase letter, one "
            "uppercase letter, one number and one symbol."
        )


class NoSequencesPasswordValidator:
    """Reject weak runs: 3+ of the same character in a row (aaa, 111) or a 3+
    long ascending/descending alphanumeric sequence (abc, 321), compared
    case-insensitively."""

    def validate(self, password, user=None):
        lowered = password.lower()
        for i in range(len(lowered) - 2):
            a, b, c = lowered[i], lowered[i + 1], lowered[i + 2]
            if a == b == c:
                raise ValidationError(
                    "Your password can’t contain a character repeated three times "
                    "in a row (e.g. “aaa” or “111”).",
                    code="password_repeated_run",
                )
            if a.isalnum() and b.isalnum() and c.isalnum():
                step_ab = ord(b) - ord(a)
                step_bc = ord(c) - ord(b)
                if step_ab == step_bc and step_ab in (1, -1):
                    raise ValidationError(
                        "Your password can’t contain a sequential run "
                        "(e.g. “abc”, “123” or “321”).",
                        code="password_sequential_run",
                    )

    def get_help_text(self):
        return (
            "Your password can’t contain a character repeated three times in a "
            "row or a sequential run like “abc” or “123”."
        )
