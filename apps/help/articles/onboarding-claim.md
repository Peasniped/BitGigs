---
title: Claiming the instance
slug: onboarding-claim
summary: The setup key proves you own this BitGigs server before an account exists.
parent: first-time-setup
audience: public
order: 1
published: true
keywords: [claim, setup key, key, instance, fresh install, owner, server log, regenerate]
pages: [core:onboarding-account]
---
A fresh BitGigs install has no owner yet — so whoever reached this page first
would get to create the owner account. The **setup key** closes that gap: only
the person who can read the server's own files or log can know it, which
proves you're the one who installed BitGigs.

## Where to find the key

When this page is first opened, the key is

- printed in the **server log** (framed in a box, hard to miss), and
- written to **`instance/setup_key.txt`** next to the database.

Paste it in and you're through — you only ever enter it once; after that this
browser session is trusted for the rest of account creation.

## Good to know

- Worried the key was seen by someone else? Regenerate it from the server:
  `python manage.py setup_key --regenerate`.
- The key file is **deleted automatically** once the owner account exists —
  and this page stops existing too. From then on there's nothing here to claim.
