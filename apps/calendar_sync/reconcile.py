"""Direction 2 — reconciliation: keep sent invites addressed to the right mailbox.

Invites are otherwise fire-and-forget (see :mod:`invites`): once a REQUEST is
sent, the only record of *who holds the event* is ``ShiftInvite.last_recipients``.
When a contract's work e-mail or the personal address changes, every already-sent
invite still points at the **old** mailbox — an orphaned event there, nothing at
the new address. This module diffs each active invite's **desired** recipients
(``invites.recipients_for``) against its **sent** ones (``last_recipients``) and,
on an explicit "Sync now", withdraws the dropped addresses (a targeted CANCEL) and
re-requests the current set (a SEQUENCE-bumped REQUEST).

Nothing here fires on its own — the user presses Sync — so computing intent with
eligibility is safe. Everything is best-effort: a per-invite send failure is
swallowed-and-logged so one bad address can't abort a batch, and nothing raises.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.utils import timezone

from core.models import EmailSettings

from . import invites
from .models import (
    CalendarInviteSettings,
    ContractCalendarConfig,
    ShiftInvite,
    parse_addresses,
)

logger = logging.getLogger(__name__)


# ── lookups ──────────────────────────────────────────────────────────────────

def shift_for_invite(invite):
    """The single live shift owning ``invite.invite_uid`` — a ``Shift``, else a
    ``PlannedShift``, else ``None``. Exactly one row owns the uid at a time:
    approval moves it from the PlannedShift to the Shift and clears the former
    (see ``shifts.models.PlannedShift.approve``)."""
    from shifts.models import PlannedShift, Shift

    uid = invite.invite_uid
    if not uid:
        return None
    return (
        Shift.objects.filter(invite_uid=uid).select_related("workplace").first()
        or PlannedShift.objects.filter(invite_uid=uid).select_related("workplace").first()
    )


def desired_recipients(shift):
    """Who *should* hold this shift's invite right now.

    Returns a list of addresses, ``[]`` to mean "withdraw" (nobody should hold
    it), or ``None`` to mean "can't tell / paused — skip", which is never a
    withdrawal trigger. The ``None`` guards keep the drift count from nagging when
    the master arm is off or mail isn't set up (invites can't move anyway).
    """
    if not CalendarInviteSettings.load().enabled:
        return None  # master arm paused → not a withdrawal
    if not EmailSettings.load().is_configured_for(EmailSettings.ROLE_CALENDAR):
        return None  # can't send → don't nag
    contract = shift.workplace.active_contract_on(shift.date)
    config = getattr(contract, "calendar_config", None) if contract else None
    if config is None or not config.send_invites:
        return []  # this contract opted out → withdraw its invites
    if shift.shift_type not in ContractCalendarConfig.INVITEABLE_TYPES:
        return []
    return invites.recipients_for(shift)


# ── drift ────────────────────────────────────────────────────────────────────

@dataclass
class DriftInfo:
    """A stale invite: who it *should* reach vs who it last reached."""

    invite: ShiftInvite
    shift: object          # Shift | PlannedShift | None (orphan)
    desired: list          # [] means "withdraw entirely"
    sent: list
    added: list            # in desired, not yet sent → REQUEST
    removed: list          # sent, no longer desired → CANCEL

    @property
    def withdraw(self):
        return not self.desired


def invite_drift(invite):
    """:class:`DriftInfo` for *invite* if its addressing is stale, else ``None``
    (already in sync, or skipped because sending is paused/unconfigured)."""
    sent = parse_addresses(invite.last_recipients)
    shift = shift_for_invite(invite)
    if shift is None:
        desired = []  # orphaned (shift gone) → withdraw
    else:
        if shift.date < timezone.localdate():
            return None  # past shift — the invite system no longer cares
        desired = desired_recipients(shift)
        if desired is None:
            return None  # paused / can't send → skip
    sent_keys = {a.lower() for a in sent}
    desired_keys = {a.lower() for a in desired}
    added = [a for a in desired if a.lower() not in sent_keys]
    removed = [a for a in sent if a.lower() not in desired_keys]
    if not added and not removed:
        return None
    return DriftInfo(invite, shift, desired, sent, added, removed)


def _active_invites(queryset=None):
    if queryset is None:
        queryset = ShiftInvite.objects.filter(status=ShiftInvite.STATUS_ACTIVE)
    return queryset


def drifted_invites(queryset=None):
    """Yield :class:`DriftInfo` for every drifted active invite in *queryset*
    (default: all active invites)."""
    for invite in _active_invites(queryset):
        drift = invite_drift(invite)
        if drift is not None:
            yield drift


def drift_summary(queryset=None):
    """Cheap ``{"count": n}`` of drifted active invites for the Settings banner —
    no sends. Zero when the master arm is off or mail isn't configured."""
    return {"count": sum(1 for _ in drifted_invites(queryset))}


def drift_details(queryset=None):
    """A human-facing preview of what a sync would do, **grouped** by the change
    itself — one row per (workplace, withdraw-from, send-to) rather than per
    shift, because a recipient change usually hits many shifts identically. Each
    group carries its sorted dates + count, so a 20-shift month reads as one line.
    Powers the review modal. No sends."""
    groups = {}
    order = []
    for drift in drifted_invites(queryset):
        shift = drift.shift
        name = shift.workplace.name if shift else ""
        key = (
            name,
            tuple(a.lower() for a in drift.removed),
            tuple(a.lower() for a in drift.added),
            drift.withdraw,
        )
        if key not in groups:
            groups[key] = {
                "workplace": name,
                "removed": drift.removed,
                "added": drift.added,
                "withdraw": drift.withdraw,
                "dates": [],
                "count": 0,
            }
            order.append(key)
        groups[key]["count"] += 1
        if shift:
            groups[key]["dates"].append(shift.date)
    result = []
    for key in order:
        group = groups[key]
        group["dates"].sort()
        result.append(group)
    return result


def contract_drift_count(contract):
    """How many active invites attributable to *contract* are drifted — the
    post-save nudge on the contract page. Scoped precisely: an invite counts only
    when the contract active on its shift's date is this one (a workplace may have
    several contracts, and one's address change must not implicate another)."""
    qs = ShiftInvite.objects.filter(
        status=ShiftInvite.STATUS_ACTIVE, workplace=contract.workplace
    )
    n = 0
    for drift in drifted_invites(qs):
        shift = drift.shift
        if shift is None:
            continue
        active = shift.workplace.active_contract_on(shift.date)
        if active and active.pk == contract.pk:
            n += 1
    return n


# ── sync (the explicit migration) ────────────────────────────────────────────

def sync_invite(drift):
    """Migrate one invite to its desired recipients. Best-effort; never raises.
    Returns ``"moved"``, ``"withdrawn"``, or ``None`` (send failed)."""
    invite, shift = drift.invite, drift.shift

    # Withdraw entirely — the contract opted out, went ineligible, or the shift
    # is gone. We can only send the CANCEL if we still have a shift to build it
    # from (a deleted shift already had its CANCEL sent by the delete signal).
    if drift.withdraw:
        try:
            if drift.sent and shift is not None:
                invite.sequence += 1
                invites._dispatch(
                    shift, invite, method="CANCEL", status="CANCELLED",
                    recipients=drift.sent, remember=False,
                )
        except Exception:
            logger.exception("calendar reconcile: withdraw failed for %s", invite.uid)
        finally:
            invite.status = ShiftInvite.STATUS_CANCELLED
            invite.save(update_fields=["status", "sequence", "sent_at", "updated_at"])
        return "withdrawn"

    # Migrate — withdraw from the dropped addresses (the event lives on for the
    # rest), then (re-)request the current set with a bumped SEQUENCE. Sending the
    # REQUEST to retained addresses again is a harmless update and is what carries
    # the event to the newly-added ones. ``remember=True`` resets last_recipients.
    try:
        if drift.removed:
            invite.sequence += 1
            invites._dispatch(
                shift, invite, method="CANCEL", status="CANCELLED",
                recipients=drift.removed, remember=False,
            )
        invite.sequence += 1
        invites._dispatch(
            shift, invite, method="REQUEST", status="CONFIRMED",
            recipients=drift.desired, remember=True,
        )
    except Exception:
        logger.exception("calendar reconcile: migrate failed for %s", invite.uid)
        return None
    return "moved"


def sync_all(queryset=None):
    """Reconcile every drifted active invite. Returns
    ``{"moved": m, "withdrawn": w, "failed": f}``."""
    counts = {"moved": 0, "withdrawn": 0, "failed": 0}
    # Materialise first: syncing mutates invite.status, which would disturb a lazy
    # re-evaluation of the active-invite queryset mid-loop.
    for drift in list(drifted_invites(queryset)):
        result = sync_invite(drift)
        if result == "moved":
            counts["moved"] += 1
        elif result == "withdrawn":
            counts["withdrawn"] += 1
        else:
            counts["failed"] += 1
    return counts
