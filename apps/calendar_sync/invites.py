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

import hashlib
import logging
import uuid
from dataclasses import dataclass
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


def _is_approved(shift) -> bool:
    """True for an approved ``Shift`` — a record of hours worked, not a plan.

    Approval carries ``invite_uid`` onto the new Shift on purpose (the invitee
    still holds the event, and that uid is what lets a deletion withdraw it), so
    an approved shift keeps a live invite. But what it holds is what *happened*:
    approving with "Arrived early" corrects the start time to reality, which is
    bookkeeping, not a change of plan anyone needs mailing about.
    """
    from shifts.models import Shift

    return isinstance(shift, Shift)


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
    ``send_invites``, an invite-able shift type (on-site / remote), mail, and
    **somewhere to send it**.

    That last one is not a detail: with the contract's work address switched off
    *and* the personal copy off, the shift is armed at nobody. ``activate``
    already refuses it, so anything that treated it as eligible was offering a
    send that could only ever do nothing — which is exactly how the planning
    button came to promise invites and then report none.
    """
    if _is_past(shift):
        return False
    invite_settings = CalendarInviteSettings.load()
    if not invite_settings.enabled:
        return False
    config = _config(shift)
    if config is None or not config.send_invites:
        return False
    if shift.shift_type not in ContractCalendarConfig.INVITEABLE_TYPES:
        return False
    if not EmailSettings.load().is_configured_for(EmailSettings.ROLE_CALENDAR):
        return False
    return bool(recipients_for(shift, settings=invite_settings))


def recipients_for(shift, *, settings=None):
    """Attendees = the contract's resolved work recipient + (when enabled) the
    owner's own address (so each shift also lands in the personal calendar),
    de-duplicated."""
    from .models import parse_addresses

    settings = settings or CalendarInviteSettings.load()
    config = _config(shift)
    recips = list(config.recipient_list(settings)) if config else []
    if settings.send_to_personal:
        personal = settings.personal_address()
        if personal:
            recips.append(personal)
    return parse_addresses("\n".join(recips))


def any_sendable_contract(settings=None) -> bool:
    """True when at least one contract is armed **and** has somewhere to send.

    The whole-app version of the rule in ``eligible``: with every armed contract's
    work address off and the personal copy off, calendar invites are switched on
    at nobody, so the planning page must not offer a Send-invites button whose
    only possible outcome is "nothing to send".
    """
    settings = settings or CalendarInviteSettings.load()
    armed = ContractCalendarConfig.objects.filter(send_invites=True)
    if settings.send_to_personal and settings.personal_address():
        return armed.exists()  # the personal copy alone is a valid destination
    return any(c.resolved_recipient(settings) for c in armed)


# ── building ─────────────────────────────────────────────────────────────────

def _as_utc(shift_date, shift_time):
    """A naive date+time in the server's local zone → an aware UTC datetime."""
    local = timezone.make_aware(
        datetime.combine(shift_date, shift_time), timezone.get_current_timezone()
    )
    return local.astimezone(dt_timezone.utc)


def _event_content(shift, *, settings=None):
    """``(title, location)`` as they will appear in *shift*'s calendar entry.

    Split out of ``build_invite_calendar`` because ``event_fingerprint`` has to
    hash exactly what a send would emit — resolving the title twice in two places
    is how a "no change" fingerprint drifts from the mail that actually goes out.
    """
    config = _config(shift)
    settings = settings if settings is not None else CalendarInviteSettings.load()
    context = {
        "workplace": shift.workplace.name,
        "date": shift.date.isoformat(),
        "start": shift.start_time.strftime("%H:%M"),
        "end": shift.end_time.strftime("%H:%M"),
    }
    if config is None:
        return shift.workplace.name, shift.workplace.name
    return (
        config.title_for(shift.shift_type, context, settings),
        config.location_for(shift.shift_type, settings),
    )


def event_fingerprint(shift, *, settings=None) -> str:
    """A short hash of everything about *shift* that reaches the invitee's
    calendar: the times, the resolved title and location, and the net hours the
    description quotes.

    Stored on the invite at send time (``ShiftInvite.content_key``) so a later
    edit can be judged: a changed start time is stale, an edited ``notes`` — which
    no invite ever carries — is not.
    """
    title, location = _event_content(shift, settings=settings)
    parts = [
        shift.date.isoformat(),
        shift.start_time.strftime("%H:%M"),
        shift.end_time.strftime("%H:%M"),
        str(shift.break_minutes),
        shift.shift_type,
        title,
        location,
    ]
    # \x1f (unit separator) can't occur in any of the parts, so no join is ambiguous.
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:32]


def backfill_content_keys():
    """Stamp the current fingerprint onto active invites that never recorded one.

    Invites sent before ``content_key`` existed carry no fingerprint, and
    ``is_stale`` reads a blank one as "unknown" rather than "changed". That is the
    right default — but on its own it also means an install with a month of live
    invites sees nothing at all until the *next* send, which is not a feature
    arriving, it's a feature that appears broken.

    Recording what each shift looks like **now** asserts "the invite matches
    this", which is true unless the shift was edited between its send and this
    backfill — and it makes every edit from here on prompt. Run once, from the
    migration that adds the field. Returns the number stamped.
    """
    from .reconcile import shift_for_invite

    stamped = 0
    for invite in ShiftInvite.objects.filter(
        status=ShiftInvite.STATUS_ACTIVE, content_key=""
    ):
        shift = shift_for_invite(invite)
        if shift is None:  # orphan — nothing to fingerprint
            continue
        ShiftInvite.objects.filter(pk=invite.pk).update(
            content_key=event_fingerprint(shift)
        )
        stamped += 1
    return stamped


def is_stale(shift, *, invite=None, settings=None) -> bool:
    """True when *shift* has an active invite that no longer matches it.

    Staleness is a **planning** question — "does anyone need telling?" — so it is
    asked only of planned shifts. Past shifts are never stale (the invite system
    stops caring — see ``_is_past``), neither is an approved one (see
    ``_is_approved``: an approval records the hours actually worked, and every
    later edit corrects that record rather than the plan), and neither is an
    invite with no recorded fingerprint: that is "unknown", not "changed", and
    treating it as stale would light up every invite that predates
    ``content_key``.
    """
    if _is_past(shift) or _is_approved(shift):
        return False
    invite = invite if invite is not None else _active_invite(shift)
    if invite is None or not invite.content_key:
        return False
    return invite.content_key != event_fingerprint(shift, settings=settings)


def build_invite_calendar(shift, invite, *, method, status, recipients=None):
    """Serialise the VCALENDAR for one invite send (REQUEST or CANCEL).

    *recipients* pins the attendee list (used by reconciliation, which withdraws
    from / re-requests a specific subset); when omitted the usual per-method
    resolution applies.
    """
    title, location = _event_content(shift)

    start = shift.start_time.strftime("%H:%M")
    end = shift.end_time.strftime("%H:%M")
    hours = shift.net_hours
    description = f"{title} — {start}–{end} ({hours:.2f}h)"

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


def _send_mail(subject, body, recipients, ics_bytes, method, *, invite=None,
               content_key="", prev_content_key=""):
    """Hand the invite send to the scheduler queue instead of blocking on SMTP.

    Every real invite path (activate / resync / cancel / reconcile / the
    delete-signal CANCEL) funnels through here, so this one line makes them all
    async: the caller's ``ShiftInvite`` bookkeeping stays synchronous, only the
    SMTP round-trip is deferred. **No auto-retry** (``max_attempts=1``): a retry
    would re-send the email — the calendar client dedupes the event, but the
    inbox shows a duplicate — so a failed send fails *visibly* on the Jobs queue
    (re-sendable from the shift) rather than silently duplicating.

    The invite's identity rides along in the payload so the *outcome* can be
    written back to it (``mark_send_ok``/``mark_send_failed``): queued is not
    sent, and without that the shift wears an "invite sent" marker for a mail
    that was rejected. ``prev_content_key`` is what the invitee held *before*
    this attempt — restored on failure, so a failed update falls back to "out of
    date" instead of claiming the recipients hold the new times.
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
            "invite_uid": str(invite.invite_uid) if invite else "",
            "content_key": content_key,
            "prev_content_key": prev_content_key,
            # A re-send after a failure is worth telling apart in the queue.
            **({"label_note": "retry"} if invite and invite.send_failed else {}),
        },
        max_attempts=1,
    )


# ── send outcome, written back onto the invite ───────────────────────────────

def _invite_for(payload):
    uid = (payload or {}).get("invite_uid")
    return ShiftInvite.objects.filter(invite_uid=uid).first() if uid else None


def mark_send_ok(payload):
    """SMTP accepted the message this payload describes: the recipients now hold
    it. Called by the queue handler, so it runs in the scheduler process."""
    invite = _invite_for(payload)
    if invite is None:
        return
    ShiftInvite.objects.filter(pk=invite.pk).update(
        delivered_at=timezone.now(), send_failed_at=None, send_error=""
    )


def mark_send_failed(payload, error):
    """The message was rejected — nobody received it.

    Restores the fingerprint the invitee actually still holds, so a failed
    *update* reads as out-of-date rather than in sync. The restore is guarded by
    a compare on the key this attempt carried: if a newer dispatch has since
    stamped its own, that one is the truth and this stale failure must not
    clobber it.
    """
    invite = _invite_for(payload)
    if invite is None:
        return
    fields = {"send_failed_at": timezone.now(), "send_error": str(error)[:2000]}
    attempted = (payload or {}).get("content_key") or ""
    if attempted and invite.content_key == attempted:
        fields["content_key"] = (payload or {}).get("prev_content_key") or ""
    ShiftInvite.objects.filter(pk=invite.pk).update(**fields)


def clear_send_failure(invite_uids):
    """Dismiss failure marks — the "clear the failed tasks" action.

    Two outcomes, because "unsend" isn't one thing. An invite that was **never
    delivered** is one nobody holds: the row is deleted, so the shift is plainly
    un-invited again and the ordinary Send-invites sweep will pick it up. One
    that *was* delivered stays — the recipients hold the older event — and simply
    loses the failure mark; its restored ``content_key`` then surfaces it as the
    familiar out-of-date invite. Returns how many rows were reset.
    """
    if not invite_uids:
        return 0
    rows = ShiftInvite.objects.filter(
        invite_uid__in=list(invite_uids), send_failed_at__isnull=False
    )
    undeliverable = [r.pk for r in rows if r.delivered_at is None and r.is_active]
    reset = rows.count()
    ShiftInvite.objects.filter(pk__in=undeliverable).delete()
    rows.exclude(pk__in=undeliverable).update(send_failed_at=None, send_error="")
    return reset


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
    # A re-send is an *update* to an event the recipient already holds, and their
    # inbox should say so rather than showing a second "Invitation:" for the same
    # shift. SEQUENCE is the same signal the calendar client uses: every re-send
    # (resync, reconciliation) bumps it before dispatching, so >0 means "not the
    # first time they've seen this".
    if method == "CANCEL":
        verb = "Cancelled"
    elif invite.sequence:
        verb = "Update"
    else:
        verb = "Invitation"
    subject = f"{verb}: {_subject_title(shift, invite)}"
    body = _plain_body(shift, method)
    prev_content_key = invite.content_key
    new_content_key = "" if method == "CANCEL" else event_fingerprint(shift)
    invite.sent_at = timezone.now()
    if method != "CANCEL":
        # A REQUEST always carries the shift's current content, so this is the
        # point the "what the invitee holds" fingerprint becomes true again —
        # including reconciliation's re-REQUEST, which passes remember=False for
        # the *recipients* only. Stamped optimistically (the send is queued, not
        # done); mark_send_failed puts prev_content_key back if it's rejected.
        invite.content_key = new_content_key
        if remember:
            invite.last_recipients = ", ".join(recipients)
    # Saved **before** the send is queued. The handler writes the outcome back to
    # this row, and a full save() of our in-memory copy afterwards would overwrite
    # it with pre-send values — instantly under SCHEDULER_TASK_EAGER, and in
    # production whenever the loop claims the task before this request finishes.
    invite.save()
    _send_mail(
        subject, body, recipients, ics, method,
        invite=invite, content_key=new_content_key, prev_content_key=prev_content_key,
    )


def _subject_title(shift, invite):
    return _event_content(shift)[0]


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
    """Re-send a REQUEST (the explicit "Re-send invite", and the retry after a
    failed send). No-op when the shift has no active invite or its day has
    passed. Never raises.

    SEQUENCE is bumped only when something was actually **delivered**: bumping it
    marks the message as an *update* to an event the recipient already holds, so
    doing that after a first send that never left the building would headline a
    retry as "Update:" for an invitation nobody ever received.
    """
    if _is_past(shift):
        return
    invite = _active_invite(shift)
    if invite is None:
        return
    try:
        if invite.ever_delivered:
            invite.sequence += 1
        _dispatch(shift, invite, method="REQUEST", status="CONFIRMED")
    except Exception:
        logger.exception("calendar invite: resync send failed for %s", invite.uid)


def needs_send(shift, *, invite=None, settings=None) -> bool:
    """True when *shift*'s active invite doesn't match reality and should go out
    again — either it was edited since (stale) or its last send failed. What the
    month's "Send invites" sweep and the chips both key on."""
    invite = invite if invite is not None else _active_invite(shift)
    if invite is None:
        return False
    if invite.send_failed:
        return not _is_past(shift)
    return is_stale(shift, invite=invite, settings=settings)


# ── the month sweep ("Send invites") ─────────────────────────────────────────

@dataclass
class SweepGroup:
    """What one workplace contributes to a month's send."""

    workplace: object
    new: list          # planned shifts with no invite yet
    updates: list      # shifts whose invite is out of date or never got through
    recipients: list   # every address this group's invites would reach

    @property
    def total(self) -> int:
        return len(self.new) + len(self.updates)


def month_sweep(year: int, month: int) -> list[SweepGroup]:
    """Exactly what a "Send invites" press for *year*/*month* would do.

    The one source of truth for that answer: the send performs it, the confirm
    modal previews it, and the planning page's button counts it. They used to
    each work it out for themselves, which is how the button came to offer sends
    the server then skipped.

    Scope is per-workplace by **payroll period**, not the padded visible grid: an
    offset job's days after its period start belong to its *next* period and are
    offered when you view that month. Groups contributing nothing are omitted, and
    a shift with no resolvable recipient is not eligible in the first place (see
    ``eligible``), so it is never counted.
    """
    from payroll.services import PayrollPeriodService
    from shifts.models import PlannedShift
    from workplaces.services import workplaces_active_in_period

    from . import services as ical

    month_start, month_end = ical.month_window(year, month, pad_days=0)
    workplaces = workplaces_active_in_period(month_start, month_end).prefetch_related(
        "contracts__calendar_config"
    )
    active_uids = set(
        ShiftInvite.objects.filter(status=ShiftInvite.STATUS_ACTIVE)
        .values_list("invite_uid", flat=True)
    )
    invite_settings = CalendarInviteSettings.load()

    groups: list[SweepGroup] = []
    for wp in workplaces:
        _terms, period_start, period_end = PayrollPeriodService.resolve_period_bounds(
            wp, year, month
        )
        planned = (
            PlannedShift.objects.filter(
                workplace=wp,
                status=PlannedShift.Status.PLANNED,
                date__gte=period_start,
                date__lte=period_end,
            )
            .select_related("workplace")
            .prefetch_related("workplace__contracts__calendar_config")
            .order_by("date", "start_time")
        )
        new, updates = [], []
        for shift in planned:
            if shift.invite_uid and shift.invite_uid in active_uids:
                # Synced — unless the shift has since been edited (what's out
                # there is wrong) or its send was rejected (nobody got one).
                if needs_send(shift, settings=invite_settings):
                    updates.append(shift)
                continue
            if eligible(shift):
                new.append(shift)
        if new or updates:
            addresses = sorted({
                a for s in new + updates
                for a in recipients_for(s, settings=invite_settings)
            })
            groups.append(SweepGroup(wp, new, updates, addresses))
    return groups


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
