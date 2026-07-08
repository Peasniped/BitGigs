"""Custom auth password validators."""
from django.contrib.auth.password_validation import UserAttributeSimilarityValidator
from django.core.exceptions import ValidationError


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
