"""The project's default ``EMAIL_BACKEND``.

Django's ``EMAIL_*`` settings are static, but BitGigs keeps its mail
configuration in the database so it can be edited and tested from the settings
page. This backend closes that gap: it is a stock SMTP backend that reads its
host/port/credentials from ``EmailSettings`` at connect time.

Wiring it as the *default* backend is what lets code that knows nothing about
BitGigs — notably Django's own password-reset views — send mail correctly.
"""
from django.core.mail.backends.smtp import EmailBackend as SMTPEmailBackend

from .mail import MailNotConfigured, stamp_message_id
from .models import EmailLog, EmailSettings, MailConnection


class DbConfiguredEmailBackend(SMTPEmailBackend):
    """SMTP backend configured from a ``MailConnection``, chosen by *role*.

    The role selects which stored connection to send through:
    ``get_connection(role="calendar")`` sends calendar invites from the calendar
    mailbox, while the default (no role) is the *system* connection — which is
    what Django's own password-reset mail lands on, since it goes through the
    default ``EMAIL_BACKEND`` and knows nothing about roles.

    Explicit keyword arguments still win, so ``get_connection(host=…)`` and the
    test-connection code path behave exactly as they would with the stock
    backend.
    """

    def __init__(self, host=None, port=None, username=None, password=None,
                 use_tls=None, use_ssl=None, timeout=None,
                 role=EmailSettings.ROLE_SYSTEM, **kwargs):
        config = EmailSettings.load().connection_for(role)
        if config is None or not config.is_configured:
            raise MailNotConfigured(
                "Email is not configured. Set it up in Settings → Email."
            )
        stored_password = config.password
        if stored_password is None:
            raise MailNotConfigured(
                "The stored mail password could not be decrypted — "
                "DJANGO_SECRET_KEY has changed. Re-enter it in Settings → Email."
            )
        # Kept for the send log so the operator can see which setup sent what.
        self.connection_name = config.name
        super().__init__(
            host=host if host is not None else config.host,
            port=port if port is not None else config.port,
            username=username if username is not None else (config.username or None),
            password=password if password is not None else (stored_password or None),
            use_tls=(use_tls if use_tls is not None
                     else config.security == MailConnection.SECURITY_STARTTLS),
            use_ssl=(use_ssl if use_ssl is not None
                     else config.security == MailConnection.SECURITY_SSL),
            timeout=timeout if timeout is not None else config.timeout,
            **kwargs,
        )

    def send_messages(self, email_messages):
        """Send, then record one EmailLog per message so the operator has a
        trail of what actually left the server.

        This backend is the app-wide ``EMAIL_BACKEND``, so it is the single point
        every real send passes through — including Django's password-reset mail,
        which does not go through ``core.mail.send_mail``. A raised error (relay
        refused, auth lost between connect and send) is logged against every
        message in the batch and then re-raised, unless ``fail_silently`` asked us
        to swallow it.
        """
        messages = list(email_messages or [])
        for message in messages:
            stamp_message_id(message)
        try:
            sent = super().send_messages(messages)
        except Exception as exc:
            for message in messages:
                self._log_message(message, ok=False, error=str(exc))
            if self.fail_silently:
                return 0
            raise
        for message in messages:
            self._log_message(message, ok=True)
        return sent

    def _log_message(self, message, ok, error=""):
        recipients = ", ".join(getattr(message, "to", []) or [])
        EmailLog.record(
            to=recipients,
            subject=getattr(message, "subject", "") or "",
            ok=ok,
            kind=EmailLog.KIND_SENT,
            error=error,
            connection_name=getattr(self, "connection_name", ""),
        )
