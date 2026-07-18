---
title: Settings & sign-in
slug: settings-and-sign-in
summary: Display preferences and how you sign in to BitGigs.
parent:
audience: everyone
order: 70
published: true
keywords: [settings, preferences, password, sso, authentik, sign in]
pages: [core:settings]
---
## Display preferences

- **Colour shifts by type** — tint calendar chips by shift type.
- **Use planned shifts** — let analytics project future months from your
  planned shifts (on by default).

## Sign-in

BitGigs works standalone with a **password**, and can optionally link an
**Authentik / OIDC** identity. One rule always holds: **at least one way in must
survive** — you can only turn the password off while an identity is linked, and
only unlink the identity while a usable password exists.

> There's no email server, so password recovery is done from the command line
> (`manage.py changepassword`). The login page's "Forgot your password?" note
> says the same.
