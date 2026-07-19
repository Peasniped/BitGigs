---
title: Settings & sign-in
slug: settings-and-sign-in
summary: Display preferences and how you sign in to BitGigs.
parent:
audience: everyone
order: 70
published: true
keywords: [settings, preferences, password, sso, oidc, authentik, sign in, theme, dark mode, accent, colour, color]
pages: [core:settings]
---
## Display preferences

- **[Theme](/settings/?tab=display#div_id_theme)** — Light, Dark, or **Auto**
  (follows your operating system, switching live when it does). There's also a
  one-tap **Dark mode / Light mode** toggle in the **More** menu; while Auto is
  active that menu item instead links back to this setting.
- **[Accent colour](/settings/?tab=display#div_id_accent_color_picker)** — one
  colour drives the whole app: buttons, links, tints, gradients and focus
  rings. Pick a preset swatch, use the colour wheel, or type a hex value — the
  page previews the colour live, and **Save** makes it stick. *Reset to
  default* returns to BitGigs indigo. (Charts keep their fixed
  actual/planned/projected colours so their meaning never changes.)
- **Colour shifts by type** — tint calendar chips by shift type.
- **Use planned shifts** — let analytics project future months from your
  planned shifts (on by default).

## Sign-in

BitGigs works standalone with a **password**, and can optionally link an identity
from **any OpenID Connect provider** (Authentik, Keycloak, Auth0, …). One rule
always holds: **at least one way in must survive** — you can only turn the
password off while an identity is linked, and only unlink the identity while a
usable password exists.

> Forgotten your password? If you've connected a mail server the login page can
> email you a reset link — see [Email & password reset](/help/email-and-password-reset/).
> Otherwise recovery is done from the command line (`manage.py changepassword`),
> which also stays available as the fallback when mail itself is broken.

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
