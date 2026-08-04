---
title: Sending shifts as invites
slug: calendar-invites
summary: Set invites up per contract, send a month's worth, and keep them current when a shift changes.
parent: calendar-integration
audience: everyone
order: 20
published: true
keywords: [invite, invitation, invites, send invites, all invites sent, test invite, per contract, work address, personal calendar, event title, location, re-send, resend, out of date, stale invite, changed shift, update, cancel, withdraw, sequence]
pages: [calendar_view:planning]
---
Invites ride your **Email** connection, so
[set that up first](/help/email-and-password-reset/) — the Calendar tab warns you
and links across if it isn't ready.

## Turning it on

Under **Settings → Calendar → Invites you send**:

1. Turn on **Enable calendar invites** (the master switch).
2. Keep **Send invites to personal calendar** on to drop every shift in your own
   calendar. It uses your account email unless you set a different address.
3. Set the **default** event titles for on-site and remote shifts (the
   placeholders `{workplace}`, `{date}`, `{start}`, `{end}` are filled in) and a
   default remote location.
4. Press **Send myself a test invite** to prove the path works end to end. The
   test event withdraws itself right away, so it won't linger in your calendar.

## Then, per contract

Creating a contract — or setting up your first workplace during onboarding —
asks **Activate calendar invites for shifts on this contract?** You must pick
Yes or No; you can change it later from the contract page, or from the Calendar
tab's per-contract overview.

Saying yes reveals **Send invites to the work address** (with the address inline)
and an **on-site location**, plus three **override** toggles — on-site title,
remote title, remote location — each revealing an input only when switched on.
Leave an override off and the contract uses your global default.

Only **on-site** and **remote** shifts generate invites. Sick leave, vacation and
paid absence don't.

### Two destinations, two decisions

The work address switch mirrors **Send invites to personal calendar** for a
reason: putting a shift in *your* calendar and putting it in your *employer's*
mailbox are separate choices. Turn the work switch off and this contract's shifts
go only to your own calendar. The address stays stored, so turning it back on
doesn't mean retyping it.

Turn **both** off and the invite has nowhere to go. BitGigs says so from either
end — the contract form warns as you switch the work address off, and Settings →
Calendar warns as you switch the personal copy off, naming every contract that
would be left with no recipient. Such a contract's shifts get no invite control,
and if *no* contract can reach anyone the **Send invites** button doesn't appear
at all.

## Sending a month

Invites aren't sent the moment you plan a shift — you send them deliberately, and
each shift is invited **once**. On the planning calendar press **Send invites**
to mail the planned shifts in the month you're looking at. Shifts that already
have an up-to-date invite are skipped, so pressing it again while you keep
planning never re-sends. When there's nothing left the button reads **All invites
sent**.

Pressing it opens a **summary of exactly what would go out** — each workplace,
how many invites are new versus updates, and every address they'd reach. Nothing
is sent until you confirm.

The button covers each workplace's **payroll period** for the month on screen,
not everything the grid happens to show, so
[greyed-out shifts](/help/shift-states/) from a neighbouring period are skipped —
you'll send them when you open the month they belong to.

An invited shift shows a small **envelope marker** with a blue ring on its chip.

## When a shift changes afterwards

Editing a **planned** shift does not silently re-send its invite — that would
spam the recipient every time you nudge a time. Instead, if your change affects
what the invite says, a **Re-send calendar invite?** dialog appears once the
shift is saved, showing the shift as it now stands and who would be mailed.

Choose **Not now** and nothing is sent, but the shift isn't forgotten: its chip
switches to a **warning-toned envelope** meaning *invite is out of date*, and the
month's **Send invites** button lights up again and will re-send it. A re-send
updates the existing event rather than adding a second one, and its subject reads
**“Update: …”** so it's clear in the inbox which mail is current.

Only changes the recipient can see count — date, times, break, shift type, and
the resulting title or location. Editing a shift's **notes** never asks. Changing
a contract's event title or location marks its future shifts out of date too.

| You do this | What happens |
|---|---|
| **Edit** a planned shift | You're asked whether to re-send; declining marks it out of date. |
| **Approve** a planned shift | The same event carries over — not re-sent, not duplicated. From then on the shift records hours worked, so later edits never ask. |
| **Delete** a shift | A cancellation is sent and the event is withdrawn. |

All of this only concerns **today and future** shifts. A shift whose day has
passed is never invited, re-sent or cancelled — open yesterday's shift and it
says so instead of offering a Send button.

> A send that gets refused is covered in
> [When an invite doesn't send](/help/invite-problems/). BitGigs ignores any
> replies or RSVPs to the invites it sends.
