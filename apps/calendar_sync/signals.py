"""Withdraw an emitted invite when its shift is deleted.

Invites are **sent once and re-sent only on request** (the "Send invite" /
"Re-send invite" controls), so editing a shift deliberately does **not** re-send
— that used to fire a fresh invite on every save and spam the recipient while a
month was being planned. The one automatic reaction that remains is a
``post_delete`` CANCEL: deleting a shift withdraws its event. It's enforced at the
model layer because a shift can be deleted from the planning modal, the approve
flow *and* the dashboard.

The handler is a cheap no-op for the common case — a shift with no ``invite_uid``
never touches the database — and ``invites.cancel`` is best-effort (swallow-and-log,
and it skips past shifts), so a mail failure can never block the delete.
"""
from django.db.models.signals import post_delete


def _on_shift_deleted(sender, instance, **kwargs):
    from . import invites

    invites.cancel(instance)


def connect():
    from shifts.models import PlannedShift, Shift

    for model in (Shift, PlannedShift):
        name = model.__name__
        post_delete.connect(
            _on_shift_deleted, sender=model, dispatch_uid=f"calsync_invite_delete_{name}"
        )
