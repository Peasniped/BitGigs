"""Scheduler task handlers for calendar_sync (Direction 2).

Registered on app load (see apps.py ``ready()``). The test-invite send is two
SMTP round-trips (REQUEST + back-to-back CANCEL), so it runs off-request via the
queue instead of blocking the settings page.
"""
from scheduler.tasks import register

TEST_INVITE = "calendar.test_invite"
SEND_INVITE_MAIL = "calendar.send_invite_mail"


@register(TEST_INVITE)
def run_test_invite(payload: dict) -> str:
    from . import invites

    to_address = payload.get("to")
    ok, error = invites.send_test_invite(to_address)
    if not ok:
        # send_test_invite already recorded last_test_ok; raising lets the queue
        # mark this run failed and surface the reason on the task row.
        raise RuntimeError(error or "test invite failed")
    return f"test invite sent to {to_address}"


@register(SEND_INVITE_MAIL)
def run_send_invite_mail(payload: dict) -> str:
    """Perform one deferred invite send (see invites._send_mail). Raising on an
    SMTP failure lets the queue retry — re-sending the same UID+SEQUENCE is an
    idempotent update for calendar clients, so a retry never duplicates."""
    import base64

    from . import invites

    invites._send_mail_now(
        payload["subject"],
        payload["body"],
        payload["recipients"],
        base64.b64decode(payload["ics_b64"]),
        payload["method"],
    )
    return f"{payload['method']} to {len(payload['recipients'])} recipient(s)"
