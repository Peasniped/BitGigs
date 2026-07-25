---
title: Calendar integration
slug: calendar-integration
summary: Overlay a personal calendar on the planning grid, and email shifts out as calendar invites.
parent: settings-and-sign-in
audience: everyone
order: 78
published: true
keywords: [calendar, ical, ics, subscription, overlay, busy, invite, invitation, invites, colleagues, sync, planning clash, feed, webcal, method request, sequence, cancel, test invite, encrypted url]
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

Invites are then configured **per contract**, where you set up the job. When you
**create a contract** — or set up your first workplace during onboarding — you're
asked **Activate calendar invites for shifts on this contract?** and must pick
**Yes** or **No** (you can always change it later). Picking **Yes**, or opening an
existing contract to **Edit** it (Workplaces → a workplace → **Edit** a contract,
or the **Edit** button on the Calendar tab's per-contract overview), reveals the
fields: a **work e-mail address** and an **on-site location** (both required),
then three **override** toggles for the on-site title, remote title and remote
location — each shows an input inline only when you turn it on, otherwise it uses
your global default. Only **on-site** and **remote** shifts generate invites; sick
leave, vacation and paid absence don't.

Invites won't actually send until your **Email** connection is set up and the
master switch is on, so the form tells you when something's still missing. During
onboarding that's just a heads-up — you set up email afterwards, and your choices
here are saved either way.

### Activating and keeping them current

Invites aren't sent automatically the moment you plan a shift — you send them
deliberately. On the planning calendar, press **Send invites** to email invites
for the planned shifts on screen. Shifts that already have an invite are skipped,
and an invited shift shows a small **envelope marker** with a blue ring.

Once a shift has an invite, BitGigs keeps it current for you:

- **Edit** the shift (time, type, from any screen) → an updated invite is
  re-sent automatically.
- **Approve** a planned shift → the same event carries over to the approved
  shift; it's updated, not duplicated.
- **Delete** the shift → a cancellation is sent and the event is withdrawn.

If a send ever fails, it's caught and logged — it will **never** block you from
saving, approving or deleting a shift. BitGigs ignores any replies or RSVPs to
the invites.

## "Accepted" is not "delivered"

Every invite is recorded in the **Email log** (Email tab) just like any other
message, and a failed send raises the red banner on your dashboard. But bear in
mind the same caveat that applies to all mail: a result of **Accepted** means
the mail server *took* the message — it is **not** proof it reached anyone's
inbox. A wrong address can bounce back minutes later. If a colleague says they
never got an invite, check the address and re-send by editing the shift.

Recovery and console notes for the underlying mail connection live in
[Email & password reset](/help/email-and-password-reset/).
