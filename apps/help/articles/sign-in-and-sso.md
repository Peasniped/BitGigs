---
title: Sign-in & single sign-on
slug: sign-in-and-sso
summary: Your password, linking an identity provider, and the rule that keeps you from locking yourself out.
parent: settings-and-sign-in
audience: everyone
order: 10
published: true
keywords: [sign in, signin, login, password, change password, sso, oidc, authentik, keycloak, identity provider, link, unlink, locked out, display name, email, brand, button]
pages: [core:settings]
---
BitGigs works standalone with a **password**, and can optionally link an identity
from **any OpenID Connect provider** (Authentik, Keycloak, Auth0, …).

The **Sign-in** tab is where you change your display name and email, set or
change your password, turn password sign-in off, or link and unlink an identity.

> **At least one way in must survive.** You can only turn the password off while
> an identity is linked, and only unlink the identity while a usable password
> exists. BitGigs enforces this — it won't let you strand yourself.

Changing your email doesn't break an existing link. Forgotten your password? See
[Email & password reset](/help/email-and-password-reset/); console recovery with
`manage.py changepassword` works even when mail doesn't.

## Setting up single sign-on

SSO is configured in `.env` — `OIDC_SERVER_URL`, `OIDC_CLIENT_ID`,
`OIDC_CLIENT_SECRET` — and takes effect after a restart. Leave them unset and
BitGigs is exactly as it was: password login, no SSO button, no provider needed.

Register `/accounts/oidc/sso/login/callback/` as the redirect URI at your
provider. An identity coming in is never accepted silently: BitGigs shows you the
name, email and ID it received on a **confirm page** first, so the wrong provider
account can't quietly become the owner.

### Naming the button

Until you say otherwise the button just reads **SSO** — correct for every
provider, branded for none.

- `OIDC_PROVIDER_BRAND=authentik` — one line, gives Authentik's own icon and colour.
- `OIDC_PROVIDER_NAME`, `OIDC_PROVIDER_COLOR`, `OIDC_PROVIDER_ICON` — set your
  own. For the icon, drop an SVG or PNG into `assets/static/graphics/` and point
  the variable at it (e.g. `graphics/my_idp.svg`).

The label colour is chosen automatically so it stays readable on whatever colour
you pick, and your own icon is used exactly as supplied — never recoloured.
