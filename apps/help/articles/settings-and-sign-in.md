---
title: Settings & sign-in
slug: settings-and-sign-in
summary: Display preferences and how you sign in to BitGigs.
parent:
audience: everyone
order: 70
published: true
keywords: [settings, preferences, password, sso, oidc, authentik, sign in]
pages: [core:settings]
---
## Display preferences

- **Colour shifts by type** — tint calendar chips by shift type.
- **Use planned shifts** — let analytics project future months from your
  planned shifts (on by default).

## Sign-in

BitGigs works standalone with a **password**, and can optionally link an identity
from **any OpenID Connect provider** (Authentik, Keycloak, Auth0, …). One rule
always holds: **at least one way in must survive** — you can only turn the
password off while an identity is linked, and only unlink the identity while a
usable password exists.

> There's no email server, so password recovery is done from the command line
> (`manage.py changepassword`). The login page's "Forgot your password?" note
> says the same.

### Naming the sign-in button

Single sign-on is set up in `.env` (`OIDC_SERVER_URL`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET`) and takes effect after a restart. Until you say otherwise
the button just reads **SSO** — correct for every provider, branded for none.

To brand it:

- `OIDC_PROVIDER_BRAND=authentik` — one line, gives Authentik's own icon and colour.
- `OIDC_PROVIDER_NAME`, `OIDC_PROVIDER_COLOR`, `OIDC_PROVIDER_ICON` — set your
  own. For the icon, drop an SVG or PNG into `assets/static/graphics/` and point
  the variable at it (e.g. `graphics/my_idp.svg`).

The label colour is chosen automatically so it stays readable on whatever colour
you pick, and your own icon is used exactly as supplied — never recoloured.
