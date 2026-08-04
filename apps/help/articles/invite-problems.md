---
title: When an invite doesn't send
slug: invite-problems
summary: Refused sends, retrying, the three-failure stop, failed cancellations and stuck tasks.
parent: calendar-integration
audience: everyone
order: 30
published: true
keywords: [failed invite, invite failed, send failed, rejected, rate limit, retry invite, clear failed, retry task, failed cancel, cancellation failed, withdraw failed, deleted shift invite, stuck, stalled, running, cancel task, scheduler, jobs queue, three refusals]
pages: []
---
Invites don't go out while you wait — they're handed to the background
scheduler, which sends a few seconds later. So a send can be **refused** by your
mail server after the page has moved on: a mistyped address, a full mailbox, a
sending limit on your account.

When that happens the shift doesn't pretend to be invited. Its chip turns **red
with a crossed-out envelope**, and opening the shift shows the mail server's own
explanation — usually the most useful part — with a link to **Settings → Jobs**,
where the failed attempt sits in the task queue with the full error.

## Three ways out

- **Retry now**, in the shift dialog. Nothing was delivered, so retrying can't
  produce a duplicate in anyone's calendar.
- **Retry** on the failed row itself, on Settings → Jobs. The same thing reached
  from the queue — and the only route left when the shift is gone (see below).
- **Clear failed** on Settings → Jobs, which dismisses the failure. A shift whose
  invite never reached anyone goes back to plain *not invited*, so **Send
  invites** will offer it again. If the failure was a *re-send* — the recipients
  still hold the older version — the shift keeps its invite and goes back to
  being marked **out of date**.

Either way the month's **Send invites** button counts failed shifts as still
needing to go out, so it won't claim *All invites sent* while one is unsent.

## BitGigs stops after three refusals in a row

A mail server that rejects one message usually rejects the next thirty — a
sending limit, a wrong password, a server that's down — and hammering it only
makes things worse. So when three messages in a row are refused on the same mail
connection, the rest of the queued batch is dropped rather than attempted. Those
shifts are marked as failed with *“Skipped …”* as the reason.

It gets out of the way as soon as you do something about it: anything you send
**after** those failures — a retry, another press of Send invites, a test message
on the Email tab — is always attempted, and the first success clears the state.
There's nothing to reset by hand.

A failed send never blocks you from saving, approving or deleting a shift.

## When the *cancellation* is what failed

Deleting an invited shift sends a **withdrawal** to whoever holds it. That send
can be refused like any other — and when it is, the shift is still deleted.
Deleting is a decision about *your* records; it never depends on an email getting
through, and the shift will not reappear.

What's left undone is on the other side: your recipient still holds an event for
a shift that no longer exists. Because the shift is gone there's no chip to click
and no **Send invites** sweep that can pick it up, so the failed row on
**Settings → Jobs** is the only trace, and its **Retry** button is the only way to
actually withdraw the event. If you'd rather sort it out in your calendar app or
by telling the person directly, **Clear failed** dismisses it instead — clearing
is *not* retrying, it only says you've seen it.

## When a task gets stuck

A task is marked *Running* the moment the scheduler picks it up. If that process
then stops — a restart, a crash, a reboot — the row is left saying **Running** for
something that isn't.

BitGigs sorts this out itself: once a task has sat there far longer than any real
send would take, the next scheduler to start marks it **failed** with a timeout,
and whatever was waiting on it is put right. The row shows as **Stalled** in the
meantime.

That clean-up needs a scheduler running to do it, though — and "no scheduler" is
exactly what strands a task. So any row still waiting or running carries a
**Cancel** button on Settings → Jobs: it gives up on that task and records it as
failed, which puts Retry and Clear failed back within reach. Cancelling doesn't
stop a send already in flight, so use it for a row that's plainly gone nowhere.

> Refused sends also appear in the **email log** and raise the red banner on your
> dashboard — see [Email problems](/help/email-troubleshooting/).
