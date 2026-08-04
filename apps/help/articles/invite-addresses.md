---
title: Changing an email address
slug: invite-addresses
summary: Moving invites that already sit in someone's calendar to a new address.
parent: calendar-integration
audience: everyone
order: 40
published: true
keywords: [change email, move invites, old address, review and sync, sync now, wrong address, personal calendar address, work email]
pages: []
---
A calendar invite lives in the recipient's calendar, and BitGigs remembers which
address each one was last sent to. So if you change a contract's **work email**,
or your **personal calendar address**, the invites you already sent still point
at the *old* mailbox — the old address keeps the events, the new one has none.

BitGigs doesn't move them silently. After such a change the **Calendar** tab
shows a **“N calendar invites still point at an old address”** notice, and saving
a contract nudges you there.

Press **Review & sync** for a summary listing exactly what will change — for each
affected shift, which address the event is **withdrawn from** and which it's
**sent to**. Nothing happens until you confirm. **Sync now** then sends a
cancellation to each dropped address and re-sends the event to the current one,
showing live status as it works.

It only ever touches invites whose address actually changed; everything already
correct is left alone. Turning a contract's invites **off** and syncing withdraws
that contract's events too.
