"""Scheduler task handlers for calendar_sync (Direction 2).

Registered on app load (see apps.py ``ready()``). The test-invite send is two
SMTP round-trips (REQUEST + back-to-back CANCEL), so it runs off-request via the
queue instead of blocking the settings page.
"""
from scheduler.tasks import register

TEST_INVITE = "calendar.test_invite"
SEND_INVITE_MAIL = "calendar.send_invite_mail"


@register(TEST_INVITE, title="Test calendar invite")
def run_test_invite(payload: dict) -> str:
    from core import mail
    from core.models import EmailSettings

    from . import invites

    mail.require_sendable(EmailSettings.ROLE_CALENDAR, payload.get("queued_at"))
    to_address = payload.get("to")
    ok, error = invites.send_test_invite(to_address)
    if not ok:
        # send_test_invite already recorded last_test_ok; raising lets the queue
        # mark this run failed and surface the reason on the task row.
        raise RuntimeError(error or "test invite failed")
    return f"test invite sent to {to_address}"


def clear_invite_failure(payload: dict) -> None:
    """Clearing this failed row dismisses the failure it recorded.

    Called by the scheduler when a failed queue row is cleared — the task row is
    the visible record of the failure, so binning it is also the answer to "yes,
    I've seen this". What that means for the shift depends on whether anything
    was ever delivered; ``clear_send_failure`` decides.
    """
    from . import invites

    uid = payload.get("invite_uid")
    if uid:
        invites.clear_send_failure([uid])


@register(SEND_INVITE_MAIL, title="Send calendar invite", on_clear=clear_invite_failure)
def run_send_invite_mail(payload: dict) -> str:
    """Perform one deferred invite send (see invites._send_mail).

    The outcome is written back onto the ``ShiftInvite``: queued is not sent, and
    a rejected message (a bad address, or the mail host's rate limit) must not
    leave the shift wearing an "invite sent" marker. Re-raising after marking is
    what puts the row on the Jobs queue as Failed, error and all — including the
    circuit breaker's "skipped", which is a failure to send like any other from
    the shift's point of view: nobody got it, and it needs sending again.
    """
    import base64

    from core import mail
    from core.models import EmailSettings

    from . import invites

    try:
        # Shared across every mail task: stop feeding a connection that has just
        # refused a run of messages (see core.mail.require_sendable).
        mail.require_sendable(EmailSettings.ROLE_CALENDAR, payload.get("queued_at"))
        invites._send_mail_now(
            payload["subject"],
            payload["body"],
            payload["recipients"],
            base64.b64decode(payload["ics_b64"]),
            payload["method"],
        )
    except Exception as exc:
        invites.mark_send_failed(payload, exc)
        raise
    invites.mark_send_ok(payload)
    return f"{payload['method']} to {len(payload['recipients'])} recipient(s)"
