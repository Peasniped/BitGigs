"""Outbound mail: connection building, sending, and connection diagnostics.

Everything BitGigs sends goes through :func:`send_mail` here, and every SMTP
connection is built from the ``EmailSettings`` singleton rather than Django's
static ``EMAIL_*`` settings — the point of the feature is that the operator can
configure mail from the settings page instead of a redeploy.

Note on the project's "data never leaves the server" rule: SMTP is the second
sanctioned outbound integration after SSO, and it follows the same shape — off
by default, pointed at a relay the operator chooses, and carrying only what the
operator asked BitGigs to send. See CLAUDE.md.
"""
import smtplib
import socket
import ssl
from dataclasses import dataclass, field

from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone

from .models import EmailSettings

# Common providers, offered as one-click fills on the settings page. Host/port
# only — credentials and the from address are always the operator's own.
PRESETS = {
    "gmail": {
        "label": "Gmail / Google Workspace",
        "host": "smtp.gmail.com",
        "port": 587,
        "security": EmailSettings.SECURITY_STARTTLS,
        "note": "Requires 2-step verification plus an App Password — a normal "
                "Google account password will be rejected.",
    },
    "outlook": {
        "label": "Outlook / Microsoft 365",
        "host": "smtp.office365.com",
        "port": 587,
        "security": EmailSettings.SECURITY_STARTTLS,
        "note": "The account must have SMTP AUTH enabled; Microsoft disables it "
                "by default on new tenants.",
    },
    "fastmail": {
        "label": "Fastmail",
        "host": "smtp.fastmail.com",
        "port": 465,
        "security": EmailSettings.SECURITY_SSL,
        "note": "Requires an app password created in Fastmail's settings.",
    },
}


class MailNotConfigured(RuntimeError):
    """Raised when a send is attempted with mail disabled or half-configured."""


def build_connection(config=None, fail_silently=False):
    """A Django email backend wired from the stored configuration."""
    config = config or EmailSettings.load()
    if not config.is_configured:
        raise MailNotConfigured(
            "Email is not configured. Set it up in Settings → Email."
        )
    password = config.password
    if password is None:
        raise MailNotConfigured(
            "The stored mail password could not be decrypted — DJANGO_SECRET_KEY "
            "has changed. Re-enter the password in Settings → Email."
        )
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=config.host,
        port=config.port,
        username=config.username or None,
        password=password or None,
        use_tls=config.security == EmailSettings.SECURITY_STARTTLS,
        use_ssl=config.security == EmailSettings.SECURITY_SSL,
        timeout=config.timeout,
        fail_silently=fail_silently,
    )


def from_address(config=None):
    """The RFC 5322 From header: ``Name <address>`` when a name is set."""
    config = config or EmailSettings.load()
    if config.from_name:
        return f"{config.from_name} <{config.from_email}>"
    return config.from_email


def send_mail(subject, body, to, html_body=None, config=None, connection=None):
    """Send one message. The single send path for the whole app.

    Raises ``MailNotConfigured`` when mail is off — callers are expected to check
    ``EmailSettings.load().is_configured`` first and hide the feature, so reaching
    this with mail off is a bug rather than a user error.
    """
    config = config or EmailSettings.load()
    connection = connection or build_connection(config)
    message = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=from_address(config),
        to=[to] if isinstance(to, str) else list(to),
        connection=connection,
    )
    if html_body:
        message.attach_alternative(html_body, "text/html")
    return message.send()


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostics
#
# The settings page's test button is the reason this configuration lives in the
# database at all, so a bare "it didn't work" would waste the whole feature. The
# run is split into the stages a real SMTP session goes through, each reported
# separately, so the first ✗ localises the fault: a wrong port fails at connect,
# a wrong security mode fails at TLS, a wrong app password fails at auth, and a
# from-address the provider won't relay for fails only at send.
# ─────────────────────────────────────────────────────────────────────────────

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"


@dataclass
class Stage:
    key: str
    label: str
    status: str = SKIPPED
    detail: str = ""
    hint: str = ""

    def as_dict(self):
        return {
            "key": self.key, "label": self.label, "status": self.status,
            "detail": self.detail, "hint": self.hint,
        }


@dataclass
class Diagnosis:
    stages: list = field(default_factory=list)

    @property
    def ok(self):
        return all(s.status != FAILED for s in self.stages)

    def as_dict(self):
        return {"ok": self.ok, "stages": [s.as_dict() for s in self.stages]}


def _server_reply(exc):
    """SMTP errors carry the server's own words, which are usually the most
    useful part of the message (Gmail links its app-password docs there)."""
    raw = getattr(exc, "smtp_error", None)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")
    text = (raw or str(exc)).strip()
    # Collapse the multi-line replies providers like to send.
    return " ".join(text.split())


def diagnose(config=None, send_to=None):
    """Run the staged connection test.

    ``send_to`` opts into a final stage that delivers a real message, which is
    the only way to catch relay and from-address rejections — those happen after
    a perfectly successful login.
    """
    config = config or EmailSettings.load()

    stages = [
        Stage("config", "Configuration"),
        Stage("dns", "Resolve hostname"),
        Stage("connect", f"Connect to port {config.port}"),
        Stage("tls", "Secure the connection"),
        Stage("auth", "Authenticate"),
    ]
    if send_to:
        stages.append(Stage("send", f"Send a test message to {send_to}"))
    result = Diagnosis(stages)
    by_key = {s.key: s for s in stages}

    def fail(key, detail, hint=""):
        by_key[key].status = FAILED
        by_key[key].detail = detail
        by_key[key].hint = hint
        return result

    def passed(key, detail=""):
        by_key[key].status = OK
        by_key[key].detail = detail

    # ── Stage 1: is there enough here to even try? ───────────────────────────
    problems = []
    if not config.host:
        problems.append("no server hostname")
    if not config.from_email:
        problems.append("no from address")
    if config.password_unreadable:
        problems.append("the stored password can't be decrypted")
    if config.username and not (config.password or config.password_from_env):
        problems.append("a username is set but no password")
    if problems:
        hint = ""
        if config.password_unreadable:
            hint = ("DJANGO_SECRET_KEY changed since the password was saved. "
                    "Re-enter the password to fix it.")
        return fail("config", "Missing: " + ", ".join(problems) + ".", hint)
    passed("config", f"{config.host}:{config.port}, {config.get_security_display()}")

    # ── Stage 2: DNS ─────────────────────────────────────────────────────────
    try:
        addresses = socket.getaddrinfo(
            config.host, config.port, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as exc:
        return fail(
            "dns", f"'{config.host}' could not be resolved ({exc.strerror or exc}).",
            "Check the hostname for typos. It should be the mail server's "
            "address (like smtp.gmail.com), not your email domain.",
        )
    resolved = sorted({a[4][0] for a in addresses})
    passed("dns", f"Resolved to {', '.join(resolved[:3])}")

    # ── Stage 3: TCP ─────────────────────────────────────────────────────────
    # Done as a bare socket first so a closed or filtered port is reported as
    # exactly that, instead of surfacing later as a confusing TLS error.
    try:
        with socket.create_connection((config.host, config.port), config.timeout):
            pass
    except ConnectionRefusedError:
        return fail(
            "connect", f"Nothing is accepting connections on port {config.port}.",
            "The port is probably wrong for this security mode — 587 for "
            "STARTTLS, 465 for implicit TLS, 25 for unencrypted.",
        )
    except (socket.timeout, TimeoutError):
        return fail(
            "connect", f"Timed out after {config.timeout}s.",
            "Something is silently dropping the connection — usually a firewall, "
            "or an ISP blocking outbound mail ports.",
        )
    except OSError as exc:
        return fail("connect", f"Could not connect: {exc}.")
    passed("connect", "Port is open")

    # ── Stages 4 & 5: TLS and AUTH share one live session ────────────────────
    server = None
    try:
        try:
            if config.security == EmailSettings.SECURITY_SSL:
                server = smtplib.SMTP_SSL(
                    config.host, config.port, timeout=config.timeout,
                    context=ssl.create_default_context(),
                )
                server.ehlo()
                passed("tls", "Implicit TLS handshake succeeded")
            else:
                server = smtplib.SMTP(config.host, config.port, timeout=config.timeout)
                server.ehlo()
                if config.security == EmailSettings.SECURITY_STARTTLS:
                    if not server.has_extn("starttls"):
                        return fail(
                            "tls", "The server does not offer STARTTLS.",
                            "Either this port expects implicit TLS (try 465 with "
                            "the SSL mode) or the server has no encryption at all.",
                        )
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                    passed("tls", "STARTTLS handshake succeeded")
                else:
                    by_key["tls"].status = SKIPPED
                    by_key["tls"].detail = "Encryption disabled — mail is sent in the clear."
        except ssl.SSLCertVerificationError as exc:
            return fail(
                "tls", f"The server's certificate could not be verified: {exc.verify_message or exc}.",
                "The certificate may be self-signed, expired, or issued for a "
                "different hostname than the one configured.",
            )
        except ssl.SSLError as exc:
            return fail(
                "tls", f"TLS handshake failed: {exc}.",
                "This usually means the security mode and port disagree — a "
                "plain-SMTP port was addressed as if it spoke TLS immediately.",
            )
        except smtplib.SMTPException as exc:
            return fail("tls", f"The server rejected the handshake: {_server_reply(exc)}.")

        # ── Stage 5: AUTH ────────────────────────────────────────────────────
        if not config.username:
            by_key["auth"].status = SKIPPED
            by_key["auth"].detail = "No username set — connecting anonymously."
        else:
            try:
                server.login(config.username, config.password)
                passed("auth", f"Signed in as {config.username}")
            except smtplib.SMTPAuthenticationError as exc:
                return fail(
                    "auth", f"The server rejected the credentials: {_server_reply(exc)}.",
                    "Check the username (often the full email address). Gmail, "
                    "Outlook and Fastmail all require an app-specific password "
                    "rather than your account password.",
                )
            except smtplib.SMTPNotSupportedError:
                return fail(
                    "auth", "The server does not support authentication.",
                    "Clear the username to connect anonymously, or check whether "
                    "this server expects a different port.",
                )
            except smtplib.SMTPException as exc:
                return fail("auth", f"Sign-in failed: {_server_reply(exc)}.")

        # ── Stage 6: a real message ──────────────────────────────────────────
        if send_to:
            try:
                message = EmailMultiAlternatives(
                    subject="BitGigs test message",
                    body=(
                        "This is a test message from BitGigs.\n\n"
                        "If you are reading this, your mail configuration works.\n"
                    ),
                    from_email=from_address(config),
                    to=[send_to],
                )
                server.send_message(message.message())
                passed("send", "Message accepted by the server")
            except smtplib.SMTPSenderRefused as exc:
                return fail(
                    "send", f"The server refused the from address: {_server_reply(exc)}.",
                    f"Most providers only relay mail from the account you signed "
                    f"in as. Try setting the from address to {config.username}.",
                )
            except smtplib.SMTPRecipientsRefused:
                return fail(
                    "send", f"The server refused the recipient {send_to}.",
                    "Check the address. Some servers also refuse to relay to "
                    "addresses outside their own domain.",
                )
            except smtplib.SMTPException as exc:
                return fail("send", f"The message was not accepted: {_server_reply(exc)}.")
    finally:
        if server is not None:
            try:
                server.quit()
            except (smtplib.SMTPException, OSError):
                pass  # The session is being torn down anyway.

    return result


def run_and_record(config=None, send_to=None):
    """``diagnose`` plus a record of the outcome on the settings row."""
    config = config or EmailSettings.load()
    result = diagnose(config, send_to=send_to)
    config.last_test_at = timezone.now()
    config.last_test_ok = result.ok
    config.save(update_fields=["last_test_at", "last_test_ok", "updated_at"])
    return result
