---
title: Settings & sign-in
slug: settings-and-sign-in
summary: Display preferences, switching features on and off, and how you sign in to BitGigs.
parent:
audience: everyone
order: 70
published: true
keywords: [settings, preferences, password, sso, oidc, authentik, sign in, theme, dark mode, accent, colour, color, features, turn off, hide, disable, payroll, vacation, commuting, analytics]
pages: [core:settings]
---
## Display preferences

- **Colour shifts by type** — tint calendar chips by shift type.
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

## Features

BitGigs covers more ground than most people need. The **Features** tab is where
you switch off the parts you don't use — each one gets a card with a switch and a
plain description of what goes away:

- **Payroll periods** — generated periods and the payslip editor.
- **Vacation & feriepenge** — the holiday-pay overview.
- **Commuting** — commuting days for the transport deduction.
- **Analytics** — income projection and rate history.

Switching one off does two things: its menu entry disappears, and its pages stop
opening. That second part matters — a bookmark or an old link would otherwise
still walk you into a page you'd turned off. If you follow one anyway, BitGigs
takes you to the dashboard and says which feature is off.

**Nothing is deleted.** A switch only changes what you can *reach*; your shifts,
payslip lines and commuting days stay exactly where they are, and turning it back
on brings the pages back unchanged. So there's no risk in trying it.

A feature that has settings of its own keeps them here, on its own card, so its
on/off switch and its behaviour sit together:

- **Projection method** and **trailing months** — how Analytics estimates future
  hours from your history.
- **Use planned shifts** — let Analytics use your planned shifts for a future
  month instead of the trailing average (on by default).

Those fold away when Analytics is switched off, but they're remembered — turn it
back on and it's configured exactly as you left it.

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
