"""Keep emitted invites current, wherever a shift is edited.

A synced shift can be changed from the planning modal, the approve flow *and* the
dashboard, so the "stay current" rule is enforced at the model layer rather than
on any one button: a ``post_save`` re-sends a SEQUENCE-bumped REQUEST and a
``post_delete`` sends a CANCEL, for both ``Shift`` and ``PlannedShift``.

Both handlers are cheap no-ops for the overwhelmingly common case — a shift with
no ``invite_uid`` never touches the database here — and ``invites.resync`` /
``invites.cancel`` are best-effort (they swallow-and-log), so a mail failure can
never block the save or delete that triggered it.
"""
from django.db.models.signals import post_delete, post_save


def _on_shift_saved(sender, instance, **kwargs):
    from . import invites

    invites.resync(instance)


def _on_shift_deleted(sender, instance, **kwargs):
    from . import invites

    invites.cancel(instance)


def connect():
    from shifts.models import PlannedShift, Shift

    for model in (Shift, PlannedShift):
        name = model.__name__
        post_save.connect(
            _on_shift_saved, sender=model, dispatch_uid=f"calsync_invite_save_{name}"
        )
        post_delete.connect(
            _on_shift_deleted, sender=model, dispatch_uid=f"calsync_invite_delete_{name}"
        )
