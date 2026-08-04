---
title: Reading a calendar into planning
slug: calendar-overlay
summary: Overlay a personal calendar's busy times on the planning grid so you don't double-book yourself.
parent: calendar-integration
audience: everyone
order: 10
published: true
keywords: [overlay, busy, show my calendar, subscription, ical url, secret address, encrypted url, external calendar, clash, planning clash, google calendar, fastmail, icloud, refresh]
pages: [calendar_view:planning]
---
Add a calendar under **Settings → Calendar → Calendars you read**. You need its
private **iCal (`.ics`) URL** — in Google Calendar it's *Settings → your calendar
→ Secret address in iCal format*; Fastmail, iCloud and Outlook have an
equivalent "subscribe" or "secret" link.

Give it a **name** and a **colour**, paste the URL, save. You can add several
(yourself, a partner, …), each with its own colour.

> That URL is a secret — treat it like a password. BitGigs fetches it **on the
> server** and stores it **encrypted**; it never reaches your browser.

Press **↻** on a row to fetch it now and see how many events it found, or the
error if something's wrong. The row shows when it was last checked.

## Seeing it while planning

On the [planning calendar](/help/planning-calendar/) a **Show my calendar**
button appears once you've added at least one calendar. Turn it on and your busy
times appear as muted, striped **read-only** chips — they can't be dragged or
edited, they're context only.

Because they use the same time shape as shifts, the planner's
**overlap warning** picks them up: plan a shift over a busy block and both turn
amber.

Turning the overlay on also reveals **one slider per calendar** beneath the
button. These are the *same* on/off switches as Settings → Calendar, so a
calendar you hide here stays hidden everywhere until you turn it back on — handy
for planning against just one calendar without leaving the page.

## Refreshing

Switching the toggle **on** is the only thing that fetches a fresh copy. After
that the events are cached for the rest of your browser session, so reloads and
month navigation reuse them. Want the latest? Toggle it **off and on again**.

Invites BitGigs sent itself are filtered out of the overlay, so a shift you
invited yourself to never reads as clashing with itself.
