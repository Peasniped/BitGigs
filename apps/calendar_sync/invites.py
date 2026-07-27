"""Direction 2 — building and sending calendar invites over SMTP.

Invites reuse the sanctioned SMTP channel (Settings → Email): an ``.ics`` with
``METHOD:REQUEST`` is attached to a mail whose organizer/From is the operator's
own robot mailbox, dressed with the owner's display name. Edits re-send with a
bumped ``SEQUENCE``; a deletion sends ``METHOD:CANCEL`` to the same UID. Every
send goes through the app's default ``EMAIL_BACKEND`` (``DbConfiguredEmailBackend``),
so it is logged to ``EmailLog`` exactly like every other message.

Times are emitted in **UTC** (``…Z``), which is unambiguous and needs no
VTIMEZONE — every calendar client handles it.

Everything here is best-effort: a caller (the activation view, or a shift signal)
must never have a save blocked by a mail failure, so the public entry points
swallow-and-log rather than raise. Heavy logic lives here; views/signals stay thin.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timedelta, timezone as dt_timezone

from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone

from core.models import EmailSettings

from .models import CalendarInviteSettings, ContractCalendarConfig, ShiftInvite
from .services import build_calendar, build_event, own_uid

logger = logging.getLogger(__name__)


# ── identity helpers ─────────────────────────────────────────────────────────

def _owner_user():
    """The single owner account — its display name dresses the organizer."""
    return (
        User.objects.filter(is_superuser=True).order_by("pk").first()
        or User.objects.order_by("pk").first()
    )


def _calendar_connection():
    """The mail connection calendar invites send through (the calendar role)."""
    return EmailSettings.load().connection_for(EmailSettings.ROLE_CALENDAR)


def _calendar_from_email():
    conn = _calendar_connection()
    return conn.from_email if conn else ""


def _organizer():
    """``(display_name, address)`` for ORGANIZER/From, or ``None`` if the calendar
    connection has no from-address. Address stays the SMTP mailbox; the name shows
    who it's from."""
    from_email = _calendar_from_email()
    if not from_email:
        return None
    owner = _owner_user()
    display = (owner.first_name or "").strip() if owner else ""
    name = f"{display} (BitGigs)" if display else "BitGigs"
    return name, from_email


def invite_domain():
    """Domain for the namespaced UID — the calendar From address's domain."""
    from_email = _calendar_from_email()
    return from_email.rpartition("@")[2] or "bitgigs.local"


# ── eligibility + recipients ─────────────────────────────────────────────────

def _is_past(shift) -> bool:
    """True once *shift*'s day has passed — the invite system stops caring about
    it (no first send, no re-send, no cancellation). ``None`` date = treat as
    not-past so an odd row is never silently skipped."""
    day = getattr(shift, "date", None)
    return day is not None and day < timezone.localdate()


def _config(shift):
    """Invite config for the contract active on the shift's date, or ``None``.

    Config is per-contract, and a shift maps to a contract by date, so a shift
    dated outside every contract's span (or at a workplace with no config) yields
    ``None`` → not eligible.
    """
    contract = shift.workplace.active_contract_on(shift.date)
    if contract is None:
        return None
    return getattr(contract, "calendar_config", None)


def eligible(shift) -> bool:
    """Whether *shift* should generate an invite at all.

    Requires the shift to be **today or later** (a finished shift is never
    invited — see ``_is_past``), the global master switch, the contract's own
    ``send_invites``, an invite-able shift type (on-site / remote), and mail.
    """
    if _is_past(shift):
        return False
    if not CalendarInviteSettings.load().enabled:
        return False
    config = _config(shift)
    if config is None or not config.send_invites:
        return False
    if shift.shift_type not in ContractCalendarConfig.INVITEABLE_TYPES:
        return False
    return EmailSettings.load().is_configured_for(EmailSettings.ROLE_CALENDAR)


def recipients_for(shift):
    """Attendees = the contract's resolved work recipient + (when enabled) the
    owner's own address (so each shift also lands in the personal calendar),
    de-duplicated."""
    from .models import parse_addresses

    settings = CalendarInviteSettings.load()
    config = _config(shift)
    recips = list(config.recipient_list(settings)) if config else []
    if settings.send_to_personal:
        personal = settings.personal_address()
        if personal:
            recips.append(personal)
    return parse_addresses("\n".join(recips))


# ── building ─────────────────────────────────────────────────────────────────

def _as_utc(shift_date, shift_time):
    """A naive date+time in the server's local zone → an aware UTC datetime."""
    local = timezone.make_aware(
        datetime.combine(shift_date, shift_time), timezone.get_current_timezone()
    )
    return local.astimezone(dt_timezone.utc)


def build_invite_calendar(shift, invite, *, method, status, recipients=None):
    """Serialise the VCALENDAR for one invite send (REQUEST or CANCEL).

    *recipients* pins the attendee list (used by reconciliation, which withdraws
    from / re-requests a specific subset); when omitted the usual per-method
    resolution applies.
    """
    config = _config(shift)
    settings = CalendarInviteSettings.load()
    shift_type = shift.shift_type

    context = {
        "workplace": shift.workplace.name,
        "date": shift.date.isoformat(),
        "start": shift.start_time.strftime("%H:%M"),
        "end": shift.end_time.strftime("%H:%M"),
    }
    title = config.title_for(shift_type, context, settings) if config else shift.workplace.name
    location = config.location_for(shift_type, settings) if config else shift.workplace.name

    hours = shift.net_hours
    description = f"{title} — {context['start']}–{context['end']} ({hours:.2f}h)"

    event = build_event(
        uid=invite.uid,
        summary=title,
        start=_as_utc(shift.date, shift.start_time),
        end=_as_utc(shift.date, shift.end_time),
        description=description,
        location=location,
        organizer=_organizer(),
        attendees=(
            recipients if recipients is not None
            else _recipients_for_send(shift, invite, method)
        ),
        status=status,
        sequence=invite.sequence,
    )
    return build_calendar(event, method=method)


def _recipients_for_send(shift, invite, method):
    """REQUEST goes to the live recipients; CANCEL reuses whoever the last
    REQUEST was addressed to (they still hold the event to withdraw)."""
    if method == "CANCEL":
        from .models import parse_addresses

        return parse_addresses(invite.last_recipients)
    return recipients_for(shift)


# ── sending ──────────────────────────────────────────────────────────────────

def _send_mail_now(subject, body, recipients, ics_bytes, method):
    """Attach the ``.ics`` and send through the default (logging) backend — the
    actual synchronous SMTP send.

    The ``text/calendar; method=…`` alternative is what makes Gmail/Fastmail
    auto-file the event; the file attachment covers clients that want a download.
    Runs **in the scheduler process** for real invites (see ``_send_mail``); the
    self-contained test invite calls it inline so it can report a live result.
    """
    organizer = _organizer()
    from_email = f"{organizer[0]} <{organizer[1]}>" if organizer else None
    # Route through the calendar role so invites go from the calendar mailbox
    # (and are logged against it), independent of the system/no-reply setup.
    connection = get_connection(role=EmailSettings.ROLE_CALENDAR)
    message = EmailMultiAlternatives(
        subject=subject, body=body, from_email=from_email, to=recipients,
        connection=connection,
    )
    ics_text = ics_bytes.decode("utf-8")
    message.attach_alternative(ics_text, f'text/calendar; method={method}; charset=UTF-8')
    message.attach("invite.ics", ics_bytes, f"text/calendar; method={method}")
    message.send()  # default EMAIL_BACKEND = DbConfiguredEmailBackend → EmailLog


def _send_mail(subject, body, recipients, ics_bytes, method):
    """Hand the invite send to the scheduler queue instead of blocking on SMTP.

    Every real invite path (activate / resync / cancel / reconcile / the
    delete-signal CANCEL) funnels through here, so this one line makes them all
    async: the caller's ``ShiftInvite`` bookkeeping stays synchronous, only the
    SMTP round-trip is deferred. **No auto-retry** (``max_attempts=1``): a retry
    would re-send the email — the calendar client dedupes the event, but the
    inbox shows a duplicate — so a failed send fails *visibly* on the Jobs queue
    (re-sendable from the shift) rather than silently duplicating.
    """
    import base64

    from scheduler.tasks import enqueue

    from .tasks import SEND_INVITE_MAIL

    enqueue(
        SEND_INVITE_MAIL,
        {
            "subject": subject,
            "body": body,
            "recipients": list(recipients),
            "ics_b64": base64.b64encode(ics_bytes).decode("ascii"),
            "method": method,
        },
        max_attempts=1,
    )


def _dispatch(shift, invite, *, method, status, recipients=None, remember=True):
    """Build + send one invite message and stamp the invite row.

    *recipients* overrides the computed address list (reconciliation targets a
    specific subset — the dropped addresses to CANCEL, or the current set to
    re-REQUEST). *remember* controls whether a REQUEST rewrites
    ``last_recipients``; a targeted CANCEL to a removed subset must not, so it
    passes ``remember=False``.
    """
    if recipients is None:
        recipients = _recipients_for_send(shift, invite, method)
    if not recipients:
        return
    ics = build_invite_calendar(
        shift, invite, method=method, status=status, recipients=recipients
    )
    verb = "Cancelled" if method == "CANCEL" else "Invitation"
    subject = f"{verb}: {_subject_title(shift, invite)}"
    body = _plain_body(shift, method)
    _send_mail(subject, body, recipients, ics, method)
    invite.sent_at = timezone.now()
    if remember and method != "CANCEL":
        invite.last_recipients = ", ".join(recipients)
    invite.save()


def _subject_title(shift, invite):
    config = _config(shift)
    context = {
        "workplace": shift.workplace.name,
        "date": shift.date.isoformat(),
        "start": shift.start_time.strftime("%H:%M"),
        "end": shift.end_time.strftime("%H:%M"),
    }
    return config.title_for(shift.shift_type, context) if config else shift.workplace.name


def _plain_body(shift, method):
    when = f"{shift.date:%A %d %B %Y} {shift.start_time:%H:%M}–{shift.end_time:%H:%M}"
    if method == "CANCEL":
        return f"This shift has been cancelled:\n\n{when}\n"
    return (
        f"You're invited to this shift:\n\n{when}\n\n"
        "This event was sent by BitGigs; replies are not monitored.\n"
    )


# ── public entry points (best-effort, never raise) ───────────────────────────

def activate(shift):
    """First activation: ensure a stable ``invite_uid``, create/reactivate the
    ``ShiftInvite`` and send the initial REQUEST. Returns the invite or ``None``
    if the shift isn't eligible / has no recipients / mail failed."""
    if not eligible(shift) or not recipients_for(shift):
        return None
    if not shift.invite_uid:
        shift.invite_uid = uuid.uuid4()
        # Saved before the invite exists, so the post_save signal finds no invite
        # and doesn't double-send — this function sends explicitly below.
        shift.save(update_fields=["invite_uid", "updated_at"])

    invite, _ = ShiftInvite.objects.get_or_create(
        invite_uid=shift.invite_uid,
        defaults={"workplace": shift.workplace},
    )
    if not invite.uid:
        invite.uid = own_uid("shift", shift.invite_uid, invite_domain())
    invite.status = ShiftInvite.STATUS_ACTIVE
    invite.workplace = shift.workplace
    invite.save()

    try:
        _dispatch(shift, invite, method="REQUEST", status="CONFIRMED")
    except Exception:
        logger.exception("calendar invite: activation send failed for %s", invite.uid)
    return invite


def send_test_invite(to_address):
    """Send a one-off test invite to *to_address* to prove the pipeline end to
    end. Records the outcome on ``CalendarInviteSettings`` and returns
    ``(ok, error_message)``; never raises."""
    if not to_address:
        return False, "No address to send to."
    if not EmailSettings.load().is_configured_for(EmailSettings.ROLE_CALENDAR):
        return False, "Email is not configured — set it up on the Email tab."

    settings = CalendarInviteSettings.load()
    day = timezone.localdate() + timedelta(days=1)
    uid = own_uid("test", uuid.uuid4(), invite_domain())

    def _test_ics(*, method, status, sequence):
        event = build_event(
            uid=uid,
            summary="BitGigs test invite",
            start=_as_utc(day, time(12, 0)),
            end=_as_utc(day, time(13, 0)),
            description="If this lands in your calendar, calendar invites are working.",
            organizer=_organizer(),
            attendees=[to_address],
            status=status,
            sequence=sequence,
        )
        return build_calendar(event, method=method)

    # The test invite already runs inside its own scheduler task, so it sends
    # *synchronously* (``_send_mail_now``, not the enqueuing ``_send_mail``) —
    # that's what lets it report a live pass/fail onto the "Last test" badge and
    # withdraw itself back-to-back over the same connection.
    ok, error = True, ""
    try:
        _send_mail_now(
            "BitGigs test invite",
            "This is a test calendar invite from BitGigs. It withdraws itself "
            "right away, so you don't need to respond. Replies are not monitored.",
            [to_address], _test_ics(method="REQUEST", status="CONFIRMED", sequence=0),
            "REQUEST",
        )
    except Exception as exc:  # noqa: BLE001 — surfaced to the user, not swallowed
        logger.exception("calendar invite: test send failed")
        ok, error = False, str(exc)

    # Immediately withdraw the test event so it doesn't linger as an unanswered
    # invitation — same UID, bumped SEQUENCE, sent back-to-back over the same SMTP
    # connection. Best-effort: a failed withdraw is logged but does not change the
    # reported result, which reflects whether the REQUEST went out.
    if ok:
        try:
            _send_mail_now(
                "Cancelled: BitGigs test invite",
                "This withdraws the BitGigs test invite just sent.",
                [to_address], _test_ics(method="CANCEL", status="CANCELLED", sequence=1),
                "CANCEL",
            )
        except Exception:
            logger.exception("calendar invite: test withdraw failed")

    settings.last_test_at = timezone.now()
    settings.last_test_ok = ok
    settings.save(update_fields=["last_test_at", "last_test_ok", "updated_at"])
    return ok, error


def _active_invite(shift):
    uid = getattr(shift, "invite_uid", None)
    if not uid:
        return None
    return ShiftInvite.objects.filter(
        invite_uid=uid, status=ShiftInvite.STATUS_ACTIVE
    ).first()


def resync(shift):
    """Re-send a SEQUENCE-bumped REQUEST (the explicit "Re-send invite"). No-op
    when the shift has no active invite or its day has passed. Never raises."""
    if _is_past(shift):
        return
    invite = _active_invite(shift)
    if invite is None:
        return
    try:
        invite.sequence += 1
        _dispatch(shift, invite, method="REQUEST", status="CONFIRMED")
    except Exception:
        logger.exception("calendar invite: resync send failed for %s", invite.uid)


def cancel(shift):
    """A synced shift is going away: send METHOD:CANCEL and mark the invite
    cancelled. No-op when there's no active invite. Never raises.

    A **past** shift is left alone — there's no point withdrawing an event for a
    day that already happened (and no point spending the send)."""
    if _is_past(shift):
        return
    invite = _active_invite(shift)
    if invite is None:
        return
    try:
        invite.sequence += 1
        _dispatch(shift, invite, method="CANCEL", status="CANCELLED")
    except Exception:
        logger.exception("calendar invite: cancel send failed for %s", invite.uid)
    finally:
        invite.status = ShiftInvite.STATUS_CANCELLED
        invite.save(update_fields=["status", "sequence", "sent_at", "updated_at"])
