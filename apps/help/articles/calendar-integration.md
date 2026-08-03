---
title: Calendar integration
slug: calendar-integration
summary: Overlay a personal calendar on the planning grid, and email shifts out as calendar invites.
parent: settings-and-sign-in
audience: everyone
order: 78
published: true
keywords: [calendar, ical, ics, subscription, overlay, busy, invite, invitation, invites, colleagues, sync, sync now, change email, move invites, old address, planning clash, feed, webcal, method request, sequence, cancel, test invite, encrypted url, re-send, resend, out of date, stale invite, changed shift, all invites sent, failed invite, invite failed, send failed, rejected, rate limit, retry invite, clear failed, retry task, failed cancel, cancellation failed, withdraw failed, deleted shift invite, work address off, personal only]
pages: [core:settings, calendar_view:planning]
---
BitGigs talks to calendars in two independent directions, and each is optional
and **off until you set it up** under **[Settings → Calendar](/settings/?tab=calendar)**.

- **Reading in** — overlay a personal calendar's busy times on the planning
  grid, so you never plan a shift on top of something you already have on.
- **Sending out** — email a calendar invite for each shift, so colleagues (and
  your own calendar) stay in sync.

Neither one sends your BitGigs data anywhere except where you explicitly point
it: reading in only *fetches* a URL you paste, and sending out rides the same
mail server you configured on the [Email tab](/settings/?tab=email).

## Reading a calendar into planning

Add a calendar under **Settings → Calendar → Calendars you read**. You need its
private **iCal (`.ics`) URL** — most providers expose one:

- **Google Calendar**: Settings → *your calendar* → **Secret address in iCal
  format**.
- **Fastmail**, **iCloud**, **Outlook** and others have an equivalent "subscribe"
  or "secret" `.ics` link.

Give it a **name** and a **colour**, paste the URL, and save. The URL is a
secret — treat it like a password — so BitGigs fetches it **on the server** (your
browser can't, and it never leaves the server) and stores it **encrypted**. You
can add several calendars (yourself, a partner, …); each gets its own colour.

Press the **↻** button on a row to fetch it right now and see how many events it
found, or the error if something's wrong. The row shows when it was **last
checked** and whether that succeeded.

### Seeing it while planning

On the **[planning calendar](/calendar/planning/)**, a **Show my calendar**
button appears once you've added at least one calendar. Turn it on and your busy
times appear as muted, striped **read-only** chips in the day cells — you can't
drag or edit them, they're just there for context. A legend swatch ("External
calendar event") shows in the help panel while the overlay is on.

Turning the overlay on also **uncollapses a list of sliders** under the button,
one per calendar. Flip a slider to show or hide that calendar's busy blocks — this
is the **same on/off switch as Settings → Calendar**, so the change is permanent
(a hidden calendar stays hidden everywhere until you turn it back on). This is the
handy way to plan against just one calendar without leaving the page.

Because the busy blocks use the same time shape as shifts, the planner's existing
**overlap warning** picks them up: plan a shift over a busy block and both turn
amber. Turning the toggle **on** is the only thing that fetches a fresh copy from
your provider: after that the events are cached for the rest of your browser
session, so reloads (from editing a shift, say) and month navigation reuse them
without re-fetching. Want the latest? Just toggle it **off and on again**.

Your own emitted invites (see below) are filtered out of this overlay, so a shift
you invited yourself to never reads as clashing with itself.

## Sending shifts as invites

This uses your **Email** connection, so set that up first — the Calendar tab
warns you and links across if it isn't ready. Then, under **Invites you send**:

1. Turn on **Enable calendar invites** (the master switch).
2. Keep **Send invites to personal calendar** on to also drop every shift in your
   own calendar. It uses your account email unless you set a different
   **personal calendar address**.
3. Set the operator-level **defaults** every contract inherits — the on-site /
   remote event **titles** (placeholders `{workplace}`, `{date}`, `{start}`,
   `{end}` are filled in) and a **default remote location** for work-from-home
   shifts.
4. Press **Send myself a test invite** to prove the whole path works end to end.
   The test event **withdraws itself right away**, so it won't linger in your
   calendar as an invitation waiting for a response.

Invites are then configured **per contract**, where you set up the job. When you
**create a contract** — or set up your first workplace during onboarding — you're
asked **Activate calendar invites for shifts on this contract?** and must pick
**Yes** or **No** (you can always change it later). Picking **Yes**, or opening an
existing contract to **Edit** it (Workplaces → a workplace → **Edit** a contract,
or the **Edit** button on the Calendar tab's per-contract overview), reveals the
fields: **Send invites to the work address** (on by default, with the address
inline beside it) and an **on-site location**, then three **override** toggles for
the on-site title, remote title and remote location — each shows an input inline
only when you turn it on, otherwise it uses your global default. Only **on-site**
and **remote** shifts generate invites; sick leave, vacation and paid absence
don't.

The work address works exactly like **Send invites to personal calendar** on
Settings → Calendar, and for the same reason: putting a shift in *your* calendar
and putting it in your *employer's* mailbox are two separate decisions. Turn the
work switch off and this contract's shifts go only to your own calendar — useful
for a job whose scheduling doesn't run through e-mail at all. The address stays
stored while the switch is off, so turning it back on doesn't mean retyping it.
Turning **both** off leaves the invite with nowhere to go, and BitGigs says so
from either end: the contract form warns as you switch the work address off, and
Settings → Calendar warns as you switch the personal copy off — there naming every
contract that would be left with no recipient, each linking straight to it. The
per-contract overview on that tab reads *Personal calendar only* while the
personal copy is on, and **No recipient** once it isn't.

Invites won't actually send until your **Email** connection is set up and the
master switch is on, so the form tells you when something's still missing. If you
turn invites **on during onboarding**, the wizard offers an **email-setup step**
right after your workplace — set your mail server up there (with the same live
connection test as Settings → Email), or **skip** it and do it later. Either way
your invite choices are saved.

### Activating and keeping them current

Invites aren't sent automatically the moment you plan a shift — you send them
deliberately, and each shift is invited **once**. On the planning calendar, press
**Send invites** to email invites for the planned shifts in the month you're
looking at; shifts that already have an up-to-date invite are skipped, so
pressing it again while you keep planning never re-sends. An invited shift shows
a small **envelope marker** with a blue ring (see the legend in this help panel).

The button covers each workplace's **payroll period** for the month on screen,
not everything the grid happens to show. With an offset period (say the 20th to
the 19th) the days after the 20th belong to the *next* period — they're greyed on
the grid, and they're offered when you move to that month. When there's nothing
left to send, the button reads **All invites sent**.

Pressing it doesn't send straight away — it opens a **summary of exactly what
would go out**: each workplace, how many invites are brand new versus updates to
one already in someone's calendar, and every address they'd reach. Nothing is
sent until you confirm, so you can back out if a recipient looks wrong.

### When a shift changes after its invite went out

Editing a **planned** shift does **not** silently re-send its invite — that would
spam the recipient every time you nudge a time. Instead, if your change affects
what the invite says, a **Re-send calendar invite?** dialog appears once the shift
is saved, showing the shift as it now stands and who would be mailed.

Choose **Not now** and nothing is sent, but the shift isn't forgotten: its chip
switches to a **warning-toned envelope** meaning *invite is out of date*, the edit
dialog says so, and the month's **Send invites** button lights up again and will
re-send it. A re-send updates the event in the recipient's calendar (same event,
new details) rather than adding a second one, and its subject reads
**“Update: …”** instead of “Invitation: …” so it's clear in the inbox which mail
is the current one.

Only changes the recipient can actually see count — the date, the times, the
break, the shift type, and the resulting title or location. Editing a shift's
**notes** changes nothing in the invite, so it never asks. Changing a contract's
**event title** or **location** does affect every future invite on it, so those
shifts are marked out of date too.

So:

- **Edit** a shift → you're asked whether to re-send; declining leaves it marked
  out of date until you re-send it, from the dialog or the Send invites button.
- **Approve** a planned shift → the same event carries over to the approved
  shift; it's not re-sent or duplicated. From there the shift is a record of the
  hours you worked rather than a plan, so editing it — correcting the start time
  because you arrived early, say — never asks about the invite.
- **Delete** a shift → a cancellation is sent and the event is withdrawn.

The whole system only cares about **today and future** shifts. A shift whose day
has passed is left alone — it's never invited, re-sent, or cancelled (deleting an
old shift sends nothing). Open yesterday's shift and it says so instead of
offering a Send button; there's nobody to invite to a shift that already
happened.

An invite also needs **somewhere to go**. If a contract has its work address
switched off *and* **Send invites to personal calendar** is off, that contract is
armed at nobody — those shifts get no invite control, and if no contract can
reach anyone the month's **Send invites** button doesn't appear at all. Turning
either destination on brings it straight back.

### When a send fails

Invites don't go out while you wait — they're handed to the background scheduler,
which does the actual sending a few seconds later. So a send can still be
*refused* by your mail server after the page has moved on: a mistyped address, a
mailbox that's full, or a sending limit on your mail account.

When that happens the shift doesn't pretend to be invited. Its chip turns
**red with a crossed-out envelope**, and opening the shift shows the mail
server's own explanation — usually the most useful part — with a link to
**Settings → Jobs**, where the failed attempt sits in the task queue with the
full error.

You have three ways out:

- **Retry now**, in the shift dialog. Nothing was delivered, so retrying can't
  produce a duplicate in anyone's calendar. The retry appears in the queue as
  *Send calendar invite (retry)*.
- **Retry** on the failed row itself, on Settings → Jobs. Same thing, reached from
  the queue instead of the shift — and the only route available when the shift is
  gone (see below).
- **Clear failed** on Settings → Jobs, which dismisses the failure. A shift whose
  invite never reached anyone goes back to plain **not invited**, so the month's
  **Send invites** button will offer it again. If the failure was a *re-send* —
  the recipients still hold the older version of the event — the shift keeps its
  invite and simply goes back to being marked **out of date**.

Either way the month's **Send invites** button counts failed shifts as still
needing to go out, so it won't claim *All invites sent* while one is unsent.

**BitGigs stops after three refusals in a row.** A mail server that rejects one
message usually rejects the next thirty — a sending limit on your account, a
wrong password, a server that's down — and hammering it only makes things worse.
So when three messages in a row are refused on the same mail connection, the rest
of the queued batch is dropped rather than attempted: those shifts are marked as
failed invites with *“Skipped …”* as the reason, and nothing further is sent on
that connection.

It gets out of the way as soon as you do something about it. Anything you send
**after** those failures — a retry, another press of Send invites, a test message
on the Email tab — is always attempted, and the first success clears the state
completely. There's nothing to reset by hand.

If a send ever fails, it's caught and logged — it will **never** block you from
saving, approving or deleting a shift. BitGigs ignores any replies or RSVPs to
the invites.

#### When the *cancellation* is what failed

Deleting an invited shift sends a **withdrawal** to whoever holds it. That send
can be refused just like any other — and when it is, the shift is still deleted.
Deleting is a decision about *your* records; it never depends on an e-mail
getting through, and the shift will not reappear.

What's left undone is on the other side: your recipient still has an event in
their calendar for a shift that no longer exists. Because the shift is gone,
there's no chip to click and no **Send invites** sweep that can pick it up — so
the failed row on **Settings → Jobs** is the only trace, and its **Retry** button
is the only way to actually withdraw the event. Retry it once the underlying
problem is fixed; if you'd rather sort it out in your calendar app or by telling
the person directly, **Clear failed** dismisses it instead. Clearing is *not*
retrying — it only says you've seen it.

Since a refused withdrawal is a refused e-mail like any other, it also shows up in
the **Email activity log** and raises the red banner on your dashboard.

#### When a task gets stuck

A task is marked *Running* the moment the scheduler picks it up. If that process
then stops — a restart, a crash, a machine reboot — the row is left saying
**Running** for something that isn't running at all.

BitGigs sorts this out by itself: once a task has sat there far longer than any
real send would take, the next scheduler to start marks it **failed** with a
timeout, and whatever was waiting on it is put right (an invite that never left
the building goes back to *not sent*, so the month's **Send invites** button
offers it again). The row shows as **Stalled** in the meantime.

That clean-up needs a scheduler running to do it, though — and "no scheduler" is
exactly the situation that strands a task. So any row still waiting or running
carries a **Cancel** button on **Settings → Jobs**: pressing it gives up on that
task and records it as failed, which puts **Retry** and **Clear failed** back
within reach. Cancelling doesn't stop a send already in flight, so use it for a
row that's plainly gone nowhere.

### Changing a work or personal e-mail

A calendar invite lives in the recipient's calendar, and BitGigs remembers which
address each invite was last sent to. So if you change a contract's **work
e-mail**, or your **personal calendar address**, the invites you already sent
still point at the *old* mailbox — old address keeps the events, new address has
none.

BitGigs doesn't move them silently. After such a change, the **Calendar** tab
shows a **“N calendar invites still point at an old address”** notice (and saving
a contract nudges you there). Press **Review & sync** to open a summary that lists
exactly what will change — for each affected shift, which address the event is
**withdrawn from** and which it's **sent to** — so nothing happens until you
confirm. Pressing **Sync now** then sends a **cancellation** to each dropped
address and re-sends the event to the current one, showing a live status as it
works. It only ever touches invites whose address actually changed; everything
already correct is left alone. Turning a contract's invites **off** and syncing
withdraws that contract's events too.

## "Accepted" is not "delivered"

Every invite is recorded in the **Email log** (Email tab) just like any other
message, and a failed send raises the red banner on your dashboard. But bear in
mind the same caveat that applies to all mail: a result of **Accepted** means
the mail server *took* the message — it is **not** proof it reached anyone's
inbox. A wrong address can bounce back minutes later. If a colleague says they
never got an invite, check the address and re-send by editing the shift.

Recovery and console notes for the underlying mail connection live in
[Email & password reset](/help/email-and-password-reset/).
